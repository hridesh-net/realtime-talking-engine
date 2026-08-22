package contract

import (
	"encoding/json"
	"fmt"
	"strconv"
	"strings"
)

// supportedMajorVersion is the only contract_version major version this
// engine build implements. Bump alongside the v1.1 fields of plan §8.1 when
// that task lands — never silently widen acceptance.
const supportedMajorVersion = 1

// VoiceDirectives are the audio-layer settings from the contract's
// voice_directives object (docs/GO_ENGINE_CONTRACT.md).
type VoiceDirectives struct {
	Pace                      string   `json:"pace"`
	TargetPauseBeforeAnswerMs int      `json:"target_pause_before_answer_ms"`
	Verbosity                 string   `json:"verbosity"`
	FillerFrequency           int      `json:"filler_frequency"`
	HesitationFrequency       int      `json:"hesitation_frequency"`
	Formality                 string   `json:"formality"`
	MayInterrupt              bool     `json:"may_interrupt"`
	Tone                      string   `json:"tone"`
	VerbalTics                []string `json:"verbal_tics"`
	SamplePhrases             []string `json:"sample_phrases"`
	SelfCorrectionRate        float64  `json:"self_correction_rate"`
}

// TurnPolicy are the turn-taking limits from the contract's turn_policy
// object (docs/GO_ENGINE_CONTRACT.md). TargetSentencesPerAnswer always sits
// inside [MinSentences, MaxSentences]; Validate enforces that invariant.
type TurnPolicy struct {
	DefaultAnswerDepth       string `json:"default_answer_depth"`
	TargetSentencesPerAnswer int    `json:"target_sentences_per_answer"`
	MinSentences             int    `json:"min_sentences"`
	MaxSentences             int    `json:"max_sentences"`
	OnUnknownQuestion        string `json:"on_unknown_question"`
	OnPressure               string `json:"on_pressure"`
	OnSilence                string `json:"on_silence"`
	BargeInAllowed           bool   `json:"barge_in_allowed"`
}

// EngineContract is the Go mirror of the schema at
// owner_handover/engine_contract_schema.json, v1.0 fields only. The v1.1
// fields described in plan §8.1 (precompiled_beliefs, stall_phrases,
// pregate_lexicon, unlock_spec, tts_voice_id) are added in a later task.
type EngineContract struct {
	ContractVersion    string          `json:"contract_version"`
	CandidateID        string          `json:"candidate_id"`
	InterviewID        string          `json:"interview_id"`
	SystemPrompt       string          `json:"system_prompt"`
	OpeningLine        string          `json:"opening_line"`
	VoiceDirectives    VoiceDirectives `json:"voice_directives"`
	TurnPolicy         TurnPolicy      `json:"turn_policy"`
	KnowledgeCeiling   map[string]int  `json:"knowledge_ceiling"`
	UnlockCondition    string          `json:"unlock_condition"`
	ForbiddenBehaviors []string        `json:"forbidden_behaviors"`

	// minorVersion is parsed from ContractVersion by Parse. Unexported and
	// untagged so it never round-trips into JSON; read it via MinorVersion.
	minorVersion int
}

// Parse decodes raw engine-contract JSON, pins it to the major version this
// engine build implements, and validates it. Reject rather than run a
// persona the engine cannot honour.
func Parse(data []byte) (*EngineContract, error) {
	var c EngineContract
	if err := json.Unmarshal(data, &c); err != nil {
		// Wraps ErrInvalidContract as well as the decode cause: every Parse
		// failure — malformed JSON, bad version, failed validation — is a
		// rejected contract, and callers classify it with a single
		// errors.Is(err, ErrInvalidContract) rather than three checks.
		return nil, fmt.Errorf("contract: decode: %w: %w", ErrInvalidContract, err)
	}

	minor, err := checkVersion(c.ContractVersion)
	if err != nil {
		return nil, err
	}
	c.minorVersion = minor

	if err := c.Validate(); err != nil {
		return nil, err
	}

	return &c, nil
}

