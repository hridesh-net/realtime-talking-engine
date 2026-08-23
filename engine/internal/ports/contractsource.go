package ports

import (
	"context"
	"time"
)

// TurnIngest is one turn of the interview as the engine observed it, the
// per-turn slice of the ingest payload — see
// docs/ENGINE_IMPLEMENTATION_PLAN.md §8.2. It mirrors
// internal/session.TurnRecord's fields as primitives; this package must not
// import internal/session.
type TurnIngest struct {
	Turn        int
	Speaker     string
	StartMs     int
	EndMs       int
	Text        string
	ProbedSkill string
	Deferred    bool
	// FallbackUsed marks a turn where the Thinker missed its deadline and
	// the contract's own fallback directive stood in. The grader discounts
	// depth claims on such a turn.
	FallbackUsed bool
	// Trimmed marks a response cut short by the sentence-bound enforcer.
	Trimmed bool
	// BargedIn marks a persona turn the interviewer interrupted.
	BargedIn bool
	// HeardMs is how much of a barged-in persona turn was actually heard.
	HeardMs int
}

// CeilingFlag records one turn where the persona's answer approached or
// breached a skill's knowledge ceiling, as judged post-hoc by the Judge
// port.
type CeilingFlag struct {
	Turn      int
	Skill     string
	Severity  string
	Rationale string
	// WalkbackHint is the Judge's suggestion for how the persona should
	// walk the claim back on its next turn, empty when no walkback is
	// warranted.
	WalkbackHint string
}

// UnlockFlip records the single monotonic instant unlock_condition was
// judged met (plan §7: the Thinker assesses, the actor decides, and depth
// once earned is never taken back). Nil in SessionIngest when the session
// never unlocked.
type UnlockFlip struct {
	Turn     int
	Evidence string
	At       time.Time
}

// ObjectKeys are the bundle's object keys in durable storage (see
// ports.Store), included in SessionIngest so the control plane can locate
// every part of the bundle without a separate lookup call.
type ObjectKeys struct {
	// Recording is the muxed dual-channel recording's object key.
	Recording string
	// Transcript is the turn-table transcript's object key.
	Transcript string
	// EventLog is the session's raw event log's object key.
	EventLog string
}

// SessionIngest is the engine's single write-back to the control plane at
// the end of a session — the full payload of
// docs/ENGINE_IMPLEMENTATION_PLAN.md §8.2. A call reporting it is idempotent
// on SessionID: the engine may retry NotifyIngest, and the control plane
// must treat a repeated SessionID as the same session, not a new one.
type SessionIngest struct {
	SessionID           string
	CandidateID         string
	InterviewID         string
	ContractFingerprint string
	EngineVersion       string
	StartedAt           time.Time
	EndedAt             time.Time
	// EndReason is one of: interviewer_ended, abandoned, cost_cap, error.
	EndReason string
	// Turns is the session's full turn table.
	Turns []TurnIngest
	// CeilingFlags is every post-hoc breach or near-breach the Judge
	// raised against a skill's knowledge ceiling.
	CeilingFlags []CeilingFlag
	// UnlockFlip is set once the session's unlock_condition was judged
	// met, nil otherwise.
	UnlockFlip *UnlockFlip
	// SuppressedAnswers names the skills a defer suppressed depth on
	// without the session ever unlocking — what the interviewer probed for
	// but the persona was never allowed to give.
	SuppressedAnswers []string
	// Metrics is freeform numeric telemetry for the session (latency
	// percentiles, defer rate, and similar), keyed by metric name.
	Metrics map[string]float64
	// Degradations lists every best-effort layer that fell back this
	// session (e.g. "thinker_deadline_missed", "truncate_unsupported",
	// "recording_degraded"), for the report to disclose rather than hide.
	Degradations []string
	// S3 is where the rest of the bundle landed in durable storage.
	S3 ObjectKeys
}

// ContractSource fetches a candidate's engine contract and reports a
// finished session's outcome back to the control plane. Implementation:
// internal/controlplane, an HTTP client.
type ContractSource interface {
	// FetchContract retrieves the raw engine-contract JSON for a candidate.
	// The caller (internal/session, via internal/contract) is responsible
	// for parsing and validating it.
	FetchContract(ctx context.Context, candidateID string) ([]byte, error)
	// NotifyIngest reports a finished session. It is idempotent on
	// ingest.SessionID — the engine may retry.
	NotifyIngest(ctx context.Context, ingest SessionIngest) error
}
