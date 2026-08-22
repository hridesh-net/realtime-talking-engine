package ports

import (
	"context"
	"time"
)

// Frame is one decoded PCM16 mono audio frame at a fixed sample rate,
// tagged with a presentation timestamp for recording alignment and drift
// reconciliation. It is the common audio unit crossing every port boundary
// (Transport, Speaker, Transcriber, TTS) so no port needs to import
// internal/audio's richer PCM types.
type Frame struct {
	// PCM holds little-endian PCM16 mono samples.
	PCM []byte
	// SampleRateHz is the sample rate of PCM, e.g. 48000, 24000, or 16000.
	SampleRateHz int
	// Timestamp is the frame's presentation time on the session's media
	// clock, used for recording alignment and drift reconciliation.
	Timestamp time.Time
}

// ControlMessage is an out-of-band message on a MediaConn's data channel:
// start/stop signalling, playout heartbeats' sibling control-plane traffic.
type ControlMessage struct {
	Kind    string
	Payload []byte
}

// PlayoutHeartbeat reports how much of a persona response item the browser
// has actually played, on its own clock. The session actor uses the latest
// heartbeat (newest-wins) to extrapolate heardMs for truncation on
// barge-in — never bytes sent, which does not reflect what was heard.
type PlayoutHeartbeat struct {
	ItemID  string
	HeardMs int
	At      time.Time
}

// Transport accepts an incoming media connection offer and returns a
// MediaConn for it. Implementations: transport/webrtc (Pion), the primary
// path, and transport/wsfallback, auto-selected on ICE failure.
type Transport interface {
	// Accept negotiates a new connection from a client offer (e.g. a WebRTC
	// SDP offer) and returns the resulting MediaConn.
	Accept(ctx context.Context, offer []byte) (MediaConn, error)
}

// MediaConn is one open last-mile media connection to a browser.
type MediaConn interface {
	// AudioIn returns decoded, jitter-buffered mic frames from the human
	// interviewer.
	AudioIn() <-chan Frame
	// SendAudio sends one persona audio frame to the browser.
	SendAudio(ctx context.Context, frame Frame) error
	// Control is the bidirectional data-channel control stream.
	Control() chan ControlMessage
	// PlayoutHeartbeats returns the browser's periodic playout reports.
	PlayoutHeartbeats() <-chan PlayoutHeartbeat
	// Close tears down the connection.
	Close(ctx context.Context) error
}
