package session

import (
	"bytes"
	"context"
	"strings"
	"testing"
	"time"

	"go.uber.org/goleak"

	"skillbrew/engine/internal/fakes"
	"skillbrew/engine/internal/ports"
)

// newActorWithDeps builds an actor with a real event log and caller-chosen
// deps, for the tests that assert on emitted events or on the session-scoped
// caps. newTestActor's Deps{} deliberately leaves both caps at zero.
func newActorWithDeps(bargeInAllowed bool, deps Deps) (*actor, *fakes.FakeClock, *bytes.Buffer) {
	clock := fakes.NewFakeClock(testNow)
	var buf bytes.Buffer
	a := newActor("sess-1", testContract(bargeInAllowed), clock, quietLogger(), newTestEventLog(&buf), deps)
	return a, clock, &buf
}

// fireNext takes the next alarm off the actor's own fire channel.
//
// A plain blocking receive, deliberately: internal/session may not call
// time.After even in tests — rule 6 of the layering gate, which exists so
// turn-timing tests are driven by FakeClock rather than by wall time, and
// which caught this helper's first draft. A missing fire hangs until the
// package test timeout, which reports it just as clearly.
func fireNext(t *testing.T, a *actor) timerFire {
	t.Helper()
	return <-a.timerFire
}

// ---------------------------------------------------------------------------
// The greeting dead-end (plan §B-1).
// ---------------------------------------------------------------------------

// TestTheGreetingReachesListeningWithoutAnyVendorResponse is the regression
// test for a bug that ended every real session before it started.
//
// The opening line is pre-synthesized audio, not a vendor response, so no
// ResponseDone is ever produced for it — and ResponseDone was SPEAKING's only
// legal exit. The actor entered SPEAKING on the interviewer's first utterance
// and stayed there for the rest of the session. It looked tested only because
// the conversation test hand-injected a ResponseDone that no production path
// emits.
func TestTheGreetingReachesListeningWithoutAnyVendorResponse(t *testing.T) {
	defer goleak.VerifyNone(t)

	a, clock, _ := newActorWithDeps(true, Deps{})
	defer a.timers.cancelAll()
	ctx := context.Background()

	a.transition(StateGreeting, "joined")
	a.handlePartial(ctx, ports.Partial{Text: "Hi, thanks for joining.", Final: true})

	if a.state != StateSpeaking {
		t.Fatalf("state = %s, want SPEAKING once the opening line starts", a.state)
	}
	if !a.timers.isArmed(timerPlayout) {
		t.Fatal("no playout alarm armed for the opening line: nothing will ever end this turn")
	}

	clock.Advance(time.Minute)
	a.handleTimer(ctx, fireNext(t, a))

	if a.state != StateListening {
		t.Fatalf("state = %s, want LISTENING once the opening line played out", a.state)
	}
}

// TestABargeInDuringTheOpeningLineCancelsItsPlayoutAlarm matters because the
// alarm is turn-scoped: if it survived the interruption it would fire later
// and close a turn that the barge-in had already closed, driving a transition
// out of whatever state the session had since reached.
func TestABargeInDuringTheOpeningLineCancelsItsPlayoutAlarm(t *testing.T) {
	defer goleak.VerifyNone(t)

	a, clock, _ := newActorWithDeps(true, Deps{})
	defer a.timers.cancelAll()
	ctx := context.Background()

	a.transition(StateGreeting, "joined")
	a.handlePartial(ctx, ports.Partial{Text: "Hello there.", Final: true})
	if !a.timers.isArmed(timerPlayout) {
		t.Fatal("test setup invalid: no playout alarm to cancel")
	}

	a.bargeIn(ctx)

	if a.timers.isArmed(timerPlayout) {
		t.Fatal("the playout alarm outlived the turn it belonged to")
	}
	clock.Advance(time.Minute)
	select {
	case f := <-a.timerFire:
		if a.timers.live(f) {
			t.Fatalf("a %s fire survived the barge-in as live", f.Kind)
		}
	default:
	}
}

