package fakes

import (
	"context"
	"sync"

	"skillbrew/engine/internal/ports"
)

// FakeSpeaker is a scripted ports.Speaker. Every session it starts replays
// the same event tape and records every call made on it, so a test can
// drive a whole conversation — confident answer, defer, barge-in, tool
// call — deterministically and then assert on both sides: what the fake
// said (the tape) and what the caller did in response (the recorded
// calls).
//
// Safe for concurrent use.
type FakeSpeaker struct {
	mu       sync.Mutex
	tape     []ports.SpeakerEvent
	sessions []*FakeSpeakerSession
}

// NewFakeSpeaker returns a FakeSpeaker whose sessions replay tape, in
// order, on their Events channel. tape is copied; mutating the slice after
// this call has no effect.
func NewFakeSpeaker(tape ...ports.SpeakerEvent) *FakeSpeaker {
	cp := make([]ports.SpeakerEvent, len(tape))
	copy(cp, tape)
	return &FakeSpeaker{tape: cp}
}

// Start implements ports.Speaker. Each call opens a new FakeSpeakerSession
// replaying this FakeSpeaker's tape from the beginning.
func (f *FakeSpeaker) Start(ctx context.Context, cfg ports.SessionCfg) (ports.SpeakerSession, error) {
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	sess := newFakeSpeakerSession(cfg, f.tape)
	f.mu.Lock()
	f.sessions = append(f.sessions, sess)
	f.mu.Unlock()
	go sess.feed()
	return sess, nil
}

// Sessions returns every FakeSpeakerSession Start has produced, in start
// order.
func (f *FakeSpeaker) Sessions() []*FakeSpeakerSession {
	f.mu.Lock()
	defer f.mu.Unlock()
	out := make([]*FakeSpeakerSession, len(f.sessions))
	copy(out, f.sessions)
	return out
}

// LastSession returns the most recently started FakeSpeakerSession, or nil
// if Start has never been called. Most tests open exactly one session and
// use this to reach it without a type assertion on the ports.SpeakerSession
// Start returned.
func (f *FakeSpeaker) LastSession() *FakeSpeakerSession {
	f.mu.Lock()
	defer f.mu.Unlock()
	if len(f.sessions) == 0 {
		return nil
	}
	return f.sessions[len(f.sessions)-1]
}

// Truncation is one recorded SpeakerSession.Truncate call.
type Truncation struct {
	// ItemID is the vendor item truncated.
	ItemID string
	// HeardMs is how much of that item the caller reported as heard.
	HeardMs int
}

// FakeSpeakerSession is a scripted ports.SpeakerSession. It replays a fixed
// event tape on Events and records every call made on it: injected system
// items, response requests, cancels, and truncations.
//
// Safe for concurrent use: recorded state is guarded by a mutex, and the
// tape-feeding goroutine only ever writes to fields it owns exclusively.
type FakeSpeakerSession struct {
	cfg ports.SessionCfg

	events  chan ports.SpeakerEvent
	closeCh chan struct{}
	doneCh  chan struct{}
	tape    []ports.SpeakerEvent

	mu          sync.Mutex
	closed      bool
	sentAudio   []ports.Frame
	systemItems []string
	responses   []ports.ResponseDirectives
	cancels     int
	truncations []Truncation
}

func newFakeSpeakerSession(cfg ports.SessionCfg, tape []ports.SpeakerEvent) *FakeSpeakerSession {
	return &FakeSpeakerSession{
		cfg:     cfg,
		events:  make(chan ports.SpeakerEvent),
		closeCh: make(chan struct{}),
		doneCh:  make(chan struct{}),
		tape:    tape,
	}
}

// feed replays the tape onto events in order, one at a time, stopping early
// if the session is closed. It is the channel's only sender, so it alone
// closes it, and it always closes doneCh on exit so Close can wait for the
// goroutine to actually stop (no leaked goroutine after Close returns).
func (s *FakeSpeakerSession) feed() {
	defer close(s.doneCh)
	defer close(s.events)
	for _, ev := range s.tape {
		select {
		case s.events <- ev:
		case <-s.closeCh:
			return
		}
	}
}

