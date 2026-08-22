package config

import (
	"errors"
	"flag"
	"fmt"
	"strings"
	"testing"
	"time"
)

// fakeEnv builds a LookupFunc over a map, giving tests a hermetic,
// parallel-safe stand-in for os.LookupEnv — no process-global mutation.
func fakeEnv(kv map[string]string) LookupFunc {
	return func(key string) (string, bool) {
		v, ok := kv[key]
		return v, ok
	}
}

// allRequired returns a fully populated required-key map so tests that
// don't care about a particular key can start from a valid baseline and
// override just what they're testing.
func allRequired() map[string]string {
	return map[string]string{
		"GEMINI_API_KEY":              "gk-test",
		"OPENAI_API_KEY":              "ok-test",
		"SPEAKER_MODEL_ID":            "gemini-2.5-flash-live",
		"THINKER_MODEL_ID":            "gemini-2.5-pro",
		"JUDGE_MODEL_ID":              "gemini-2.5-flash",
		"TTS_MODEL_ID":                "gemini-2.5-flash-tts",
		"ASR_MODEL_ID":                "gpt-4o-transcribe",
		"S3_BUCKET":                   "interview-bundles",
		"S3_REGION":                   "us-east-1",
		"CONTROL_PLANE_BASE_URL":      "https://control-plane.internal",
		"CONTROL_PLANE_SHARED_SECRET": "shh",
	}
}

func TestLoad_AllRequiredPresent_AppliesDefaults(t *testing.T) {
	t.Parallel()

	cfg, err := Load(fakeEnv(allRequired()))
	if err != nil {
		t.Fatalf("Load returned unexpected error: %v", err)
	}

	if cfg.GeminiAPIKey.Reveal() != "gk-test" {
		t.Errorf("GeminiAPIKey = %q, want gk-test", cfg.GeminiAPIKey.Reveal())
	}
	if cfg.SpeakerModelID != "gemini-2.5-flash-live" {
		t.Errorf("SpeakerModelID = %q, want gemini-2.5-flash-live", cfg.SpeakerModelID)
	}
	if cfg.S3Prefix != "" {
		t.Errorf("S3Prefix = %q, want empty (optional, unset)", cfg.S3Prefix)
	}

	wantDefaults := map[string]struct {
		got  time.Duration
		want time.Duration
	}{
		"PreGateDeadline":          {cfg.PreGateDeadline, defaultPreGateDeadline},
		"StallDeadline":            {cfg.StallDeadline, defaultStallDeadline},
		"ThinkerDeadline":          {cfg.ThinkerDeadline, defaultThinkerDeadline},
		"PauseBeforeAnswerDefault": {cfg.PauseBeforeAnswerDefault, defaultPauseBeforeAnswer},
		"SilenceTimeout":           {cfg.SilenceTimeout, defaultSilenceTimeout},
		"SessionDurationCap":       {cfg.SessionDurationCap, defaultSessionDurationCap},
	}
	for name, d := range wantDefaults {
		if d.got != d.want {
			t.Errorf("%s = %v, want default %v", name, d.got, d.want)
		}
	}
	if cfg.SessionCostCapUSD != defaultSessionCostCapUSD {
		t.Errorf("SessionCostCapUSD = %v, want default %v", cfg.SessionCostCapUSD, defaultSessionCostCapUSD)
	}
}

func TestLoad_Overrides_TakePrecedenceOverDefaults(t *testing.T) {
	t.Parallel()

	kv := allRequired()
	kv["S3_PREFIX"] = "sessions/"
	kv["SESSION_COST_CAP_USD"] = "12.5"
	kv["PREGATE_DEADLINE_MS"] = "300"
	kv["ABANDON_AFTER_S"] = "120"

	cfg, err := Load(fakeEnv(kv))
	if err != nil {
		t.Fatalf("Load returned unexpected error: %v", err)
	}

	if cfg.S3Prefix != "sessions/" {
		t.Errorf("S3Prefix = %q, want sessions/", cfg.S3Prefix)
	}
	if cfg.SessionCostCapUSD != 12.5 {
		t.Errorf("SessionCostCapUSD = %v, want 12.5", cfg.SessionCostCapUSD)
	}
	if cfg.PreGateDeadline != 300*time.Millisecond {
		t.Errorf("PreGateDeadline = %v, want 300ms", cfg.PreGateDeadline)
	}
	if cfg.SilenceTimeout != 120*time.Second {
		t.Errorf("SilenceTimeout = %v, want 120s", cfg.SilenceTimeout)
	}
}

