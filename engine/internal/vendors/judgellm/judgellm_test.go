package judgellm_test

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strconv"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"go.uber.org/goleak"

	"skillbrew/engine/internal/ports"
	"skillbrew/engine/internal/vendors/judgellm"
)

// verifyNoEngineLeaks is goleak scoped to goroutines this package owns.
//
// httptest servers and the stdlib HTTP transport keep connection goroutines
// alive past Close, and they are not ours. Ignoring those two functions by
// name keeps the check sharp — a stranded worker or watcher goroutine still
// fails — rather than dropping goleak from this package because it was noisy.
func verifyNoEngineLeaks(t *testing.T) {
	goleak.VerifyNone(t,
		goleak.IgnoreTopFunction("net/http.(*connReader).backgroundRead"),
		goleak.IgnoreTopFunction("net/http.(*persistConn).writeLoop"),
		goleak.IgnoreTopFunction("net/http.(*persistConn).readLoop"),
		goleak.IgnoreTopFunction("internal/poll.runtime_pollWait"),
	)
}

// newJudge returns a Judge wired to srv, with sane defaults for a test.
func newJudge(t *testing.T, srv *httptest.Server) *judgellm.Judge {
	t.Helper()
	return judgellm.New("test-model", "test-key",
		judgellm.WithHTTPClient(srv.Client()), judgellm.WithEndpoint(srv.URL))
}

// judgeServer returns a stub vendor that answers every call with the given
// verdict JSON, wrapped in the Gemini response envelope.
func judgeServer(t *testing.T, verdictJSON string) *httptest.Server {
	t.Helper()
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(w, `{"candidates":[{"content":{"parts":[{"text":`+
			strconv.Quote(verdictJSON)+`}]}}]}`)
	}))
	t.Cleanup(srv.Close)
	return srv
}

// stallServer returns a stub vendor that never responds until its request is
// cancelled. Used to keep the Judge's single worker permanently busy so a
// test can drive the review queue to capacity.
//
// The body drain is load-bearing, not tidiness. net/http only starts the
// background read that detects a client disconnect once the request body has
// been consumed, so a handler that parks on r.Context().Done() without reading
// the body is never woken when the Judge cancels the call. The handler then
// outlives the test, goleak reports it, and httptest.Server.Close blocks
// forever waiting for a connection it still considers active — which is
// exactly how this package first hung.
func stallServer(t *testing.T) *httptest.Server {
	t.Helper()
	srv := httptest.NewServer(http.HandlerFunc(func(_ http.ResponseWriter, r *http.Request) {
		_, _ = io.Copy(io.Discard, r.Body)
		<-r.Context().Done()
	}))
	t.Cleanup(srv.Close)
	return srv
}

// requireVerdict reads the next verdict, failing the test rather than
// blocking forever if none arrives.
func requireVerdict(t *testing.T, j *judgellm.Judge) ports.Verdict {
	t.Helper()
	select {
	case v, ok := <-j.Verdicts():
		if !ok {
			t.Fatal("verdict stream closed before a verdict arrived")
		}
		return v
	case <-time.After(2 * time.Second):
		t.Fatal("no verdict arrived within 2s")
		return ports.Verdict{}
	}
}

// floodQueue submits turns against j until Submit starts shedding them,
// proving the review queue filled. It fails the test — rather than hanging —
// if Submit ever blocks instead of returning promptly.
func floodQueue(t *testing.T, j *judgellm.Judge) int {
	t.Helper()
	done := make(chan int, 1)
	go func() {
		var dropped int
		for i := 0; i < 1000; i++ {
			if err := j.Submit(context.Background(), ports.TurnForReview{Turn: i}); err != nil {
				dropped++
			}
		}
		done <- dropped
	}()
	select {
	case dropped := <-done:
		return dropped
	case <-time.After(2 * time.Second):
		t.Fatal("Submit blocked instead of shedding load once the review queue was full")
		return 0
	}
}

