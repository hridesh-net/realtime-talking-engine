package gemini_test

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/coder/websocket"
	"go.uber.org/goleak"

	"skillbrew/engine/internal/ports"
	"skillbrew/engine/internal/vendors/gemini"
)

// testModelID stands in for a configured model id. Deliberately not shaped
// like a real vendor id: model ids are config, and the layering gate enforces
// that no literal that looks like one appears outside internal/config.
const testModelID = "test-live-model"

func quietLogger() *slog.Logger { return slog.New(slog.NewTextHandler(io.Discard, nil)) }

func verifyNoEngineLeaks(t *testing.T) {
	t.Cleanup(func() {
		goleak.VerifyNone(t,
			goleak.IgnoreTopFunction("net/http.(*connReader).backgroundRead"),
			goleak.IgnoreTopFunction("net/http.(*persistConn).writeLoop"),
			goleak.IgnoreTopFunction("net/http.(*persistConn).readLoop"),
			goleak.IgnoreTopFunction("internal/poll.runtime_pollWait"),
		)
	})
}

// fakeVendor is a local stand-in for the Live API. It records every client
// message and replays scripted server frames, which is what makes this
// adapter — the riskiest package in the build — testable with no network and
// no spend.
type fakeVendor struct {
	srv *httptest.Server

	mu       sync.Mutex
	received []map[string]json.RawMessage
	sockets  []*websocket.Conn
	dials    int

	// onSetup is called with the setup message; whatever it returns is sent
	// back before anything else.
	onSetup func(setup map[string]json.RawMessage) []any
	// onMessage lets a test respond to any later client message.
	onMessage func(msg map[string]json.RawMessage) []any
	// stallAfterSetup makes the vendor stop reading once setup is done,
	// which is what actually backs the socket up. CloseRead does not: it
	// keeps draining the connection and discarding, so writes never block
	// and a deadlock test built on it can never fail.
	stallAfterSetup bool
	// stop releases a stalled handler. Closed before the httptest server is,
	// because Close waits for in-flight handlers and a handler parked on a
	// context that only the server cancels would deadlock the teardown.
	stop chan struct{}
}

func newFakeVendor(t *testing.T) *fakeVendor {
	t.Helper()
	f := &fakeVendor{stop: make(chan struct{})}
	f.srv = httptest.NewServer(http.HandlerFunc(f.serve))
	t.Cleanup(f.srv.Close)
	// Registered after the server's own cleanup so it runs before it:
	// cleanups run last-registered-first.
	t.Cleanup(func() { close(f.stop) })
	return f
}

func (f *fakeVendor) endpoint() string { return "ws" + strings.TrimPrefix(f.srv.URL, "http") }

func (f *fakeVendor) serve(w http.ResponseWriter, r *http.Request) {
	ws, err := websocket.Accept(w, r, &websocket.AcceptOptions{InsecureSkipVerify: true})
	if err != nil {
		return
	}
	ws.SetReadLimit(1 << 24)
	f.mu.Lock()
	f.dials++
	f.sockets = append(f.sockets, ws)
	f.mu.Unlock()
	defer ws.CloseNow()

	ctx := r.Context()
	for {
		_, data, err := ws.Read(ctx)
		if err != nil {
			return
		}
		var msg map[string]json.RawMessage
		if json.Unmarshal(data, &msg) != nil {
			continue
		}
		f.mu.Lock()
		f.received = append(f.received, msg)
		isSetup := msg["setup"] != nil
		onSetup, onMessage, stall := f.onSetup, f.onMessage, f.stallAfterSetup
		f.mu.Unlock()

		var replies []any
		switch {
		case isSetup && onSetup != nil:
			var setup map[string]json.RawMessage
			_ = json.Unmarshal(msg["setup"], &setup)
			replies = onSetup(setup)
		case isSetup:
			replies = []any{map[string]any{"setupComplete": map[string]any{}}}
		case onMessage != nil:
			replies = onMessage(msg)
		}
		for _, rep := range replies {
			b, _ := json.Marshal(rep)
			if err := ws.Write(ctx, websocket.MessageText, b); err != nil {
				return
			}
		}
		if isSetup && stall {
			// Stop reading, but hold the connection open.
			select {
			case <-ctx.Done():
			case <-f.stop:
			}
			return
		}
	}
}

