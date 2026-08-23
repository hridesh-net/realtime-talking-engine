package session

import (
	"context"
	"strings"
	"testing"
	"time"

	"go.uber.org/goleak"

	"skillbrew/engine/internal/contract"
	"skillbrew/engine/internal/fakes"
	"skillbrew/engine/internal/ledger"
	"skillbrew/engine/internal/ports"
)

// deferRig builds an actor with both models and a seeded ledger.
func deferRig(t *testing.T, script []fakes.NoteScriptEntry) (
	*actor, *fakes.FakeClock, *fakes.FakeSpeakerSession, *ledger.Ledger,
) {
	t.Helper()
	clock := fakes.NewFakeClock(testNow)
	c := testContract(true)
	c.KnowledgeCeiling = map[string]int{"Redis": 2, "Go": 7}
	c.TurnPolicy.OnUnknownQuestion = "admit you have only read about it and keep it short"
	c.UnlockSpec = contract.UnlockSpec{Kind: "conditional", Condition: "asks for a specific outage"}

	led := ledger.New([]contract.PrecompiledBelief{
		{ClaimID: "b1", Skill: "Redis", Statement: "Redis is single-threaded"},
	}, testNow)

	a := newActor("sess-1", c, clock, quietLogger(), nil, Deps{
		Thinker: fakes.NewFakeThinker(script...),
		Ledger:  led,
	})
	speaker := fakes.NewFakeSpeaker()
	sess, err := speaker.Start(context.Background(), ports.SessionCfg{SessionID: "sess-1"})
	if err != nil {
		t.Fatalf("start speaker: %v", err)
	}
	a.speaking = sess
	return a, clock, sess.(*fakes.FakeSpeakerSession), led
}

// enterDefer drives the actor to a deferred Redis probe.
func enterDefer(a *actor) {
	a.state = StateListening
	a.turn = 3
	a.probedSkill = "Redis"
	a.deferred = true
	a.beginDefer(context.Background())
}

func TestANoteArrivingInTimeIsInjectedAsContextNotSpokenVerbatim(t *testing.T) {
	defer goleak.VerifyNone(t)

	a, _, fs, _ := deferRig(t, []fakes.NoteScriptEntry{{Note: ports.Note{
		Text:         "you half-remember this; keep it vague, two sentences",
		ClaimsToMake: []string{"Redis is single-threaded"},
	}}})
	defer a.release()

	enterDefer(a)
	if a.state != StateDeferred {
		t.Fatalf("state = %s, want DEFERRED", a.state)
	}
	if !a.timers.isArmed(timerThinker) {
		t.Fatal("the thinker deadline must be armed while the stall plays")
	}

	a.handleNote(context.Background(), thinkerNote{Turn: 3, Note: ports.Note{
		Text:         "you half-remember this; keep it vague, two sentences",
		ClaimsToMake: []string{"Redis is single-threaded"},
	}})

	// The note grounds the response; the speech model still does the
	// talking, so there is no register seam between stall and answer.
	items := fs.SystemItems()
	if len(items) == 0 || !strings.Contains(strings.Join(items, " "), "keep it vague") {
		t.Fatalf("note was not injected as a system item: %v", items)
	}
	if len(fs.Responses()) != 1 {
		t.Fatalf("got %d responses, want 1 after the note", len(fs.Responses()))
	}
	if a.state != StateSpeaking {
		t.Fatalf("state = %s, want SPEAKING", a.state)
	}
	if a.fallbackUsed {
		t.Fatal("a note that arrived in time must not be marked as a fallback")
	}
}

func TestAMissedDeadlineFallsBackToTheContractsOwnDirective(t *testing.T) {
	// The floor of plan §6 layer 3: when the reasoning model does not
	// answer, the worst case is the persona's own documented behaviour,
	// not an invented answer.
	defer goleak.VerifyNone(t)

	a, clock, fs, _ := deferRig(t, []fakes.NoteScriptEntry{{Miss: true}})
	defer a.release()

	enterDefer(a)
	clock.Advance(thinkerDeadline)
	a.handleTimer(context.Background(), <-a.timerFire)

	if !a.fallbackUsed {
		t.Fatal("a missed deadline must be recorded, so the grader discounts depth")
	}
	joined := strings.Join(fs.SystemItems(), " ")
	if !strings.Contains(joined, "only read about it") {
		t.Fatalf("the contract's own directive should have stood in: %v", fs.SystemItems())
	}
	if a.state != StateSpeaking {
		t.Fatalf("state = %s, want SPEAKING", a.state)
	}
}

func TestANoteForATurnThatHasMovedOnIsDiscarded(t *testing.T) {
	// A late note driving the wrong turn is the ghost-utterance failure in
	// another guise.
	defer goleak.VerifyNone(t)

	a, _, fs, _ := deferRig(t, nil)
	defer a.release()

	enterDefer(a)
	a.turn = 4 // the interview moved on

	a.handleNote(context.Background(), thinkerNote{Turn: 3, Note: ports.Note{Text: "stale"}})
	if len(fs.Responses()) != 0 {
		t.Fatal("a note for a closed turn must not create a response")
	}
}

// ---------------------------------------------------------------------------
// Task 34 — the contradiction guard
// ---------------------------------------------------------------------------