// TestSubmitNeverBlocksWhenTheReviewQueueIsFull matters because Submit is
// called by the session actor — the goroutine driving a live conversation —
// at turn close. A Judge backlog must never become backpressure on somebody's
// interview: flooding the queue past capacity, with the single worker stuck
// on a call that never returns, must still return promptly.
func TestSubmitNeverBlocksWhenTheReviewQueueIsFull(t *testing.T) {
	defer verifyNoEngineLeaks(t)

	srv := stallServer(t)
	j := newJudge(t, srv)
	defer j.Close()

	start := time.Now()
	dropped := floodQueue(t, j)
	elapsed := time.Since(start)

	if dropped == 0 {
		t.Fatal("expected the review queue to fill and shed submissions, got none")
	}
	if elapsed > time.Second {
		t.Fatalf("flooding the queue took %v; Submit must never block", elapsed)
	}
}

// TestADroppedReviewIsCountedRatherThanSilent matters because a dropped
// review is a gap in the grading metadata. It must be visible via Dropped(),
// not merely absent from the verdict stream — otherwise a session that
// reviewed less than it should looks merely clean.
func TestADroppedReviewIsCountedRatherThanSilent(t *testing.T) {
	defer verifyNoEngineLeaks(t)

	srv := stallServer(t)
	j := newJudge(t, srv)
	defer j.Close()

	dropped := floodQueue(t, j)
	if dropped == 0 {
		t.Fatal("queue never filled; test setup invalid")
	}
	if got := j.Dropped(); got != dropped {
		t.Fatalf("Dropped() = %d, want %d to match Submit's own error count", got, dropped)
	}
}

// TestAVendorErrorIsNotAVerdict matters because a failed review is a gap, not
// a clean bill of health and not a breach. Inferring either from a transport
// error would be worse than saying nothing about the turn.
func TestAVendorErrorIsNotAVerdict(t *testing.T) {
	defer verifyNoEngineLeaks(t)

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusTooManyRequests)
		_, _ = io.WriteString(w, `{"error":{"message":"quota exceeded"}}`)
	}))
	defer srv.Close()

	j := newJudge(t, srv)
	defer j.Close()

	if err := j.Submit(context.Background(), ports.TurnForReview{Turn: 1, Skill: "sql", Ceiling: 3}); err != nil {
		t.Fatalf("submit: %v", err)
	}

	select {
	case v, ok := <-j.Verdicts():
		if ok {
			t.Fatalf("a vendor error must not surface as a verdict, got %+v", v)
		}
	case <-time.After(300 * time.Millisecond):
		// Nothing arrived — correct: the failed review is a gap, not a
		// verdict, and it must not be counted as a queue drop either.
	}
	if got := j.Dropped(); got != 0 {
		t.Fatalf("Dropped() = %d, want 0 — a vendor error is not a shed submission", got)
	}
}

// TestMalformedModelJSONIsRejectedRatherThanGuessed matters because a
// half-parsed verdict reaching the stream would be indistinguishable from a
// real judgement to anything downstream.
func TestMalformedModelJSONIsRejectedRatherThanGuessed(t *testing.T) {
	defer verifyNoEngineLeaks(t)

	srv := judgeServer(t, `{"breach": not json`)
	j := newJudge(t, srv)
	defer j.Close()

	if err := j.Submit(context.Background(), ports.TurnForReview{Turn: 1}); err != nil {
		t.Fatalf("submit: %v", err)
	}

	select {
	case v, ok := <-j.Verdicts():
		if ok {
			t.Fatalf("a malformed verdict must not reach the stream, got %+v", v)
		}
	case <-time.After(300 * time.Millisecond):
	}
}

