package audio_test

import (
	"testing"
	"time"

	"go.uber.org/goleak"

	"skillbrew/engine/internal/audio"
)

func jitterCfg() audio.JitterConfig {
	c := audio.DefaultJitterConfig()
	c.TargetFrames = 3
	return c
}

func pushSeq(j *audio.JitterBuffer, seq uint32, v byte) {
	j.Push(seq, frameOf(v, 8), 48000, time.Unix(0, 0))
}

// TestOutOfOrderArrivalsAreReplayedInOrder matters because networks reorder
// and audio played out of order is unintelligible in a way that silence is
// not.
func TestOutOfOrderArrivalsAreReplayedInOrder(t *testing.T) {
	defer goleak.VerifyNone(t)

	j := audio.NewJitterBuffer(jitterCfg())
	pushSeq(j, 0, 0)
	pushSeq(j, 2, 2)
	pushSeq(j, 1, 1)
	pushSeq(j, 3, 3)

	for want := range byte(4) {
		pcm, _, concealed, ok := j.Pop()
		if !ok {
			t.Fatalf("frame %d: buffer came up empty", want)
		}
		if concealed {
			t.Fatalf("frame %d was concealed although it had arrived", want)
		}
		if pcm[0] != want {
			t.Fatalf("got frame %d, want %d — arrivals were not reordered", pcm[0], want)
		}
	}
}

// TestALostFrameIsConcealedRatherThanSkipped matters because dropping the
// slot entirely shortens the stream, which walks every later timestamp
// forward and breaks the recording alignment the grading bundle depends on.
func TestALostFrameIsConcealedRatherThanSkipped(t *testing.T) {
	defer goleak.VerifyNone(t)

	j := audio.NewJitterBuffer(jitterCfg())
	pushSeq(j, 0, 100)
	// Sequence 1 never arrives.
	pushSeq(j, 2, 2)
	pushSeq(j, 3, 3)
	pushSeq(j, 4, 4)

	if _, _, _, ok := j.Pop(); !ok {
		t.Fatal("frame 0 did not come out")
	}
	pcm, _, concealed, ok := j.Pop()
	if !ok {
		t.Fatal("the lost slot produced nothing at all")
	}
	if !concealed {
		t.Fatal("the lost slot was not reported as concealed")
	}
	if len(pcm) == 0 {
		t.Fatal("concealment produced an empty frame; the stream would shorten")
	}
	if pcm[0] == 0 {
		t.Fatal("concealment produced silence where the previous frame was available to repeat")
	}
	if got := j.Stats().Concealed; got != 1 {
		t.Fatalf("Concealed = %d, want 1", got)
	}
}

// TestAnEmptyBufferIsNotAConcealedLoss is the distinction that matters most
// here. Concealing an empty buffer invents audio out of nothing, and on the
// mic path that means inventing speech the interviewer did not make.
func TestAnEmptyBufferIsNotAConcealedLoss(t *testing.T) {
	defer goleak.VerifyNone(t)

	j := audio.NewJitterBuffer(jitterCfg())
	pushSeq(j, 0, 1)
	if _, _, _, ok := j.Pop(); !ok {
		t.Fatal("frame 0 did not come out")
	}
	if _, _, concealed, ok := j.Pop(); ok || concealed {
		t.Fatal("a dry buffer produced audio; it must report not-ready instead")
	}
	if got := j.Stats().Concealed; got != 0 {
		t.Fatalf("Concealed = %d, want 0 — running dry is not a loss", got)
	}
}

// TestALateArrivalIsDroppedRatherThanPlayedOutOfOrder matters because a
// packet whose slot has already been concealed cannot be inserted into the
// past; playing it now would repeat audio the listener already heard.
func TestALateArrivalIsDroppedRatherThanPlayedOutOfOrder(t *testing.T) {
	defer goleak.VerifyNone(t)

	j := audio.NewJitterBuffer(jitterCfg())
	for i := range uint32(4) {
		pushSeq(j, i, byte(i))
	}
	for range 4 {
		j.Pop()
	}
	pushSeq(j, 1, 1) // arrives after its slot has gone

	if got := j.Stats().Late; got != 1 {
		t.Fatalf("Late = %d, want 1", got)
	}
	if _, _, _, ok := j.Pop(); ok {
		t.Fatal("a late packet was played out of order")
	}
}

// TestABurstIsBoundedRatherThanGrowingLatencyForever matters because this
// buffer sits on the interviewer's question — the half of the conversation
// the two-model design has least time to spend. Absorbing an unbounded burst
// would trade a glitch for permanent added delay.
func TestABurstIsBoundedRatherThanGrowingLatencyForever(t *testing.T) {
	defer goleak.VerifyNone(t)

	cfg := jitterCfg()
	cfg.MaxFrames = 5
	j := audio.NewJitterBuffer(cfg)
	for i := range uint32(20) {
		pushSeq(j, i, byte(i))
	}
	if got := j.Depth(); got > cfg.MaxFrames {
		t.Fatalf("depth %d exceeds the %d-frame bound", got, cfg.MaxFrames)
	}
	if j.Stats().Overflow == 0 {
		t.Fatal("frames were shed without being counted")
	}
}

// TestDuplicatesAreCountedAndDiscarded matters because retransmission and
// duplication are ordinary on a real path, and playing a frame twice is an
// audible stutter.
func TestDuplicatesAreCountedAndDiscarded(t *testing.T) {
	defer goleak.VerifyNone(t)

	j := audio.NewJitterBuffer(jitterCfg())
	pushSeq(j, 0, 1)
	pushSeq(j, 1, 2)
	pushSeq(j, 1, 2)
	if got := j.Stats().Duplicate; got != 1 {
		t.Fatalf("Duplicate = %d, want 1", got)
	}
	if got := j.Depth(); got != 2 {
		t.Fatalf("depth = %d, want 2 — the duplicate was queued", got)
	}
}
