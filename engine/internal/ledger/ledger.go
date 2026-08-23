// Package ledger owns the per-session claims ledger: what the persona has
// committed to saying, seeded from the contract's precompiled beliefs and
// appended to as the interview runs.
//
// This is the concrete mechanism that makes the speech model and the reasoning
// model one brain rather than two models sharing a socket. Realtime models
// forget the detail of their own audio history, so without a ledger a persona
// asserts one thing at turn 4 and its opposite at turn 19 — which does not
// just sound wrong, it poisons the product's own feedback signal, because the
// report cannot tell whether the interviewer failed to catch a contradiction
// or the contradiction was never really there.
package ledger

import (
	"sort"
	"strings"
	"time"

	"skillbrew/engine/internal/contract"
)

// Stance is how the persona holds a claim.
const (
	StanceAsserted = "asserted"
	StanceDenied   = "denied"
	StanceHedged   = "hedged"
)

// Origin records where a claim came from, so the grader can separate what the
// persona was *designed* to believe from what it said on the day.
const (
	// OriginPrecompiled is a belief fixed at cast time. These exist before
	// the first question, which is what keeps a session reproducible.
	OriginPrecompiled = "precompiled_belief"
	// OriginThinkerNote is a claim the reasoning model proposed.
	OriginThinkerNote = "thinker_note"
	// OriginSpoken is a claim extracted from what the persona actually said.
	OriginSpoken = "spoken_extracted"
)

// Entry is one claim in the ledger.
type Entry struct {
	ClaimID   string    `json:"claim_id"`
	Skill     string    `json:"skill"`
	Statement string    `json:"statement"`
	Stance    string    `json:"stance"`
	Origin    string    `json:"origin"`
	Turn      int       `json:"turn"`
	TS        time.Time `json:"ts"`
	// Supersedes names the claim this one walks back, empty otherwise. A
	// walk-back is the only sanctioned reversal (plan §6 layer 7); anything
	// else that reverses a claim is a contradiction, not a correction.
	Supersedes string `json:"supersedes,omitempty"`
}

// Ledger is the per-session claim store.
//
// **Single writer: the session actor.** Everything else proposes. That is not
// a concurrency shortcut — it is what makes the ledger a coherent account of
// one persona rather than a race between two models writing beliefs.
//
// Not safe for concurrent use, deliberately.
type Ledger struct {
	entries []Entry
	// bySkill indexes into entries for contradiction lookup.
	bySkill map[string][]int
	// nextRuntime numbers runtime claims r1, r2, … Precompiled ones keep
	// the contract's b* ids so a session's beliefs trace back to the cast.
	nextRuntime int
	// superseded marks claims a walk-back has retired, so they stop
	// counting as live commitments without being deleted — the timeline is
	// the point.
	superseded map[string]bool
}

// New returns a ledger seeded from the contract's precompiled beliefs at
// turn 0. The persona's false beliefs exist before the first question.
func New(beliefs []contract.PrecompiledBelief, at time.Time) *Ledger {
	l := &Ledger{
		bySkill:    make(map[string][]int, len(beliefs)),
		superseded: make(map[string]bool),
	}
	for _, b := range beliefs {
		l.appendEntry(Entry{
			ClaimID:   b.ClaimID,
			Skill:     b.Skill,
			Statement: b.Statement,
			Stance:    StanceAsserted,
			Origin:    OriginPrecompiled,
			Turn:      0,
			TS:        at,
		})
	}
	return l
}

func (l *Ledger) appendEntry(e Entry) Entry {
	l.entries = append(l.entries, e)
	l.bySkill[canonicalSkill(e.Skill)] = append(l.bySkill[canonicalSkill(e.Skill)], len(l.entries)-1)
	return e
}

// Append records a claim the persona has made. The statement is stored as
// given — the canonical form is derived for comparison, never substituted for
// what was actually said.
func (l *Ledger) Append(skill, statement, stance, origin string, turn int, at time.Time) Entry {
	l.nextRuntime++
	return l.appendEntry(Entry{
		ClaimID:   runtimeID(l.nextRuntime),
		Skill:     skill,
		Statement: statement,
		Stance:    normalizeStance(stance),
		Origin:    origin,
		Turn:      turn,
		TS:        at,
	})
}

// WalkBack records an in-character retraction of an earlier claim.
//
// This is the only sanctioned reversal. It supersedes rather than deletes: the
// belief timeline is what the grader reads, and a persona that said something
// wrong and then corrected it is a different session from one that never said
// it.
func (l *Ledger) WalkBack(claimID, statement string, turn int, at time.Time) (Entry, bool) {
	prior, ok := l.byID(claimID)
	if !ok {
		return Entry{}, false
	}
	l.nextRuntime++
	l.superseded[claimID] = true
	return l.appendEntry(Entry{
		ClaimID:    runtimeID(l.nextRuntime),
		Skill:      prior.Skill,
		Statement:  statement,
		Stance:     StanceDenied,
		Origin:     OriginSpoken,
		Turn:       turn,
		TS:         at,
		Supersedes: claimID,
	}), true
}

