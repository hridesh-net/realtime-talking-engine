package gemini

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"strings"
	"sync"
	"time"

	"github.com/coder/websocket"

	"skillbrew/engine/internal/ports"
)

const (
	// eventBuffer sizes the normalized event stream. The session actor's pump
	// drains it; a few frames of slack absorbs a scheduling hiccup without
	// letting a stalled actor grow unbounded memory.
	eventBuffer = 64
	// writeBuffer sizes the outbound queue. It exists so that the port's
	// no-blocking-I/O clause can be honoured: mutating methods enqueue and
	// return, and one writer goroutine owns the socket.
	writeBuffer = 64
	// setupTimeout bounds how long Start waits for setupComplete.
	setupTimeout = 20 * time.Second
	// writeTimeout bounds one socket write.
	writeTimeout = 10 * time.Second
	// reconnectBackoff is the pause before a resumption attempt.
	reconnectBackoff = 500 * time.Millisecond
	// maxReconnects bounds resumption attempts before the session is
	// declared fatally lost.
	maxReconnects = 3
)

// session is one open Gemini Live conversation.
//
// It survives the vendor's connection lifetime rather than being bounded by it:
// the API caps a connection at around ten minutes and signals GoAway before
// cutting it, while an interview runs 45-60. Resumption is therefore not an
// optimisation but the only way this port's contract — one logical session for
// the whole interview — can be met at all.
type session struct {
	speaker *Speaker
	cfg     ports.SessionCfg
	logger  *slog.Logger

	events chan ports.SpeakerEvent
	writes chan clientMessage

	closeOnce sync.Once
	closed    chan struct{}
	setupOnce sync.Once
	setupOK   chan struct{}
	runDone   chan struct{}

	mu sync.Mutex
	ws *websocket.Conn
	// resumeHandle is the vendor's token for continuing this conversation on
	// a new connection. Updated on every sessionResumptionUpdate.
	resumeHandle string
	// activityOpen tracks whether an input activity window is open.
	//
	// This is load-bearing, not bookkeeping. Automatic voice activity
	// detection is disabled — the engine owns turn boundaries — and audio
	// sent outside an activity window is discarded by the vendor *silently*:
	// no bytes, no transcription, no error. A lost activityStart therefore
	// means the persona never hears the question and nothing downstream can
	// tell.
	activityOpen bool
	// responseAudio counts audio bytes in the response currently generating,
	// so a turn that completes having produced none can be reported rather
	// than leaving the persona mutely "speaking".
	responseAudio int
	// responseText accumulates the output transcript for the same check.
	responseText int
	reconnects   int
	// turnID identifies the response currently generating. Gemini Live
	// supplies no per-response identifier, and the actor needs one: its
	// playout tracker keys on it, and the browser echoes it back on every
	// heartbeat so barge-in truncation lands on the right item. Minted here
	// so the rest of the engine sees the same shape it gets from a vendor
	// that does supply one.
	turnID     string
	turnSeq    int
	writeDrops int
}

// currentTurn returns the id of the response being generated, minting one on
// the first event of a new response.
func (s *session) currentTurn() string {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.turnID == "" {
		s.turnSeq++
		s.turnID = fmt.Sprintf("g%d", s.turnSeq)
	}
	return s.turnID
}

var _ ports.SpeakerSession = (*session)(nil)

