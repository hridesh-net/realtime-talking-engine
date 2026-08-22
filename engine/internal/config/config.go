package config

import (
	"flag"
	"fmt"
	"os"
	"strconv"
	"time"
)

// Defaults for values the plan gives a concrete number for
// (docs/ENGINE_IMPLEMENTATION_PLAN.md §4, §11). Model IDs have no default —
// see the doc comment on Config's model-id fields — and every other
// required value (vendor keys, S3 location, control-plane address) has no
// default either: a missing deploy value should fail loudly, not silently
// run against the wrong bucket or endpoint.
const (
	// defaultPreGateDeadline is the deterministic pre-gate's verdict
	// deadline after end-of-turn (plan §4 step 3).
	defaultPreGateDeadline = 250 * time.Millisecond
	// defaultStallDeadline is the target latency for the first stall clip
	// to reach the transport after a DEFER verdict (plan §4 DEFERRED state,
	// task 28).
	defaultStallDeadline = 50 * time.Millisecond
	// defaultThinkerDeadline is how long the actor waits for a Thinker note
	// before falling back to the contract's on_unknown_question/on_pressure
	// directive (plan §4 DEFERRED state, §11 row 2).
	defaultThinkerDeadline = 700 * time.Millisecond
	// defaultPauseBeforeAnswer is the fallback pause-before-answer target
	// used only when a contract's voice_directives.target_pause_before_answer_ms
	// is absent; the sample contract's own value is also 700ms (plan §4
	// PRE_ANSWER state, line ~60).
	defaultPauseBeforeAnswer = 700 * time.Millisecond
	// defaultSilenceTimeout is how long the actor waits in silence before
	// applying on_silence and, on a second span, abandoning the session
	// (plan §11 "Abandonment" row, ABANDON_AFTER_S).
	defaultSilenceTimeout = 300 * time.Second
	// defaultSessionDurationCap bounds total session wall-clock time. The
	// plan does not pin an exact number (OQ-8 notes live interviews run
	// "45-60 min"); default to the top of that range and let deploys tune
	// it with SESSION_DURATION_CAP_S.
	defaultSessionDurationCap = 60 * time.Minute
	// defaultSessionCostCapUSD is the per-session spend ceiling that trips
	// WINDING_DOWN with end_reason "cost_cap" (plan §11 row 6).
	defaultSessionCostCapUSD = 5.0
)

// LookupFunc looks up an environment variable by name, mirroring
// os.LookupEnv's signature. Load takes one as a seam so tests can inject a
// fake map-backed environment instead of mutating process-global state via
// os.Setenv — keeping config tests parallel-safe.
type LookupFunc func(key string) (string, bool)

// Config is the engine's fully parsed, validated configuration. It is the
// only typed surface other packages see; nothing outside internal/config
// reads an environment variable directly (enforced by internal/arch).
type Config struct {
	// GeminiAPIKey authenticates the Gemini Live Speaker adapter and the
	// stall-bank/opening-line TTS adapter.
	GeminiAPIKey Secret
	// OpenAIAPIKey authenticates the OpenAI Realtime Speaker adapter and
	// the OpenAI realtime-transcription Transcriber adapter.
	OpenAIAPIKey Secret

	// SpeakerModelID is the realtime speech model the Speaker adapter
	// opens a session against. Model IDs are config, never hardcoded
	// (CLAUDE.md hard rule; plan §10 arch check 5 bans vendor model-id
	// literals outside this package and testdata/). No default: which
	// vendor/model is live is an operational decision, not a code default,
	// until plan task 51 sets one after the Speaker A/B.
	SpeakerModelID string
	// ThinkerModelID is the reasoning model behind the Thinker port.
	ThinkerModelID string
	// JudgeModelID is the model behind the async post-hoc semantic Judge.
	JudgeModelID string
	// TTSModelID is the model behind stall-bank and opening-line
	// pre-synthesis.
	TTSModelID string
	// ASRModelID is the model/engine behind the independent Transcriber
	// port (vendor or self-hosted, per plan tasks 25-26).
	ASRModelID string

	// S3Bucket is the destination for session bundles (recording,
	// transcripts, event log; plan §9).
	S3Bucket string
	// S3Region is the bucket's AWS region.
	S3Region string
	// S3Prefix namespaces object keys within the bucket. Optional; empty
	// means objects are written at the bucket root.
	S3Prefix string

	// ControlPlaneBaseURL is the base URL of the Python control-plane
	// service this engine fetches contracts from and notifies ingest to.
	ControlPlaneBaseURL string
	// ControlPlaneSharedSecret authenticates the engine to the control
	// plane (plan §15 OQ-6: shared secret or mTLS).
	ControlPlaneSharedSecret Secret

	// SessionCostCapUSD is the per-session spend ceiling. Crossing it
	// drives WINDING_DOWN with end_reason "cost_cap" (plan §11).
	SessionCostCapUSD float64

	// PreGateDeadline is the deterministic pre-gate's verdict deadline
	// after end-of-turn. A verdict not ready by this deadline is treated
	// as CONFIDENT (plan §4 step 3).
	PreGateDeadline time.Duration
	// StallDeadline is the target latency for the first stall clip to
	// reach the transport after a DEFER verdict (plan task 28).
	StallDeadline time.Duration
	// ThinkerDeadline is how long the actor waits for a Thinker note
	// before falling back to the contract's directive (plan §11 row 2).
	ThinkerDeadline time.Duration
	// PauseBeforeAnswerDefault is the pause-before-answer target used when
	// a contract does not specify
	// voice_directives.target_pause_before_answer_ms.
	PauseBeforeAnswerDefault time.Duration
	// SilenceTimeout is how long the actor tolerates silence before
	// applying on_silence, and — per the plan's abandonment row — the same
	// span again before ending the session (plan §11 "Abandonment").
	SilenceTimeout time.Duration
	// SessionDurationCap bounds total session wall-clock time; crossing it
	// drives WINDING_DOWN alongside the cost cap (plan §11).
	SessionDurationCap time.Duration
}

