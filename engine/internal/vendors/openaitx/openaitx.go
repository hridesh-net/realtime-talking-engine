// Package openaitx implements the OpenAI Realtime transcription-session
// Transcriber adapter.
package openaitx

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"log/slog"
	"net/http"
	"sync"
	"time"

	"github.com/coder/websocket"

	"skillbrew/engine/internal/audio"
	"skillbrew/engine/internal/ports"
)

// DefaultEndpoint is the OpenAI Realtime WebSocket endpoint. The
// transcription intent selects a transcription-only session rather than a
// speech model that can also answer.
const DefaultEndpoint = "wss://api.openai.com/v1/realtime?intent=transcription"

const (
	inputRateHz  = 24000
	eventBuffer  = 64
	writeBuffer  = 64
	setupTimeout = 10 * time.Second
)

// Transcriber opens independent streaming ASR sessions. It deliberately does
// not share the Speaker's connection: ASR failure is non-fatal and the
// Speaker's own input transcript remains the actor's fallback.
type Transcriber struct {
	modelID  string
	apiKey   string
	endpoint string
	logger   *slog.Logger
	dialer   *http.Client

	mu      sync.Mutex
	session *transcriptionSession
}

var _ ports.Transcriber = (*Transcriber)(nil)

// Option configures a Transcriber.
type Option func(*Transcriber)

// WithEndpoint overrides the vendor endpoint, allowing offline WebSocket
// tests and private-compatible deployments.
func WithEndpoint(endpoint string) Option {
	return func(t *Transcriber) { t.endpoint = endpoint }
}

// WithHTTPClient injects the HTTP client used for the WebSocket handshake.
func WithHTTPClient(client *http.Client) Option {
	return func(t *Transcriber) { t.dialer = client }
}

// New builds an OpenAI transcription adapter. The model id is configuration,
// never a vendor default in this package.
func New(modelID, apiKey string, logger *slog.Logger, opts ...Option) *Transcriber {
	if logger == nil {
		logger = slog.Default()
	}
	t := &Transcriber{
		modelID:  modelID,
		apiKey:   apiKey,
		endpoint: DefaultEndpoint,
		logger:   logger,
	}
	for _, opt := range opts {
		opt(t)
	}
	return t
}

// Start opens a transcription-only Realtime session and sends its setup
// message before returning. The session then owns one reader and one writer
// goroutine for the lifetime of the interview.
func (t *Transcriber) Start(ctx context.Context) error {
	ws, resp, err := websocket.Dial(ctx, t.endpoint, &websocket.DialOptions{
		HTTPClient: t.dialer,
		HTTPHeader: http.Header{
			"Authorization": []string{"Bearer " + t.apiKey},
		},
	})
	if resp != nil && resp.Body != nil {
		_ = resp.Body.Close()
	}
	if err != nil {
		return fmt.Errorf("openaitx: dial: %w", err)
	}

	s := &transcriptionSession{
		parent:   t,
		ws:       ws,
		partials: make(chan ports.Partial, eventBuffer),
		writes:   make(chan []byte, writeBuffer),
		closed:   make(chan struct{}),
		done:     make(chan struct{}),
		ready:    make(chan error, 1),
	}
	if err := s.writeSetup(ctx); err != nil {
		_ = ws.CloseNow()
		return fmt.Errorf("openaitx: send setup: %w", err)
	}

	t.mu.Lock()
	if t.session != nil {
		t.mu.Unlock()
		_ = ws.CloseNow()
		return fmt.Errorf("openaitx: session already started")
	}
	t.session = s
	t.mu.Unlock()

	go s.run()
	setupCtx, cancel := context.WithTimeout(ctx, setupTimeout)
	defer cancel()
	select {
	case err := <-s.ready:
		if err != nil {
			s.stop()
			<-s.done
			return fmt.Errorf("openaitx: setup: %w", err)
		}
		return nil
	case <-setupCtx.Done():
		s.stop()
		<-s.done
		return fmt.Errorf("openaitx: wait for setup: %w", setupCtx.Err())
	}
}

