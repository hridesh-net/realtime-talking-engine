package wsfallback_test

import (
	"context"
	"encoding/binary"
	"encoding/json"
	"io"
	"log/slog"
	"math"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/coder/websocket"
	"go.uber.org/goleak"

	"skillbrew/engine/internal/audio"
	"skillbrew/engine/internal/fakes"
	"skillbrew/engine/internal/ports"
	"skillbrew/engine/internal/transport/wsfallback"
)

const browserRate = 48000

func quietLogger() *slog.Logger { return slog.New(slog.NewTextHandler(io.Discard, nil)) }

// verifyNoEngineLeaks registers the leak check, scoped to goroutines this
// package owns. httptest and the stdlib transport keep connection goroutines
// alive past Close and they are not ours.
//
// Registered with t.Cleanup and called *first* in a test, rather than
// deferred. Deferred functions run before cleanups, so a deferred check fires
// while the connection this rig registered for cleanup is still open, and
// reports its live goroutines as leaks. Cleanups run last-registered-first,
// so registering this one first makes it run last — after the connection has
// actually been closed.
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

// rig is a transport served over httptest, plus the answer for one accepted
// offer.
type rig struct {
	tr     *wsfallback.Transport
	srv    *httptest.Server
	conn   ports.MediaConn
	answer struct {
		Kind           string `json:"kind"`
		Ticket         string `json:"ticket"`
		MicRateHz      int    `json:"mic_rate_hz"`
		PlaybackRateHz int    `json:"playback_rate_hz"`
		FrameMs        int    `json:"frame_ms"`
	}
}

func newRig(t *testing.T) *rig {
	t.Helper()
	r := &rig{}
	r.tr = wsfallback.New(wsfallback.DefaultConfig(), fakes.NewFakeClock(time.Unix(0, 0)), quietLogger())

	mux := http.NewServeMux()
	mux.Handle("/v1/media/ws", r.tr)
	r.srv = httptest.NewServer(mux)
	t.Cleanup(r.srv.Close)

	offer, err := json.Marshal(map[string]any{"kind": "ws-pcm", "sample_rate_hz": browserRate})
	if err != nil {
		t.Fatalf("marshal offer: %v", err)
	}
	answerBytes, conn, err := r.tr.Accept(context.Background(), offer)
	if err != nil {
		t.Fatalf("accept: %v", err)
	}
	if err := json.Unmarshal(answerBytes, &r.answer); err != nil {
		t.Fatalf("unmarshal answer: %v", err)
	}
	r.conn = conn
	t.Cleanup(func() { _ = conn.Close(context.Background()) })
	return r
}

// dial connects a client to the rig's media path with the given ticket.
func (r *rig) dial(t *testing.T, ticket string) *websocket.Conn {
	t.Helper()
	url := "ws" + strings.TrimPrefix(r.srv.URL, "http") + "/v1/media/ws?ticket=" + ticket
	ws, resp, err := websocket.Dial(context.Background(), url, nil)
	if resp != nil && resp.Body != nil {
		_ = resp.Body.Close()
	}
	if err != nil {
		t.Fatalf("dial: %v", err)
	}
	t.Cleanup(func() { _ = ws.Close(websocket.StatusNormalClosure, "") })
	return ws
}

// micFrame builds one 20 ms browser audio message at browserRate.
func micFrame(seq uint32, amp float64, phase *float64) []byte {
	n := browserRate / 50
	s := make([]float64, n)
	for i := range n {
		tSec := *phase + float64(i)/browserRate
		s[i] = amp * math.Sin(2*math.Pi*220*tSec)
	}
	*phase += float64(n) / browserRate

	pcm := audio.FloatToBytes(nil, s)
	msg := make([]byte, 9, 9+len(pcm))
	msg[0] = 0x01
	binary.BigEndian.PutUint32(msg[1:5], seq)
	binary.BigEndian.PutUint32(msg[5:9], browserRate)
	return append(msg, pcm...)
}

