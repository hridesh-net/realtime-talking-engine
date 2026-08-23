package audio_test

import (
	"math"
	"slices"
	"testing"
	"time"

	"go.uber.org/goleak"

	"skillbrew/engine/internal/audio"
)

// tapsPerPhaseTest mirrors the resampler's own filter length. The test is in
// the external package and cannot see the constant, so a change to one must
// be made in both — hence this comment rather than a silent duplicate.
const tapsPerPhaseTest = 64

// ratio reduces a rate pair to the interpolation and decimation factors the
// resampler itself uses.
func ratio(inRate, outRate int) (l, m int) {
	a, b := inRate, outRate
	for b != 0 {
		a, b = b, a%b
	}
	return outRate / a, inRate / a
}

// tone renders a sine at freqHz for d, as PCM16 at rate.
func tone(freqHz float64, rate int, d time.Duration, amp float64) []byte {
	n := int(float64(rate) * d.Seconds())
	s := make([]float64, n)
	for i := range n {
		s[i] = amp * math.Sin(2*math.Pi*freqHz*float64(i)/float64(rate))
	}
	return audio.FloatToBytes(nil, s)
}

// measureSNR resamples a tone and compares the result against an ideal tone
// generated directly at the output rate, ignoring the filter's group delay
// and its startup transient.
//
// It reports dB of signal over error. This is the number the resampler's
// quality bar is stated in, measured rather than asserted.
func measureSNR(t *testing.T, freqHz float64, inRate, outRate int) float64 {
	t.Helper()

	r, err := audio.NewResampler(inRate, outRate)
	if err != nil {
		t.Fatalf("new resampler: %v", err)
	}

	// One second, fed 20 ms at a time — the real frame cadence, so this
	// also exercises the streaming history across 50 frame boundaries.
	const dur = time.Second
	in := tone(freqHz, inRate, dur, 0.5)
	frameBytes := inRate / 50 * audio.BytesPerSample

	var got []byte
	for off := 0; off+frameBytes <= len(in); off += frameBytes {
		got = append(got, r.Process(in[off:off+frameBytes])...)
	}
	gotF := audio.BytesToFloat(nil, got)

	// The prototype filter is tapsPerPhase*L long and delays by half of it,
	// measured on the interpolated L*inRate grid. Converting that to output
	// samples divides by M. Assuming a fixed delay instead is wrong for
	// every ratio but 1:1 — and wrong in a way that looks like the
	// resampler failing rather than the measurement failing.
	// The delay is fractional in output samples for most ratios, so it is
	// carried as a float. Rounding it to an integer makes an ideal
	// resampler look like a broken one: at 1 kHz a 0.75-sample error alone
	// reads as 14 dB SNR, which is what this measurement first reported.
	l, m := ratio(inRate, outRate)
	groupDelay := float64(tapsPerPhaseTest*l-1) / 2 / float64(m)
	// Skip the startup transient generously: the first samples see a
	// zero-filled history and are not representative of steady state.
	skip := int(groupDelay) + outRate/50
	if len(gotF) <= skip*2 {
		t.Fatalf("resampled to %d samples, too few to measure", len(gotF))
	}

	var sigSq, errSq float64
	for i := skip; i < len(gotF)-skip; i++ {
		// The ideal sample at this output index, accounting for delay.
		phase := 2 * math.Pi * freqHz * (float64(i) - groupDelay) / float64(outRate)
		want := 0.5 * math.Sin(phase)
		d := gotF[i] - want
		sigSq += want * want
		errSq += d * d
	}
	if errSq == 0 {
		return math.Inf(1)
	}
	return 10 * math.Log10(sigSq/errSq)
}

// TestTheResamplerClearsSixtyDBOnEveryRatePairTheEngineUses is the D7 quality
// bar, measured rather than asserted.
//
// The rates disagree by design — the browser sends 48 kHz, the Speaker vendor
// speaks 24 kHz, ASR wants 16 kHz — so conversion is unavoidable and its
// quality is a product property, not a detail: aliasing lands on exactly the
// consonants that separate one technical term from another, and this pipeline
// is graded on what a candidate was heard to say.
func TestTheResamplerClearsSixtyDBOnEveryRatePairTheEngineUses(t *testing.T) {
	defer goleak.VerifyNone(t)

	const wantDB = 60.0
	rates := []int{16000, 24000, 48000}

	for _, in := range rates {
		for _, out := range rates {
			if in == out {
				continue
			}
			// 1 kHz sits in the middle of the speech band and well inside
			// every one of these rates' passbands.
			snr := measureSNR(t, 1000, in, out)
			if snr < wantDB {
				t.Errorf("%d -> %d Hz: SNR %.1f dB, want at least %.0f dB", in, out, snr, wantDB)
			} else {
				t.Logf("%d -> %d Hz: SNR %.1f dB", in, out, snr)
			}
		}
	}
}