// ---------------------------------------------------------------------------
// The barge-in flag (plan §B-4).
// ---------------------------------------------------------------------------

// TestANonYieldingPersonaHoldsTheFloorInEverySpeakingIshState matters because
// the gate used to test StateSpeaking alone, while persona audio is in flight
// in four other states. A no-barge-in persona therefore yielded during its own
// opening line and its own stall clips — the two moments an interviewer is
// most likely to talk over it, and the two the flag most obviously covers.
func TestANonYieldingPersonaHoldsTheFloorInEverySpeakingIshState(t *testing.T) {
	defer goleak.VerifyNone(t)

	for _, state := range []State{StatePreAnswer, StateDeferred, StateStalling, StateSpeaking} {
		t.Run(state.String(), func(t *testing.T) {
			a, clock, _ := newActorWithDeps(false, Deps{})
			defer a.timers.cancelAll()

			a.state = state
			a.playout.begin("item-1", clock.Now())

			speaker := fakes.NewFakeSpeaker()
			if _, err := speaker.Start(context.Background(), ports.SessionCfg{SessionID: "sess-1"}); err != nil {
				t.Fatalf("start speaker: %v", err)
			}
			sess := speaker.LastSession()
			a.speaking = sess

			a.bargeIn(context.Background())

			if a.state != state {
				t.Fatalf("state = %s, want %s: a non-yielding persona must keep the floor", a.state, state)
			}
			if got := sess.CancelCount(); got != 0 {
				t.Fatalf("CancelResponse called %d times in %s; the persona does not yield", got, state)
			}
		})
	}
}

// TestTheMicGateHoldsInEverySpeakingIshState is the same rule on the inbound
// path: while a non-yielding persona is talking, the interviewer's audio is
// not forwarded to the Speaker at all, in any state where persona audio is in
// flight.
func TestTheMicGateHoldsInEverySpeakingIshState(t *testing.T) {
	defer goleak.VerifyNone(t)

	for _, state := range []State{StatePreAnswer, StateDeferred, StateStalling, StateSpeaking} {
		t.Run(state.String(), func(t *testing.T) {
			a, _, _ := newActorWithDeps(false, Deps{})
			defer a.timers.cancelAll()

			speaker := fakes.NewFakeSpeaker()
			if _, err := speaker.Start(context.Background(), ports.SessionCfg{SessionID: "sess-1"}); err != nil {
				t.Fatalf("start speaker: %v", err)
			}
			sess := speaker.LastSession()
			a.speaking = sess
			a.state = state

			a.handleMic(context.Background(), micFrame{Frame: ports.Frame{
				PCM: make([]byte, 960), SampleRateHz: defaultSampleRate,
			}})

			if got := len(sess.SentAudio()); got != 0 {
				t.Fatalf("%d frames reached the Speaker in %s; the mic gate is shut", got, state)
			}
		})
	}
}

// ---------------------------------------------------------------------------
// The two session-scoped caps, neither of which had ever been armed.
// ---------------------------------------------------------------------------

// TestTheAbandonmentCapWindsTheSessionDown matters because plan §11's
// abandonment behaviour did not exist: timerSilence was declared, was never
// armed anywhere in production code, and so could never fire. An interviewer
// who closed the tab left a session running against a paid vendor connection
// until something else killed it.
func TestTheAbandonmentCapWindsTheSessionDown(t *testing.T) {
	defer goleak.VerifyNone(t)

	a, clock, _ := newActorWithDeps(true, Deps{SilenceTimeout: 90 * time.Second})
	defer a.timers.cancelAll()
	ctx := context.Background()

	a.transition(StateGreeting, "joined")
	a.transition(StateListening, "greeting done")

	if !a.timers.isArmed(timerSilence) {
		t.Fatal("the abandonment cap must be armed while the session waits on the interviewer")
	}

	clock.Advance(91 * time.Second)
	a.handleTimer(ctx, fireNext(t, a))

	if a.state != StateDone {
		t.Fatalf("state = %s, want DONE after the abandonment cap fired", a.state)
	}
}

