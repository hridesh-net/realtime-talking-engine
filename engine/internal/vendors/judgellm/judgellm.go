// Package judgellm implements the async post-hoc Judge over a JSON-mode LLM.
//
// This is the only ceiling layer that is an actual guarantee. Every layer
// before it is best-effort: the system prompt drifts under pressure, the
// pre-gate cannot see semantics, the stall-and-note path has a deadline it can
// miss. A fluent, in-character, level-6 answer against a ceiling of 3 is a
// *semantic depth* failure no lexicon or regex catches.
//
// So the Judge runs after the fact, seconds late, and cannot un-say the audio.
// What it guarantees is that every persona turn is reviewed and every breach
// is labelled — which is what stops the report crediting an interviewer for
// depth that was never supposed to exist. Latency is irrelevant here by
// design; being late is the price of reading what was actually said.
package judgellm

import (
	"context"
	"fmt"
	"net/http"
	"sync"

	"skillbrew/engine/internal/ports"
	"skillbrew/engine/internal/vendors/shared/geminijson"
)

// queueDepth bounds submitted-but-unreviewed turns.
//
// Bounded, and it drops rather than blocks. Submit is called by the session
// actor at turn close, and that actor is the goroutine driving a live
// conversation — a Judge backlog must never become backpressure on somebody's
// interview. A dropped review is a gap in the grading metadata; a blocked
// actor is a stalled call.
const queueDepth = 32

// Option configures a Judge.
type Option func(*Judge)

// WithHTTPClient injects the HTTP client so tests can drive the adapter
// against an httptest server.
func WithHTTPClient(c *http.Client) Option { return func(j *Judge) { j.http = c } }

// WithEndpoint overrides the API base URL.
func WithEndpoint(url string) Option { return func(j *Judge) { j.endpoint = url } }

// Judge reviews persona turns against their skill ceiling, asynchronously.
type Judge struct {
	modelID  string
	apiKey   string
	http     *http.Client
	endpoint string

	// client is built once. The vendor call is stateless, so rebuilding it
	// per review only allocated.
	client *geminijson.Client

	in       chan ports.TurnForReview
	out      chan ports.Verdict
	stop     chan struct{}
	wg       sync.WaitGroup
	closeOne sync.Once

	// ctx bounds every review and is cancelled by Close.
	//
	// Deliberately not the submitting turn's context: the whole point of
	// this layer is to outlive the turn it is reviewing. Equally
	// deliberately one context for the Judge's whole life rather than one
	// per review — the per-review form needed a watcher goroutine each
	// time to translate stop into cancel, and those accumulated for the
	// length of the session, one per persona turn.
	ctx    context.Context
	cancel context.CancelFunc

	// dropped counts turns shed because the queue was full, and failed
	// counts reviews the vendor never answered. Both are surfaced so a
	// session that reviewed less than it should says so, rather than
	// looking merely clean — a gap in the grading metadata is not a clean
	// bill of health, and the two causes have different fixes.
	mu      sync.Mutex
	dropped int
	failed  int
}

var _ ports.Judge = (*Judge)(nil)

// New starts a Judge with one review worker.
//
// One worker, not a pool: reviews are cheap relative to a session, and ordered
// work is easier to reconcile against the event log. If review latency ever
// matters the fix is more workers, and it is one line.
func New(modelID, apiKey string, opts ...Option) *Judge {
	j := &Judge{
		modelID:  modelID,
		apiKey:   apiKey,
		endpoint: geminijson.DefaultEndpoint,
		in:       make(chan ports.TurnForReview, queueDepth),
		out:      make(chan ports.Verdict, queueDepth),
		stop:     make(chan struct{}),
	}
	for _, o := range opts {
		o(j)
	}
	j.ctx, j.cancel = context.WithCancel(context.Background())
	j.client = &geminijson.Client{Endpoint: j.endpoint, HTTP: j.http, APIKey: j.apiKey}
	j.wg.Add(1)
	go j.run()
	return j
}

// Submit queues a turn for review. It never blocks.
func (j *Judge) Submit(_ context.Context, turn ports.TurnForReview) error {
	select {
	case <-j.stop:
		return fmt.Errorf("judgellm: closed")
	default:
	}
	select {
	case j.in <- turn:
		return nil
	default:
		j.mu.Lock()
		j.dropped++
		j.mu.Unlock()
		return fmt.Errorf("judgellm: review queue full, turn %d dropped", turn.Turn)
	}
}

// Verdicts returns the stream of verdicts as they complete, in no guaranteed
// order relative to Submit calls.
func (j *Judge) Verdicts() <-chan ports.Verdict { return j.out }

// Dropped reports how many turns were shed because the queue was full.
func (j *Judge) Dropped() int {
	j.mu.Lock()
	defer j.mu.Unlock()
	return j.dropped
}

// Failed reports how many reviews were attempted but produced no verdict
// because the vendor call errored. Separate from Dropped: one means the Judge
// could not keep up, the other means the vendor did not answer.
func (j *Judge) Failed() int {
	j.mu.Lock()
	defer j.mu.Unlock()
	return j.failed
}

// Close stops the worker and closes the verdict stream.
func (j *Judge) Close() {
	j.closeOne.Do(func() {
		// Order matters: stop first so the worker's loop cannot pick up
		// another turn, then cancel so any call already in flight at the
		// vendor unblocks instead of holding Close for its full timeout.
		close(j.stop)
		j.cancel()
		j.wg.Wait()
		close(j.out)
	})
}

func (j *Judge) run() {
	defer j.wg.Done()
	for {
		// Stop is checked on its own first. A plain two-case select picks
		// uniformly at random among ready cases, so with a full queue a
		// closed stop would be passed over roughly half the time and Close
		// would drain the backlog before returning.
		select {
		case <-j.stop:
			return
		default:
		}
		select {
		case <-j.stop:
			return
		case turn := <-j.in:
			verdict, err := j.review(j.ctx, turn)
			if err != nil {
				// A failed review is a gap, not a breach. Inferring
				// either verdict from a vendor error would be worse than
				// saying nothing about the turn — but it is counted, so
				// the gap is visible rather than silent.
				j.mu.Lock()
				j.failed++
				j.mu.Unlock()
				continue
			}
			select {
			case j.out <- verdict:
			case <-j.stop:
				return
			}
		}
	}
}
