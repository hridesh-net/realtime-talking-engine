package session

import (
	"context"
	"strings"
	"testing"
	"time"

	"go.uber.org/goleak"

	"skillbrew/engine/internal/fakes"
	"skillbrew/engine/internal/ports"
)

// acceptFakeMedia returns a fresh fake media connection, obtained the way the
// actor obtains a real one so the test exercises the same shape.
func acceptFakeMedia(t *testing.T) *fakes.FakeMediaConn {
	t.Helper()
	tr := fakes.NewFakeTransport([]byte("answer"))
	_, conn, err := tr.Accept(context.Background(), []byte("offer"))
	if err != nil {
		t.Fatalf("accept: %v", err)
	}
	fake, ok := conn.(*fakes.FakeMediaConn)
	if !ok {
		t.Fatalf("FakeTransport returned %T, want *fakes.FakeMediaConn", conn)
	}
	return fake
}

// TestTheInterviewBeginsWhenTheInterviewersAudioStartsArriving is the
// regression test for a dead path one level above the greeting dead-end:
// cmdInterviewerJoined had no producer anywhere in production, so CONNECTING
// was terminal, GREETING was unreachable, and no interview could ever start.
// It looked exercised only because tests injected the command by hand.
func TestTheInterviewBeginsWhenTheInterviewersAudioStartsArriving(t *testing.T) {
	defer goleak.VerifyNone(t)

	a, _, _ := newActorWithDeps(true, Deps{})
	defer a.timers.cancelAll()

	speaker := fakes.NewFakeSpeaker()
	sess, err := speaker.Start(context.Background(), ports.SessionCfg{SessionID: "s1"})
	if err != nil {
		t.Fatalf("start speaker: %v", err)
	}
	a.speaking = sess

	if a.state != StateConnecting {
		t.Fatalf("state = %s, want CONNECTING at the start", a.state)
	}
	a.handleMic(context.Background(), micFrame{Frame: ports.Frame{
		PCM: make([]byte, 320), SampleRateHz: 16000,
	}})

	if a.state != StateGreeting {
		t.Fatalf("state = %s, want GREETING once the interviewer's audio arrives", a.state)
	}
}

// TestPersonaAudioIsForwardedToTheMediaConnection matters because the media
// plane and the turn loop were two working halves that never met: the actor
// tracked playout for audio it never sent anywhere, so a browser could attach
// and hear silence.
func TestPersonaAudioIsForwardedToTheMediaConnection(t *testing.T) {
	defer goleak.VerifyNone(t)

	a, _, _ := newActorWithDeps(true, Deps{})
	defer a.timers.cancelAll()

	conn := acceptFakeMedia(t)
	a.mediaConn = conn
	a.state = StateSpeaking

	a.handleSpeakerEvent(context.Background(), ports.AudioDelta{
		Frame:      ports.Frame{PCM: make([]byte, 480), SampleRateHz: 24000},
		ResponseID: "r1",
		ItemID:     "i1",
	})

	if got := len(conn.SentAudio()); got != 1 {
		t.Fatalf("%d frames reached the browser, want 1", got)
	}
}

// TestPlayoutIsTrackedByItemIDSoHeartbeatsCanMatch matters because the browser
// echoes back the item id it was sent. Tracking a response id instead means no
// heartbeat ever matches, and heardMs silently degrades to "assume it all
// played" — which truncates a barge-in in the wrong place, every time.
func TestPlayoutIsTrackedByItemIDSoHeartbeatsCanMatch(t *testing.T) {
	defer goleak.VerifyNone(t)

	a, clock, _ := newActorWithDeps(true, Deps{})
	defer a.timers.cancelAll()
	a.state = StateSpeaking

	a.handleSpeakerEvent(context.Background(), ports.AudioDelta{
		Frame:      ports.Frame{PCM: make([]byte, 24000*2), SampleRateHz: 24000},
		ResponseID: "response-1",
		ItemID:     "item-1",
	})

	// A heartbeat naming the item the browser was actually sent must land.
	a.playout.heartbeat("item-1", 500, clock.Now())
	if got := a.playout.heardMs(clock.Now()); got != 500 {
		t.Fatalf("heardMs = %d after a matching heartbeat, want 500; the tracker is keyed on the wrong id", got)
	}
}