// requiredKeys lists every key whose absence makes Load fail, in the order
// they're checked (not the order reported — LoadError sorts for
// determinism).
type loader struct {
	lookup LookupFunc
	issues []*Issue
}

// str returns the raw value for key, or "" if unset. Used for optional
// string fields.
func (l *loader) str(key string) string {
	v, _ := l.lookup(key)
	return v
}

// required returns the raw value for key, recording an Issue if it is
// unset or empty.
func (l *loader) required(key string) string {
	v, ok := l.lookup(key)
	if !ok || v == "" {
		l.issues = append(l.issues, &Issue{Key: key, Err: ErrRequired})
		return ""
	}
	return v
}

// requiredSecret is required, wrapped as a Secret.
func (l *loader) requiredSecret(key string) Secret {
	return NewSecret(l.required(key))
}

// durationMs reads key as a millisecond integer, falling back to def if
// unset. A present-but-unparseable value records an Issue and also falls
// back to def, so a single bad field doesn't cascade into unrelated
// zero-value durations.
func (l *loader) durationMs(key string, def time.Duration) time.Duration {
	v, ok := l.lookup(key)
	if !ok || v == "" {
		return def
	}
	n, err := strconv.Atoi(v)
	if err != nil {
		l.issues = append(l.issues, &Issue{Key: key, Err: fmt.Errorf("%w: %s", ErrInvalid, err.Error())})
		return def
	}
	return time.Duration(n) * time.Millisecond
}

// durationS reads key as a second integer, falling back to def if unset.
func (l *loader) durationS(key string, def time.Duration) time.Duration {
	v, ok := l.lookup(key)
	if !ok || v == "" {
		return def
	}
	n, err := strconv.Atoi(v)
	if err != nil {
		l.issues = append(l.issues, &Issue{Key: key, Err: fmt.Errorf("%w: %s", ErrInvalid, err.Error())})
		return def
	}
	return time.Duration(n) * time.Second
}

// float64 reads key as a float64, falling back to def if unset.
func (l *loader) float64(key string, def float64) float64 {
	v, ok := l.lookup(key)
	if !ok || v == "" {
		return def
	}
	f, err := strconv.ParseFloat(v, 64)
	if err != nil {
		l.issues = append(l.issues, &Issue{Key: key, Err: fmt.Errorf("%w: %s", ErrInvalid, err.Error())})
		return def
	}
	return f
}

// LoadFromEnv reads configuration from the real process environment.
//
// This exists so os.LookupEnv is called here and nowhere else: cmd/engined
// wires the engine together, and if it had to pass os.LookupEnv into Load it
// would itself become a package that reads the environment, breaking the rule
// internal/arch enforces. Tests use Load with an injected LookupFunc instead.
func LoadFromEnv() (*Config, error) {
	return Load(os.LookupEnv)
}

