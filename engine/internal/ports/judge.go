package ports

import "context"

// TurnForReview is one persona turn submitted to the Judge for async,
// post-hoc semantic review against the skill's ceiling and beliefs.
type TurnForReview struct {
	Turn     int
	Question string
	Answer   string
	Skill    string
	Ceiling  int
	Beliefs  []string
}

// Verdict is the Judge's assessment of one submitted turn.
type Verdict struct {
	Turn         int
	Breach       bool
	Severity     string
	Rationale    string
	WalkbackHint string
}

// Judge runs an async, post-hoc semantic review of persona turns against
// their skill ceiling — the guarantee that every persona turn is judged and
// breaches are labelled, even though no pre-speech layer can guarantee
// depth compliance. Implementation: internal/judge (an LLM behind this
// port).
type Judge interface {
	// Submit queues a turn for review. It does not block on the verdict.
	Submit(ctx context.Context, turn TurnForReview) error
	// Verdicts returns the stream of verdicts as they complete, in no
	// guaranteed order relative to Submit calls.
	Verdicts() <-chan Verdict
}
