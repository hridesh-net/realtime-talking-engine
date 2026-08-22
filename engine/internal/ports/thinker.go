package ports

import (
	"context"
	"time"
)

// PersonaCtx is what the Thinker needs to reason over a persona: the
// standing system prompt plus a compact summary of the claims ledger
// ("what this person has already committed to"). Primitives only, so this
// package never imports internal/contract or internal/ledger.
type PersonaCtx struct {
	SystemPrompt  string
	LedgerSummary string
}

// UnlockAssessment is the Thinker's per-turn judgement of whether
// unlock_condition has been met. The Thinker only assesses; the session
// actor owns the monotonic flip.
type UnlockAssessment struct {
	Met      bool
	Evidence string
}

// Note is the Thinker's structured output for one turn: retrieval and
// elaboration of pre-committed material, never invented content.
type Note struct {
	// Text is injected verbatim as a system item ahead of CreateResponse —
	// a note, never a script.
	Text string
	// ClaimsToMake are candidate claims for this turn, checked against the
	// ledger for contradictions before Text is injected.
	ClaimsToMake []string
	// ClaimsMade are claims extracted from the persona's previous turn
	// transcript, appended to the ledger by the session actor.
	ClaimsMade []string
	// Unlock is nil when unlock_spec.kind == "never" and the runtime
	// short-circuits per-turn assessment.
	Unlock     *UnlockAssessment
	Confidence float64
}

// Thinker is the persona's subconscious: a reasoning model that runs
// speculatively and continuously, retrieving and elaborating pre-committed
// material. It never invents beliefs at runtime.
type Thinker interface {
	// Start begins continuous speculative operation for one session,
	// seeded with the persona and the initial ledger state.
	Start(ctx context.Context, persona PersonaCtx) error
	// FeedPartial streams an in-progress interviewer utterance in as it is
	// transcribed, so the Thinker is never cold at end-of-turn.
	FeedPartial(ctx context.Context, text string) error
	// RequestNote asks for a structured note before deadline. The returned
	// channel delivers at most one Note and is never sent to after
	// deadline; a miss is the caller's responsibility to detect via its own
	// timer.
	RequestNote(ctx context.Context, deadline time.Time) <-chan Note
	// Reset re-seeds the Thinker with the ledger state after a turn closes.
	// It is never a cold call — Reset happens while the Thinker keeps
	// reasoning.
	Reset(ctx context.Context, ledgerSummary string) error
	// Close ends the Thinker's session and releases resources.
	Close(ctx context.Context) error
}
