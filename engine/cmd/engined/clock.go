package main

import (
	"time"

	"skillbrew/engine/internal/ports"
)

// realClock is the production ports.Clock: a thin wrapper over the standard
// library's wall clock and timers. cmd/engined is the module's sole wiring
// point (see doc comment on this package), so this is the only place a real
// ports.Clock implementation lives — internal/session and every other
// restricted package take a ports.Clock as a dependency and never construct
// one themselves; tests use internal/fakes.FakeClock instead.
type realClock struct{}

// Now implements ports.Clock.
func (realClock) Now() time.Time { return time.Now() }

// NewTimer implements ports.Clock.
func (realClock) NewTimer(d time.Duration) ports.Timer {
	return &realTimer{t: time.NewTimer(d)}
}

// After implements ports.Clock.
func (realClock) After(d time.Duration) <-chan time.Time { return time.After(d) }

var _ ports.Clock = realClock{}

// realTimer adapts *time.Timer to ports.Timer.
type realTimer struct {
	t *time.Timer
}

// C implements ports.Timer.
func (r *realTimer) C() <-chan time.Time { return r.t.C }

// Stop implements ports.Timer.
func (r *realTimer) Stop() bool { return r.t.Stop() }

// Reset implements ports.Timer.
func (r *realTimer) Reset(d time.Duration) bool { return r.t.Reset(d) }

var _ ports.Timer = (*realTimer)(nil)
