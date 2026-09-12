package controlplane_test

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"sync/atomic"
	"testing"
	"time"

	"go.uber.org/goleak"

	"skillbrew/engine/internal/controlplane"
	"skillbrew/engine/internal/ports"
)

func quietLogger() *slog.Logger { return slog.New(slog.NewTextHandler(io.Discard, nil)) }

func verifyNoEngineLeaks(t *testing.T) {
	t.Cleanup(func() {
		goleak.VerifyNone(t,
			goleak.IgnoreTopFunction("net/http.(*connReader).backgroundRead"),
			goleak.IgnoreTopFunction("net/http.(*persistConn).writeLoop"),
			goleak.IgnoreTopFunction("net/http.(*persistConn).readLoop"),
			goleak.IgnoreTopFunction("internal/poll.runtime_pollWait"),
		)
	})
}

func newClient(t *testing.T, srv *httptest.Server, opts ...controlplane.Option) *controlplane.Client {
	t.Helper()
	t.Cleanup(srv.CloseClientConnections)
	opts = append([]controlplane.Option{
		controlplane.WithHTTPClient(srv.Client()),
		controlplane.WithBackoff(), // one attempt unless a test says otherwise
	}, opts...)
	c, err := controlplane.New(srv.URL, "s3cret", quietLogger(), opts...)
	if err != nil {
		t.Fatalf("New: %v", err)
	}
	return c
}

func sampleIngest() ports.SessionIngest {
	return ports.SessionIngest{
		SessionID: "sess-1", CandidateID: "vc-1", InterviewID: "int-1",
		ContractFingerprint: "abc", EngineVersion: "test",
		StartedAt: time.Date(2026, 9, 12, 10, 0, 0, 0, time.UTC),
		EndedAt:   time.Date(2026, 9, 12, 10, 20, 0, 0, time.UTC),
		EndReason: "interviewer_ended",
		Turns:     []ports.TurnIngest{{Turn: 1, Speaker: "human", Text: "hello", EndMs: 900}},
		Metrics:   map[string]float64{"turns": 1},
	}
}

