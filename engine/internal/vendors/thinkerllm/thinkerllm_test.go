package thinkerllm_test

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"go.uber.org/goleak"

	"skillbrew/engine/internal/ports"
	"skillbrew/engine/internal/vendors/thinkerllm"
)

// verifyNoEngineLeaks is goleak scoped to goroutines this package owns.
//
// httptest servers and the stdlib HTTP transport keep connection goroutines
// alive past Close, and they are not ours. Ignoring those two functions by
// name keeps the check sharp — a stranded speculation goroutine still fails —
// rather than dropping goleak from this package because it was noisy.
func verifyNoEngineLeaks(t *testing.T) {
	goleak.VerifyNone(t,
		goleak.IgnoreTopFunction("net/http.(*connReader).backgroundRead"),
		goleak.IgnoreTopFunction("net/http.(*persistConn).writeLoop"),
		goleak.IgnoreTopFunction("net/http.(*persistConn).readLoop"),
		goleak.IgnoreTopFunction("internal/poll.runtime_pollWait"),
	)
}

// waitCalls blocks until the stub vendor has seen n requests.
//
// Speculation is asynchronous by design — FeedPartial returns the moment it
// has handed the work off, because the interviewer is still talking and
// nothing may block that path. So a test asserting on call counts has to wait
// for the call rather than assume it already happened.
func waitCalls(t *testing.T, calls *atomic.Int64, n int64) {
	t.Helper()
	deadline := time.Now().Add(2 * time.Second)
	for time.Now().Before(deadline) {
		if calls.Load() >= n {
			return
		}
		time.Sleep(time.Millisecond)
	}
	t.Fatalf("only %d calls after 2s, want %d", calls.Load(), n)
}

// noteServer returns a stub vendor that answers with the given note JSON after
// a delay, and counts the calls it received.
func noteServer(t *testing.T, delay time.Duration, noteJSON string) (*httptest.Server, *atomic.Int64, *atomic.Pointer[string]) {
	t.Helper()
	var calls atomic.Int64
	var lastPrompt atomic.Pointer[string]
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls.Add(1)
		body, _ := io.ReadAll(r.Body)
		s := string(body)
		lastPrompt.Store(&s)
		select {
		case <-time.After(delay):
		case <-r.Context().Done():
			return
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(w, `{"candidates":[{"content":{"parts":[{"text":`+
			strconv.Quote(noteJSON)+`}]}}]}`)
	}))
	t.Cleanup(srv.Close)
	return srv, &calls, &lastPrompt
}

const goodNote = `{"note":"you half-remember this; keep it vague","claims_to_make":["Redis is single-threaded"],"claims_made":["we used it for caching"],"unlock_met":false,"confidence":0.8}`

func newThinker(t *testing.T, srv *httptest.Server) *thinkerllm.Thinker {
	t.Helper()
	return thinkerllm.New("test-model", "test-key",
		thinkerllm.WithHTTPClient(srv.Client()),
		thinkerllm.WithEndpoint(srv.URL),
		thinkerllm.WithMinPartialWords(3),
	)
}

func TestANoteArrivesBeforeTheDeadline(t *testing.T) {
	defer verifyNoEngineLeaks(t)

	srv, _, _ := noteServer(t, 0, goodNote)
	th := newThinker(t, srv)
	ctx := context.Background()

	if err := th.Start(ctx, ports.PersonaCtx{SystemPrompt: "You are Rohan."}); err != nil {
		t.Fatalf("start: %v", err)
	}
	defer th.Close(ctx)

	if err := th.FeedPartial(ctx, "how did you scale redis"); err != nil {
		t.Fatalf("feed: %v", err)
	}
	note, ok := <-th.RequestNote(ctx, time.Now().Add(2*time.Second))
	if !ok {
		t.Fatal("expected a note before the deadline")
	}
	if !strings.Contains(note.Text, "keep it vague") {
		t.Fatalf("note = %q", note.Text)
	}
	if len(note.ClaimsToMake) != 1 || len(note.ClaimsMade) != 1 {
		t.Fatalf("claims not carried through: %+v", note)
	}
}

