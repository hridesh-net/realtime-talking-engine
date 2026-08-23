//go:build race

package audio_test

// raceEnabled reports whether the race detector is compiled in. See the
// !race build of this file for why the resampler's latency gate needs it.
const raceEnabled = true
