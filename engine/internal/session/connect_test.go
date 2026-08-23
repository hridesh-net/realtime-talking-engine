package session

import (
	"context"
	"errors"
	"strings"
	"sync"
	"testing"
	"time"

	"go.uber.org/goleak"

	"skillbrew/engine/internal/fakes"
	"skillbrew/engine/internal/ports"
)

// syncBuffer is a mutex-guarded string sink. The plain strings.Builder the
// rest of this package's tests use (see newTestEventLog) is fine when
// nothing reads it until after the actor has fully stopped — the tests in
// this file poll the log content *while the session is still running*, so
// the write (the actor's own goroutine, via obs.EventLog) and the read
// (this test's polling loop) are genuinely concurrent and need their own
// synchronization, not just EventLog's.
type syncBuffer struct {
	mu  sync.Mutex
	buf strings.Builder
}

func (s *syncBuffer) Write(p []byte) (int, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.buf.Write(p)
}

func (s *syncBuffer) String() string {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.buf.String()
}

// errConnectBoom is the scripted failure this file injects into fakes to
// drive the connect failure paths.
var errConnectBoom = errors.New("connect_test: boom")

// connectTestConnectTimeout is the connect budget every rig in this file
// uses unless a test needs a different one (the slow-vendor test) — long
// enough that no test here accidentally races it, short enough that the
// timeout test's own Advance is a small, readable number.
const connectTestConnectTimeout = 15 * time.Second

// connectRig is the actor and its running owner goroutine, wired for the
// connect path: a FakeTransport plus whatever Speaker/Transcriber the
// caller supplies. log captures the session's event stream so tests can
// assert on what was recorded without touching owner-goroutine-only actor
// fields from the test goroutine.
type connectRig struct {
	actor     *actor
	clock     *fakes.FakeClock
	log       *syncBuffer
	transport *fakes.FakeTransport
	ctx       context.Context
	cancel    context.CancelFunc
	done      chan struct{}
}

func newConnectRig(t *testing.T, deps Deps, connectTimeout time.Duration) *connectRig {
	t.Helper()
	clock := fakes.NewFakeClock(testNow)
	log := &syncBuffer{}
	events := newTestEventLog(log)
	transport := fakes.NewFakeTransport([]byte("answer-sdp"))
	deps.Transport = transport
	deps.ConnectTimeout = connectTimeout
	a := newActor("sess-connect", testContract(true), clock, quietLogger(), events, deps)

	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan struct{})
	go a.run(ctx, done)

	return &connectRig{actor: a, clock: clock, log: log, transport: transport, ctx: ctx, cancel: cancel, done: done}
}

// attach sends cmdAttachTransport and blocks for its synchronous reply —
// the same round trip Manager.AttachTransport does against the actor.
func (r *connectRig) attach(t *testing.T, offer []byte) attachOutcome {
	t.Helper()
	reply := make(chan attachOutcome, 1)
	r.actor.control <- command{Kind: cmdAttachTransport, Offer: offer, Reply: reply}
	return <-reply
}

// stop sends cmdStop and waits for the owner goroutine to fully exit. It
// deliberately does not cancel r.ctx — cmdStop is the graceful, in-character
// stop path, distinct from context cancellation, and a test proving cmdStop
// alone must not strand a connector would be meaningless if this quietly
// cancelled ctx too. Callers still own a deferred r.cancel() for final
// cleanup once the test's assertions are done.
func (r *connectRig) stop(t *testing.T) {
	t.Helper()
	r.actor.control <- command{Kind: cmdStop, Reason: "test cleanup"}
	<-r.done
}

// waitForEventCount polls the event log — internal/session may not call
// time.Now or time.After, including in test files, so this is a bounded
// retry loop on time.Sleep rather than a deadline computed from the real
// clock. EventLog.Count() is mutex-guarded, and every actor emit happens
// on the owner goroutine strictly before the Count() the actor's own next
// Emit call would observe, so once Count() reaches n here it is race-free
// to read the log's accumulated text.
func waitForEventCount(t *testing.T, log interface{ Count() int }, n int) {
	t.Helper()
	for i := 0; i < 400; i++ {
		if log.Count() >= n {
			return
		}
		time.Sleep(5 * time.Millisecond)
	}
	t.Fatalf("event log never reached %d events (got %d)", n, log.Count())
}

