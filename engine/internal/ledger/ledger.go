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
	"skillbrew/engine/internal/ports"
)

// DefaultSpeakerSummaryLines caps the compact summary injected into the
// realtime context.
const DefaultSpeakerSummaryLines = 15

// Ledger is the per-session claim store, implementing ports.ClaimLedger.
//
// **Single writer: the session actor.** Everything else proposes. Not safe for
// concurrent use, deliberately.
type Ledger struct {
	entries []ports.Claim
	// bySkill indexes into entries for contradiction lookup.
	bySkill map[string][]int
	// nextRuntime numbers runtime claims r1, r2, … Precompiled ones keep
	// the contract's b* ids, so a glance at an id says whether the persona
	// was designed to believe this or said it on the day.
	nextRuntime int
	// superseded marks claims a walk-back has retired: they stop counting
	// as live commitments without leaving the timeline.
	superseded map[string]bool
}

var _ ports.ClaimLedger = (*Ledger)(nil)

// New returns a ledger seeded from the contract's precompiled beliefs at
// turn 0. The persona's false beliefs exist before the first question.
func New(beliefs []contract.PrecompiledBelief, at time.Time) *Ledger {
	l := &Ledger{
		bySkill:    make(map[string][]int, len(beliefs)),
		superseded: make(map[string]bool),
	}
	for _, b := range beliefs {
		l.appendEntry(ports.Claim{
			ClaimID:   b.ClaimID,
			Skill:     b.Skill,
			Statement: b.Statement,
			Stance:    ports.StanceAsserted,
			Origin:    ports.OriginPrecompiled,
			Turn:      0,
			TS:        at,
		})
	}
	return l
}

func (l *Ledger) appendEntry(e ports.Claim) ports.Claim {
	l.entries = append(l.entries, e)
	key := canonicalSkill(e.Skill)
	l.bySkill[key] = append(l.bySkill[key], len(l.entries)-1)
	return e
}

// Append records a claim the persona has made. The statement is stored as
// given — the canonical form is derived for comparison, never substituted for
// what was actually said.
func (l *Ledger) Append(skill, statement, stance, origin string, turn int, at time.Time) ports.Claim {
	l.nextRuntime++
	return l.appendEntry(ports.Claim{
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
// The only sanctioned reversal. It supersedes rather than deletes: a persona
// that said something wrong and corrected it is a different session from one
// that never said it, and the report is about the interviewer either way.
func (l *Ledger) WalkBack(claimID, statement string, turn int, at time.Time) (ports.Claim, bool) {
	prior, ok := l.byID(claimID)
	if !ok {
		return ports.Claim{}, false
	}
	l.nextRuntime++
	l.superseded[claimID] = true
	return l.appendEntry(ports.Claim{
		ClaimID:    runtimeID(l.nextRuntime),
		Skill:      prior.Skill,
		Statement:  statement,
		Stance:     ports.StanceDenied,
		Origin:     ports.OriginSpoken,
		Turn:       turn,
		TS:         at,
		Supersedes: claimID,
	}), true
}

// FindContradiction reports whether a proposed claim reverses something the
// persona already committed to on the same skill, and how it was detected.
//
// Deterministic and code-owned: it compares canonical forms and negation
// parity, catching the case it exists for — "Redis is single-threaded" at turn
// 4 against "Redis is not single-threaded" at turn 19 — with no model call on
// the latency path.
//
// It does **not** catch semantic contradiction between differently-worded
// claims. Nothing deterministic does. That is the async Judge's job (plan §6
// layer 6), and pretending otherwise here would be the kind of guarantee this
// codebase refuses to claim.
func (l *Ledger) FindContradiction(skill, statement string) (ports.Claim, string, bool) {
	key, neg := canonicalStatement(statement)
	if key == "" {
		return ports.Claim{}, "", false
	}
	for _, idx := range l.bySkill[canonicalSkill(skill)] {
		e := l.entries[idx]
		if l.superseded[e.ClaimID] {
			continue
		}
		// A hedge commits to nothing, so nothing can reverse it. Checked
		// before the polarity comparison, or "I think Redis is
		// single-threaded" would be treated as a firm claim to contradict.
		if e.Stance == ports.StanceHedged {
			continue
		}
		existingKey, existingNeg := canonicalStatement(e.Statement)
		if existingKey != key {
			continue
		}
		if existingNeg != neg {
			return e, "negation_flip", true
		}
		if oppositeStance(e.Stance, statement) {
			return e, "stance_flip", true
		}
	}
	return ports.Claim{}, "", false
}

// Live returns the claims still standing, oldest first.
func (l *Ledger) Live() []ports.Claim {
	out := make([]ports.Claim, 0, len(l.entries))
	for _, e := range l.entries {
		if !l.superseded[e.ClaimID] {
			out = append(out, e)
		}
	}
	return out
}

// All returns every claim including superseded ones, in append order. This is
// the belief timeline the ingest payload carries.
func (l *Ledger) All() []ports.Claim {
	out := make([]ports.Claim, len(l.entries))
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
	bySkill := make(map[string][]ports.Claim)
	skills := make([]string, 0, len(l.bySkill))
	for _, e := range l.Live() {
		if _, seen := bySkill[e.Skill]; !seen {
			skills = append(skills, e.Skill)
		}
		bySkill[e.Skill] = append([]ports.Claim{e}, bySkill[e.Skill]...) // newest first
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

func (l *Ledger) byID(id string) (ports.Claim, bool) {
	for _, e := range l.entries {
		if e.ClaimID == id {
			return e, true
		}
	}
	return ports.Claim{}, false
}
