package session

import (
	"context"
	"testing"
	"time"

	"go.uber.org/goleak"

	"skillbrew/engine/internal/fakes"
	"skillbrew/engine/internal/ports"
)

func TestHarnessContextOrdersEntriesAndSequencesRevisions(t *testing.T) {
	h := newHarnessContext(16)
	first := testNow
	second := first.Add(time.Millisecond)

	h.recordHuman("tell me", false, "human-1", first, 1)
	h.recordPersonaDelta("I can", "response-1", second, 1)
	h.recordHuman("tell me about yourself", true, "human-1", second, 1)

	entries := h.entriesSnapshot()
	if len(entries) != 2 {
		t.Fatalf("got %d entries, want 2: %+v", len(entries), entries)
	}
	for i := 1; i < len(entries); i++ {
		if entries[i-1].Sequence >= entries[i].Sequence {
			t.Fatalf("sequences are not monotonic: %+v", entries)
		}
	}
	if entries[0].Source != harnessSourcePersona || entries[0].Text != "I can" {
		t.Fatalf("first retained entry = %+v, want persona delta", entries[0])
	}
	if entries[1].Source != harnessSourceHuman || !entries[1].Final || entries[1].Text != "tell me about yourself" {
		t.Fatalf("final human entry = %+v", entries[1])
	}
	if !entries[1].Timestamp.Equal(second) {
		t.Fatalf("timestamp = %v, want %v", entries[1].Timestamp, second)
	}
}

func TestHarnessContextReplacesInterimAndFinalizesPersona(t *testing.T) {
	h := newHarnessContext(16)
	h.recordHuman("what is", false, "human-1", testNow, 2)
	h.recordHuman("what is caching", false, "human-1", testNow.Add(time.Second), 2)
	h.recordHuman("what is caching?", true, "human-1", testNow.Add(2*time.Second), 2)
	h.recordPersonaDelta("We used ", "response-2", testNow.Add(3*time.Second), 2)
	h.recordPersonaDelta("it for speed.", "response-2", testNow.Add(4*time.Second), 2)
	h.finalizePersona("response-2", testNow.Add(5*time.Second), 2)

	entries := h.entriesSnapshot()
	if len(entries) != 2 {
		t.Fatalf("got %d entries, want one human and one persona: %+v", len(entries), entries)
	}
	if !entries[0].Final || entries[0].Text != "what is caching?" {
		t.Fatalf("human entry = %+v", entries[0])
	}
	if !entries[1].Final || entries[1].Text != "We used it for speed." {
		t.Fatalf("persona entry = %+v", entries[1])
	}
	turns := h.finalTurnSnapshot()
	if len(turns) != 1 || turns[0].Human != "what is caching?" || turns[0].Persona != "We used it for speed." {
		t.Fatalf("final snapshot = %+v", turns)
	}
}

func TestHarnessContextCompactsEntriesButRetainsFinalSnapshot(t *testing.T) {
	h := newHarnessContext(2)
	h.recordHuman("one", true, "h1", testNow, 1)
	h.recordPersonaFinal("answer one", "", testNow, 1)
	h.recordHuman("two", true, "h2", testNow, 2)
	h.recordPersonaFinal("answer two", "", testNow, 2)

	entries := h.entriesSnapshot()
	if len(entries) != 2 {
		t.Fatalf("got %d retained entries, want capacity 2", len(entries))
	}
	if entries[0].Turn != 2 || entries[1].Turn != 2 {
		t.Fatalf("old entries were not compacted: %+v", entries)
	}
	turns := h.finalTurnSnapshot()
	if len(turns) != 2 || turns[0].Human != "one" || turns[1].Persona != "answer two" {
		t.Fatalf("compacted final snapshot = %+v", turns)
	}
}

func TestHarnessSnapshotIsVersionedBoundedAndIgnoresStaleRevisions(t *testing.T) {
	h := newHarnessContext(16)
	h.recordHuman("what is caching", false, "human-1", testNow, 1)
	h.recordHuman("what is caching?", true, "human-1", testNow.Add(time.Second), 1)
	h.recordPersonaDelta("We used it", "response-1", testNow.Add(2*time.Second), 1)
	h.finalizePersona("response-1", testNow.Add(3*time.Second), 1)

	snapshot := h.snapshot(2)
	if snapshot.Version == 0 || snapshot.CurrentTurn != 2 {
		t.Fatalf("snapshot metadata = %+v", snapshot)
	}
	if len(snapshot.Turns) != 1 || snapshot.Turns[0].Human != "what is caching?" || snapshot.Turns[0].Persona != "We used it" {
		t.Fatalf("snapshot turns = %+v", snapshot.Turns)
	}
	version := snapshot.Version
	if h.recordHuman("what is caching", false, "human-1", testNow.Add(4*time.Second), 1) {
		t.Fatal("stale revision was accepted after the human item finalized")
	}
	if got := h.snapshot(2); got.Version != version || got.Turns[0].Human != "what is caching?" {
		t.Fatalf("stale revision changed snapshot: before=%+v after=%+v", snapshot, got)
	}
}

