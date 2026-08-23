package session

import (
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
)

// command is one control instruction delivered to the actor's owner
// goroutine. Control is never dropped: each of these is a decision, and a
// dropped decision is a session that hangs in the wrong state.
type command struct {
	Kind   commandKind
	Reason string
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
type drops struct {
	MicAudio     int
	ASRPartials  int
	SpeakerAudio int
	Heartbeats   int
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