// SendAudio appends one PCM16 frame to the vendor's input buffer. OpenAI's
// transcription session accepts 24 kHz PCM; other engine rates are converted
// with the stateful engine resampler so frame boundaries do not click or
// change the sample phase.
func (t *Transcriber) SendAudio(ctx context.Context, frame ports.Frame) error {
	t.mu.Lock()
	s := t.session
	t.mu.Unlock()
	if s == nil {
		return fmt.Errorf("openaitx: send audio before Start")
	}
	return s.sendAudio(ctx, frame)
}

// Partials returns cumulative revisions for an in-progress item and one final
// partial when the vendor completes it. Cumulative text is important because
// the actor replaces the current utterance on each revision.
func (t *Transcriber) Partials() <-chan ports.Partial {
	t.mu.Lock()
	defer t.mu.Unlock()
	if t.session == nil {
		return nil
	}
	return t.session.partials
}

// Close stops the session and waits for both its reader and writer to exit.
// It is safe to call when Start failed or was never called.
func (t *Transcriber) Close(ctx context.Context) error {
	t.mu.Lock()
	s := t.session
	t.mu.Unlock()
	if s == nil {
		return nil
	}
	s.stop()
	select {
	case <-s.done:
		return nil
	case <-ctx.Done():
		return ctx.Err()
	}
}

type transcriptionSession struct {
	parent   *Transcriber
	ws       *websocket.Conn
	partials chan ports.Partial
	writes   chan []byte
	closed   chan struct{}
	done     chan struct{}
	ready    chan error

	closeOnce    sync.Once
	writeMu      sync.Mutex
	resampler    *audio.Resampler
	resampleRate int
}

// writeSetup sends the GA Realtime session shape. Verified live on
// 2026-09-12: the beta `transcription_session.update` event and the
// `OpenAI-Beta: realtime=v1` header are rejected outright ("The Realtime Beta
// API is no longer supported"), so everything here is the `session.update`
// form with the transcription settings nested under `audio.input`.
func (s *transcriptionSession) writeSetup(ctx context.Context) error {
	msg := sessionUpdate{
		Type: "session.update",
		Session: sessionConfig{
			Type: "transcription",
			Audio: sessionAudio{
				Input: sessionAudioInput{
					Format:        audioFormat{Type: "audio/pcm", Rate: inputRateHz},
					Transcription: transcriptionConfig{Model: s.parent.modelID},
					TurnDetection: turnDetection{Type: "server_vad"},
				},
			},
		},
	}
	b, err := json.Marshal(msg)
	if err != nil {
		return fmt.Errorf("marshal setup: %w", err)
	}
	if err := s.ws.Write(ctx, websocket.MessageText, b); err != nil {
		return fmt.Errorf("write setup: %w", err)
	}
	return nil
}

func (s *transcriptionSession) sendAudio(ctx context.Context, frame ports.Frame) error {
	if frame.SampleRateHz <= 0 {
		return fmt.Errorf("openaitx: invalid sample rate %d", frame.SampleRateHz)
	}
	if len(frame.PCM) == 0 {
		return nil
	}
	s.writeMu.Lock()
	if s.resampleRate != frame.SampleRateHz {
		resampler, err := audio.NewResampler(frame.SampleRateHz, inputRateHz)
		if err != nil {
			s.writeMu.Unlock()
			return fmt.Errorf("openaitx: create resampler: %w", err)
		}
		s.resampler = resampler
		s.resampleRate = frame.SampleRateHz
	}
	pcm := s.resampler.Process(frame.PCM)
	encoded := base64.StdEncoding.EncodeToString(pcm)
	s.writeMu.Unlock()

	b, err := json.Marshal(audioAppend{Type: "input_audio_buffer.append", Audio: encoded})
	if err != nil {
		return fmt.Errorf("openaitx: marshal audio: %w", err)
	}
	select {
	case s.writes <- b:
		return nil
	case <-s.closed:
		return fmt.Errorf("openaitx: session closed")
	case <-ctx.Done():
		return ctx.Err()
	}
}

