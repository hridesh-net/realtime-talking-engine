package stall_test

import (
	"context"
	"errors"
	"io"
	"log/slog"
	"sync"
	"testing"
	"time"

	"go.uber.org/goleak"

	"skillbrew/engine/internal/ports"
	"skillbrew/engine/internal/stall"
)

func quietLogger() *slog.Logger { return slog.New(slog.NewTextHandler(io.Discard, nil)) }

// scriptedTTS renders whatever it is told to, or fails for chosen texts.
type scriptedTTS struct {
	mu      sync.Mutex
	failFor map[string]bool
	calls   []string
	voices  []string
	rateHz  int
	sampleN int
	failAll bool
	// failOnce fails a text exactly once, then succeeds — a transient
	// vendor fault, which is what the retry exists for.
	failOnce map[string]bool
}

func newScriptedTTS() *scriptedTTS {
	return &scriptedTTS{failFor: map[string]bool{}, rateHz: 24000, sampleN: 480}
}

func (s *scriptedTTS) Synthesize(_ context.Context, text, voiceID string) (ports.PCM16Audio, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.calls = append(s.calls, text)
	s.voices = append(s.voices, voiceID)
	if s.failAll || s.failFor[text] {
		return ports.PCM16Audio{}, errors.New("scripted failure")
	}
	if s.failOnce[text] {
		delete(s.failOnce, text)
		return ports.PCM16Audio{}, errors.New("scripted transient failure")
	}
	return ports.PCM16Audio{Samples: make([]byte, s.sampleN), SampleRateHz: s.rateHz}, nil
}

func (s *scriptedTTS) rendered() []string {
	s.mu.Lock()
	defer s.mu.Unlock()
	out := make([]string, len(s.calls))
	copy(out, s.calls)
	return out
}

func (s *scriptedTTS) usedVoices() []string {
	s.mu.Lock()
	defer s.mu.Unlock()
	out := make([]string, len(s.voices))
	copy(out, s.voices)
	return out
}

var phrases = []string{"Let me think.", "Good question.", "Hmm, one moment."}

// TestWarmRendersEveryClipInTheContractsVoice matters because the whole point
// of the bank is that nothing is synthesized on the latency path — and because
// a clip in the wrong voice is a seam the listener hears at once.
func TestWarmRendersEveryClipInTheContractsVoice(t *testing.T) {
	defer goleak.VerifyNone(t)

	tts := newScriptedTTS()
	b := stall.New(tts, "Algenib", "Hi, I'm Mateo.", phrases, quietLogger())
	if err := b.Warm(context.Background()); err != nil {
		t.Fatalf("warm: %v", err)
	}

	if got := len(tts.rendered()); got != len(phrases)+1 {
		t.Fatalf("rendered %d clips, want %d phrases plus the opening line", got, len(phrases))
	}
	for _, v := range tts.usedVoices() {
		if v != "Algenib" {
			t.Fatalf("clip rendered in voice %q, want the contract's Algenib", v)
		}
	}
	if _, ok := b.OpeningLine(); !ok {
		t.Fatal("no opening line after a successful warm")
	}
	if got := b.Clips(); got != len(phrases) {
		t.Fatalf("Clips() = %d, want %d", got, len(phrases))
	}
}

// TestOneFailedPhraseDegradesTheBankRatherThanFailingTheWarm matters because a
// session with three stall clips instead of six is materially fine, and
// refusing to open an interview over one unrendered phrase is not.
func TestOneFailedPhraseDegradesTheBankRatherThanFailingTheWarm(t *testing.T) {
	defer goleak.VerifyNone(t)

	tts := newScriptedTTS()
	tts.failFor["Good question."] = true
	b := stall.New(tts, "Algenib", "Hi.", phrases, quietLogger())

	if err := b.Warm(context.Background()); err != nil {
		t.Fatalf("warm failed over one unrenderable phrase: %v", err)
	}
	if got := b.Clips(); got != len(phrases)-1 {
		t.Fatalf("Clips() = %d, want %d", got, len(phrases)-1)
	}
	if _, _, ok := b.PickStall(); !ok {
		t.Fatal("a partly-warmed bank must still serve the clips it did get")
	}
}

// TestAFailedOpeningLineIsReported matters because without it the session has
// nothing to open with, which is a different class of problem from a missing
// stall phrase — and the caller's own failure classification, not this
// package, decides what it costs.
func TestAFailedOpeningLineIsReported(t *testing.T) {
	defer goleak.VerifyNone(t)

	tts := newScriptedTTS()
	tts.failFor["Hi."] = true
	b := stall.New(tts, "Algenib", "Hi.", phrases, quietLogger())

	if err := b.Warm(context.Background()); err == nil {
		t.Fatal("a failed opening line was not reported")
	}
	if _, ok := b.OpeningLine(); ok {
		t.Fatal("the bank claims an opening line it never rendered")
	}
}