// push sends a server frame on the most recent socket.
func (f *fakeVendor) push(t *testing.T, v any) {
	t.Helper()
	f.mu.Lock()
	if len(f.sockets) == 0 {
		f.mu.Unlock()
		t.Fatal("no vendor socket yet")
	}
	ws := f.sockets[len(f.sockets)-1]
	f.mu.Unlock()
	b, _ := json.Marshal(v)
	if err := ws.Write(context.Background(), websocket.MessageText, b); err != nil {
		t.Fatalf("push: %v", err)
	}
}

// sent returns every client message whose top-level key matches.
func (f *fakeVendor) sent(key string) []map[string]json.RawMessage {
	f.mu.Lock()
	defer f.mu.Unlock()
	var out []map[string]json.RawMessage
	for _, m := range f.received {
		if m[key] != nil {
			out = append(out, m)
		}
	}
	return out
}

func (f *fakeVendor) dialCount() int {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.dials
}

// waitFor polls until cond holds, failing rather than hanging.
func waitFor(t *testing.T, what string, cond func() bool) {
	t.Helper()
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		if cond() {
			return
		}
		time.Sleep(2 * time.Millisecond)
	}
	t.Fatalf("timed out waiting for %s", what)
}

func startSession(t *testing.T, f *fakeVendor, cfg ports.SessionCfg) ports.SpeakerSession {
	t.Helper()
	sp := gemini.New(testModelID, "test-key", quietLogger(), gemini.WithEndpoint(f.endpoint()))
	sess, err := sp.Start(context.Background(), cfg)
	if err != nil {
		t.Fatalf("start: %v", err)
	}
	t.Cleanup(func() { _ = sess.Close(context.Background()) })
	return sess
}

// nextEvent reads one event, failing rather than blocking forever.
func nextEvent(t *testing.T, sess ports.SpeakerSession) ports.SpeakerEvent {
	t.Helper()
	select {
	case ev, ok := <-sess.Events():
		if !ok {
			t.Fatal("event stream closed")
		}
		return ev
	case <-time.After(5 * time.Second):
		t.Fatal("no event arrived")
		return nil
	}
}

// TestSetupDisablesVendorVoiceDetectionAndAsksForBothTranscripts matters
// because the engine owning turn boundaries is the decision the whole
// two-model design rests on: the persona must hold the floor for
// target_pause_before_answer_ms, and a vendor that decides on its own when a
// turn ended cannot be made to wait.
func TestSetupDisablesVendorVoiceDetectionAndAsksForBothTranscripts(t *testing.T) {
	verifyNoEngineLeaks(t)

	f := newFakeVendor(t)
	startSession(t, f, ports.SessionCfg{
		SessionID: "s1", SystemPrompt: "you are a candidate", VoiceID: "Algenib",
	})

	sent := f.sent("setup")
	if len(sent) != 1 {
		t.Fatalf("got %d setup messages, want 1", len(sent))
	}
	var setup struct {
		Model               string `json:"model"`
		RealtimeInputConfig struct {
			AutomaticActivityDetection struct {
				Disabled bool `json:"disabled"`
			} `json:"automaticActivityDetection"`
		} `json:"realtimeInputConfig"`
		SystemInstruction struct {
			Parts []struct {
				Text string `json:"text"`
			} `json:"parts"`
		} `json:"systemInstruction"`
		GenerationConfig struct {
			ResponseModalities []string `json:"responseModalities"`
			SpeechConfig       struct {
				VoiceConfig struct {
					PrebuiltVoiceConfig struct {
						VoiceName string `json:"voiceName"`
					} `json:"prebuiltVoiceConfig"`
				} `json:"voiceConfig"`
			} `json:"speechConfig"`
		} `json:"generationConfig"`
		InputAudioTranscription  *struct{} `json:"inputAudioTranscription"`
		OutputAudioTranscription *struct{} `json:"outputAudioTranscription"`
		ContextWindowCompression *struct {
			SlidingWindow *struct{} `json:"slidingWindow"`
		} `json:"contextWindowCompression"`
	}
	if err := json.Unmarshal(sent[0]["setup"], &setup); err != nil {
		t.Fatalf("decode setup: %v", err)
	}

	if !setup.RealtimeInputConfig.AutomaticActivityDetection.Disabled {
		t.Fatal("vendor automatic activity detection is enabled; the engine cannot own turn boundaries")
	}
	if setup.InputAudioTranscription == nil || setup.OutputAudioTranscription == nil {
		t.Fatal("both transcriptions must be requested: one is ASR fallback, the other is grading ground truth")
	}
	if setup.ContextWindowCompression == nil || setup.ContextWindowCompression.SlidingWindow == nil {
		t.Fatal("context compression is off; a 45-60 minute interview would overrun the window and end")
	}
	if got := setup.SystemInstruction.Parts[0].Text; got != "you are a candidate" {
		t.Fatalf("system prompt = %q; adapters must pass it verbatim", got)
	}
	if got := setup.GenerationConfig.SpeechConfig.VoiceConfig.PrebuiltVoiceConfig.VoiceName; got != "Algenib" {
		t.Fatalf("voice = %q, want the contract's frozen voice", got)
	}
	// Compared by trimming rather than against a combined literal: the
	// layering gate forbids model-id literals outside config, and writing
	// the expectation out in full would be exactly such a literal.
	if got := strings.TrimPrefix(setup.Model, "models/"); got != testModelID || got == setup.Model {
		t.Fatalf("model = %q, want the configured id %q in resource form", setup.Model, testModelID)
	}
}

