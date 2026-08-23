package geminijson_test

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"go.uber.org/goleak"

	"skillbrew/engine/internal/vendors/shared/geminijson"
)

// verifyNoEngineLeaks is goleak scoped to goroutines this package owns.
// httptest and the stdlib transport keep connection goroutines alive past
// Close and they are not ours; ignoring those by name keeps the check sharp
// rather than dropping it because httptest is noisy.
func verifyNoEngineLeaks(t *testing.T) {
	goleak.VerifyNone(t,
		goleak.IgnoreTopFunction("net/http.(*connReader).backgroundRead"),
		goleak.IgnoreTopFunction("net/http.(*persistConn).writeLoop"),
		goleak.IgnoreTopFunction("net/http.(*persistConn).readLoop"),
		goleak.IgnoreTopFunction("internal/poll.runtime_pollWait"),
	)
}

// envelope wraps a payload the way the vendor does, so tests state the
// model's answer rather than the transport's packaging.
func envelope(text string) string {
	b, _ := json.Marshal(text)
	return `{"candidates":[{"content":{"parts":[{"text":` + string(b) + `}]}}]}`
}

func newClient(srv *httptest.Server) *geminijson.Client {
	return &geminijson.Client{Endpoint: srv.URL, HTTP: srv.Client(), APIKey: "test-key"}
}

func sampleRequest() geminijson.Request {
	return geminijson.Request{
		ModelID:     "test-model",
		System:      "you are a test",
		Prompt:      "the question",
		Schema:      map[string]any{"type": "object"},
		Temperature: 0.25,
	}
}

// TestTheRequestCarriesEverythingTheVendorNeedsToConstrainTheAnswer matters
// because this client's whole purpose is schema-constrained JSON. If the
// schema or the MIME type were dropped the vendor would answer in prose, and
// both callers would fail at the decode step with an error pointing at the
// wrong layer.
func TestTheRequestCarriesEverythingTheVendorNeedsToConstrainTheAnswer(t *testing.T) {
	defer verifyNoEngineLeaks(t)

	type captured struct {
		path   string
		apiKey string
		body   map[string]any
	}
	got := make(chan captured, 1)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var body map[string]any
		raw, _ := io.ReadAll(r.Body)
		_ = json.Unmarshal(raw, &body)
		got <- captured{path: r.URL.Path, apiKey: r.Header.Get("x-goog-api-key"), body: body}
		_, _ = io.WriteString(w, envelope(`{"ok":true}`))
	}))
	t.Cleanup(srv.Close)

	payload, err := newClient(srv).Do(context.Background(), sampleRequest())
	if err != nil {
		t.Fatalf("Do: %v", err)
	}
	if string(payload) != `{"ok":true}` {
		t.Fatalf("payload = %s, want the model's own text unwrapped from the envelope", payload)
	}

	c := <-got
	if !strings.HasSuffix(c.path, "/test-model:generateContent") {
		t.Fatalf("path = %q, want it to name the model and the generateContent method", c.path)
	}
	if c.apiKey != "test-key" {
		t.Fatalf("x-goog-api-key = %q, want the injected key", c.apiKey)
	}

	cfg, ok := c.body["generationConfig"].(map[string]any)
	if !ok {
		t.Fatalf("request has no generationConfig: %v", c.body)
	}
	if cfg["responseMimeType"] != "application/json" {
		t.Fatalf("responseMimeType = %v, want application/json", cfg["responseMimeType"])
	}
	if cfg["responseSchema"] == nil {
		t.Fatal("responseSchema is absent; the answer would come back as prose")
	}
	if cfg["temperature"] != 0.25 {
		t.Fatalf("temperature = %v, want the caller's 0.25 — the two callers want opposite things here", cfg["temperature"])
	}
	if c.body["system_instruction"] == nil {
		t.Fatal("system_instruction is absent")
	}
}

// TestAnHTTPErrorReportsTheVendorsOwnExplanation matters because the two
// failures this client sees most — a bad key and a quota refusal — are both
// non-200 with the reason in the body. Reporting only the status code would
// send whoever is on call to read the wrong thing.
func TestAnHTTPErrorReportsTheVendorsOwnExplanation(t *testing.T) {
	defer verifyNoEngineLeaks(t)

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusTooManyRequests)
		_, _ = io.WriteString(w, `{"error":{"message":"quota exceeded for this project"}}`)
	}))
	t.Cleanup(srv.Close)

	_, err := newClient(srv).Do(context.Background(), sampleRequest())
	if err == nil {
		t.Fatal("a 429 must be an error")
	}
	if !strings.Contains(err.Error(), "429") || !strings.Contains(err.Error(), "quota exceeded") {
		t.Fatalf("error = %q, want it to carry both the status and the vendor's message", err)
	}
}

