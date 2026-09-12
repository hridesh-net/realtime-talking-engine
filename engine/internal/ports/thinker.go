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

// HarnessTurn is one bounded, finalized turn from the live conversation.
// Human and persona text are kept together so a Thinker can reason over what
// was actually said on both sides, not only over predicted claims.
type HarnessTurn struct {
	Turn    int
	Human   string
	Persona string
}

// HarnessSnapshot is the canonical, versioned conversation history supplied to
// a Thinker: the finalized turns *before* CurrentTurn, human and persona text
// together. The current turn's question is not in it — that arrives live
// through FeedPartial. Version identifies the finalized history: it changes
// only when a turn finalizes, never on an interim ASR revision, so two
// snapshots with equal Version carry the same history and an implementation
// must treat the second as a no-op rather than restarting its reasoning.
type HarnessSnapshot struct {
	Version     uint64
	CurrentTurn int
	Turns       []HarnessTurn
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
	// SetHarnessSnapshot replaces the bounded canonical conversation history
	// used by the next RequestNote. The actor publishes it when a persona
	// turn closes and again at defer time. Implementations must ignore an
	// older Version (a late revision must never rewind reasoning) and must
	// keep in-flight speculation when the Version is unchanged (the defer
	// republish must not make the Thinker cold at end-of-turn).
	SetHarnessSnapshot(ctx context.Context, snapshot HarnessSnapshot) error
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