func TestTheReasoningStartsWhileTheQuestionIsStillBeingAsked(t *testing.T) {
	// The whole reason the two-model design works. A call started at
	// end-of-turn arrives seconds late; one started mid-question is already
	// running when the silence begins.
	defer verifyNoEngineLeaks(t)

	srv, calls, _ := noteServer(t, 50*time.Millisecond, goodNote)
	th := newThinker(t, srv)
	ctx := context.Background()
	_ = th.Start(ctx, ports.PersonaCtx{SystemPrompt: "You are Rohan."})
	defer th.Close(ctx)

	_ = th.FeedPartial(ctx, "how did you scale redis")
	waitCalls(t, calls, 1)
	// RequestNote joins the call already in flight rather than starting one.
	<-th.RequestNote(ctx, time.Now().Add(2*time.Second))
	if got := calls.Load(); got != 1 {
		t.Fatalf("%d calls total, want 1 — RequestNote should reuse the speculation", got)
	}
}

func TestAShortPartialIsNotWorthACall(t *testing.T) {
	defer verifyNoEngineLeaks(t)

	srv, calls, _ := noteServer(t, 0, goodNote)
	th := newThinker(t, srv)
	ctx := context.Background()
	_ = th.Start(ctx, ports.PersonaCtx{})
	defer th.Close(ctx)

	_ = th.FeedPartial(ctx, "so")
	if got := calls.Load(); got != 0 {
		t.Fatalf("%d calls on a two-word partial; every 'so,' would cost a request", got)
	}
}

func TestALaterPartialSupersedesTheEarlierSpeculation(t *testing.T) {
	// A guess made from four words is worth less than one made from twelve,
	// and answering the question the interviewer did not finish asking is
	// worse than either.
	defer verifyNoEngineLeaks(t)

	srv, calls, prompt := noteServer(t, 0, goodNote)
	th := newThinker(t, srv)
	ctx := context.Background()
	_ = th.Start(ctx, ports.PersonaCtx{})
	defer th.Close(ctx)

	_ = th.FeedPartial(ctx, "how did you scale")
	waitCalls(t, calls, 1)
	_ = th.FeedPartial(ctx, "how did you scale redis under load")
	waitCalls(t, calls, 2)
	<-th.RequestNote(ctx, time.Now().Add(2*time.Second))
	if p := prompt.Load(); p == nil || !strings.Contains(*p, "under load") {
		t.Fatal("the final call should carry the fuller question")
	}
}

func TestAMissedDeadlineClosesTheChannelWithoutANote(t *testing.T) {
	// The actor has its own timer and a persona-correct fallback. Blocking
	// on a late reasoning model is exactly what the stall bank exists to
	// avoid.
	defer verifyNoEngineLeaks(t)

	srv, _, _ := noteServer(t, 2*time.Second, goodNote)
	th := newThinker(t, srv)
	ctx := context.Background()
	_ = th.Start(ctx, ports.PersonaCtx{})
	defer th.Close(ctx)

	_ = th.FeedPartial(ctx, "how did you scale redis")
	start := time.Now()
	_, ok := <-th.RequestNote(ctx, time.Now().Add(80*time.Millisecond))
	if ok {
		t.Fatal("no note should arrive before the deadline")
	}
	if elapsed := time.Since(start); elapsed > time.Second {
		t.Fatalf("RequestNote blocked for %v; it must return at the deadline", elapsed)
	}
}

func TestAVendorErrorIsNotANote(t *testing.T) {
	defer verifyNoEngineLeaks(t)

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusTooManyRequests)
		_, _ = io.WriteString(w, `{"error":{"message":"quota exceeded"}}`)
	}))
	defer srv.Close()

	th := thinkerllm.New("m", "k", thinkerllm.WithHTTPClient(srv.Client()),
		thinkerllm.WithEndpoint(srv.URL), thinkerllm.WithMinPartialWords(1))
	ctx := context.Background()
	_ = th.Start(ctx, ports.PersonaCtx{})
	defer th.Close(ctx)

	_ = th.FeedPartial(ctx, "how did you scale redis")
	if _, ok := <-th.RequestNote(ctx, time.Now().Add(2*time.Second)); ok {
		t.Fatal("a vendor failure must not surface as a note; the actor falls back")
	}
}

