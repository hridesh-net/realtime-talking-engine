package ports

import (
	"context"
	"errors"
)

// ErrTruncateUnsupported is returned by SpeakerSession.Truncate when the
// vendor exposes no client-side truncation API — verified live: Gemini Live
// has no such API, so its adapter cannot honour Truncate at all. Truncate is
// best-effort; see its doc comment for what callers must do with this error.
var ErrTruncateUnsupported = errors.New("ports: vendor does not support truncation")

// SessionCfg configures a new Speaker session. Fields are primitives, not
// contract types, so this package never needs to import internal/contract —
// the caller (internal/session) is responsible for projecting an
// internal/contract.EngineContract into a SessionCfg.
type SessionCfg struct {
	// SessionID identifies the session for logging and vendor correlation.
	SessionID string
	// SystemPrompt is injected verbatim as the realtime model's system
	// instruction. It is compiled deterministically in Python; adapters must
	// not edit, summarize, or append to it.
	SystemPrompt string
	// VoiceID selects the vendor voice. Must equal the TTS voice used for
	// stall-bank pre-synthesis so stall clips have no voice seam.
	VoiceID string
	// MayInterrupt mirrors voice_directives.may_interrupt: whether the
	// persona may barge in on the human.
	MayInterrupt bool
	// DeferToolEnabled controls whether the defer tool is declared to the
	// Speaker for this session. The engine's own pre-gate is the sole
	// source of defer decisions today; this only governs whether the
	// vendor model is even offered the tool.
	DeferToolEnabled bool
}

// ResponseDirectives shapes one Speaker response. It carries the turn's
// sentence bounds and answer depth, derived from turn_policy and the
// session's current unlock state.
type ResponseDirectives struct {
	// MinSentences and MaxSentences bound the response length. The engine
	// enforces MaxSentences by trimming (CancelResponse); it does not rely
	// on the model alone.
	MinSentences int
	MaxSentences int
	// TargetSentences is the aim within [MinSentences, MaxSentences].
	TargetSentences int
	// AnswerDepth is the depth directive for this response, e.g. the
	// contract's default_answer_depth or, post-unlock, a deeper directive.
	AnswerDepth string
}

// Speaker starts realtime speech sessions with a vendor speech model. The
// Speaker always owns the persona's mouth; only a Speaker vendor adapter may
// hold vendor API keys.
type Speaker interface {
	// Start opens a new realtime speech session for one interview session.
	Start(ctx context.Context, cfg SessionCfg) (SpeakerSession, error)
}

// SpeakerSession is one open realtime speech session with a vendor speech
// model.
//
// Mutating methods (SendAudio, InjectSystemItem, CreateResponse,
// CancelResponse, Truncate) must not block on network I/O. The session
// actor calls them from inside its own single-threaded loop while a pump
// goroutine feeds that same loop from the vendor's event stream; an adapter
// that blocks on a socket write closes a deadlock cycle between the two.
// Adapters must own an internal write queue and return once the call is
// enqueued, not once it is on the wire.
type SpeakerSession interface {
	// SendAudio streams one decoded audio frame from the human interviewer
	// to the Speaker.
	SendAudio(ctx context.Context, frame Frame) error
	// InjectSystemItem adds a system-authored item — a ledger summary, a
	// Thinker note, a ceiling re-assertion — to the session's context
	// without producing audio. This is the single grounding path: verified
	// live, injecting a note as its own clientContent turn with
	// turn_complete=false, framed as a parenthetical context note, is
	// obeyed, is not spoken aloud, and leaves the transcript faithful.
	// ResponseDirectives carries no equivalent field for this reason —
	// every adapter grounds a response by calling this before
	// CreateResponse.
	InjectSystemItem(ctx context.Context, text string) error
	// CreateResponse asks the Speaker to produce a persona response under
	// the given directives.
	CreateResponse(ctx context.Context, directives ResponseDirectives) error
	// CancelResponse stops the in-flight response, e.g. on barge-in or a
	// sentence-bound trim.
	CancelResponse(ctx context.Context) error
	// Truncate tells the vendor how much of a prior response item was
	// actually heard (heardMs), so the vendor's own history matches reality
	// after a barge-in.
	//
	// This is best-effort. Not every vendor exposes a client-side
	// truncation API — verified live, Gemini Live does not — and an
	// adapter that cannot honour it returns ErrTruncateUnsupported.
	// Callers must treat that as "the vendor's history now contains more
	// than the human heard," never as a failure to propagate up the
	// session: the recording's right channel, truncated at heardMs,
	// remains the grading ground truth regardless of vendor capability.
	// Vendor history is persona-consistency insurance only — it keeps the
	// model from confidently referencing audio nobody heard — and losing
	// that insurance does not corrupt anything the grader reads.
	Truncate(ctx context.Context, itemID string, heardMs int) error
	// Events returns the normalized event stream for this session. It is
	// closed when the session ends; no vendor wire type is ever sent on it.
	Events() <-chan SpeakerEvent
	// Close ends the session and releases vendor resources.
	Close(ctx context.Context) error
}

