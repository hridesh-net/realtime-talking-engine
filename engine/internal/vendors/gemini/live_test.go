//go:build live

package gemini_test

import (
	"context"
	"testing"
	"time"

	"skillbrew/engine/internal/config"
	"skillbrew/engine/internal/ports"
	"skillbrew/engine/internal/vendors/gemini"
)

// Live tests call the real vendor and cost money, so they sit behind the
// `live` build tag and run only under `scripts/check.sh --live`, matching the
// convention the Python side already uses.

// liveSpeaker builds a Speaker from the real configuration.
//
// Through internal/config rather than os.Getenv, for the reason the layering
// gate enforces: only internal/config reads the environment. It also means the
// live test exercises the same configuration path production does, so a
// mis-declared variable fails here rather than on a deployment.
func liveSpeaker(t *testing.T) *gemini.Speaker {
	t.Helper()
	// Load returns a usable Config alongside any error, so a missing
	// unrelated variable does not prevent a live Speaker test from running.
	cfg, _ := config.LoadFromEnv()
	if cfg == nil || cfg.GeminiAPIKey.IsZero() || cfg.SpeakerModelID == "" {
		t.Skip("GEMINI_API_KEY and SPEAKER_MODEL_ID must be configured for live tests")
	}
	return gemini.New(cfg.SpeakerModelID, cfg.GeminiAPIKey.Reveal(), quietLogger())
}

// TestLiveStartCompletesSetupPromptly is the one that matters operationally:
// Start runs inside the session's connect budget, and a Start that takes
// longer than it fails the whole interview before it begins.
func TestLiveStartCompletesSetupPromptly(t *testing.T) {
	sp := liveSpeaker(t)

	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	start := time.Now()
	sess, err := sp.Start(ctx, ports.SessionCfg{
		SessionID:    "live-1",
		SystemPrompt: "You are a candidate in a job interview. Answer briefly.",
		VoiceID:      "Algenib",
	})
	elapsed := time.Since(start)
	if err != nil {
		t.Fatalf("start after %v: %v", elapsed, err)
	}
	defer func() { _ = sess.Close(context.Background()) }()

	t.Logf("setup completed in %v", elapsed)
	if elapsed > 10*time.Second {
		t.Fatalf("setup took %v; the connect budget is not that generous", elapsed)
	}
}

// TestLiveASpokenTurnProducesAudioAndATranscript drives one full turn the way
// the engine does: open an activity window with audio, close it to generate,
// and read the normalized events back.
func TestLiveASpokenTurnProducesAudioAndATranscript(t *testing.T) {
	sp := liveSpeaker(t)

	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()

	sess, err := sp.Start(ctx, ports.SessionCfg{
		SessionID:    "live-2",
		SystemPrompt: "You are a candidate in a job interview. Answer in two sentences.",
		VoiceID:      "Algenib",
	})
	if err != nil {
		t.Fatalf("start: %v", err)
	}
	defer func() { _ = sess.Close(context.Background()) }()

	// The engine grounds a response with a note, then asks for it.
	if err := sess.InjectSystemItem(ctx, "The interviewer just asked you to describe your last role."); err != nil {
		t.Fatalf("inject: %v", err)
	}
	if err := sess.CreateResponse(ctx, ports.ResponseDirectives{MinSentences: 1, MaxSentences: 3}); err != nil {
		t.Fatalf("create response: %v", err)
	}

	var audioBytes, transcriptChars int
	deadline := time.After(45 * time.Second)
	for {
		select {
		case ev, ok := <-sess.Events():
			if !ok {
				t.Fatal("event stream closed before the turn finished")
			}
			switch e := ev.(type) {
			case ports.AudioDelta:
				audioBytes += len(e.Frame.PCM)
				if e.ItemID == "" {
					t.Fatal("AudioDelta carried no ItemID; playout heartbeats could not match it")
				}
			case ports.OutputTranscriptDelta:
				transcriptChars += len(e.Text)
			case ports.SpeakerError:
				if e.Fatal {
					t.Fatalf("fatal speaker error: %s", e.Message)
				}
				t.Logf("non-fatal speaker error: %s (%s)", e.Message, e.Code)
			case ports.ResponseDone:
				t.Logf("turn done: %d audio bytes (%.2fs), %d transcript chars",
					audioBytes, float64(audioBytes)/2/float64(gemini.OutputRateHz), transcriptChars)
				if audioBytes == 0 {
					t.Fatal("the persona produced no audio")
				}
				return
			}
		case <-deadline:
			t.Fatalf("no ResponseDone within 45s (%d audio bytes, %d transcript chars so far)",
				audioBytes, transcriptChars)
		}
	}
}