// TestAudioIsAlwaysWrappedInAnActivityWindow is the one that would otherwise
// fail silently in production. Verified live: audio sent outside a window is
// discarded with no bytes, no transcription and no error — so without this the
// persona simply never hears the question and nothing can tell.
func TestAudioIsAlwaysWrappedInAnActivityWindow(t *testing.T) {
	verifyNoEngineLeaks(t)

	f := newFakeVendor(t)
	sess := startSession(t, f, ports.SessionCfg{SessionID: "s1"})

	if err := sess.SendAudio(context.Background(), ports.Frame{
		PCM: make([]byte, 320), SampleRateHz: 16000,
	}); err != nil {
		t.Fatalf("send audio: %v", err)
	}

	waitFor(t, "the audio message", func() bool { return len(f.sent("realtimeInput")) >= 2 })

	msgs := f.sent("realtimeInput")
	var first struct {
		ActivityStart *struct{} `json:"activityStart"`
	}
	if err := json.Unmarshal(msgs[0]["realtimeInput"], &first); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if first.ActivityStart == nil {
		t.Fatal("audio was sent before any activityStart; the vendor would discard it in silence")
	}

	var second struct {
		Audio *struct {
			MimeType string `json:"mimeType"`
		} `json:"audio"`
	}
	if err := json.Unmarshal(msgs[1]["realtimeInput"], &second); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if second.Audio == nil {
		t.Fatal("no audio followed the activityStart")
	}
	if !strings.Contains(second.Audio.MimeType, "16000") {
		t.Fatalf("mime type %q must declare the 16 kHz rate the vendor requires", second.Audio.MimeType)
	}
}

// TestOnlyOneActivityWindowIsOpenedPerUtterance matters because a redundant
// activityStart mid-utterance reads to the vendor as a barge-in and cancels
// the very response the engine is waiting for.
func TestOnlyOneActivityWindowIsOpenedPerUtterance(t *testing.T) {
	verifyNoEngineLeaks(t)

	f := newFakeVendor(t)
	sess := startSession(t, f, ports.SessionCfg{SessionID: "s1"})

	for range 5 {
		if err := sess.SendAudio(context.Background(), ports.Frame{
			PCM: make([]byte, 320), SampleRateHz: 16000,
		}); err != nil {
			t.Fatalf("send audio: %v", err)
		}
	}
	waitFor(t, "all frames", func() bool { return len(f.sent("realtimeInput")) >= 6 })

	starts := 0
	for _, m := range f.sent("realtimeInput") {
		var v struct {
			ActivityStart *struct{} `json:"activityStart"`
		}
		_ = json.Unmarshal(m["realtimeInput"], &v)
		if v.ActivityStart != nil {
			starts++
		}
	}
	if starts != 1 {
		t.Fatalf("sent %d activityStart messages for one utterance, want 1", starts)
	}
}

// TestCreateResponseClosesTheWindowWhichIsWhatMakesTheVendorGenerate pins the
// mechanism D6 depends on.
func TestCreateResponseClosesTheWindowWhichIsWhatMakesTheVendorGenerate(t *testing.T) {
	verifyNoEngineLeaks(t)

	f := newFakeVendor(t)
	sess := startSession(t, f, ports.SessionCfg{SessionID: "s1"})

	_ = sess.SendAudio(context.Background(), ports.Frame{PCM: make([]byte, 320), SampleRateHz: 16000})
	if err := sess.CreateResponse(context.Background(), ports.ResponseDirectives{MaxSentences: 3}); err != nil {
		t.Fatalf("create response: %v", err)
	}
	waitFor(t, "activityEnd", func() bool {
		for _, m := range f.sent("realtimeInput") {
			var v struct {
				ActivityEnd *struct{} `json:"activityEnd"`
			}
			_ = json.Unmarshal(m["realtimeInput"], &v)
			if v.ActivityEnd != nil {
				return true
			}
		}
		return false
	})
}

