package ports

import "context"

// StallBank pre-synthesizes and serves the persona's stall clips and
// opening line, so a defer or a session start never waits on live TTS on
// the latency path. Implementation: internal/stall, built over the TTS
// port.
type StallBank interface {
	// Warm pre-synthesizes every stall clip and the opening line for this
	// session, ahead of the first turn that might need one.
	Warm(ctx context.Context) error
	// PickStall returns one stall clip, its index into the bank (so a
	// caller can avoid immediate repeats), and whether the bank had a
	// clip to give. ok is false when Warm has not completed or produced
	// nothing usable.
	PickStall() (clip PCM16Audio, index int, ok bool)
	// OpeningLine returns the pre-synthesized opening line, and whether it
	// is ready.
	OpeningLine() (PCM16Audio, bool)
}