func TestLoad_MissingRequired_AggregatesAllAtOnce(t *testing.T) {
	t.Parallel()

	// Empty environment: every required key is missing.
	_, err := Load(fakeEnv(nil))
	if err == nil {
		t.Fatal("Load returned nil error for an empty environment")
	}

	var loadErr *LoadError
	if !errors.As(err, &loadErr) {
		t.Fatalf("error is not a *LoadError: %T: %v", err, err)
	}
	if !errors.Is(err, ErrRequired) {
		t.Error("errors.Is(err, ErrRequired) = false, want true")
	}

	wantKeys := []string{
		"GEMINI_API_KEY", "OPENAI_API_KEY",
		"SPEAKER_MODEL_ID", "THINKER_MODEL_ID", "JUDGE_MODEL_ID", "TTS_MODEL_ID", "ASR_MODEL_ID",
		"S3_BUCKET", "S3_REGION",
		"CONTROL_PLANE_BASE_URL", "CONTROL_PLANE_SHARED_SECRET",
	}
	if len(loadErr.Issues) != len(wantKeys) {
		t.Fatalf("got %d issues, want %d: %v", len(loadErr.Issues), len(wantKeys), loadErr)
	}
	got := make(map[string]bool, len(loadErr.Issues))
	for _, issue := range loadErr.Issues {
		got[issue.Key] = true
		if !errors.Is(issue, ErrRequired) {
			t.Errorf("issue %q does not wrap ErrRequired: %v", issue.Key, issue)
		}
	}
	for _, key := range wantKeys {
		if !got[key] {
			t.Errorf("missing-key error does not name %s; full error: %v", key, err)
		}
	}

	// The single aggregated error names every missing key, not just the
	// first one found.
	for _, key := range wantKeys {
		if !strings.Contains(err.Error(), key) {
			t.Errorf("aggregated error message missing %s: %s", key, err.Error())
		}
	}
}

func TestLoad_InvalidDuration_ReportsIssueAndKeepsDefault(t *testing.T) {
	t.Parallel()

	kv := allRequired()
	kv["THINKER_DEADLINE_MS"] = "not-a-number"

	_, err := Load(fakeEnv(kv))
	if err == nil {
		t.Fatal("Load returned nil error for an unparseable duration")
	}
	if !errors.Is(err, ErrInvalid) {
		t.Errorf("errors.Is(err, ErrInvalid) = false, want true: %v", err)
	}
	if errors.Is(err, ErrRequired) {
		t.Errorf("errors.Is(err, ErrRequired) = true, want false (only THINKER_DEADLINE_MS was bad): %v", err)
	}
	if !strings.Contains(err.Error(), "THINKER_DEADLINE_MS") {
		t.Errorf("error does not name THINKER_DEADLINE_MS: %v", err)
	}
}

func TestLoad_InvalidCostCap_ReportsIssue(t *testing.T) {
	t.Parallel()

	kv := allRequired()
	kv["SESSION_COST_CAP_USD"] = "five-dollars"

	_, err := Load(fakeEnv(kv))
	if err == nil {
		t.Fatal("Load returned nil error for an unparseable cost cap")
	}
	if !errors.Is(err, ErrInvalid) {
		t.Errorf("errors.Is(err, ErrInvalid) = false, want true: %v", err)
	}
}

func TestLoad_MissingAndInvalid_BothReportedTogether(t *testing.T) {
	t.Parallel()

	kv := allRequired()
	delete(kv, "GEMINI_API_KEY")
	kv["PREGATE_DEADLINE_MS"] = "oops"

	_, err := Load(fakeEnv(kv))
	if err == nil {
		t.Fatal("Load returned nil error")
	}
	if !errors.Is(err, ErrRequired) {
		t.Error("errors.Is(err, ErrRequired) = false, want true")
	}
	if !errors.Is(err, ErrInvalid) {
		t.Error("errors.Is(err, ErrInvalid) = false, want true")
	}

	var loadErr *LoadError
	if !errors.As(err, &loadErr) {
		t.Fatalf("error is not a *LoadError: %v", err)
	}
	if len(loadErr.Issues) != 2 {
		t.Fatalf("got %d issues, want 2: %v", len(loadErr.Issues), loadErr)
	}
}

