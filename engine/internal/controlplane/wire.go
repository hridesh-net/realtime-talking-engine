package controlplane

import (
	"time"

	"skillbrew/engine/internal/ports"
)

// The wire shape of POST /api/v1/sessions/{id}/ingest, per
// docs/ENGINE_IMPLEMENTATION_PLAN.md §8.2 and the control plane's
// SessionIngest model. Slices are always present (never null) because the
// receiving model declares lists, and a null where a list is expected is a
// 422 the engine would then spool forever.

type wireIngest struct {
	SessionID           string             `json:"session_id"`
	CandidateID         string             `json:"candidate_id"`
	InterviewID         string             `json:"interview_id"`
	ContractFingerprint string             `json:"contract_fingerprint"`
	EngineVersion       string             `json:"engine_version"`
	StartedAt           time.Time          `json:"started_at"`
	EndedAt             time.Time          `json:"ended_at"`
	EndReason           string             `json:"end_reason"`
	S3                  wireObjectKeys     `json:"s3"`
	Turns               []wireTurn         `json:"turns"`
	CeilingFlags        []wireCeilingFlag  `json:"ceiling_flags"`
	UnlockFlip          *wireUnlockFlip    `json:"unlock_flip"`
	SuppressedAnswers   []string           `json:"suppressed_answers"`
	Metrics             map[string]float64 `json:"metrics"`
	Degradations        []string           `json:"degradations"`
}

type wireObjectKeys struct {
	Recording  string `json:"recording"`
	Transcript string `json:"transcript"`
	EventLog   string `json:"event_log"`
}

type wireTurn struct {
	Turn         int    `json:"turn"`
	Speaker      string `json:"speaker"`
	StartMs      int    `json:"start_ms"`
	EndMs        int    `json:"end_ms"`
	Text         string `json:"text"`
	ProbedSkill  string `json:"probed_skill"`
	Deferred     bool   `json:"deferred"`
	FallbackUsed bool   `json:"fallback_used"`
	Trimmed      bool   `json:"trimmed"`
	BargedIn     bool   `json:"barged_in"`
	HeardMs      int    `json:"heard_ms"`
}

type wireCeilingFlag struct {
	Turn         int    `json:"turn"`
	Skill        string `json:"skill"`
	Severity     string `json:"severity"`
	Rationale    string `json:"rationale"`
	WalkbackHint string `json:"walkback_hint"`
}

type wireUnlockFlip struct {
	Turn     int       `json:"turn"`
	Evidence string    `json:"evidence"`
	At       time.Time `json:"at"`
}

func toWire(in ports.SessionIngest) wireIngest {
	out := wireIngest{
		SessionID:           in.SessionID,
		CandidateID:         in.CandidateID,
		InterviewID:         in.InterviewID,
		ContractFingerprint: in.ContractFingerprint,
		EngineVersion:       in.EngineVersion,
		StartedAt:           in.StartedAt.UTC(),
		EndedAt:             in.EndedAt.UTC(),
		EndReason:           in.EndReason,
		S3: wireObjectKeys{
			Recording:  in.S3.Recording,
			Transcript: in.S3.Transcript,
			EventLog:   in.S3.EventLog,
		},
		Turns:             make([]wireTurn, 0, len(in.Turns)),
		CeilingFlags:      make([]wireCeilingFlag, 0, len(in.CeilingFlags)),
		SuppressedAnswers: append([]string{}, in.SuppressedAnswers...),
		Metrics:           map[string]float64{},
		Degradations:      append([]string{}, in.Degradations...),
	}
	for _, t := range in.Turns {
		out.Turns = append(out.Turns, wireTurn{
			Turn: t.Turn, Speaker: t.Speaker, StartMs: t.StartMs, EndMs: t.EndMs, Text: t.Text,
			ProbedSkill: t.ProbedSkill, Deferred: t.Deferred, FallbackUsed: t.FallbackUsed,
			Trimmed: t.Trimmed, BargedIn: t.BargedIn, HeardMs: t.HeardMs,
		})
	}
	for _, f := range in.CeilingFlags {
		out.CeilingFlags = append(out.CeilingFlags, wireCeilingFlag{
			Turn: f.Turn, Skill: f.Skill, Severity: f.Severity, Rationale: f.Rationale, WalkbackHint: f.WalkbackHint,
		})
	}
	if in.UnlockFlip != nil {
		out.UnlockFlip = &wireUnlockFlip{Turn: in.UnlockFlip.Turn, Evidence: in.UnlockFlip.Evidence, At: in.UnlockFlip.At.UTC()}
	}
	for k, v := range in.Metrics {
		out.Metrics[k] = v
	}
	return out
}