func (s *transcriptionSession) run() {
	var wg sync.WaitGroup
	wg.Add(2)
	go func() {
		defer wg.Done()
		s.writeLoop()
	}()
	go func() {
		defer wg.Done()
		s.readLoop()
	}()
	wg.Wait()
	close(s.partials)
	close(s.done)
}

func (s *transcriptionSession) writeLoop() {
	for {
		select {
		case <-s.closed:
			return
		case b := <-s.writes:
			ctx := context.Background()
			if err := s.ws.Write(ctx, websocket.MessageText, b); err != nil {
				s.parent.logger.Warn("openaitx: write failed", "err", err)
				s.stop()
				return
			}
		}
	}
}

func (s *transcriptionSession) readLoop() {
	texts := make(map[string]string)
	ready := false
	for {
		_, b, err := s.ws.Read(context.Background())
		if err != nil {
			if !ready {
				s.signalReady(fmt.Errorf("read setup response: %w", err))
			}
			select {
			case <-s.closed:
			default:
				s.parent.logger.Warn("openaitx: read failed", "err", err)
			}
			s.stop()
			return
		}
		var ev serverEvent
		if err := json.Unmarshal(b, &ev); err != nil {
			s.parent.logger.Warn("openaitx: invalid event", "err", err)
			continue
		}
		switch ev.Type {
		case "session.created", "session.updated", "transcription_session.created":
			if !ready {
				ready = true
				s.signalReady(nil)
			}
		case "conversation.item.input_audio_transcription.delta":
			if ev.ItemID == "" || ev.Delta == "" {
				continue
			}
			texts[ev.ItemID] += ev.Delta
			if !s.emit(ports.Partial{Text: texts[ev.ItemID], ItemID: ev.ItemID}) {
				return
			}
		case "conversation.item.input_audio_transcription.completed":
			if ev.ItemID == "" {
				continue
			}
			text := ev.Transcript
			if text == "" {
				text = texts[ev.ItemID]
			}
			if !s.emit(ports.Partial{Text: text, Final: true, ItemID: ev.ItemID}) {
				return
			}
			delete(texts, ev.ItemID)
		case "error":
			if !ready {
				s.signalReady(fmt.Errorf("vendor rejected setup: %s", ev.Error.Message))
			}
			s.parent.logger.Warn("openaitx: vendor error", "message", ev.Error.Message, "code", ev.Error.Code)
			s.stop()
			return
		}
	}
}

func (s *transcriptionSession) signalReady(err error) {
	select {
	case s.ready <- err:
	default:
	}
}

func (s *transcriptionSession) emit(p ports.Partial) bool {
	select {
	case s.partials <- p:
		return true
	case <-s.closed:
		return false
	}
}

func (s *transcriptionSession) stop() {
	s.closeOnce.Do(func() {
		close(s.closed)
		_ = s.ws.CloseNow()
	})
}

type sessionUpdate struct {
	Type    string        `json:"type"`
	Session sessionConfig `json:"session"`
}

type sessionConfig struct {
	Type  string       `json:"type"`
	Audio sessionAudio `json:"audio"`
}

type sessionAudio struct {
	Input sessionAudioInput `json:"input"`
}

type sessionAudioInput struct {
	Format        audioFormat         `json:"format"`
	Transcription transcriptionConfig `json:"transcription"`
	TurnDetection turnDetection       `json:"turn_detection"`
}

type audioFormat struct {
	Type string `json:"type"`
	Rate int    `json:"rate"`
}

type transcriptionConfig struct {
	Model string `json:"model"`
}

type turnDetection struct {
	Type string `json:"type"`
}

type audioAppend struct {
	Type  string `json:"type"`
	Audio string `json:"audio"`
}

type serverEvent struct {
	Type       string `json:"type"`
	ItemID     string `json:"item_id"`
	Delta      string `json:"delta"`
	Transcript string `json:"transcript"`
	Error      struct {
		Code    string `json:"code"`
		Message string `json:"message"`
	} `json:"error"`
}
