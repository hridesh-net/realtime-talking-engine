package session

import (
	"context"
	"testing"
	"time"

	"go.uber.org/goleak"

	"skillbrew/engine/internal/fakes"
	"skillbrew/engine/internal/ports"
)

// drive runs the actor until it has processed everything queued, by round-
// tripping a control command through it. The actor is single-threaded, so a
// command it has handled proves every message queued before it was handled
// too — no sleeping, no polling, no real time.
func drive(t *testing.T, a *actor) {
	t.Helper()
	a.control <- command{Kind: cmdInterviewerJoined}
}

// ---------------------------------------------------------------------------
// Task 15, done-when: "a full fake conversation produces a correct turn table."
// ---------------------------------------------------------------------------

func TestAFullFakeConversationProducesACorrectTurnTable(t *testing.T) {
	defer goleak.VerifyNone(t)

	a, clock := newTestActor(t, true)
	defer a.timers.cancelAll()

	speaker := fakes.NewFakeSpeaker()
	sess, err := speaker.Start(context.Background(), ports.SessionCfg{SessionID: "sess-1"})
	if err != nil {
		t.Fatalf("start speaker: %v", err)
	}
	a.speaking = sess
	ctx := context.Background()

	// --- greeting: interviewer speaks first, persona opens ----------------
	a.transition(StateGreeting, "joined")
	a.handlePartial(ctx, ports.Partial{Text: "Hi, thanks for joining.", Final: true})
	if a.state != StateSpeaking {
		t.Fatalf("after greeting state = %s, want SPEAKING", a.state)
	}
	a.handleSpeakerEvent(ctx, ports.ResponseDone{ResponseID: "r0", ItemID: "i0"})
	if a.state != StateListening {
		t.Fatalf("after opening line state = %s, want LISTENING", a.state)
	}

	// --- turn 2: a confident question, answered unaided -------------------
	clock.Advance(time.Second)
	a.handlePartial(ctx, ports.Partial{Text: "Tell me about"})
	clock.Advance(2 * time.Second)
	a.handlePartial(ctx, ports.Partial{Text: "Tell me about your last role.", Final: true})
	a.handlePregate(ctx, pregateVerdict{Skill: "Redis", Defer: false, Turn: a.turn})

	if a.state != StatePreAnswer {
		t.Fatalf("state = %s, want PRE_ANSWER after a confident verdict", a.state)
	}
	if !a.timers.isArmed(timerPause) {
		t.Fatal("the human-pause delay should be armed")
	}

	clock.Advance(700 * time.Millisecond)
	a.handleTimer(ctx, <-a.timerFire)
	if a.state != StateSpeaking {
		t.Fatalf("state = %s, want SPEAKING once the pause elapsed", a.state)
	}

	a.handleSpeakerEvent(ctx, ports.OutputTranscriptDelta{Text: "We used it for caching.", ResponseID: "r1"})
	clock.Advance(2 * time.Second)
	a.handleSpeakerEvent(ctx, ports.ResponseDone{ResponseID: "r1", ItemID: "i1"})

	// --- turn 3: a probe that defers --------------------------------------
	clock.Advance(time.Second)
	a.handlePartial(ctx, ports.Partial{Text: "How would you scale that?", Final: true})
	a.handlePregate(ctx, pregateVerdict{Skill: "System design", Defer: true, Turn: a.turn})
	// No Thinker is wired in this session, so the defer collapses straight
	// to the contract's own fallback directive — still persona-correct
	// behaviour, and marked so the grader discounts depth on this turn.
	if a.state != StateSpeaking {
		t.Fatalf("state = %s, want SPEAKING via the fallback path", a.state)
	}
	if !a.fallbackUsed {
		t.Fatal("a defer with no Thinker must be marked as having used the fallback")
	}

	turns := a.Turns()
	if len(turns) != 5 {
		t.Fatalf("got %d turns, want 5:\n%+v", len(turns), turns)
	}

	want := []struct {
		speaker     string
		text        string
		probedSkill string
		deferred    bool
	}{
		{speakerHuman, "Hi, thanks for joining.", "", false},
		{speakerPersona, "", "", false}, // opening line; contract has none here
		{speakerHuman, "Tell me about your last role.", "Redis", false},
		{speakerPersona, "We used it for caching.", "Redis", false},
		{speakerHuman, "How would you scale that?", "System design", true},
	}
	for i, w := range want {
		got := turns[i]
		if got.Speaker != w.speaker || got.Text != w.text {
			t.Errorf("turn %d = {%s %q}, want {%s %q}", i, got.Speaker, got.Text, w.speaker, w.text)
		}
		if got.ProbedSkill != w.probedSkill || got.Deferred != w.deferred {
			t.Errorf("turn %d skill/defer = %q/%v, want %q/%v",
				i, got.ProbedSkill, got.Deferred, w.probedSkill, w.deferred)
		}
	}

	// The interviewer's turn spans from their first partial to their final,
	// not from the moment they stopped speaking — a manager who took eight
	// seconds to ask a question and one who took two are different, and the
	// grader can only see it if the record carries it.
	if turns[2].EndMs-turns[2].StartMs != 2000 {
		t.Errorf("turn 2 spans %d..%d ms, want a 2000 ms question",
			turns[2].StartMs, turns[2].EndMs)
	}
	// The last probe deferred, and that is recorded on the interviewer's
	// turn: "what did the manager ask that the persona could not answer".
	if !turns[4].Deferred || turns[4].ProbedSkill != "System design" {
		t.Errorf("turn 4 = %+v, want a deferred System design probe", turns[4])
	}
}

