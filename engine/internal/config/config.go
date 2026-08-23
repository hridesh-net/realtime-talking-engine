package config

import (
	"errors"
	"flag"
	"fmt"
	"os"
	"strconv"
	"strings"
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
	// defaultConnectTimeout bounds how long the engine waits for a
	// transport connection (WebRTC signaling, vendor session open) to
	// establish before giving up.
	defaultConnectTimeout = 15 * time.Second
	// defaultSpoolDir is where in-flight session artifacts (recording,
	// transcript, event log) are buffered on local disk before upload to
	// S3.
	defaultSpoolDir = "./spool"
	// defaultSpeakerVendor selects which Speaker adapter backs a session
	// when SPEAKER_VENDOR is unset.
	defaultSpeakerVendor = "gemini"
)

// defaultWebRTCICEServers is the ICE server list used when
// WEBRTC_ICE_SERVERS is unset: a public STUN server sufficient for
// development and for peers that don't need relay.
var defaultWebRTCICEServers = []string{"stun:stun.l.google.com:19302"}

// defaultTTSVoices is the verified Gemini prebuilt voice roster. This is an
// ordered, append-only list: a persona's voice is chosen by hashing its
// candidate id modulo the roster length, so reordering or removing an
// existing entry would repoint every persona already cast against it. New
// voices may only be appended.
var defaultTTSVoices = []string{
	"Zephyr", "Puck", "Charon", "Kore", "Fenrir", "Leda", "Orus", "Aoede",
	"Callirrhoe", "Autonoe", "Enceladus", "Iapetus", "Umbriel", "Algieba",
	"Despina", "Erinome", "Algenib", "Rasalgethi", "Laomedeia", "Achernar",
	"Alnilam", "Schedar", "Gacrux", "Pulcherrima", "Achird", "Zubenelgenubi",
	"Vindemiatrix", "Sadachbia", "Sadaltager", "Sulafat",
}

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

	// SpeakerVendor selects which Speaker adapter backs a session:
	// "gemini" or "openai". Defaults to "gemini".
	SpeakerVendor string

	// WebRTCICEServers lists the ICE servers (STUN/TURN URIs) offered to
	// the browser transport during signaling. Defaults to a public STUN
	// server.
	WebRTCICEServers []string
	// TURNURL is the URI of a TURN relay server, used alongside
	// TURNUsername/TURNCredential when NAT traversal needs a relay.
	// Optional; empty means no TURN server is offered.
	TURNURL string
	// TURNUsername authenticates to the TURN server named by TURNURL.
	TURNUsername string
	// TURNCredential authenticates to the TURN server named by TURNURL.
	TURNCredential Secret

	// S3Endpoint overrides the default AWS S3 endpoint, for S3-compatible
	// stores (e.g. MinIO) in local/dev deploys. Optional; empty means the
	// vendor SDK's default AWS endpoint.
	S3Endpoint string
	// S3ForcePathStyle forces path-style S3 addressing
	// (https://host/bucket/key) instead of virtual-hosted-style
	// (https://bucket.host/key), required by most S3-compatible stores.
	S3ForcePathStyle bool

	// WalkbackEnabled toggles the actor's ability to revise ("walk back")
	// a spoken answer already in flight. Defaults to true.
	WalkbackEnabled bool
	// DeferToolEnabled toggles whether the Thinker port may hand back a
	// DEFER verdict at all. Defaults to true.
	DeferToolEnabled bool

	// ConnectTimeout bounds how long the engine waits for a transport
	// connection (WebRTC signaling, vendor session open) to establish
	// before giving up.
	ConnectTimeout time.Duration

	// SpoolDir is where in-flight session artifacts (recording,
	// transcript, event log) are buffered on local disk before upload to
	// S3.
	SpoolDir string

	// MetricsAddr is the address the metrics HTTP endpoint listens on.
	// Optional; empty disables the metrics endpoint.
	MetricsAddr string

	// TTSVoices is the ordered roster of prebuilt Gemini voices a
	// persona's voice is chosen from, by hashing its candidate id modulo
	// len(TTSVoices). Append-only: reordering or removing an entry
	// repoints personas already cast against the existing roster.
	TTSVoices []string
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

