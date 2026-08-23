package session

import (
	"strings"
	"testing"
	"time"

	"skillbrew/engine/internal/fakes"
)

var testNow = time.Date(2026, 8, 25, 12, 0, 0, 0, time.UTC)

// ---------------------------------------------------------------------------
// Task 10 — state machine
// ---------------------------------------------------------------------------

func TestLegalTurnLoopTransitions(t *testing.T) {
	legal := []struct{ from, to State }{
		{StateConnecting, StateGreeting},
		{StateGreeting, StateListening},
		{StateGreeting, StateSpeaking},
		{StateListening, StatePreAnswer},
		{StateListening, StateDeferred},
		{StatePreAnswer, StateSpeaking},
		{StateDeferred, StateStalling},
		{StateDeferred, StateSpeaking},
		{StateStalling, StateSpeaking},
		{StateSpeaking, StateListening},
		{StateDraining, StateListening},
		{StateWindingDown, StateFinalizing},
		{StateFinalizing, StateDone},
	}
	for _, c := range legal {
		if !canTransition(c.from, c.to) {
			t.Errorf("%s -> %s should be legal", c.from, c.to)
		}
	}
}

func TestIllegalTurnLoopTransitionsAreRejected(t *testing.T) {
	// The ones that would actually happen if the loop had a bug: skipping
	// the pause, answering twice, resurrecting a finished session.
	illegal := []struct{ from, to State }{
		{StateListening, StateSpeaking},   // skipped the pre-gate entirely
		{StateConnecting, StateListening}, // never greeted
		{StateSpeaking, StatePreAnswer},   // answering while answering
		{StateDone, StateListening},       // terminal is terminal
		{StateDone, StateWindingDown},
		{StateListening, StateDraining}, // nothing playing to drain
		{StateFinalizing, StateListening},
	}
	for _, c := range illegal {
		if canTransition(c.from, c.to) {
			t.Errorf("%s -> %s should be illegal", c.from, c.to)
		}
	}
}

func TestBargeInReachesDrainingFromAnySpeakingishStateOnly(t *testing.T) {
	for s := StateConnecting; s <= StateDone; s++ {
		got := canTransition(s, StateDraining)
		if want := s.speakingish(); got != want {
			t.Errorf("%s -> DRAINING = %v, want %v", s, got, want)
		}
	}
}

func TestWindDownIsReachableFromAnywhereStillRunning(t *testing.T) {
	for s := StateConnecting; s <= StateDone; s++ {
		got := canTransition(s, StateWindingDown)
		if want := !s.terminating(); got != want {
			t.Errorf("%s -> WINDING_DOWN = %v, want %v", s, got, want)
		}
	}
}

func TestStateNamesAreStableForTheEventLog(t *testing.T) {
	// The grader reads these strings. Renaming one silently breaks a
	// downstream consumer, so they are pinned here.
	want := map[State]string{
		StateConnecting: "CONNECTING", StateGreeting: "GREETING",
		StateListening: "LISTENING", StatePreAnswer: "PRE_ANSWER",
		StateDeferred: "DEFERRED", StateStalling: "STALLING",
		StateSpeaking: "SPEAKING", StateDraining: "DRAINING",
		StateWindingDown: "WINDING_DOWN", StateFinalizing: "FINALIZING",
		StateDone: "DONE",
	}
	for s, name := range want {
		if s.String() != name {
			t.Errorf("State(%d).String() = %q, want %q", int(s), s.String(), name)
		}
	}
}

// ---------------------------------------------------------------------------
// Task 11 — timers. The bug class here is the ghost fire.
// ---------------------------------------------------------------------------

