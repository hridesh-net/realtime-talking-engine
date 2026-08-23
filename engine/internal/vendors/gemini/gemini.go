// Package gemini implements the Speaker port over the Gemini Live API.
//
// This is the persona's mouth: a realtime speech-to-speech session that always
// owns the voice. The reasoning half of the persona lives elsewhere
// (vendors/thinkerllm) and reaches this one only through InjectSystemItem.
//
// # Why this speaks the wire protocol directly
//
// The plan's D3 chose the official genai SDK for this adapter. That decision is
// reversed here, and the reversal is recorded rather than quietly taken:
//
//   - The SDK requires Go 1.24 while this module targets 1.23, so adopting it
//     is also a toolchain bump and a change to the deployment image.
//   - It pulls in gRPC and protobuf to reach an API that is JSON over a
//     WebSocket. That is a large dependency surface inside a real-time audio
//     binary.
//   - The repo already calls this vendor by hand for the reasoning adapters
//     (vendors/shared/geminijson). Adopting the SDK here without migrating
//     those leaves two ways to call one vendor — the outcome D3 itself named as
//     the thing to avoid.
//   - D3's own first task was to check whether the SDK could be pointed at a
//     local endpoint, because an adapter that cannot be tested offline is the
//     riskiest package in the build. Speaking the protocol directly makes the
//     endpoint a plain field, so the whole adapter — reconnect included — runs
//     against a local WebSocket in the offline suite.
//
// The protocol shapes in wire.go were exercised against the live API rather
// than transcribed from documentation.
package gemini

import (
	"context"
	"fmt"
	"log/slog"
	"net/http"
	"time"

	"github.com/coder/websocket"

	"skillbrew/engine/internal/ports"
)

// DefaultEndpoint is the Live API's bidirectional WebSocket.
const DefaultEndpoint = "wss://generativelanguage.googleapis.com/ws/" +
	"google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"

// InputRateHz and OutputRateHz are the rates this vendor fixes.
//
// They are not configurable because they are not ours to choose: the API
// accepts 16 kHz PCM16 in and emits 24 kHz PCM16 out. The transport resamples
// to meet them.
const (
	InputRateHz  = 16000
	OutputRateHz = 24000
)

// readLimit bounds one incoming WebSocket message. Audio chunks observed live
// run to a few tens of kilobytes; this is far above that and still refuses a
// response that would exhaust the process.
const readLimit = 1 << 24

// Speaker opens Gemini Live sessions.
type Speaker struct {
	modelID  string
	apiKey   string
	endpoint string
	logger   *slog.Logger
	dialer   *http.Client
}

var _ ports.Speaker = (*Speaker)(nil)

// Option configures a Speaker.
type Option func(*Speaker)

// WithEndpoint overrides the API endpoint, which is what lets the whole
// adapter run against a local WebSocket in the offline suite.
func WithEndpoint(url string) Option { return func(s *Speaker) { s.endpoint = url } }

// WithHTTPClient injects the client used for the WebSocket handshake.
func WithHTTPClient(c *http.Client) Option { return func(s *Speaker) { s.dialer = c } }

// New builds a Speaker. The model id is config, never a literal here.
func New(modelID, apiKey string, logger *slog.Logger, opts ...Option) *Speaker {
	if logger == nil {
		logger = slog.Default()
	}
	s := &Speaker{
		modelID:  modelID,
		apiKey:   apiKey,
		endpoint: DefaultEndpoint,
		logger:   logger,
	}
	for _, o := range opts {
		o(s)
	}
	return s
}

// Start opens one realtime session and blocks until the vendor has confirmed
// setup, so a caller that gets a session back has one that is ready to use.
func (s *Speaker) Start(ctx context.Context, cfg ports.SessionCfg) (ports.SpeakerSession, error) {
	sess := &session{
		speaker: s,
		cfg:     cfg,
		logger:  s.logger.With("session_id", cfg.SessionID),
		events:  make(chan ports.SpeakerEvent, eventBuffer),
		writes:  make(chan clientMessage, writeBuffer),
		closed:  make(chan struct{}),
		setupOK: make(chan struct{}),
		runDone: make(chan struct{}),
	}
	if err := sess.connect(ctx, ""); err != nil {
		return nil, err
	}
	// Deliberately not ctx: this goroutine owns the session for the whole
	// interview, and ctx bounds only the connect. Tying the session's life to
	// it would tear down the persona's mouth the moment setup returned.
	// Shutdown is driven by Close, which run selects on.
	//nolint:gosec // G118: the session must outlive the context that started it.
	go sess.run()

	select {
	case <-sess.setupOK:
		return sess, nil
	case <-sess.closed:
		return nil, fmt.Errorf("gemini: session ended before setup completed")
	case <-ctx.Done():
		_ = sess.Close(context.WithoutCancel(ctx))
		return nil, ctx.Err()
	case <-time.After(setupTimeout):
		_ = sess.Close(context.WithoutCancel(ctx))
		return nil, fmt.Errorf("gemini: vendor did not confirm setup within %v", setupTimeout)
	}
}

// dial opens the socket. Split out so reconnect uses exactly the same path as
// the first connection — a reconnect that differs from the original is a
// reconnect nobody tests.
func (s *Speaker) dial(ctx context.Context) (*websocket.Conn, error) {
	url := s.endpoint + "?key=" + s.apiKey
	ws, resp, err := websocket.Dial(ctx, url, &websocket.DialOptions{HTTPClient: s.dialer})
	if resp != nil && resp.Body != nil {
		_ = resp.Body.Close()
	}
	if err != nil {
		return nil, fmt.Errorf("gemini: dial: %w", err)
	}
	ws.SetReadLimit(readLimit)
	return ws, nil
}