// TestCancelResponseSendsABareActivityStart pins the measured interruption
// mechanism. There is no cancel RPC on this API: live, a bare activityStart
// set `interrupted` within 90 ms, produced no further audio, and completed the
// turn without starting a new response.
func TestCancelResponseSendsABareActivityStart(t *testing.T) {
	verifyNoEngineLeaks(t)

	f := newFakeVendor(t)
	sess := startSession(t, f, ports.SessionCfg{SessionID: "s1"})

	if err := sess.CancelResponse(context.Background()); err != nil {
		t.Fatalf("cancel: %v", err)
	}
	waitFor(t, "the interrupting activityStart", func() bool {
		for _, m := range f.sent("realtimeInput") {
			var v struct {
				ActivityStart *struct{} `json:"activityStart"`
			}
			_ = json.Unmarshal(m["realtimeInput"], &v)
			if v.ActivityStart != nil {
				return true
			}
		}
		return false
	})
}

// TestASystemItemIsAParentheticalWithNoMarkerConvention is the finding that
// removed work from the plan rather than adding it. Teaching the persona a
// bracketed marker causes it to fabricate its own marker spans — four turns
// out of four with the marker present, none without — and those spans reach
// the transcript while never reaching the audio.
func TestASystemItemIsAParentheticalWithNoMarkerConvention(t *testing.T) {
	verifyNoEngineLeaks(t)

	f := newFakeVendor(t)
	sess := startSession(t, f, ports.SessionCfg{SessionID: "s1"})

	if err := sess.InjectSystemItem(context.Background(), "Stay vague about Redis internals."); err != nil {
		t.Fatalf("inject: %v", err)
	}
	waitFor(t, "the note", func() bool { return len(f.sent("clientContent")) >= 1 })

	var cc struct {
		Turns []struct {
			Role  string `json:"role"`
			Parts []struct {
				Text string `json:"text"`
			} `json:"parts"`
		} `json:"turns"`
		TurnComplete bool `json:"turnComplete"`
	}
	if err := json.Unmarshal(f.sent("clientContent")[0]["clientContent"], &cc); err != nil {
		t.Fatalf("decode: %v", err)
	}
	text := cc.Turns[0].Parts[0].Text
	if !strings.HasPrefix(text, "(") || !strings.HasSuffix(text, ")") {
		t.Fatalf("note = %q, want a plain parenthetical", text)
	}
	if strings.Contains(text, "[[") {
		t.Fatalf("note = %q carries a marker convention, which induces the model to fabricate its own", text)
	}
	if cc.TurnComplete {
		t.Fatal("a grounding note must not complete the turn, or the model answers it aloud")
	}
}

// TestTruncateReportsThatThisVendorCannotDoIt pins D4. The caller must treat
// this as "vendor history now holds more than the human heard", never as a
// session failure.
func TestTruncateReportsThatThisVendorCannotDoIt(t *testing.T) {
	verifyNoEngineLeaks(t)

	f := newFakeVendor(t)
	sess := startSession(t, f, ports.SessionCfg{SessionID: "s1"})

	err := sess.Truncate(context.Background(), "item-1", 2100)
	if !errors.Is(err, ports.ErrTruncateUnsupported) {
		t.Fatalf("Truncate error = %v, want ErrTruncateUnsupported", err)
	}
}

