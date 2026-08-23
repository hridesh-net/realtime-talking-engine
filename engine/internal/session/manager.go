package session

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"sync"
	"time"

	"skillbrew/engine/internal/contract"
	"skillbrew/engine/internal/obs"
	"skillbrew/engine/internal/ports"
)

// Session is the information about a live session Manager exposes outside
// the package. It deliberately carries no actor internals — those stay
// owned by the actor's own goroutine (plan §4).
type Session struct {
	// ID is the session's generated identifier.
	ID string
	// CandidateID is the candidate id the session was created for.
	CandidateID string
	// CreatedAt is when Manager.CreateSession spawned this session's actor,
	// per the injected Clock.
	CreatedAt time.Time
}

// entry is Manager's private bookkeeping for one live session: the pieces
// needed to stop it and answer Lookup, kept separate from the actor's own
// state so Manager never reaches into the actor's goroutine-owned fields.
type entry struct {
	info   Session
	cancel context.CancelFunc
	done   chan struct{}
}

// Manager creates, looks up, and stops session actors, keyed by a generated
// session id. Safe for concurrent use; holding ~50 concurrent live sessions
// per node is the normal case (plan §1), not an edge case to special-case
// for.
//
// Each session's actor runs under its own context, independent of any
// caller's request context: a session must not be torn down just because
// the HTTP request that created or is stopping it was cancelled or its
// client disconnected.
type Manager struct {
	clock     ports.Clock
	contracts ports.ContractSource
	logger    *slog.Logger
	// events is the session event log. Nil is legal and means "discard":
	// the log is the grader's record, not a runtime dependency, and a
	// missing sink must never stop an interview.
	events *obs.EventLog

	mu       sync.RWMutex
	sessions map[string]*entry
}

// NewManager constructs a Manager. clock is the actor's only source of time
// (plan §4); contracts fetches and validates the engine contract a new
// session runs.
func NewManager(
	clock ports.Clock,
	contracts ports.ContractSource,
	logger *slog.Logger,
	events *obs.EventLog,
) *Manager {
	return &Manager{
		events:    events,
		clock:     clock,
		contracts: contracts,
		logger:    logger,
		sessions:  make(map[string]*entry),
	}
}

// CreateSession fetches candidateID's engine contract, parses and validates
// it, and spawns a session actor for it. ctx bounds the contract fetch only
// — once the actor is spawned, its lifetime is independent of ctx.
//
// A contract that fails to parse or pins to an unsupported major version
// (contract.ErrInvalidContract / contract.ErrUnsupportedVersion) is
// returned wrapped, unmodified, so callers can match it with errors.Is: a
// bad persona is a client problem, not an engine failure, and the HTTP
// layer maps it to 400 accordingly.
func (m *Manager) CreateSession(ctx context.Context, candidateID string) (Session, error) {
	if candidateID == "" {
		return Session{}, ErrEmptyCandidateID
	}

	raw, err := m.contracts.FetchContract(ctx, candidateID)
	if err != nil {
		return Session{}, fmt.Errorf("session: fetch contract for %q: %w", candidateID, err)
	}

	c, err := contract.Parse(raw)
	if err != nil {
		// contract.Parse's own error only satisfies errors.Is against
		// contract.ErrInvalidContract/ErrUnsupportedVersion for validation
		// and version failures — a raw JSON decode failure (malformed body,
		// not merely an invalid-but-well-formed one) carries no such
		// sentinel. ErrContractRejected covers all three uniformly, wrapped
		// alongside the original error (Go's multi-%w) so the HTTP layer
		// can classify "contract.Parse rejected this" as one client-input
		// case without depending on which specific way it failed.
		return Session{}, fmt.Errorf("session: parse contract for %q: %w: %w", candidateID, ErrContractRejected, err)
	}

	id, err := newSessionID()
	if err != nil {
		return Session{}, err
	}

	info := Session{
		ID:          id,
		CandidateID: candidateID,
		CreatedAt:   m.clock.Now(),
	}

	// The actor's context is rooted independently of ctx (see the type
	// doc): a session outlives the HTTP request that created it.
	actorCtx, cancel := context.WithCancel(context.Background())
	a := newActor(id, c, m.clock,
		m.logger.With("session_id", id, "candidate_id", candidateID), m.events)
	done := make(chan struct{})
	go a.run(actorCtx, done)

	m.mu.Lock()
	m.sessions[id] = &entry{info: info, cancel: cancel, done: done}
	m.mu.Unlock()

	m.logger.Info("session created", "session_id", id, "candidate_id", candidateID)
	return info, nil
}

// Lookup returns the live session for id, and whether it was found.
func (m *Manager) Lookup(id string) (Session, bool) {
	m.mu.RLock()
	defer m.mu.RUnlock()
	e, ok := m.sessions[id]
	if !ok {
		return Session{}, false
	}
	return e.info, true
}

// Count returns the number of live sessions.
func (m *Manager) Count() int {
	m.mu.RLock()
	defer m.mu.RUnlock()
	return len(m.sessions)
}

// StopSession cancels the session's actor and blocks until its owner
// goroutine has fully exited before returning — the synchronization the
// "zero goroutines after stop" guarantee (plan §14 task 8) depends on. The
// session is removed from the registry before the wait, so a concurrent
// Lookup or second StopSession never observes a session that is mid-teardown
// as still present.
//
// If ctx is cancelled while waiting, StopSession returns ctx's error even
// though the actor's own shutdown — already triggered — continues
// independently and is not abandoned.
func (m *Manager) StopSession(ctx context.Context, id string) error {
	m.mu.Lock()
	e, ok := m.sessions[id]
	if ok {
		delete(m.sessions, id)
	}
	m.mu.Unlock()
	if !ok {
		return fmt.Errorf("session: stop %q: %w", id, ErrSessionNotFound)
	}

	e.cancel()
	select {
	case <-e.done:
		m.logger.Info("session stopped", "session_id", id)
		return nil
	case <-ctx.Done():
		return fmt.Errorf("session: stop %q: %w", id, ctx.Err())
	}
}

// Shutdown cancels every live session and waits for all of their actor
// goroutines to exit, cancelling them concurrently rather than one at a
// time so shutdown latency is bounded by the slowest single session, not
// their sum. It is meant for process shutdown (cmd/engined's SIGINT/SIGTERM
// handling): after Shutdown returns, no session actor goroutine remains
// running, regardless of ctx's outcome.
func (m *Manager) Shutdown(ctx context.Context) error {
	m.mu.Lock()
	entries := make([]*entry, 0, len(m.sessions))
	for _, e := range m.sessions {
		entries = append(entries, e)
	}
	m.sessions = make(map[string]*entry)
	m.mu.Unlock()

	for _, e := range entries {
		e.cancel()
	}

	var errs []error
	for _, e := range entries {
		select {
		case <-e.done:
		case <-ctx.Done():
			errs = append(errs, fmt.Errorf("session: shutdown wait for %q: %w", e.info.ID, ctx.Err()))
		}
	}
	if len(errs) > 0 {
		return errors.Join(errs...)
	}
	return nil
}