// TestVerdictFieldsAreBoundedOnTheWayOut mirrors the Thinker's normalization
// discipline: a clean turn must look clean downstream. A non-empty severity
// or walkback hint on a turn the model itself marked "not a breach" would let
// a grading report treat a clean answer as flagged.
func TestVerdictFieldsAreBoundedOnTheWayOut(t *testing.T) {
	defer verifyNoEngineLeaks(t)

	srv := judgeServer(t, `{"breach":false,"severity":"high","rationale":"  within ceiling  ",`+
		`"walkback_hint":"say something else"}`)
	j := newJudge(t, srv)
	defer j.Close()

	if err := j.Submit(context.Background(), ports.TurnForReview{Turn: 7}); err != nil {
		t.Fatalf("submit: %v", err)
	}
	v := requireVerdict(t, j)

	if v.Breach {
		t.Fatal("breach should be false")
	}
	if v.Severity != "" {
		t.Fatalf("severity = %q on a non-breach verdict, want empty", v.Severity)
	}
	if v.WalkbackHint != "" {
		t.Fatalf("walkback_hint = %q on a non-breach verdict, want empty", v.WalkbackHint)
	}
	if v.Rationale != "within ceiling" {
		t.Fatalf("rationale = %q, want trimmed", v.Rationale)
	}
}

// TestUnrecognisedSeverityDefaultsToMediumOnARealBreach matters because the
// breach happened either way; losing it because the severity label was
// malformed or missing would be worse than defaulting it.
func TestUnrecognisedSeverityDefaultsToMediumOnARealBreach(t *testing.T) {
	defer verifyNoEngineLeaks(t)

	srv := judgeServer(t, `{"breach":true,"severity":"critical","rationale":"leaked depth"}`)
	j := newJudge(t, srv)
	defer j.Close()

	if err := j.Submit(context.Background(), ports.TurnForReview{Turn: 3}); err != nil {
		t.Fatalf("submit: %v", err)
	}
	v := requireVerdict(t, j)

	if !v.Breach {
		t.Fatal("breach should be true")
	}
	if v.Severity != "medium" {
		t.Fatalf("severity = %q, want default of medium for an unrecognised label", v.Severity)
	}
}

// TestCloseStopsTheWorkerAndClosesTheVerdictStream matters because a Judge
// that leaks its worker or a Judge that panics on a second Close would take
// down whatever calls it during session teardown.
func TestCloseStopsTheWorkerAndClosesTheVerdictStream(t *testing.T) {
	defer verifyNoEngineLeaks(t)

	srv := judgeServer(t, `{"breach":false,"rationale":"fine"}`)
	j := newJudge(t, srv)

	j.Close()
	j.Close() // idempotent: a second Close must not panic or double-close.

	if _, ok := <-j.Verdicts(); ok {
		t.Fatal("Verdicts() must be closed after Close")
	}
	if err := j.Submit(context.Background(), ports.TurnForReview{Turn: 1}); err == nil {
		t.Fatal("Submit after Close should error rather than silently queue")
	}
}

// TestEverySubmittedTurnThatSucceedsProducesExactlyOneVerdict matters because
// the Judge's whole guarantee is that every reviewed turn is labelled once —
// not zero times (silently lost) and not twice (a duplicate label a grading
// report could double-count).
func TestEverySubmittedTurnThatSucceedsProducesExactlyOneVerdict(t *testing.T) {
	defer verifyNoEngineLeaks(t)

	srv := judgeServer(t, `{"breach":true,"severity":"low","rationale":"leaked one detail",`+
		`"walkback_hint":"walk it back"}`)
	j := newJudge(t, srv)
	defer j.Close()

	const n = 5
	for i := 0; i < n; i++ {
		if err := j.Submit(context.Background(), ports.TurnForReview{Turn: i}); err != nil {
			t.Fatalf("submit %d: %v", i, err)
		}
	}

	seen := map[int]bool{}
	for i := 0; i < n; i++ {
		v := requireVerdict(t, j)
		if seen[v.Turn] {
			t.Fatalf("turn %d produced more than one verdict", v.Turn)
		}
		seen[v.Turn] = true
	}
	select {
	case v, ok := <-j.Verdicts():
		if ok {
			t.Fatalf("extra verdict beyond the %d submitted turns: %+v", n, v)
		}
	case <-time.After(200 * time.Millisecond):
	}
}

