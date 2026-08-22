package contract_test

import (
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"testing"

	"skillbrew/engine/internal/contract"
)

func sampleBytes(t *testing.T) []byte {
	t.Helper()
	data, err := os.ReadFile(filepath.Join("testdata", "engine_contract_sample.json"))
	if err != nil {
		t.Fatalf("read sample: %v", err)
	}
	return data
}

func TestParse_SampleRoundTrips(t *testing.T) {
	data := sampleBytes(t)

	c, err := contract.Parse(data)
	if err != nil {
		t.Fatalf("Parse(sample) returned error: %v", err)
	}

	if c.ContractVersion != "v1.0" {
		t.Errorf("ContractVersion = %q, want v1.0", c.ContractVersion)
	}
	if c.CandidateID != "vc-0c4aff82e1cb" {
		t.Errorf("CandidateID = %q, want vc-0c4aff82e1cb", c.CandidateID)
	}
	if c.TurnPolicy.TargetSentencesPerAnswer != 3 {
		t.Errorf("TurnPolicy.TargetSentencesPerAnswer = %d, want 3", c.TurnPolicy.TargetSentencesPerAnswer)
	}
	if c.KnowledgeCeiling["Go"] != 3 {
		t.Errorf("KnowledgeCeiling[Go] = %d, want 3", c.KnowledgeCeiling["Go"])
	}
	if len(c.ForbiddenBehaviors) == 0 {
		t.Error("ForbiddenBehaviors is empty, want non-empty")
	}
	if c.VoiceDirectives.TargetPauseBeforeAnswerMs != 700 {
		t.Errorf("VoiceDirectives.TargetPauseBeforeAnswerMs = %d, want 700", c.VoiceDirectives.TargetPauseBeforeAnswerMs)
	}

	// Round-trip: marshal back out and re-parse; the second parse must
	// produce an identical struct, proving no data was lost going through
	// our types.
	remarshaled, err := json.Marshal(c)
	if err != nil {
		t.Fatalf("Marshal(parsed): %v", err)
	}

	c2, err := contract.Parse(remarshaled)
	if err != nil {
		t.Fatalf("Parse(remarshaled) returned error: %v", err)
	}

	orig, err := json.Marshal(c)
	if err != nil {
		t.Fatalf("Marshal(c): %v", err)
	}
	again, err := json.Marshal(c2)
	if err != nil {
		t.Fatalf("Marshal(c2): %v", err)
	}
	if string(orig) != string(again) {
		t.Errorf("round-trip mismatch:\nfirst:  %s\nsecond: %s", orig, again)
	}
}

func TestParse_RejectsUnsupportedMajorVersion(t *testing.T) {
	var doc map[string]any
	if err := json.Unmarshal(sampleBytes(t), &doc); err != nil {
		t.Fatalf("unmarshal sample into map: %v", err)
	}

	tests := []struct {
		name    string
		version string
	}{
		{"next major", "v2.0"},
		{"future major", "v3.1"},
		{"unversioned major zero", "v0.9"},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			doc["contract_version"] = tt.version
			data, err := json.Marshal(doc)
			if err != nil {
				t.Fatalf("marshal fabricated payload: %v", err)
			}

			_, err = contract.Parse(data)
			if err == nil {
				t.Fatalf("Parse(%s) succeeded, want an UnsupportedVersionError", tt.version)
			}

			var verErr *contract.UnsupportedVersionError
			if !errors.As(err, &verErr) {
				t.Fatalf("Parse(%s) error = %v, want *UnsupportedVersionError", tt.version, err)
			}
			if verErr.Version != tt.version {
				t.Errorf("UnsupportedVersionError.Version = %q, want %q", verErr.Version, tt.version)
			}
			if !errors.Is(err, contract.ErrUnsupportedVersion) {
				t.Errorf("errors.Is(err, ErrUnsupportedVersion) = false, want true")
			}
		})
	}
}

