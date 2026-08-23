package audio_test

import (
	"testing"
	"time"

	"go.uber.org/goleak"

	"skillbrew/engine/internal/audio"
)

func frameOf(b byte, n int) []byte {
	f := make([]byte, n)
	for i := range f {
		f[i] = b
	}
	return f
}

// TestTheRingDropsTheOldestNotTheNewest matters because the persona's audio
// is real-time. When the transport falls behind, the useful thing to send is
// the newest audio; keeping a backlog the listener has already waited through
// makes the persona stutter and then jump.
func TestTheRingDropsTheOldestNotTheNewest(t *testing.T) {
	defer goleak.VerifyNone(t)

	r := audio.NewSendRing(3)
	at := time.Unix(0, 0)
	for i := range 5 {
		r.Push(frameOf(byte(i), 4), 24000, "item-1", at)
	}
	if got := r.Dropped(); got != 2 {
		t.Fatalf("Dropped() = %d, want 2", got)
	}

	var seen []byte
	for {
		pcm, _, _, _, ok := r.Pop()
		if !ok {
			break
		}
		seen = append(seen, pcm[0])
	}
	// Frames 0 and 1 were shed; 2, 3 and 4 survive, in order.
	want := []byte{2, 3, 4}
	if len(seen) != len(want) {
		t.Fatalf("popped %v, want %v", seen, want)
	}
	for i := range want {
		if seen[i] != want[i] {
			t.Fatalf("popped %v, want %v — the ring kept the wrong end of the queue", seen, want)
		}
	}
}

// TestABumpInvalidatesEverythingQueued is the barge-in property. Audio queued
// for a response the human has stopped listening to must not play out after
// the interruption — that is the audible form of the ghost-utterance bug the
// timer generation counter exists to prevent elsewhere.
func TestABumpInvalidatesEverythingQueued(t *testing.T) {
	defer goleak.VerifyNone(t)

	r := audio.NewSendRing(8)
	at := time.Unix(0, 0)
	for i := range 5 {
		r.Push(frameOf(byte(i), 4), 24000, "item-1", at)
	}

	r.Bump()

	if _, _, _, _, ok := r.Pop(); ok {
		t.Fatal("a frame from the superseded response survived the barge-in")
	}

	// The ring is still usable for the next response.
	r.Push(frameOf(99, 4), 24000, "item-2", at)
	pcm, _, itemID, _, ok := r.Pop()
	if !ok || pcm[0] != 99 || itemID != "item-2" {
		t.Fatal("the ring did not accept audio for the response after the barge-in")
	}
}

// TestTheRingCopiesWhatItIsGiven matters because the caller reuses its frame
// buffer between frames — the resampler explicitly returns a buffer it will
// overwrite. Aliasing would mean queued audio silently changing content while
// it waits its turn.
func TestTheRingCopiesWhatItIsGiven(t *testing.T) {
	defer goleak.VerifyNone(t)

	r := audio.NewSendRing(4)
	shared := frameOf(7, 4)
	r.Push(shared, 24000, "item-1", time.Unix(0, 0))

	for i := range shared {
		shared[i] = 42
	}

	pcm, _, _, _, ok := r.Pop()
	if !ok {
		t.Fatal("nothing queued")
	}
	if pcm[0] != 7 {
		t.Fatalf("queued frame changed under the ring: got %d, want 7", pcm[0])
	}
}

// TestReadyIsAHintAndPopMayStillComeUpEmpty pins the contract a reader has to
// honour: a generation bump between the signal and the read leaves the
// announced frame invalid, and a reader that assumed Ready meant a frame
// would block forever.
func TestReadyIsAHintAndPopMayStillComeUpEmpty(t *testing.T) {
	defer goleak.VerifyNone(t)

	r := audio.NewSendRing(4)
	r.Push(frameOf(1, 4), 24000, "item-1", time.Unix(0, 0))

	select {
	case <-r.Ready():
	default:
		t.Fatal("Ready did not signal after a push")
	}

	r.Bump()
	if _, _, _, _, ok := r.Pop(); ok {
		t.Fatal("Pop returned a superseded frame")
	}
}
