package ports

import "context"

// RecordingInfo describes the bundle Recorder.Finalize produced: enough for
// a Finalizer to locate and describe it in the ingest payload, without
// Recorder itself knowing about Store or SessionIngest.
type RecordingInfo struct {
	// Key is the storage key the muxed recording was (or will be) written
	// to under ports.Store.
	Key string
	// DurationMs is the recording's total duration.
	DurationMs int
	// SilenceFilledMs is how much silence Recorder inserted to cover
	// dropped or overflowed frames rather than apply backpressure.
	SilenceFilledMs int
	// Degraded is true when Recorder had to silence-fill or drop frames
	// instead of producing the ideal frame-perfect bundle. A degraded
	// recording is still usable — the right channel's timing is what
	// grading depends on, not perfection — but it is worth flagging.
	Degraded bool
}

// Recorder captures the session's dual-channel recording: the human's mic
// audio and the persona's spoken audio, aligned so the persona channel can
// be truncated at exactly what was heard on a barge-in — the same heardMs
// the session actor already computes for SpeakerSession.Truncate.
//
// Every write is non-blocking. The recorder sits off the media path, not on
// it: it must silence-fill and count on overflow rather than ever apply
// backpressure to SendAudio or the Speaker event loop. Recorder failure
// degrades the bundle (see RecordingInfo.Degraded), never the live session.
type Recorder interface {
	// WriteHuman appends one frame of the interviewer's mic audio.
	WriteHuman(f Frame)
	// WritePersona appends one frame of the persona's spoken audio for
	// response item itemID.
	WritePersona(itemID string, f Frame)
	// TruncatePersona marks item itemID's recorded audio as heard only up
	// to heardMs, mirroring a SpeakerSession.Truncate call so the
	// recording and the vendor's (best-effort) history agree on what
	// actually played.
	TruncatePersona(itemID string, heardMs int)
	// Finalize stops accepting writes and produces the muxed recording,
	// writing it to durable storage and returning where it landed.
	Finalize(ctx context.Context) (RecordingInfo, error)
}
