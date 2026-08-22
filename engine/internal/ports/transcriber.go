package ports

import "context"

// Partial is one incremental transcription result for the human
// interviewer's in-progress utterance. Final marks end-of-utterance; the
// session actor closes the interviewer utterance on the first Final
// partial (or the Speaker's own end-of-turn VAD, whichever the actor is
// wired to trust).
type Partial struct {
	Text   string
	Final  bool
	ItemID string
}

// Transcriber runs an independent transcription stream over the human's
// mic audio, separate from any input transcription the Speaker vendor may
// also produce. Its partials drive the pre-gate and feed the Thinker.
type Transcriber interface {
	// Start opens a transcription stream for one session.
	Start(ctx context.Context) error
	// SendAudio streams one decoded mic frame to the transcriber.
	SendAudio(ctx context.Context, frame Frame) error
	// Partials returns the incremental transcription stream. Closed when
	// the transcriber session ends.
	Partials() <-chan Partial
	// Close ends the transcription stream and releases resources.
	Close(ctx context.Context) error
}
