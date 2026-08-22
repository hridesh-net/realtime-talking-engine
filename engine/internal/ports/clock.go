package ports

import "time"

// Timer is a cancellable, one-shot alarm created by Clock. It mirrors
// *time.Timer's usable surface as an interface so a fake implementation can
// give tests deterministic, manually-advanced timer order — real timer
// firing order is not reproducible enough for turn-timing tests.
type Timer interface {
	// C delivers the fire time when the timer expires. Never sent to more
	// than once.
	C() <-chan time.Time
	// Stop prevents the timer from firing. It returns false if the timer
	// already fired or was already stopped.
	Stop() bool
	// Reset changes the timer to fire after duration d, relative to Reset
	// being called. It returns false if the timer already fired or was
	// already stopped.
	Reset(d time.Duration) bool
}

// Clock is the session actor's only source of time. It is injected
// everywhere from day one: internal/session must never call time.Now,
// time.After, or time.NewTimer directly (enforced by internal/arch), so
// that turn timing is deterministic under internal/fakes.FakeClock.
type Clock interface {
	// Now returns the current time.
	Now() time.Time
	// NewTimer creates a Timer that fires after duration d.
	NewTimer(d time.Duration) Timer
	// After returns a channel that receives the time after duration d —
	// the Clock-injected equivalent of time.After.
	After(d time.Duration) <-chan time.Time
}