// waitClosed blocks, via a bounded time.Sleep retry rather than a real
// deadline, until ch closes, failing the test with msg if it never does
// within the budget. internal/session bans time.Now/time.After even in
// test files (the arch gate scans this whole directory), which is why this
// is a poll loop and not a select against time.After.
func waitClosed(t *testing.T, ch <-chan struct{}, msg string) {
	t.Helper()
	for i := 0; i < 400; i++ {
		select {
		case <-ch:
			return
		default:
		}
		time.Sleep(5 * time.Millisecond)
	}
	t.Fatal(msg)
}

// ---------------------------------------------------------------------------
// Failure classification.
// ---------------------------------------------------------------------------

// TestAttachTransportWithNoSpeakerConfiguredWindsTheSessionDownSynchronously
// covers the other fatal-Speaker path: no connector ever runs because there
// is no ports.Speaker to spawn one for (cmd/engined's own wiring today,
// ahead of the real adapter landing). The media handshake still succeeds —
// the caller gets its answer — but the session must still end with
// end_reason "error" and the owner loop must actually exit, not just
// transition state and keep looping.
func TestAttachTransportWithNoSpeakerConfiguredWindsTheSessionDownSynchronously(t *testing.T) {
	defer goleak.VerifyNone(t)

	r := newConnectRig(t, Deps{}, connectTestConnectTimeout) // no Speaker
	defer r.cancel()

	out := r.attach(t, []byte("offer"))
	if out.Err != nil {
		t.Fatalf("attach transport: %v, want the offer still accepted", out.Err)
	}
	if len(out.Answer) == 0 {
		t.Fatal("attach transport returned no answer despite Transport.Accept succeeding")
	}

	waitClosed(t, r.done, "session never wound down (or the owner loop never exited) with no Speaker configured")

	got := r.log.String()
	if !strings.Contains(got, `"reason":"error"`) {
		t.Fatalf("event log missing a state transition with reason \"error\":\n%s", got)
	}
}

// TestAttachTransportWithNoTransportConfiguredIsFatalToo covers the
// Transport half of "Speaker and Transport are fatal": with no
// ports.Transport at all, Accept can never even be attempted, so the reply
// carries the error instead of an answer — but the session must still wind
// down and the owner loop must still exit, exactly like a nil Speaker.
func TestAttachTransportWithNoTransportConfiguredIsFatalToo(t *testing.T) {
	defer goleak.VerifyNone(t)

	clock := fakes.NewFakeClock(testNow)
	var log syncBuffer
	events := newTestEventLog(&log)
	speaker := fakes.NewFakeSpeaker()
	a := newActor("sess-no-transport", testContract(true), clock, quietLogger(), events, Deps{
		Speaker: speaker, ConnectTimeout: connectTestConnectTimeout,
	}) // no Transport
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	done := make(chan struct{})
	go a.run(ctx, done)

	reply := make(chan attachOutcome, 1)
	a.control <- command{Kind: cmdAttachTransport, Offer: []byte("offer"), Reply: reply}
	out := <-reply
	if !errors.Is(out.Err, ErrNoTransportConfigured) {
		t.Fatalf("attach transport error = %v, want ErrNoTransportConfigured", out.Err)
	}

	waitClosed(t, done, "session never wound down (or the owner loop never exited) with no Transport configured")

	got := log.String()
	if !strings.Contains(got, `"reason":"error"`) {
		t.Fatalf("event log missing a state transition with reason \"error\":\n%s", got)
	}
}

// TestConnectFailureOfTheSpeakerWindsTheSessionDownWithEndReasonError proves
// the fatal half of the connect failure classification: no mouth, no
// interview. The Speaker is the one collaborator whose failure must end the
// session, not degrade it.
func TestConnectFailureOfTheSpeakerWindsTheSessionDownWithEndReasonError(t *testing.T) {
	defer goleak.VerifyNone(t)

	speaker := fakes.NewFakeSpeaker()
	speaker.SetStartError(errConnectBoom)
	r := newConnectRig(t, Deps{Speaker: speaker}, connectTestConnectTimeout)
	defer r.cancel()

	out := r.attach(t, []byte("offer"))
	if out.Err != nil {
		t.Fatalf("attach transport: %v, want the offer accepted despite the Speaker failing later", out.Err)
	}

	// A fatal connect failure winds the session down on its own; no
	// further command is needed. r.done closing is the synchronization
	// point.
	waitClosed(t, r.done, "session never wound down after a fatal Speaker connect failure")

	got := r.log.String()
	if !strings.Contains(got, `"connect_failed"`) {
		t.Fatalf("event log missing connect_failed:\n%s", got)
	}
	if !strings.Contains(got, `"reason":"error"`) {
		t.Fatalf("event log missing a state transition with reason \"error\":\n%s", got)
	}
	r.cancel()
}

