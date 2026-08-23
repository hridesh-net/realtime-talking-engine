package session

import (
	"time"

	"skillbrew/engine/internal/ports"
)

// timerKind names one of the actor's alarms. Each kind is at most singly
// armed: arming a kind that is already running replaces it.
type timerKind int

const (
	// timerPause is the pause-before-answer delay, vendor-latency
	// compensated, that keeps the persona from replying inhumanly fast.
	timerPause timerKind = iota
	// timerPregate bounds how long the actor waits for a pre-gate verdict
	// after end-of-turn before treating the turn as CONFIDENT.
	timerPregate
	// timerStall bounds how long a stall clip covers for the Thinker
	// before the actor falls back to the contract's own directive.
	timerStall
	// timerThinker bounds the Thinker's note deadline.
	timerThinker
	// timerSilence detects an interviewer who has stopped participating.
	timerSilence
	// timerSession is the hard duration cap.
	timerSession
	numTimerKinds
)

func (k timerKind) String() string {
	switch k {
	case timerPause:
		return "pause"
	case timerPregate:
		return "pregate"
	case timerStall:
		return "stall"
	case timerThinker:
		return "thinker"
	case timerSilence:
		return "silence"
	case timerSession:
		return "session"
	default:
		return "unknown"
	}
}

// turnScoped reports whether this alarm belongs to the in-flight turn and so
// must die when the turn does. The silence and session caps outlive turns;
// everything else is a ghost waiting to happen if it survives a barge-in.
func (k timerKind) turnScoped() bool {
	return k != timerSilence && k != timerSession
}

// timerFire is what a fired alarm delivers to the actor loop.
type timerFire struct {
	Kind timerKind
	At   time.Time
	// Gen is the arming generation. The actor drops a fire whose generation
	// no longer matches the armed one — see timerSet.
	Gen uint64
}

// timerSet owns the actor's alarms.
//
// The generation counter is the whole point. Stopping a Go timer does not
// retract a fire that is already in flight on its channel, so a naive
// implementation lets a stall timer cancelled during barge-in still deliver
// milliseconds later and drive a response for a turn that no longer exists.
// That is the "ghost utterance" bug class plan §4 names. Every arming bumps a
// generation; a fire carries the generation it was armed under; the actor
// discards any fire whose generation is stale. Cancellation is then a fact
// about the actor's state rather than a race against the runtime.
//
// Not safe for concurrent use: it is actor-owned state, touched only from the
// owner goroutine, which is the point of the actor model.
type timerSet struct {
	clock ports.Clock
	fires chan timerFire

	timers [numTimerKinds]ports.Timer
	gens   [numTimerKinds]uint64
	armed  [numTimerKinds]bool
	// stops releases each armed alarm's waiter goroutine. Stopping a Timer
	// does not close its channel, so a waiter blocked on it would live
	// until process exit: one leaked goroutine per cancelled timer, per
	// turn. At fifty sessions a node that is a slow-motion outage, so
	// cancellation closes the waiter's own door instead.
	stops   [numTimerKinds]chan struct{}
	nextGen uint64
}

func newTimerSet(clock ports.Clock, fires chan timerFire) *timerSet {
	return &timerSet{clock: clock, fires: fires}
}

// arm starts (or restarts) one alarm. Arming a running alarm replaces it.
func (t *timerSet) arm(kind timerKind, d time.Duration) {
	t.cancel(kind)
	t.nextGen++
	gen := t.nextGen
	t.gens[kind] = gen
	t.armed[kind] = true

	timer := t.clock.NewTimer(d)
	t.timers[kind] = timer
	stop := make(chan struct{})
	t.stops[kind] = stop

	// One goroutine per armed alarm. It carries no logic — it converts a
	// timer channel into an actor message, which is the pump discipline of
	// plan §4 — and it has two exits: the alarm fires, or cancellation
	// closes stop. Sending on fires also selects on stop, because an actor
	// that has already shut down will never drain the channel.
	go func(c <-chan time.Time) {
		select {
		case at, ok := <-c:
			if !ok {
				return
			}
			select {
			case t.fires <- timerFire{Kind: kind, At: at, Gen: gen}:
			case <-stop:
			}
		case <-stop:
		}
	}(timer.C())
}

// cancel stops one alarm. A fire already in flight for it becomes stale and
// the actor will discard it.
func (t *timerSet) cancel(kind timerKind) {
	if t.timers[kind] != nil {
		t.timers[kind].Stop()
		t.timers[kind] = nil
	}
	if t.stops[kind] != nil {
		close(t.stops[kind])
		t.stops[kind] = nil
	}
	t.armed[kind] = false
	t.gens[kind] = 0
}

// cancelTurnScoped stops every alarm belonging to the in-flight turn. Called
// on every turn close and on every barge-in.
func (t *timerSet) cancelTurnScoped() {
	for k := timerKind(0); k < numTimerKinds; k++ {
		if k.turnScoped() {
			t.cancel(k)
		}
	}
}

// cancelAll stops every alarm, including the session-scoped ones.
func (t *timerSet) cancelAll() {
	for k := timerKind(0); k < numTimerKinds; k++ {
		t.cancel(k)
	}
}

// live reports whether a fire should be acted on: the alarm must still be
// armed and the fire must carry the current generation.
func (t *timerSet) live(f timerFire) bool {
	return t.armed[f.Kind] && t.gens[f.Kind] == f.Gen
}

// isArmed reports whether one alarm is currently running. Tests assert on it.
func (t *timerSet) isArmed(kind timerKind) bool { return t.armed[kind] }