func TestANoteThatWouldContradictThePersonaIsDowngraded(t *testing.T) {
	defer goleak.VerifyNone(t)

	a, _, fs, _ := deferRig(t, nil)
	defer a.release()
	enterDefer(a)

	// The ledger already holds "Redis is single-threaded" from turn 0.
	a.handleNote(context.Background(), thinkerNote{Turn: 3, Note: ports.Note{
		Text:         "tell them Redis is not single-threaded",
		ClaimsToMake: []string{"Redis is not single-threaded"},
	}})

	joined := strings.Join(fs.SystemItems(), " ")
	if strings.Contains(joined, "is not single-threaded") {
		t.Fatalf("the contradicting note was injected anyway: %v", fs.SystemItems())
	}
	if !strings.Contains(joined, "Restate what you already said") {
		t.Fatalf("expected a downgrade to a restatement, got: %v", fs.SystemItems())
	}
}

// ---------------------------------------------------------------------------
// Task 36 — unlock. The Thinker assesses; the actor decides.
// ---------------------------------------------------------------------------

func TestTheActorOwnsTheUnlockFlipAndItIsMonotonic(t *testing.T) {
	defer goleak.VerifyNone(t)

	a, _, _, _ := deferRig(t, nil)
	defer a.release()
	enterDefer(a)

	a.handleNote(context.Background(), thinkerNote{Turn: 3, Note: ports.Note{
		Text:   "go deeper now",
		Unlock: &ports.UnlockAssessment{Met: true, Evidence: "asked about the outage"},
	}})
	if !a.unlocked || a.unlockTurn != 3 {
		t.Fatalf("unlocked=%v at turn %d, want true at 3", a.unlocked, a.unlockTurn)
	}

	// Depth once earned is never taken back.
	a.turn = 6
	a.handleNote(context.Background(), thinkerNote{Turn: 6, Note: ports.Note{
		Text: "back off", Unlock: &ports.UnlockAssessment{Met: false},
	}})
	if !a.unlocked || a.unlockTurn != 3 {
		t.Fatalf("unlock regressed to %v at turn %d", a.unlocked, a.unlockTurn)
	}
}

func TestANeverUnlockPersonaCannotBeTalkedIntoUnlocking(t *testing.T) {
	// unlock_spec.kind == "never" short-circuits assessment. A Thinker
	// claiming the condition was met does not get to override the contract.
	defer goleak.VerifyNone(t)

	a, _, _, _ := deferRig(t, nil)
	defer a.release()
	a.contract.UnlockSpec = contract.UnlockSpec{Kind: "never"}
	enterDefer(a)

	a.handleNote(context.Background(), thinkerNote{Turn: 3, Note: ports.Note{
		Text:   "they earned it",
		Unlock: &ports.UnlockAssessment{Met: true, Evidence: "rapport"},
	}})
	if a.unlocked {
		t.Fatal("a never-unlock persona must stay locked whatever the Thinker says")
	}
}

func TestUnlockRaisesTheDepthDirectiveOnLaterTurns(t *testing.T) {
	defer goleak.VerifyNone(t)

	a, _, fs, _ := deferRig(t, nil)
	defer a.release()

	a.state = StatePreAnswer
	a.createResponse(context.Background(), "locked")
	a.state = StatePreAnswer
	a.unlocked = true
	a.createResponse(context.Background(), "unlocked")

	got := fs.Responses()
	if len(got) != 2 {
		t.Fatalf("got %d responses, want 2", len(got))
	}
	if got[0].AnswerDepth == got[1].AnswerDepth {
		t.Fatalf("depth did not change on unlock: both %q", got[0].AnswerDepth)
	}
	if got[1].AnswerDepth != "thorough" {
		t.Fatalf("post-unlock depth = %q, want thorough", got[1].AnswerDepth)
	}
}

// ---------------------------------------------------------------------------
// Task 35 — the two re-injection cadences
// ---------------------------------------------------------------------------

func TestALowCeilingProbeReAssertsTheCeilingImmediately(t *testing.T) {
	// Not on a cadence: the moment the interviewer probes something the
	// persona cannot discuss is exactly when prompt adherence drifts.
	defer goleak.VerifyNone(t)

	a, _, fs, _ := deferRig(t, nil)
	defer a.release()
	a.probedSkill = "Redis" // ceiling 2
	a.state = StatePreAnswer
	a.createResponse(context.Background(), "answering")

	if !strings.Contains(strings.Join(fs.SystemItems(), " "), "Redis: level 2/10") {
		t.Fatalf("expected a ceiling re-assertion, got: %v", fs.SystemItems())
	}
}

func TestTheLedgerSummaryIsReInjectedOnItsCadence(t *testing.T) {
	defer goleak.VerifyNone(t)

	a, _, fs, led := deferRig(t, nil)
	defer a.release()
	led.Append("Go", "we ship weekly", ports.StanceAsserted, ports.OriginSpoken, 1, testNow)

	a.turn = ledgerRefreshTurns
	a.state = StatePreAnswer
	a.createResponse(context.Background(), "answering")

	if !strings.Contains(strings.Join(fs.SystemItems(), " "), "Things you have already said") {
		t.Fatalf("expected the ledger summary, got: %v", fs.SystemItems())
	}
}

func TestTheStallTimerDiesWithABargeInDuringStalling(t *testing.T) {
	defer goleak.VerifyNone(t)

	a, clock, _, _ := deferRig(t, []fakes.NoteScriptEntry{{Miss: true}})
	defer a.release()

	enterDefer(a)
	a.playout.begin("stall-1", clock.Now())
	a.playout.sent(pcmFor(500 * time.Millisecond))

	a.bargeIn(context.Background())

	if a.timers.isArmed(timerThinker) {
		t.Fatal("the thinker deadline must not outlive the turn it belonged to")
	}
	if a.state != StateListening {
		t.Fatalf("state = %s, want LISTENING", a.state)
	}
}
