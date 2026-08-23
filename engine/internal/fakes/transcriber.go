package fakes

import (
	"context"
	"errors"
	"sync"

	"skillbrew/engine/internal/ports"
)

// ErrTranscriberNotStarted is returned by FakeTranscriber methods that
// require Start to have been called first.
var ErrTranscriberNotStarted = errors.New("fakes: transcriber not started")

// FakeTranscriber is a scripted ports.Transcriber. It replays a fixed tape
// of partials on Partials and records every audio frame sent to it, so a
// test can drive the pre-gate and Thinker paths deterministically.
//
// Safe for concurrent use.
type FakeTranscriber struct {
	tape     []ports.Partial
	partials chan ports.Partial
	closeCh  chan struct{}
	doneCh   chan struct{}

	mu        sync.Mutex
	started   bool
	closed    bool
	sentAudio []ports.Frame
	startErr  error
}

// NewFakeTranscriber returns a FakeTranscriber whose Partials channel
// replays tape, in order, once Start is called. tape is copied; mutating
// the slice after this call has no effect.
func NewFakeTranscriber(tape ...ports.Partial) *FakeTranscriber {
	cp := make([]ports.Partial, len(tape))
	copy(cp, tape)
	return &FakeTranscriber{
		tape:     cp,
		partials: make(chan ports.Partial),
		closeCh:  make(chan struct{}),
		doneCh:   make(chan struct{}),
	}
}

// Start implements ports.Transcriber. It begins replaying the tape onto
// Partials in a background goroutine. Calling Start more than once is a
// no-op after the first call.
func (f *FakeTranscriber) Start(ctx context.Context) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	f.mu.Lock()
	defer f.mu.Unlock()
	if f.startErr != nil {
		return f.startErr
	}
	if f.started {
		return nil
	}
	f.started = true
	go f.feed()
	return nil
}

// SetStartError makes every subsequent Start call return err instead of
// starting the tape-feeding goroutine. Pass nil to clear it.
func (f *FakeTranscriber) SetStartError(err error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.startErr = err
}

// feed replays the tape onto partials in order, stopping early if the
// session is closed. It is the channel's only sender, so it alone closes
// it, and it always closes doneCh on exit so Close can wait for it.
func (f *FakeTranscriber) feed() {
	defer close(f.doneCh)
	defer close(f.partials)
	for _, p := range f.tape {
		select {
		case f.partials <- p:
		case <-f.closeCh:
			return
		}
	}
}

// SendAudio implements ports.Transcriber, recording frame. It returns
// ErrTranscriberNotStarted if Start has not been called.
func (f *FakeTranscriber) SendAudio(ctx context.Context, frame ports.Frame) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	f.mu.Lock()
	defer f.mu.Unlock()
	if !f.started {
		return ErrTranscriberNotStarted
	}
	f.sentAudio = append(f.sentAudio, frame)
	return nil
}

// Partials implements ports.Transcriber, delivering the scripted tape in
// order. It is closed once the tape is exhausted or the session is closed,
// whichever comes first.
func (f *FakeTranscriber) Partials() <-chan ports.Partial {
	return f.partials
}

// Close implements ports.Transcriber. It stops the tape-feeding goroutine
// and waits for it to exit before returning, so no goroutine outlives a
// closed session. Idempotent; safe to call even if Start was never called.
func (f *FakeTranscriber) Close(ctx context.Context) error {
	f.mu.Lock()
	started := f.started
	alreadyClosed := f.closed
	f.closed = true
	f.mu.Unlock()
	if alreadyClosed {
		return nil
	}
	close(f.closeCh)
	if started {
		<-f.doneCh
	}
	return nil
}

// SentAudio returns every frame passed to SendAudio, in call order.
func (f *FakeTranscriber) SentAudio() []ports.Frame {
	f.mu.Lock()
	defer f.mu.Unlock()
	out := make([]ports.Frame, len(f.sentAudio))
	copy(out, f.sentAudio)
	return out
}

// Started reports whether Start has been called.
func (f *FakeTranscriber) Started() bool {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.started
}

// Closed reports whether Close has been called.
func (f *FakeTranscriber) Closed() bool {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.closed
}

var _ ports.Transcriber = (*FakeTranscriber)(nil)