// TestMicAudioArrivesResampledAtTheRateTheSpeakerWants matters because the
// browser and the vendor disagree by design — 48 kHz in, 16 kHz wanted — and
// a transport that forwarded the browser's rate unchanged would send the
// Speaker audio it cannot use.
func TestMicAudioArrivesResampledAtTheRateTheSpeakerWants(t *testing.T) {
	verifyNoEngineLeaks(t)

	r := newRig(t)
	ws := r.dial(t, r.answer.Ticket)

	var phase float64
	for seq := range uint32(12) {
		if err := ws.Write(context.Background(), websocket.MessageBinary, micFrame(seq, 0.3, &phase)); err != nil {
			t.Fatalf("write frame %d: %v", seq, err)
		}
	}

	select {
	case f := <-r.conn.AudioIn():
		if f.SampleRateHz != r.answer.MicRateHz {
			t.Fatalf("frame rate = %d, want the advertised mic rate %d", f.SampleRateHz, r.answer.MicRateHz)
		}
		if len(f.PCM) == 0 {
			t.Fatal("an empty frame reached the session")
		}
	case <-time.After(5 * time.Second):
		t.Fatal("no mic audio reached the session")
	}
}

// TestSpeechOnsetReachesTheSessionOverTheTransport matters because that
// signal drives the vendor's activityStart, and the live spike proved audio
// sent outside an activity window is discarded in silence.
func TestSpeechOnsetReachesTheSessionOverTheTransport(t *testing.T) {
	verifyNoEngineLeaks(t)

	r := newRig(t)
	ws := r.dial(t, r.answer.Ticket)

	var phase float64
	seq := uint32(0)
	// Quiet first so the detector has a floor, then speech.
	for range 60 {
		_ = ws.Write(context.Background(), websocket.MessageBinary, micFrame(seq, 0.0005, &phase))
		seq++
	}
	for range 40 {
		_ = ws.Write(context.Background(), websocket.MessageBinary, micFrame(seq, 0.35, &phase))
		seq++
	}

	select {
	case ev := <-r.conn.Speech():
		if !ev.Started {
			t.Fatal("first speech event was an offset, not an onset")
		}
	case <-time.After(5 * time.Second):
		t.Fatal("speech onset never reached the session")
	}
}

