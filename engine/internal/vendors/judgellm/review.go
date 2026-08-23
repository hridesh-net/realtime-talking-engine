package judgellm

import (
	"context"
	"encoding/json"
	"fmt"
	"strconv"
	"strings"

	"skillbrew/engine/internal/ports"
	"skillbrew/engine/internal/vendors/shared/geminijson"
)

// systemPreamble frames the review.
//
// The instruction that matters most is the last one. A judge that flags
// everything is as useless as one that flags nothing: the persona is *supposed*
// to be wrong, vague and out of its depth, and mistaking designed incompetence
// for a breach would fill the report with noise and train managers to ignore
// it.
const systemPreamble = `You review one answer given by a simulated job
candidate during an interview-practice session.

The candidate has a fixed, deliberate skill ceiling. Answering badly, vaguely,
or wrongly is CORRECT behaviour when it sits at or below that ceiling — that is
the exercise. You are looking for the opposite failure: an answer that
demonstrates MORE genuine depth than the ceiling allows.

Judge only depth actually demonstrated. Confident tone, jargon, and long
answers are not depth. A specific, accurate, load-bearing technical detail the
ceiling does not permit is.

Severity:
- "high": the answer would convince a competent interviewer the candidate is
  materially stronger than the ceiling.
- "medium": one detail leaked above the ceiling but the overall level held.
- "low": borderline; a careful listener might notice.

If the answer is within the ceiling — including if it is wrong, vague, or
evasive — breach is false. Say so plainly.`

var verdictSchema = map[string]any{
	"type": "object",
	"properties": map[string]any{
		"breach":   map[string]any{"type": "boolean"},
		"severity": map[string]any{"type": "string", "enum": []string{"low", "medium", "high"}},
		"rationale": map[string]any{
			"type":        "string",
			"description": "One sentence naming the specific detail that exceeded the ceiling.",
		},
		"walkback_hint": map[string]any{
			"type":        "string",
			"description": "What the candidate could say next turn to walk it back, in character.",
		},
	},
	"required": []string{"breach", "rationale"},
}

type rawVerdict struct {
	Breach       bool   `json:"breach"`
	Severity     string `json:"severity"`
	Rationale    string `json:"rationale"`
	WalkbackHint string `json:"walkback_hint"`
}

func (j *Judge) review(ctx context.Context, turn ports.TurnForReview) (ports.Verdict, error) {
	payload, err := j.client.Do(ctx, geminijson.Request{
		ModelID: j.modelID,
		System:  systemPreamble,
		Prompt:  buildPrompt(turn),
		Schema:  verdictSchema,
		// Near-zero: this is a judgement against a fixed rule, and a judge
		// that answers differently on reruns cannot be audited by the
		// manager who disagrees with its verdict.
		Temperature: 0.0,
	})
	if err != nil {
		return ports.Verdict{}, err
	}
	var raw rawVerdict
	if err := json.Unmarshal(payload, &raw); err != nil {
		return ports.Verdict{}, fmt.Errorf("judgellm: decode verdict: %w", err)
	}
	return normalize(turn.Turn, raw), nil
}

// normalize bounds the model's verdict.
func normalize(turn int, raw rawVerdict) ports.Verdict {
	v := ports.Verdict{
		Turn:         turn,
		Breach:       raw.Breach,
		Rationale:    strings.TrimSpace(raw.Rationale),
		WalkbackHint: strings.TrimSpace(raw.WalkbackHint),
	}
	if !raw.Breach {
		// No breach, no severity and nothing to walk back. Leaving either
		// populated would let a downstream reader treat a clean turn as a
		// flagged one.
		v.WalkbackHint = ""
		return v
	}
	switch strings.ToLower(strings.TrimSpace(raw.Severity)) {
	case "high":
		v.Severity = "high"
	case "low":
		v.Severity = "low"
	default:
		// Unrecognised or missing severity on a real breach defaults to
		// medium rather than being dropped: the breach happened either
		// way, and losing it because the label was malformed is worse.
		v.Severity = "medium"
	}
	return v
}

// buildPrompt renders one turn for review.
func buildPrompt(t ports.TurnForReview) string {
	var b strings.Builder
	b.WriteString("SKILL UNDER REVIEW: ")
	b.WriteString(t.Skill)
	b.WriteString("\nCEILING: ")
	b.WriteString(strconv.Itoa(t.Ceiling))
	b.WriteString("/10 — the candidate may not demonstrate more than this.\n")
	if len(t.Beliefs) > 0 {
		b.WriteString("\nTHINGS THIS CANDIDATE SINCERELY BELIEVES (being wrong here is correct):\n")
		for _, belief := range t.Beliefs {
			b.WriteString("- ")
			b.WriteString(belief)
			b.WriteString("\n")
		}
	}
	b.WriteString("\nINTERVIEWER ASKED:\n")
	b.WriteString(t.Question)
	b.WriteString("\n\nCANDIDATE ANSWERED:\n")
	b.WriteString(t.Answer)
	b.WriteString("\n\nDid the answer demonstrate more genuine depth than the ceiling allows?")
	return b.String()
}
