// Package audio holds the engine's sample-domain code: PCM16 conversion, the
// rational resampler, speech-onset detection, the receive jitter buffer and
// the send ring.
//
// It knows nothing about vendors, transports or sessions — it takes samples
// and returns samples. That is what lets the layering gate allow every
// adapter to import it while the session core may not.
package audio

import (
	"math"
	"time"
)

// BytesPerSample is 2: PCM16, the format every port boundary in this engine
// speaks.
const BytesPerSample = 2

// fullScale is the magnitude of a full-scale PCM16 sample, used to express
// levels in dBFS.
const fullScale = 32768.0

// SilentDB is the level reported for a frame with no energy at all. Real
// silence is negative infinity in dBFS, which propagates NaN through any
// later arithmetic, so it is floored at a value far below any real signal.
const SilentDB = -120.0

// decodeSample reinterprets two little-endian bytes as one signed PCM16
// sample.
//
// The uint16 -> int16 conversion is the reinterpretation, not an accident:
// PCM16 is signed two's-complement on the wire, and reassembling it from
// bytes necessarily goes through the unsigned form. Every such conversion in
// this package funnels through here and encodeSample so the reasoning lives
// in one place rather than being asserted nine times.
//
//nolint:gosec // G115: deliberate two's-complement reinterpretation of PCM16.
func decodeSample(lo, hi byte) int16 {
	return int16(uint16(lo) | uint16(hi)<<8)
}

// encodeSample writes one signed PCM16 sample as two little-endian bytes.
//
//nolint:gosec // G115: deliberate two's-complement reinterpretation of PCM16.
func encodeSample(dst []byte, s int16) {
	u := uint16(s)
	dst[0] = byte(u)
	dst[1] = byte(u >> 8)
}

// BytesToFloat decodes little-endian PCM16 into normalized floats in
// [-1, 1). dst is reused when it has capacity, so a per-frame caller does not
// allocate on the audio path.
func BytesToFloat(dst []float64, pcm []byte) []float64 {
	n := len(pcm) / BytesPerSample
	if cap(dst) < n {
		dst = make([]float64, n)
	}
	dst = dst[:n]
	for i := range n {
		dst[i] = float64(decodeSample(pcm[2*i], pcm[2*i+1])) / fullScale
	}
	return dst
}

// FloatToBytes encodes normalized floats back to little-endian PCM16,
// clipping rather than wrapping.
//
// Clipping matters: a resampler's ringing overshoots slightly past full scale
// on loud material, and an int16 conversion that wraps turns that overshoot
// into a full-amplitude sign flip — an audible click on every loud syllable.
func FloatToBytes(dst []byte, samples []float64) []byte {
	n := len(samples) * BytesPerSample
	if cap(dst) < n {
		dst = make([]byte, n)
	}
	dst = dst[:n]
	for i, v := range samples {
		s := math.Round(v * fullScale)
		if s > math.MaxInt16 {
			s = math.MaxInt16
		}
		if s < math.MinInt16 {
			s = math.MinInt16
		}
		encodeSample(dst[2*i:], int16(s))
	}
	return dst
}

// Duration is how long a PCM16 buffer plays at a sample rate. A non-positive
// rate yields zero rather than dividing by it.
func Duration(pcmBytes int, sampleRateHz int) time.Duration {
	if sampleRateHz <= 0 {
		return 0
	}
	samples := int64(pcmBytes / BytesPerSample)
	return time.Duration(samples * int64(time.Second) / int64(sampleRateHz))
}

// RMSDB is the root-mean-square level of a PCM16 buffer in dBFS.
//
// RMS rather than peak because this feeds speech detection: one sample of
// keyboard clatter has a high peak and almost no energy, and treating it as
// speech onset would start a turn the interviewer did not.
func RMSDB(pcm []byte) float64 {
	n := len(pcm) / BytesPerSample
	if n == 0 {
		return SilentDB
	}
	var sumSq float64
	for i := range n {
		s := float64(decodeSample(pcm[2*i], pcm[2*i+1])) / fullScale
		sumSq += s * s
	}
	rms := math.Sqrt(sumSq / float64(n))
	if rms <= 0 {
		return SilentDB
	}
	db := 20 * math.Log10(rms)
	if db < SilentDB || math.IsNaN(db) {
		return SilentDB
	}
	return db
}
