package audio

import (
	"fmt"
	"math"
)

// tapsPerPhase is the length of each polyphase branch of the resampling
// filter.
//
// 64 is chosen against the standard this engine holds itself to, and the
// number was measured rather than picked: at 32 the stopband rejection near
// the cutoff was only ~23 dB, which is audible aliasing on the exact
// consonants ASR is being asked to distinguish. Cost is 64 multiply-adds per
// output sample regardless of ratio — a few million per second on a stream
// that carries fifty frames a second, which is not where this engine's time
// goes.
const tapsPerPhase = 64

// kaiserBeta shapes the window. 8.0 puts the first sidelobe near -80 dB,
// comfortably below the 60 dB the resampler must clear, so the error budget
// is spent on the transition band rather than on stopband leakage.
const kaiserBeta = 8.0

// Resampler converts a PCM16 stream between two sample rates.
//
// It exists because the three rates in this system disagree by design: the
// browser sends 48 kHz, the Speaker vendor emits and expects 24 kHz, and ASR
// wants 16 kHz. Something has to convert, and doing it by dropping or
// repeating samples — the obvious cheap approach — aliases badly enough to
// hurt recognition accuracy on the exact consonants that distinguish one
// technical term from another.
//
// The implementation is a polyphase rational resampler: upsample by L,
// low-pass, decimate by M, with the filter evaluated only at the samples that
// survive. It is stateful and streaming — consecutive Process calls join
// seamlessly, because the filter history carries across the boundary. A
// stateless per-frame resampler clicks at every frame edge, 50 times a
// second.
//
// Not safe for concurrent use: one Resampler belongs to one direction of one
// stream.
type Resampler struct {
	inRate, outRate int

	// l and m are the interpolation and decimation factors, coprime.
	l, m int

	// coeffs is the prototype low-pass filter, indexed [phase][tap].
	coeffs [][]float64

	// hist holds the tail of the previous input, so a filter window that
	// straddles a frame boundary sees the real samples rather than zeros.
	hist []float64

	// outIndex counts output samples produced since construction, and is
	// what makes the phase continuous across calls. Resetting it per frame
	// would restart the phase and warble.
	outIndex int64
	// inConsumed counts input samples retired from hist.
	inConsumed int64

	// scratch buffers, reused to keep the audio path allocation-free.
	in  []float64
	out []float64
	buf []byte
}

// NewResampler builds a resampler between two rates. Equal rates are legal
// and yield a pass-through, which keeps callers from having to special-case
// the common configuration where no conversion is needed.
func NewResampler(inRate, outRate int) (*Resampler, error) {
	if inRate <= 0 || outRate <= 0 {
		return nil, fmt.Errorf("audio: resampler rates must be positive, got %d -> %d", inRate, outRate)
	}
	g := gcd(inRate, outRate)
	r := &Resampler{
		inRate:  inRate,
		outRate: outRate,
		l:       outRate / g,
		m:       inRate / g,
	}
	if r.l != 1 || r.m != 1 {
		r.coeffs = designPolyphase(r.l, r.m)
		r.hist = make([]float64, tapsPerPhase-1)
		// The priming history sits *before* the stream, at input indices
		// -(K-1)..-1. Starting inConsumed at zero instead would label those
		// zeros as samples 0..K-2 and shift the whole stream by K-1
		// samples relative to its own filter phase — which produces output
		// that is stable, streams seamlessly, and is wrong.
		r.inConsumed = -int64(tapsPerPhase - 1)
	}
	return r, nil
}

// InRate is the rate this resampler consumes.
func (r *Resampler) InRate() int { return r.inRate }

// OutRate is the rate this resampler produces.
func (r *Resampler) OutRate() int { return r.outRate }

// PassThrough reports whether the rates match, so no conversion happens.
func (r *Resampler) PassThrough() bool { return r.l == 1 && r.m == 1 }

