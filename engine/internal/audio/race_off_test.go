//go:build !race

package audio_test

// raceEnabled reports whether the race detector is compiled in.
//
// It exists for the resampler's latency gate. Race instrumentation adds an
// order of magnitude to every memory access, so a budget that describes real
// per-frame cost is simply not measurable under it — and the offline gate runs
// the whole suite with -race. Scaling the budget keeps the check running in
// both modes rather than deleting it in one, which is how a latency gate
// quietly stops existing.
const raceEnabled = false