// ---------------------------------------------------------------------------
// Sentence bounds — plan §6 layer 5, the one ceiling layer that is a real
// guarantee rather than best-effort model compliance.
// ---------------------------------------------------------------------------

func TestAResponseThatRunsLongIsTrimmed(t *testing.T) {
	defer goleak.VerifyNone(t)

	a, _ := newTestActor(t, true) // MaxSentences: 3
	defer a.timers.cancelAll()

	speaker := fakes.NewFakeSpeaker()
	sess, _ := speaker.Start(context.Background(), ports.SessionCfg{SessionID: "s"})
	a.speaking = sess
	ctx := context.Background()

	a.state = StateSpeaking
	a.turns.begin(1, speakerPersona, testNow)
	for _, delta := range []string{
		"One. ", "Two. ", "Three. ", // allowance spent, grace still open
	} {
		a.handleSpeakerEvent(ctx, ports.OutputTranscriptDelta{Text: delta})
	}
	fs := sess.(*fakes.FakeSpeakerSession)
	if fs.CancelCount() != 0 {
		t.Fatal("three sentences is within the allowance; nothing should be cut")
	}

	// A fourth sentence begins: the grace clause is over.
	a.handleSpeakerEvent(ctx, ports.OutputTranscriptDelta{Text: "And another"})
	if fs.CancelCount() != 1 {
		t.Fatalf("CancelResponse called %d times, want 1 once the allowance is exceeded", fs.CancelCount())
	}
	if a.turns.open == nil || !a.turns.open.Trimmed {
		t.Fatal("the turn record must mark that it was trimmed")
	}
}

func TestTrimWaitsForTheSentenceInProgressToFinish(t *testing.T) {
	// Cutting mid-sentence sounds like a dropped call, not like a person
	// finishing a thought.
	defer goleak.VerifyNone(t)

	a, _ := newTestActor(t, true)
	defer a.timers.cancelAll()
	speaker := fakes.NewFakeSpeaker()
	sess, _ := speaker.Start(context.Background(), ports.SessionCfg{SessionID: "s"})
	a.speaking = sess
	a.state = StateSpeaking
	a.turns.begin(1, speakerPersona, testNow)

	// Two complete sentences and a third mid-flight: still under the bound.
	a.handleSpeakerEvent(context.Background(),
		ports.OutputTranscriptDelta{Text: "One. Two. Three is still going"})

	if sess.(*fakes.FakeSpeakerSession).CancelCount() != 0 {
		t.Fatal("a sentence in progress must be allowed to finish")
	}
}

func TestSentenceCountingIgnoresWhitespaceAndEmptyDeltas(t *testing.T) {
	var c sentenceCounter
	if c.feed("   ", 3) || c.feed("", 3) {
		t.Fatal("whitespace alone starts no sentence")
	}
	if c.completed != 0 || c.pendingText {
		t.Fatalf("counter moved on whitespace: completed=%d pending=%v", c.completed, c.pendingText)
	}
	// Terminators with no text before them are punctuation noise, not
	// sentences — a stream that opens with "..." must not spend the
	// allowance.
	c.feed("...", 3)
	if c.completed != 0 {
		t.Fatalf("completed = %d, want 0 — no text preceded those terminators", c.completed)
	}
}
