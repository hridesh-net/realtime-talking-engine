package audio_test

import (
	"math"
	"math/rand"
	"testing"
	"time"

	"go.uber.org/goleak"

	"skillbrew/engine/internal/audio"
)

const vadRate = 48000

var vadFrameDur = 20 * time.Millisecond

// noise renders a frame of quiet room tone at the given RMS-ish amplitude.
// Seeded explicitly so a failure is reproducible.
func noise(rng *rand.Rand, amp float64) []byte {
	n := int(float64(vadRate) * vadFrameDur.Seconds())
	s := make([]float64, n)
	for i := range n {
		s[i] = (rng.Float64()*2 - 1) * amp
	}
	return audio.FloatToBytes(nil, s)
}

// speech renders a frame of voiced-sounding audio: a low fundamental with
// harmonics, which is closer to a vowel than a pure tone and exercises the
// RMS path the detector actually uses.
func speech(phase *float64, amp float64) []byte {
	n := int(float64(vadRate) * vadFrameDur.Seconds())
	s := make([]float64, n)
	for i := range n {
		t := *phase + float64(i)/vadRate
		s[i] = amp * (math.Sin(2*math.Pi*130*t)*0.6 +
			math.Sin(2*math.Pi*260*t)*0.3 +
			math.Sin(2*math.Pi*520*t)*0.1)
	}
	*phase += float64(n) / vadRate
	return audio.FloatToBytes(nil, s)
}

// TestSpeechOnsetFiresOnceWhenTheInterviewerStartsTalking matters because the
// signal drives the vendor's activityStart. The live spike proved audio sent
// outside an activity window is discarded in silence — no bytes, no
// transcription, no error — so a missed onset means the persona never hears
// the question and nothing in the system can tell.
func TestSpeechOnsetFiresOnceWhenTheInterviewerStartsTalking(t *testing.T) {
	defer goleak.VerifyNone(t)

	v := audio.NewVAD(audio.DefaultVADConfig())
	rng := rand.New(rand.NewSource(1))
	now := time.Unix(0, 0)

	// A second of quiet room, to establish the floor.
	for range 50 {
		if _, changed := v.Push(noise(rng, 0.001), vadRate, now); changed {
			t.Fatal("room tone alone must not be reported as speech")
		}
		now = now.Add(vadFrameDur)
	}

	var phase float64
	onsets := 0
	for range 50 {
		started, changed := v.Push(speech(&phase, 0.2), vadRate, now)
		if changed && started {
			onsets++
		}
		now = now.Add(vadFrameDur)
	}

	if onsets != 1 {
		t.Fatalf("got %d onset signals for one utterance, want exactly 1", onsets)
	}
	if !v.Speaking() {
		t.Fatal("the detector should still consider speech in progress")
	}
}

// TestAThinkingPauseDoesNotEndTheTurn is the behaviour D6 turns on. The human
// here is a manager composing a question, and one- and two-second pauses
// mid-question are the normal case, not the exception. An energy detector
// that ends the turn inside one cuts off the very behaviour being assessed —
// and does it worse on code-switched speech, where the pauses are longer.
func TestAThinkingPauseDoesNotEndTheTurn(t *testing.T) {
	defer goleak.VerifyNone(t)

	v := audio.NewVAD(audio.DefaultVADConfig())
	rng := rand.New(rand.NewSource(2))
	now := time.Unix(0, 0)
	for range 50 {
		v.Push(noise(rng, 0.001), vadRate, now)
		now = now.Add(vadFrameDur)
	}

	var phase float64
	for range 20 {
		v.Push(speech(&phase, 0.2), vadRate, now)
		now = now.Add(vadFrameDur)
	}
	if !v.Speaking() {
		t.Fatal("test setup invalid: speech was never detected")
	}

	// A 600 ms pause — well inside a thinking pause.
	for range 30 {
		if _, changed := v.Push(noise(rng, 0.001), vadRate, now); changed {
			t.Fatal("a 600 ms pause ended the turn; the hangover is too short")
		}
		now = now.Add(vadFrameDur)
	}
	if !v.Speaking() {
		t.Fatal("the turn ended inside a thinking pause")
	}
}

// TestSpeechEventuallyEndsAfterTheHangover matters because the offset signal
// is the degraded end-of-turn path: when the Transcriber is gone, this is all
// the engine has, and a detector that never reports an end leaves the session
// waiting forever.
func TestSpeechEventuallyEndsAfterTheHangover(t *testing.T) {
	defer goleak.VerifyNone(t)

	v := audio.NewVAD(audio.DefaultVADConfig())
	rng := rand.New(rand.NewSource(3))
	now := time.Unix(0, 0)
	for range 50 {
		v.Push(noise(rng, 0.001), vadRate, now)
		now = now.Add(vadFrameDur)
	}
	var phase float64
	for range 20 {
		v.Push(speech(&phase, 0.2), vadRate, now)
		now = now.Add(vadFrameDur)
	}

	ended := false
	for range 100 {
		started, changed := v.Push(noise(rng, 0.001), vadRate, now)
		now = now.Add(vadFrameDur)
		if changed && !started {
			ended = true
			break
		}
	}
	if !ended {
		t.Fatal("speech never ended; the degraded end-of-turn path would hang")
	}
}

// TestSpeechDoesNotRaiseTheNoiseFloorMidSentence matters because a floor that
// tracks upward during speech goes deaf to the rest of the sentence and then
// reports an end-of-turn that never happened.
func TestSpeechDoesNotRaiseTheNoiseFloorMidSentence(t *testing.T) {
	defer goleak.VerifyNone(t)

	v := audio.NewVAD(audio.DefaultVADConfig())
	rng := rand.New(rand.NewSource(4))
	now := time.Unix(0, 0)
	for range 50 {
		v.Push(noise(rng, 0.001), vadRate, now)
		now = now.Add(vadFrameDur)
	}
	floorBefore := v.FloorDB()

	var phase float64
	for range 150 { // three seconds of continuous speech
		v.Push(speech(&phase, 0.2), vadRate, now)
		now = now.Add(vadFrameDur)
	}

	if v.FloorDB() > floorBefore+1 {
		t.Fatalf("noise floor climbed from %.1f to %.1f dB during speech", floorBefore, v.FloorDB())
	}
	if !v.Speaking() {
		t.Fatal("the detector went deaf during a continuous sentence")
	}
}

// TestDigitalSilenceIsNeverSpeech matters because a muted microphone produces
// a stream of zeros, and a detector that promoted its own dither to speech
// would open a turn nobody started.
func TestDigitalSilenceIsNeverSpeech(t *testing.T) {
	defer goleak.VerifyNone(t)

	v := audio.NewVAD(audio.DefaultVADConfig())
	now := time.Unix(0, 0)
	silent := make([]byte, vadRate/50*audio.BytesPerSample)
	for range 200 {
		if started, changed := v.Push(silent, vadRate, now); changed || started {
			t.Fatal("digital silence was reported as speech")
		}
		now = now.Add(vadFrameDur)
	}
}
