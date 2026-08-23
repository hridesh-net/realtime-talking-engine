// Package geminitts implements the TTS port over Gemini's speech generation
// endpoint.
//
// It exists to pre-synthesize, not to speak in real time. The persona's live
// voice is the Speaker; this renders the two kinds of audio the engine must
// have ready *before* the moment it needs them — the opening line and the
// stall clips — because both are played on paths with no time to wait for a
// vendor round trip.
//
// The voice must match the Speaker's. A stall clip in a different voice is a
// seam the listener hears instantly, and the contract freezes one voice id for
// exactly this reason.
package geminitts

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strconv"
	"strings"
	"time"

	"skillbrew/engine/internal/ports"
)

// DefaultEndpoint is the generative-language REST base.
const DefaultEndpoint = "https://generativelanguage.googleapis.com/v1beta/models"

// defaultRateHz is the rate Gemini's speech endpoint returns when it does not
// say otherwise. The response normally declares its own rate in the mime type
// and that is preferred; this is the documented fallback.
const defaultRateHz = 24000

// maxResponseBytes bounds one response. A minute of 24 kHz PCM16 is under
// 3 MB, so this is generous for a stall clip and still refuses a response that
// would exhaust a node running many sessions.
const maxResponseBytes = 16 << 20

// TTS renders text to speech.
type TTS struct {
	modelID  string
	apiKey   string
	endpoint string
	http     *http.Client
}

var _ ports.TTS = (*TTS)(nil)

// Option configures a TTS.
type Option func(*TTS)

// WithEndpoint overrides the API base URL, which is what lets this adapter be
// driven against an httptest server offline.
func WithEndpoint(url string) Option { return func(t *TTS) { t.endpoint = url } }

// WithHTTPClient injects the HTTP client.
func WithHTTPClient(c *http.Client) Option { return func(t *TTS) { t.http = c } }

// New builds a TTS client.
func New(modelID, apiKey string, opts ...Option) *TTS {
	t := &TTS{
		modelID:  modelID,
		apiKey:   apiKey,
		endpoint: DefaultEndpoint,
		// Pre-synthesis happens off the latency path, so a generous timeout
		// is the right trade: a clip that arrives late is still useful, and
		// one that is abandoned means the session runs without a stall bank.
		http: &http.Client{Timeout: 60 * time.Second},
	}
	for _, o := range opts {
		o(t)
	}
	return t
}

type wireRequest struct {
	Contents         []wireContent   `json:"contents"`
	GenerationConfig wireGenerateCfg `json:"generationConfig"`
}

type wireContent struct {
	Parts []wirePart `json:"parts"`
}

type wirePart struct {
	Text       string          `json:"text,omitempty"`
	InlineData *wireInlineData `json:"inlineData,omitempty"`
}

type wireInlineData struct {
	MimeType string `json:"mimeType"`
	Data     []byte `json:"data"`
}

type wireGenerateCfg struct {
	ResponseModalities []string      `json:"responseModalities"`
	SpeechConfig       wireSpeechCfg `json:"speechConfig"`
}

type wireSpeechCfg struct {
	VoiceConfig wireVoiceCfg `json:"voiceConfig"`
}

type wireVoiceCfg struct {
	PrebuiltVoiceConfig wirePrebuiltVoice `json:"prebuiltVoiceConfig"`
}

type wirePrebuiltVoice struct {
	VoiceName string `json:"voiceName"`
}

type wireResponse struct {
	Candidates []struct {
		Content struct {
			Parts []wirePart `json:"parts"`
		} `json:"content"`
	} `json:"candidates"`
	Error *struct {
		Message string `json:"message"`
	} `json:"error,omitempty"`
}

// Synthesize renders text in voiceID's voice.
func (t *TTS) Synthesize(ctx context.Context, text string, voiceID string) (ports.PCM16Audio, error) {
	if strings.TrimSpace(text) == "" {
		return ports.PCM16Audio{}, fmt.Errorf("geminitts: refusing to synthesize empty text")
	}
	if voiceID == "" {
		// Silently picking one would produce a stall clip in a different
		// voice from the Speaker, which is a seam the listener hears at
		// once. The contract freezes a voice; an empty one is a bug
		// upstream, not something to paper over here.
		return ports.PCM16Audio{}, fmt.Errorf("geminitts: no voice id; a clip in the wrong voice is worse than none")
	}

	body, err := json.Marshal(wireRequest{
		Contents: []wireContent{{Parts: []wirePart{{Text: text}}}},
		GenerationConfig: wireGenerateCfg{
			ResponseModalities: []string{"AUDIO"},
			SpeechConfig: wireSpeechCfg{
				VoiceConfig: wireVoiceCfg{PrebuiltVoiceConfig: wirePrebuiltVoice{VoiceName: voiceID}},
			},
		},
	})
	if err != nil {
		return ports.PCM16Audio{}, fmt.Errorf("geminitts: marshal: %w", err)
	}

	url := fmt.Sprintf("%s/%s:generateContent", strings.TrimRight(t.endpoint, "/"), t.modelID)
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewReader(body))
	if err != nil {
		return ports.PCM16Audio{}, fmt.Errorf("geminitts: build request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("x-goog-api-key", t.apiKey)

	resp, err := t.http.Do(req)
	if err != nil {
		return ports.PCM16Audio{}, fmt.Errorf("geminitts: call: %w", err)
	}
	defer func() { _ = resp.Body.Close() }()

	payload, err := io.ReadAll(io.LimitReader(resp.Body, maxResponseBytes))
	if err != nil {
		return ports.PCM16Audio{}, fmt.Errorf("geminitts: read: %w", err)
	}
	if resp.StatusCode != http.StatusOK {
		return ports.PCM16Audio{}, fmt.Errorf("geminitts: status %d: %s", resp.StatusCode, truncate(payload))
	}

	var out wireResponse
	if err := json.Unmarshal(payload, &out); err != nil {
		return ports.PCM16Audio{}, fmt.Errorf("geminitts: decode: %w", err)
	}
	if out.Error != nil {
		return ports.PCM16Audio{}, fmt.Errorf("geminitts: vendor error: %s", out.Error.Message)
	}
	for _, c := range out.Candidates {
		for _, p := range c.Content.Parts {
			if p.InlineData == nil || len(p.InlineData.Data) == 0 {
				continue
			}
			return ports.PCM16Audio{
				Samples:      p.InlineData.Data,
				SampleRateHz: rateFromMime(p.InlineData.MimeType),
			}, nil
		}
	}
	return ports.PCM16Audio{}, fmt.Errorf("geminitts: response carried no audio")
}

// rateFromMime reads the sample rate out of a mime type such as
// "audio/L16;codec=pcm;rate=24000".
//
// Parsed rather than assumed: the rate decides how long a clip is believed to
// play, and the engine arms the alarm that ends the persona's turn from that
// duration. Guessing wrong cuts the opening line off or leaves the session
// waiting in silence.
func rateFromMime(mime string) int {
	for _, field := range strings.Split(mime, ";") {
		key, value, ok := strings.Cut(strings.TrimSpace(field), "=")
		if !ok || !strings.EqualFold(key, "rate") {
			continue
		}
		if n, err := strconv.Atoi(strings.TrimSpace(value)); err == nil && n > 0 {
			return n
		}
	}
	return defaultRateHz
}

func truncate(b []byte) string {
	const limit = 300
	if len(b) <= limit {
		return string(b)
	}
	return string(b[:limit]) + "…"
}
