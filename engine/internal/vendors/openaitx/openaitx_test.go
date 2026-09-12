package openaitx

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/coder/websocket"

	"skillbrew/engine/internal/ports"
)

func TestTranscriberEmitsCumulativeRevisionsAndFinal(t *testing.T) {
	setupSeen := make(chan sessionUpdate, 1)
	serverDone := make(chan struct{})
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if got := r.Header.Get("Authorization"); got != "Bearer test-key" {
			t.Errorf("authorization = %q, want bearer test-key", got)
		}
		if got := r.Header.Get("OpenAI-Beta"); got != "" {
			t.Errorf("OpenAI-Beta header = %q; the GA endpoint rejects the beta header", got)
		}
		ws, err := websocket.Accept(w, r, nil)
		if err != nil {
			t.Errorf("accept websocket: %v", err)
			return
		}
		defer close(serverDone)
		defer ws.CloseNow()

		_, msg, err := ws.Read(context.Background())
		if err != nil {
			t.Errorf("read setup: %v", err)
			return
		}
		var setup sessionUpdate
		if err := json.Unmarshal(msg, &setup); err != nil {
			t.Errorf("decode setup: %v", err)
			return
		}
		setupSeen <- setup
		created, marshalErr := json.Marshal(map[string]any{"type": "session.created"})
		if marshalErr != nil {
			t.Errorf("encode created event: %v", marshalErr)
			return
		}
		if writeErr := ws.Write(context.Background(), websocket.MessageText, created); writeErr != nil {
			return
		}
		for _, event := range []map[string]any{
			{"type": "conversation.item.input_audio_transcription.delta", "item_id": "item-1", "delta": "hel"},
			{"type": "conversation.item.input_audio_transcription.delta", "item_id": "item-1", "delta": "lo"},
			{"type": "conversation.item.input_audio_transcription.completed", "item_id": "item-1", "transcript": "hello"},
		} {
			b, marshalErr := json.Marshal(event)
			if marshalErr != nil {
				t.Errorf("encode event: %v", marshalErr)
				return
			}
			if writeErr := ws.Write(context.Background(), websocket.MessageText, b); writeErr != nil {
				return
			}
		}
		for {
			if _, _, err := ws.Read(context.Background()); err != nil {
				return
			}
		}
	}))
	t.Cleanup(srv.Close)

	transcriber := New("test-transcribe", "test-key", nil,
		WithEndpoint("ws"+strings.TrimPrefix(srv.URL, "http")))
	if err := transcriber.Start(context.Background()); err != nil {
		t.Fatalf("start: %v", err)
	}
	defer transcriber.Close(context.Background())

	select {
	case setup := <-setupSeen:
		if setup.Type != "session.update" {
			t.Fatalf("setup type = %q, want the GA session.update event", setup.Type)
		}
		if setup.Session.Type != "transcription" {
			t.Fatalf("session type = %q, want transcription", setup.Session.Type)
		}
		in := setup.Session.Audio.Input
		if in.Transcription.Model != "test-transcribe" {
			t.Fatalf("ASR model = %q", in.Transcription.Model)
		}
		if in.Format.Type != "audio/pcm" || in.Format.Rate != inputRateHz {
			t.Fatalf("setup audio format = %+v, want audio/pcm at %d Hz", in.Format, inputRateHz)
		}
		if in.TurnDetection.Type != "server_vad" {
			t.Fatalf("turn detection = %+v, want server_vad", in.TurnDetection)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("timed out waiting for setup")
	}

	partials := transcriber.Partials()
	want := []ports.Partial{
		{Text: "hel", ItemID: "item-1"},
		{Text: "hello", ItemID: "item-1"},
		{Text: "hello", ItemID: "item-1", Final: true},
	}
	for i, expected := range want {
		select {
		case got := <-partials:
			if got != expected {
				t.Fatalf("partial %d = %+v, want %+v", i, got, expected)
			}
		case <-time.After(5 * time.Second):
			t.Fatalf("timed out waiting for partial %d", i)
		}
	}
}

func TestTranscriberResamplesAndAppendsAudio(t *testing.T) {
	audioSeen := make(chan []byte, 1)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		ws, err := websocket.Accept(w, r, nil)
		if err != nil {
			t.Errorf("accept websocket: %v", err)
			return
		}
		defer ws.CloseNow()
		if _, _, err := ws.Read(context.Background()); err != nil {
			return
		}
		created, marshalErr := json.Marshal(map[string]any{"type": "session.created"})
		if marshalErr != nil {
			t.Errorf("encode created event: %v", marshalErr)
			return
		}
		if err := ws.Write(context.Background(), websocket.MessageText, created); err != nil {
			return
		}
		for {
			_, msg, err := ws.Read(context.Background())
			if err != nil {
				return
			}
			var appendEvent audioAppend
			if json.Unmarshal(msg, &appendEvent) != nil || appendEvent.Type != "input_audio_buffer.append" {
				continue
			}
			pcm, decodeErr := base64.StdEncoding.DecodeString(appendEvent.Audio)
			if decodeErr != nil {
				t.Errorf("decode appended audio: %v", decodeErr)
				return
			}
			audioSeen <- pcm
			return
		}
	}))
	t.Cleanup(srv.Close)

	transcriber := New("test-transcribe", "test-key", nil,
		WithEndpoint("ws"+strings.TrimPrefix(srv.URL, "http")))
	if err := transcriber.Start(context.Background()); err != nil {
		t.Fatalf("start: %v", err)
	}
	defer transcriber.Close(context.Background())
	if err := transcriber.SendAudio(context.Background(), ports.Frame{
		PCM:          make([]byte, 320), // ten milliseconds at 16 kHz
		SampleRateHz: 16000,
	}); err != nil {
		t.Fatalf("send audio: %v", err)
	}
	select {
	case pcm := <-audioSeen:
		if len(pcm) <= 320 {
			t.Fatalf("resampled PCM length = %d, want more than source length", len(pcm))
		}
	case <-time.After(5 * time.Second):
		t.Fatal("timed out waiting for appended audio")
	}
}

func TestTranscriberCloseBeforeStartIsSafe(t *testing.T) {
	transcriber := New("model", "key", nil)
	if err := transcriber.Close(context.Background()); err != nil {
		t.Fatalf("close before start: %v", err)
	}
}