func TestACancelledTimerCannotDriveTheNextTurn(t *testing.T) {
	// Stopping a timer does not retract a fire already in flight. Without a
	// generation guard, a stall alarm cancelled during barge-in still
	// arrives milliseconds later and drives a response for a turn that no
	// longer exists — the ghost-utterance bug of plan §4.
	clock := fakes.NewFakeClock(testNow)
	fires := make(chan timerFire, 4)
	ts := newTimerSet(clock, fires)
	defer ts.cancelAll()

	ts.arm(timerStall, 100*time.Millisecond)
	stale := timerFire{Kind: timerStall, At: testNow, Gen: ts.gens[timerStall]}
	ts.cancel(timerStall)

	if ts.live(stale) {
		t.Fatal("a fire from a cancelled timer must not be live")
	}

	// Re-arming the same kind must not resurrect the old fire either.
	ts.arm(timerStall, 100*time.Millisecond)
	if ts.live(stale) {
		t.Fatal("a fire from a superseded arming must not be live")
	}
	fresh := timerFire{Kind: timerStall, At: testNow, Gen: ts.gens[timerStall]}
	if !ts.live(fresh) {
		t.Fatal("the current arming's fire must be live")
	}
}

func TestBargeInCancelsEveryTurnTimerButNotTheSessionCaps(t *testing.T) {
	clock := fakes.NewFakeClock(testNow)
	ts := newTimerSet(clock, make(chan timerFire, 8))
	defer ts.cancelAll()
	for _, k := range []timerKind{timerPause, timerPregate, timerStall, timerThinker, timerSilence, timerSession} {
		ts.arm(k, time.Second)
	}
	ts.cancelTurnScoped()

	for _, k := range []timerKind{timerPause, timerPregate, timerStall, timerThinker} {
		if ts.isArmed(k) {
			t.Errorf("%s should be cancelled with the turn", k)
		}
	}
	// The interviewer going silent and the duration cap outlive any one
	// turn — cancelling them on barge-in would let a session run forever.
	for _, k := range []timerKind{timerSilence, timerSession} {
		if !ts.isArmed(k) {
			t.Errorf("%s must survive a turn close", k)
		}
	}
}

func TestArmedTimersDeliverOnTheInjectedClock(t *testing.T) {
	clock := fakes.NewFakeClock(testNow)
	fires := make(chan timerFire, 4)
	ts := newTimerSet(clock, fires)
	defer ts.cancelAll()
	ts.arm(timerPause, 700*time.Millisecond)

	clock.Advance(700 * time.Millisecond)

	// A blocking receive, deliberately. internal/session may not call
	// time.After — the arch gate enforces it, and the rule is right: a
	// test that reaches for real time to bound a fake-clock test has
	// stopped testing determinism. If the fire never comes, go test's own
	// timeout reports it.
	f := <-fires
	if f.Kind != timerPause {
		t.Fatalf("fired %v, want pause", f.Kind)
	}
	if !ts.live(f) {
		t.Fatal("a fire from a live arming should be live")
	}
}

// ---------------------------------------------------------------------------
// Task 12 — playout tracker
// ---------------------------------------------------------------------------

// pcmFor returns the byte count for d of PCM16 mono at 24 kHz.
func pcmFor(d time.Duration) int {
	return int(d/time.Millisecond) * defaultSampleRate / 1000 * bytesPerSamplePCM16
}

func TestBargeInTruncatesAtWhatWasHeardNotWhatWasSent(t *testing.T) {
	// Plan §14 task 12: send 5 s, heartbeat says 2.1 s played, barge-in ⇒
	// truncate at 2100 ± one frame. Truncating at bytes-sent would tell the
	// vendor the persona said three seconds nobody heard, and every later
	// turn would reason from that false history.
	p := newPlayoutTracker(defaultSampleRate)
	now := testNow
	p.begin("item-1", now)
	p.sent(pcmFor(5 * time.Second))

	now = now.Add(2100 * time.Millisecond)
	p.heartbeat("item-1", 2100, now)

	if got := p.sentMs(); got != 5000 {
		t.Fatalf("sentMs = %d, want 5000", got)
	}
	if got := p.heardMs(now); got != 2100 {
		t.Fatalf("heardMs = %d, want 2100", got)
	}
}

func TestHeardTimeExtrapolatesBetweenHeartbeats(t *testing.T) {
	p := newPlayoutTracker(defaultSampleRate)
	now := testNow
	p.begin("item-1", now)
	p.sent(pcmFor(5 * time.Second))
	p.heartbeat("item-1", 2000, now)

	// 250 ms later, before the next heartbeat, the human has heard 250 ms
	// more — the heartbeat cadence must not freeze the estimate.
	if got := p.heardMs(now.Add(250 * time.Millisecond)); got != 2250 {
		t.Fatalf("heardMs = %d, want 2250", got)
	}
}

