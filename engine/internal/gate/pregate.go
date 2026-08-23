// Package gate holds the deterministic pre-gate: the cheap, model-free
// classifier that decides, while the interviewer is still speaking, whether
// the question coming is one this persona can answer unaided.
//
// It runs on partial transcripts because the budget demands it. A defer has to
// put a stall clip on the wire within 50 ms of end-of-turn, and a reasoning
// model cannot be consulted in 50 ms — so the decision is made from the
// question's *first half*, before the interviewer has finished asking it.
package gate

import (
	"strings"

	"skillbrew/engine/internal/contract"
	"skillbrew/engine/internal/ports"
)

// Gate classifies interviewer speech against one persona's contract.
//
// Safe for concurrent use: it holds no per-utterance state. The caller owns
// the accumulating transcript, because the actor already owns the utterance
// and giving the gate its own copy would be two sources of truth for the same
// sentence.
type Gate struct {
	// entries is the lexicon flattened and pre-lowered, longest alias
	// first. Longest-first matters: "system design" must win over "design"
	// so the more specific skill claims the question.
	entries []entry
	// ceilings is the persona's per-skill hard ceiling.
	ceilings map[string]int
}

type entry struct {
	skill string
	alias string
	// deferAtOrBelow is the skill's own threshold from the contract.
	deferAtOrBelow int
}

// New builds a Gate from a compiled contract.
func New(c *contract.EngineContract) *Gate {
	g := &Gate{ceilings: make(map[string]int, len(c.KnowledgeCeiling))}
	for skill, ceiling := range c.KnowledgeCeiling {
		g.ceilings[skill] = ceiling
	}
	for skill, spec := range c.PregateLexicon {
		for _, alias := range spec.Aliases {
			alias = strings.ToLower(strings.TrimSpace(alias))
			if alias == "" {
				continue
			}
			g.entries = append(g.entries, entry{
				skill:          skill,
				alias:          alias,
				deferAtOrBelow: spec.DeferAtOrBelow,
			})
		}
	}
	// Longest alias first, then by skill for a stable order — two aliases
	// of equal length must classify the same way on every run, or a session
	// stops being reproducible for reasons nobody can see.
	sortEntries(g.entries)
	return g
}

var _ ports.PreGate = (*Gate)(nil)

// Classify examines the utterance so far and returns a verdict.
//
// Called on every partial, so it must stay cheap: one lowercase pass and a
// substring scan over a lexicon of a few dozen aliases.
func (g *Gate) Classify(utterance string) ports.PreGateVerdict {
	if len(g.entries) == 0 || utterance == "" {
		return ports.PreGateVerdict{}
	}
	lowered := strings.ToLower(utterance)
	for _, e := range g.entries {
		if !containsPhrase(lowered, e.alias) {
			continue
		}
		ceiling, known := g.ceilings[e.skill]
		if !known {
			// A lexicon entry for a skill with no ceiling is a contract
			// the control plane built inconsistently. Treat it as
			// answerable rather than deferring on every mention: a
			// spurious defer costs a stall clip on every turn.
			return ports.PreGateVerdict{Skill: e.skill, MatchedAlias: e.alias}
		}
		return ports.PreGateVerdict{
			Skill:        e.skill,
			Defer:        ceiling <= e.deferAtOrBelow,
			MatchedAlias: e.alias,
		}
	}
	return ports.PreGateVerdict{}
}

// containsPhrase reports whether haystack contains needle on word boundaries.
//
// Substring matching alone is wrong here: "go" would fire on "going",
// "algorithm" and "ago", and a persona that stalls every time the interviewer
// says "going to" is unusable.
func containsPhrase(haystack, needle string) bool {
	from := 0
	for {
		idx := strings.Index(haystack[from:], needle)
		if idx < 0 {
			return false
		}
		start := from + idx
		end := start + len(needle)
		if boundary(haystack, start-1) && boundary(haystack, end) {
			return true
		}
		from = start + 1
		if from >= len(haystack) {
			return false
		}
	}
}

// boundary reports whether the byte at i is outside a word — either past an
// edge of the string, or not alphanumeric.
func boundary(s string, i int) bool {
	if i < 0 || i >= len(s) {
		return true
	}
	c := s[i]
	switch {
	case c >= 'a' && c <= 'z':
		return false
	case c >= '0' && c <= '9':
		return false
	default:
		return true
	}
}

// sortEntries orders by descending alias length, then skill, then alias, so
// the ordering is total and therefore reproducible.
func sortEntries(es []entry) {
	for i := 1; i < len(es); i++ {
		for j := i; j > 0 && less(es[j], es[j-1]); j-- {
			es[j], es[j-1] = es[j-1], es[j]
		}
	}
}

func less(a, b entry) bool {
	if len(a.alias) != len(b.alias) {
		return len(a.alias) > len(b.alias)
	}
	if a.skill != b.skill {
		return a.skill < b.skill
	}
	return a.alias < b.alias
}