// TestAPlayoutHeartbeatReachesTheSession matters because heardMs is what
// barge-in truncation is computed from, and without heartbeats the actor
// falls back to assuming everything sent was heard.
func TestAPlayoutHeartbeatReachesTheSession(t *testing.T) {
	verifyNoEngineLeaks(t)

	r := newRig(t)
	ws := r.dial(t, r.answer.Ticket)

	body, err := json.Marshal(map[string]any{
		"kind": "playout_heartbeat", "item_id": "item-7", "heard_ms": 2100,
	})
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	if err := ws.Write(context.Background(), websocket.MessageText, body); err != nil {
		t.Fatalf("write: %v", err)
	}

	select {
	case hb := <-r.conn.PlayoutHeartbeats():
		if hb.ItemID != "item-7" || hb.HeardMs != 2100 {
			t.Fatalf("heartbeat = %+v, want item-7 at 2100 ms", hb)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("no heartbeat reached the session")
	}
}

// TestPersonaAudioReachesTheBrowser closes the loop the other way.
func TestPersonaAudioReachesTheBrowser(t *testing.T) {
	verifyNoEngineLeaks(t)

	r := newRig(t)
	ws := r.dial(t, r.answer.Ticket)

	pcm := make([]byte, 480*2)
	for i := range pcm {
		pcm[i] = byte(i % 251)
	}
	if err := r.conn.SendAudio(context.Background(), ports.Frame{
		PCM: pcm, SampleRateHz: 24000, Timestamp: time.Unix(0, 0),
	}); err != nil {
		t.Fatalf("send audio: %v", err)
	}

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	typ, msg, err := ws.Read(ctx)
	if err != nil {
		t.Fatalf("read: %v", err)
	}
	if typ != websocket.MessageBinary {
		t.Fatalf("message type = %v, want binary", typ)
	}
	if len(msg) < 7 || msg[0] != 0x01 {
		t.Fatalf("malformed outbound audio message of %d bytes", len(msg))
	}
	if got := int(binary.BigEndian.Uint32(msg[1:5])); got != 24000 {
		t.Fatalf("declared rate = %d, want 24000", got)
	}
}

// TestSendAudioNeverBlocksOnASlowBrowser is the port's no-blocking-I/O clause
// made concrete. The caller is the session actor's owner goroutine: a
// SendAudio that could wait on a slow client would stall a live conversation's
// entire turn loop.
func TestSendAudioNeverBlocksOnASlowBrowser(t *testing.T) {
	verifyNoEngineLeaks(t)

	r := newRig(t)
	// Deliberately no client at all: nothing is draining the ring.
	pcm := make([]byte, 480*2)

	done := make(chan struct{})
	go func() {
		defer close(done)
		for range 500 { // twenty times the ring's depth
			_ = r.conn.SendAudio(context.Background(), ports.Frame{
				PCM: pcm, SampleRateHz: 24000, Timestamp: time.Unix(0, 0),
			})
		}
	}()

	select {
	case <-done:
	case <-time.After(5 * time.Second):
		t.Fatal("SendAudio blocked with no browser attached; it must shed instead")
	}
}

// TestATicketIsSingleUse matters because the ticket is what authorizes the
// media attach. A reusable one would let a second client join a live
// interview's audio path.
func TestATicketIsSingleUse(t *testing.T) {
	verifyNoEngineLeaks(t)

	r := newRig(t)
	r.dial(t, r.answer.Ticket)

	url := "ws" + strings.TrimPrefix(r.srv.URL, "http") + "/v1/media/ws?ticket=" + r.answer.Ticket
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	ws2, resp, err := websocket.Dial(ctx, url, nil)
	if resp != nil && resp.Body != nil {
		_ = resp.Body.Close()
	}
	if err == nil {
		_ = ws2.Close(websocket.StatusNormalClosure, "")
		t.Fatal("a second client attached with an already-claimed ticket")
	}
}

// TestAnUnknownTicketIsRefused matters for the same reason: without it the
// media path is open to anyone who can reach it.
func TestAnUnknownTicketIsRefused(t *testing.T) {
	verifyNoEngineLeaks(t)

	r := newRig(t)
	url := "ws" + strings.TrimPrefix(r.srv.URL, "http") + "/v1/media/ws?ticket=not-a-real-ticket"
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	ws, resp, err := websocket.Dial(ctx, url, nil)
	if resp != nil && resp.Body != nil {
		_ = resp.Body.Close()
	}
	if err == nil {
		_ = ws.Close(websocket.StatusNormalClosure, "")
		t.Fatal("an unissued ticket was accepted")
	}
}

// TestAnUnusableOfferIsRefusedRatherThanHalfAccepted matters because a
// half-accepted offer leaves a registration nothing will ever claim.
func TestAnUnusableOfferIsRefusedRatherThanHalfAccepted(t *testing.T) {
	verifyNoEngineLeaks(t)

	tr := wsfallback.New(wsfallback.DefaultConfig(), fakes.NewFakeClock(time.Unix(0, 0)), quietLogger())
	for _, bad := range []string{
		`not json`,
		`{"kind":"webrtc","sample_rate_hz":48000}`,
		`{"kind":"ws-pcm","sample_rate_hz":0}`,
	} {
		if _, _, err := tr.Accept(context.Background(), []byte(bad)); err == nil {
			t.Fatalf("offer %q was accepted", bad)
		}
	}
	if got := tr.Pending(); got != 0 {
		t.Fatalf("Pending() = %d after only bad offers; a refused offer left a registration", got)
	}
}

// TestClosingBeforeTheClientArrivesDropsTheTicket matters because a session
// that gives up during connect must not leave a ticket outstanding — that is
// the same class of leak as a vendor session landing after a stop.
func TestClosingBeforeTheClientArrivesDropsTheTicket(t *testing.T) {
	verifyNoEngineLeaks(t)

	tr := wsfallback.New(wsfallback.DefaultConfig(), fakes.NewFakeClock(time.Unix(0, 0)), quietLogger())
	offer := []byte(`{"kind":"ws-pcm","sample_rate_hz":48000}`)
	_, conn, err := tr.Accept(context.Background(), offer)
	if err != nil {
		t.Fatalf("accept: %v", err)
	}
	if got := tr.Pending(); got != 1 {
		t.Fatalf("Pending() = %d, want 1", got)
	}
	if err := conn.Close(context.Background()); err != nil {
		t.Fatalf("close: %v", err)
	}
	if got := tr.Pending(); got != 0 {
		t.Fatalf("Pending() = %d after close; the ticket leaked", got)
	}
}