// Contradiction is a live claim that a proposed statement would reverse.
type Contradiction struct {
	Existing Entry
	// Reason names how the conflict was detected, for the event log.
	Reason string
}

// FindContradiction reports whether a proposed claim reverses something the
// persona already committed to on the same skill.
//
// Deterministic and code-owned: it compares canonical forms and negation
// parity. That catches the case this exists for — "Redis is single-threaded"
// at turn 4 against "Redis is not single-threaded" at turn 19 — without a
// model call on the latency path.
//
// It does **not** catch semantic contradiction between differently-worded
// claims. Nothing deterministic does. That is the async Judge's job (plan §6
// layer 6), and pretending otherwise here would be the kind of guarantee this
// codebase refuses to claim.
func (l *Ledger) FindContradiction(skill, statement string) (Contradiction, bool) {
	key, neg := canonicalStatement(statement)
	if key == "" {
		return Contradiction{}, false
	}
	for _, idx := range l.bySkill[canonicalSkill(skill)] {
		e := l.entries[idx]
		if l.superseded[e.ClaimID] {
			continue
		}
		// A hedge commits to nothing, so nothing can reverse it. Checked
		// before the polarity comparison, or "I think Redis is
		// single-threaded" would be treated as a firm claim to contradict.
		if e.Stance == StanceHedged {
			continue
		}
		existingKey, existingNeg := canonicalStatement(e.Statement)
		if existingKey != key {
			continue
		}
		if existingNeg != neg {
			return Contradiction{Existing: e, Reason: "negation_flip"}, true
		}
		if oppositeStance(e.Stance, statement) {
			return Contradiction{Existing: e, Reason: "stance_flip"}, true
		}
	}
	return Contradiction{}, false
}

// Live returns the claims still standing, oldest first.
func (l *Ledger) Live() []Entry {
	out := make([]Entry, 0, len(l.entries))
	for _, e := range l.entries {
		if !l.superseded[e.ClaimID] {
			out = append(out, e)
		}
	}
	return out
}

// All returns every claim including superseded ones, in append order. This is
// the belief timeline the ingest payload carries.
func (l *Ledger) All() []Entry {
	out := make([]Entry, len(l.entries))
	copy(out, l.entries)
	return out
}

// SpeakerSummary renders the compact "things you have already said" system
// item for the speech model.
//
// Newest-first per skill and hard-capped, because this is injected into a
// realtime context where every token competes with the persona's own
// instructions. maxLines <= 0 means the default cap.
func (l *Ledger) SpeakerSummary(maxLines int) string {
	if maxLines <= 0 {
		maxLines = DefaultSpeakerSummaryLines
	}
	bySkill := make(map[string][]Entry)
	skills := make([]string, 0, len(l.bySkill))
	for _, e := range l.Live() {
		k := e.Skill
		if _, seen := bySkill[k]; !seen {
			skills = append(skills, k)
		}
		bySkill[k] = append([]Entry{e}, bySkill[k]...) // newest first
	}
	sort.Strings(skills)

	var b strings.Builder
	b.WriteString("Things you have already said in this interview:\n")
	lines := 0
	for _, skill := range skills {
		for _, e := range bySkill[skill] {
			if lines >= maxLines {
				return b.String()
			}
			b.WriteString("- ")
			b.WriteString(e.Skill)
			b.WriteString(": ")
			b.WriteString(e.Statement)
			b.WriteString("\n")
			lines++
		}
	}
	return b.String()
}

// ThinkerSummary renders the full ledger for the reasoning model, which gets
// everything — it is reasoning over "what has this person committed to", and a
// truncated ledger produces confidently contradictory notes.
func (l *Ledger) ThinkerSummary() string {
	var b strings.Builder
	for _, e := range l.All() {
		b.WriteString(e.ClaimID)
		b.WriteString(" [")
		b.WriteString(e.Skill)
		b.WriteString("] ")
		b.WriteString(e.Statement)
		b.WriteString(" (")
		b.WriteString(e.Stance)
		if e.Supersedes != "" {
			b.WriteString(", supersedes ")
			b.WriteString(e.Supersedes)
		}
		if l.superseded[e.ClaimID] {
			b.WriteString(", WALKED BACK")
		}
		b.WriteString(")\n")
	}
	return b.String()
}

// DefaultSpeakerSummaryLines caps the compact summary injected into the
// realtime context.
const DefaultSpeakerSummaryLines = 15

func (l *Ledger) byID(id string) (Entry, bool) {
	for _, e := range l.entries {
		if e.ClaimID == id {
			return e, true
		}
	}
	return Entry{}, false
}