// Process converts one buffer of PCM16 and returns the converted PCM16.
//
// The returned slice is owned by the Resampler and is overwritten by the next
// call. Callers that keep it must copy — which is why every caller inside
// this repo hands it straight to a port that copies, rather than storing it.
func (r *Resampler) Process(pcm []byte) []byte {
	if r.PassThrough() {
		return pcm
	}
	r.in = BytesToFloat(r.in, pcm)

	// The working window is the carried history followed by this input, so
	// a filter tap reaching back across the frame boundary reads real audio.
	window := append(r.hist[:len(r.hist):len(r.hist)], r.in...)

	// Output n reads input indices [i-K+1, i] where i = floor(n*M/L), in
	// absolute input-sample coordinates. Produce every output whose window
	// is fully inside what we hold.
	origin := r.inConsumed
	last := origin + int64(len(window)) - 1
	r.out = r.out[:0]
	for {
		i := (r.outIndex * int64(r.m)) / int64(r.l)
		if i > last {
			break
		}
		phase := int((r.outIndex * int64(r.m)) % int64(r.l))
		base := int(i - origin)
		var acc float64
		for k := range tapsPerPhase {
			idx := base - k
			if idx < 0 {
				break
			}
			acc += r.coeffs[phase][k] * window[idx]
		}
		r.out = append(r.out, acc)
		r.outIndex++
	}

	// Retain exactly the samples a future window can still reach back to.
	nextI := (r.outIndex * int64(r.m)) / int64(r.l)
	keepFrom := nextI - int64(tapsPerPhase) + 1
	if keepFrom < origin {
		keepFrom = origin
	}
	if keepFrom > origin+int64(len(window)) {
		keepFrom = origin + int64(len(window))
	}
	r.hist = append(r.hist[:0], window[keepFrom-origin:]...)
	r.inConsumed = keepFrom

	r.buf = FloatToBytes(r.buf, r.out)
	return r.buf
}

// Reset clears the filter history and restarts the phase. Call it between
// unrelated streams; calling it between frames of one stream reintroduces the
// boundary click the history exists to prevent.
func (r *Resampler) Reset() {
	for i := range r.hist {
		r.hist[i] = 0
	}
	r.hist = r.hist[:cap(r.hist)]
	if len(r.hist) > tapsPerPhase-1 {
		r.hist = r.hist[:tapsPerPhase-1]
	}
	r.outIndex = 0
	r.inConsumed = -int64(tapsPerPhase - 1)
}

// designPolyphase builds the windowed-sinc prototype and splits it into L
// phases of tapsPerPhase coefficients each.
//
// The cutoff is the lower of the two Nyquist limits, which is the whole point
// of the filter: decimating without it folds everything above the output's
// Nyquist back down into the audible band, and interpolating without it
// leaves images above the input's.
func designPolyphase(l, m int) [][]float64 {
	n := tapsPerPhase * l
	// Slightly below the theoretical Nyquist limit. A filter cannot fall
	// vertically, so placing the cutoff exactly at Nyquist spends half the
	// transition band above it, where everything folds back into the signal.
	// Pulling it in by 10% buys that rejection for a sliver of the top
	// octave, which for speech is the right trade.
	cutoff := 0.45 / float64(max(l, m))
	center := float64(n-1) / 2

	proto := make([]float64, n)
	i0beta := besselI0(kaiserBeta)
	for i := range n {
		x := float64(i) - center
		proto[i] = 2 * cutoff * sinc(2*cutoff*x)

		// Kaiser window.
		ratio := (float64(i) - center) / center
		arg := 1 - ratio*ratio
		if arg < 0 {
			arg = 0
		}
		proto[i] *= besselI0(kaiserBeta*math.Sqrt(arg)) / i0beta
	}

	// Unity passband gain. Interpolation spreads each input sample across L
	// outputs, so without the L factor the signal drops by 1/L — silence,
	// for any real ratio.
	var sum float64
	for _, c := range proto {
		sum += c
	}
	if sum != 0 {
		scale := float64(l) / sum
		for i := range proto {
			proto[i] *= scale
		}
	}

	phases := make([][]float64, l)
	for p := range l {
		phases[p] = make([]float64, tapsPerPhase)
		for k := range tapsPerPhase {
			// Output at phase p reads the prototype at the offset that
			// lands on the same fractional position, k input samples back.
			idx := k*l + p
			if idx < n {
				phases[p][k] = proto[idx]
			}
		}
	}
	return phases
}

func sinc(x float64) float64 {
	if x == 0 {
		return 1
	}
	px := math.Pi * x
	return math.Sin(px) / px
}

// besselI0 is the zeroth-order modified Bessel function, the Kaiser window's
// shape term. The series converges quickly for the arguments used here.
func besselI0(x float64) float64 {
	sum, term := 1.0, 1.0
	for i := 1; i < 64; i++ {
		term *= (x / 2) * (x / 2) / (float64(i) * float64(i))
		sum += term
		if term < 1e-18*sum {
			break
		}
	}
	return sum
}

func gcd(a, b int) int {
	for b != 0 {
		a, b = b, a%b
	}
	return a
}
