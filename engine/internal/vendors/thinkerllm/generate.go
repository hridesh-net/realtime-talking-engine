package thinkerllm

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"

	"skillbrew/engine/internal/ports"
	"skillbrew/engine/internal/vendors/shared/geminijson"
)

// systemPreamble frames the reasoning model's job.
//
// The two prohibitions carry the weight. "Retrieve, do not invent" is what
// keeps a session reproducible — a belief improvised at runtime would make two
// sessions on the same contract disagree, which is exactly what
// seed_fingerprint promises cannot happen. "A note, not a script" is what
// keeps the seam hidden: the speech model phrases everything, so the stall
// clip and the answer are the same voice in the same register.
const systemPreamble = `You are the private, inner reasoning of a job candidate
being interviewed. You do not speak. You write a short note to yourself that
another system will use to shape what the candidate says next.

Hard rules:
- Retrieve and elaborate ONLY what the persona brief below already establishes.
  Never invent a new belief, employer, project or number.
- Write a note, never a script. Say what to convey and how vague to be, not the
  sentences to say.
- If the persona cannot really answer, say so and prescribe vagueness
  explicitly. Vague is a correct answer here, not a failure.
- Never break character and never mention this note.`

// noteSchema is the structured output contract. Asking for JSON in prose and
// parsing whatever comes back is how you get a note that half-parses at 2am;
// the vendor enforces this shape instead.
var noteSchema = map[string]any{
	"type": "object",
	"properties": map[string]any{
		"note": map[string]any{
			"type":        "string",
			"description": "2-3 sentences of guidance for the candidate's next answer.",
		},
		"claims_to_make": map[string]any{
			"type":  "array",
			"items": map[string]any{"type": "string"},
		},
		"claims_made": map[string]any{
			"type":  "array",
			"items": map[string]any{"type": "string"},
		},
		"unlock_met":      map[string]any{"type": "boolean"},
		"unlock_evidence": map[string]any{"type": "string"},
		"confidence":      map[string]any{"type": "number"},
	},
	"required": []string{"note", "claims_to_make", "claims_made", "confidence"},
}

// rawNote is the model's JSON, before it becomes a ports.Note.
type rawNote struct {
	Note           string   `json:"note"`
	ClaimsToMake   []string `json:"claims_to_make"`
	ClaimsMade     []string `json:"claims_made"`
	UnlockMet      bool     `json:"unlock_met"`
	UnlockEvidence string   `json:"unlock_evidence"`
	Confidence     float64  `json:"confidence"`
}

// generate runs one reasoning call and normalizes the result.
func (t *Thinker) generate(
	ctx context.Context, persona ports.PersonaCtx, question string,
) (ports.Note, error) {
	payload, err := t.client().Do(ctx, geminijson.Request{
		ModelID: t.modelID,
		System:  systemPreamble,
		Prompt:  buildPrompt(persona, question),
		Schema:  noteSchema,
		// Low, deliberately. This layer retrieves committed material;
		// creativity here is indistinguishable from invention, and an
		// invented belief voids the persona's seed_fingerprint.
		Temperature: 0.2,
	})
	if err != nil {
		return ports.Note{}, err
	}
	var raw rawNote
	if err := json.Unmarshal(payload, &raw); err != nil {
		return ports.Note{}, fmt.Errorf("thinkerllm: decode note: %w", err)
	}
	return normalize(raw), nil
}

// normalize turns the model's JSON into a Note, bounding everything the actor
// will act on. A model that returns forty claims is not more useful than one
// that returns three; it is just a bigger injection into a realtime context.
func normalize(raw rawNote) ports.Note {
	n := ports.Note{
		Text:         strings.TrimSpace(raw.Note),
		ClaimsToMake: cleanList(raw.ClaimsToMake, 4),
		ClaimsMade:   cleanList(raw.ClaimsMade, 4),
		Confidence:   clamp01(raw.Confidence),
	}
	// Only report an assessment when the model actually made one. The actor
	// treats a nil Unlock as "no opinion", which is different from "not
	// met" — and only one of those should ever be inferred from silence.
	if raw.UnlockMet || raw.UnlockEvidence != "" {
		n.Unlock = &ports.UnlockAssessment{
			Met:      raw.UnlockMet,
			Evidence: strings.TrimSpace(raw.UnlockEvidence),
		}
	}
	return n
}

func cleanList(in []string, limit int) []string {
	out := make([]string, 0, len(in))
	for _, s := range in {
		if s = strings.TrimSpace(s); s != "" {
			out = append(out, s)
		}
		if len(out) == limit {
			break
		}
	}
	return out
}

func clamp01(f float64) float64 {
	switch {
	case f < 0:
		return 0
	case f > 1:
		return 1
	default:
		return f
	}
}

// buildPrompt assembles the turn's reasoning input.
func buildPrompt(persona ports.PersonaCtx, question string) string {
	var b strings.Builder
	b.WriteString("=== WHO YOU ARE (the persona brief) ===\n")
	b.WriteString(persona.SystemPrompt)
	b.WriteString("\n\n=== WHAT YOU HAVE ALREADY COMMITTED TO THIS INTERVIEW ===\n")
	if strings.TrimSpace(persona.LedgerSummary) == "" {
		b.WriteString("(nothing yet — this is early in the interview)\n")
	} else {
		b.WriteString(persona.LedgerSummary)
	}
	b.WriteString("\n=== WHAT THE INTERVIEWER IS ASKING (may be mid-sentence) ===\n")
	b.WriteString(question)
	b.WriteString("\n\nWrite the note.")
	return b.String()
}