// TestATranscriberFailureDegradesTheSessionInsteadOfEndingIt proves the
// non-fatal half: a Transcriber that fails to connect flags the session
// degraded:asr and the session keeps running, because the Speaker — the
// one collaborator that matters for "is there an interview at all" —
// still connected.
func TestATranscriberFailureDegradesTheSessionInsteadOfEndingIt(t *testing.T) {
	defer goleak.VerifyNone(t)

	speaker := fakes.NewFakeSpeaker()
	transcriber := fakes.NewFakeTranscriber()
	transcriber.SetStartError(errConnectBoom)
	r := newConnectRig(t, Deps{Speaker: speaker, Transcriber: transcriber}, connectTestConnectTimeout)
	defer r.cancel()

	out := r.attach(t, []byte("offer"))
	if out.Err != nil {
		t.Fatalf("attach transport: %v", out.Err)
	}

	waitForEventCount(t, r.actor.events, 1)
	// Poll until the degradation event specifically lands, rather than
	// asserting on the first event emitted — transport_attached beats it.
	for i := 0; i < 400; i++ {
		if strings.Contains(r.log.String(), degradedASR) {
			break
		}
		time.Sleep(5 * time.Millisecond)
	}
	got := r.log.String()
	if !strings.Contains(got, degradedASR) {
		t.Fatalf("event log missing %s:\n%s", degradedASR, got)
	}
	if strings.Contains(got, `"connect_failed"`) {
		t.Fatalf("a non-fatal Transcriber failure must not fail the connect:\n%s", got)
	}

	// The session must still be running — no wind-down, no session_stopped.
	select {
	case <-r.done:
		t.Fatal("session ended after a non-fatal Transcriber failure, want it still running")
	default:
	}

	r.stop(t)
}

// ---------------------------------------------------------------------------
// Cleanup ownership.
// ---------------------------------------------------------------------------

// TestStoppingMidConnectClosesEverythingTheConnectorHadAlreadyStarted is the
// leak test: a cmdStop arriving while Speaker.Start is still in flight must
// not strand it. The connector keeps waiting for Start to actually return
// (it cannot abandon a still-running goroutine without leaking it), and
// once it does — after the stop already happened — the connector notices
// the actor is gone and closes the session itself instead of handing it
// off to nobody.
func TestStoppingMidConnectClosesEverythingTheConnectorHadAlreadyStarted(t *testing.T) {
	defer goleak.VerifyNone(t)

	speaker := fakes.NewFakeSpeaker()
	speaker.SetStartBlocking(true)
	r := newConnectRig(t, Deps{Speaker: speaker}, connectTestConnectTimeout)
	defer r.cancel()

	out := r.attach(t, []byte("offer"))
	if out.Err != nil {
		t.Fatalf("attach transport: %v", out.Err)
	}

	waitClosed(t, speaker.StartBlocked(), "Speaker.Start never entered its block")

	// Stop the session while Start is still blocked — cmdStop exits the
	// owner loop without cancelling ctx, so this is exactly the case a
	// select on ctx.Done() alone would miss.
	r.stop(t)

	// Now let the "vendor" finally answer, three seconds too late.
	speaker.Release()

	var sess *fakes.FakeSpeakerSession
	for i := 0; i < 400; i++ {
		if s := speaker.LastSession(); s != nil {
			sess = s
			break
		}
		time.Sleep(5 * time.Millisecond)
	}
	if sess == nil {
		t.Fatal("Speaker.Start never produced a session after Release")
	}
	for i := 0; i < 400; i++ {
		if sess.Closed() {
			break
		}
		time.Sleep(5 * time.Millisecond)
	}
	if !sess.Closed() {
		t.Fatal("the connector must close a Speaker session that lands after the actor already stopped")
	}
}

