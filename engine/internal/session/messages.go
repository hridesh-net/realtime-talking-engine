package session

import (
	"sync/atomic"
	"time"

	"skillbrew/engine/internal/ports"
)

// Channel capacities per plan §4. The policy differences matter more than the
// numbers: control and timers are never dropped because losing one loses a
// decision, while media is bounded and drop-oldest because a stalled actor
// must not become backpressure on a real-time audio path.
const (
	controlBufferSize      = 64
	timerBufferSize        = 16
	micAudioBufferSize     = 64
	speechBufferSize       = 16
	asrPartialBufferSize   = 8
	speakerAudioBufferSize = 64
	speakerCtrlBufferSize  = 32
	heartbeatBufferSize    = 1
)

// commandKind names a control-plane instruction to the actor.
type commandKind int

const (
	// cmdStop asks the session to wind down in character.
	cmdStop commandKind = iota
	// cmdInterviewerJoined moves CONNECTING → GREETING.
	cmdInterviewerJoined
	// cmdAttachTransport asks the actor to accept a client's SDP offer and,
	// on success, spawn the per-session connector. Carries Offer and Reply.
	cmdAttachTransport
	// cmdConnected delivers the connector's finished, all-or-nothing result:
	// the fatal Speaker session plus which non-fatal collaborators actually
	// came up. Carries Connected.
	cmdConnected
	// cmdConnectFailed delivers a fatal connect failure (no Speaker within
	// budget). Carries Err; the actor winds down with end_reason "error".
	cmdConnectFailed
)

// attachOutcome is what a cmdAttachTransport reply carries back to the
// caller waiting on it (Manager.AttachTransport): the SDP answer on
// success, or the reason attaching failed.
type attachOutcome struct {
	Answer []byte
	Err    error
}

// connectOutcome is what the per-session connector goroutine hands the
// actor on cmdConnected: the fatal Speaker session, already open, plus
// which non-fatal collaborators failed to come up and must therefore
// degrade rather than end the session.
type connectOutcome struct {
	// Speaker is the opened SpeakerSession. Never nil — a nil Speaker is a
	// fatal connect failure, delivered via cmdConnectFailed instead.
	Speaker ports.SpeakerSession
	// TranscriberFailed marks that a configured Transcriber failed to
	// start; the actor drops it and flags the session degraded:asr.
	TranscriberFailed bool
	// ThinkerFailed marks that a configured Thinker failed to start; the
	// actor drops it and the session runs the single-model path.
	ThinkerFailed bool
	// StallFailed marks that a configured StallBank failed to warm; the
	// actor drops it and flags the session degraded:stall.
	StallFailed bool
}

// command is one control instruction delivered to the actor's owner
// goroutine. Control is never dropped: each of these is a decision, and a
// dropped decision is a session that hangs in the wrong state.
type command struct {
	Kind   commandKind
	Reason string
	// Reply receives this command's outcome exactly once, for a caller
	// waiting synchronously on it. Only cmdAttachTransport ever sets this;
	// every other kind leaves it nil.
	Reply chan<- attachOutcome
	// Offer is the client's SDP offer, carried by cmdAttachTransport.
	Offer []byte
	// Connected carries the connector's result on cmdConnected.
	Connected *connectOutcome
	// Err carries the fatal failure reason on cmdConnectFailed.
	Err error
}

// micFrame is one decoded frame of the interviewer's audio.
type micFrame struct {
	Frame ports.Frame
	At    time.Time
}

// heartbeat is the browser's report of how much persona audio it has actually
// played. Newest-wins: an older report tells us nothing a newer one does not.
type heartbeat struct {
	ItemID   string
	PlayedMs int
	At       time.Time
}

// thinkerNote carries one reasoning-model note into the actor, scoped to the
// turn it was requested for so a late note cannot drive the next turn.
type thinkerNote struct {
	Note ports.Note
	Turn int
}

// pregateVerdict is the deterministic pre-gate's classification of the
// in-flight interviewer utterance.
type pregateVerdict struct {
	// Skill is the skill being probed, "" when none matched.
	Skill string
	// Defer is true when the probe is at or below the skill's defer
	// ceiling and the Speaker should not answer unaided.
	Defer bool
	// Turn scopes the verdict, so one arriving late for a turn that has
	// already closed is discarded rather than applied to the next one.
	Turn int
}

// drops counts what the bounded channels shed under overload, per plan §4.
// Surfaced in the event log so a session that degraded says so rather than
// looking merely slow.
//
// Every field is an atomic counter, not a plain int. The Speaker event pump
// writes SpeakerAudio concurrently with the actor's own owner goroutine —
// the one exception to "every actor field is touched only from inside
// run" — so a plain int would race under go test -race the moment a
// session actually sheds a frame.
type drops struct {
	MicAudio     atomic.Int64
	ASRPartials  atomic.Int64
	SpeakerAudio atomic.Int64
	Heartbeats   atomic.Int64
}

// offerDrop pushes v onto a bounded channel, dropping the oldest queued item
// if it is full, and reports whether something was shed.
//
// Drop-oldest rather than drop-newest: for audio and partials the newest item
// is the one that reflects reality now. A jitter spike should cost the stalest
// frame, not the freshest.
func offerDrop[T any](ch chan T, v T) bool {
	select {
	case ch <- v:
		return false
	default:
	}
	dropped := false
	select {
	case <-ch:
		dropped = true
	default:
	}
	select {
	case ch <- v:
	default:
	}
	return dropped
}

// offerNewest replaces whatever is queued with v on a size-1 channel.
func offerNewest[T any](ch chan T, v T) {
	select {
	case <-ch:
	default:
	}
	select {
	case ch <- v:
	default:
	}
}
