package config

import (
	"errors"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"runtime"
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
		//nolint:staticcheck // exercising the fmt %s path is the point: Secret must
		// redact through fmt, not only when String is called directly.
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

func TestListLoaderSplitsAndTrimsCSV(t *testing.T) {
	t.Parallel()

	// A deploy sets a list variable as a comma-separated string with
	// human-typed spacing; strList must split on commas, trim the
	// surrounding whitespace off each element, and drop elements that are
	// empty after trimming (e.g. a trailing comma) rather than keeping a
	// stray "" entry.
	l := &loader{lookup: fakeEnv(map[string]string{
		"LIST_KEY": " a, b ,c ,, d",
	})}

	got := l.strList("LIST_KEY", []string{"unused-default"})
	want := []string{"a", "b", "c", "d"}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("strList = %#v, want %#v", got, want)
	}
	if len(l.issues) != 0 {
		t.Errorf("strList recorded issues for valid input: %v", l.issues)
	}
}

func TestListLoaderFallsBackToTheDefaultWhenUnset(t *testing.T) {
	t.Parallel()

	// Both an entirely absent variable and one set to the empty string
	// must fall back to the caller's default — an operator who sets
	// FOO= in a .env file did not mean "empty list", they meant "not
	// overridden".
	def := []string{"stun:stun.l.google.com:19302"}

	unset := &loader{lookup: fakeEnv(nil)}
	if got := unset.strList("LIST_KEY", def); !reflect.DeepEqual(got, def) {
		t.Errorf("strList on unset key = %#v, want default %#v", got, def)
	}

	empty := &loader{lookup: fakeEnv(map[string]string{"LIST_KEY": ""})}
	if got := empty.strList("LIST_KEY", def); !reflect.DeepEqual(got, def) {
		t.Errorf("strList on empty-string key = %#v, want default %#v", got, def)
	}

	// A value that is only commas/whitespace trims down to zero elements,
	// which must also fall back to the default rather than returning an
	// empty-but-non-nil slice a caller might mistake for "explicitly
	// cleared".
	blank := &loader{lookup: fakeEnv(map[string]string{"LIST_KEY": " , , "})}
	if got := blank.strList("LIST_KEY", def); !reflect.DeepEqual(got, def) {
		t.Errorf("strList on all-blank key = %#v, want default %#v", got, def)
	}
}

func TestBooleanLoaderRejectsGarbageAndKeepsTheDefault(t *testing.T) {
	t.Parallel()

	// A present-but-unparseable boolean must not cascade into a silent
	// zero value: it records an Issue (so Load's aggregation surfaces it)
	// and still returns the caller's default, matching durationMs/float64.
	l := &loader{lookup: fakeEnv(map[string]string{"BOOL_KEY": "maybe"})}

	got := l.boolean("BOOL_KEY", true)
	if got != true {
		t.Errorf("boolean on garbage input = %v, want default true", got)
	}
	if len(l.issues) != 1 {
		t.Fatalf("got %d issues, want 1: %v", len(l.issues), l.issues)
	}
	if l.issues[0].Key != "BOOL_KEY" {
		t.Errorf("issue key = %q, want BOOL_KEY", l.issues[0].Key)
	}
	if !errors.Is(l.issues[0], ErrInvalid) {
		t.Errorf("issue does not wrap ErrInvalid: %v", l.issues[0])
	}

	// Every accepted spelling, case-insensitively, must parse cleanly with
	// no issue recorded.
	cases := map[string]bool{
		"true": true, "TRUE": true, "True": true,
		"1": true, "yes": true, "YES": true,
		"false": false, "FALSE": false, "0": false, "no": false, "NO": false,
	}
	for input, want := range cases {
		ll := &loader{lookup: fakeEnv(map[string]string{"BOOL_KEY": input})}
		if got := ll.boolean("BOOL_KEY", !want); got != want {
			t.Errorf("boolean(%q) = %v, want %v", input, got, want)
		}
		if len(ll.issues) != 0 {
			t.Errorf("boolean(%q) recorded an issue for valid input: %v", input, ll.issues)
		}
	}
}