// TestServerAudioBecomesAudioDeltasCarryingAnItemID matters because the actor
// keys its playout tracker on that identifier and the browser echoes it back
// on every heartbeat. Gemini supplies none, so the adapter mints one — and a
// missing one would make every heartbeat fail to match.
func TestServerAudioBecomesAudioDeltasCarryingAnItemID(t *testing.T) {
	verifyNoEngineLeaks(t)

	f := newFakeVendor(t)
	sess := startSession(t, f, ports.SessionCfg{SessionID: "s1"})

	f.push(t, map[string]any{"serverContent": map[string]any{
		"modelTurn": map[string]any{"parts": []any{
			map[string]any{"inlineData": map[string]any{
				"mimeType": "audio/pcm;rate=24000",
				"data":     []byte{1, 2, 3, 4},
			}},
		}},
	}})

	ev := nextEvent(t, sess)
	delta, ok := ev.(ports.AudioDelta)
	if !ok {
		t.Fatalf("got %T, want AudioDelta", ev)
	}
	if delta.ItemID == "" {
		t.Fatal("AudioDelta carries no ItemID; playout heartbeats could never match it")
	}
	if delta.Frame.SampleRateHz != gemini.OutputRateHz {
		t.Fatalf("rate = %d, want the vendor's %d", delta.Frame.SampleRateHz, gemini.OutputRateHz)
	}
	if len(delta.Frame.PCM) != 4 {
		t.Fatalf("PCM length = %d, want 4", len(delta.Frame.PCM))
	}
}

// TestATurnWithTranscriptButNoAudioIsReported guards a failure observed live:
// one session returned a complete 1050-character transcript and zero audio,
// then completed the turn. The persona would have been silent while the
// transcript — grading ground truth — said it spoke.
func TestATurnWithTranscriptButNoAudioIsReported(t *testing.T) {
	verifyNoEngineLeaks(t)

	f := newFakeVendor(t)
	sess := startSession(t, f, ports.SessionCfg{SessionID: "s1"})

	f.push(t, map[string]any{"serverContent": map[string]any{
		"outputTranscription": map[string]any{"text": "I designed a caching layer using Redis."},
	}})
	f.push(t, map[string]any{"serverContent": map[string]any{"turnComplete": true}})

	var sawError bool
	for range 3 {
		switch ev := nextEvent(t, sess).(type) {
		case ports.SpeakerError:
			if ev.Code == "silent_turn" {
				sawError = true
			}
		case ports.ResponseDone:
			if !sawError {
				t.Fatal("a turn with transcript and no audio completed without being reported")
			}
			return
		}
	}
	t.Fatal("no ResponseDone arrived")
}

// TestTheSessionResumesOnADroppedConnection is the property D5 turns on: the
// API caps a connection at around ten minutes while an interview runs 45-60,
// so resumption is not an optimisation but the only way one logical session
// can span the interview.
func TestTheSessionResumesOnADroppedConnection(t *testing.T) {
	verifyNoEngineLeaks(t)

	f := newFakeVendor(t)
	sess := startSession(t, f, ports.SessionCfg{SessionID: "s1"})

	// The vendor hands out a resumption handle, then drops the connection.
	f.push(t, map[string]any{"sessionResumptionUpdate": map[string]any{
		"newHandle": "handle-abc", "resumable": true,
	}})
	// Give the adapter a moment to record the handle before the drop.
	waitFor(t, "the handle to be recorded", func() bool { return true })
	time.Sleep(50 * time.Millisecond)

	f.mu.Lock()
	ws := f.sockets[len(f.sockets)-1]
	f.mu.Unlock()
	_ = ws.CloseNow()

	waitFor(t, "the reconnect", func() bool { return f.dialCount() >= 2 })

	// The second setup must carry the handle, or the vendor starts a fresh
	// conversation and the persona forgets the interview so far.
	waitFor(t, "the resumed setup", func() bool { return len(f.sent("setup")) >= 2 })
	var setup struct {
		SessionResumption struct {
			Handle string `json:"handle"`
		} `json:"sessionResumption"`
	}
	if err := json.Unmarshal(f.sent("setup")[1]["setup"], &setup); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if setup.SessionResumption.Handle != "handle-abc" {
		t.Fatalf("resumed with handle %q, want handle-abc; the persona would forget the interview",
			setup.SessionResumption.Handle)
	}
	_ = sess
}

// TestAnUnresumableDropIsFatalAndSaysSo matters because the actor's own
// rebuild path is what handles a lost mouth, and it cannot handle what it is
// never told about.
func TestAnUnresumableDropIsFatalAndSaysSo(t *testing.T) {
	verifyNoEngineLeaks(t)

	f := newFakeVendor(t)
	sess := startSession(t, f, ports.SessionCfg{SessionID: "s1"})

	// No resumption handle was ever issued, so the drop is unrecoverable.
	f.mu.Lock()
	ws := f.sockets[len(f.sockets)-1]
	f.mu.Unlock()
	_ = ws.CloseNow()

	for range 4 {
		if e, ok := nextEvent(t, sess).(ports.SpeakerError); ok && e.Fatal {
			return
		}
	}
	t.Fatal("an unresumable drop produced no fatal SpeakerError")
}

