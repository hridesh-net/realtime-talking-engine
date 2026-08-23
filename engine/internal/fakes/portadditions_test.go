// Tests for the M1.4 port additions: FakeSpeaker's blocking mode, and the
// new FakeTransport/FakeMediaConn, FakeStallBank, FakeRecorder,
// FakeFinalizer, and FakeJudge fakes.
package fakes_test

import (
	"context"
	"errors"
	"reflect"
	"testing"
	"time"

	"go.uber.org/goleak"

	"skillbrew/engine/internal/fakes"
	"skillbrew/engine/internal/ports"
)

var errBoom = errors.New("fakes_test: boom")

// TestFakeSpeakerSession_Blocking proves the blocking mode this work item
// added actually blocks a mutating call until Release, and unblocks it once
// Release is called — the property that makes the "SpeakerSession mutating
// methods must not block on network I/O" contract testable at all.
func TestFakeSpeakerSession_Blocking(t *testing.T) {
	defer goleak.VerifyNone(t)
	speaker := fakes.NewFakeSpeaker()
	ctx := context.Background()
	sess, err := speaker.Start(ctx, ports.SessionCfg{SessionID: "sess-block"})
	if err != nil {
		t.Fatalf("Start: %v", err)
	}
	fake, ok := sess.(*fakes.FakeSpeakerSession)
	if !ok {
		t.Fatalf("Start returned %T, want *fakes.FakeSpeakerSession", sess)
	}

	fake.SetBlocking(fakes.BlockSendAudio)

	done := make(chan error, 1)
	go func() {
		done <- fake.SendAudio(ctx, ports.Frame{PCM: []byte{1}})
	}()

	select {
	case <-fake.Blocked():
	case <-time.After(2 * time.Second):
		t.Fatalf("SendAudio never entered its block")
	}

	// It must still be blocked: no return within a short grace window.
	select {
	case err := <-done:
		t.Fatalf("SendAudio returned (err=%v) before Release", err)
	case <-time.After(20 * time.Millisecond):
	}
	if got := fake.SentAudio(); len(got) != 0 {
		t.Fatalf("SentAudio() = %v before Release, want none recorded yet", got)
	}

	fake.Release()

	select {
	case err := <-done:
		if err != nil {
			t.Fatalf("SendAudio after Release = %v, want nil", err)
		}
	case <-time.After(2 * time.Second):
		t.Fatalf("SendAudio never returned after Release")
	}
	if got := fake.SentAudio(); len(got) != 1 {
		t.Fatalf("SentAudio() = %v after Release, want one frame recorded", got)
	}

	if err := fake.Close(ctx); err != nil {
		t.Fatalf("Close: %v", err)
	}
}

// TestFakeSpeakerSession_BlockingReleasedByContext proves a blocked call
// unblocks on its own ctx being cancelled, not only on Release — an
// adapter under a real deadline must not hang forever either.
func TestFakeSpeakerSession_BlockingReleasedByContext(t *testing.T) {
	defer goleak.VerifyNone(t)
	speaker := fakes.NewFakeSpeaker()
	sess, err := speaker.Start(context.Background(), ports.SessionCfg{SessionID: "sess-block-ctx"})
	if err != nil {
		t.Fatalf("Start: %v", err)
	}
	fake := sess.(*fakes.FakeSpeakerSession)
	fake.SetBlocking(fakes.BlockCreateResponse)

	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() {
		done <- fake.CreateResponse(ctx, ports.ResponseDirectives{})
	}()

	select {
	case <-fake.Blocked():
	case <-time.After(2 * time.Second):
		t.Fatalf("CreateResponse never entered its block")
	}

	cancel()
	select {
	case err := <-done:
		if !errors.Is(err, context.Canceled) {
			t.Fatalf("CreateResponse after cancel = %v, want context.Canceled", err)
		}
	case <-time.After(2 * time.Second):
		t.Fatalf("CreateResponse never returned after ctx cancellation")
	}

	fake.Release()
	if err := fake.Close(context.Background()); err != nil {
		t.Fatalf("Close: %v", err)
	}
}

