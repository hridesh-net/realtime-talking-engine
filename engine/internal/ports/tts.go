package ports

import "context"

// PCM16Audio is synthesized PCM16 mono audio at a fixed sample rate.
type PCM16Audio struct {
	Samples      []byte
	SampleRateHz int
}

// TTS synthesizes speech for pre-synthesis use cases: the stall bank and
// the opening line. VoiceID must equal the Speaker's voice (SessionCfg.
// VoiceID / the contract's tts_voice_id) so pre-synthesized clips have no
// voice seam against the live Speaker. Implementation: vendor/geminitts.
type TTS interface {
	// Synthesize renders text to audio in voiceID's voice.
	Synthesize(ctx context.Context, text string, voiceID string) (PCM16Audio, error)
}
