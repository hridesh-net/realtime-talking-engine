// Package fakes_test smoke-tests internal/fakes end-to-end: every fake is
// driven the way the session actor (plan §4) will drive it, under
// go test -race, proving the fakes are concurrency-safe and behave
// deterministically.
package fakes_test

import (
	"context"
	"io"
	"slices"
	"strings"
	"sync"
	"testing"
	"time"

	"skillbrew/engine/internal/contract"
	"skillbrew/engine/internal/fakes"
	"skillbrew/engine/internal/ports"
)

// TestFakeClock_DeterministicOrderAndCancel proves the two properties the
// plan calls out explicitly: timers due at the same instant fire in a
// defined, documented order (creation order), and a cancelled timer
// produces zero fires — the "no ghost timer fires after barge-in"
// guarantee.
func TestFakeClock_DeterministicOrderAndCancel(t *testing.T) {
	clock := fakes.NewFakeClock(time.Unix(0, 0))

	const n = 5
	timers := make([]ports.Timer, n)
	seqs := make([]uint64, n)
	for i := 0; i < n; i++ {
		timers[i] = clock.NewTimer(10 * time.Millisecond)
		seqs[i] = uint64(i + 1) // FakeClock assigns seq starting at 1, in creation order.
	}
	// A timer due later must never fire ahead of one due earlier or
	// created earlier at the same instant.
	late := clock.NewTimer(50 * time.Millisecond)

	// Cancel one timer before it is due; it must never fire.
	cancelled := clock.NewTimer(10 * time.Millisecond)
	if !cancelled.Stop() {
		t.Fatalf("Stop() on an un-fired timer = false, want true")
	}

	firedBefore := clock.FiredCount()
	fired := clock.Advance(10 * time.Millisecond)
	if fired != n {
		t.Fatalf("Advance fired %d timers, want %d (the cancelled and the 50ms timer must not fire)", fired, n)
	}

	// FireLog proves the same-instant tie-break order directly, avoiding
	// any race on which goroutine's channel receive happens to resume
	// first.
	if log := clock.FireLog(); !slices.Equal(log, seqs) {
		t.Fatalf("FireLog() = %v, want %v (creation order 1..%d)", log, seqs, n)
	}

	if got := clock.FiredCount() - firedBefore; got != n {
		t.Fatalf("FiredCount delta = %d, want %d", got, n)
	}

	// Each fired timer's own channel must have delivered exactly once.
	for i, tm := range timers {
		select {
		case <-tm.C():
		default:
			t.Fatalf("timer %d never delivered on C()", i)
		}
	}

	// Advance well past the cancelled timer's original due time and the
	// late timer's due time; assert the cancelled timer produced zero
	// fires (ghost-fire check) while the late one now fires.
	fired = clock.Advance(100 * time.Millisecond)
	if fired != 1 {
		t.Fatalf("second Advance fired %d timers, want 1 (only the late timer)", fired)
	}
	select {
	case <-late.C():
	default:
		t.Fatalf("late timer did not fire after advancing past its due time")
	}
	select {
	case <-cancelled.C():
		t.Fatalf("cancelled timer fired — ghost fire after Stop")
	default:
	}
	if pending := clock.Pending(); len(pending) != 0 {
		t.Fatalf("Pending() = %v, want none left pending", pending)
	}
}

// TestFakeClock_ResetDrainsUnreadFire proves Reset on an already-fired,
// unread timer re-arms cleanly instead of deadlocking Advance.
func TestFakeClock_ResetDrainsUnreadFire(t *testing.T) {
	clock := fakes.NewFakeClock(time.Unix(0, 0))
	tm := clock.NewTimer(5 * time.Millisecond)
	if fired := clock.Advance(5 * time.Millisecond); fired != 1 {
		t.Fatalf("Advance fired %d, want 1", fired)
	}
	// Fire value never read off tm.C() before Reset.
	if was := tm.Reset(5 * time.Millisecond); was {
		t.Fatalf("Reset() on an already-fired timer = true, want false")
	}
	if fired := clock.Advance(5 * time.Millisecond); fired != 1 {
		t.Fatalf("Advance after Reset fired %d, want 1", fired)
	}
	select {
	case <-tm.C():
	default:
		t.Fatalf("timer did not deliver its second fire")
	}
}

