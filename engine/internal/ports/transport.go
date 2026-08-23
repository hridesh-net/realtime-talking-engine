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
//
// ItemID must be the same identifier the browser was sent on the AudioDelta
// it is reporting playout for — i.e. AudioDelta.ItemID, not ResponseID. The
// browser has to echo back exactly what it was given for the newest-wins
// match against the in-flight item to land on the right item.
type PlayoutHeartbeat struct {
	ItemID  string
	HeardMs int
	At      time.Time
}

// VADEvent is a speech-onset signal detected locally on the human
// interviewer's mic audio, independent of any vendor VAD.
//
// The engine owns turn boundaries because vendor automatic VAD is disabled
// — verified live: with automaticActivityDetection.disabled, the model
// correctly does not answer until the engine sends activityEnd. VADEvent
// carries speech onset only: it drives the vendor activity signal and
// barge-in candidacy. End-of-turn detection remains the Transcriber's job —
// an energy threshold cannot distinguish a thinking pause from a finished
// question, and the interviewer is a manager composing a question, for whom
// 1-2 second mid-question pauses are normal. Energy-based end-of-turn is the
// degraded fallback only.
type VADEvent struct {
	// Started is true for speech onset.
	Started bool
	// EnergyDB is the detected signal energy, in decibels, at At.
	EnergyDB float64
	// At is when the event was detected, on the session clock.
	At time.Time
}

// Transport accepts an incoming media connection offer and returns a
// MediaConn for it. Implementations: transport/webrtc (Pion), the primary
// path, and transport/wsfallback, auto-selected on ICE failure.
type Transport interface {
	// Accept negotiates a new connection from a client offer (e.g. a WebRTC
	// SDP offer) and returns the SDP answer plus the resulting MediaConn.
	// Answer generation is local and cheap — it must not be bundled into
	// the vendor-connect timeout callers apply around the rest of session
	// setup.
	Accept(ctx context.Context, offer []byte) (answer []byte, conn MediaConn, err error)
}

// MediaConn is one open last-mile media connection to a browser.
type MediaConn interface {
	// AudioIn returns decoded, jitter-buffered mic frames from the human
	// interviewer.
	AudioIn() <-chan Frame
	// SendAudio sends one persona audio frame to the browser.
	SendAudio(ctx context.Context, frame Frame) error
	// Control returns control messages arriving from the browser.
	//
	// Receive-only, and paired with SendControl rather than being one
	// bidirectional channel. A single channel that the transport both reads
	// and writes cannot work: the transport would race its own consumer for
	// the messages it just sent.
	Control() <-chan ControlMessage
	// SendControl sends one control message to the browser. It must not
	// block on network I/O for longer than ctx allows.
	SendControl(ctx context.Context, msg ControlMessage) error
	// PlayoutHeartbeats returns the browser's periodic playout reports.
	PlayoutHeartbeats() <-chan PlayoutHeartbeat
	// Speech returns the locally-detected VAD stream for the human
	// interviewer's mic audio — see VADEvent for why the engine, not the
	// vendor, owns this signal.
	Speech() <-chan VADEvent
	// Close tears down the connection.
	Close(ctx context.Context) error
}