func TestBooleanDefaultsThatAreTrueStayTrueWhenUnset(t *testing.T) {
	t.Parallel()

	// WALKBACK_ENABLED and DEFER_TOOL_ENABLED both default to true. A
	// naive `v, ok := lookup(key); return ok && v == "true"` style
	// implementation silently returns false for an unset key regardless
	// of the caller's default — this guards against that regression by
	// loading through the real Load path with neither variable set.
	cfg, err := Load(fakeEnv(allRequired()))
	if err != nil {
		t.Fatalf("Load returned unexpected error: %v", err)
	}
	if !cfg.WalkbackEnabled {
		t.Error("WalkbackEnabled = false with WALKBACK_ENABLED unset, want true (the documented default)")
	}
	if !cfg.DeferToolEnabled {
		t.Error("DeferToolEnabled = false with DEFER_TOOL_ENABLED unset, want true (the documented default)")
	}
}

func TestNoNewVariableIsRequired(t *testing.T) {
	t.Parallel()

	// Loading with only the pre-existing required keys present must
	// succeed: every M1.3 field (SPEAKER_VENDOR, WEBRTC_ICE_SERVERS,
	// TURN_*, S3_ENDPOINT, S3_FORCE_PATH_STYLE, WALKBACK_ENABLED,
	// DEFER_TOOL_ENABLED, CONNECT_TIMEOUT_S, SPOOL_DIR, METRICS_ADDR,
	// GEMINI_TTS_VOICES) is optional. TestLoad_MissingRequired_AggregatesAllAtOnce
	// pins the exact *count* of required-key issues on an empty
	// environment; a new required variable would silently inflate that
	// count without failing loudly here first.
	cfg, err := Load(fakeEnv(allRequired()))
	if err != nil {
		t.Fatalf("Load returned unexpected error with only the pre-existing required set present: %v", err)
	}
	if cfg == nil {
		t.Fatal("Load returned a nil Config alongside a nil error")
	}

	newKeys := []string{
		"SPEAKER_VENDOR", "WEBRTC_ICE_SERVERS", "TURN_URL", "TURN_USERNAME",
		"TURN_CREDENTIAL", "S3_ENDPOINT", "S3_FORCE_PATH_STYLE",
		"WALKBACK_ENABLED", "DEFER_TOOL_ENABLED", "CONNECT_TIMEOUT_S",
		"SPOOL_DIR", "METRICS_ADDR", "GEMINI_TTS_VOICES",
	}
	// Belt-and-suspenders: even if Load somehow returned a non-nil error
	// above (caught by the Fatalf), make sure none of the new keys are
	// the cause, so a failure here points at the right variable.
	var loadErr *LoadError
	if errors.As(err, &loadErr) {
		for _, issue := range loadErr.Issues {
			for _, key := range newKeys {
				if issue.Key == key {
					t.Errorf("new optional variable %s produced an issue: %v", key, issue)
				}
			}
		}
	}
}

func TestEnvExampleListsEveryEngineVariable(t *testing.T) {
	t.Parallel()

	// Locate the repo-root .env.example relative to this source file's own
	// on-disk path (not the working directory, which varies by how `go
	// test` is invoked) — the same pattern internal/fakes/contractsource.go
	// uses for its sample-contract fixture.
	_, thisFile, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("runtime.Caller(0) failed")
	}
	path := filepath.Clean(filepath.Join(filepath.Dir(thisFile), "..", "..", "..", ".env.example"))
	data, err := os.ReadFile(path) // #nosec G304 -- path is derived from this file's own location, not external input; tests are exempt from gosec anyway.
	if err != nil {
		t.Fatalf("read %s: %v", path, err)
	}
	content := string(data)

	// Every environment variable the config package reads, kept in sync by
	// hand with config.go's Load function (19 pre-existing + 13 added by
	// M1.3 = 32).
	allEngineKeys := []string{
		"GEMINI_API_KEY", "OPENAI_API_KEY",
		"SPEAKER_MODEL_ID", "THINKER_MODEL_ID", "JUDGE_MODEL_ID", "TTS_MODEL_ID", "ASR_MODEL_ID",
		"S3_BUCKET", "S3_REGION", "S3_PREFIX",
		"CONTROL_PLANE_BASE_URL", "CONTROL_PLANE_SHARED_SECRET",
		"SESSION_COST_CAP_USD",
		"PREGATE_DEADLINE_MS", "STALL_DEADLINE_MS", "THINKER_DEADLINE_MS",
		"PAUSE_BEFORE_ANSWER_DEFAULT_MS", "ABANDON_AFTER_S", "SESSION_DURATION_CAP_S",
		"SPEAKER_VENDOR",
		"WEBRTC_ICE_SERVERS", "TURN_URL", "TURN_USERNAME", "TURN_CREDENTIAL",
		"S3_ENDPOINT", "S3_FORCE_PATH_STYLE",
		"WALKBACK_ENABLED", "DEFER_TOOL_ENABLED",
		"CONNECT_TIMEOUT_S",
		"SPOOL_DIR",
		"METRICS_ADDR",
		"GEMINI_TTS_VOICES",
	}

	var missing []string
	for _, key := range allEngineKeys {
		if !strings.Contains(content, key) {
			missing = append(missing, key)
		}
	}
	if len(missing) > 0 {
		t.Errorf(".env.example is missing %d engine variable(s): %s", len(missing), strings.Join(missing, ", "))
	}
}