// TestFakeTransport_AcceptAndMediaConn drives FakeTransport.Accept and the
// resulting FakeMediaConn through every direction of traffic: inbound mic
// audio, playout heartbeats, and VAD events pushed in by the test, and
// outbound persona audio recorded by SendAudio.
func TestFakeTransport_AcceptAndMediaConn(t *testing.T) {
	defer goleak.VerifyNone(t)
	transport := fakes.NewFakeTransport([]byte("sdp-answer"))
	ctx := context.Background()

	answer, conn, err := transport.Accept(ctx, []byte("sdp-offer"))
	if err != nil {
		t.Fatalf("Accept: %v", err)
	}
	if string(answer) != "sdp-answer" {
		t.Fatalf("Accept answer = %q, want sdp-answer", answer)
	}
	mc, ok := conn.(*fakes.FakeMediaConn)
	if !ok {
		t.Fatalf("Accept returned %T, want *fakes.FakeMediaConn", conn)
	}
	if got := transport.Offers(); len(got) != 1 || string(got[0]) != "sdp-offer" {
		t.Fatalf("Offers() = %v, want [sdp-offer]", got)
	}
	if got := transport.Conns(); len(got) != 1 || got[0] != mc {
		t.Fatalf("Conns() did not include the produced FakeMediaConn")
	}

	if !mc.PushAudioIn(ports.Frame{PCM: []byte{9}}) {
		t.Fatalf("PushAudioIn on an open conn = false")
	}
	if frame := <-mc.AudioIn(); len(frame.PCM) != 1 || frame.PCM[0] != 9 {
		t.Fatalf("AudioIn() delivered %v, want the pushed frame", frame)
	}

	if !mc.PushHeartbeat(ports.PlayoutHeartbeat{ItemID: "item-1", HeardMs: 500}) {
		t.Fatalf("PushHeartbeat on an open conn = false")
	}
	if hb := <-mc.PlayoutHeartbeats(); hb.ItemID != "item-1" || hb.HeardMs != 500 {
		t.Fatalf("PlayoutHeartbeats() delivered %+v", hb)
	}

	if !mc.PushSpeech(ports.VADEvent{Started: true, EnergyDB: -20}) {
		t.Fatalf("PushSpeech on an open conn = false")
	}
	if v := <-mc.Speech(); !v.Started || v.EnergyDB != -20 {
		t.Fatalf("Speech() delivered %+v", v)
	}

	if err := mc.SendAudio(ctx, ports.Frame{PCM: []byte{1, 2}}); err != nil {
		t.Fatalf("SendAudio: %v", err)
	}
	if got := mc.SentAudio(); len(got) != 1 {
		t.Fatalf("SentAudio() = %v, want one frame", got)
	}

	if err := mc.Close(ctx); err != nil {
		t.Fatalf("Close: %v", err)
	}
	if !mc.Closed() {
		t.Fatalf("Closed() = false after Close")
	}
	if mc.PushAudioIn(ports.Frame{}) {
		t.Fatalf("PushAudioIn after Close = true, want false")
	}
	if err := mc.Close(ctx); err != nil {
		t.Fatalf("second Close: %v, want idempotent nil", err)
	}
}

// TestFakeStallBank_CyclesAndWarms proves PickStall cycles and wraps, and
// Warm/SetWarmError behave as documented.
func TestFakeStallBank_CyclesAndWarms(t *testing.T) {
	defer goleak.VerifyNone(t)
	opening := ports.PCM16Audio{Samples: []byte("opening"), SampleRateHz: 24000}
	a := ports.PCM16Audio{Samples: []byte("a")}
	b := ports.PCM16Audio{Samples: []byte("b")}
	bank := fakes.NewFakeStallBank(opening, a, b)
	ctx := context.Background()

	if err := bank.Warm(ctx); err != nil {
		t.Fatalf("Warm: %v", err)
	}
	if !bank.Warmed() {
		t.Fatalf("Warmed() = false after Warm")
	}
	if got := bank.WarmCalls(); got != 1 {
		t.Fatalf("WarmCalls() = %d, want 1", got)
	}

	if clip, idx, ok := bank.PickStall(); !ok || idx != 0 || string(clip.Samples) != "a" {
		t.Fatalf("first PickStall = %v, %d, %v, want a, 0, true", clip, idx, ok)
	}
	if clip, idx, ok := bank.PickStall(); !ok || idx != 1 || string(clip.Samples) != "b" {
		t.Fatalf("second PickStall = %v, %d, %v, want b, 1, true", clip, idx, ok)
	}
	if clip, idx, ok := bank.PickStall(); !ok || idx != 0 || string(clip.Samples) != "a" {
		t.Fatalf("third PickStall did not wrap around: %v, %d, %v", clip, idx, ok)
	}
	if got := bank.PickCalls(); got != 3 {
		t.Fatalf("PickCalls() = %d, want 3", got)
	}

	if line, ok := bank.OpeningLine(); !ok || string(line.Samples) != "opening" {
		t.Fatalf("OpeningLine() = %v, %v, want opening, true", line, ok)
	}

	bank.SetWarmError(errBoom)
	if err := bank.Warm(ctx); !errors.Is(err, errBoom) {
		t.Fatalf("Warm after SetWarmError = %v, want errBoom", err)
	}
}