// MinorVersion is the minor component of contract_version.
//
// The major version is pinned; the minor is retained because minor bumps are
// additive and are therefore accepted, which means a newer contract can arrive
// at an older engine and have its new fields silently dropped by the decoder.
// Features gated on later minors must call RequireMinor rather than assume the
// fields are populated — a v1.1 contract running on a v1.0 code path would fall
// back to runtime-invented persona beliefs, the exact non-determinism v1.1
// exists to remove, with nothing in the logs to say so.
func (c *EngineContract) MinorVersion() int { return c.minorVersion }

// RequireMinor reports an error unless the contract's minor version is at
// least min. Callers gate minor-versioned features on this so a version skew
// fails loudly instead of degrading in silence.
func (c *EngineContract) RequireMinor(min int) error {
	if c.minorVersion < min {
		return &ValidationError{
			Field: "contract_version",
			Reason: fmt.Sprintf(
				"contract is v%d.%d but this feature requires at least v%d.%d",
				supportedMajorVersion, c.minorVersion, supportedMajorVersion, min,
			),
		}
	}
	return nil
}

// checkVersion parses a contract_version string such as "v1.0" or "1.0",
// rejects anything but supportedMajorVersion, and returns the minor.
func checkVersion(version string) (int, error) {
	major, minor, err := parseVersion(version)
	if err != nil || major != supportedMajorVersion {
		return 0, &UnsupportedVersionError{Version: version, SupportedMajor: supportedMajorVersion}
	}
	return minor, nil
}

// parseVersion splits a "[v]MAJOR.MINOR" version string. A missing minor
// reads as 0; a non-numeric minor is an error rather than a silent zero,
// since version strings gate feature availability.
func parseVersion(version string) (major, minor int, err error) {
	trimmed := strings.TrimPrefix(strings.TrimSpace(version), "v")
	majorStr, minorStr, hasMinor := strings.Cut(trimmed, ".")

	major, err = strconv.Atoi(majorStr)
	if err != nil {
		return 0, 0, fmt.Errorf("contract: malformed contract_version %q: %w", version, err)
	}
	if !hasMinor {
		return major, 0, nil
	}
	minor, err = strconv.Atoi(minorStr)
	if err != nil {
		return 0, 0, fmt.Errorf("contract: malformed contract_version %q: %w", version, err)
	}
	return major, minor, nil
}

// Validate checks required fields and the contract's own stated invariants
// where cheap to check. It does not attempt full JSON-schema validation.
func (c *EngineContract) Validate() error {
	for _, req := range []struct {
		field string
		value string
	}{
		{"candidate_id", c.CandidateID},
		{"interview_id", c.InterviewID},
		{"system_prompt", c.SystemPrompt},
		{"opening_line", c.OpeningLine},
		{"unlock_condition", c.UnlockCondition},
	} {
		if req.value == "" {
			return &ValidationError{Field: req.field, Reason: "required field is empty"}
		}
	}

	if len(c.KnowledgeCeiling) == 0 {
		return &ValidationError{Field: "knowledge_ceiling", Reason: "required field is empty"}
	}
	if len(c.ForbiddenBehaviors) == 0 {
		return &ValidationError{Field: "forbidden_behaviors", Reason: "required field is empty"}
	}

	return c.TurnPolicy.Validate()
}

// Validate enforces turn_policy's own stated invariant: target_sentences_per_answer
// always sits inside [min_sentences, max_sentences] (docs/GO_ENGINE_CONTRACT.md).
func (p *TurnPolicy) Validate() error {
	if p.MinSentences > p.MaxSentences {
		return &ValidationError{
			Field:  "turn_policy.min_sentences",
			Reason: "min_sentences is greater than max_sentences",
		}
	}
	if p.TargetSentencesPerAnswer < p.MinSentences || p.TargetSentencesPerAnswer > p.MaxSentences {
		return &ValidationError{
			Field:  "turn_policy.target_sentences_per_answer",
			Reason: "target_sentences_per_answer must lie within [min_sentences, max_sentences]",
		}
	}
	return nil
}
