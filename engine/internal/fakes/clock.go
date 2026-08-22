package fakes

import (
	"sort"
	"sync"
	"time"

	"skillbrew/engine/internal/ports"
)

// FakeClock is a manually-advanced ports.Clock for deterministic timer
// tests. Real timer firing order is not reproducible enough for turn-timing
// tests (plan §13); FakeClock replaces it with an explicit, documented
// order.
//
// Timers due at or before the instant Advance moves to fire in a single
// batch, ordered by due time and, for ties, by creation order (the order
// NewTimer/After was called) — never map order. A timer's tie-break
// position is fixed at creation and unaffected by a later Reset.
//
// FakeClock is safe for concurrent use: all state is guarded by a mutex.
// Timers it creates are likewise safe for concurrent Stop/Reset from a
// goroutine other than the one advancing the clock.
type FakeClock struct {
	mu      sync.Mutex
	now     time.Time
	nextSeq uint64
	timers  []*fakeTimer
	fired   int
	fireLog []uint64
}

// NewFakeClock returns a FakeClock whose current time is start.
func NewFakeClock(start time.Time) *FakeClock {
	return &FakeClock{now: start}
}

// Now returns the clock's current time, as last set by NewFakeClock or
// advanced by Advance.
func (c *FakeClock) Now() time.Time {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.now
}

// NewTimer creates a Timer due at the clock's current time plus d. It fires
// only when a call to Advance moves the clock's time to or past its due
// instant.
func (c *FakeClock) NewTimer(d time.Duration) ports.Timer {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.newTimerLocked(d)
}

// After returns a channel that receives the due time once a call to Advance
// moves the clock's time to or past now+d. It is the Clock-injected
// equivalent of time.After, implemented as NewTimer(d).C().
func (c *FakeClock) After(d time.Duration) <-chan time.Time {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.newTimerLocked(d).C()
}

func (c *FakeClock) newTimerLocked(d time.Duration) *fakeTimer {
	c.nextSeq++
	t := &fakeTimer{
		clock:   c,
		seq:     c.nextSeq,
		due:     c.now.Add(d),
		ch:      make(chan time.Time, 1),
		pending: true,
	}
	c.timers = append(c.timers, t)
	return t
}

// Advance moves the clock's current time forward by d and fires, in order,
// every pending timer whose due instant is now at or before the new time.
// It returns how many timers fired in this call. Advance never fires a
// timer that was cancelled by Stop before this call, and never fires the
// same timer twice.
func (c *FakeClock) Advance(d time.Duration) int {
	c.mu.Lock()
	defer c.mu.Unlock()

	c.now = c.now.Add(d)

	var due []*fakeTimer
	for _, t := range c.timers {
		if t.pending && !t.due.After(c.now) {
			due = append(due, t)
		}
	}
	sort.Slice(due, func(i, j int) bool {
		if due[i].due.Equal(due[j].due) {
			return due[i].seq < due[j].seq
		}
		return due[i].due.Before(due[j].due)
	})

	for _, t := range due {
		t.pending = false
		t.ch <- t.due
		c.fired++
		c.fireLog = append(c.fireLog, t.seq)
	}
	return len(due)
}

// FiredCount returns the cumulative number of timer fires this clock has
// produced across every Advance call. Tests use it to prove that no
// additional timer fired after a cancellation point — capture the count,
// perform the cancel, Advance, and assert the count is unchanged.
func (c *FakeClock) FiredCount() int {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.fired
}

// FireLog returns the creation-order sequence number (see PendingTimer.Seq)
// of every timer this clock has fired, across every Advance call, in the
// exact order Advance fired them.
//
// This is the provable form of the same-instant tie-break rule: each
// Timer's own C() is an independent one-buffered channel, so once Advance
// returns, every due timer's value is already sitting in its channel and
// concurrent goroutines racing to receive from different channels observe
// wake-up order, not fire order — Go's scheduler, not FakeClock, decides
// that race. FireLog sidesteps it by recording the order inside Advance
// itself, under the same lock that decided it.
func (c *FakeClock) FireLog() []uint64 {
	c.mu.Lock()
	defer c.mu.Unlock()
	out := make([]uint64, len(c.fireLog))
	copy(out, c.fireLog)
	return out
}

// PendingTimer describes one timer that has neither fired nor been
// stopped, as returned by Pending.
type PendingTimer struct {
	// Seq is the timer's creation order, used to break ties among timers
	// due at the same instant.
	Seq uint64
	// Due is the instant, on the clock's own timeline, the timer fires.
	Due time.Time
}

// Pending returns every timer that has neither fired nor been stopped, in
// creation order. Tests use it to assert on what is still armed — e.g. that
// a barge-in cancelled every outstanding turn timer, leaving none pending.
func (c *FakeClock) Pending() []PendingTimer {
	c.mu.Lock()
	defer c.mu.Unlock()
	out := make([]PendingTimer, 0, len(c.timers))
	for _, t := range c.timers {
		if t.pending {
			out = append(out, PendingTimer{Seq: t.seq, Due: t.due})
		}
	}
	return out
}

// fakeTimer is FakeClock's ports.Timer implementation. Every field except
// ch is guarded by clock.mu; ch is set once at creation and never
// reassigned, so reading it via C() needs no lock.
type fakeTimer struct {
	clock *FakeClock
	seq   uint64
	due   time.Time
	ch    chan time.Time
	// pending is true from creation until the timer fires or is stopped.
	// Reset sets it back to true, re-arming the timer at its original
	// creation order.
	pending bool
}

// C implements ports.Timer.
func (t *fakeTimer) C() <-chan time.Time {
	return t.ch
}

// Stop implements ports.Timer. It reports whether the timer was pending
// (armed, not yet fired) immediately before this call.
func (t *fakeTimer) Stop() bool {
	t.clock.mu.Lock()
	defer t.clock.mu.Unlock()
	was := t.pending
	t.pending = false
	return was
}

// Reset implements ports.Timer. It reports whether the timer was pending
// immediately before this call, and always re-arms it to fire at the
// clock's current time plus d, at its original creation order.
//
// If the timer had already fired and its fire value was never read off C,
// Reset drains it first — otherwise a second fire into the same
// one-buffered channel would block Advance forever. Real *time.Timer
// pushes this responsibility onto the caller; FakeClock does it here
// because Advance fires timers synchronously under its own lock and a
// blocked send there would wedge the whole clock.
func (t *fakeTimer) Reset(d time.Duration) bool {
	t.clock.mu.Lock()
	defer t.clock.mu.Unlock()
	was := t.pending
	if !was {
		select {
		case <-t.ch:
		default:
		}
	}
	t.due = t.clock.now.Add(d)
	t.pending = true
	return was
}

var _ ports.Clock = (*FakeClock)(nil)
var _ ports.Timer = (*fakeTimer)(nil)
