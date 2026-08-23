package gemini

import "encoding/json"

// The Gemini Live BidiGenerateContent wire protocol, as far as this adapter
// uses it. Every field here was exercised against the live API; the shapes are
// measured, not transcribed from documentation.
//
// These types never leave this package. The port's SpeakerEvent types are what
// crosses the boundary, which is the rule that keeps a vendor's protocol from
// reaching the session loop.

// ---- client -> server ------------------------------------------------------

type clientMessage struct {
	Setup         *setupMsg         `json:"setup,omitempty"`
	ClientContent *clientContentMsg `json:"clientContent,omitempty"`
	RealtimeInput *realtimeInputMsg `json:"realtimeInput,omitempty"`
}

type setupMsg struct {
	Model                    string                `json:"model"`
	GenerationConfig         generationConfig      `json:"generationConfig"`
	SystemInstruction        *content              `json:"systemInstruction,omitempty"`
	RealtimeInputConfig      *realtimeInputConfig  `json:"realtimeInputConfig,omitempty"`
	InputAudioTranscription  *struct{}             `json:"inputAudioTranscription,omitempty"`
	OutputAudioTranscription *struct{}             `json:"outputAudioTranscription,omitempty"`
	SessionResumption        *sessionResumptionCfg `json:"sessionResumption,omitempty"`
	ContextWindowCompression *contextCompression   `json:"contextWindowCompression,omitempty"`
}

type generationConfig struct {
	ResponseModalities []string      `json:"responseModalities"`
	SpeechConfig       *speechConfig `json:"speechConfig,omitempty"`
}

type speechConfig struct {
	VoiceConfig *voiceConfig `json:"voiceConfig,omitempty"`
}

type voiceConfig struct {
	PrebuiltVoiceConfig *prebuiltVoiceConfig `json:"prebuiltVoiceConfig,omitempty"`
}

type prebuiltVoiceConfig struct {
	VoiceName string `json:"voiceName"`
}

type realtimeInputConfig struct {
	AutomaticActivityDetection *automaticActivityDetection `json:"automaticActivityDetection,omitempty"`
}

type automaticActivityDetection struct {
	Disabled bool `json:"disabled"`
}

type sessionResumptionCfg struct {
	Handle string `json:"handle,omitempty"`
}

// contextCompression keeps a long interview inside the model's window. A
// 45-60 minute session will exceed it otherwise, and the failure mode is the
// session ending rather than degrading.
type contextCompression struct {
	SlidingWindow *struct{} `json:"slidingWindow,omitempty"`
}

type content struct {
	Role  string `json:"role,omitempty"`
	Parts []part `json:"parts"`
}

type part struct {
	Text       string      `json:"text,omitempty"`
	InlineData *inlineData `json:"inlineData,omitempty"`
}

type inlineData struct {
	MimeType string `json:"mimeType"`
	Data     []byte `json:"data"`
}

type clientContentMsg struct {
	Turns        []content `json:"turns,omitempty"`
	TurnComplete bool      `json:"turnComplete"`
}

type realtimeInputMsg struct {
	Audio         *inlineData `json:"audio,omitempty"`
	ActivityStart *struct{}   `json:"activityStart,omitempty"`
	ActivityEnd   *struct{}   `json:"activityEnd,omitempty"`
}

// ---- server -> client ------------------------------------------------------

type serverMessage struct {
	SetupComplete           json.RawMessage          `json:"setupComplete,omitempty"`
	ServerContent           *serverContent           `json:"serverContent,omitempty"`
	GoAway                  *goAway                  `json:"goAway,omitempty"`
	SessionResumptionUpdate *sessionResumptionUpdate `json:"sessionResumptionUpdate,omitempty"`
	UsageMetadata           json.RawMessage          `json:"usageMetadata,omitempty"`
	ToolCall                json.RawMessage          `json:"toolCall,omitempty"`
	Error                   json.RawMessage          `json:"error,omitempty"`
}

type serverContent struct {
	ModelTurn           *content       `json:"modelTurn,omitempty"`
	InputTranscription  *transcription `json:"inputTranscription,omitempty"`
	OutputTranscription *transcription `json:"outputTranscription,omitempty"`
	Interrupted         bool           `json:"interrupted,omitempty"`
	TurnComplete        bool           `json:"turnComplete,omitempty"`
	GenerationComplete  bool           `json:"generationComplete,omitempty"`
}

type transcription struct {
	Text string `json:"text"`
}

type goAway struct {
	TimeLeft string `json:"timeLeft"`
}

type sessionResumptionUpdate struct {
	NewHandle string `json:"newHandle"`
	Resumable bool   `json:"resumable"`
}
