package ports

import "time"

// Stances a persona can hold a claim in.
const (
	StanceAsserted = "asserted"
	StanceDenied   = "denied"
	StanceHedged   = "hedged"
)

// Where a claim came from. The distinction matters to the grader: a belief the
// persona was *designed* to hold is part of the exercise, while one it produced
// on the day is evidence about the session.
const (
	OriginPrecompiled = "precompiled_belief"
	OriginThinkerNote = "thinker_note"
	OriginSpoken      = "spoken_extracted"
)

// Claim is one entry in the session's claims ledger. Primitives only, so this
// package stays a leaf — internal/ledger owns the behaviour.
type Claim struct {
	ClaimID   string
	Skill     string
	Statement string
	Stance    string
	Origin    string
	Turn      int
	TS        time.Time
	// Supersedes names the claim this one walks back, empty otherwise.
	Supersedes string
}

// ClaimLedger is what the persona has committed to saying this session.
//
// The session actor is the **only** writer; everything else proposes. That is
// not a concurrency convenience — it is what makes the ledger a coherent
// account of one persona rather than a race between two models writing beliefs
// about the same person.
type ClaimLedger interface {
	// Append records a claim the persona has made.
	Append(skill, statement, stance, origin string, turn int, at time.Time) Claim
	// WalkBack records an in-character retraction, superseding rather than
	// deleting: the belief timeline is what the grader reads.
	WalkBack(claimID, statement string, turn int, at time.Time) (Claim, bool)
	// FindContradiction reports whether a proposed statement reverses a live
	// claim on the same skill, and how the conflict was detected.
	FindContradiction(skill, statement string) (Claim, string, bool)
	// SpeakerSummary renders the compact "things you have already said"
	// system item. Capped, because it competes for realtime context.
	SpeakerSummary(maxLines int) string
	// ThinkerSummary renders the full timeline for the reasoning model,
	// which needs all of it — a truncated ledger produces confidently
	// contradictory notes.
	ThinkerSummary() string
	// All returns the whole timeline, superseded claims included.
	All() []Claim
}

// PreGateVerdict is the deterministic pre-gate's classification of one
// interviewer utterance.
type PreGateVerdict struct {
	// Skill the question probes, "" when nothing matched.
	Skill string
	// Defer is true when the probed skill sits at or below its threshold,
	// so the speech model must not answer unaided.
	Defer bool
	// MatchedAlias is the phrase that fired, for the event log. A defer
	// nobody can explain afterwards is a defer nobody can tune.
	MatchedAlias string
}

// PreGate classifies interviewer speech from a partial transcript, without a
// model call. It runs on the latency path: a defer must reach the wire inside
// 50 ms of end-of-turn, which rules out asking anything that thinks.
type PreGate interface {
	Classify(utterance string) PreGateVerdict
}