// connect dials and sends setup. handle, when non-empty, resumes a prior
// conversation instead of starting a new one.
func (s *session) connect(ctx context.Context, handle string) error {
	ws, err := s.speaker.dial(ctx)
	if err != nil {
		return err
	}
	s.mu.Lock()
	s.ws = ws
	// A new connection has no activity window open, whatever the old one had.
	s.activityOpen = false
	s.mu.Unlock()

	setup := setupMsg{
		Model: modelPath(s.speaker.modelID),
		GenerationConfig: generationConfig{
			ResponseModalities: []string{"AUDIO"},
		},
		// Automatic activity detection is disabled because the engine owns
		// turn boundaries: the persona must hold the floor for
		// target_pause_before_answer_ms before answering, and a vendor that
		// decides on its own when a turn ended cannot be made to wait.
		RealtimeInputConfig: &realtimeInputConfig{
			AutomaticActivityDetection: &automaticActivityDetection{Disabled: true},
		},
		InputAudioTranscription:  &struct{}{},
		OutputAudioTranscription: &struct{}{},
		SessionResumption:        &sessionResumptionCfg{Handle: handle},
		// Without compression a 45-60 minute interview overruns the model's
		// context window and the session ends rather than degrading.
		ContextWindowCompression: &contextCompression{SlidingWindow: &struct{}{}},
	}
	if s.cfg.SystemPrompt != "" {
		// Verbatim. The prompt is compiled deterministically in Python and an
		// adapter that edited, summarised or appended to it would void the
		// seed fingerprint that makes two interviews comparable.
		setup.SystemInstruction = &content{Parts: []part{{Text: s.cfg.SystemPrompt}}}
	}
	if s.cfg.VoiceID != "" {
		setup.GenerationConfig.SpeechConfig = &speechConfig{
			VoiceConfig: &voiceConfig{PrebuiltVoiceConfig: &prebuiltVoiceConfig{VoiceName: s.cfg.VoiceID}},
		}
	}

	return s.writeNow(ctx, ws, clientMessage{Setup: &setup})
}

// modelPath normalizes a configured model id to the API's resource form.
func modelPath(id string) string {
	if strings.HasPrefix(id, "models/") {
		return id
	}
	return "models/" + id
}

// run owns the socket: one reader, one writer, and the reconnect loop between
// them. Every goroutine this session starts is joined before Close returns.
func (s *session) run() {
	defer close(s.runDone)
	defer close(s.events)

	for {
		s.mu.Lock()
		ws := s.ws
		s.mu.Unlock()
		if ws == nil {
			return
		}

		ctx, cancel := context.WithCancel(context.Background())
		var wg sync.WaitGroup
		wg.Add(1)
		go func() {
			defer wg.Done()
			s.writeLoop(ctx, ws)
		}()

		readErr := s.readLoop(ctx, ws)
		cancel()
		wg.Wait()
		_ = ws.CloseNow()

		select {
		case <-s.closed:
			return
		default:
		}

		if !s.tryResume(readErr) {
			return
		}
	}
}

// tryResume reconnects with the vendor's resumption handle. It reports whether
// the session continues.
//
// On failure it emits SpeakerError{Fatal:true} rather than closing quietly:
// the actor's own rebuild path is what handles a lost mouth, and it cannot
// handle what it is not told about.
func (s *session) tryResume(cause error) bool {
	s.mu.Lock()
	handle := s.resumeHandle
	s.reconnects++
	attempt := s.reconnects
	s.mu.Unlock()

	if handle == "" || attempt > maxReconnects {
		s.emit(ports.SpeakerError{
			Message: fmt.Sprintf("gemini: session lost and not resumable after %d attempt(s): %v",
				attempt-1, cause),
			Code:  "session_lost",
			Fatal: true,
		})
		s.markClosed()
		return false
	}

	s.logger.Warn("gemini: resuming session", "attempt", attempt, "cause", cause)
	time.Sleep(reconnectBackoff)

	ctx, cancel := context.WithTimeout(context.Background(), setupTimeout)
	defer cancel()
	if err := s.connect(ctx, handle); err != nil {
		s.emit(ports.SpeakerError{
			Message: fmt.Sprintf("gemini: resume failed: %v", err),
			Code:    "resume_failed",
			Fatal:   true,
		})
		s.markClosed()
		return false
	}
	// Non-fatal: the mouth is back, but the actor may want to re-ground the
	// persona, and a resumption that left no trace is one nobody can
	// reconstruct from the event log afterwards.
	s.emit(ports.SpeakerError{
		Message: fmt.Sprintf("gemini: connection replaced, session resumed (attempt %d)", attempt),
		Code:    "resumed",
		Fatal:   false,
	})
	return true
}

// readLoop translates vendor frames into port events until the socket ends.
func (s *session) readLoop(ctx context.Context, ws *websocket.Conn) error {
	for {
		_, data, err := ws.Read(ctx)
		if err != nil {
			return err
		}
		var msg serverMessage
		if err := json.Unmarshal(data, &msg); err != nil {
			s.logger.Warn("gemini: undecodable frame", "err", err)
			continue
		}
		s.dispatch(msg)
	}
}