func TestLoad_ConcurrentCallsAreIndependent(t *testing.T) {
	t.Parallel()

	// Two goroutines Load from two independent fake environments
	// concurrently. This only proves the seam is safe if config.Load
	// itself never touches package/process globals — which is the point
	// of injecting LookupFunc instead of calling os.Getenv directly.
	done := make(chan error, 2)
	go func() {
		_, err := Load(fakeEnv(allRequired()))
		done <- err
	}()
	go func() {
		_, err := Load(fakeEnv(nil))
		done <- err
	}()

	err1 := <-done
	err2 := <-done
	// One of the two calls used a complete env and the other an empty one;
	// exactly one of the two results must be nil.
	if (err1 == nil) == (err2 == nil) {
		t.Fatalf("expected exactly one of the two concurrent Loads to fail, got %v and %v", err1, err2)
	}
}

func TestSecret_StringAndFormatting_Redacts(t *testing.T) {
	t.Parallel()

	const raw = "sk-super-secret-value"
	s := NewSecret(raw)

	checks := []struct {
		name string
		out  string
	}{
		{"String()", s.String()},
		{"%v", fmt.Sprintf("%v", s)},
		{"%s", fmt.Sprintf("%s", s)},
		{"%+v", fmt.Sprintf("%+v", s)},
		{"%#v", fmt.Sprintf("%#v", s)},
	}
	for _, c := range checks {
		if strings.Contains(c.out, raw) {
			t.Errorf("%s leaked the raw secret: %q", c.name, c.out)
		}
	}

	if s.Reveal() != raw {
		t.Errorf("Reveal() = %q, want %q", s.Reveal(), raw)
	}

	// A Secret embedded in a struct must not leak via %v/%+v either.
	type wrapper struct{ Key Secret }
	w := wrapper{Key: s}
	if strings.Contains(fmt.Sprintf("%+v", w), raw) {
		t.Errorf("struct %%+v leaked the raw secret: %q", fmt.Sprintf("%+v", w))
	}

	if got := s.LogValue().String(); strings.Contains(got, raw) {
		t.Errorf("LogValue() leaked the raw secret: %q", got)
	}
}

func TestSecret_ZeroValue_IsEmptyNotRedacted(t *testing.T) {
	t.Parallel()

	var s Secret
	if !s.IsZero() {
		t.Error("zero-value Secret.IsZero() = false, want true")
	}
	if s.String() != "" {
		t.Errorf("zero-value Secret.String() = %q, want empty", s.String())
	}
}

func TestBindFlags_OverridesNonSecretFields(t *testing.T) {
	t.Parallel()

	cfg, err := Load(fakeEnv(allRequired()))
	if err != nil {
		t.Fatalf("Load returned unexpected error: %v", err)
	}

	fs := flag.NewFlagSet("test", flag.ContinueOnError)
	cfg.BindFlags(fs)
	if err := fs.Parse([]string{
		"-speaker-model-id=gemini-3.1-flash-live",
		"-session-cost-cap-usd=9.99",
		"-thinker-deadline=500ms",
	}); err != nil {
		t.Fatalf("fs.Parse returned unexpected error: %v", err)
	}

	if cfg.SpeakerModelID != "gemini-3.1-flash-live" {
		t.Errorf("SpeakerModelID = %q, want gemini-3.1-flash-live", cfg.SpeakerModelID)
	}
	if cfg.SessionCostCapUSD != 9.99 {
		t.Errorf("SessionCostCapUSD = %v, want 9.99", cfg.SessionCostCapUSD)
	}
	if cfg.ThinkerDeadline != 500*time.Millisecond {
		t.Errorf("ThinkerDeadline = %v, want 500ms", cfg.ThinkerDeadline)
	}
}

func TestBindFlags_NoSecretFlagsRegistered(t *testing.T) {
	t.Parallel()

	cfg, err := Load(fakeEnv(allRequired()))
	if err != nil {
		t.Fatalf("Load returned unexpected error: %v", err)
	}

	fs := flag.NewFlagSet("test", flag.ContinueOnError)
	cfg.BindFlags(fs)

	secretFlagNames := []string{
		"gemini-api-key", "openai-api-key", "control-plane-shared-secret",
	}
	for _, name := range secretFlagNames {
		if fs.Lookup(name) != nil {
			t.Errorf("BindFlags registered a flag for secret %q; env must remain the sole source of truth", name)
		}
	}
}
