//go:build live

package openaitx_test

import (
	"context"
	"io"
	"log/slog"
	"os"
	"strings"
	"testing"
	"time"

	"skillbrew/engine/internal/config"
	"skillbrew/engine/internal/ports"
	"skillbrew/engine/internal/vendors/openaitx"
)

// Live tests call the real vendor and cost money, so they sit behind the
// `live` build tag and run only under `scripts/check.sh --live`, matching the
// Gemini adapter and the Python side.

// liveTranscriber builds a Transcriber from the real configuration, through
// internal/config rather than os.Getenv for the reason the layering gate
// enforces: only internal/config reads the environment.
func liveTranscriber(t *testing.T) *openaitx.Transcriber {
	t.Helper()
	cfg, _ := config.LoadFromEnv()
	if cfg == nil || cfg.OpenAIAPIKey.IsZero() || cfg.ASRModelID == "" {
		t.Skip("OPENAI_API_KEY and ASR_MODEL_ID must be configured for live tests")
	}
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	return openaitx.New(cfg.ASRModelID, cfg.OpenAIAPIKey.Reveal(), logger)
}

// TestLiveSetupIsAcceptedAndSpeechIsTranscribed is the one the offline suite
// cannot stand in for: the offline server accepts whatever setup message the
// adapter sends, so only the vendor can say whether the session shape is
// right. It streams a fixed 16 kHz question and expects a final transcript
// naming the outage — the adapter resamples to the vendor's 24 kHz on the way.
func TestLiveSetupIsAcceptedAndSpeechIsTranscribed(t *testing.T) {
	tr := liveTranscriber(t)
	ctx, cancel := context.WithTimeout(context.Background(), 45*time.Second)
	defer cancel()

	start := time.Now()
	if err := tr.Start(ctx); err != nil {
		t.Fatalf("start after %v: %v", time.Since(start), err)
	}
	defer func() { _ = tr.Close(context.Background()) }()
	t.Logf("setup accepted in %v", time.Since(start))

	pcm, err := os.ReadFile("testdata/outage_question_16k.pcm")
	if err != nil {
		t.Fatalf("read fixture: %v", err)
	}
	// One second of trailing silence so the vendor's server VAD commits the
	// utterance instead of waiting for more speech.
	pcm = append(pcm, make([]byte, 16000*2)...)

	const frameBytes = 640 // 20 ms at 16 kHz mono PCM16, the engine's mic frame
	sent := time.Now()
	for off := 0; off < len(pcm); off += frameBytes {
		end := off + frameBytes
		if end > len(pcm) {
			end = len(pcm)
		}
		if err := tr.SendAudio(ctx, ports.Frame{PCM: pcm[off:end], SampleRateHz: 16000}); err != nil {
			t.Fatalf("send audio at %d: %v", off, err)
		}
	}

	var revisions int
	for {
		select {
		case p, ok := <-tr.Partials():
			if !ok {
				t.Fatalf("partials closed before a final arrived (%d revisions seen)", revisions)
			}
			revisions++
			if !p.Final {
				continue
			}
			t.Logf("final %q after %v, %d revisions, item %s", p.Text, time.Since(sent), revisions, p.ItemID)
			if !strings.Contains(strings.ToLower(p.Text), "outage") {
				t.Fatalf("final transcript %q does not mention the outage", p.Text)
			}
			if p.ItemID == "" {
				t.Fatal("final partial carries no item id; the actor keys revisions by it")
			}
			return
		case <-ctx.Done():
			t.Fatalf("no final transcript within budget (%d revisions seen)", revisions)
		}
	}
}
