package fakes

import (
	"context"
	"sync"

	"skillbrew/engine/internal/ports"
)

// FakeFinalizer is a scripted ports.Finalizer. Finalize records every
// FinalizeInput it was given and returns nil (or the error set by
// SetFinalizeError).
//
// Safe for concurrent use.
type FakeFinalizer struct {
	mu  sync.Mutex
	ins []ports.FinalizeInput
	err error
}

// NewFakeFinalizer returns an empty FakeFinalizer.
func NewFakeFinalizer() *FakeFinalizer {
	return &FakeFinalizer{}
}

// Finalize implements ports.Finalizer, recording in.
func (f *FakeFinalizer) Finalize(ctx context.Context, in ports.FinalizeInput) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	f.mu.Lock()
	defer f.mu.Unlock()
	f.ins = append(f.ins, in)
	return f.err
}

// SetFinalizeError makes every subsequent Finalize call return err after
// still recording the input. Pass nil to clear it.
func (f *FakeFinalizer) SetFinalizeError(err error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.err = err
}

// Finalized returns every FinalizeInput passed to Finalize, in call order.
func (f *FakeFinalizer) Finalized() []ports.FinalizeInput {
	f.mu.Lock()
	defer f.mu.Unlock()
	out := make([]ports.FinalizeInput, len(f.ins))
	copy(out, f.ins)
	return out
}

var _ ports.Finalizer = (*FakeFinalizer)(nil)