// TestTheAbandonmentCapDoesNotRunWhileThePersonaIsTalking matters because the
// cap measures an absent interviewer, not an interviewer who is listening. A
// 90-second answer would otherwise end the session mid-sentence.
func TestTheAbandonmentCapDoesNotRunWhileThePersonaIsTalking(t *testing.T) {
	defer goleak.VerifyNone(t)

	a, _, _ := newActorWithDeps(true, Deps{SilenceTimeout: 90 * time.Second})
	defer a.timers.cancelAll()

	a.transition(StateGreeting, "joined")
	a.transition(StateListening, "greeting done")
	a.transition(StatePreAnswer, "answering")

	if a.timers.isArmed(timerSilence) {
		t.Fatal("the abandonment cap is still running while the persona holds the floor")
	}
}

// TestTheSessionCapStartsWhenTheInterviewDoesNotWhenTheActorIsBuilt matters
// because a session can sit in CONNECTING with nobody talking. Charging that
// to the interviewer's hour would cut a real interview short by however long
// the vendor took to answer.
func TestTheSessionCapStartsWhenTheInterviewDoesNotWhenTheActorIsBuilt(t *testing.T) {
	defer goleak.VerifyNone(t)

	a, clock, _ := newActorWithDeps(true, Deps{SessionDurationCap: 45 * time.Minute})
	defer a.timers.cancelAll()
	ctx := context.Background()

	if a.timers.isArmed(timerSession) {
		t.Fatal("the duration cap must not run before the interviewer has joined")
	}

	a.handle(ctx, command{Kind: cmdInterviewerJoined})
	if !a.timers.isArmed(timerSession) {
		t.Fatal("the duration cap must start when the interview does")
	}

	clock.Advance(46 * time.Minute)
	a.handleTimer(ctx, fireNext(t, a))
	if a.state != StateDone {
		t.Fatalf("state = %s, want DONE after the duration cap fired", a.state)
	}
}

// TestAZeroCapIsNotArmedRatherThanFiringImmediately matters because zero is
// what an unset config value reads as, and an alarm armed at zero would end
// every session on its first tick.
func TestAZeroCapIsNotArmedRatherThanFiringImmediately(t *testing.T) {
	defer goleak.VerifyNone(t)

	a, _, _ := newActorWithDeps(true, Deps{})
	defer a.timers.cancelAll()

	a.handle(context.Background(), command{Kind: cmdInterviewerJoined})
	a.transition(StateListening, "greeting done")

	if a.timers.isArmed(timerSession) || a.timers.isArmed(timerSilence) {
		t.Fatal("a zero cap must mean no alarm, not an alarm that fires at once")
	}
}

// ---------------------------------------------------------------------------
// Nothing is dropped in silence.
// ---------------------------------------------------------------------------

// TestAnUnhandledSpeakerEventIsRecordedRatherThanDropped matters because
// ports.SpeakerEvent is an open interface with seven kinds and four adapters
// to come, and this build handles five of them. The other two — ToolCall and
// SpeakerError — reach the actor today and fall straight through. Dropping
// them is the correct behaviour for now; dropping them in silence is not,
// because it is indistinguishable from an adapter that never emitted
// anything.
//
// SpeakerError in particular is the one that will matter: D5 has the Gemini
// adapter emit SpeakerError{Fatal:true} when session resumption fails, and
// until the rebuild path lands in M5 the only trace of that will be this
// event.
func TestAnUnhandledSpeakerEventIsRecordedRatherThanDropped(t *testing.T) {
	defer goleak.VerifyNone(t)

	for _, ev := range []ports.SpeakerEvent{
		ports.ToolCall{},
		ports.SpeakerError{},
	} {
		a, _, log := newActorWithDeps(true, Deps{})
		a.handleSpeakerEvent(context.Background(), ev)
		a.timers.cancelAll()

		if !strings.Contains(log.String(), "speaker_event_unhandled") {
			t.Fatalf("%T left no trace in the event log:\n%s", ev, log.String())
		}
	}
}