// TestMutatingCallsDoNotBlockOnTheSocket is the port's no-blocking-I/O clause.
// The session actor calls these from inside its own single-threaded loop while
// a pump feeds that same loop from this session's events; an adapter that
// wrote inline would close a deadlock cycle between the two.
func TestMutatingCallsDoNotBlockOnTheSocket(t *testing.T) {
	verifyNoEngineLeaks(t)

	f := newFakeVendor(t)
	f.stallAfterSetup = true
	sess := startSession(t, f, ports.SessionCfg{SessionID: "s1"})

	// Far more traffic than either the write queue or the socket buffers can
	// hold, against a vendor that has stopped reading. Large frames so the
	// kernel buffers fill quickly rather than after an unbounded number of
	// tiny writes.
	frame := ports.Frame{PCM: make([]byte, 64<<10), SampleRateHz: 16000}
	done := make(chan struct{})
	go func() {
		defer close(done)
		for range 512 {
			_ = sess.SendAudio(context.Background(), frame)
			_ = sess.InjectSystemItem(context.Background(), "note")
			_ = sess.CancelResponse(context.Background())
		}
	}()
	select {
	case <-done:
	case <-time.After(10 * time.Second):
		t.Fatal("a mutating call blocked while the vendor socket was not draining; " +
			"this is the actor-pump deadlock the port forbids")
	}
}

// TestAFullWriteQueueShedsAndSaysSoRatherThanWaiting matters because a bounded
// queue that blocks when full is only a slower version of the deadlock: it
// survives a hiccup and dies under a sustained stall, which is worse precisely
// because it passes every short test.
func TestAFullWriteQueueShedsAndSaysSoRatherThanWaiting(t *testing.T) {
	verifyNoEngineLeaks(t)

	f := newFakeVendor(t)
	f.stallAfterSetup = true
	sess := startSession(t, f, ports.SessionCfg{SessionID: "s1"})

	frame := ports.Frame{PCM: make([]byte, 64<<10), SampleRateHz: 16000}
	var refused int
	for range 512 {
		if err := sess.SendAudio(context.Background(), frame); err != nil {
			refused++
		}
	}
	if refused == 0 {
		t.Fatal("nothing was refused against a vendor that never read a byte; the queue is unbounded")
	}

	// And the session says so, rather than merely sounding wrong.
	deadline := time.After(5 * time.Second)
	for {
		select {
		case ev := <-sess.Events():
			if e, ok := ev.(ports.SpeakerError); ok && e.Code == "write_queue_full" {
				return
			}
		case <-deadline:
			t.Fatal("messages were dropped with nothing on the event stream to say so")
		}
	}
}

// TestSendAudioRefusesTheWrongSampleRate matters because the vendor fixes its
// input rate and silently mis-renders anything else — the conversion belongs
// upstream, and a mismatch here is a bug worth surfacing rather than resampling
// over.
func TestSendAudioRefusesTheWrongSampleRate(t *testing.T) {
	verifyNoEngineLeaks(t)

	f := newFakeVendor(t)
	sess := startSession(t, f, ports.SessionCfg{SessionID: "s1"})

	err := sess.SendAudio(context.Background(), ports.Frame{PCM: make([]byte, 320), SampleRateHz: 48000})
	if err == nil {
		t.Fatal("48 kHz audio was accepted for a vendor that requires 16 kHz")
	}
}

// TestCloseEndsTheEventStreamAndLeavesNoGoroutine matters because a node runs
// many sessions and each one leaking its reader and writer would be a
// slow-motion outage.
func TestCloseEndsTheEventStreamAndLeavesNoGoroutine(t *testing.T) {
	verifyNoEngineLeaks(t)

	f := newFakeVendor(t)
	sp := gemini.New(testModelID, "test-key", quietLogger(), gemini.WithEndpoint(f.endpoint()))
	sess, err := sp.Start(context.Background(), ports.SessionCfg{SessionID: "s1"})
	if err != nil {
		t.Fatalf("start: %v", err)
	}
	if err := sess.Close(context.Background()); err != nil {
		t.Fatalf("close: %v", err)
	}
	for {
		select {
		case _, ok := <-sess.Events():
			if !ok {
				return
			}
		case <-time.After(5 * time.Second):
			t.Fatal("the event stream was not closed")
		}
	}
}
