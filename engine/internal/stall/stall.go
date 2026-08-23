// Package stall pre-synthesizes and serves the persona's stall clips and
// opening line.
//
// It exists because both are played on paths with no time to wait for a vendor
// round trip. The opening line starts the moment the interviewer stops talking;
// a stall clip covers the gap while the reasoning model is consulted, and that
// gap is the thing it exists to hide. Synthesizing either on demand would mean
// waiting for TTS in exactly the moment the design cannot afford to.
//
// The clips come from the contract, compiled in Python at cast time, so two
// interviews with the same persona stall in the same words.
package stall

import (
	"context"
	"fmt"
	"log/slog"
	"sync"

	"skillbrew/engine/internal/ports"
)

// Bank holds one session's pre-synthesized audio.
type Bank struct {
	tts     ports.TTS
	voiceID string
	opening string
	phrases []string
	logger  *slog.Logger

	mu         sync.Mutex
	clips      []ports.PCM16Audio
	openClip   ports.PCM16Audio
	hasOpening bool
	lastPick   int
}

var _ ports.StallBank = (*Bank)(nil)

// New builds a bank for one session from its contract's own material.
func New(tts ports.TTS, voiceID, openingLine string, stallPhrases []string, logger *slog.Logger) *Bank {
	if logger == nil {
		logger = slog.Default()
	}
	phrases := make([]string, len(stallPhrases))
	copy(phrases, stallPhrases)
	return &Bank{
		tts:      tts,
		voiceID:  voiceID,
		opening:  openingLine,
		phrases:  phrases,
		logger:   logger,
		lastPick: -1,
	}
}

// Warm pre-synthesizes everything this session might need.
//
// A failure to render one stall phrase is not a failure to warm: the bank
// degrades to the clips it did get, and a session with three stall clips
// instead of six is materially fine. The opening line is different — without it
// the session has nothing to open with — so its failure is reported, and the
// caller's own classification decides what that means.
func (b *Bank) Warm(ctx context.Context) error {
	if b.tts == nil {
		return fmt.Errorf("stall: no TTS configured")
	}

	// Rendered concurrently, because this sits inside the session's connect
	// budget and the clips are independent. Serially, a persona with six
	// stall phrases plus an opening line is seven round trips deep before an
	// interview can start — which is how the first live run of this code
	// blew a 15-second connect timeout.
	rendered := make([]ports.PCM16Audio, len(b.phrases))
	ok := make([]bool, len(b.phrases))
	var wg sync.WaitGroup
	for i, phrase := range b.phrases {
		wg.Add(1)
		go func() {
			defer wg.Done()
			clip, err := b.synthesize(ctx, phrase)
			if err != nil {
				b.logger.Warn("stall: phrase not synthesized", "phrase", phrase, "err", err)
				return
			}
			rendered[i], ok[i] = clip, true
		}()
	}

	var opening ports.PCM16Audio
	var haveOpening bool
	var openErr error
	if b.opening != "" {
		wg.Add(1)
		go func() {
			defer wg.Done()
			clip, err := b.synthesize(ctx, b.opening)
			if err != nil {
				openErr = fmt.Errorf("stall: opening line not synthesized: %w", err)
				return
			}
			opening, haveOpening = clip, true
		}()
	}
	wg.Wait()

	// Kept in contract order rather than completion order, so the same
	// contract always numbers its clips the same way.
	var clips []ports.PCM16Audio
	for i := range rendered {
		if ok[i] {
			clips = append(clips, rendered[i])
		}
	}
	if openErr != nil {
		b.storeLocked(clips, ports.PCM16Audio{}, false)
		return openErr
	}

	b.storeLocked(clips, opening, haveOpening)
	if len(clips) < len(b.phrases) {
		b.logger.Warn("stall: bank warmed partially",
			"got", len(clips), "want", len(b.phrases))
	}
	return nil
}

// synthesizeRetries is how many times one clip is attempted.
//
// Pre-synthesis is off the latency path, so a retry costs nothing the listener
// can hear — and the vendor was observed returning a bare 500 "internal error,
// please retry" during the first live warm of this code. Losing a stall clip
// to a transient fault the vendor itself calls retryable is a poor trade.
const synthesizeRetries = 2

// synthesize renders one clip, retrying a transient failure.
func (b *Bank) synthesize(ctx context.Context, text string) (ports.PCM16Audio, error) {
	var lastErr error
	for attempt := range synthesizeRetries {
		if err := ctx.Err(); err != nil {
			return ports.PCM16Audio{}, err
		}
		clip, err := b.tts.Synthesize(ctx, text, b.voiceID)
		if err == nil {
			return clip, nil
		}
		lastErr = err
		if attempt+1 < synthesizeRetries {
			b.logger.Debug("stall: retrying clip", "err", err)
		}
	}
	return ports.PCM16Audio{}, lastErr
}

func (b *Bank) storeLocked(clips []ports.PCM16Audio, opening ports.PCM16Audio, haveOpening bool) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.clips = clips
	b.openClip = opening
	b.hasOpening = haveOpening
}

// PickStall returns a clip, avoiding the one used last.
//
// Avoiding an immediate repeat is the whole reason the index is returned: a
// persona that says "let me think about that" twice in a row sounds like a
// recording, which is exactly the illusion the stall bank exists to protect.
func (b *Bank) PickStall() (ports.PCM16Audio, int, bool) {
	b.mu.Lock()
	defer b.mu.Unlock()
	if len(b.clips) == 0 {
		return ports.PCM16Audio{}, 0, false
	}
	idx := (b.lastPick + 1) % len(b.clips)
	b.lastPick = idx
	return b.clips[idx], idx, true
}

// OpeningLine returns the pre-synthesized opening line.
func (b *Bank) OpeningLine() (ports.PCM16Audio, bool) {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.openClip, b.hasOpening
}

// Clips reports how many stall clips were successfully rendered, so a session
// running on a partly-warmed bank can say so.
func (b *Bank) Clips() int {
	b.mu.Lock()
	defer b.mu.Unlock()
	return len(b.clips)
}
