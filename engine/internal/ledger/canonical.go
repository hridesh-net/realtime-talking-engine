package ledger

import (
	"strconv"
	"strings"

	"skillbrew/engine/internal/ports"
)

// runtimeID numbers a runtime-observed claim. Precompiled beliefs keep their
// contract-assigned b* ids; runtime ones are r*, so a glance at an id says
// whether the persona was designed to believe this or said it on the day.
func runtimeID(n int) string { return "r" + strconv.Itoa(n) }

func normalizeStance(s string) string {
	switch strings.ToLower(strings.TrimSpace(s)) {
	case ports.StanceDenied:
		return ports.StanceDenied
	case ports.StanceHedged:
		return ports.StanceHedged
	default:
		return ports.StanceAsserted
	}
}

// canonicalSkill normalizes a skill name for indexing. Skills come from the
// job spec on one side and a model on the other, so "System Design" and
// "system design" must land in the same bucket.
func canonicalSkill(s string) string {
	return strings.Join(strings.Fields(strings.ToLower(s)), " ")
}

// negationTokens are the words whose presence flips a claim's polarity. Kept
// small on purpose: every entry is a word that reverses meaning on its own,
// so the parity check stays predictable rather than clever.
var negationTokens = map[string]bool{
	"not": true, "never": true, "no": true, "cannot": true,
	"isn't": true, "aren't": true, "doesn't": true, "don't": true,
	"wasn't": true, "won't": true, "can't": true,
}

// doSupport are auxiliaries English inserts purely to carry negation:
// "fixes" becomes "does not fix". They add no meaning to a declarative claim,
// and leaving them in the key means the negated and positive forms never
// match — which is the one comparison this whole function exists to make.
var doSupport = map[string]bool{"do": true, "does": true, "did": true}

// canonicalStatement reduces a claim to a comparable form and reports whether
// it is negated.
//
// The negation tokens are *removed* from the key, so "Redis is single-threaded"
// and "Redis is not single-threaded" share a key and differ only in parity —
// which is precisely the contradiction worth catching deterministically.
func canonicalStatement(s string) (key string, negated bool) {
	fields := strings.Fields(strings.ToLower(s))
	kept := make([]string, 0, len(fields))
	for _, f := range fields {
		f = strings.Trim(f, ".,;:!?\"'()")
		if f == "" {
			continue
		}
		if negationTokens[f] {
			negated = !negated
			continue
		}
		if doSupport[f] {
			continue
		}
		// English inflects the verb when it negates: "fixes" becomes "does
		// not fix". Dropping the negation token alone therefore leaves two
		// keys that differ only by an "s", and the contradiction slips
		// through. Stemming a trailing "s"/"es" is crude — it also folds
		// "process" to "proces" — but it is applied identically to both
		// sides, so equality comparison is unaffected and the inflection
		// case is caught.
		kept = append(kept, stem(f))
	}
	return strings.Join(kept, " "), negated
}

// stem removes a trailing plural/third-person "s" so that a verb inflected by
// negation still matches its positive form.
func stem(w string) string {
	switch {
	case strings.HasSuffix(w, "ies") && len(w) > 4:
		return w[:len(w)-3] + "y"
	case strings.HasSuffix(w, "es") && len(w) > 3:
		return w[:len(w)-2]
	case strings.HasSuffix(w, "s") && !strings.HasSuffix(w, "ss") && len(w) > 2:
		return w[:len(w)-1]
	default:
		return w
	}
}

// oppositeStance reports whether an existing stance conflicts with a proposed
// statement's own polarity.
func oppositeStance(existing, proposed string) bool {
	_, negated := canonicalStatement(proposed)
	switch existing {
	case ports.StanceAsserted:
		return negated
	case ports.StanceDenied:
		return !negated
	default:
		// A hedge commits to nothing, so nothing contradicts it.
		return false
	}
}