// TestFakeSpeaker_ScriptedConversation drives a FakeSpeaker through a
// confident-answer turn followed by a barge-in, the two paths plan §4
// singles out (turn lifecycle and barge-in/DRAINING), and asserts both the
// replayed tape and the recorded calls.
func TestFakeSpeaker_ScriptedConversation(t *testing.T) {
	tape := []ports.SpeakerEvent{
		ports.InputTranscript{Text: "tell me about yourself", Final: true, ItemID: "item-1"},
		ports.AudioDelta{Frame: ports.Frame{PCM: []byte{1, 2, 3}, SampleRateHz: 24000}, ResponseID: "resp-1"},
		ports.OutputTranscriptDelta{Text: "So, I've worked with Go...", ResponseID: "resp-1"},
		ports.SpeechStarted{AudioStartMs: 240}, // barge-in mid-answer
		ports.ResponseDone{ResponseID: "resp-1", ItemID: "item-1"},
	}
	speaker := fakes.NewFakeSpeaker(tape...)

	ctx := context.Background()
	sess, err := speaker.Start(ctx, ports.SessionCfg{SessionID: "sess-1", VoiceID: "voice-a"})
	if err != nil {
		t.Fatalf("Start: %v", err)
	}
	fake, ok := sess.(*fakes.FakeSpeakerSession)
	if !ok {
		t.Fatalf("Start returned %T, want *fakes.FakeSpeakerSession", sess)
	}
	if speaker.LastSession() != fake {
		t.Fatalf("LastSession() did not return the started session")
	}

	var got []ports.SpeakerEvent
	var bargeIn bool
	for ev := range fake.Events() {
		got = append(got, ev)
		if _, ok := ev.(ports.SpeechStarted); ok {
			bargeIn = true
			// Mirror the actor's DRAINING path: cancel, truncate to what
			// was heard, drop into LISTENING.
			if err := fake.CancelResponse(ctx); err != nil {
				t.Fatalf("CancelResponse: %v", err)
			}
			if err := fake.Truncate(ctx, "item-1", 180); err != nil {
				t.Fatalf("Truncate: %v", err)
			}
		}
	}
	if !bargeIn {
		t.Fatalf("tape replay never delivered SpeechStarted")
	}
	if len(got) != len(tape) {
		t.Fatalf("replayed %d events, want %d", len(got), len(tape))
	}

	if err := fake.InjectSystemItem(ctx, "note: keep it vague"); err != nil {
		t.Fatalf("InjectSystemItem: %v", err)
	}
	if err := fake.CreateResponse(ctx, ports.ResponseDirectives{MinSentences: 3, MaxSentences: 6}); err != nil {
		t.Fatalf("CreateResponse: %v", err)
	}

	if items := fake.SystemItems(); len(items) != 1 || items[0] != "note: keep it vague" {
		t.Fatalf("SystemItems() = %v, want [\"note: keep it vague\"]", items)
	}
	if resp := fake.Responses(); len(resp) != 1 || resp[0].MaxSentences != 6 {
		t.Fatalf("Responses() = %v, want one entry with MaxSentences=6", resp)
	}
	if n := fake.CancelCount(); n != 1 {
		t.Fatalf("CancelCount() = %d, want 1", n)
	}
	trunc := fake.Truncations()
	if len(trunc) != 1 || trunc[0] != (fakes.Truncation{ItemID: "item-1", HeardMs: 180}) {
		t.Fatalf("Truncations() = %v, want one entry {item-1, 180}", trunc)
	}

	if err := fake.Close(ctx); err != nil {
		t.Fatalf("Close: %v", err)
	}
	if !fake.Closed() {
		t.Fatalf("Closed() = false after Close")
	}
}

// TestFakeTranscriber_ScriptedPartials proves the transcriber tape replays
// in order and SendAudio is recorded, concurrently.
func TestFakeTranscriber_ScriptedPartials(t *testing.T) {
	tape := []ports.Partial{
		{Text: "tell me", Final: false, ItemID: "item-1"},
		{Text: "tell me about yourself", Final: true, ItemID: "item-1"},
	}
	tx := fakes.NewFakeTranscriber(tape...)
	ctx := context.Background()
	if err := tx.Start(ctx); err != nil {
		t.Fatalf("Start: %v", err)
	}

	var wg sync.WaitGroup
	wg.Add(1)
	go func() {
		defer wg.Done()
		for i := 0; i < 3; i++ {
			if err := tx.SendAudio(ctx, ports.Frame{PCM: []byte{byte(i)}}); err != nil {
				t.Errorf("SendAudio: %v", err)
			}
		}
	}()

	var got []ports.Partial
	for p := range tx.Partials() {
		got = append(got, p)
	}
	wg.Wait()

	if len(got) != len(tape) || got[1].Text != tape[1].Text {
		t.Fatalf("Partials() replayed %v, want %v", got, tape)
	}
	if n := len(tx.SentAudio()); n != 3 {
		t.Fatalf("SentAudio() has %d frames, want 3", n)
	}
	if err := tx.Close(ctx); err != nil {
		t.Fatalf("Close: %v", err)
	}
}