// TestDownsamplingRejectsContentAboveTheOutputNyquist matters because this is
// the failure that naive sample-dropping produces: a tone above the output's
// Nyquist does not disappear, it folds down into the speech band as a whistle
// that was never in the room.
func TestDownsamplingRejectsContentAboveTheOutputNyquist(t *testing.T) {
	defer goleak.VerifyNone(t)

	// 10 kHz into a 16 kHz output: above its 8 kHz Nyquist, so it must be
	// attenuated, not folded down to 6 kHz.
	r, err := audio.NewResampler(48000, 16000)
	if err != nil {
		t.Fatalf("new resampler: %v", err)
	}
	in := tone(10000, 48000, 500*time.Millisecond, 0.5)

	var out []byte
	frameBytes := 48000 / 50 * audio.BytesPerSample
	for off := 0; off+frameBytes <= len(in); off += frameBytes {
		out = append(out, r.Process(in[off:off+frameBytes])...)
	}

	inDB := audio.RMSDB(in)
	outDB := audio.RMSDB(out[len(out)/4:])
	if outDB > inDB-40 {
		t.Fatalf("out-of-band tone attenuated only %.1f dB (in %.1f, out %.1f); it is aliasing into the speech band",
			inDB-outDB, inDB, outDB)
	}
	t.Logf("10 kHz into 16 kHz attenuated by %.1f dB", inDB-outDB)
}

// TestStreamingFrameByFrameMatchesOneShot matters because the resampler is
// stateful and the audio path calls it 50 times a second. If the filter
// history did not carry across a call, every frame boundary would click.
func TestStreamingFrameByFrameMatchesOneShot(t *testing.T) {
	defer goleak.VerifyNone(t)

	in := tone(1000, 48000, 200*time.Millisecond, 0.5)

	one, err := audio.NewResampler(48000, 24000)
	if err != nil {
		t.Fatalf("new resampler: %v", err)
	}
	whole := append([]byte(nil), one.Process(in)...)

	streamed := make([]byte, 0, len(whole))
	many, err := audio.NewResampler(48000, 24000)
	if err != nil {
		t.Fatalf("new resampler: %v", err)
	}
	frameBytes := 48000 / 50 * audio.BytesPerSample
	for off := 0; off+frameBytes <= len(in); off += frameBytes {
		streamed = append(streamed, many.Process(in[off:off+frameBytes])...)
	}

	if len(streamed) != len(whole) {
		t.Fatalf("streamed %d bytes, one-shot %d: the two must agree sample for sample",
			len(streamed), len(whole))
	}
	for i := range whole {
		if streamed[i] != whole[i] {
			t.Fatalf("streamed and one-shot diverge at byte %d: the filter history is not carrying across frames", i)
		}
	}
}

// TestEqualRatesArePassThrough matters because callers should not have to
// special-case the configuration where no conversion is needed, and a
// pass-through that still ran the filter would spend CPU to degrade audio.
func TestEqualRatesArePassThrough(t *testing.T) {
	defer goleak.VerifyNone(t)

	r, err := audio.NewResampler(24000, 24000)
	if err != nil {
		t.Fatalf("new resampler: %v", err)
	}
	if !r.PassThrough() {
		t.Fatal("equal rates must be a pass-through")
	}
	in := tone(1000, 24000, 20*time.Millisecond, 0.5)
	out := r.Process(in)
	if len(out) != len(in) {
		t.Fatalf("pass-through changed length: %d -> %d", len(in), len(out))
	}
}

// TestAResamplerRefusesNonsenseRates matters because a zero rate reaching the
// filter design would divide by zero at startup, in a constructor that runs
// once per session and would take the session with it.
func TestAResamplerRefusesNonsenseRates(t *testing.T) {
	defer goleak.VerifyNone(t)

	for _, tc := range [][2]int{{0, 24000}, {48000, 0}, {-1, 24000}} {
		if _, err := audio.NewResampler(tc[0], tc[1]); err == nil {
			t.Fatalf("NewResampler(%d, %d) must fail", tc[0], tc[1])
		}
	}
}

// BenchmarkResample20msFrame is the other half of the D7 bar: the conversion
// runs on every frame of a live call, so it has to be far cheaper than the
// 20 ms of audio it processes.
func BenchmarkResample20msFrame(b *testing.B) {
	r, err := audio.NewResampler(48000, 24000)
	if err != nil {
		b.Fatalf("new resampler: %v", err)
	}
	frame := tone(1000, 48000, 20*time.Millisecond, 0.5)
	b.ResetTimer()
	for range b.N {
		r.Process(frame)
	}
}

// TestResamplingOneFrameStaysFarInsideTheRealTimeBudget is the second half of
// the D7 bar, and it is a gate rather than a benchmark because a benchmark
// nobody reads cannot fail.
//
// The budget is per 20 ms frame, on the latency path of a live call, with
// fifty of them a second in each direction. The assertion is 1 ms — some
// fifty times the measured cost — because the point is to catch a change that
// makes conversion cost *orders* more, not to police jitter on a shared CI
// box.
func TestResamplingOneFrameStaysFarInsideTheRealTimeBudget(t *testing.T) {
	defer goleak.VerifyNone(t)

	const iterations = 2000
	budget := time.Millisecond
	if raceEnabled {
		// Not a weaker standard, a different measurement: race
		// instrumentation costs roughly an order of magnitude per memory
		// access, and this function is almost entirely memory access.
		budget = 20 * time.Millisecond
	}
	r, err := audio.NewResampler(48000, 24000)
	if err != nil {
		t.Fatalf("new resampler: %v", err)
	}
	frame := tone(1000, 48000, 20*time.Millisecond, 0.5)

	samples := make([]time.Duration, iterations)
	for i := range iterations {
		start := time.Now()
		r.Process(frame)
		samples[i] = time.Since(start)
	}
	slices.Sort(samples)
	p99 := samples[int(float64(iterations)*0.99)]

	if p99 > budget {
		t.Fatalf("p99 %v per 20 ms frame exceeds the %v budget", p99, budget)
	}
	t.Logf("p99 %v, median %v per 20 ms frame", p99, samples[iterations/2])
}
