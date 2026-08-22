package session_test

import (
	"context"
	"errors"
	"io"
	"log/slog"
	"sync"
	"testing"
	"time"

	"go.uber.org/goleak"

	"skillbrew/engine/internal/contract"
	"skillbrew/engine/internal/fakes"
	"skillbrew/engine/internal/session"
)

// testLogger discards output: tests assert on behaviour, not log lines.
func testLogger() *slog.Logger {
	return slog.New(slog.NewTextHandler(io.Discard, nil))
}

// fixedNow seeds FakeClock in tests that don't otherwise care about the
// clock's value. It is a literal, not time.Now(): internal/arch's
// TestSessionDoesNotCallTimeDirectly scans this package's test files too
// (a test that reaches for the real wall clock instead of driving FakeClock
// is exactly the flakiness plan §10 rule 6 exists to prevent), so even test
// helpers here must not call time.Now.
var fixedNow = time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC)

func newManager(t *testing.T) (*session.Manager, *fakes.ContractSource) {
	t.Helper()
	cs, err := fakes.NewSampleContractSource()
	if err != nil {
		t.Fatalf("NewSampleContractSource: %v", err)
	}
	return session.NewManager(fakes.NewFakeClock(fixedNow), cs, testLogger()), cs
}

func TestCreateSession_SpawnsAndIsLookupable(t *testing.T) {
	defer goleak.VerifyNone(t)

	mgr, cs := newManager(t)
	got, err := mgr.CreateSession(context.Background(), "vc-test-1")
	if err != nil {
		t.Fatalf("CreateSession: %v", err)
	}
	if got.ID == "" {
		t.Fatal("CreateSession returned empty session id")
	}
	if got.CandidateID != "vc-test-1" {
		t.Errorf("CandidateID = %q, want vc-test-1", got.CandidateID)
	}

	found, ok := mgr.Lookup(got.ID)
	if !ok {
		t.Fatal("Lookup did not find the session just created")
	}
	if found.ID != got.ID {
		t.Errorf("Lookup returned id %q, want %q", found.ID, got.ID)
	}
	if mgr.Count() != 1 {
		t.Errorf("Count() = %d, want 1", mgr.Count())
	}

	ids := cs.FetchedCandidateIDs()
	if len(ids) != 1 || ids[0] != "vc-test-1" {
		t.Errorf("FetchedCandidateIDs = %v, want [vc-test-1]", ids)
	}

	if err := mgr.StopSession(context.Background(), got.ID); err != nil {
		t.Fatalf("StopSession: %v", err)
	}
	if mgr.Count() != 0 {
		t.Errorf("Count() after stop = %d, want 0", mgr.Count())
	}
}

func TestCreateSession_EmptyCandidateID(t *testing.T) {
	defer goleak.VerifyNone(t)

	mgr, _ := newManager(t)
	_, err := mgr.CreateSession(context.Background(), "")
	if !errors.Is(err, session.ErrEmptyCandidateID) {
		t.Fatalf("CreateSession(\"\") error = %v, want ErrEmptyCandidateID", err)
	}
	if mgr.Count() != 0 {
		t.Errorf("Count() = %d, want 0 after a rejected create", mgr.Count())
	}
}

func TestCreateSession_FetchError(t *testing.T) {
	defer goleak.VerifyNone(t)

	mgr, cs := newManager(t)
	fetchErr := errors.New("control plane unreachable")
	cs.SetFetchError(fetchErr)

	_, err := mgr.CreateSession(context.Background(), "vc-test-1")
	if !errors.Is(err, fetchErr) {
		t.Fatalf("CreateSession error = %v, want wrapping %v", err, fetchErr)
	}
	if mgr.Count() != 0 {
		t.Errorf("Count() = %d, want 0 after a failed fetch", mgr.Count())
	}
}

func TestCreateSession_UnparseableContractRejectedWithTypedError(t *testing.T) {
	defer goleak.VerifyNone(t)

	badCS := fakes.NewContractSource([]byte(`{"contract_version": "v2.0"}`))
	mgr := session.NewManager(fakes.NewFakeClock(fixedNow), badCS, testLogger())

	_, err := mgr.CreateSession(context.Background(), "vc-test-1")
	if !errors.Is(err, session.ErrContractRejected) {
		t.Fatalf("CreateSession error = %v, want wrapping session.ErrContractRejected", err)
	}
	if !errors.Is(err, contract.ErrUnsupportedVersion) {
		t.Fatalf("CreateSession error = %v, want also wrapping contract.ErrUnsupportedVersion", err)
	}
	if mgr.Count() != 0 {
		t.Errorf("Count() = %d, want 0 after a rejected contract", mgr.Count())
	}
}

// TestCreateSession_MalformedContractJSONRejectedWithTypedError covers the
// other contract.Parse failure mode: JSON that does not decode at all. That
// path (unlike a failed validation or an unsupported version) carries none
// of contract's own sentinels, which is exactly why Manager wraps
// ErrContractRejected around every contract.Parse failure uniformly.
func TestCreateSession_MalformedContractJSONRejectedWithTypedError(t *testing.T) {
	defer goleak.VerifyNone(t)

	badCS := fakes.NewContractSource([]byte(`not json at all`))
	mgr := session.NewManager(fakes.NewFakeClock(fixedNow), badCS, testLogger())

	_, err := mgr.CreateSession(context.Background(), "vc-test-1")
	if !errors.Is(err, session.ErrContractRejected) {
		t.Fatalf("CreateSession error = %v, want wrapping session.ErrContractRejected", err)
	}
	if mgr.Count() != 0 {
		t.Errorf("Count() = %d, want 0 after a rejected contract", mgr.Count())
	}
}

