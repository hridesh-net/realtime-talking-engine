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
	// PickStall returns one stall clip and the phrase it renders, and
	// whether the bank had a clip to give. The bank avoids an immediate
	// repeat itself; the phrase is returned because the turn record and the
	// Thinker's history must carry what the persona actually said while it
	// bought time. ok is false when Warm has not completed or produced
	// nothing usable.
	PickStall() (clip PCM16Audio, phrase string, ok bool)
	// OpeningLine returns the pre-synthesized opening line, and whether it
	// is ready.
	OpeningLine() (PCM16Audio, bool)
}