// strOr returns the raw value for key, or def if unset or empty. Used for
// optional string fields with a non-empty default.
func (l *loader) strOr(key string, def string) string {
	v, ok := l.lookup(key)
	if !ok || v == "" {
		return def
	}
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

// strList reads key as a comma-separated list, trimming whitespace around
// each element and dropping empty elements, falling back to def if unset or
// empty after trimming.
func (l *loader) strList(key string, def []string) []string {
	v, ok := l.lookup(key)
	if !ok || v == "" {
		return def
	}
	parts := strings.Split(v, ",")
	out := make([]string, 0, len(parts))
	for _, p := range parts {
		p = strings.TrimSpace(p)
		if p == "" {
			continue
		}
		out = append(out, p)
	}
	if len(out) == 0 {
		return def
	}
	return out
}

// boolean reads key as a bool, accepting true/false/1/0/yes/no
// case-insensitively and falling back to def if unset. A present-but-garbage
// value records an Issue and also falls back to def, so a single bad field
// doesn't cascade into unrelated zero-value booleans.
func (l *loader) boolean(key string, def bool) bool {
	v, ok := l.lookup(key)
	if !ok || v == "" {
		return def
	}
	switch strings.ToLower(v) {
	case "true", "1", "yes":
		return true
	case "false", "0", "no":
		return false
	default:
		l.issues = append(l.issues, &Issue{Key: key, Err: fmt.Errorf("%w: %s", ErrInvalid, v)})
		return def
	}
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
// returns a fully populated *Config and a nil error. On failure it returns a
// *LoadError naming every missing or invalid key at once — never just the
// first one — so a half-configured deploy fails with the complete list. The
// returned *Config is non-nil even on failure (every optional field still
// has its default or env-derived value; required fields left unset by the
// failure are the zero value) so a caller can bind flags for a -h listing
// before deciding whether to treat the load as fatal; it must not otherwise
// be used unless the error is nil.
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

		SpeakerVendor: l.strOr("SPEAKER_VENDOR", defaultSpeakerVendor),

		WebRTCICEServers: l.strList("WEBRTC_ICE_SERVERS", defaultWebRTCICEServers),
		TURNURL:          l.str("TURN_URL"),
		TURNUsername:     l.str("TURN_USERNAME"),
		TURNCredential:   NewSecret(l.str("TURN_CREDENTIAL")),

		S3Endpoint:       l.str("S3_ENDPOINT"),
		S3ForcePathStyle: l.boolean("S3_FORCE_PATH_STYLE", false),

		WalkbackEnabled:  l.boolean("WALKBACK_ENABLED", true),
		DeferToolEnabled: l.boolean("DEFER_TOOL_ENABLED", true),

		ConnectTimeout: l.durationS("CONNECT_TIMEOUT_S", defaultConnectTimeout),

		SpoolDir: l.strOr("SPOOL_DIR", defaultSpoolDir),

		MetricsAddr: l.str("METRICS_ADDR"),

		TTSVoices: l.strList("GEMINI_TTS_VOICES", defaultTTSVoices),
	}

	if len(l.issues) > 0 {
		// cfg is still returned alongside the error: every optional field
		// already has its default or env-derived value applied (Load never
		// short-circuits), which lets a caller like cmd/engined register
		// flags — and serve -h — against sensible defaults even when a
		// required key is missing. Required fields left unset by the
		// failure are the zero value; callers must treat a non-nil error as
		// authoritative and not act on cfg until it is nil.
		return cfg, &LoadError{Issues: l.issues}
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

	fs.StringVar(&c.SpeakerVendor, "speaker-vendor", c.SpeakerVendor, "vendor backing the Speaker adapter (gemini or openai)")

	fs.Var(newStringListFlag(&c.WebRTCICEServers), "webrtc-ice-servers", "comma-separated ICE server URIs offered during WebRTC signaling")
	fs.StringVar(&c.TURNURL, "turn-url", c.TURNURL, "TURN relay server URI")
	fs.StringVar(&c.TURNUsername, "turn-username", c.TURNUsername, "TURN relay server username")

	fs.StringVar(&c.S3Endpoint, "s3-endpoint", c.S3Endpoint, "S3 endpoint override, for S3-compatible stores")
	fs.BoolVar(&c.S3ForcePathStyle, "s3-force-path-style", c.S3ForcePathStyle, "force path-style S3 addressing")

	fs.BoolVar(&c.WalkbackEnabled, "walkback-enabled", c.WalkbackEnabled, "allow the actor to revise a spoken answer already in flight")
	fs.BoolVar(&c.DeferToolEnabled, "defer-tool-enabled", c.DeferToolEnabled, "allow the Thinker port to hand back a DEFER verdict")

	fs.DurationVar(&c.ConnectTimeout, "connect-timeout", c.ConnectTimeout, "timeout for establishing a transport connection")

	fs.StringVar(&c.SpoolDir, "spool-dir", c.SpoolDir, "local directory session artifacts are buffered in before upload to S3")

	fs.StringVar(&c.MetricsAddr, "metrics-addr", c.MetricsAddr, "address the metrics HTTP endpoint listens on; empty disables it")

	fs.Var(newStringListFlag(&c.TTSVoices), "gemini-tts-voices", "comma-separated ordered roster of prebuilt Gemini voices")
}

// flagEnvKeys maps every flag BindFlags registers to the environment variable
// it overrides.
//
// It is an explicit table rather than a name transform because several pairs
// do not correspond mechanically: -pregate-deadline carries a Duration while
// PREGATE_DEADLINE_MS is an integer count of milliseconds, and -silence-timeout
// overrides ABANDON_AFTER_S. A transform would silently miss exactly those,
// which is the case this table exists to get right.
// TestEveryRegisteredFlagMapsToAnEnvironmentVariable fails if a flag is added
// without an entry here.
var flagEnvKeys = map[string]string{
	"speaker-model-id":            "SPEAKER_MODEL_ID",
	"thinker-model-id":            "THINKER_MODEL_ID",
	"judge-model-id":              "JUDGE_MODEL_ID",
	"tts-model-id":                "TTS_MODEL_ID",
	"asr-model-id":                "ASR_MODEL_ID",
	"s3-bucket":                   "S3_BUCKET",
	"s3-region":                   "S3_REGION",
	"s3-prefix":                   "S3_PREFIX",
	"control-plane-base-url":      "CONTROL_PLANE_BASE_URL",
	"session-cost-cap-usd":        "SESSION_COST_CAP_USD",
	"pregate-deadline":            "PREGATE_DEADLINE_MS",
	"stall-deadline":              "STALL_DEADLINE_MS",
	"thinker-deadline":            "THINKER_DEADLINE_MS",
	"pause-before-answer-default": "PAUSE_BEFORE_ANSWER_DEFAULT_MS",
	"silence-timeout":             "ABANDON_AFTER_S",
	"session-duration-cap":        "SESSION_DURATION_CAP_S",
	"speaker-vendor":              "SPEAKER_VENDOR",
	"webrtc-ice-servers":          "WEBRTC_ICE_SERVERS",
	"turn-url":                    "TURN_URL",
	"turn-username":               "TURN_USERNAME",
	"s3-endpoint":                 "S3_ENDPOINT",
	"s3-force-path-style":         "S3_FORCE_PATH_STYLE",
	"walkback-enabled":            "WALKBACK_ENABLED",
	"defer-tool-enabled":          "DEFER_TOOL_ENABLED",
	"connect-timeout":             "CONNECT_TIMEOUT_S",
	"spool-dir":                   "SPOOL_DIR",
	"metrics-addr":                "METRICS_ADDR",
	"gemini-tts-voices":           "GEMINI_TTS_VOICES",
}

// ResolveFlagOverrides reports which load issues survive the flags actually
// passed on fs. Call it after fs.Parse, with the error Load returned.
//
// Load runs before flags are parsed, because BindFlags needs a *Config to bind
// defaults from. That ordering means a required key supplied on the command
// line is still recorded as missing by Load. Rejecting the process then would
// advertise a flag in -h that cannot do the one thing its name promises, so an
// issue whose variable was explicitly overridden is dropped here. Issues for
// variables the operator did not override are kept, and a load that produced
// no issues stays nil.
func ResolveFlagOverrides(fs *flag.FlagSet, loadErr error) error {
	if loadErr == nil {
		return nil
	}
	var le *LoadError
	if !errors.As(loadErr, &le) {
		return loadErr
	}
	overridden := make(map[string]bool)
	fs.Visit(func(f *flag.Flag) {
		if key, ok := flagEnvKeys[f.Name]; ok {
			overridden[key] = true
		}
	})
	remaining := make([]*Issue, 0, len(le.Issues))
	for _, issue := range le.Issues {
		if !overridden[issue.Key] {
			remaining = append(remaining, issue)
		}
	}
	if len(remaining) == 0 {
		return nil
	}
	return &LoadError{Issues: remaining}
}

// stringListFlag adapts a *[]string to flag.Value, parsing a comma-separated
// string the same way strList does: trimming whitespace around each element
// and dropping empty elements.
type stringListFlag struct {
	target *[]string
}

// newStringListFlag returns a flag.Value that writes a comma-separated flag
// value into target.
func newStringListFlag(target *[]string) *stringListFlag {
	return &stringListFlag{target: target}
}

// String implements flag.Value, rendering the current value back as a
// comma-separated string.
func (f *stringListFlag) String() string {
	if f == nil || f.target == nil {
		return ""
	}
	return strings.Join(*f.target, ",")
}

// Set implements flag.Value, splitting a comma-separated string into the
// target slice, trimming whitespace and dropping empty elements.
func (f *stringListFlag) Set(v string) error {
	parts := strings.Split(v, ",")
	out := make([]string, 0, len(parts))
	for _, p := range parts {
		p = strings.TrimSpace(p)
		if p == "" {
			continue
		}
		out = append(out, p)
	}
	*f.target = out
	return nil
}