// ---------------------------------------------------------------------------
// Playout measures duration, not samples (plan §B-7).
// ---------------------------------------------------------------------------

// TestPlayoutMeasuresDurationSoMixedSampleRatesAreNotMisMeasured matters
// because the tracker used to accumulate a sample count and divide once by a
// single fixed rate. Vendor audio at 24 kHz alongside transport audio at
// 48 kHz is the ordinary case, and under the old arithmetic one second of
// 48 kHz audio was measured as two.
func TestPlayoutMeasuresDurationSoMixedSampleRatesAreNotMisMeasured(t *testing.T) {
	defer goleak.VerifyNone(t)

	p := newPlayoutTracker(defaultSampleRate)
	p.begin("item-1", testNow)

	// One second at each rate: 2 s of audio, whatever the sample counts.
	p.sent(24000*bytesPerSamplePCM16, 24000)
	p.sent(48000*bytesPerSamplePCM16, 48000)

	if got := p.sentMs(); got != 2000 {
		t.Fatalf("sentMs() = %d, want 2000 — one second at 24 kHz plus one at 48 kHz is two seconds", got)
	}
}

// TestAFrameWithNoDeclaredRateFallsBackRatherThanBeingDropped matters because
// discarding it would under-count what was sent, and sentMs caps the heard
// estimate — so a dropped frame truncates a barge-in earlier than it should.
func TestAFrameWithNoDeclaredRateFallsBackRatherThanBeingDropped(t *testing.T) {
	defer goleak.VerifyNone(t)

	p := newPlayoutTracker(defaultSampleRate)
	p.begin("item-1", testNow)
	p.sent(defaultSampleRate*bytesPerSamplePCM16, 0)

	if got := p.sentMs(); got != 1000 {
		t.Fatalf("sentMs() = %d, want 1000 via the default rate", got)
	}
}

// ---------------------------------------------------------------------------
// Clip duration.
// ---------------------------------------------------------------------------

// TestClipDurationPrefersTheRealClipAndDegradesToAnEstimate matters because
// the degraded path is the one that runs today: no StallBank is wired yet, so
// every opening line is currently timed from its text. An estimate that ends
// the turn a little early is a blemish; hanging in SPEAKING because no clip
// existed to measure ends the interview.
func TestClipDurationPrefersTheRealClipAndDegradesToAnEstimate(t *testing.T) {
	defer goleak.VerifyNone(t)

	a, _, _ := newActorWithDeps(true, Deps{})
	defer a.timers.cancelAll()

	ctx := context.Background()
	text := strings.Repeat("word ", 150) // 150 words ≈ one minute, clamped
	if got := a.playClip(ctx, text); got != 30*time.Second {
		t.Fatalf("estimated duration = %v, want the 30s ceiling with no clip available", got)
	}

	// One second of 24 kHz PCM16 as the opening line.
	bank := fakes.NewFakeStallBank(ports.PCM16Audio{
		Samples:      make([]byte, defaultSampleRate*bytesPerSamplePCM16),
		SampleRateHz: defaultSampleRate,
	})
	if err := bank.Warm(context.Background()); err != nil {
		t.Fatalf("warm: %v", err)
	}
	a.stall = bank
	clip, ok := bank.OpeningLine()
	if !ok {
		t.Fatal("test setup invalid: the fake bank has no opening line")
	}
	want, exact := clipPlayTime(clip)
	if !exact {
		t.Fatal("test setup invalid: the fake clip has no measurable duration")
	}
	if got := a.playClip(ctx, text); got != want {
		t.Fatalf("duration = %v, want the clip's own %v when a clip is in hand", got, want)
	}
}
