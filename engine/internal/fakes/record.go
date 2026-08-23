package fakes

import (
	"context"
	"sync"

	"skillbrew/engine/internal/ports"
)

// PersonaWrite is one recorded FakeRecorder.WritePersona call.
type PersonaWrite struct {
	// ItemID is the response item the frame belongs to.
	ItemID string
	// Frame is the persona audio frame written.
	Frame ports.Frame
}

// FakeRecorder is a scripted ports.Recorder. Every write is recorded rather
// than actually muxed, and Finalize returns a fixed RecordingInfo (or the
// error set by SetFinalizeError). Matching the port's contract that writes
// never block or apply backpressure, every write method here is a plain,
// always-succeeding append under a mutex — there is nothing in a fake for
// "the media path" to ever block on.
//
// Safe for concurrent use.
type FakeRecorder struct {
	mu            sync.Mutex
	humanFrames   []ports.Frame
	personaWrites []PersonaWrite
	truncations   []Truncation
	info          ports.RecordingInfo
	finalizeErr   error
	finalized     bool
}

// NewFakeRecorder returns a FakeRecorder whose Finalize call returns info.
func NewFakeRecorder(info ports.RecordingInfo) *FakeRecorder {
	return &FakeRecorder{info: info}
}

// WriteHuman implements ports.Recorder, recording f.
func (r *FakeRecorder) WriteHuman(f ports.Frame) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.humanFrames = append(r.humanFrames, f)
}

// WritePersona implements ports.Recorder, recording itemID and f.
func (r *FakeRecorder) WritePersona(itemID string, f ports.Frame) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.personaWrites = append(r.personaWrites, PersonaWrite{ItemID: itemID, Frame: f})
}

// TruncatePersona implements ports.Recorder, recording itemID and heardMs.
func (r *FakeRecorder) TruncatePersona(itemID string, heardMs int) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.truncations = append(r.truncations, Truncation{ItemID: itemID, HeardMs: heardMs})
}

// Finalize implements ports.Recorder.
func (r *FakeRecorder) Finalize(ctx context.Context) (ports.RecordingInfo, error) {
	if err := ctx.Err(); err != nil {
		return ports.RecordingInfo{}, err
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	r.finalized = true
	if r.finalizeErr != nil {
		return ports.RecordingInfo{}, r.finalizeErr
	}
	return r.info, nil
}

// SetFinalizeError makes the next Finalize call return err. Pass nil to
// clear it.
func (r *FakeRecorder) SetFinalizeError(err error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.finalizeErr = err
}

// HumanFrames returns every frame passed to WriteHuman, in call order.
func (r *FakeRecorder) HumanFrames() []ports.Frame {
	r.mu.Lock()
	defer r.mu.Unlock()
	out := make([]ports.Frame, len(r.humanFrames))
	copy(out, r.humanFrames)
	return out
}

// PersonaWrites returns every recorded WritePersona call, in call order.
func (r *FakeRecorder) PersonaWrites() []PersonaWrite {
	r.mu.Lock()
	defer r.mu.Unlock()
	out := make([]PersonaWrite, len(r.personaWrites))
	copy(out, r.personaWrites)
	return out
}

// Truncations returns every recorded TruncatePersona call, in call order.
func (r *FakeRecorder) Truncations() []Truncation {
	r.mu.Lock()
	defer r.mu.Unlock()
	out := make([]Truncation, len(r.truncations))
	copy(out, r.truncations)
	return out
}

// Finalized reports whether Finalize has been called.
func (r *FakeRecorder) Finalized() bool {
	r.mu.Lock()
	defer r.mu.Unlock()
	return r.finalized
}

var _ ports.Recorder = (*FakeRecorder)(nil)