// TestMediaPumpDeliversMicAudioHeartbeatsAndOnsets covers the seam itself.
func TestMediaPumpDeliversMicAudioHeartbeatsAndOnsets(t *testing.T) {
	defer goleak.VerifyNone(t)

	a, _, _ := newActorWithDeps(true, Deps{})
	defer a.timers.cancelAll()

	conn := acceptFakeMedia(t)
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan struct{})
	go func() { defer close(done); pumpMediaConn(ctx, conn, a) }()
	defer func() {
		cancel()
		<-done
	}()

	conn.PushAudioIn(ports.Frame{PCM: make([]byte, 320), SampleRateHz: 16000})
	conn.PushHeartbeat(ports.PlayoutHeartbeat{ItemID: "item-1", HeardMs: 250})
	conn.PushSpeech(ports.VADEvent{Started: true, EnergyDB: -20})

	// Plain blocking receives: internal/session may not call time.After even
	// in tests (layering rule 6, so that turn timing is always FakeClock
	// driven). A message that never arrives hangs until the package test
	// timeout, which reports it just as clearly.
	<-a.micAudio
	if hb := <-a.playoutBeat; hb.ItemID != "item-1" || hb.PlayedMs != 250 {
		t.Fatalf("heartbeat = %+v, want item-1 at 250 ms", hb)
	}
	if ev := <-a.speechOnset; !ev.Started {
		t.Fatal("an offset was forwarded as an onset")
	}
}

// TestASpeechOnsetInterruptsAPersonaThatYields is what makes barge-in real:
// with the vendor's own voice detection disabled, the engine's detector is the
// only thing that knows the interviewer has started talking.
func TestASpeechOnsetInterruptsAPersonaThatYields(t *testing.T) {
	defer goleak.VerifyNone(t)

	a, clock, _ := newActorWithDeps(true, Deps{})
	defer a.timers.cancelAll()

	speaker := fakes.NewFakeSpeaker()
	if _, err := speaker.Start(context.Background(), ports.SessionCfg{SessionID: "s1"}); err != nil {
		t.Fatalf("start speaker: %v", err)
	}
	a.speaking = speaker.LastSession()
	a.state = StateSpeaking
	a.playout.begin("item-1", clock.Now())

	a.handleSpeechOnset(context.Background(), ports.VADEvent{Started: true, EnergyDB: -20})

	if a.state != StateListening {
		t.Fatalf("state = %s, want LISTENING after a barge-in", a.state)
	}
	if got := speaker.LastSession().CancelCount(); got != 1 {
		t.Fatalf("CancelResponse called %d times, want 1", got)
	}
}

// TestWithNoTranscriberTheEnergyDetectorEndsTheTurn is plan §11 row 4, which
// was promised and absent. With no Transcriber nothing could produce the final
// partial that ends a turn, so a live session reached GREETING and stayed
// there — the interviewer spoke, the persona never answered, and no event said
// why.
func TestWithNoTranscriberTheEnergyDetectorEndsTheTurn(t *testing.T) {
	defer goleak.VerifyNone(t)

	a, _, log := newActorWithDeps(true, Deps{})
	defer a.timers.cancelAll()
	ctx := context.Background()

	speaker := fakes.NewFakeSpeaker()
	if _, err := speaker.Start(ctx, ports.SessionCfg{SessionID: "s1"}); err != nil {
		t.Fatalf("start speaker: %v", err)
	}
	a.speaking = speaker.LastSession()
	a.transcriber = nil // degraded:asr

	a.handleMic(ctx, micFrame{Frame: ports.Frame{PCM: make([]byte, 320), SampleRateHz: 16000}})
	if a.state != StateGreeting {
		t.Fatalf("state = %s, want GREETING", a.state)
	}

	a.handleSpeechOnset(ctx, ports.VADEvent{Started: true, EnergyDB: -11})
	a.handleSpeechOnset(ctx, ports.VADEvent{Started: false, EnergyDB: -60})

	if a.state != StateSpeaking {
		t.Fatalf("state = %s, want SPEAKING: the energy detector must end the turn when no Transcriber exists", a.state)
	}
	if !strings.Contains(log.String(), "degraded_end_of_turn") {
		t.Fatal("the degraded end-of-turn path left no trace in the event log")
	}
}