// TestAttachingATransportTwiceIsConflictNotASecondConnector proves a second
// AttachTransport call is rejected as a conflict before it ever spawns a
// second connector — not merely that the second connector eventually loses
// a race.
func TestAttachingATransportTwiceIsConflictNotASecondConnector(t *testing.T) {
	defer goleak.VerifyNone(t)

	speaker := fakes.NewFakeSpeaker()
	speaker.SetStartBlocking(true) // keep the first connector from ever finishing
	r := newConnectRig(t, Deps{Speaker: speaker}, connectTestConnectTimeout)
	defer r.cancel()

	first := r.attach(t, []byte("offer-1"))
	if first.Err != nil {
		t.Fatalf("first attach: %v", first.Err)
	}
	waitClosed(t, speaker.StartBlocked(), "Speaker.Start never entered its block")

	second := r.attach(t, []byte("offer-2"))
	if !errors.Is(second.Err, ErrTransportAlreadyAttached) {
		t.Fatalf("second attach error = %v, want ErrTransportAlreadyAttached", second.Err)
	}
	if got := len(r.transport.Offers()); got != 1 {
		t.Fatalf("transport.Accept called %d times, want 1 — the second attempt must never reach it", got)
	}

	speaker.Release()
	r.stop(t)
}

// ---------------------------------------------------------------------------
// The connect timeout.
// ---------------------------------------------------------------------------

// TestASlowVendorStartIsBoundedByTheConnectTimeout proves the connector
// gives up on a Speaker that never answers, bounded by connectTimeout on
// the injected Clock — never a real deadline, so this test advances no
// real time.
func TestASlowVendorStartIsBoundedByTheConnectTimeout(t *testing.T) {
	defer goleak.VerifyNone(t)

	const timeout = 15 * time.Second
	speaker := fakes.NewFakeSpeaker()
	speaker.SetStartBlocking(true)
	r := newConnectRig(t, Deps{Speaker: speaker}, timeout)
	defer r.cancel()

	out := r.attach(t, []byte("offer"))
	if out.Err != nil {
		t.Fatalf("attach transport: %v", out.Err)
	}
	waitClosed(t, speaker.StartBlocked(), "Speaker.Start never entered its block")

	// The FakeClock timer backing the connect budget is armed by the
	// connector as soon as it starts, concurrently with the block above —
	// Advance must happen after we know Start is in flight, or the
	// connector may not have called clock.After yet. A short bounded poll
	// on Pending() avoids a race without touching real time.
	for i := 0; i < 400; i++ {
		if len(r.clock.Pending()) > 0 {
			break
		}
		time.Sleep(5 * time.Millisecond)
	}
	r.clock.Advance(timeout)

	waitClosed(t, r.done, "session never wound down after the connect timeout elapsed")

	got := r.log.String()
	if !strings.Contains(got, `"connect_failed"`) {
		t.Fatalf("event log missing connect_failed:\n%s", got)
	}
	if !strings.Contains(got, `"reason":"error"`) {
		t.Fatalf("event log missing a state transition with reason \"error\":\n%s", got)
	}
}

// ---------------------------------------------------------------------------
// The Speaker event pump.
// ---------------------------------------------------------------------------

// TestAudioOverloadDropsOldestFramesWhileControlEventsAllArrive proves both
// channel policies of the Speaker event pump at once: AudioDelta sheds the
// oldest frame under overload, while every other event still arrives,
// blocking, in order.
func TestAudioOverloadDropsOldestFramesWhileControlEventsAllArrive(t *testing.T) {
	defer goleak.VerifyNone(t)

	tape := []ports.SpeakerEvent{
		ports.AudioDelta{Frame: ports.Frame{PCM: []byte{1}}, ResponseID: "r1"},
		ports.AudioDelta{Frame: ports.Frame{PCM: []byte{2}}, ResponseID: "r2"},
		ports.AudioDelta{Frame: ports.Frame{PCM: []byte{3}}, ResponseID: "r3"},
		ports.OutputTranscriptDelta{Text: "hello"},
		ports.AudioDelta{Frame: ports.Frame{PCM: []byte{4}}, ResponseID: "r4"},
		ports.SpeechStarted{AudioStartMs: 10},
		ports.ResponseDone{ResponseID: "r4", ItemID: "item-1"},
	}
	speaker := fakes.NewFakeSpeaker(tape...)
	sess, err := speaker.Start(context.Background(), ports.SessionCfg{SessionID: "sess-pump"})
	if err != nil {
		t.Fatalf("Start: %v", err)
	}

	audio := make(chan ports.SpeakerEvent, 2) // small on purpose: force a drop with only 4 audio events
	ctrl := make(chan ports.SpeakerEvent, 8)  // large enough that control never blocks the pump here
	var d drops

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	pumpDone := make(chan struct{})
	go func() {
		defer close(pumpDone)
		pumpSpeakerEvents(ctx, sess, audio, ctrl, &d)
	}()

	waitClosed(t, pumpDone, "pump never exited once Events() closed")

	var gotCtrl []ports.SpeakerEvent
	for {
		select {
		case ev := <-ctrl:
			gotCtrl = append(gotCtrl, ev)
			continue
		default:
		}
		break
	}
	if len(gotCtrl) != 3 {
		t.Fatalf("control events received = %d, want 3 (every non-audio event, all arrived): %+v", len(gotCtrl), gotCtrl)
	}
	if _, ok := gotCtrl[0].(ports.OutputTranscriptDelta); !ok {
		t.Fatalf("gotCtrl[0] = %T, want OutputTranscriptDelta", gotCtrl[0])
	}
	if _, ok := gotCtrl[1].(ports.SpeechStarted); !ok {
		t.Fatalf("gotCtrl[1] = %T, want SpeechStarted", gotCtrl[1])
	}
	if _, ok := gotCtrl[2].(ports.ResponseDone); !ok {
		t.Fatalf("gotCtrl[2] = %T, want ResponseDone", gotCtrl[2])
	}

	if len(audio) != 2 {
		t.Fatalf("audio channel holds %d, want 2 (its capacity)", len(audio))
	}
	first := (<-audio).(ports.AudioDelta)
	second := (<-audio).(ports.AudioDelta)
	if first.ResponseID != "r3" || second.ResponseID != "r4" {
		t.Fatalf("audio channel kept {%s, %s}, want {r3, r4} — the two newest frames, oldest shed", first.ResponseID, second.ResponseID)
	}
	if got := d.SpeakerAudio.Load(); got != 2 {
		t.Fatalf("drops.SpeakerAudio = %d, want 2 (r1 and r2 shed)", got)
	}
}