func (s *session) dispatch(msg serverMessage) {
	if msg.SetupComplete != nil {
		s.setupOnce.Do(func() { close(s.setupOK) })
		return
	}
	if msg.Error != nil {
		s.emit(ports.SpeakerError{
			Message: fmt.Sprintf("gemini: vendor error: %s", msg.Error),
			Code:    "vendor_error",
			Fatal:   false,
		})
		return
	}
	if u := msg.SessionResumptionUpdate; u != nil {
		if u.NewHandle != "" {
			s.mu.Lock()
			s.resumeHandle = u.NewHandle
			s.mu.Unlock()
		}
		return
	}
	if g := msg.GoAway; g != nil {
		// The vendor is about to close this connection. Nothing to do but
		// note it: the read loop will end and run reconnects with the
		// resumption handle already in hand.
		s.logger.Info("gemini: vendor go-away", "time_left", g.TimeLeft)
		return
	}
	if msg.ToolCall != nil {
		s.onToolCall(msg.ToolCall)
		return
	}
	if msg.ServerContent != nil {
		s.onServerContent(msg.ServerContent)
	}
}

// onToolCall forwards a vendor function call. Emitted with its name and
// arguments rather than as an anonymous event: the actor identifies the defer
// tool by name, and an event that omits the name tells it nothing.
func (s *session) onToolCall(raw json.RawMessage) {
	var tc struct {
		FunctionCalls []struct {
			ID   string          `json:"id"`
			Name string          `json:"name"`
			Args json.RawMessage `json:"args"`
		} `json:"functionCalls"`
	}
	if err := json.Unmarshal(raw, &tc); err != nil {
		s.logger.Warn("gemini: undecodable tool call", "err", err)
		return
	}
	for _, fc := range tc.FunctionCalls {
		s.emit(ports.ToolCall{
			Name:       fc.Name,
			CallID:     fc.ID,
			Arguments:  fc.Args,
			ResponseID: s.currentTurn(),
		})
	}
}

func (s *session) onServerContent(c *serverContent) {
	if t := c.InputTranscription; t != nil && t.Text != "" {
		s.emit(ports.InputTranscript{Text: t.Text})
	}
	if t := c.OutputTranscription; t != nil && t.Text != "" {
		s.mu.Lock()
		s.responseText += len(t.Text)
		s.mu.Unlock()
		// Forwarded verbatim. The engine feeds this into max_sentences
		// enforcement and into the persona's turn text, which is grading
		// ground truth, so an adapter that edited it would corrupt both.
		s.emit(ports.OutputTranscriptDelta{Text: t.Text})
	}
	if c.ModelTurn != nil {
		for _, p := range c.ModelTurn.Parts {
			if p.InlineData == nil || len(p.InlineData.Data) == 0 {
				continue
			}
			s.mu.Lock()
			s.responseAudio += len(p.InlineData.Data)
			s.mu.Unlock()
			id := s.currentTurn()
			s.emit(ports.AudioDelta{
				Frame: ports.Frame{
					PCM:          p.InlineData.Data,
					SampleRateHz: OutputRateHz,
					Timestamp:    time.Now(),
				},
				ResponseID: id,
				ItemID:     id,
			})
		}
	}
	if c.Interrupted {
		s.logger.Debug("gemini: response interrupted")
	}
	if c.TurnComplete {
		s.finishTurn()
	}
}

// finishTurn closes out one response and checks it actually produced speech.
//
// The check exists because it was observed live: one session returned a
// complete 1050-character output transcription and *zero* audio parts, then
// completed the turn — the persona would have been silent while the transcript
// claimed it spoke, and the transcript is grading ground truth. It did not
// reproduce across eleven later connections, which makes it rare rather than
// imaginary, and a rare silent failure on the one channel the human actually
// hears is worth an event.
func (s *session) finishTurn() {
	s.mu.Lock()
	gotAudio, gotText := s.responseAudio, s.responseText
	id := s.turnID
	s.responseAudio, s.responseText = 0, 0
	s.turnID = ""
	s.mu.Unlock()

	if gotAudio == 0 && gotText > 0 {
		s.emit(ports.SpeakerError{
			Message: fmt.Sprintf("gemini: turn produced %d characters of transcript and no audio; "+
				"the persona was silent while the transcript says it spoke", gotText),
			Code:  "silent_turn",
			Fatal: false,
		})
	}
	s.emit(ports.ResponseDone{ResponseID: id, ItemID: id})
}

