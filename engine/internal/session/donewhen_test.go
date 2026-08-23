package session

import (
	"context"
	"io"
	"log/slog"
	"testing"
	"time"

	"go.uber.org/goleak"

	"skillbrew/engine/internal/contract"
	"skillbrew/engine/internal/fakes"
	"skillbrew/engine/internal/ports"
)

func quietLogger() *slog.Logger {
	return slog.New(slog.NewTextHandler(io.Discard, nil))
}

// testContract is the minimum an actor needs to run a turn.
//
// bargeInAllowed drives turn_policy.barge_in_allowed — whether the *human*
// may interrupt the persona, which is the flag the mic gate and bargeIn
// enforce.
//
// voice_directives.may_interrupt is deliberately set to the OPPOSITE value.
// The two fields name opposite directions of interruption — may_interrupt is
// the persona's licence to talk over the human — and the actor read the wrong
// one of them for the whole of Phase 1, gating barge-in on may_interrupt while
// barge_in_allowed was read nowhere in the codebase, tests included. Setting
// them to the same value would let that conflation return and every test still
// pass. Opposed, any code that reaches for may_interrupt when it means
// barge_in_allowed fails immediately.
func testContract(bargeInAllowed bool) *contract.EngineContract {
	return &contract.EngineContract{
		ContractVersion: "v1.3",
		CandidateID:     "cand-1",
		InterviewID:     "int-1",
		VoiceDirectives: contract.VoiceDirectives{
			TargetPauseBeforeAnswerMs: 700,
			MayInterrupt:              !bargeInAllowed,
		},
		TurnPolicy: contract.TurnPolicy{
			MinSentences: 1, MaxSentences: 3, TargetSentencesPerAnswer: 2,
			DefaultAnswerDepth: "adequate",
			BargeInAllowed:     bargeInAllowed,
		},
	}
}

func newTestActor(t *testing.T, bargeInAllowed bool) (*actor, *fakes.FakeClock) {
	t.Helper()
	clock := fakes.NewFakeClock(testNow)
	a := newActor("sess-1", testContract(bargeInAllowed), clock, quietLogger(), nil, Deps{})
	return a, clock
}

// ---------------------------------------------------------------------------
// Task 9, done-when: "1000x start/stop churn is -race- and goleak-clean."
// ---------------------------------------------------------------------------

func TestThousandSessionChurnLeavesNothingBehind(t *testing.T) {
	defer goleak.VerifyNone(t)
	// The leak this guards is not hypothetical: the first timer
	// implementation left one goroutine per cancelled alarm alive forever.
	// goleak's TestMain catches survivors; this makes sure there are enough
	// start/stop cycles for a per-session leak to be unmissable.
	for i := 0; i < 1000; i++ {
		a, _ := newTestActor(t, true)
		ctx, cancel := context.WithCancel(context.Background())
		done := make(chan struct{})
		go a.run(ctx, done)

		// Actually arm the alarms. An earlier version of this test only
		// sent a control command, which arms nothing — it churned actors
		// but never exercised timer cancellation, so it passed just as
		// happily with the leak reintroduced. A churn test that cannot
		// fail is worse than no churn test, because it reads like proof.
		for k := timerKind(0); k < numTimerKinds; k++ {
			a.timers.arm(k, time.Hour)
		}
		a.control <- command{Kind: cmdInterviewerJoined}
		cancel()
		<-done
	}
}

func TestStoppingASessionCancelsEveryAlarmItArmed(t *testing.T) {
	defer goleak.VerifyNone(t)
	a, _ := newTestActor(t, true)
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan struct{})
	go a.run(ctx, done)
	cancel()
	<-done

	// run defers cancelAll; nothing may still be armed once it has exited.
	for k := timerKind(0); k < numTimerKinds; k++ {
		if a.timers.isArmed(k) {
			t.Errorf("%s still armed after the actor stopped", k)
		}
	}
}

// ---------------------------------------------------------------------------
// Task 11, done-when: "FakeClock tests prove zero ghost fires after barge-in
// and after session stop."
// ---------------------------------------------------------------------------