// TestFakeThinker_NoteAndMiss drives the defer→note and
// defer→deadline-fallback paths from plan §4 step 5.
func TestFakeThinker_NoteAndMiss(t *testing.T) {
	thinker := fakes.NewFakeThinker(
		fakes.NoteScriptEntry{Note: ports.Note{Text: "half-remembers detail B7", Confidence: 0.6}},
		fakes.NoteScriptEntry{Miss: true}, // deadline miss
	)
	ctx := context.Background()
	persona := ports.PersonaCtx{SystemPrompt: "you are Mateo", LedgerSummary: "none yet"}
	if err := thinker.Start(ctx, persona); err != nil {
		t.Fatalf("Start: %v", err)
	}
	if err := thinker.FeedPartial(ctx, "so tell me about redis"); err != nil {
		t.Fatalf("FeedPartial: %v", err)
	}

	deadline := time.Now().Add(700 * time.Millisecond)
	note, ok := <-thinker.RequestNote(ctx, deadline)
	if !ok || note.Text != "half-remembers detail B7" {
		t.Fatalf("first RequestNote delivered %+v, ok=%v, want the scripted note", note, ok)
	}

	missCh := thinker.RequestNote(ctx, deadline)
	select {
	case n := <-missCh:
		t.Fatalf("second RequestNote delivered %+v, want a miss (no delivery)", n)
	case <-time.After(20 * time.Millisecond):
	}

	if err := thinker.Reset(ctx, "ledger: B7 committed"); err != nil {
		t.Fatalf("Reset: %v", err)
	}
	if err := thinker.Close(ctx); err != nil {
		t.Fatalf("Close: %v", err)
	}

	if got := thinker.Persona(); got != persona {
		t.Fatalf("Persona() = %+v, want %+v", got, persona)
	}
	if got := thinker.Partials(); len(got) != 1 || got[0] != "so tell me about redis" {
		t.Fatalf("Partials() = %v", got)
	}
	if got := thinker.NoteDeadlines(); len(got) != 2 {
		t.Fatalf("NoteDeadlines() has %d entries, want 2", len(got))
	}
	if got := thinker.Resets(); len(got) != 1 || got[0] != "ledger: B7 committed" {
		t.Fatalf("Resets() = %v", got)
	}
	if !thinker.Closed() {
		t.Fatalf("Closed() = false after Close")
	}
}

// TestStore_PutAndGet proves the in-memory Store round-trips content and is
// safe under concurrent writers.
func TestStore_PutAndGet(t *testing.T) {
	store := fakes.NewStore()
	ctx := context.Background()

	var wg sync.WaitGroup
	for i := 0; i < 10; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			key := "session/turn-" + string(rune('a'+i))
			if err := store.PutObject(ctx, key, strings.NewReader("payload")); err != nil {
				t.Errorf("PutObject(%s): %v", key, err)
			}
		}(i)
	}
	wg.Wait()

	if got := len(store.Keys()); got != 10 {
		t.Fatalf("Keys() has %d entries, want 10", got)
	}
	data, ok := store.Get("session/turn-a")
	if !ok || string(data) != "payload" {
		t.Fatalf("Get(session/turn-a) = %q, %v, want \"payload\", true", data, ok)
	}
	if _, ok := store.Get("does-not-exist"); ok {
		t.Fatalf("Get(does-not-exist) ok = true, want false")
	}

	// PutObject propagates a reader error instead of silently storing a
	// partial object.
	if err := store.PutObject(ctx, "bad", errReader{}); err == nil {
		t.Fatalf("PutObject with an erroring reader returned nil error")
	}
	if _, ok := store.Get("bad"); ok {
		t.Fatalf("Get(bad) ok = true, want false: a failed PutObject must not leave a partial object")
	}
}

type errReader struct{}

func (errReader) Read([]byte) (int, error) { return 0, io.ErrUnexpectedEOF }

// TestSampleContractSource_ServesParsableContract proves the static
// ContractSource serves the checked-in sample contract byte-for-byte and
// that it parses under internal/contract — end-to-end proof the fixture the
// rest of the engine's tests will lean on actually works.
func TestSampleContractSource_ServesParsableContract(t *testing.T) {
	src, err := fakes.NewSampleContractSource()
	if err != nil {
		t.Fatalf("NewSampleContractSource: %v", err)
	}
	ctx := context.Background()

	data, err := src.FetchContract(ctx, "vc-0c4aff82e1cb")
	if err != nil {
		t.Fatalf("FetchContract: %v", err)
	}
	c, err := contract.Parse(data)
	if err != nil {
		t.Fatalf("contract.Parse(sample) failed: %v", err)
	}
	if c.CandidateID != "vc-0c4aff82e1cb" {
		t.Fatalf("CandidateID = %q, want vc-0c4aff82e1cb", c.CandidateID)
	}

	if ids := src.FetchedCandidateIDs(); len(ids) != 1 || ids[0] != "vc-0c4aff82e1cb" {
		t.Fatalf("FetchedCandidateIDs() = %v", ids)
	}

	ingest := ports.SessionIngest{
		SessionID:   "sess-1",
		CandidateID: "vc-0c4aff82e1cb",
		EndReason:   "interviewer_ended",
	}
	if err := src.NotifyIngest(ctx, ingest); err != nil {
		t.Fatalf("NotifyIngest: %v", err)
	}
	if got := src.Ingests(); len(got) != 1 || got[0] != ingest {
		t.Fatalf("Ingests() = %v, want [%v]", got, ingest)
	}

	wantErr := context.Canceled
	src.SetFetchError(wantErr)
	if _, err := src.FetchContract(ctx, "any"); err != wantErr {
		t.Fatalf("FetchContract after SetFetchError = %v, want %v", err, wantErr)
	}
}