// fixtureCase is one labelled persona turn in testdata/judge_fixture.json.
type fixtureCase struct {
	ID            string   `json:"id"`
	Class         string   `json:"class"`
	Skill         string   `json:"skill"`
	Ceiling       int      `json:"ceiling"`
	Beliefs       []string `json:"beliefs"`
	Question      string   `json:"question"`
	Answer        string   `json:"answer"`
	CannedVerdict struct {
		Breach       bool   `json:"breach"`
		Severity     string `json:"severity"`
		Rationale    string `json:"rationale"`
		WalkbackHint string `json:"walkback_hint"`
	} `json:"canned_verdict"`
	ExpectedBreach   bool   `json:"expected_breach"`
	ExpectedSeverity string `json:"expected_severity"`
}

type fixtureFile struct {
	Cases []fixtureCase `json:"cases"`
}

// loadFixture reads the offline evaluation fixture. Reading testdata with a
// non-constant path from a _test.go file is exempt from gosec's file-read
// check (see .golangci.yml exclusions).
func loadFixture(t *testing.T) []fixtureCase {
	t.Helper()
	raw, err := os.ReadFile(filepath.Join("testdata", "judge_fixture.json"))
	if err != nil {
		t.Fatalf("read fixture: %v", err)
	}
	var f fixtureFile
	if err := json.Unmarshal(raw, &f); err != nil {
		t.Fatalf("parse fixture: %v", err)
	}
	if len(f.Cases) < 20 {
		t.Fatalf("fixture has %d cases, want at least 20", len(f.Cases))
	}
	return f.Cases
}

// fixtureServer answers the i-th request with cases[i]'s canned verdict, so
// the test can drive the fixture through the adapter one case at a time in
// order.
func fixtureServer(t *testing.T, cases []fixtureCase) *httptest.Server {
	t.Helper()
	var next atomic.Int64
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		i := next.Add(1) - 1
		if int(i) >= len(cases) {
			w.WriteHeader(http.StatusInternalServerError)
			return
		}
		body, _ := json.Marshal(cases[i].CannedVerdict)
		w.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(w, `{"candidates":[{"content":{"parts":[{"text":`+
			strconv.Quote(string(body))+`}]}}]}`)
	}))
	t.Cleanup(srv.Close)
	return srv
}

// TestTheOfflineFixtureLabelsCleanBreachAndVagueTurnsCorrectly drives the
// labelled fixture through the adapter end to end — HTTP envelope parsing,
// JSON decode, and normalize — against canned model responses served over
// httptest. It pins the adapter's parsing and labelling pipeline; it does
// NOT and cannot measure real model judgement precision, since no live model
// is called. Calibrating actual model accuracy against a fixture like this is
// a separate, later, live task.
func TestTheOfflineFixtureLabelsCleanBreachAndVagueTurnsCorrectly(t *testing.T) {
	defer verifyNoEngineLeaks(t)

	cases := loadFixture(t)
	srv := fixtureServer(t, cases)
	j := newJudge(t, srv)
	defer j.Close()

	var clean, breach, vague int
	for i, c := range cases {
		err := j.Submit(context.Background(), ports.TurnForReview{
			Turn:     i,
			Skill:    c.Skill,
			Ceiling:  c.Ceiling,
			Beliefs:  c.Beliefs,
			Question: c.Question,
			Answer:   c.Answer,
		})
		if err != nil {
			t.Fatalf("case %q: submit: %v", c.ID, err)
		}
		v := requireVerdict(t, j)
		if v.Turn != i {
			t.Fatalf("case %q: verdict turn = %d, want %d", c.ID, v.Turn, i)
		}
		if v.Breach != c.ExpectedBreach {
			t.Fatalf("case %q: breach = %v, want %v", c.ID, v.Breach, c.ExpectedBreach)
		}
		if v.Severity != c.ExpectedSeverity {
			t.Fatalf("case %q: severity = %q, want %q", c.ID, v.Severity, c.ExpectedSeverity)
		}
		if !c.ExpectedBreach && v.WalkbackHint != "" {
			t.Fatalf("case %q: walkback_hint = %q on a non-breach verdict, want empty", c.ID, v.WalkbackHint)
		}

		switch c.Class {
		case "clean":
			clean++
			if v.Breach {
				t.Fatalf("case %q: a clean, at-or-below-ceiling answer must not be flagged", c.ID)
			}
		case "breach":
			breach++
			if !v.Breach {
				t.Fatalf("case %q: a semantic-depth breach must be flagged", c.ID)
			}
		case "vague":
			vague++
			if v.Breach {
				t.Fatalf("case %q: a correctly vague deflection must not be flagged as a breach", c.ID)
			}
		default:
			t.Fatalf("case %q: unknown class %q", c.ID, c.Class)
		}
	}

	if clean == 0 || breach == 0 || vague == 0 {
		t.Fatalf("fixture missing a class: clean=%d breach=%d vague=%d", clean, breach, vague)
	}
}

