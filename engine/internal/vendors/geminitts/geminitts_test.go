package geminitts_test

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"go.uber.org/goleak"

	"skillbrew/engine/internal/vendors/geminitts"
)

func verifyNoEngineLeaks(t *testing.T) {
	t.Cleanup(func() {
		goleak.VerifyNone(t,
			goleak.IgnoreTopFunction("net/http.(*connReader).backgroundRead"),
			goleak.IgnoreTopFunction("net/http.(*persistConn).writeLoop"),
			goleak.IgnoreTopFunction("net/http.(*persistConn).readLoop"),
			goleak.IgnoreTopFunction("internal/poll.runtime_pollWait"),
		)
	})
}

// audioReply wraps PCM in the envelope the vendor returns.
func audioReply(mime string, pcm []byte) string {
	return `{"candidates":[{"content":{"parts":[{"inlineData":{"mimeType":"` + mime +
		`","data":"` + base64.StdEncoding.EncodeToString(pcm) + `"}}]}}]}`
}

// TestTheRequestAsksForAudioInTheContractsVoice matters because a clip
// rendered in a different voice from the Speaker is a seam the listener hears
// the instant a stall clip plays.
func TestTheRequestAsksForAudioInTheContractsVoice(t *testing.T) {
	verifyNoEngineLeaks(t)

	got := make(chan map[string]any, 1)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var body map[string]any
		raw, _ := io.ReadAll(r.Body)
		_ = json.Unmarshal(raw, &body)
		got <- body
		_, _ = io.WriteString(w, audioReply("audio/L16;codec=pcm;rate=24000", make([]byte, 480)))
	}))
	t.Cleanup(srv.Close)

	tts := geminitts.New("test-tts", "k", geminitts.WithEndpoint(srv.URL), geminitts.WithHTTPClient(srv.Client()))
	clip, err := tts.Synthesize(context.Background(), "Let me think about that.", "Algenib")
	if err != nil {
		t.Fatalf("synthesize: %v", err)
	}
	if clip.SampleRateHz != 24000 {
		t.Fatalf("rate = %d, want 24000 read from the mime type", clip.SampleRateHz)
	}
	if len(clip.Samples) != 480 {
		t.Fatalf("samples = %d, want 480", len(clip.Samples))
	}

	body := <-got
	cfg := body["generationConfig"].(map[string]any)
	mods := cfg["responseModalities"].([]any)
	if len(mods) != 1 || mods[0] != "AUDIO" {
		t.Fatalf("responseModalities = %v, want [AUDIO]", mods)
	}
	voice := cfg["speechConfig"].(map[string]any)["voiceConfig"].(map[string]any)["prebuiltVoiceConfig"].(map[string]any)["voiceName"]
	if voice != "Algenib" {
		t.Fatalf("voice = %v, want the contract's frozen voice", voice)
	}
}

// TestTheSampleRateIsReadFromTheResponseNotAssumed matters because the engine
// arms the alarm that ends the persona's turn from the clip's believed
// duration. Assuming the wrong rate cuts the opening line off or leaves the
// session waiting in silence.
func TestTheSampleRateIsReadFromTheResponseNotAssumed(t *testing.T) {
	verifyNoEngineLeaks(t)

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_, _ = io.WriteString(w, audioReply("audio/L16;codec=pcm;rate=16000", make([]byte, 320)))
	}))
	t.Cleanup(srv.Close)

	tts := geminitts.New("test-tts", "k", geminitts.WithEndpoint(srv.URL), geminitts.WithHTTPClient(srv.Client()))
	clip, err := tts.Synthesize(context.Background(), "hello", "Algenib")
	if err != nil {
		t.Fatalf("synthesize: %v", err)
	}
	if clip.SampleRateHz != 16000 {
		t.Fatalf("rate = %d, want the 16000 the response declared", clip.SampleRateHz)
	}
}

// TestAnEmptyVoiceIsRefusedRatherThanDefaulted matters because silently
// choosing a voice produces a stall clip that does not match the persona, and
// the contract freezes a voice precisely so that cannot happen.
func TestAnEmptyVoiceIsRefusedRatherThanDefaulted(t *testing.T) {
	verifyNoEngineLeaks(t)

	tts := geminitts.New("test-tts", "k")
	if _, err := tts.Synthesize(context.Background(), "hello", ""); err == nil {
		t.Fatal("an empty voice id was accepted")
	}
}

// TestAResponseWithNoAudioIsAnError matters because a safety block decodes
// perfectly well, and returning its empty clip would leave the session with a
// zero-length opening line it believes is real.
func TestAResponseWithNoAudioIsAnError(t *testing.T) {
	verifyNoEngineLeaks(t)

	for _, body := range []string{
		`{"candidates":[]}`,
		`{"candidates":[{"content":{"parts":[{"text":"I can't do that"}]}}]}`,
		`{"error":{"message":"quota exceeded"}}`,
	} {
		srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
			_, _ = io.WriteString(w, body)
		}))
		tts := geminitts.New("test-tts", "k", geminitts.WithEndpoint(srv.URL), geminitts.WithHTTPClient(srv.Client()))
		if _, err := tts.Synthesize(context.Background(), "hello", "Algenib"); err == nil {
			t.Fatalf("response %q produced no error", body)
		}
		srv.Close()
	}
}

// TestAnHTTPErrorCarriesTheVendorsExplanation matters for the same reason it
// does on the reasoning path: a bad key and a quota refusal both arrive as
// non-200 with the reason in the body.
func TestAnHTTPErrorCarriesTheVendorsExplanation(t *testing.T) {
	verifyNoEngineLeaks(t)

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusTooManyRequests)
		_, _ = io.WriteString(w, `{"error":{"message":"quota exceeded for this project"}}`)
	}))
	t.Cleanup(srv.Close)

	tts := geminitts.New("test-tts", "k", geminitts.WithEndpoint(srv.URL), geminitts.WithHTTPClient(srv.Client()))
	_, err := tts.Synthesize(context.Background(), "hello", "Algenib")
	if err == nil || !strings.Contains(err.Error(), "429") || !strings.Contains(err.Error(), "quota exceeded") {
		t.Fatalf("error = %v, want both the status and the vendor's message", err)
	}
}
