package fakes

import (
	"context"
	"sync"

	"skillbrew/engine/internal/ports"
)

// FakeJudge is a scripted ports.Judge. Verdicts replays a fixed script,
// pre-loaded and ready before the first read — the real Judge's async
// latency is not something an offline test needs to reproduce. Submit
// records every turn submitted for review.
//
// Safe for concurrent use.
type FakeJudge struct {
	verdicts chan ports.Verdict

	mu        sync.Mutex
	submitted []ports.TurnForReview
	submitErr error
}

// NewFakeJudge returns a FakeJudge whose Verdicts channel already holds
// script, in order. script is copied.
func NewFakeJudge(script ...ports.Verdict) *FakeJudge {
	cp := make([]ports.Verdict, len(script))
	copy(cp, script)
	ch := make(chan ports.Verdict, len(cp))
	for _, v := range cp {
		ch <- v
	}
	return &FakeJudge{verdicts: ch}
}

// Submit implements ports.Judge, recording turn (or returning the error set
// by SetSubmitError).
func (j *FakeJudge) Submit(ctx context.Context, turn ports.TurnForReview) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	j.mu.Lock()
	defer j.mu.Unlock()
	j.submitted = append(j.submitted, turn)
	return j.submitErr
}

// Verdicts implements ports.Judge, delivering the scripted verdicts.
func (j *FakeJudge) Verdicts() <-chan ports.Verdict { return j.verdicts }

// SetSubmitError makes every subsequent Submit call return err after still
// recording the turn. Pass nil to clear it.
func (j *FakeJudge) SetSubmitError(err error) {
	j.mu.Lock()
	defer j.mu.Unlock()
	j.submitErr = err
}

// Submitted returns every turn passed to Submit, in call order.
func (j *FakeJudge) Submitted() []ports.TurnForReview {
	j.mu.Lock()
	defer j.mu.Unlock()
	out := make([]ports.TurnForReview, len(j.submitted))
	copy(out, j.submitted)
	return out
}

var _ ports.Judge = (*FakeJudge)(nil)