// TestCloseUnblocksAReviewAlreadyInFlightAtTheVendor matters because Close is
// called on the session-teardown path. The Judge's whole design is to outlive
// the turn it is reviewing, so a review holds a context nothing else cancels:
// if Close did not cancel it, teardown would block for the vendor's full HTTP
// timeout on every session that ended mid-review.
func TestCloseUnblocksAReviewAlreadyInFlightAtTheVendor(t *testing.T) {
	defer verifyNoEngineLeaks(t)

	inFlight := make(chan struct{})
	var once sync.Once
	srv := httptest.NewServer(http.HandlerFunc(func(_ http.ResponseWriter, r *http.Request) {
		_, _ = io.Copy(io.Discard, r.Body)
		once.Do(func() { close(inFlight) })
		<-r.Context().Done()
	}))
	t.Cleanup(srv.Close)

	j := newJudge(t, srv)
	if err := j.Submit(context.Background(), ports.TurnForReview{Turn: 0}); err != nil {
		t.Fatalf("submit: %v", err)
	}

	select {
	case <-inFlight:
	case <-time.After(2 * time.Second):
		t.Fatal("the review never reached the vendor; test setup invalid")
	}

	closed := make(chan struct{})
	go func() {
		j.Close()
		close(closed)
	}()
	select {
	case <-closed:
	case <-time.After(2 * time.Second):
		t.Fatal("Close blocked on a review already in flight at the vendor")
	}
}

// TestAReviewTheVendorNeverAnsweredIsCountedRatherThanSilent matters for the
// same reason Dropped() exists: a turn that was never reviewed is a gap in the
// grading metadata, and a gap that is invisible reads as a clean turn. The two
// causes are counted separately because they have different fixes — Dropped
// means the Judge could not keep up, Failed means the vendor did not answer.
func TestAReviewTheVendorNeverAnsweredIsCountedRatherThanSilent(t *testing.T) {
	defer verifyNoEngineLeaks(t)

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = io.Copy(io.Discard, r.Body)
		w.WriteHeader(http.StatusInternalServerError)
	}))
	t.Cleanup(srv.Close)

	j := newJudge(t, srv)
	defer j.Close()

	const turns = 3
	for i := 0; i < turns; i++ {
		if err := j.Submit(context.Background(), ports.TurnForReview{Turn: i}); err != nil {
			t.Fatalf("submit %d: %v", i, err)
		}
	}

	deadline := time.After(3 * time.Second)
	for j.Failed() < turns {
		select {
		case <-deadline:
			t.Fatalf("Failed() = %d after 3s, want %d; a review the vendor never answered must be counted", j.Failed(), turns)
		default:
			time.Sleep(5 * time.Millisecond)
		}
	}
	if got := j.Dropped(); got != 0 {
		t.Fatalf("Dropped() = %d, want 0; a vendor error is not a queue overflow", got)
	}
	select {
	case v := <-j.Verdicts():
		t.Fatalf("a failed review produced a verdict %+v; it must produce none", v)
	case <-time.After(100 * time.Millisecond):
	}
}