// Config returns the SessionCfg this session was started with.
func (s *FakeSpeakerSession) Config() ports.SessionCfg {
	return s.cfg
}

// SendAudio implements ports.SpeakerSession, recording frame.
func (s *FakeSpeakerSession) SendAudio(ctx context.Context, frame ports.Frame) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	s.sentAudio = append(s.sentAudio, frame)
	return nil
}

// InjectSystemItem implements ports.SpeakerSession, recording text.
func (s *FakeSpeakerSession) InjectSystemItem(ctx context.Context, text string) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	s.systemItems = append(s.systemItems, text)
	return nil
}

// CreateResponse implements ports.SpeakerSession, recording directives.
func (s *FakeSpeakerSession) CreateResponse(ctx context.Context, directives ports.ResponseDirectives) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	s.responses = append(s.responses, directives)
	return nil
}

// CancelResponse implements ports.SpeakerSession, incrementing the cancel
// count.
func (s *FakeSpeakerSession) CancelResponse(ctx context.Context) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	s.cancels++
	return nil
}

// Truncate implements ports.SpeakerSession, recording itemID and heardMs.
func (s *FakeSpeakerSession) Truncate(ctx context.Context, itemID string, heardMs int) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	s.truncations = append(s.truncations, Truncation{ItemID: itemID, HeardMs: heardMs})
	return nil
}

// Events implements ports.SpeakerSession, delivering the scripted tape in
// order. It is closed once the tape is exhausted or the session is closed,
// whichever comes first.
func (s *FakeSpeakerSession) Events() <-chan ports.SpeakerEvent {
	return s.events
}

// Close implements ports.SpeakerSession. It stops the tape-feeding
// goroutine and waits for it to exit before returning, so no goroutine
// outlives a closed session. Idempotent. Releasing resources is not
// something a cancelled ctx should prevent, so Close ignores ctx and
// always succeeds.
func (s *FakeSpeakerSession) Close(ctx context.Context) error {
	s.mu.Lock()
	alreadyClosed := s.closed
	s.closed = true
	s.mu.Unlock()
	if alreadyClosed {
		return nil
	}
	close(s.closeCh)
	<-s.doneCh
	return nil
}

// SentAudio returns every frame passed to SendAudio, in call order.
func (s *FakeSpeakerSession) SentAudio() []ports.Frame {
	s.mu.Lock()
	defer s.mu.Unlock()
	out := make([]ports.Frame, len(s.sentAudio))
	copy(out, s.sentAudio)
	return out
}

// SystemItems returns every text passed to InjectSystemItem, in call
// order.
func (s *FakeSpeakerSession) SystemItems() []string {
	s.mu.Lock()
	defer s.mu.Unlock()
	out := make([]string, len(s.systemItems))
	copy(out, s.systemItems)
	return out
}

// Responses returns every directives value passed to CreateResponse, in
// call order.
func (s *FakeSpeakerSession) Responses() []ports.ResponseDirectives {
	s.mu.Lock()
	defer s.mu.Unlock()
	out := make([]ports.ResponseDirectives, len(s.responses))
	copy(out, s.responses)
	return out
}

// CancelCount returns how many times CancelResponse was called.
func (s *FakeSpeakerSession) CancelCount() int {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.cancels
}

// Truncations returns every recorded Truncate call, in call order. Tests
// use it to assert truncation ms matches heartbeat-derived heard ms after
// barge-in.
func (s *FakeSpeakerSession) Truncations() []Truncation {
	s.mu.Lock()
	defer s.mu.Unlock()
	out := make([]Truncation, len(s.truncations))
	copy(out, s.truncations)
	return out
}

// Closed reports whether Close has been called.
func (s *FakeSpeakerSession) Closed() bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.closed
}

var _ ports.Speaker = (*FakeSpeaker)(nil)
var _ ports.SpeakerSession = (*FakeSpeakerSession)(nil)