// TestHarnessSnapshotIsHistoryOnlyAndItsVersionIgnoresInterimRevisions pins
// what makes the Thinker's speculation survive to end-of-turn: the current
// turn is not in the snapshot (it streams in through FeedPartial), and the
// version only moves when a finalized turn changes.
func TestHarnessSnapshotIsHistoryOnlyAndItsVersionIgnoresInterimRevisions(t *testing.T) {
	h := newHarnessContext(16)
	h.recordHuman("first question", true, "h1", testNow, 1)
	h.recordPersonaFinal("first answer", "", testNow, 1)
	history := h.historyVersion(2)
	if history == 0 {
		t.Fatal("a finalized turn left the history version at zero")
	}

	h.recordHuman("second", false, "h2", testNow.Add(time.Second), 2)
	h.recordHuman("second question", false, "h2", testNow.Add(2*time.Second), 2)
	if got := h.historyVersion(2); got != history {
		t.Fatalf("interim revisions moved the history version %d -> %d", history, got)
	}
	h.recordHuman("second question?", true, "h2", testNow.Add(3*time.Second), 2)
	if got := h.historyVersion(2); got != history {
		t.Fatalf("the current turn's own final moved the history version %d -> %d", history, got)
	}
	snapshot := h.snapshot(2)
	if len(snapshot.Turns) != 1 || snapshot.Turns[0].Turn != 1 || snapshot.Version != history {
		t.Fatalf("snapshot for turn 2 = %+v, want only turn 1 at version %d", snapshot, history)
	}

	h.recordPersonaFinal("second answer", "", testNow.Add(4*time.Second), 2)
	if got := h.historyVersion(3); got <= history {
		t.Fatalf("closing turn 2 did not advance the history version for turn 3: %d <= %d", got, history)
	}
	if got := h.snapshot(3); len(got.Turns) != 2 || got.Turns[1].Persona != "second answer" {
		t.Fatalf("snapshot for turn 3 = %+v", got)
	}
	if got := h.historyVersion(1); got != 0 || len(h.snapshot(1).Turns) != 0 {
		t.Fatalf("turn 1 has history: version %d, turns %+v", got, h.snapshot(1).Turns)
	}
}

func TestActorWiresHumanAndSpeakerTranscriptEventsIntoHarness(t *testing.T) {
	defer goleak.VerifyNone(t)

	// Degraded path: the Speaker's fragments accumulate under the turn's own
	// key and the energy detector's final closes that same key, so the
	// harness holds one cumulative utterance rather than the last fragment.
	speakerASRActor, _ := newTestActor(t, true)
	defer speakerASRActor.timers.cancelAll()
	speakerASRActor.state = StateListening
	speakerASRActor.handleSpeakerEvent(context.Background(), ports.InputTranscript{Text: "speaker "})
	speakerASRActor.handleSpeakerEvent(context.Background(), ports.InputTranscript{Text: "transcript"})
	speakerEntries := speakerASRActor.harness.entriesSnapshot()
	if len(speakerEntries) != 1 || speakerEntries[0].Final || speakerEntries[0].Text != "speaker transcript" {
		t.Fatalf("Speaker fragments were not accumulated in the harness: %+v", speakerEntries)
	}
	speakerASRActor.handleSpeechOnset(context.Background(), ports.VADEvent{Started: false})
	speakerEntries = speakerASRActor.harness.entriesSnapshot()
	if len(speakerEntries) != 1 || !speakerEntries[0].Final || speakerEntries[0].Text != "speaker transcript" {
		t.Fatalf("energy end-of-turn did not finalize the Speaker transcript in the harness: %+v", speakerEntries)
	}
	if speakerASRActor.utterance != "" {
		t.Fatalf("utterance %q survived its own end-of-turn", speakerASRActor.utterance)
	}

	canonicalASRActor, _ := newTestActor(t, true)
	defer canonicalASRActor.timers.cancelAll()
	canonicalASRActor.state = StateListening
	canonicalASRActor.transcriber = fakes.NewFakeTranscriber()
	canonicalASRActor.handleSpeakerEvent(context.Background(), ports.InputTranscript{
		Text: "vendor fallback must not duplicate canonical ASR", Final: true, ItemID: "speaker-human-2",
	})
	if entries := canonicalASRActor.harness.entriesSnapshot(); len(entries) != 0 {
		t.Fatalf("Speaker fallback duplicated an active Transcriber stream: %+v", entries)
	}

	a, _ := newTestActor(t, true)
	defer a.timers.cancelAll()
	a.state = StateListening

	a.handlePartial(context.Background(), ports.Partial{Text: "tell me", ItemID: "human-1"})
	a.handlePartial(context.Background(), ports.Partial{Text: "tell me about yourself", Final: true, ItemID: "human-1"})

	a.state = StateSpeaking
	a.turns.begin(1, speakerPersona, testNow)
	a.handleSpeakerEvent(context.Background(), ports.OutputTranscriptDelta{
		Text: "I build reliable systems.", ResponseID: "response-1",
	})
	a.handleSpeakerEvent(context.Background(), ports.ResponseDone{ResponseID: "response-1"})

	entries := a.harness.entriesSnapshot()
	if len(entries) != 2 {
		t.Fatalf("got %d harness entries, want human + persona: %+v", len(entries), entries)
	}
	if entries[0].Source != harnessSourceHuman || !entries[0].Final || entries[0].Text != "tell me about yourself" {
		t.Fatalf("human harness entry = %+v", entries[0])
	}
	if entries[1].Source != harnessSourcePersona || !entries[1].Final || entries[1].Text != "I build reliable systems." {
		t.Fatalf("persona harness entry = %+v", entries[1])
	}
	if a.state != StateListening {
		t.Fatalf("actor state = %s, want LISTENING", a.state)
	}
}
