package fakes

import (
	"context"
	"sync"
	"time"

	"skillbrew/engine/internal/ports"
)

// NoteScriptEntry is one scripted response to a RequestNote call.
type NoteScriptEntry struct {
	// Note is delivered on the channel RequestNote returns, unless Miss is
	// set.
	Note ports.Note
	// Miss simulates a Thinker that did not answer before its deadline:
	// RequestNote's returned channel never receives anything, and the
	// caller's own deadline timer is what must move it on.
	Miss bool
}

// FakeThinker is a scripted ports.Thinker. Successive RequestNote calls
// consume a fixed script of notes (or misses) in order, and every other
// call is recorded, so a test can drive the confident, defer→note, and
// defer→deadline-fallback paths deterministically.
//
// Safe for concurrent use.
type FakeThinker struct {
	mu      sync.Mutex
	script  []NoteScriptEntry
	nextIdx int

	started  bool
	persona  ports.PersonaCtx
	partials []string
	notes    []time.Time
	resets   []string
	closed   bool
}

// NewFakeThinker returns a FakeThinker whose successive RequestNote calls
// consume script in order. A RequestNote call past the end of script
// behaves as a Miss.
func NewFakeThinker(script ...NoteScriptEntry) *FakeThinker {
	cp := make([]NoteScriptEntry, len(script))
	copy(cp, script)
	return &FakeThinker{script: cp}
}

// Start implements ports.Thinker, recording persona.
func (t *FakeThinker) Start(ctx context.Context, persona ports.PersonaCtx) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	t.mu.Lock()
	defer t.mu.Unlock()
	t.started = true
	t.persona = persona
	return nil
}

// FeedPartial implements ports.Thinker, recording text.
func (t *FakeThinker) FeedPartial(ctx context.Context, text string) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	t.mu.Lock()
	defer t.mu.Unlock()
	t.partials = append(t.partials, text)
	return nil
}

// RequestNote implements ports.Thinker. It records deadline, then either
// delivers the next scripted Note immediately (buffered, non-blocking) or,
// for a Miss entry or a call past the end of the script, returns a channel
// that never receives — matching the port's contract that a miss is the
// caller's own timer to detect.
func (t *FakeThinker) RequestNote(ctx context.Context, deadline time.Time) <-chan ports.Note {
	t.mu.Lock()
	t.notes = append(t.notes, deadline)
	var entry NoteScriptEntry
	hasEntry := t.nextIdx < len(t.script)
	if hasEntry {
		entry = t.script[t.nextIdx]
		t.nextIdx++
	}
	t.mu.Unlock()

	ch := make(chan ports.Note, 1)
	if hasEntry && !entry.Miss {
		ch <- entry.Note
	}
	return ch
}

// Reset implements ports.Thinker, recording ledgerSummary.
func (t *FakeThinker) Reset(ctx context.Context, ledgerSummary string) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	t.mu.Lock()
	defer t.mu.Unlock()
	t.resets = append(t.resets, ledgerSummary)
	return nil
}

// Close implements ports.Thinker. Releasing resources is not something a
// cancelled ctx should prevent, so Close ignores ctx and always succeeds.
func (t *FakeThinker) Close(ctx context.Context) error {
	t.mu.Lock()
	defer t.mu.Unlock()
	t.closed = true
	return nil
}

// Started reports whether Start has been called.
func (t *FakeThinker) Started() bool {
	t.mu.Lock()
	defer t.mu.Unlock()
	return t.started
}

// Persona returns the PersonaCtx passed to Start.
func (t *FakeThinker) Persona() ports.PersonaCtx {
	t.mu.Lock()
	defer t.mu.Unlock()
	return t.persona
}

// Partials returns every text passed to FeedPartial, in call order.
func (t *FakeThinker) Partials() []string {
	t.mu.Lock()
	defer t.mu.Unlock()
	out := make([]string, len(t.partials))
	copy(out, t.partials)
	return out
}

// NoteDeadlines returns every deadline passed to RequestNote, in call
// order.
func (t *FakeThinker) NoteDeadlines() []time.Time {
	t.mu.Lock()
	defer t.mu.Unlock()
	out := make([]time.Time, len(t.notes))
	copy(out, t.notes)
	return out
}

// Resets returns every ledgerSummary passed to Reset, in call order.
func (t *FakeThinker) Resets() []string {
	t.mu.Lock()
	defer t.mu.Unlock()
	out := make([]string, len(t.resets))
	copy(out, t.resets)
	return out
}

// Closed reports whether Close has been called.
func (t *FakeThinker) Closed() bool {
	t.mu.Lock()
	defer t.mu.Unlock()
	return t.closed
}

var _ ports.Thinker = (*FakeThinker)(nil)