// SpeakerEvent is one normalized event from a Speaker session's event
// stream. Vendor adapters translate their wire protocol into these concrete
// types at the vendor boundary; no vendor wire type ever leaks past
// internal/vendor/*.
type SpeakerEvent interface {
	isSpeakerEvent()
}

// InputTranscript is the human interviewer's speech, transcribed by the
// Speaker vendor's own input transcription (distinct from the Transcriber
// port). Final marks end-of-utterance.
type InputTranscript struct {
	Text   string
	Final  bool
	ItemID string
}

func (InputTranscript) isSpeakerEvent() {}

// OutputTranscriptDelta is a chunk of what the Speaker is saying, as text.
//
// The adapter must ensure the delta stream reflects only what was actually
// spoken. Verified live: Gemini's output_audio_transcription can report
// planning text that never reaches the audio. This matters because the
// session actor feeds these deltas into sentence-bound enforcement
// (max_sentences) and into the persona's turn text, which is the grading
// ground truth — phantom text both cuts the persona off early and corrupts
// the record.
type OutputTranscriptDelta struct {
	Text       string
	ResponseID string
}

func (OutputTranscriptDelta) isSpeakerEvent() {}

// AudioDelta is a chunk of persona PCM16 audio the Speaker is producing.
type AudioDelta struct {
	Frame      Frame
	ResponseID string
	// ItemID is the identifier this adapter's own Truncate accepts for
	// this response item. It is not necessarily equal to ResponseID: on
	// OpenAI Realtime, conversation.item.truncate requires an item id, not
	// a response id, and passing the wrong one truncates nothing. Callers
	// must plumb this value, not ResponseID, through to Truncate.
	ItemID string
}

func (AudioDelta) isSpeakerEvent() {}

// SpeechStarted signals that the human started speaking — the barge-in
// signal. It fires whether or not the Speaker is currently talking; the
// session actor decides what to do with it.
type SpeechStarted struct {
	AudioStartMs int
}

func (SpeechStarted) isSpeakerEvent() {}

// ResponseDone signals that the Speaker finished a response turn.
type ResponseDone struct {
	ResponseID string
	ItemID     string
}

func (ResponseDone) isSpeakerEvent() {}

// ToolCall is a vendor tool/function call emitted by the Speaker model, e.g.
// the bonus-path defer tool. The session actor identifies the defer call by
// Name and joins the DEFERRED flow; no other tool call is contractually
// meaningful yet.
type ToolCall struct {
	Name       string
	CallID     string
	Arguments  []byte
	ResponseID string
}

func (ToolCall) isSpeakerEvent() {}

// SpeakerError is a transport or vendor API error surfaced from the Speaker
// session. Fatal indicates the session cannot continue without a
// reconnect.
type SpeakerError struct {
	Message string
	Code    string
	Fatal   bool
}

func (SpeakerError) isSpeakerEvent() {}
