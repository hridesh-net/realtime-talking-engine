package audio

import "time"

// VADConfig tunes speech-onset detection.
type VADConfig struct {
	// OnsetMarginDB is how far above the tracked noise floor a frame must
	// sit to count as speech.
	OnsetMarginDB float64
	// OnsetFrames is how many consecutive qualifying frames declare onset.
	// More than one, because a single loud frame is a door or a keyboard.
	OnsetFrames int
	// HangoverFrames is how many quiet frames must pass before speech is
	// declared over. Speech is full of short gaps — stops, breaths — and
	// ending a turn inside one is the failure this exists to prevent.
	HangoverFrames int
	// FloorRiseDBPerSec and FloorFallDBPerSec bound how fast the noise
	// floor tracks. It falls quickly toward a newly quiet room and rises
	// slowly, so that speech itself cannot drag the floor up and mute the
	// detector mid-sentence.
	FloorRiseDBPerSec float64
	FloorFallDBPerSec float64
	// AbsoluteFloorDB is the level below which nothing counts as speech
	// however quiet the room, so a perfectly silent input cannot have its
	// own dither promoted to speech.
	AbsoluteFloorDB float64
}

// DefaultVADConfig is tuned for an office-quality microphone on a laptop.
//
// The bias is deliberately toward false positives over false negatives. A
// spurious onset costs an activityStart the engine can retract; a missed one
// means the persona never hears the question, and the live spike proved the
// vendor discards that audio silently — no bytes, no transcription, no error.
func DefaultVADConfig() VADConfig {
	return VADConfig{
		OnsetMarginDB:     9,
		OnsetFrames:       2,
		HangoverFrames:    40, // 800 ms at 20 ms frames: a thinking pause, not a turn end
		FloorRiseDBPerSec: 1.5,
		FloorFallDBPerSec: 24,
		AbsoluteFloorDB:   -55,
	}
}

// VAD detects speech onset and offset on the interviewer's mic audio.
//
// The engine owns this signal because vendor automatic VAD is disabled — a
// decision the design depends on, since the persona must hold the floor for
// target_pause_before_answer_ms before answering, and a vendor that decides
// on its own when a turn ended cannot be made to wait.
//
// Onset is the load-bearing output. Offset is published too, but only the
// degraded path uses it: an energy threshold cannot tell a thinking pause
// from a finished question, and the human here is a manager composing a
// question, for whom one- and two-second mid-question pauses are the normal
// case. End-of-turn belongs to the Transcriber; this is the fallback for when
// the Transcriber is gone.
//
// Not safe for concurrent use.
type VAD struct {
	cfg VADConfig

	floorDB     float64
	haveFloor   bool
	speaking    bool
	loudRun     int
	quietRun    int
	lastFrameAt time.Time
}

// NewVAD builds a detector. A zero-valued config is replaced by the default
// rather than producing a detector that fires on everything.
func NewVAD(cfg VADConfig) *VAD {
	if cfg.OnsetFrames <= 0 {
		cfg = DefaultVADConfig()
	}
	return &VAD{cfg: cfg}
}

// Speaking reports whether the detector currently believes speech is in
// progress.
func (v *VAD) Speaking() bool { return v.speaking }

// FloorDB is the currently tracked noise floor, exposed for observability:
// a session whose floor has climbed into the speech band explains a detector
// that stopped firing far better than the absence of onsets does.
func (v *VAD) FloorDB() float64 { return v.floorDB }

// Push feeds one frame and reports a state change, if any.
//
// changed is false for the overwhelming majority of frames. Callers emit an
// event only when it is true, so a 50 Hz frame stream produces a handful of
// signals per turn rather than a stream of its own.
func (v *VAD) Push(pcm []byte, sampleRateHz int, now time.Time) (started bool, changed bool) {
	level := RMSDB(pcm)

	// Track the floor before deciding, but never while speech is in
	// progress: letting a talker raise the floor is how a detector goes
	// deaf halfway through a sentence.
	if !v.haveFloor {
		v.floorDB = level
		v.haveFloor = true
		v.lastFrameAt = now
	} else {
		elapsed := now.Sub(v.lastFrameAt).Seconds()
		if elapsed < 0 {
			elapsed = 0
		}
		v.lastFrameAt = now
		switch {
		case level < v.floorDB:
			v.floorDB -= min(v.floorDB-level, v.cfg.FloorFallDBPerSec*elapsed)
		case !v.speaking:
			v.floorDB += min(level-v.floorDB, v.cfg.FloorRiseDBPerSec*elapsed)
		}
	}

	loud := level > v.floorDB+v.cfg.OnsetMarginDB && level > v.cfg.AbsoluteFloorDB
	if loud {
		v.loudRun++
		v.quietRun = 0
	} else {
		v.quietRun++
		v.loudRun = 0
	}

	if !v.speaking && v.loudRun >= v.cfg.OnsetFrames {
		v.speaking = true
		return true, true
	}
	if v.speaking && v.quietRun >= v.cfg.HangoverFrames {
		v.speaking = false
		return false, true
	}
	return v.speaking, false
}

// Reset returns the detector to its initial state, keeping the tuning. Used
// when a connection is replaced and the old room's noise floor no longer
// describes the new one.
func (v *VAD) Reset() {
	v.haveFloor = false
	v.speaking = false
	v.loudRun = 0
	v.quietRun = 0
}