func TestHeardTimeNeverExceedsWhatWasActuallySent(t *testing.T) {
	p := newPlayoutTracker(defaultSampleRate)
	now := testNow
	p.begin("item-1", now)
	p.sent(pcmFor(1 * time.Second))
	p.heartbeat("item-1", 1000, now)

	// Ten seconds of wall time later, only one second was ever transmitted.
	if got := p.heardMs(now.Add(10 * time.Second)); got != 1000 {
		t.Fatalf("heardMs = %d, want 1000 (capped at sent)", got)
	}
}

func TestAStaleHeartbeatCannotWalkTheEstimateBackwards(t *testing.T) {
	// A late-arriving older report followed immediately by a barge-in would
	// truncate too early, inventing silence the human did hear.
	p := newPlayoutTracker(defaultSampleRate)
	now := testNow
	p.begin("item-1", now)
	p.sent(pcmFor(5 * time.Second))
	p.heartbeat("item-1", 3000, now)
	p.heartbeat("item-1", 1000, now) // stale, out of order

	if got := p.heardMs(now); got != 3000 {
		t.Fatalf("heardMs = %d, want 3000", got)
	}
}

func TestHeartbeatsForAnotherItemAreIgnored(t *testing.T) {
	p := newPlayoutTracker(defaultSampleRate)
	p.begin("item-2", testNow)
	p.sent(pcmFor(2 * time.Second))
	p.heartbeat("item-1", 1900, testNow) // previous response, still in flight

	if got := p.heardMs(testNow); got != 0 {
		t.Fatalf("heardMs = %d, want 0 — that heartbeat was for a different item", got)
	}
}

// ---------------------------------------------------------------------------
// Task 14 — backpressure
// ---------------------------------------------------------------------------

func TestBoundedChannelsShedTheOldestNotTheNewest(t *testing.T) {
	// Under a jitter spike the freshest frame is the one that reflects
	// reality; the stalest is the one worth losing.
	ch := make(chan int, 2)
	if offerDrop(ch, 1) || offerDrop(ch, 2) {
		t.Fatal("no drop expected while there is room")
	}
	if !offerDrop(ch, 3) {
		t.Fatal("a full channel should report a drop")
	}
	got := []int{<-ch, <-ch}
	if got[0] != 2 || got[1] != 3 {
		t.Fatalf("queue = %v, want [2 3] — oldest shed", got)
	}
}

func TestNewestWinsChannelKeepsOnlyTheLatest(t *testing.T) {
	ch := make(chan heartbeat, 1)
	offerNewest(ch, heartbeat{PlayedMs: 100})
	offerNewest(ch, heartbeat{PlayedMs: 200})
	offerNewest(ch, heartbeat{PlayedMs: 300})

	if got := <-ch; got.PlayedMs != 300 {
		t.Fatalf("kept %d ms, want the newest 300", got.PlayedMs)
	}
	if len(ch) != 0 {
		t.Fatalf("channel should hold at most one, holds %d", len(ch))
	}
}

// ---------------------------------------------------------------------------
// Event log
// ---------------------------------------------------------------------------

func TestEventLogIsOrderedAndStampedFromTheSessionClock(t *testing.T) {
	var sb strings.Builder
	log := newTestEventLog(&sb)
	log.Emit(testNow, "state_transition", 1, map[string]any{"to": "LISTENING"})
	log.Emit(testNow.Add(time.Second), "barge_in", 1, map[string]any{"heard_ms": 2100})

	out := sb.String()
	if !strings.Contains(out, `"seq":1`) || !strings.Contains(out, `"seq":2`) {
		t.Fatalf("events must be sequenced:\n%s", out)
	}
	if !strings.Contains(out, `"heard_ms":2100`) {
		t.Fatalf("payload missing:\n%s", out)
	}
	if strings.Count(out, "\n") != 2 {
		t.Fatalf("expected one JSON object per line:\n%s", out)
	}
}