// TestWithATranscriberRunningTheEnergyDetectorDoesNotEndTheTurn is the other
// half of D6, and the more important one: an energy threshold cannot tell a
// thinking pause from a finished question, and cutting the interviewer off
// mid-question breaks the exact behaviour the session exists to assess.
func TestWithATranscriberRunningTheEnergyDetectorDoesNotEndTheTurn(t *testing.T) {
	defer goleak.VerifyNone(t)

	a, _, _ := newActorWithDeps(true, Deps{})
	defer a.timers.cancelAll()
	ctx := context.Background()

	speaker := fakes.NewFakeSpeaker()
	if _, err := speaker.Start(ctx, ports.SessionCfg{SessionID: "s1"}); err != nil {
		t.Fatalf("start speaker: %v", err)
	}
	a.speaking = speaker.LastSession()
	a.transcriber = fakes.NewFakeTranscriber()

	a.handleMic(ctx, micFrame{Frame: ports.Frame{PCM: make([]byte, 320), SampleRateHz: 16000}})
	a.handleSpeechOnset(ctx, ports.VADEvent{Started: true, EnergyDB: -11})
	a.handleSpeechOnset(ctx, ports.VADEvent{Started: false, EnergyDB: -60})

	if a.state != StateGreeting {
		t.Fatalf("state = %s, want GREETING still: a pause is not an end-of-turn while ASR is running", a.state)
	}
}

// TestTheSpeakersOwnTranscriptionSuppliesTheUtteranceText matters because on
// the degraded path the energy detector supplies only a boundary. Verified
// live: the vendor's input transcription still fires with its automatic voice
// detection off, which is what makes it usable as the ASR fallback.
func TestTheSpeakersOwnTranscriptionSuppliesTheUtteranceText(t *testing.T) {
	defer goleak.VerifyNone(t)

	a, _, _ := newActorWithDeps(true, Deps{})
	defer a.timers.cancelAll()

	a.handleSpeakerEvent(context.Background(), ports.InputTranscript{Text: "Tell me about Redis."})
	if a.utterance != "Tell me about Redis." {
		t.Fatalf("utterance = %q, want the Speaker's own transcription", a.utterance)
	}
}

// TestANonYieldingPersonaStillHearsTheFirstQuestion is the second fault that
// counting GREETING as speaking-ish caused, and the more damaging one: the mic
// gate closed during the greeting, so a persona with barge_in_allowed=false
// never received the interviewer's opening question at all.
func TestANonYieldingPersonaStillHearsTheFirstQuestion(t *testing.T) {
	defer goleak.VerifyNone(t)

	a, _, _ := newActorWithDeps(false, Deps{}) // barge-in NOT allowed
	defer a.timers.cancelAll()
	ctx := context.Background()

	speaker := fakes.NewFakeSpeaker()
	if _, err := speaker.Start(ctx, ports.SessionCfg{SessionID: "s1"}); err != nil {
		t.Fatalf("start speaker: %v", err)
	}
	a.speaking = speaker.LastSession()

	a.handleMic(ctx, micFrame{Frame: ports.Frame{PCM: make([]byte, 320), SampleRateHz: 16000}})
	if a.state != StateGreeting {
		t.Fatalf("state = %s, want GREETING", a.state)
	}
	a.handleMic(ctx, micFrame{Frame: ports.Frame{PCM: make([]byte, 320), SampleRateHz: 16000}})

	if got := len(speaker.LastSession().SentAudio()); got == 0 {
		t.Fatal("no interviewer audio reached the Speaker during the greeting; the persona never hears the first question")
	}
}

// TestTheInterviewersFirstWordDoesNotBargeOutOfTheGreeting pins the other half.
func TestTheInterviewersFirstWordDoesNotBargeOutOfTheGreeting(t *testing.T) {
	defer goleak.VerifyNone(t)

	a, _, _ := newActorWithDeps(true, Deps{})
	defer a.timers.cancelAll()
	ctx := context.Background()

	speaker := fakes.NewFakeSpeaker()
	if _, err := speaker.Start(ctx, ports.SessionCfg{SessionID: "s1"}); err != nil {
		t.Fatalf("start speaker: %v", err)
	}
	a.speaking = speaker.LastSession()

	a.handleMic(ctx, micFrame{Frame: ports.Frame{PCM: make([]byte, 320), SampleRateHz: 16000}})
	a.handleSpeechOnset(ctx, ports.VADEvent{Started: true, EnergyDB: -11})

	if a.state != StateGreeting {
		t.Fatalf("state = %s, want GREETING: there is no persona audio to interrupt yet", a.state)
	}
}