func TestStopSession_NotFound(t *testing.T) {
	defer goleak.VerifyNone(t)

	mgr, _ := newManager(t)
	err := mgr.StopSession(context.Background(), "does-not-exist")
	if !errors.Is(err, session.ErrSessionNotFound) {
		t.Fatalf("StopSession error = %v, want ErrSessionNotFound", err)
	}
}

func TestStopSession_TwiceIsNotFoundSecondTime(t *testing.T) {
	defer goleak.VerifyNone(t)

	mgr, _ := newManager(t)
	got, err := mgr.CreateSession(context.Background(), "vc-test-1")
	if err != nil {
		t.Fatalf("CreateSession: %v", err)
	}
	if err := mgr.StopSession(context.Background(), got.ID); err != nil {
		t.Fatalf("first StopSession: %v", err)
	}
	err = mgr.StopSession(context.Background(), got.ID)
	if !errors.Is(err, session.ErrSessionNotFound) {
		t.Fatalf("second StopSession error = %v, want ErrSessionNotFound", err)
	}
}

// TestCreateStopChurn_RaceAndLeakClean is the plan §14 task 8 "done when":
// create/stop against fakes leaves zero goroutines, proven with goleak, and
// churn is clean under -race. 1000 iterations matches plan task 9's churn
// figure; this task's own actor is a stub, but the lifecycle it exercises is
// the same one task 9 builds the real actor loop on top of.
func TestCreateStopChurn_RaceAndLeakClean(t *testing.T) {
	defer goleak.VerifyNone(t)

	mgr, _ := newManager(t)
	const iterations = 1000
	for i := 0; i < iterations; i++ {
		got, err := mgr.CreateSession(context.Background(), "vc-churn")
		if err != nil {
			t.Fatalf("iteration %d: CreateSession: %v", i, err)
		}
		if err := mgr.StopSession(context.Background(), got.ID); err != nil {
			t.Fatalf("iteration %d: StopSession: %v", i, err)
		}
	}
	if mgr.Count() != 0 {
		t.Errorf("Count() = %d, want 0 after churn", mgr.Count())
	}
}

// TestCreateStopChurn_Concurrent drives create/stop from many goroutines at
// once, proving Manager's registry is race-safe and every session it hands
// out is actually stoppable, under -race.
func TestCreateStopChurn_Concurrent(t *testing.T) {
	defer goleak.VerifyNone(t)

	mgr, _ := newManager(t)
	const workers = 20
	const perWorker = 25

	var wg sync.WaitGroup
	wg.Add(workers)
	for w := 0; w < workers; w++ {
		go func() {
			defer wg.Done()
			for i := 0; i < perWorker; i++ {
				got, err := mgr.CreateSession(context.Background(), "vc-concurrent")
				if err != nil {
					t.Errorf("CreateSession: %v", err)
					return
				}
				if err := mgr.StopSession(context.Background(), got.ID); err != nil {
					t.Errorf("StopSession: %v", err)
					return
				}
			}
		}()
	}
	wg.Wait()

	if mgr.Count() != 0 {
		t.Errorf("Count() = %d, want 0 after concurrent churn", mgr.Count())
	}
}

func TestShutdown_StopsAllLiveSessions(t *testing.T) {
	defer goleak.VerifyNone(t)

	mgr, _ := newManager(t)
	const n = 10
	for i := 0; i < n; i++ {
		if _, err := mgr.CreateSession(context.Background(), "vc-shutdown"); err != nil {
			t.Fatalf("CreateSession: %v", err)
		}
	}
	if mgr.Count() != n {
		t.Fatalf("Count() = %d, want %d before shutdown", mgr.Count(), n)
	}

	if err := mgr.Shutdown(context.Background()); err != nil {
		t.Fatalf("Shutdown: %v", err)
	}
	if mgr.Count() != 0 {
		t.Errorf("Count() = %d, want 0 after Shutdown", mgr.Count())
	}
}

// TestStopSession_CallerContextCancelledStillStopsSession proves that a
// caller giving up on waiting does not abandon the session: the actor's own
// context is independent of the caller's, so cancellation already happened
// and the goroutine still exits — this test's own goleak check would fail
// otherwise.
func TestStopSession_CallerContextCancelledStillStopsSession(t *testing.T) {
	defer goleak.VerifyNone(t)

	mgr, _ := newManager(t)
	got, err := mgr.CreateSession(context.Background(), "vc-test-1")
	if err != nil {
		t.Fatalf("CreateSession: %v", err)
	}

	alreadyCancelled, cancel := context.WithCancel(context.Background())
	cancel()

	err = mgr.StopSession(alreadyCancelled, got.ID)
	if !errors.Is(err, context.Canceled) {
		t.Fatalf("StopSession with cancelled ctx error = %v, want context.Canceled", err)
	}

	// The session was removed from the registry (and its teardown
	// triggered) even though the caller's ctx was already cancelled.
	if _, ok := mgr.Lookup(got.ID); ok {
		t.Error("session still present in registry after a cancelled-ctx StopSession call")
	}

	// e.cancel() already ran synchronously inside StopSession before the
	// select that returned context.Canceled above, so the actor's own
	// teardown is already in flight independent of this test's ctx. Give
	// its goroutine a brief, generous moment to finish exiting before the
	// deferred goleak check runs.
	time.Sleep(100 * time.Millisecond)
}