func TestFetchContractSendsTheSharedSecretAndReturnsTheBody(t *testing.T) {
	verifyNoEngineLeaks(t)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/v1/candidates/vc%2F1/engine-contract" && r.URL.Path != "/api/v1/candidates/vc/1/engine-contract" {
			t.Errorf("path = %q", r.URL.Path)
		}
		if got := r.Header.Get("Authorization"); got != "Bearer s3cret" {
			t.Errorf("authorization = %q; the shared secret must ride as a bearer token", got)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"contract_version":"v1.3"}`))
	}))
	defer srv.Close()
	c := newClient(t, srv)

	body, err := c.FetchContract(context.Background(), "vc/1")
	if err != nil {
		t.Fatalf("FetchContract: %v", err)
	}
	if string(body) != `{"contract_version":"v1.3"}` {
		t.Fatalf("body = %s", body)
	}
}

func TestFetchContractMapsNotFoundToTheSentinel(t *testing.T) {
	verifyNoEngineLeaks(t)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		http.Error(w, `{"error":"candidate not found"}`, http.StatusNotFound)
	}))
	defer srv.Close()
	c := newClient(t, srv)

	_, err := c.FetchContract(context.Background(), "nope")
	if !errors.Is(err, ports.ErrContractNotFound) {
		t.Fatalf("err = %v, want ErrContractNotFound", err)
	}
}

func TestFetchContractReportsARefusedSecret(t *testing.T) {
	verifyNoEngineLeaks(t)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		http.Error(w, `{"error":"engine credential rejected"}`, http.StatusUnauthorized)
	}))
	defer srv.Close()
	c := newClient(t, srv)

	_, err := c.FetchContract(context.Background(), "vc-1")
	if err == nil || errors.Is(err, ports.ErrContractNotFound) {
		t.Fatalf("err = %v, want a non-not-found failure naming HTTP 401", err)
	}
}

func TestNotifyIngestCarriesTheIdempotencyKeyAndTreatsConflictAsDelivered(t *testing.T) {
	verifyNoEngineLeaks(t)
	var calls atomic.Int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls.Add(1)
		if r.URL.Path != "/api/v1/sessions/sess-1/ingest" {
			t.Errorf("path = %q", r.URL.Path)
		}
		if r.Header.Get("Idempotency-Key") != "sess-1" {
			t.Errorf("Idempotency-Key = %q", r.Header.Get("Idempotency-Key"))
		}
		var body map[string]any
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			t.Errorf("decode: %v", err)
		}
		if body["session_id"] != "sess-1" || body["end_reason"] != "interviewer_ended" {
			t.Errorf("body = %v", body)
		}
		if turns, ok := body["turns"].([]any); !ok || len(turns) != 1 {
			t.Errorf("turns = %v", body["turns"])
		}
		for _, key := range []string{"ceiling_flags", "suppressed_answers", "degradations"} {
			if _, ok := body[key].([]any); !ok {
				t.Errorf("%s = %v, want a list even when empty", key, body[key])
			}
		}
		if calls.Load() == 1 {
			w.WriteHeader(http.StatusCreated)
			return
		}
		http.Error(w, `{"error":"already ingested"}`, http.StatusConflict)
	}))
	defer srv.Close()
	c := newClient(t, srv)

	if err := c.NotifyIngest(context.Background(), sampleIngest()); err != nil {
		t.Fatalf("first notify: %v", err)
	}
	if err := c.NotifyIngest(context.Background(), sampleIngest()); err != nil {
		t.Fatalf("repeat notify must treat a conflict as delivered: %v", err)
	}
}

func TestNotifyIngestRetriesServerErrorsThenSucceeds(t *testing.T) {
	verifyNoEngineLeaks(t)
	var calls atomic.Int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		if calls.Add(1) < 3 {
			http.Error(w, "boom", http.StatusBadGateway)
			return
		}
		w.WriteHeader(http.StatusOK)
	}))
	defer srv.Close()
	c := newClient(t, srv, controlplane.WithBackoff(time.Millisecond, time.Millisecond))

	if err := c.NotifyIngest(context.Background(), sampleIngest()); err != nil {
		t.Fatalf("notify: %v", err)
	}
	if calls.Load() != 3 {
		t.Fatalf("calls = %d, want 3 (two server errors, then success)", calls.Load())
	}
}

func TestNotifyIngestDoesNotRetryARejectedPayload(t *testing.T) {
	verifyNoEngineLeaks(t)
	var calls atomic.Int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		calls.Add(1)
		http.Error(w, `{"error":"candidate not found"}`, http.StatusNotFound)
	}))
	defer srv.Close()
	dir := t.TempDir()
	c := newClient(t, srv, controlplane.WithBackoff(time.Millisecond, time.Millisecond), controlplane.WithSpoolDir(dir))

	err := c.NotifyIngest(context.Background(), sampleIngest())
	if err == nil || errors.Is(err, controlplane.ErrIngestSpooled) {
		t.Fatalf("err = %v, want a definitive rejection, not a spool", err)
	}
	if calls.Load() != 1 {
		t.Fatalf("calls = %d; a 404 must not be retried", calls.Load())
	}
	if entries, _ := os.ReadDir(dir); len(entries) != 0 {
		t.Fatalf("spool = %v; a rejected payload must not be spooled", entries)
	}
}

func TestNotifyIngestSpoolsWhenTheControlPlaneIsDownAndDrainsLater(t *testing.T) {
	verifyNoEngineLeaks(t)
	var up atomic.Bool
	var received atomic.Int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if !up.Load() {
			http.Error(w, "restarting", http.StatusServiceUnavailable)
			return
		}
		if r.Header.Get("Idempotency-Key") != "sess-1" {
			t.Errorf("drained post lost the idempotency key: %q", r.Header.Get("Idempotency-Key"))
		}
		received.Add(1)
		w.WriteHeader(http.StatusCreated)
	}))
	defer srv.Close()
	dir := filepath.Join(t.TempDir(), "ingest")
	c := newClient(t, srv, controlplane.WithBackoff(time.Millisecond), controlplane.WithSpoolDir(dir))

	err := c.NotifyIngest(context.Background(), sampleIngest())
	if !errors.Is(err, controlplane.ErrIngestSpooled) {
		t.Fatalf("err = %v, want ErrIngestSpooled", err)
	}
	entries, _ := os.ReadDir(dir)
	if len(entries) != 1 || entries[0].Name() != "sess-1.json" {
		t.Fatalf("spool entries = %v, want sess-1.json", entries)
	}

	// Still down: the drain keeps the file.
	if n, err := c.DrainSpool(context.Background()); n != 0 || err == nil {
		t.Fatalf("drain while down = %d, %v; want 0 delivered and an error", n, err)
	}
	if entries, _ := os.ReadDir(dir); len(entries) != 1 {
		t.Fatal("a failed drain must keep the payload")
	}

	up.Store(true)
	n, err := c.DrainSpool(context.Background())
	if err != nil || n != 1 {
		t.Fatalf("drain = %d, %v; want 1 delivered", n, err)
	}
	if received.Load() != 1 {
		t.Fatalf("control plane received %d payloads, want 1", received.Load())
	}
	if entries, _ := os.ReadDir(dir); len(entries) != 0 {
		t.Fatalf("spool after drain = %v, want empty", entries)
	}
}

func TestNewRejectsAnUnusableConfiguration(t *testing.T) {
	if _, err := controlplane.New("127.0.0.1:8081", "s", quietLogger()); err == nil {
		t.Fatal("a base URL without a scheme was accepted")
	}
	if _, err := controlplane.New("http://127.0.0.1:8081", "", quietLogger()); err == nil {
		t.Fatal("an empty shared secret was accepted")
	}
}