// TestFakeStallBank_Empty proves PickStall reports ok=false on a bank with
// no clips, rather than panicking on the modulo.
func TestFakeStallBank_Empty(t *testing.T) {
	defer goleak.VerifyNone(t)
	bank := fakes.NewFakeStallBank(ports.PCM16Audio{})
	if _, _, ok := bank.PickStall(); ok {
		t.Fatalf("PickStall on an empty bank ok = true, want false")
	}
}

// TestFakeRecorder_RecordsAndFinalizes proves every Recorder write is
// captured and Finalize returns the scripted RecordingInfo (or error).
func TestFakeRecorder_RecordsAndFinalizes(t *testing.T) {
	defer goleak.VerifyNone(t)
	info := ports.RecordingInfo{Key: "session/rec.wav", DurationMs: 1000}
	rec := fakes.NewFakeRecorder(info)
	ctx := context.Background()

	rec.WriteHuman(ports.Frame{PCM: []byte{1}})
	rec.WritePersona("item-1", ports.Frame{PCM: []byte{2}})
	rec.TruncatePersona("item-1", 300)

	if got := rec.HumanFrames(); len(got) != 1 {
		t.Fatalf("HumanFrames() = %v, want 1 frame", got)
	}
	if got := rec.PersonaWrites(); len(got) != 1 || got[0].ItemID != "item-1" {
		t.Fatalf("PersonaWrites() = %v, want one write for item-1", got)
	}
	if got := rec.Truncations(); len(got) != 1 || got[0] != (fakes.Truncation{ItemID: "item-1", HeardMs: 300}) {
		t.Fatalf("Truncations() = %v, want one entry {item-1, 300}", got)
	}

	got, err := rec.Finalize(ctx)
	if err != nil {
		t.Fatalf("Finalize: %v", err)
	}
	if got != info {
		t.Fatalf("Finalize() = %v, want %v", got, info)
	}
	if !rec.Finalized() {
		t.Fatalf("Finalized() = false after Finalize")
	}

	rec.SetFinalizeError(errBoom)
	if _, err := rec.Finalize(ctx); !errors.Is(err, errBoom) {
		t.Fatalf("Finalize after SetFinalizeError = %v, want errBoom", err)
	}
}

// TestFakeFinalizer_RecordsInput proves every FinalizeInput is recorded and
// SetFinalizeError still records the input alongside the error.
func TestFakeFinalizer_RecordsInput(t *testing.T) {
	defer goleak.VerifyNone(t)
	fin := fakes.NewFakeFinalizer()
	ctx := context.Background()
	in := ports.FinalizeInput{
		Recording: ports.RecordingInfo{Key: "session/rec.wav"},
		Ingest:    ports.SessionIngest{SessionID: "sess-1"},
	}
	if err := fin.Finalize(ctx, in); err != nil {
		t.Fatalf("Finalize: %v", err)
	}
	if got := fin.Finalized(); len(got) != 1 || !reflect.DeepEqual(got[0], in) {
		t.Fatalf("Finalized() = %v, want [%v]", got, in)
	}

	fin.SetFinalizeError(errBoom)
	if err := fin.Finalize(ctx, in); !errors.Is(err, errBoom) {
		t.Fatalf("Finalize after SetFinalizeError = %v, want errBoom", err)
	}
	if got := fin.Finalized(); len(got) != 2 {
		t.Fatalf("Finalized() len = %d, want 2 (still recorded despite the error)", len(got))
	}
}

// TestFakeJudge_SubmitsAndReplaysVerdicts proves Submit records turns and
// Verdicts replays the scripted verdicts, both independent of Submit order
// per the port's own contract.
func TestFakeJudge_SubmitsAndReplaysVerdicts(t *testing.T) {
	defer goleak.VerifyNone(t)
	v1 := ports.Verdict{Turn: 1, Breach: false, Severity: "none"}
	v2 := ports.Verdict{Turn: 2, Breach: true, Severity: "major", Rationale: "leaked ceiling"}
	judge := fakes.NewFakeJudge(v1, v2)
	ctx := context.Background()

	turn := ports.TurnForReview{
		Turn: 1, Question: "tell me about redis", Answer: "...", Skill: "redis", Ceiling: 3,
	}
	if err := judge.Submit(ctx, turn); err != nil {
		t.Fatalf("Submit: %v", err)
	}
	if got := judge.Submitted(); len(got) != 1 || !reflect.DeepEqual(got[0], turn) {
		t.Fatalf("Submitted() = %v, want [%v]", got, turn)
	}

	if got1, got2 := <-judge.Verdicts(), <-judge.Verdicts(); got1 != v1 || got2 != v2 {
		t.Fatalf("Verdicts() delivered %+v, %+v, want %+v, %+v", got1, got2, v1, v2)
	}

	judge.SetSubmitError(errBoom)
	if err := judge.Submit(ctx, turn); !errors.Is(err, errBoom) {
		t.Fatalf("Submit after SetSubmitError = %v, want errBoom", err)
	}
}