func TestTheLedgerReachesTheReasoningModel(t *testing.T) {
	// It is reasoning over "what has this person already committed to". A
	// Thinker without the ledger produces confidently contradictory notes.
	defer verifyNoEngineLeaks(t)

	srv, _, prompt := noteServer(t, 0, goodNote)
	th := newThinker(t, srv)
	ctx := context.Background()
	_ = th.Start(ctx, ports.PersonaCtx{SystemPrompt: "You are Rohan."})
	defer th.Close(ctx)

	if err := th.Reset(ctx, "b1 [Redis] Redis is single-threaded (asserted)"); err != nil {
		t.Fatalf("reset: %v", err)
	}
	_ = th.FeedPartial(ctx, "tell me more about redis internals")
	<-th.RequestNote(ctx, time.Now().Add(2*time.Second))

	p := prompt.Load()
	if p == nil || !strings.Contains(*p, "single-threaded") {
		t.Fatal("the ledger must reach the reasoning model")
	}
}

func TestResetClearsTheQuestionButKeepsThePersona(t *testing.T) {
	defer verifyNoEngineLeaks(t)

	srv, calls, _ := noteServer(t, 0, goodNote)
	th := newThinker(t, srv)
	ctx := context.Background()
	_ = th.Start(ctx, ports.PersonaCtx{SystemPrompt: "You are Rohan."})
	defer th.Close(ctx)

	_ = th.FeedPartial(ctx, "how did you scale redis")
	waitCalls(t, calls, 1)
	_ = th.Reset(ctx, "")
	// Nothing is being asked, so there is nothing to speculate about.
	if _, ok := <-th.RequestNote(ctx, time.Now().Add(200*time.Millisecond)); ok {
		t.Fatal("no note should be produced with no question in flight")
	}
	if got := calls.Load(); got != 1 {
		t.Fatalf("%d calls, want 1 — Reset must not start a new one", got)
	}
}

func TestAnUnlockAssessmentIsOnlyReportedWhenTheModelMadeOne(t *testing.T) {
	// nil Unlock means "no opinion", which is different from "not met".
	// Only one of those should ever be inferred from silence.
	defer verifyNoEngineLeaks(t)

	srv, _, _ := noteServer(t, 0,
		`{"note":"n","claims_to_make":[],"claims_made":[],"confidence":0.5}`)
	th := newThinker(t, srv)
	ctx := context.Background()
	_ = th.Start(ctx, ports.PersonaCtx{})
	defer th.Close(ctx)

	_ = th.FeedPartial(ctx, "tell me about your background please")
	note := <-th.RequestNote(ctx, time.Now().Add(2*time.Second))
	if note.Unlock != nil {
		t.Fatalf("Unlock = %+v, want nil when the model expressed no view", note.Unlock)
	}
}

func TestMalformedJSONIsRejectedRatherThanGuessed(t *testing.T) {
	defer verifyNoEngineLeaks(t)

	srv, _, _ := noteServer(t, 0, `{"note": not json`)
	th := newThinker(t, srv)
	ctx := context.Background()
	_ = th.Start(ctx, ports.PersonaCtx{})
	defer th.Close(ctx)

	_ = th.FeedPartial(ctx, "how did you scale redis")
	if _, ok := <-th.RequestNote(ctx, time.Now().Add(2*time.Second)); ok {
		t.Fatal("a half-parsed note must not reach the persona")
	}
}

func TestNoteFieldsAreBounded(t *testing.T) {
	defer verifyNoEngineLeaks(t)

	many, _ := json.Marshal([]string{"a", "b", "c", "d", "e", "f", "g"})
	srv, _, _ := noteServer(t, 0,
		`{"note":"n","claims_to_make":`+string(many)+`,"claims_made":`+string(many)+`,"confidence":9}`)
	th := newThinker(t, srv)
	ctx := context.Background()
	_ = th.Start(ctx, ports.PersonaCtx{})
	defer th.Close(ctx)

	_ = th.FeedPartial(ctx, "how did you scale redis")
	note := <-th.RequestNote(ctx, time.Now().Add(2*time.Second))
	if len(note.ClaimsToMake) > 4 || len(note.ClaimsMade) > 4 {
		t.Fatalf("claims unbounded: %+v", note)
	}
	if note.Confidence != 1 {
		t.Fatalf("confidence = %v, want clamped to 1", note.Confidence)
	}
}