// TestAVendorErrorInsideATwoHundredIsStillAnError matters because this API
// reports some failures in the body of an otherwise successful response. A
// client that only checked the status would hand its caller an empty payload
// and let it be mistaken for a legitimate answer.
func TestAVendorErrorInsideATwoHundredIsStillAnError(t *testing.T) {
	defer verifyNoEngineLeaks(t)

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_, _ = io.WriteString(w, `{"error":{"message":"model overloaded"}}`)
	}))
	t.Cleanup(srv.Close)

	_, err := newClient(srv).Do(context.Background(), sampleRequest())
	if err == nil {
		t.Fatal("an error object inside a 200 must be an error")
	}
	if !strings.Contains(err.Error(), "model overloaded") {
		t.Fatalf("error = %q, want the vendor's message", err)
	}
}

// TestAnAnswerlessResponseIsAnErrorRatherThanEmptyText matters because a
// response with no candidates — a safety block, for one — decodes perfectly
// well. Returning its empty text would make a blocked call indistinguishable
// from a model that legitimately had nothing to say.
func TestAnAnswerlessResponseIsAnErrorRatherThanEmptyText(t *testing.T) {
	defer verifyNoEngineLeaks(t)

	for _, tc := range []struct{ name, body string }{
		{"no candidates", `{"candidates":[]}`},
		{"a candidate with no parts", `{"candidates":[{"content":{"parts":[]}}]}`},
	} {
		t.Run(tc.name, func(t *testing.T) {
			srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
				_, _ = io.WriteString(w, tc.body)
			}))
			t.Cleanup(srv.Close)

			if _, err := newClient(srv).Do(context.Background(), sampleRequest()); err == nil {
				t.Fatal("an answerless response must be an error, not empty text")
			}
		})
	}
}

// TestTheResponseBodyIsBoundedSoOneVendorCannotExhaustTheNode matters because
// a node runs many sessions at once and every one of them holds this client.
// An unbounded ReadAll turns a vendor bug — or a hostile response — into an
// out-of-memory kill that takes every live interview on the box with it.
func TestTheResponseBodyIsBoundedSoOneVendorCannotExhaustTheNode(t *testing.T) {
	defer verifyNoEngineLeaks(t)

	const wantAtMost = 3 << 20 // the limit is 1 MiB; allow generous slack for socket buffers
	var written atomic.Int64
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		chunk := make([]byte, 64<<10)
		for i := range chunk {
			chunk[i] = 'a'
		}
		// Far more than the limit. The write fails once the client stops
		// reading and closes, which is the behaviour under test.
		for i := 0; i < 512; i++ {
			n, err := w.Write(chunk)
			written.Add(int64(n))
			if err != nil {
				return
			}
		}
	}))
	t.Cleanup(srv.Close)

	// The truncated body is not valid JSON, so this is an error either way.
	// What is being asserted is how much was consumed getting there.
	if _, err := newClient(srv).Do(context.Background(), sampleRequest()); err == nil {
		t.Fatal("a 32 MiB run of 'a' is not a valid response and must not decode")
	}
	if got := written.Load(); got > wantAtMost {
		t.Fatalf("the vendor pushed %d bytes before the client stopped reading; the read is meant to be bounded at 1 MiB", got)
	}
}

// TestACancelledContextAbandonsTheCallRatherThanWaitingOutTheTimeout matters
// because the Judge cancels in-flight reviews at session teardown and the
// Thinker abandons speculation the moment it is superseded. Without
// propagation both would hold their goroutine for the client's full timeout.
func TestACancelledContextAbandonsTheCallRatherThanWaitingOutTheTimeout(t *testing.T) {
	defer verifyNoEngineLeaks(t)

	srv := httptest.NewServer(http.HandlerFunc(func(_ http.ResponseWriter, r *http.Request) {
		// Draining the body is what lets the server observe the client
		// going away; without it this handler would never be woken.
		_, _ = io.Copy(io.Discard, r.Body)
		<-r.Context().Done()
	}))
	t.Cleanup(srv.Close)

	ctx, cancel := context.WithCancel(context.Background())
	go func() {
		time.Sleep(50 * time.Millisecond)
		cancel()
	}()

	done := make(chan error, 1)
	go func() {
		_, err := newClient(srv).Do(ctx, sampleRequest())
		done <- err
	}()

	select {
	case err := <-done:
		if !errors.Is(err, context.Canceled) {
			t.Fatalf("error = %v, want it to wrap context.Canceled", err)
		}
	case <-time.After(3 * time.Second):
		t.Fatal("Do ignored its cancelled context and kept waiting on the vendor")
	}
}
