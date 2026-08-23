// Package wsfallback implements the WebSocket/PCM last-mile transport.
//
// It is the fallback for when WebRTC cannot be established — a corporate
// network that blocks UDP and has no reachable TURN relay, most commonly —
// and it is also the transport that works with no CGo and no ICE at all,
// which makes it the one an offline test can drive end to end.
//
// The trade it makes is explicit: raw PCM over a TCP WebSocket has no
// congestion control tuned for audio and no forward error correction, so a
// lossy path degrades into latency rather than into a glitch. That is the
// wrong failure mode for a real-time call, which is exactly why this is the
// fallback and not the primary. It is markedly better than no session.
package wsfallback

import (
	"context"
	"crypto/rand"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"sync"
	"time"

	"github.com/coder/websocket"

	"skillbrew/engine/internal/audio"
	"skillbrew/engine/internal/ports"
)

// Wire message types. One byte, because every audio frame carries it fifty
// times a second in each direction.
const (
	msgAudio = 0x01
)

// Buffer depths. Audio channels are shallow on purpose: a deep queue on a
// real-time path converts a slow consumer into latency that never recovers,
// where a shallow one converts it into a drop that does.
const (
	audioInBuffer    = 8
	heartbeatBuffer  = 4
	speechBuffer     = 8
	controlBuffer    = 8
	sendRingCapacity = 25 // half a second at 20 ms framing
)

// Config tunes the transport.
type Config struct {
	// MicRateHz is the rate mic audio is delivered at, after resampling.
	// Gemini Live wants 16 kHz input, so that is the default.
	MicRateHz int
	// PlaybackRateHz is the rate persona audio is sent to the browser at.
	// The Speaker vendor emits 24 kHz and the browser can resample, so the
	// default avoids a conversion nobody needs.
	PlaybackRateHz int
	// TicketTTL bounds how long an unclaimed ticket stays valid. A session
	// whose client never connects must not hold a registration forever.
	TicketTTL time.Duration
	// VAD tunes speech-onset detection on the mic stream.
	VAD audio.VADConfig
	// Jitter tunes the receive buffer.
	Jitter audio.JitterConfig
}

// DefaultConfig returns the tuning this engine ships with.
func DefaultConfig() Config {
	return Config{
		MicRateHz:      16000,
		PlaybackRateHz: 24000,
		TicketTTL:      2 * time.Minute,
		VAD:            audio.DefaultVADConfig(),
		Jitter:         audio.DefaultJitterConfig(),
	}
}

// Errors this transport reports to its caller.
var (
	// ErrBadOffer is an offer this transport cannot serve.
	ErrBadOffer = errors.New("wsfallback: unusable offer")
	// ErrUnknownTicket is a client connecting with a ticket that was never
	// issued, has already been claimed, or has expired.
	ErrUnknownTicket = errors.New("wsfallback: unknown or expired ticket")
	// ErrConnClosed is a send on a closed connection.
	ErrConnClosed = errors.New("wsfallback: connection closed")
)

// offer is what the browser sends to open a session.
type offer struct {
	Kind       string `json:"kind"`
	SampleRate int    `json:"sample_rate_hz"`
}

// answer is what it gets back: where to connect and what to send.
type answer struct {
	Kind           string `json:"kind"`
	Ticket         string `json:"ticket"`
	MicRateHz      int    `json:"mic_rate_hz"`
	PlaybackRateHz int    `json:"playback_rate_hz"`
	FrameMs        int    `json:"frame_ms"`
}

// Transport hands out tickets and binds arriving WebSockets to the
// MediaConn that was created for them.
//
// Accept and the HTTP upgrade are deliberately separate steps. The session
// actor needs a MediaConn the moment it accepts the offer — that is the port's
// contract — but the browser cannot connect until it has been told where to,
// which requires the answer to have been returned first. So Accept mints a
// conn that is real but not yet attached, and the socket binds to it later.
type Transport struct {
	cfg    Config
	logger *slog.Logger
	clock  ports.Clock

	mu      sync.Mutex
	pending map[string]*pendingConn
}

type pendingConn struct {
	conn      *Conn
	expiresAt time.Time
}

var _ ports.Transport = (*Transport)(nil)

// New builds a transport. A zero-valued config is replaced with the default.
func New(cfg Config, clock ports.Clock, logger *slog.Logger) *Transport {
	if cfg.MicRateHz <= 0 || cfg.PlaybackRateHz <= 0 {
		cfg = DefaultConfig()
	}
	if logger == nil {
		logger = slog.Default()
	}
	return &Transport{
		cfg:     cfg,
		logger:  logger,
		clock:   clock,
		pending: make(map[string]*pendingConn),
	}
}