func TestNoGhostFireAfterBargeIn(t *testing.T) {
	defer goleak.VerifyNone(t)
	// A pause alarm armed for this turn, a barge-in, then the clock moves
	// past when the alarm would have fired. It must not drive a response
	// for a turn that no longer exists.
	a, clock := newTestActor(t, true)
	defer a.timers.cancelAll()

	a.state = StateSpeaking
	a.playout.begin("item-1", clock.Now())
	a.timers.arm(timerPause, 700*time.Millisecond)

	a.bargeIn(context.Background())

	if a.state != StateListening {
		t.Fatalf("state = %s, want LISTENING after barge-in", a.state)
	}
	clock.Advance(2 * time.Second)

	// Drain whatever the cancelled alarm managed to emit and assert the
	// actor would reject all of it.
	for {
		select {
		case f := <-a.timerFire:
			if a.timers.live(f) {
				t.Fatalf("ghost fire accepted after barge-in: %s", f.Kind)
			}
		default:
			return
		}
	}
}

func TestNoGhostFireAfterSessionStop(t *testing.T) {
	defer goleak.VerifyNone(t)
	a, clock := newTestActor(t, true)
	a.timers.arm(timerPlayout, 500*time.Millisecond)
	a.timers.arm(timerThinker, 700*time.Millisecond)

	a.windDown(context.Background(), "test stop")
	clock.Advance(5 * time.Second)

	for {
		select {
		case f := <-a.timerFire:
			if a.timers.live(f) {
				t.Fatalf("ghost fire accepted after stop: %s", f.Kind)
			}
		default:
			return
		}
	}
}

// ---------------------------------------------------------------------------
// Tasks 12 & 13, done-when: "send 5 s, heartbeat says 2.1 s played, barge-in
// => Truncate called with 2100 +/- one frame."
// ---------------------------------------------------------------------------

func TestBargeInTruncatesTheVendorHistoryAtHeardMs(t *testing.T) {
	defer goleak.VerifyNone(t)
	a, clock := newTestActor(t, true)
	defer a.timers.cancelAll()

	speaker := fakes.NewFakeSpeaker()
	sess, err := speaker.Start(context.Background(), ports.SessionCfg{SessionID: "sess-1"})
	if err != nil {
		t.Fatalf("start speaker: %v", err)
	}
	a.speaking = sess
	a.state = StateSpeaking

	a.playout.begin("item-1", clock.Now())
	a.playout.sent(pcmFor(5*time.Second), defaultSampleRate)
	clock.Advance(2100 * time.Millisecond)
	a.playout.heartbeat("item-1", 2100, clock.Now())

	a.bargeIn(context.Background())

	fs := sess.(*fakes.FakeSpeakerSession)
	if got := fs.CancelCount(); got != 1 {
		t.Fatalf("CancelResponse called %d times, want 1", got)
	}
	truncs := fs.Truncations()
	if len(truncs) != 1 {
		t.Fatalf("Truncate called %d times, want 1", len(truncs))
	}
	// One 24 kHz frame is ~20 ms; the plan allows +/- one frame.
	if truncs[0].ItemID != "item-1" || truncs[0].HeardMs < 2080 || truncs[0].HeardMs > 2120 {
		t.Fatalf("Truncate(%q, %d), want (item-1, 2100 +/- one frame)",
			truncs[0].ItemID, truncs[0].HeardMs)
	}
	if a.state != StateListening {
		t.Fatalf("state = %s, want LISTENING", a.state)
	}
}

func TestAPersonaThatDoesNotYieldRecordsTheAttemptAndKeepsTalking(t *testing.T) {
	defer goleak.VerifyNone(t)
	// barge_in_allowed=false: the interviewer is talked over. That is not
	// nothing to report — an ignored interruption attempt is feedback about
	// how the manager handled the turn.
	a, clock := newTestActor(t, false)
	defer a.timers.cancelAll()

	speaker := fakes.NewFakeSpeaker()
	sess, _ := speaker.Start(context.Background(), ports.SessionCfg{SessionID: "sess-1"})
	a.speaking = sess
	a.state = StateSpeaking
	a.playout.begin("item-1", clock.Now())
	a.playout.sent(pcmFor(2*time.Second), defaultSampleRate)

	a.bargeIn(context.Background())

	fs := sess.(*fakes.FakeSpeakerSession)
	if fs.CancelCount() != 0 || len(fs.Truncations()) != 0 {
		t.Fatal("a non-yielding persona must not cancel or truncate")
	}
	if a.state != StateSpeaking {
		t.Fatalf("state = %s, want SPEAKING — the persona keeps the floor", a.state)
	}
}