func TestParse_MalformedVersionRejected(t *testing.T) {
	var doc map[string]any
	if err := json.Unmarshal(sampleBytes(t), &doc); err != nil {
		t.Fatalf("unmarshal sample into map: %v", err)
	}
	doc["contract_version"] = "not-a-version"
	data, err := json.Marshal(doc)
	if err != nil {
		t.Fatalf("marshal fabricated payload: %v", err)
	}

	_, err = contract.Parse(data)
	if err == nil {
		t.Fatal("Parse(malformed version) succeeded, want an error")
	}
	if !errors.Is(err, contract.ErrUnsupportedVersion) {
		t.Errorf("errors.Is(err, ErrUnsupportedVersion) = false, want true; got %v", err)
	}
}

func TestEngineContract_Validate(t *testing.T) {
	valid := func() contract.EngineContract {
		var c contract.EngineContract
		if err := json.Unmarshal(sampleBytes(t), &c); err != nil {
			t.Fatalf("unmarshal sample: %v", err)
		}
		return c
	}

	tests := []struct {
		name    string
		mutate  func(c *contract.EngineContract)
		wantErr bool
	}{
		{
			name:    "valid sample passes",
			mutate:  func(c *contract.EngineContract) {},
			wantErr: false,
		},
		{
			name:    "empty candidate_id rejected",
			mutate:  func(c *contract.EngineContract) { c.CandidateID = "" },
			wantErr: true,
		},
		{
			name:    "empty unlock_condition rejected",
			mutate:  func(c *contract.EngineContract) { c.UnlockCondition = "" },
			wantErr: true,
		},
		{
			name:    "empty knowledge_ceiling rejected",
			mutate:  func(c *contract.EngineContract) { c.KnowledgeCeiling = nil },
			wantErr: true,
		},
		{
			name:    "empty forbidden_behaviors rejected",
			mutate:  func(c *contract.EngineContract) { c.ForbiddenBehaviors = nil },
			wantErr: true,
		},
		{
			name: "target_sentences_per_answer below min rejected",
			mutate: func(c *contract.EngineContract) {
				c.TurnPolicy.MinSentences = 3
				c.TurnPolicy.MaxSentences = 6
				c.TurnPolicy.TargetSentencesPerAnswer = 2
			},
			wantErr: true,
		},
		{
			name: "target_sentences_per_answer above max rejected",
			mutate: func(c *contract.EngineContract) {
				c.TurnPolicy.MinSentences = 3
				c.TurnPolicy.MaxSentences = 6
				c.TurnPolicy.TargetSentencesPerAnswer = 7
			},
			wantErr: true,
		},
		{
			name: "target_sentences_per_answer at bounds accepted",
			mutate: func(c *contract.EngineContract) {
				c.TurnPolicy.MinSentences = 3
				c.TurnPolicy.MaxSentences = 6
				c.TurnPolicy.TargetSentencesPerAnswer = 6
			},
			wantErr: false,
		},
		{
			name: "min greater than max rejected",
			mutate: func(c *contract.EngineContract) {
				c.TurnPolicy.MinSentences = 6
				c.TurnPolicy.MaxSentences = 3
				c.TurnPolicy.TargetSentencesPerAnswer = 4
			},
			wantErr: true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			c := valid()
			tt.mutate(&c)

			err := c.Validate()
			if (err != nil) != tt.wantErr {
				t.Fatalf("Validate() error = %v, wantErr %v", err, tt.wantErr)
			}
			if err != nil && !errors.Is(err, contract.ErrInvalidContract) {
				t.Errorf("errors.Is(err, ErrInvalidContract) = false, want true; got %v", err)
			}
		})
	}
}

// sampleWithVersion returns the sample contract with contract_version swapped,
// so version behaviour is exercised against an otherwise valid payload.
func sampleWithVersion(t *testing.T, version string) []byte {
	t.Helper()
	var raw map[string]any
	if err := json.Unmarshal(sampleBytes(t), &raw); err != nil {
		t.Fatalf("unmarshal sample: %v", err)
	}
	raw["contract_version"] = version
	data, err := json.Marshal(raw)
	if err != nil {
		t.Fatalf("marshal sample: %v", err)
	}
	return data
}

