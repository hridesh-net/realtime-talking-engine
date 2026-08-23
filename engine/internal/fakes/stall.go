package fakes

import (
	"context"
	"sync"

	"skillbrew/engine/internal/ports"
)

// FakeStallBank is a scripted ports.StallBank. PickStall cycles through a
// fixed set of clips in order, wrapping around; OpeningLine serves a fixed
// clip; Warm records the call (or returns the error set by SetWarmError).
//
// Safe for concurrent use.
type FakeStallBank struct {
	mu         sync.Mutex
	clips      []ports.PCM16Audio
	opening    ports.PCM16Audio
	hasOpening bool
	warmErr    error
	warmed     bool
	warmCalls  int
	nextIdx    int
	pickCalls  int
}

// NewFakeStallBank returns a FakeStallBank whose PickStall calls cycle
// through clips in order, wrapping around, and whose OpeningLine serves
// opening. clips is copied.
func NewFakeStallBank(opening ports.PCM16Audio, clips ...ports.PCM16Audio) *FakeStallBank {
	cp := make([]ports.PCM16Audio, len(clips))
	copy(cp, clips)
	return &FakeStallBank{clips: cp, opening: opening, hasOpening: true}
}

// Warm implements ports.StallBank, recording the call.
func (b *FakeStallBank) Warm(ctx context.Context) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	b.mu.Lock()
	defer b.mu.Unlock()
	b.warmCalls++
	if b.warmErr != nil {
		return b.warmErr
	}
	b.warmed = true
	return nil
}

// PickStall implements ports.StallBank, returning clips in order and
// wrapping around. ok is false when the bank has no clips.
func (b *FakeStallBank) PickStall() (ports.PCM16Audio, int, bool) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.pickCalls++
	if len(b.clips) == 0 {
		return ports.PCM16Audio{}, 0, false
	}
	idx := b.nextIdx % len(b.clips)
	b.nextIdx++
	return b.clips[idx], idx, true
}

// OpeningLine implements ports.StallBank.
func (b *FakeStallBank) OpeningLine() (ports.PCM16Audio, bool) {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.opening, b.hasOpening
}

// SetWarmError makes every subsequent Warm call return err. Pass nil to
// clear it.
func (b *FakeStallBank) SetWarmError(err error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.warmErr = err
}

// Warmed reports whether Warm has ever succeeded.
func (b *FakeStallBank) Warmed() bool {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.warmed
}

// WarmCalls returns how many times Warm was called.
func (b *FakeStallBank) WarmCalls() int {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.warmCalls
}

// PickCalls returns how many times PickStall was called.
func (b *FakeStallBank) PickCalls() int {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.pickCalls
}

var _ ports.StallBank = (*FakeStallBank)(nil)
