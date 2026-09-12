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
	// Two alarms are due by the deadline: the grace pause that starts the
	// stall cover, then the Thinker deadline itself.
	clock.Advance(thinkerDeadline)
	for range 2 {
		a.handleTimer(context.Background(), <-a.timerFire)
	}

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

func TestDeferPublishesCanonicalHarnessContextBeforeRequest(t *testing.T) {
	defer goleak.VerifyNone(t)

	a, _, _, _ := deferRig(t, nil)
	defer a.release()
	a.harness.recordHuman("describe the cache", true, "human-2", testNow, 2)
	a.harness.recordPersonaFinal("I would keep that vague.", "", testNow, 2)

	enterDefer(a)
	thinker := a.thinker.(*fakes.FakeThinker)
	snapshots := thinker.HarnessSnapshots()
	if len(snapshots) != 1 {
		t.Fatalf("harness snapshots = %d, want 1", len(snapshots))
	}
	snapshot := snapshots[0]
	if snapshot.Version == 0 || snapshot.CurrentTurn != 3 {
		t.Fatalf("snapshot metadata = %+v", snapshot)
	}
	if len(snapshot.Turns) != 1 || snapshot.Turns[0].Human != "describe the cache" || snapshot.Turns[0].Persona != "I would keep that vague." {
		t.Fatalf("snapshot turns = %+v", snapshot.Turns)
	}
}

// TestAnInterimRevisionDuringDeferDoesNotDiscardTheNote is the latency rule
// from the harness diagram. An interviewer who adds "um, and also" while the
// reasoning model is still working changes the interim transcript, not the
// finalized history the note was reasoned from — and the first draft of the
// context guard compared against the interim revision counter, which made
// exactly that trailing "um" cost the persona its answer.
func TestAnInterimRevisionDuringDeferDoesNotDiscardTheNote(t *testing.T) {
	defer goleak.VerifyNone(t)

	a, _, fs, _ := deferRig(t, nil)
	defer a.release()
	enterDefer(a)
	version := a.harness.historyVersion(a.turn)
	a.handlePartial(context.Background(), ports.Partial{Text: "um, and also", ItemID: "human-new"})

	a.handleNote(context.Background(), thinkerNote{
		Turn: 3, ContextVersion: version, Note: ports.Note{Text: "the note"},
	})
	if len(fs.Responses()) != 1 {
		t.Fatalf("responses = %d; an interim revision must not discard the note", len(fs.Responses()))
	}
}

// TestLateNoteWithStaleHarnessVersionIsDiscarded is the other half of the
// guard: a note reasoned from a history that has since gained a finalized
// turn answers a conversation that no longer exists.
func TestLateNoteWithStaleHarnessVersionIsDiscarded(t *testing.T) {
	defer goleak.VerifyNone(t)

	a, _, fs, _ := deferRig(t, nil)
	defer a.release()
	enterDefer(a)
	version := a.harness.historyVersion(a.turn)
	a.harness.recordPersonaFinal("a finalized earlier answer", "", testNow.Add(time.Second), 2)
	if a.harness.historyVersion(a.turn) == version {
		t.Fatal("finalizing an earlier turn did not move the history version")
	}

	a.handleNote(context.Background(), thinkerNote{
		Turn: 3, ContextVersion: version, Note: ports.Note{Text: "late note"},
	})
	if len(fs.Responses()) != 0 {
		t.Fatal("a note from an older harness history created a response")
	}
}

