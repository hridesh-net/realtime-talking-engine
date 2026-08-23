// Package thinkerllm implements the Thinker port over a JSON-mode LLM API.
//
// The Thinker is the persona's subconscious. It runs *speculatively*: it is
// fed the interviewer's question as it is transcribed, so that by the time the
// question ends it has already been reasoning for seconds. That is the whole
// reason the two-model design works at all — a reasoning call started at
// end-of-turn would arrive several seconds late, long after the silence became
// unbearable.
//
// It retrieves and elaborates material the contract already fixed. It never
// invents a belief at runtime: doing so would void the persona's
// seed_fingerprint, which is the determinism the whole product rests on.
package thinkerllm

import (
	"context"
	"net/http"
	"strings"
	"sync"
	"time"

	"skillbrew/engine/internal/ports"
	"skillbrew/engine/internal/vendors/shared/geminijson"
)

// Option configures a Thinker.
type Option func(*Thinker)

// WithHTTPClient injects the HTTP client, so tests can drive the adapter
// against an httptest server instead of a vendor.
func WithHTTPClient(c *http.Client) Option {
	return func(t *Thinker) { t.http = c }
}

// WithEndpoint overrides the API base URL.
func WithEndpoint(url string) Option {
	return func(t *Thinker) { t.endpoint = url }
}

// WithMinPartialWords sets how much of a question must have arrived before a
// speculative call is worth spending. Too low and every "so," costs a request;
// too high and the speculation has no head start left to give.
func WithMinPartialWords(n int) Option {
	return func(t *Thinker) { t.minPartialWords = n }
}

// Thinker is a ports.Thinker backed by a JSON-mode reasoning model.
type Thinker struct {
	modelID string
	apiKey  string
	http    *http.Client

	endpoint        string
	minPartialWords int

	mu sync.Mutex
	// persona is the standing context: system prompt plus ledger.
	persona ports.PersonaCtx
	// question is the interviewer's utterance so far.
	question string
	// speculation is the in-flight or completed guess for the current
	// question. Replaced whenever the question materially grows.
	speculation *attempt
	closed      bool
}

// attempt is one speculative reasoning call.
type attempt struct {
	done   chan struct{}
	cancel context.CancelFunc
	note   ports.Note
	err    error
}

var _ ports.Thinker = (*Thinker)(nil)

// New returns a Thinker. modelID and apiKey come from internal/config — this
// package never reads the environment (plan §10 arch check 4).
func New(modelID, apiKey string, opts ...Option) *Thinker {
	t := &Thinker{
		modelID:         modelID,
		apiKey:          apiKey,
		http:            &http.Client{Timeout: 20 * time.Second},
		endpoint:        geminijson.DefaultEndpoint,
		minPartialWords: 4,
	}
	for _, o := range opts {
		o(t)
	}
	return t
}

// client builds the shared vendor client for this Thinker.
func (t *Thinker) client() *geminijson.Client {
	return &geminijson.Client{Endpoint: t.endpoint, HTTP: t.http, APIKey: t.apiKey}
}

// Start begins speculative operation for one session.
func (t *Thinker) Start(_ context.Context, persona ports.PersonaCtx) error {
	t.mu.Lock()
	defer t.mu.Unlock()
	t.persona = persona
	t.closed = false
	return nil
}

// FeedPartial streams the in-progress question in.
//
// Each materially longer partial supersedes the last speculation: a guess made
// from four words is worth less than one made from twelve, and keeping both
// would mean answering a question the interviewer did not finish asking.
func (t *Thinker) FeedPartial(ctx context.Context, text string) error {
	t.mu.Lock()
	defer t.mu.Unlock()
	if t.closed {
		return nil
	}
	text = strings.TrimSpace(text)
	if text == "" || text == t.question {
		return nil
	}
	t.question = text
	if len(strings.Fields(text)) < t.minPartialWords {
		return nil
	}
	t.startSpeculationLocked(ctx, text)
	return nil
}

// RequestNote asks for a structured note before deadline.
//
// The returned channel delivers at most one Note and is never sent to after
// the deadline. A miss is the caller's to detect: the actor has its own timer
// and a persona-correct fallback, and blocking on a late reasoning model would
// be exactly the failure the stall bank exists to avoid.
func (t *Thinker) RequestNote(ctx context.Context, deadline time.Time) <-chan ports.Note {
	out := make(chan ports.Note, 1)

	t.mu.Lock()
	if t.closed {
		t.mu.Unlock()
		close(out)
		return out
	}
	if t.speculation == nil && t.question != "" {
		// Nothing speculative in flight — a very short question, or one
		// that arrived all at once. Start now and hope it lands.
		t.startSpeculationLocked(ctx, t.question)
	}
	att := t.speculation
	t.mu.Unlock()

	if att == nil {
		close(out)
		return out
	}

	go func() {
		timer := time.NewTimer(time.Until(deadline))
		defer timer.Stop()
		select {
		case <-att.done:
			if att.err == nil {
				out <- att.note
			}
			close(out)
		case <-timer.C:
			// Deadline. Leave the call running — its result may still be
			// useful to the next turn, and cancelling buys nothing.
			close(out)
		case <-ctx.Done():
			close(out)
		}
	}()
	return out
}

// Reset re-seeds the Thinker with the ledger after a turn closes. Never a cold
// call: the persona context stays, only the ledger and the question move.
func (t *Thinker) Reset(_ context.Context, ledgerSummary string) error {
	t.mu.Lock()
	defer t.mu.Unlock()
	t.persona.LedgerSummary = ledgerSummary
	t.question = ""
	t.abandonSpeculationLocked()
	return nil
}

// Close ends the session and releases resources.
func (t *Thinker) Close(_ context.Context) error {
	t.mu.Lock()
	defer t.mu.Unlock()
	t.closed = true
	t.abandonSpeculationLocked()
	return nil
}

// startSpeculationLocked replaces any in-flight guess with one for question.
func (t *Thinker) startSpeculationLocked(ctx context.Context, question string) {
	t.abandonSpeculationLocked()
	callCtx, cancel := context.WithCancel(context.WithoutCancel(ctx))
	att := &attempt{done: make(chan struct{}), cancel: cancel}
	t.speculation = att
	persona := t.persona

	go func() {
		defer close(att.done)
		att.note, att.err = t.generate(callCtx, persona, question)
	}()
}

// abandonSpeculationLocked cancels the in-flight guess.
func (t *Thinker) abandonSpeculationLocked() {
	if t.speculation != nil {
		t.speculation.cancel()
		t.speculation = nil
	}
}