// TestSuccessiveStallsDoNotRepeatImmediately matters because a persona that
// says "let me think about that" twice in a row sounds like a recording, which
// is precisely the illusion the stall bank exists to protect.
func TestSuccessiveStallsDoNotRepeatImmediately(t *testing.T) {
	defer goleak.VerifyNone(t)

	tts := newScriptedTTS()
	b := stall.New(tts, "Algenib", "Hi.", phrases, quietLogger())
	if err := b.Warm(context.Background()); err != nil {
		t.Fatalf("warm: %v", err)
	}

	_, first, _ := b.PickStall()
	_, second, _ := b.PickStall()
	if first == second {
		t.Fatalf("two successive stalls both returned clip %d; the persona sounds like a recording", first)
	}
}

// TestAnUnwarmedBankServesNothingRatherThanSilence matters because the caller
// distinguishes "no clip" from "a clip of length zero": the first degrades to
// a text-estimated turn, the second would end the persona's turn instantly.
func TestAnUnwarmedBankServesNothingRatherThanSilence(t *testing.T) {
	defer goleak.VerifyNone(t)

	b := stall.New(newScriptedTTS(), "Algenib", "Hi.", phrases, quietLogger())
	if _, _, ok := b.PickStall(); ok {
		t.Fatal("an unwarmed bank served a stall clip")
	}
	if _, ok := b.OpeningLine(); ok {
		t.Fatal("an unwarmed bank served an opening line")
	}
}

// TestNoTTSIsAnErrorNotASilentEmptyBank matters because a bank that warmed
// "successfully" with nothing in it looks healthy and produces silence.
func TestNoTTSIsAnErrorNotASilentEmptyBank(t *testing.T) {
	defer goleak.VerifyNone(t)

	b := stall.New(nil, "Algenib", "Hi.", phrases, quietLogger())
	if err := b.Warm(context.Background()); err == nil {
		t.Fatal("warming with no TTS reported success")
	}
}

// TestClipsAreRenderedConcurrently matters because Warm runs inside the
// session's connect budget. Serially, a persona with six stall phrases plus an
// opening line is seven vendor round trips deep before an interview can start
// — which is exactly how the first live run of this code blew a 15-second
// connect timeout.
func TestClipsAreRenderedConcurrently(t *testing.T) {
	defer goleak.VerifyNone(t)

	tts := newBlockingTTS(len(phrases) + 1)
	b := stall.New(tts, "Algenib", "Hi.", phrases, quietLogger())

	done := make(chan error, 1)
	go func() { done <- b.Warm(context.Background()) }()

	// Every clip must be in flight at once. If Warm were serial this would
	// never reach the full count and the test would time out.
	tts.waitAllInFlight(t)
	tts.releaseAll()

	if err := <-done; err != nil {
		t.Fatalf("warm: %v", err)
	}
}

// TestATransientFailureIsRetried matters because pre-synthesis is off the
// latency path, so a retry costs nothing a listener can hear — and the vendor
// was observed returning a bare 500 "please retry" during the first live warm.
func TestATransientFailureIsRetried(t *testing.T) {
	defer goleak.VerifyNone(t)

	tts := newScriptedTTS()
	tts.failOnce = map[string]bool{"Good question.": true}
	b := stall.New(tts, "Algenib", "Hi.", phrases, quietLogger())

	if err := b.Warm(context.Background()); err != nil {
		t.Fatalf("warm: %v", err)
	}
	if got := b.Clips(); got != len(phrases) {
		t.Fatalf("Clips() = %d, want %d: a transient failure lost a clip that a retry would have got",
			got, len(phrases))
	}
}

// blockingTTS holds every call until released, so a test can observe how many
// are in flight at once.
type blockingTTS struct {
	want     int
	mu       sync.Mutex
	inFlight int
	release  chan struct{}
}

func newBlockingTTS(want int) *blockingTTS {
	return &blockingTTS{want: want, release: make(chan struct{})}
}

func (b *blockingTTS) Synthesize(_ context.Context, _, _ string) (ports.PCM16Audio, error) {
	b.mu.Lock()
	b.inFlight++
	b.mu.Unlock()
	<-b.release
	return ports.PCM16Audio{Samples: make([]byte, 480), SampleRateHz: 24000}, nil
}

func (b *blockingTTS) waitAllInFlight(t *testing.T) {
	t.Helper()
	for range 5000 {
		b.mu.Lock()
		n := b.inFlight
		b.mu.Unlock()
		if n >= b.want {
			return
		}
		time.Sleep(time.Millisecond)
	}
	b.mu.Lock()
	n := b.inFlight
	b.mu.Unlock()
	close(b.release)
	t.Fatalf("only %d of %d clips were in flight at once; Warm is serial", n, b.want)
}

func (b *blockingTTS) releaseAll() { close(b.release) }