// TestAClosedPersonaTurnRefreshesTheThinker is Window B of the harness
// diagram: when the persona stops speaking, the reasoning model gets what was
// actually said and what the persona is now committed to, so the next
// question streams into a Thinker that already holds the right history.
// Before this, Reset was an interface method nothing called and the Thinker
// reasoned from the ledger as it stood at connect for the whole interview.
func TestAClosedPersonaTurnRefreshesTheThinker(t *testing.T) {
	defer goleak.VerifyNone(t)

	a, _, fs, led := deferRig(t, nil)
	defer a.release()
	ctx := context.Background()
	a.state = StateSpeaking
	a.turn = 3
	a.harness.recordHuman("what does Redis do under load", true, "human-3", testNow, 3)
	a.turns.begin(3, speakerPersona, testNow)
	led.Append("Redis", "we shard by tenant", ports.StanceAsserted, ports.OriginSpoken, 3, testNow)

	a.handleSpeakerEvent(ctx, ports.OutputTranscriptDelta{Text: "We shard by tenant.", ResponseID: "r3"})
	a.handleSpeakerEvent(ctx, ports.ResponseDone{ResponseID: "r3"})

	thinker := a.thinker.(*fakes.FakeThinker)
	resets := thinker.Resets()
	if len(resets) != 1 || !strings.Contains(resets[0], "we shard by tenant") {
		t.Fatalf("resets = %#v, want one carrying the spoken claim", resets)
	}
	snapshots := thinker.HarnessSnapshots()
	if len(snapshots) != 1 {
		t.Fatalf("harness snapshots = %d, want the Window B publish", len(snapshots))
	}
	got := snapshots[0]
	if got.CurrentTurn != 4 || len(got.Turns) != 1 || got.Turns[0].Turn != 3 ||
		got.Turns[0].Human != "what does Redis do under load" || got.Turns[0].Persona != "We shard by tenant." {
		t.Fatalf("Window B snapshot = %+v", got)
	}
	if a.state != StateListening || len(fs.Responses()) != 0 {
		t.Fatalf("state = %s, responses = %d after response done", a.state, len(fs.Responses()))
	}

	// Window A then publishes the same history under the same version, so a
	// Thinker keeping its speculation on an unchanged version stays warm.
	a.harness.recordHuman("and how do you rebalance", true, "human-4", testNow.Add(time.Second), 4)
	a.turn = 4
	a.probedSkill = "Redis"
	a.deferred = true
	a.beginDefer(ctx)
	snapshots = thinker.HarnessSnapshots()
	if len(snapshots) != 2 || snapshots[1].Version != got.Version || snapshots[1].CurrentTurn != 4 {
		t.Fatalf("defer-time snapshot = %+v, want the Window B version %d republished for turn 4", snapshots[len(snapshots)-1], got.Version)
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
	a.playout.sent(pcmFor(500*time.Millisecond), defaultSampleRate)

	a.bargeIn(context.Background())

	if a.timers.isArmed(timerThinker) {
		t.Fatal("the thinker deadline must not outlive the turn it belonged to")
	}
	if a.state != StateListening {
		t.Fatalf("state = %s, want LISTENING", a.state)
	}
}

// ---------------------------------------------------------------------------
// The latency rule and the two windows (docs/LIVE_TALKING_ENGINE_HARNESS).
// ---------------------------------------------------------------------------

// stallClip is a fake stall clip of the given length at the engine rate.
func stallClip(d time.Duration) ports.PCM16Audio {
	return ports.PCM16Audio{
		Samples:      make([]byte, int(d.Milliseconds())*defaultSampleRate/1000*bytesPerSamplePCM16),
		SampleRateHz: defaultSampleRate,
	}
}

// deferRigWithStall is deferRig with a warmed stall bank of one clip.
func deferRigWithStall(t *testing.T, clip time.Duration, script []fakes.NoteScriptEntry) (
	*actor, *fakes.FakeClock, *fakes.FakeSpeakerSession, *fakes.FakeStallBank,
) {
	t.Helper()
	a, clock, fs, _ := deferRig(t, script)
	bank := fakes.NewFakeStallBank(stallClip(time.Second), stallClip(clip))
	a.stall = bank
	return a, clock, fs, bank
}

// TestANoteAlreadyThereLandsInsideThePauseWithNoStallClip is the diagram's
// primary path: the Thinker read the question as it streamed and its note
// is waiting when the interviewer stops, so the direction lands inside the
// persona's own pause and no time-buying phrase is spoken. The first build
// had no stall path at all — a defer was a bare pause until the note — and
// the plan's version played the clip on every defer; both are what the
// latency rule forbids.
func TestANoteAlreadyThereLandsInsideThePauseWithNoStallClip(t *testing.T) {
	defer goleak.VerifyNone(t)

	a, _, fs, bank := deferRigWithStall(t, 200*time.Millisecond, []fakes.NoteScriptEntry{{Note: ports.Note{Text: "keep it vague"}}})
	defer a.release()
	ctx := context.Background()

	enterDefer(a)
	if !a.timers.isArmed(timerPause) || !a.timers.isArmed(timerThinker) {
		t.Fatal("a defer must arm both the grace pause and the Thinker deadline")
	}
	// The scripted note is delivered at once; the pump hands it to the actor.
	a.handleNote(ctx, <-a.notes)

	if a.state != StateSpeaking {
		t.Fatalf("state = %s, want SPEAKING straight from DEFERRED", a.state)
	}
	if bank.PickCalls() != 0 {
		t.Fatal("a note that was already there must not be covered by a stall clip")
	}
	if len(fs.Responses()) != 1 || !strings.Contains(strings.Join(fs.SystemItems(), " "), "keep it vague") {
		t.Fatalf("responses = %d, items = %v", len(fs.Responses()), fs.SystemItems())
	}
	if a.timers.isArmed(timerPause) || a.timers.isArmed(timerThinker) {
		t.Fatal("the note must disarm both the grace pause and the deadline")
	}
}

// TestALateNoteIsCoveredByAStallClipThenInjected is the cover for the miss:
// the pause runs out, the persona buys time with one of its own phrases in
// its own voice, and the note lands under it. The phrase was said, so it is
// part of the persona's turn record and of the Thinker's history, joined
// with the answer that follows.
func TestALateNoteIsCoveredByAStallClipThenInjected(t *testing.T) {
	defer goleak.VerifyNone(t)

	a, clock, fs, bank := deferRigWithStall(t, 200*time.Millisecond, []fakes.NoteScriptEntry{{Miss: true}})
	defer a.release()
	ctx := context.Background()

	enterDefer(a)
	clock.Advance(a.stallGrace())
	a.handleTimer(ctx, <-a.timerFire)

	if a.state != StateStalling {
		t.Fatalf("state = %s, want STALLING once the grace pause elapsed", a.state)
	}
	if bank.PickCalls() != 1 {
		t.Fatalf("stall clips picked = %d, want 1", bank.PickCalls())
	}
	if !a.timers.isArmed(timerPlayout) || !a.timers.isArmed(timerThinker) {
		t.Fatal("the clip playout and the Thinker deadline must both be armed while stalling")
	}
	if open := a.turns.open; open == nil || open.Speaker != speakerPersona || !strings.HasPrefix(open.Text, "stall clip 0") {
		t.Fatalf("open turn = %+v, want the persona's stall phrase", open)
	}

	a.handleNote(ctx, thinkerNote{Turn: 3, Note: ports.Note{Text: "say you only read about it"}})
	if a.state != StateSpeaking || len(fs.Responses()) != 1 {
		t.Fatalf("state = %s, responses = %d after the note", a.state, len(fs.Responses()))
	}
	if a.fallbackUsed {
		t.Fatal("a note that arrived under the stall clip is not a fallback")
	}
	a.handleSpeakerEvent(ctx, ports.OutputTranscriptDelta{Text: "I only read about it.", ResponseID: "r3"})
	a.handleSpeakerEvent(ctx, ports.ResponseDone{ResponseID: "r3"})

	records := a.Turns()
	last := records[len(records)-1]
	if last.Speaker != speakerPersona || last.Text != "stall clip 0 I only read about it." {
		t.Fatalf("persona turn = %+v, want the stall phrase and the answer in one record", last)
	}
	turns := a.harness.snapshot(4).Turns
	if len(turns) == 0 || turns[len(turns)-1].Persona != "stall clip 0 I only read about it." {
		t.Fatalf("harness persona text = %+v, want phrase and answer joined", turns)
	}
}

// TestAStallClipRunningOutLeavesThePersonaQuietUntilTheDeadline: the clip is
// shorter than the deadline, and when it ends nothing else is said — the
// accepted silence after an in-character stall, never a second canned
// phrase — until the note or the deadline moves the turn on.
func TestAStallClipRunningOutLeavesThePersonaQuietUntilTheDeadline(t *testing.T) {
	defer goleak.VerifyNone(t)

	a, clock, fs, bank := deferRigWithStall(t, 200*time.Millisecond, []fakes.NoteScriptEntry{{Miss: true}})
	defer a.release()
	ctx := context.Background()

	enterDefer(a)
	clock.Advance(a.stallGrace())
	a.handleTimer(ctx, <-a.timerFire) // grace → stall clip
	clock.Advance(200 * time.Millisecond)
	a.handleTimer(ctx, <-a.timerFire) // clip played out

	if a.state != StateStalling {
		t.Fatalf("state = %s, want STALLING still after the clip", a.state)
	}
	if bank.PickCalls() != 1 || len(fs.Responses()) != 0 {
		t.Fatalf("picks = %d, responses = %d; the persona must stay quiet", bank.PickCalls(), len(fs.Responses()))
	}

	clock.Advance(thinkerDeadline)
	a.handleTimer(ctx, <-a.timerFire) // the deadline
	if a.state != StateSpeaking || !a.fallbackUsed || len(fs.Responses()) != 1 {
		t.Fatalf("state = %s, fallback = %v, responses = %d after the deadline", a.state, a.fallbackUsed, len(fs.Responses()))
	}
}

// TestAConfidentTurnTakesTheNoteInsideThePause is Window A on the CONFIDENT
// path. The Thinker has been reasoning since the first words and that call
// is already paid for; if its direction lands inside the persona's pause it
// steers this answer too. Before this the note was requested only on DEFER,
// and every confident turn threw the speculation away.
func TestAConfidentTurnTakesTheNoteInsideThePause(t *testing.T) {
	defer goleak.VerifyNone(t)

	a, _, fs, _ := deferRig(t, []fakes.NoteScriptEntry{{Note: ports.Note{
		Text: "mention the tenant sharding", ClaimsToMake: []string{"we shard by tenant"},
	}}})
	defer a.release()
	ctx := context.Background()
	a.state = StateListening
	a.turn = 3
	a.probedSkill = "Redis"

	a.beginAnswer(ctx, "pregate confident")
	if a.state != StatePreAnswer || !a.timers.isArmed(timerPause) {
		t.Fatalf("state = %s, pause armed = %v", a.state, a.timers.isArmed(timerPause))
	}
	a.handleNote(ctx, <-a.notes)

	if a.state != StateSpeaking || len(fs.Responses()) != 1 {
		t.Fatalf("state = %s, responses = %d", a.state, len(fs.Responses()))
	}
	if !strings.Contains(strings.Join(fs.SystemItems(), " "), "tenant sharding") {
		t.Fatalf("the note did not reach the Speaker: %v", fs.SystemItems())
	}
	if a.timers.isArmed(timerPause) {
		t.Fatal("the note must cancel the pause; the answer starts now")
	}
	if a.fallbackUsed {
		t.Fatal("a confident turn never uses the fallback directive")
	}
}

// TestAConfidentTurnAnswersUnaidedWhenTheNoteIsLate: CONFIDENT means the
// Speaker may answer alone, so a note that misses the pause is logged and
// nothing waits for it — no stall, no fallback directive.
func TestAConfidentTurnAnswersUnaidedWhenTheNoteIsLate(t *testing.T) {
	defer goleak.VerifyNone(t)

	a, clock, fs, _ := deferRig(t, []fakes.NoteScriptEntry{{Miss: true}})
	defer a.release()
	ctx := context.Background()
	a.state = StateListening
	a.turn = 3

	a.beginAnswer(ctx, "pregate confident")
	clock.Advance(700 * time.Millisecond)
	a.handleTimer(ctx, <-a.timerFire)

	if a.state != StateSpeaking || len(fs.Responses()) != 1 {
		t.Fatalf("state = %s, responses = %d", a.state, len(fs.Responses()))
	}
	if a.fallbackUsed || len(fs.SystemItems()) != 0 {
		t.Fatalf("fallback = %v, items = %v; a confident turn answers unaided", a.fallbackUsed, fs.SystemItems())
	}
	// A note arriving now is for the log only: the persona is talking.
	a.handleNote(ctx, thinkerNote{Turn: 3, Note: ports.Note{Text: "too late"}})
	if len(fs.SystemItems()) != 0 {
		t.Fatal("nothing is injected while the Speaker is talking")
	}
}