// writeLoop owns the socket's write side.
//
// One goroutine, fed by a queue, is what makes the port's no-blocking-I/O
// clause true: the session actor calls mutating methods from inside its own
// single-threaded loop while a pump feeds that same loop from this session's
// event stream, so an adapter that wrote to the socket inline would close a
// deadlock cycle between the two.
func (s *session) writeLoop(ctx context.Context, ws *websocket.Conn) {
	for {
		select {
		case <-ctx.Done():
			return
		case msg := <-s.writes:
			if err := s.writeNow(ctx, ws, msg); err != nil {
				if ctx.Err() == nil {
					s.logger.Info("gemini: write ended", "err", err)
				}
				return
			}
		}
	}
}

func (s *session) writeNow(ctx context.Context, ws *websocket.Conn, msg clientMessage) error {
	body, err := json.Marshal(msg)
	if err != nil {
		return fmt.Errorf("gemini: marshal: %w", err)
	}
	wctx, cancel := context.WithTimeout(ctx, writeTimeout)
	defer cancel()
	return ws.Write(wctx, websocket.MessageText, body)
}

// enqueue hands one message to the writer. It never blocks — not on the
// socket, and not on the queue either.
//
// The queue-full case has to be a refusal rather than a wait. The port forbids
// blocking on network I/O because the session actor calls these methods from
// inside its own single-threaded loop while a pump feeds that same loop from
// this session's events; anything that parks the actor closes a deadlock cycle
// between the two. A bounded queue that blocks when full is only a slower
// version of the same deadlock — it survives a hiccup and dies under a
// sustained stall, which is the worse of the two failure modes because it
// passes every short test.
//
// A refused message is counted and surfaced once, so a session that is
// shedding says so instead of merely sounding wrong.
func (s *session) enqueue(_ context.Context, msg clientMessage) error {
	select {
	case <-s.closed:
		return errors.New("gemini: session closed")
	default:
	}
	select {
	case s.writes <- msg:
		return nil
	case <-s.closed:
		return errors.New("gemini: session closed")
	default:
		s.mu.Lock()
		s.writeDrops++
		n := s.writeDrops
		s.mu.Unlock()
		if n == 1 {
			s.emit(ports.SpeakerError{
				Message: "gemini: write queue full, messages are being dropped; the vendor socket is not draining",
				Code:    "write_queue_full",
				Fatal:   false,
			})
		}
		return fmt.Errorf("gemini: write queue full, message dropped (%d so far)", n)
	}
}

// WriteDrops is how many outbound messages were shed because the vendor socket
// was not draining.
func (s *session) WriteDrops() int {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.writeDrops
}

func (s *session) emit(ev ports.SpeakerEvent) {
	select {
	case s.events <- ev:
	case <-s.closed:
	}
}

// ---- ports.SpeakerSession --------------------------------------------------

// SendAudio streams one frame of the interviewer's speech.
//
// It opens an activity window first if none is open. That is not politeness:
// audio outside a window is discarded by the vendor in silence, so without
// this the persona simply never hears the question.
func (s *session) SendAudio(ctx context.Context, frame ports.Frame) error {
	if len(frame.PCM) == 0 {
		return nil
	}
	if frame.SampleRateHz != 0 && frame.SampleRateHz != InputRateHz {
		return fmt.Errorf("gemini: input audio must be %d Hz, got %d", InputRateHz, frame.SampleRateHz)
	}
	if err := s.ensureActivity(ctx); err != nil {
		return err
	}
	return s.enqueue(ctx, clientMessage{RealtimeInput: &realtimeInputMsg{
		Audio: &inlineData{
			MimeType: fmt.Sprintf("audio/pcm;rate=%d", InputRateHz),
			Data:     frame.PCM,
		},
	}})
}

