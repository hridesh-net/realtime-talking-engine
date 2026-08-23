package session_test

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"testing"

	"go.uber.org/goleak"

	"skillbrew/engine/internal/fakes"
	"skillbrew/engine/internal/session"
)

func newHandler(t *testing.T) (*http.ServeMux, *session.Manager, *fakes.ContractSource) {
	t.Helper()
	mgr, cs := newManager(t)
	mux := http.NewServeMux()
	session.NewHandler(mgr, testLogger()).Register(mux)
	return mux, mgr, cs
}

func TestHTTPCreateSession_Success(t *testing.T) {
	defer goleak.VerifyNone(t)

	mux, mgr, _ := newHandler(t)

	body, err := json.Marshal(map[string]string{"candidate_id": "vc-http-1"})
	if err != nil {
		t.Fatalf("marshal request: %v", err)
	}
	req := httptest.NewRequest(http.MethodPost, "/v1/sessions", bytes.NewReader(body))
	rec := httptest.NewRecorder()
	mux.ServeHTTP(rec, req)

	if rec.Code != http.StatusCreated {
		t.Fatalf("status = %d, want %d; body = %s", rec.Code, http.StatusCreated, rec.Body.String())
	}
	var resp struct {
		SessionID         string `json:"session_id"`
		TransportOfferURL string `json:"transport_offer_url"`
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &resp); err != nil {
		t.Fatalf("unmarshal response: %v; body = %s", err, rec.Body.String())
	}
	if resp.SessionID == "" {
		t.Error("response session_id is empty")
	}
	if resp.TransportOfferURL == "" {
		t.Error("response transport_offer_url is empty")
	}
	if _, ok := mgr.Lookup(resp.SessionID); !ok {
		t.Error("session from response not found in manager")
	}

	if err := mgr.StopSession(context.Background(), resp.SessionID); err != nil {
		t.Fatalf("cleanup StopSession: %v", err)
	}
}

func TestHTTPCreateSession_MalformedBody(t *testing.T) {
	defer goleak.VerifyNone(t)

	mux, _, _ := newHandler(t)

	req := httptest.NewRequest(http.MethodPost, "/v1/sessions", bytes.NewReader([]byte("not json")))
	rec := httptest.NewRecorder()
	mux.ServeHTTP(rec, req)

	if rec.Code != http.StatusBadRequest {
		t.Fatalf("status = %d, want %d", rec.Code, http.StatusBadRequest)
	}
}

func TestHTTPCreateSession_EmptyCandidateID(t *testing.T) {
	defer goleak.VerifyNone(t)

	mux, mgr, _ := newHandler(t)

	body, err := json.Marshal(map[string]string{"candidate_id": ""})
	if err != nil {
		t.Fatalf("marshal request: %v", err)
	}
	req := httptest.NewRequest(http.MethodPost, "/v1/sessions", bytes.NewReader(body))
	rec := httptest.NewRecorder()
	mux.ServeHTTP(rec, req)

	if rec.Code != http.StatusBadRequest {
		t.Fatalf("status = %d, want %d; body = %s", rec.Code, http.StatusBadRequest, rec.Body.String())
	}
	if mgr.Count() != 0 {
		t.Errorf("Count() = %d, want 0", mgr.Count())
	}
}

// TestHTTPCreateSession_UnsupportedContractVersionIs4xx is the requirement's
// explicit case: a contract that fails to parse or pins an unsupported
// version is a client-supplied-persona problem, not a server crash, so it
// must produce a clear 4xx rather than a 500.
func TestHTTPCreateSession_UnsupportedContractVersionIs4xx(t *testing.T) {
	defer goleak.VerifyNone(t)

	badCS := fakes.NewContractSource([]byte(`{"contract_version": "v2.0"}`))
	mgr := session.NewManager(fakes.NewFakeClock(fixedNow), badCS, testLogger(), nil, nil)
	mux := http.NewServeMux()
	session.NewHandler(mgr, testLogger()).Register(mux)

	body, err := json.Marshal(map[string]string{"candidate_id": "vc-http-1"})
	if err != nil {
		t.Fatalf("marshal request: %v", err)
	}
	req := httptest.NewRequest(http.MethodPost, "/v1/sessions", bytes.NewReader(body))
	rec := httptest.NewRecorder()
	mux.ServeHTTP(rec, req)

	if rec.Code < 400 || rec.Code >= 500 {
		t.Fatalf("status = %d, want a 4xx; body = %s", rec.Code, rec.Body.String())
	}
}

// TestHTTPCreateSession_UnparseableContractIs4xx covers the other half of
// the same requirement: malformed contract JSON, not just a bad version.
func TestHTTPCreateSession_UnparseableContractIs4xx(t *testing.T) {
	defer goleak.VerifyNone(t)

	badCS := fakes.NewContractSource([]byte(`not json at all`))
	mgr := session.NewManager(fakes.NewFakeClock(fixedNow), badCS, testLogger(), nil, nil)
	mux := http.NewServeMux()
	session.NewHandler(mgr, testLogger()).Register(mux)

	body, err := json.Marshal(map[string]string{"candidate_id": "vc-http-1"})
	if err != nil {
		t.Fatalf("marshal request: %v", err)
	}
	req := httptest.NewRequest(http.MethodPost, "/v1/sessions", bytes.NewReader(body))
	rec := httptest.NewRecorder()
	mux.ServeHTTP(rec, req)

	if rec.Code < 400 || rec.Code >= 500 {
		t.Fatalf("status = %d, want a 4xx; body = %s", rec.Code, rec.Body.String())
	}
}

func TestHTTPCreateSession_FetchErrorIsNot4xx(t *testing.T) {
	defer goleak.VerifyNone(t)

	mux, _, cs := newHandler(t)
	cs.SetFetchError(errors.New("control plane unreachable"))

	body, err := json.Marshal(map[string]string{"candidate_id": "vc-http-1"})
	if err != nil {
		t.Fatalf("marshal request: %v", err)
	}
	req := httptest.NewRequest(http.MethodPost, "/v1/sessions", bytes.NewReader(body))
	rec := httptest.NewRecorder()
	mux.ServeHTTP(rec, req)

	// A dependency failure fetching the contract is an engine-side problem,
	// not the caller's — it must not be reported as a 4xx.
	if rec.Code < 500 {
		t.Fatalf("status = %d, want 5xx for an upstream fetch failure", rec.Code)
	}
}

func TestHTTPStopSession_Success(t *testing.T) {
	defer goleak.VerifyNone(t)

	mux, mgr, _ := newHandler(t)
	got, err := mgr.CreateSession(context.Background(), "vc-http-1")
	if err != nil {
		t.Fatalf("CreateSession: %v", err)
	}

	req := httptest.NewRequest(http.MethodDelete, "/v1/sessions/"+got.ID, nil)
	rec := httptest.NewRecorder()
	mux.ServeHTTP(rec, req)

	if rec.Code != http.StatusNoContent {
		t.Fatalf("status = %d, want %d; body = %s", rec.Code, http.StatusNoContent, rec.Body.String())
	}
	if _, ok := mgr.Lookup(got.ID); ok {
		t.Error("session still present after DELETE")
	}
}

func TestHTTPStopSession_NotFound(t *testing.T) {
	defer goleak.VerifyNone(t)

	mux, _, _ := newHandler(t)

	req := httptest.NewRequest(http.MethodDelete, "/v1/sessions/does-not-exist", nil)
	rec := httptest.NewRecorder()
	mux.ServeHTTP(rec, req)

	if rec.Code != http.StatusNotFound {
		t.Fatalf("status = %d, want %d", rec.Code, http.StatusNotFound)
	}
}