// Accept registers a connection and returns the answer telling the client
// how to reach it.
//
// It performs no I/O, which is what the port promises callers who deliberately
// run it outside their vendor-connect timeout.
func (t *Transport) Accept(_ context.Context, offerBytes []byte) ([]byte, ports.MediaConn, error) {
	var o offer
	if err := json.Unmarshal(offerBytes, &o); err != nil {
		return nil, nil, fmt.Errorf("%w: %w", ErrBadOffer, err)
	}
	if o.Kind != "ws-pcm" {
		return nil, nil, fmt.Errorf("%w: kind %q, want \"ws-pcm\"", ErrBadOffer, o.Kind)
	}
	if o.SampleRate <= 0 {
		return nil, nil, fmt.Errorf("%w: sample_rate_hz must be positive", ErrBadOffer)
	}

	c, err := newConn(t.cfg, o.SampleRate, t.logger)
	if err != nil {
		return nil, nil, err
	}

	ticket, err := mintTicket()
	if err != nil {
		return nil, nil, err
	}

	t.mu.Lock()
	t.reapLocked()
	t.pending[ticket] = &pendingConn{conn: c, expiresAt: t.clock.Now().Add(t.cfg.TicketTTL)}
	t.mu.Unlock()

	c.onClose = func() { t.forget(ticket) }

	body, err := json.Marshal(answer{
		Kind:           "ws-pcm",
		Ticket:         ticket,
		MicRateHz:      t.cfg.MicRateHz,
		PlaybackRateHz: t.cfg.PlaybackRateHz,
		FrameMs:        int(t.cfg.Jitter.FrameDuration / time.Millisecond),
	})
	if err != nil {
		return nil, nil, fmt.Errorf("wsfallback: marshal answer: %w", err)
	}
	return body, c, nil
}

// ServeHTTP upgrades an arriving request and binds it to the connection its
// ticket names. Mount it at the media path named in the answer.
func (t *Transport) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	ticket := r.URL.Query().Get("ticket")

	t.mu.Lock()
	t.reapLocked()
	p, ok := t.pending[ticket]
	if ok {
		// A ticket is single-use. Leaving it valid would let a second
		// client attach to a live session's media path.
		delete(t.pending, ticket)
	}
	t.mu.Unlock()

	if !ok {
		http.Error(w, ErrUnknownTicket.Error(), http.StatusNotFound)
		return
	}

	ws, err := websocket.Accept(w, r, &websocket.AcceptOptions{
		// The engine and the UI are served from different origins in every
		// deployment this targets, and the ticket — not the origin — is
		// what authorizes the attach.
		InsecureSkipVerify: true,
	})
	if err != nil {
		t.logger.Warn("wsfallback: upgrade failed", "err", err)
		return
	}
	// Audio frames are small; the limit is generous for control JSON and
	// still refuses a client trying to buffer the process to death.
	ws.SetReadLimit(1 << 20)

	p.conn.attach(r.Context(), ws)
}

// forget drops a ticket, called when a conn closes before being claimed.
func (t *Transport) forget(ticket string) {
	t.mu.Lock()
	defer t.mu.Unlock()
	delete(t.pending, ticket)
}

// reapLocked drops expired tickets. Called on both paths that take the lock,
// so an abandoned offer cannot accumulate.
func (t *Transport) reapLocked() {
	now := t.clock.Now()
	for k, p := range t.pending {
		if now.After(p.expiresAt) {
			p.conn.expire()
			delete(t.pending, k)
		}
	}
}

// Pending reports how many unclaimed tickets are outstanding. Tests assert on
// it; it is also the number that says whether clients are failing to attach.
func (t *Transport) Pending() int {
	t.mu.Lock()
	defer t.mu.Unlock()
	return len(t.pending)
}

func mintTicket() (string, error) {
	var b [16]byte
	if _, err := rand.Read(b[:]); err != nil {
		return "", fmt.Errorf("wsfallback: mint ticket: %w", err)
	}
	return hex.EncodeToString(b[:]), nil
}

// maxItemIDLen bounds the item identifier carried with each outbound frame.
//
// The browser echoes this identifier back on every playout heartbeat, and the
// actor matches heartbeats to the in-flight item by it. A silently truncated
// identifier would therefore never match, and barge-in truncation would
// quietly fall back to assuming everything sent was heard — so the length is
// checked rather than cast.
const maxItemIDLen = 1<<16 - 1

// encodeAudio frames one outbound PCM buffer.
func encodeAudio(rate int, itemID string, pcm []byte) ([]byte, error) {
	if len(itemID) > maxItemIDLen {
		return nil, fmt.Errorf("wsfallback: item id of %d bytes exceeds the %d-byte frame field",
			len(itemID), maxItemIDLen)
	}
	if rate <= 0 {
		return nil, fmt.Errorf("wsfallback: refusing to send audio with sample rate %d", rate)
	}
	out := make([]byte, 0, audioHeaderLen+len(itemID)+len(pcm))
	out = append(out, msgAudio)
	var hdr [4]byte
	binary.BigEndian.PutUint32(hdr[:], uint32(rate)) //nolint:gosec // guarded positive just above
	out = append(out, hdr[:]...)
	var idLen [2]byte
	binary.BigEndian.PutUint16(idLen[:], uint16(len(itemID))) //nolint:gosec // bounded by maxItemIDLen above
	out = append(out, idLen[:]...)
	out = append(out, itemID...)
	return append(out, pcm...), nil
}

// audioHeaderLen is the fixed part of an outbound audio message: the type
// byte, the sample rate, and the item-id length.
const audioHeaderLen = 1 + 4 + 2

// decodeAudio parses one inbound audio message: sequence, rate, samples.
func decodeAudio(msg []byte) (seq uint32, rate int, pcm []byte, err error) {
	const header = 1 + 4 + 4
	if len(msg) < header || msg[0] != msgAudio {
		return 0, 0, nil, fmt.Errorf("wsfallback: malformed audio message of %d bytes", len(msg))
	}
	seq = binary.BigEndian.Uint32(msg[1:5])
	rate = int(binary.BigEndian.Uint32(msg[5:9]))
	if rate <= 0 {
		return 0, 0, nil, fmt.Errorf("wsfallback: audio message declares sample rate %d", rate)
	}
	return seq, rate, msg[header:], nil
}