// ensureActivity opens an input activity window if one is not already open.
func (s *session) ensureActivity(ctx context.Context) error {
	s.mu.Lock()
	if s.activityOpen {
		s.mu.Unlock()
		return nil
	}
	s.activityOpen = true
	s.mu.Unlock()
	return s.enqueue(ctx, clientMessage{RealtimeInput: &realtimeInputMsg{ActivityStart: &struct{}{}}})
}

// InjectSystemItem adds grounding context without producing audio.
//
// Verified live, and the phrasing matters more than it looks. Teaching the
// persona a bracketed marker convention — "[[DIRECTION]] ..." — causes the
// model to *fabricate its own* marker spans, four turns out of four with the
// marker present and none without. A plain parenthetical note carries the same
// instruction, is obeyed, is never spoken aloud, and leaves the transcript
// identical to the audio. So: no markers, ever.
func (s *session) InjectSystemItem(ctx context.Context, text string) error {
	if strings.TrimSpace(text) == "" {
		return nil
	}
	return s.enqueue(ctx, clientMessage{ClientContent: &clientContentMsg{
		Turns: []content{{
			Role:  "user",
			Parts: []part{{Text: "(" + strings.TrimSpace(text) + ")"}},
		}},
		// Explicitly not a complete turn: this is context, not a question,
		// and completing the turn would make the model answer it.
		TurnComplete: false,
	}})
}

// CreateResponse closes the input activity window, which is what makes this
// vendor generate. The engine — not the vendor's own voice detection — decides
// when a turn has ended, which is the whole reason automatic activity
// detection is disabled.
//
// The directives are not sent to the vendor. Sentence bounds are enforced by
// the engine trimming the response, because a model asked politely for three
// sentences delivers four often enough that the ceiling has to be a mechanism
// rather than a request.
func (s *session) CreateResponse(ctx context.Context, _ ports.ResponseDirectives) error {
	s.mu.Lock()
	open := s.activityOpen
	s.activityOpen = false
	s.mu.Unlock()
	if !open {
		// Nothing to close. Opening and immediately closing an empty window
		// would ask the model to answer silence.
		if err := s.enqueue(ctx, clientMessage{RealtimeInput: &realtimeInputMsg{ActivityStart: &struct{}{}}}); err != nil {
			return err
		}
	}
	return s.enqueue(ctx, clientMessage{RealtimeInput: &realtimeInputMsg{ActivityEnd: &struct{}{}}})
}

// CancelResponse stops the in-flight response.
//
// A bare activityStart is the mechanism, measured against the live API: the
// server set `interrupted` 90 ms after it was sent, produced no further audio,
// and completed the turn without starting a new response. There is no explicit
// cancel RPC on this API; this is it.
//
// The window it opens is left open on purpose — the barge-in that triggered
// this cancel is almost always followed by the human's own audio, which is
// exactly what that window is for.
func (s *session) CancelResponse(ctx context.Context) error {
	s.mu.Lock()
	if s.activityOpen {
		// A window is already open, so generation is not running and there
		// is nothing to interrupt.
		s.mu.Unlock()
		return nil
	}
	s.activityOpen = true
	s.mu.Unlock()
	return s.enqueue(ctx, clientMessage{RealtimeInput: &realtimeInputMsg{ActivityStart: &struct{}{}}})
}

// Truncate reports that this vendor cannot do it.
//
// Verified live: the Live API exposes no client-side truncation. The caller's
// contract says to treat this as "the vendor's history now contains more than
// the human heard", never as a session failure — the recording's right
// channel, cut at heardMs, stays the grading ground truth either way.
func (s *session) Truncate(context.Context, string, int) error {
	return ports.ErrTruncateUnsupported
}

// Events returns the normalized stream. It closes when the session ends.
func (s *session) Events() <-chan ports.SpeakerEvent { return s.events }

// Close ends the session and waits for its goroutines, so none outlives it.
func (s *session) Close(ctx context.Context) error {
	s.markClosed()
	s.mu.Lock()
	ws := s.ws
	s.mu.Unlock()
	if ws != nil {
		_ = ws.Close(websocket.StatusNormalClosure, "session ended")
	}
	select {
	case <-s.runDone:
	case <-ctx.Done():
		return ctx.Err()
	}
	return nil
}

func (s *session) markClosed() {
	s.closeOnce.Do(func() { close(s.closed) })
}
