package ports

import (
	"context"
	"time"
)

// SessionIngest is the engine's single write-back to the control plane at
// the end of a session. This is a minimal placeholder covering the fields
// needed to identify and locate a finished session; the full payload
// (turn table, ceiling flags, unlock flip, metrics — see
// docs/ENGINE_IMPLEMENTATION_PLAN.md §8.2) is filled in by the ingest-flow
// task once the control-plane endpoint exists.
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