// TestAFlagSuppliesAValueItsEnvironmentVariableWasMissing guards the promise a
// flag's own name makes. Load runs before flags are parsed, so it records a
// required key as missing even when the operator passed it on the command line;
// if that stale issue stayed fatal, every flag naming a required variable would
// appear in -h while being unable to do the one thing it advertises.
func TestAFlagSuppliesAValueItsEnvironmentVariableWasMissing(t *testing.T) {
	t.Parallel()

	env := allRequired()
	delete(env, "SPEAKER_MODEL_ID")
	cfg, loadErr := Load(fakeEnv(env))
	if loadErr == nil {
		t.Fatal("expected Load to report the missing SPEAKER_MODEL_ID")
	}

	fs := flag.NewFlagSet("test", flag.ContinueOnError)
	cfg.BindFlags(fs)
	if err := fs.Parse([]string{"-speaker-model-id", "some-model"}); err != nil {
		t.Fatalf("parse: %v", err)
	}
	if err := ResolveFlagOverrides(fs, loadErr); err != nil {
		t.Fatalf("flag override should have satisfied the missing key, got: %v", err)
	}
	if cfg.SpeakerModelID != "some-model" {
		t.Fatalf("flag value did not reach the config: %q", cfg.SpeakerModelID)
	}
}

// TestAnUnrelatedFlagDoesNotSuppressAMissingRequiredKey is the other half: only
// the variable actually overridden is forgiven. Dropping every issue as soon as
// any flag was passed would let a half-configured process boot.
func TestAnUnrelatedFlagDoesNotSuppressAMissingRequiredKey(t *testing.T) {
	t.Parallel()

	env := allRequired()
	delete(env, "SPEAKER_MODEL_ID")
	cfg, loadErr := Load(fakeEnv(env))

	fs := flag.NewFlagSet("test", flag.ContinueOnError)
	cfg.BindFlags(fs)
	if err := fs.Parse([]string{"-s3-prefix", "unrelated"}); err != nil {
		t.Fatalf("parse: %v", err)
	}
	err := ResolveFlagOverrides(fs, loadErr)
	if err == nil {
		t.Fatal("an unrelated flag must not excuse the still-missing SPEAKER_MODEL_ID")
	}
	if !strings.Contains(err.Error(), "SPEAKER_MODEL_ID") {
		t.Fatalf("error should still name the missing key, got: %v", err)
	}
}

// TestFlagOverridesLeaveACleanLoadAlone keeps ResolveFlagOverrides honest about
// the ordinary case: no issues in, no error out.
func TestFlagOverridesLeaveACleanLoadAlone(t *testing.T) {
	t.Parallel()

	cfg, loadErr := Load(fakeEnv(allRequired()))
	if loadErr != nil {
		t.Fatalf("fixture should load cleanly: %v", loadErr)
	}
	fs := flag.NewFlagSet("test", flag.ContinueOnError)
	cfg.BindFlags(fs)
	if err := fs.Parse([]string{"-s3-prefix", "x"}); err != nil {
		t.Fatalf("parse: %v", err)
	}
	if err := ResolveFlagOverrides(fs, nil); err != nil {
		t.Fatalf("clean load must stay clean, got: %v", err)
	}
}

// TestEveryRegisteredFlagMapsToAnEnvironmentVariable stops flagEnvKeys going
// stale. A flag added to BindFlags without an entry here would silently lose the
// ability to satisfy its own variable — the exact defect this table fixes, back
// again and invisible.
func TestEveryRegisteredFlagMapsToAnEnvironmentVariable(t *testing.T) {
	t.Parallel()

	var cfg Config
	fs := flag.NewFlagSet("test", flag.ContinueOnError)
	cfg.BindFlags(fs)

	var missing []string
	fs.VisitAll(func(f *flag.Flag) {
		if _, ok := flagEnvKeys[f.Name]; !ok {
			missing = append(missing, f.Name)
		}
	})
	if len(missing) > 0 {
		t.Fatalf("flags registered with no flagEnvKeys entry: %v", missing)
	}
}