// TestASlowStallBankDegradesRatherThanEndingTheInterview is the regression
// test for a connect bug whose symptom pointed at entirely the wrong
// component.
//
// The connector waits for every collaborator on one deadline. On timeout it
// used to mark the *Speaker* failed regardless of who was slow — overwriting a
// Speaker that had already started successfully. Because the Speaker is the
// one fatal collaborator, a slow stall bank therefore ended the interview
// instead of degrading it, and the log blamed the mouth. Live, the Speaker had
// come up in 847 ms while pre-synthesis was still running.
func TestASlowStallBankDegradesRatherThanEndingTheInterview(t *testing.T) {
	defer goleak.VerifyNone(t)

	speaker := fakes.NewFakeSpeaker()
	bank := &slowStallBank{released: make(chan struct{})}

	a, clock, log := newActorWithDeps(true, Deps{
		Speaker:        speaker,
		Stall:          bank,
		ConnectTimeout: 5 * time.Second,
	})
	defer a.timers.cancelAll()

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	done := make(chan struct{})
	go func() {
		defer close(done)
		a.connect(ctx, ports.SessionCfg{SessionID: "s1"}, ports.PersonaCtx{})
	}()

	// Let the Speaker finish, then blow the budget with the stall bank still
	// warming.
	waitUntil(t, "the speaker to start", func() bool { return speaker.LastSession() != nil })
	clock.Advance(6 * time.Second)

	// A plain blocking receive: internal/session may not call time.After even
	// in tests (layering rule 6). A hand-off that never happens hangs until
	// the package test timeout, which reports it just as clearly.
	cmd := <-a.control
	if cmd.Kind != cmdConnected {
		t.Fatalf("connector sent %v, want cmdConnected: a slow stall bank must degrade, not end the session", cmd.Kind)
	}
	if cmd.Connected == nil || !cmd.Connected.StallFailed {
		t.Fatal("the stall bank timeout was not recorded as a degradation")
	}

	close(bank.released)
	<-done
	_ = log
}

// waitUntil polls a condition, failing rather than hanging. It does not use
// the session clock: this waits on another goroutine's progress, not on
// session time.
func waitUntil(t *testing.T, what string, cond func() bool) {
	t.Helper()
	for range 5000 {
		if cond() {
			return
		}
		time.Sleep(time.Millisecond)
	}
	t.Fatalf("timed out waiting for %s", what)
}

// slowStallBank blocks in Warm until released or the context ends.
type slowStallBank struct{ released chan struct{} }

func (b *slowStallBank) Warm(ctx context.Context) error {
	select {
	case <-b.released:
		return nil
	case <-ctx.Done():
		return ctx.Err()
	}
}
func (b *slowStallBank) PickStall() (ports.PCM16Audio, int, bool) {
	return ports.PCM16Audio{}, 0, false
}
func (b *slowStallBank) OpeningLine() (ports.PCM16Audio, bool) { return ports.PCM16Audio{}, false }

// TestTheOpeningLineClipActuallyReachesTheBrowser matters because everything
// around it worked without it: the bank warmed, the turn was timed from the
// clip's real duration, the playout alarm fired and the session moved on — and
// the interviewer heard silence, because nothing ever sent the audio.
func TestTheOpeningLineClipActuallyReachesTheBrowser(t *testing.T) {
	defer goleak.VerifyNone(t)

	a, _, _ := newActorWithDeps(true, Deps{})
	defer a.timers.cancelAll()
	ctx := context.Background()

	conn := acceptFakeMedia(t)
	a.mediaConn = conn
	a.stall = fakes.NewFakeStallBank(ports.PCM16Audio{
		Samples:      make([]byte, 24000*2), // one second
		SampleRateHz: 24000,
	})
	if err := a.stall.Warm(ctx); err != nil {
		t.Fatalf("warm: %v", err)
	}

	d := a.playClip(ctx, "Hi, I'm Mateo.")

	if d != time.Second {
		t.Fatalf("clip duration = %v, want 1s measured from the clip itself", d)
	}
	sent := conn.SentAudio()
	if len(sent) != 1 {
		t.Fatalf("%d frames reached the browser, want the clip", len(sent))
	}
	if len(sent[0].PCM) != 24000*2 {
		t.Fatalf("sent %d bytes, want the whole clip; a partial opening line is worse than none", len(sent[0].PCM))
	}
}

// TestAMissingClipStillTimesTheTurn matters because the degraded path is the
// one that runs whenever pre-synthesis failed. A persona that opens silently
// is a blemish; one that hangs in SPEAKING forever is a dead interview.
func TestAMissingClipStillTimesTheTurn(t *testing.T) {
	defer goleak.VerifyNone(t)

	a, _, log := newActorWithDeps(true, Deps{})
	defer a.timers.cancelAll()
	a.mediaConn = acceptFakeMedia(t)

	if d := a.playClip(context.Background(), "Hi there."); d <= 0 {
		t.Fatalf("duration = %v with no clip; the turn would never end", d)
	}
	if !strings.Contains(log.String(), "clip_unavailable") {
		t.Fatal("running without a clip left no trace in the event log")
	}
}