// Load reads configuration from the environment via lookup, applying the
// defaults documented on Config's fields, and validates it. On success it
// returns a fully populated *Config. On failure it returns a *LoadError
// naming every missing or invalid key at once — never just the first one —
// so a half-configured deploy fails with the complete list.
//
// lookup is typically os.LookupEnv in production and a fake map-backed
// function in tests (see LookupFunc).
func Load(lookup LookupFunc) (*Config, error) {
	l := &loader{lookup: lookup}

	cfg := &Config{
		GeminiAPIKey: l.requiredSecret("GEMINI_API_KEY"),
		OpenAIAPIKey: l.requiredSecret("OPENAI_API_KEY"),

		SpeakerModelID: l.required("SPEAKER_MODEL_ID"),
		ThinkerModelID: l.required("THINKER_MODEL_ID"),
		JudgeModelID:   l.required("JUDGE_MODEL_ID"),
		TTSModelID:     l.required("TTS_MODEL_ID"),
		ASRModelID:     l.required("ASR_MODEL_ID"),

		S3Bucket: l.required("S3_BUCKET"),
		S3Region: l.required("S3_REGION"),
		S3Prefix: l.str("S3_PREFIX"),

		ControlPlaneBaseURL:      l.required("CONTROL_PLANE_BASE_URL"),
		ControlPlaneSharedSecret: l.requiredSecret("CONTROL_PLANE_SHARED_SECRET"),

		SessionCostCapUSD: l.float64("SESSION_COST_CAP_USD", defaultSessionCostCapUSD),

		PreGateDeadline:          l.durationMs("PREGATE_DEADLINE_MS", defaultPreGateDeadline),
		StallDeadline:            l.durationMs("STALL_DEADLINE_MS", defaultStallDeadline),
		ThinkerDeadline:          l.durationMs("THINKER_DEADLINE_MS", defaultThinkerDeadline),
		PauseBeforeAnswerDefault: l.durationMs("PAUSE_BEFORE_ANSWER_DEFAULT_MS", defaultPauseBeforeAnswer),
		SilenceTimeout:           l.durationS("ABANDON_AFTER_S", defaultSilenceTimeout),
		SessionDurationCap:       l.durationS("SESSION_DURATION_CAP_S", defaultSessionDurationCap),
	}

	if len(l.issues) > 0 {
		return nil, &LoadError{Issues: l.issues}
	}
	return cfg, nil
}

// BindFlags registers command-line flags for the subset of configuration
// that is safe to override at the process boundary. Vendor API keys and
// the control-plane shared secret get no flag by design: env is the source
// of truth for secrets. Call fs.Parse after BindFlags; parsed flags
// overwrite the corresponding field on c in place, so BindFlags is meant to
// run on a *Config already produced by Load.
func (c *Config) BindFlags(fs *flag.FlagSet) {
	fs.StringVar(&c.SpeakerModelID, "speaker-model-id", c.SpeakerModelID, "realtime speech model ID for the Speaker adapter")
	fs.StringVar(&c.ThinkerModelID, "thinker-model-id", c.ThinkerModelID, "reasoning model ID for the Thinker port")
	fs.StringVar(&c.JudgeModelID, "judge-model-id", c.JudgeModelID, "model ID for the async post-hoc semantic Judge")
	fs.StringVar(&c.TTSModelID, "tts-model-id", c.TTSModelID, "model ID for stall-bank/opening-line pre-synthesis")
	fs.StringVar(&c.ASRModelID, "asr-model-id", c.ASRModelID, "model/engine ID for the Transcriber port")

	fs.StringVar(&c.S3Bucket, "s3-bucket", c.S3Bucket, "S3 bucket for session bundles")
	fs.StringVar(&c.S3Region, "s3-region", c.S3Region, "S3 bucket region")
	fs.StringVar(&c.S3Prefix, "s3-prefix", c.S3Prefix, "S3 object key prefix")

	fs.StringVar(&c.ControlPlaneBaseURL, "control-plane-base-url", c.ControlPlaneBaseURL, "base URL of the control-plane service")

	fs.Float64Var(&c.SessionCostCapUSD, "session-cost-cap-usd", c.SessionCostCapUSD, "per-session spend ceiling in USD")

	fs.DurationVar(&c.PreGateDeadline, "pregate-deadline", c.PreGateDeadline, "pre-gate verdict deadline after end-of-turn")
	fs.DurationVar(&c.StallDeadline, "stall-deadline", c.StallDeadline, "target latency for the first stall clip after a DEFER verdict")
	fs.DurationVar(&c.ThinkerDeadline, "thinker-deadline", c.ThinkerDeadline, "Thinker note deadline before falling back to the contract directive")
	fs.DurationVar(&c.PauseBeforeAnswerDefault, "pause-before-answer-default", c.PauseBeforeAnswerDefault, "fallback pause-before-answer target when a contract omits one")
	fs.DurationVar(&c.SilenceTimeout, "silence-timeout", c.SilenceTimeout, "silence span before on_silence, and again before abandonment")
	fs.DurationVar(&c.SessionDurationCap, "session-duration-cap", c.SessionDurationCap, "maximum session wall-clock duration")
}
