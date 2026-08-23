package audio

import (
	"sync"
	"time"
)

// SendRing is the bounded outbound audio queue between the session actor and
// the transport.
//
// Policy is drop-oldest, and the direction matters. The persona's audio is
// real-time: if the transport falls behind, the useful thing to send next is
// the newest audio, not a backlog the listener has already been waiting
// through. Dropping the newest instead — the natural result of a plain full
// channel — makes the persona stutter and then jump.
//
// The generation counter is what makes barge-in correct. On interruption the
// actor bumps the generation; every frame already queued belongs to a
// response the human has stopped listening to, and playing it out after the
// interruption is the audible version of the "ghost utterance" bug. Bumping
// is O(1) and does not require draining.
//
// Safe for concurrent use: the actor writes, the transport reads.
type SendRing struct {
	mu     sync.Mutex
	frames []ringFrame
	head   int
	size   int
	cap    int
	gen    uint64
	// dropped counts frames shed under pressure, so a session that
	// stuttered can say so rather than merely sounding bad.
	dropped int
	notify  chan struct{}
}

type ringFrame struct {
	pcm    []byte
	rate   int
	at     time.Time
	gen    uint64
	itemID string
}

// NewSendRing builds a ring holding at most capacity frames. At the usual
// 20 ms framing, capacity is also the queue's depth in 20 ms units, which is
// the number worth reasoning about: 25 frames is half a second of slack.
func NewSendRing(capacity int) *SendRing {
	if capacity < 1 {
		capacity = 1
	}
	return &SendRing{
		frames: make([]ringFrame, capacity),
		cap:    capacity,
		notify: make(chan struct{}, 1),
	}
}

// Push queues one frame, discarding the oldest if the ring is full. It
// reports whether a frame was dropped to make room.
//
// It never blocks. The caller is the session actor's owner goroutine, and a
// queue that can block it is a queue that can stall a live conversation over
// a slow socket.
func (r *SendRing) Push(pcm []byte, sampleRateHz int, itemID string, at time.Time) (dropped bool) {
	// The caller reuses its buffer between frames, so the ring must own a
	// copy. Aliasing here would mean queued audio silently changing content
	// while it waits.
	cp := make([]byte, len(pcm))
	copy(cp, pcm)

	r.mu.Lock()
	if r.size == r.cap {
		r.head = (r.head + 1) % r.cap
		r.size--
		r.dropped++
		dropped = true
	}
	idx := (r.head + r.size) % r.cap
	r.frames[idx] = ringFrame{pcm: cp, rate: sampleRateHz, at: at, gen: r.gen, itemID: itemID}
	r.size++
	r.mu.Unlock()

	select {
	case r.notify <- struct{}{}:
	default:
	}
	return dropped
}

// Pop returns the oldest frame still belonging to the current generation.
//
// Frames from a superseded generation are discarded here rather than at
// bump time: the alternative walks the whole queue while holding the lock,
// on the barge-in path, which is the one path in this system with a hard
// latency budget.
func (r *SendRing) Pop() (pcm []byte, sampleRateHz int, itemID string, at time.Time, ok bool) {
	r.mu.Lock()
	defer r.mu.Unlock()
	for r.size > 0 {
		f := r.frames[r.head]
		r.frames[r.head] = ringFrame{}
		r.head = (r.head + 1) % r.cap
		r.size--
		if f.gen != r.gen {
			continue
		}
		return f.pcm, f.rate, f.itemID, f.at, true
	}
	return nil, 0, "", time.Time{}, false
}

// Ready signals that a frame may be available. It is a hint, not a promise:
// the frame it announced may have been superseded by a generation bump
// before the reader got to it, so a reader must handle Pop returning false.
func (r *SendRing) Ready() <-chan struct{} { return r.notify }

// Bump invalidates everything queued and returns the new generation. Called
// on barge-in and on any other abandonment of an in-flight response.
func (r *SendRing) Bump() uint64 {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.gen++
	return r.gen
}

// Generation is the current generation.
func (r *SendRing) Generation() uint64 {
	r.mu.Lock()
	defer r.mu.Unlock()
	return r.gen
}

// Len is how many frames are queued, including any superseded ones not yet
// popped.
func (r *SendRing) Len() int {
	r.mu.Lock()
	defer r.mu.Unlock()
	return r.size
}

// Dropped is how many frames have been shed under pressure over the ring's
// life.
func (r *SendRing) Dropped() int {
	r.mu.Lock()
	defer r.mu.Unlock()
	return r.dropped
}