// parseWithVersion parses the sample contract rewritten to a given version.
func parseWithVersion(t *testing.T, version string) *contract.EngineContract {
	t.Helper()
	c, err := contract.Parse(sampleWithVersion(t, version))
	if err != nil {
		t.Fatalf("Parse(%q) failed: %v", version, err)
	}
	return c
}

// TestMinorVersion covers the forward-compatibility seam: minor bumps are
// additive so they parse, but a feature needing a later minor must detect the
// skew rather than run silently against zero-valued fields.
func TestMinorVersion(t *testing.T) {
	t.Parallel()

	for _, tc := range []struct {
		name      string
		version   string
		wantMinor int
	}{
		{"explicit minor", "v1.1", 1},
		{"zero minor", "v1.0", 0},
		{"no v prefix", "1.2", 2},
		{"missing minor reads as zero", "v1", 0},
	} {
		t.Run(tc.name, func(t *testing.T) {
			t.Parallel()
			if got := parseWithVersion(t, tc.version).MinorVersion(); got != tc.wantMinor {
				t.Fatalf("MinorVersion() = %d, want %d", got, tc.wantMinor)
			}
		})
	}

	t.Run("non-numeric minor is rejected", func(t *testing.T) {
		t.Parallel()
		if _, err := contract.Parse(sampleWithVersion(t, "v1.x")); err == nil {
			t.Fatal("Parse accepted a malformed minor version")
		}
	})

	t.Run("RequireMinor fails loudly on a version skew", func(t *testing.T) {
		t.Parallel()
		v10 := parseWithVersion(t, "v1.0")
		if err := v10.RequireMinor(1); err == nil {
			t.Fatal("v1.0 satisfied RequireMinor(1); a skew must fail, not degrade silently")
		}
		if err := v10.RequireMinor(0); err != nil {
			t.Fatalf("v1.0 failed RequireMinor(0): %v", err)
		}
		if err := parseWithVersion(t, "v1.1").RequireMinor(1); err != nil {
			t.Fatalf("v1.1 failed RequireMinor(1): %v", err)
		}
	})
}

// TestParse_AllFailuresAreInvalidContract pins the classification contract:
// callers (the HTTP layer especially) distinguish "bad persona" from "server
// broke" with one errors.Is check, so every rejection path must carry
// ErrInvalidContract. Malformed JSON used to escape it and surfaced as a 5xx.
func TestParse_AllFailuresAreInvalidContract(t *testing.T) {
	t.Parallel()

	for _, tc := range []struct {
		name string
		data []byte
	}{
		{"malformed json", []byte("{not json")},
		{"empty body", []byte("")},
		{"wrong json type", []byte(`["an array, not an object"]`)},
	} {
		t.Run(tc.name, func(t *testing.T) {
			t.Parallel()
			_, err := contract.Parse(tc.data)
			if err == nil {
				t.Fatal("Parse accepted invalid input")
			}
			if !errors.Is(err, contract.ErrInvalidContract) {
				t.Fatalf("error %v does not match ErrInvalidContract; callers would classify it as a server fault", err)
			}
		})
	}

	t.Run("validation failure", func(t *testing.T) {
		t.Parallel()
		if _, err := contract.Parse([]byte(`{"contract_version":"v1.0"}`)); !errors.Is(err, contract.ErrInvalidContract) {
			t.Fatalf("validation failure did not match ErrInvalidContract: %v", err)
		}
	})

	t.Run("version failure keeps its own sentinel", func(t *testing.T) {
		t.Parallel()
		_, err := contract.Parse(sampleWithVersion(t, "v2.0"))
		if !errors.Is(err, contract.ErrUnsupportedVersion) {
			t.Fatalf("version failure did not match ErrUnsupportedVersion: %v", err)
		}
	})
}
