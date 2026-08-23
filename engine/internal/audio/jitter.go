package audio

import (
	"sort"
	"time"
)

// JitterConfig tunes the receive buffer.
type JitterConfig struct {
	// TargetFrames is the steady-state depth. Every frame of depth is a
	// frame of added latency, and this sits on the interviewer's question
	// — the half of the conversation the design has least time to spend.
	TargetFrames int
	// MaxFrames bounds growth under a burst, after which the buffer sheds
	// the oldest rather than growing latency without limit.
	MaxFrames int
	// FrameDuration is the expected span of one frame, used to size
	// concealment.
	FrameDuration time.Duration
	// MaxConsecutiveConceal bounds how long concealment continues before
	// the buffer emits silence instead. Concealment repeats the previous
	// frame with decay; repeated far enough it becomes a buzz, which is
	// worse than a gap.
	MaxConsecutiveConceal int
}

// DefaultJitterConfig is three frames — 60 ms at the usual framing.
//
// Deliberately shallow. A conferencing product would run deeper and be right
// to; here the buffer sits on the path between the interviewer finishing a
// question and the persona being allowed to think about it, and the whole
// two-model design is fighting for exactly that time.
func DefaultJitterConfig() JitterConfig {
	return JitterConfig{
		TargetFrames:          3,
		MaxFrames:             12,
		FrameDuration:         20 * time.Millisecond,
		MaxConsecutiveConceal: 5,
	}
}

// JitterBuffer reorders arriving audio by sequence number, absorbs arrival
// jitter, and conceals losses.
//
// Not safe for concurrent use: it belongs to one connection's read loop.
type JitterBuffer struct {
	cfg JitterConfig

	pending []jitterPacket
	// nextSeq is the sequence the buffer will emit next. Zero until the
	// first packet establishes the stream's numbering, which is why it is
	// paired with started rather than assumed to begin at zero.
	nextSeq uint32
	started bool

	lastGood   []byte
	lastRate   int
	concealRun int

	// Stats, read after a session for the media report.
	received  int
	late      int
	duplicate int
	concealed int
	overflow  int
}

type jitterPacket struct {
	seq  uint32
	pcm  []byte
	rate int
	at   time.Time
}

// NewJitterBuffer builds a buffer. A zero-valued config is replaced by the
// default rather than yielding a zero-depth buffer that conceals constantly.
func NewJitterBuffer(cfg JitterConfig) *JitterBuffer {
	if cfg.TargetFrames <= 0 || cfg.MaxFrames <= 0 {
		cfg = DefaultJitterConfig()
	}
	return &JitterBuffer{cfg: cfg}
}

// Push inserts one arriving packet. Duplicates and packets already emitted
// are counted and discarded rather than reordered into the past.
func (j *JitterBuffer) Push(seq uint32, pcm []byte, sampleRateHz int, at time.Time) {
	j.received++
	if !j.started {
		j.nextSeq = seq
		j.started = true
	} else if seqBefore(seq, j.nextSeq) {
		// Arrived after its slot was already emitted. Inserting it would
		// play audio out of order, which is worse than the gap already
		// concealed in its place.
		j.late++
		return
	}
	for i := range j.pending {
		if j.pending[i].seq == seq {
			j.duplicate++
			return
		}
	}

	cp := make([]byte, len(pcm))
	copy(cp, pcm)
	j.pending = append(j.pending, jitterPacket{seq: seq, pcm: cp, rate: sampleRateHz, at: at})
	sort.Slice(j.pending, func(a, b int) bool {
		return seqBefore(j.pending[a].seq, j.pending[b].seq)
	})

	for len(j.pending) > j.cfg.MaxFrames {
		// Shedding the oldest keeps latency bounded. Shedding the newest
		// would keep a queue that is already too deep and stay too deep.
		j.pending = j.pending[1:]
		j.overflow++
		j.nextSeq = j.pending[0].seq
	}
}

// Pop returns the next frame in order, concealing a gap when the frame that
// should come next has not arrived and the buffer is deep enough to believe
// it never will.
//
// ok is false when the buffer is simply not ready yet — during initial fill,
// or when it has run dry. That is not a loss and must not be concealed:
// concealing an empty buffer invents audio out of nothing and, on the mic
// path, invents speech the interviewer did not make.
func (j *JitterBuffer) Pop() (pcm []byte, sampleRateHz int, concealed bool, ok bool) {
	if !j.started {
		return nil, 0, false, false
	}
	if len(j.pending) > 0 && j.pending[0].seq == j.nextSeq {
		p := j.pending[0]
		j.pending = j.pending[1:]
		j.nextSeq++
		j.lastGood = p.pcm
		j.lastRate = p.rate
		j.concealRun = 0
		return p.pcm, p.rate, false, true
	}

	// The next frame is missing. Only call it lost once enough later audio
	// has piled up behind it that it cannot still be in flight.
	if len(j.pending) < j.cfg.TargetFrames {
		return nil, 0, false, false
	}
	j.nextSeq++
	j.concealed++
	j.concealRun++
	return j.conceal(), j.lastRate, true, true
}

// conceal produces a substitute for one lost frame.
//
// It repeats the previous frame at decaying gain. This is deliberately the
// simple form of packet-loss concealment: pitch-synchronous methods sound
// better over long losses, and long losses are not the case worth optimising
// here — a WebRTC path on a working connection loses single frames. Repeating
// a frame indefinitely turns into a buzz, so the run is bounded and then
// gives way to silence, which is honest about having lost the audio.
func (j *JitterBuffer) conceal() []byte {
	if len(j.lastGood) == 0 || j.concealRun > j.cfg.MaxConsecutiveConceal {
		n := int(j.cfg.FrameDuration.Seconds()*float64(max(j.lastRate, 1))) * BytesPerSample
		return make([]byte, n)
	}
	// -6 dB per concealed frame. Reusing the package's own PCM conversion
	// rather than open-coding it here: this function had its own copy, and
	// a second copy of a sample-format decoder is a second place for a
	// byte-order bug to live.
	gain := 1.0
	for range j.concealRun {
		gain *= 0.5
	}
	samples := BytesToFloat(nil, j.lastGood)
	for i := range samples {
		samples[i] *= gain
	}
	return FloatToBytes(nil, samples)
}

// seqBefore reports whether a precedes b in a wrapping sequence space.
//
// The subtraction-then-signed-compare is the standard way to order sequence
// numbers that wrap: comparing them directly would declare every packet after
// a wrap to be ancient, and this buffer would then discard the rest of the
// stream as "late".
//
//nolint:gosec // G115: the wraparound is the algorithm, not an overflow.
func seqBefore(a, b uint32) bool { return int32(a-b) < 0 }

// Depth is how many frames are buffered.
func (j *JitterBuffer) Depth() int { return len(j.pending) }

// JitterStats is one connection's receive-path health, for the media report.
type JitterStats struct {
	Received  int
	Late      int
	Duplicate int
	Concealed int
	Overflow  int
}

// Stats reports the buffer's counters.
func (j *JitterBuffer) Stats() JitterStats {
	return JitterStats{
		Received:  j.received,
		Late:      j.late,
		Duplicate: j.duplicate,
		Concealed: j.concealed,
		Overflow:  j.overflow,
	}
}