// TestThePumpExitsWhenTheSpeakerEventStreamCloses proves the pump's other
// exit condition: once Events() closes, the pump returns even with no
// control-channel pressure at all.
func TestThePumpExitsWhenTheSpeakerEventStreamCloses(t *testing.T) {
	defer goleak.VerifyNone(t)

	speaker := fakes.NewFakeSpeaker(ports.OutputTranscriptDelta{Text: "hi"})
	sess, err := speaker.Start(context.Background(), ports.SessionCfg{SessionID: "sess-pump-close"})
	if err != nil {
		t.Fatalf("Start: %v", err)
	}

	audio := make(chan ports.SpeakerEvent, 4)
	ctrl := make(chan ports.SpeakerEvent, 4)
	var d drops

	ctx := context.Background()
	pumpDone := make(chan struct{})
	go func() {
		defer close(pumpDone)
		pumpSpeakerEvents(ctx, sess, audio, ctrl, &d)
	}()

	waitClosed(t, pumpDone, "pump never exited after Events() closed (tape exhausted)")
}

// TestThePumpExitsOnCtxCancellationEvenWhileBlockedSendingToAFullControlChannel
// is the guard for the escape required on every blocking send: a control
// event the actor's loop has stopped draining must not strand the pump
// forever, even though Events() itself may never close. Without the
// `case <-ctx.Done()` arm inside the blocking send, this deadlocks and
// goleak catches the stranded pump goroutine — see the re-introduction
// proof recorded for this work item.
func TestThePumpExitsOnCtxCancellationEvenWhileBlockedSendingToAFullControlChannel(t *testing.T) {
	defer goleak.VerifyNone(t)

	speaker := fakes.NewFakeSpeaker(
		ports.OutputTranscriptDelta{Text: "one"},
		ports.OutputTranscriptDelta{Text: "two"},
	)
	sess, err := speaker.Start(context.Background(), ports.SessionCfg{SessionID: "sess-pump-stuck"})
	if err != nil {
		t.Fatalf("Start: %v", err)
	}

	audio := make(chan ports.SpeakerEvent, 4)
	ctrl := make(chan ports.SpeakerEvent, 1) // capacity 1: the second control event has nowhere to go
	var d drops

	ctx, cancel := context.WithCancel(context.Background())
	pumpDone := make(chan struct{})
	go func() {
		defer close(pumpDone)
		pumpSpeakerEvents(ctx, sess, audio, ctrl, &d)
	}()

	// Let the first event fill ctrl, so the pump is now blocked trying to
	// send the second one, with nobody draining ctrl.
	for i := 0; i < 400; i++ {
		if len(ctrl) == 1 {
			break
		}
		time.Sleep(5 * time.Millisecond)
	}
	if len(ctrl) != 1 {
		t.Fatal("control channel never filled — the pump isn't stuck on the second send as this test requires")
	}

	cancel()

	waitClosed(t, pumpDone, "pump did not exit on ctx cancellation while blocked sending to a full control channel")
}
