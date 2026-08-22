package ports

import "context"

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
	// SystemItem is optional additional context to ground this response —
	// a Thinker note, a fallback directive, or a claims-ledger summary.
	// Empty when there is nothing to add beyond the standing system prompt.
	SystemItem string
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
type SpeakerSession interface {
	// SendAudio streams one decoded audio frame from the human interviewer
	// to the Speaker.
	SendAudio(ctx context.Context, frame Frame) error
	// InjectSystemItem adds a system-authored item — a ledger summary, a
	// Thinker note, a ceiling re-assertion — to the session's context
	// without producing audio.
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
type OutputTranscriptDelta struct {
	Text       string
	ResponseID string
}

func (OutputTranscriptDelta) isSpeakerEvent() {}

// AudioDelta is a chunk of persona PCM16 audio the Speaker is producing.
type AudioDelta struct {
	Frame      Frame
	ResponseID string
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
