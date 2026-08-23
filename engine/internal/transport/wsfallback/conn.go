package wsfallback

import (
	"context"
	"encoding/json"
	"errors"
	"log/slog"
	"sync"
	"time"

	"github.com/coder/websocket"

	"skillbrew/engine/internal/audio"
	"skillbrew/engine/internal/ports"
)

// writeTimeout bounds one socket write. A browser that has stopped reading
// must not be able to park the writer goroutine — and with it the whole
// outbound audio path — indefinitely.
const writeTimeout = 5 * time.Second

// Conn is one browser's media connection.
//
// It exists from the moment the offer is accepted, which is before the socket
// arrives: the session actor needs a MediaConn immediately, and the browser
// cannot connect until it has been handed the answer. Until attach, the
// connection is real and quiet — AudioIn yields nothing and SendAudio queues
// into the ring, where drop-oldest keeps it bounded.
type Conn struct {
	cfg         Config
	browserRate int
	logger      *slog.Logger

	audioIn    chan ports.Frame
	heartbeats chan ports.PlayoutHeartbeat
	speech     chan ports.VADEvent
	control    chan ports.ControlMessage

	out *audio.SendRing

	// mic converts browser audio to the rate the Speaker wants; vad runs on
	// the browser's own rate, before conversion, because the detector's
	// tuning is in dB and conversion does not change level.
	mic    *audio.Resampler
	vad    *audio.VAD
	jitter *audio.JitterBuffer

	attachOnce sync.Once
	attached   chan struct{}

	closeOnce sync.Once
	closed    chan struct{}
	wg        sync.WaitGroup

	// onClose lets the Transport drop an unclaimed ticket when the session
	// gives up before the browser ever connected.
	onClose func()

	mu      sync.Mutex
	ws      *websocket.Conn
	dropped int
}

var _ ports.MediaConn = (*Conn)(nil)

func newConn(cfg Config, browserRate int, logger *slog.Logger) (*Conn, error) {
	mic, err := audio.NewResampler(browserRate, cfg.MicRateHz)
	if err != nil {
		return nil, err
	}
	return &Conn{
		cfg:         cfg,
		browserRate: browserRate,
		logger:      logger,
		audioIn:     make(chan ports.Frame, audioInBuffer),
		heartbeats:  make(chan ports.PlayoutHeartbeat, heartbeatBuffer),
		speech:      make(chan ports.VADEvent, speechBuffer),
		control:     make(chan ports.ControlMessage, controlBuffer),
		out:         audio.NewSendRing(sendRingCapacity),
		mic:         mic,
		vad:         audio.NewVAD(cfg.VAD),
		jitter:      audio.NewJitterBuffer(cfg.Jitter),
		attached:    make(chan struct{}),
		closed:      make(chan struct{}),
	}, nil
}

// AudioIn implements ports.MediaConn.
func (c *Conn) AudioIn() <-chan ports.Frame { return c.audioIn }

// Control implements ports.MediaConn.
func (c *Conn) Control() <-chan ports.ControlMessage { return c.control }

// PlayoutHeartbeats implements ports.MediaConn.
func (c *Conn) PlayoutHeartbeats() <-chan ports.PlayoutHeartbeat { return c.heartbeats }

// Speech implements ports.MediaConn.
func (c *Conn) Speech() <-chan ports.VADEvent { return c.speech }

// SendAudio implements ports.MediaConn. It queues and returns; it never waits
// on the socket.
//
// The caller is the session actor's owner goroutine. A SendAudio that could
// block on a slow client would stall the turn loop of a live conversation —
// which is the deadlock the port's own no-blocking-I/O clause exists to
// forbid.
func (c *Conn) SendAudio(ctx context.Context, frame ports.Frame) error {
	select {
	case <-c.closed:
		return ErrConnClosed
	case <-ctx.Done():
		return ctx.Err()
	default:
	}
	if c.out.Push(frame.PCM, frame.SampleRateHz, "", frame.Timestamp) {
		c.mu.Lock()
		c.dropped++
		c.mu.Unlock()
	}
	return nil
}

// SendControl implements ports.MediaConn.
func (c *Conn) SendControl(ctx context.Context, msg ports.ControlMessage) error {
	c.mu.Lock()
	ws := c.ws
	c.mu.Unlock()
	if ws == nil {
		return ErrConnClosed
	}
	body, err := json.Marshal(struct {
		Kind    string `json:"kind"`
		Payload []byte `json:"payload,omitempty"`
	}{Kind: msg.Kind, Payload: msg.Payload})
	if err != nil {
		return err
	}
	wctx, cancel := context.WithTimeout(ctx, writeTimeout)
	defer cancel()
	return ws.Write(wctx, websocket.MessageText, body)
}

// Dropped is how many outbound frames were shed under pressure.
func (c *Conn) Dropped() int {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.dropped
}

// Attached reports whether a browser has claimed this connection. Tests wait
// on it; operationally, a session that never attaches is one whose client
// never arrived.
func (c *Conn) Attached() <-chan struct{} { return c.attached }

// attach binds an upgraded socket and starts the read and write loops. It
// returns when the connection is finished, so the HTTP handler's goroutine is
// the one that serves it rather than a goroutine outliving the request.
func (c *Conn) attach(ctx context.Context, ws *websocket.Conn) {
	c.mu.Lock()
	c.ws = ws
	c.mu.Unlock()
	c.attachOnce.Do(func() { close(c.attached) })

	// The socket's lifetime is the connection's, not the HTTP request's, but
	// a cancelled request must still tear it down.
	runCtx, cancel := context.WithCancel(context.WithoutCancel(ctx))
	defer cancel()
	go func() {
		select {
		case <-c.closed:
			cancel()
		case <-ctx.Done():
			cancel()
		case <-runCtx.Done():
		}
	}()

	c.wg.Add(1)
	go func() {
		defer c.wg.Done()
		c.writeLoop(runCtx, ws)
	}()

	c.readLoop(runCtx, ws)
	cancel()
	c.wg.Wait()
	_ = ws.Close(websocket.StatusNormalClosure, "")
}

// expire tears down a connection whose ticket was never claimed.
func (c *Conn) expire() {
	c.logger.Warn("wsfallback: ticket expired before the client connected")
	_ = c.Close(context.Background())
}

// readLoop turns arriving messages into port events.
func (c *Conn) readLoop(ctx context.Context, ws *websocket.Conn) {
	for {
		typ, msg, err := ws.Read(ctx)
		if err != nil {
			if ctx.Err() == nil && !errors.Is(err, context.Canceled) {
				c.logger.Info("wsfallback: read ended", "err", err)
			}
			return
		}
		switch typ {
		case websocket.MessageBinary:
			c.onAudio(msg)
		case websocket.MessageText:
			c.onControl(msg)
		}
	}
}

// onAudio pushes one arriving frame through the jitter buffer, converts what
// comes out, and publishes it along with any speech-state change.
func (c *Conn) onAudio(msg []byte) {
	seq, rate, pcm, err := decodeAudio(msg)
	if err != nil {
		c.logger.Warn("wsfallback: bad audio message", "err", err)
		return
	}
	now := time.Now()
	c.jitter.Push(seq, pcm, rate, now)

	for {
		framePCM, frameRate, _, ok := c.jitter.Pop()
		if !ok {
			return
		}
		// Onset detection runs before conversion: the detector's tuning is
		// in dB, which resampling does not change, and running it on the
		// browser's own audio keeps it independent of the conversion.
		if started, changed := c.vad.Push(framePCM, frameRate, now); changed {
			publish(c, c.speech, ports.VADEvent{
				Started:  started,
				EnergyDB: audio.RMSDB(framePCM),
				At:       now,
			})
		}

		converted := framePCM
		if frameRate != c.cfg.MicRateHz {
			converted = c.mic.Process(framePCM)
		}
		// The resampler owns its output buffer and overwrites it on the
		// next call, so what crosses the port boundary must be a copy.
		cp := make([]byte, len(converted))
		copy(cp, converted)

		publish(c, c.audioIn, ports.Frame{
			PCM:          cp,
			SampleRateHz: c.cfg.MicRateHz,
			Timestamp:    now,
		})
	}
}

// inboundControl is the JSON the browser sends on the text channel.
type inboundControl struct {
	Kind    string `json:"kind"`
	ItemID  string `json:"item_id"`
	HeardMs int    `json:"heard_ms"`
	Payload []byte `json:"payload"`
}

func (c *Conn) onControl(msg []byte) {
	var in inboundControl
	if err := json.Unmarshal(msg, &in); err != nil {
		c.logger.Warn("wsfallback: bad control message", "err", err)
		return
	}
	if in.Kind == "playout_heartbeat" {
		publish(c, c.heartbeats, ports.PlayoutHeartbeat{
			ItemID:  in.ItemID,
			HeardMs: in.HeardMs,
			At:      time.Now(),
		})
		return
	}
	publish(c, c.control, ports.ControlMessage{Kind: in.Kind, Payload: in.Payload})
}

// publish delivers without ever blocking the read loop.
//
// A blocked read loop stops reading the socket, which stops the browser's
// audio arriving at all — so one slow consumer would silence every other
// signal. Dropping is the correct trade on a real-time path, and it is
// counted rather than silent.
func publish[T any](c *Conn, ch chan T, v T) {
	select {
	case ch <- v:
	default:
		c.mu.Lock()
		c.dropped++
		c.mu.Unlock()
	}
}

// writeLoop drains the send ring to the socket.
func (c *Conn) writeLoop(ctx context.Context, ws *websocket.Conn) {
	for {
		pcm, rate, itemID, _, ok := c.out.Pop()
		if !ok {
			select {
			case <-ctx.Done():
				return
			case <-c.out.Ready():
				continue
			}
		}
		msg, err := encodeAudio(rate, itemID, pcm)
		if err != nil {
			// A frame the wire format cannot carry. Dropping one frame is
			// 20 ms of audio; sending a corrupt one desynchronises the
			// stream from that point on.
			c.logger.Warn("wsfallback: undeliverable frame dropped", "err", err)
			continue
		}
		wctx, cancel := context.WithTimeout(ctx, writeTimeout)
		err = ws.Write(wctx, websocket.MessageBinary, msg)
		cancel()
		if err != nil {
			if ctx.Err() == nil {
				c.logger.Info("wsfallback: write ended", "err", err)
			}
			return
		}
	}
}

// Close implements ports.MediaConn. Idempotent, and it waits for the loops it
// started so no goroutine outlives a closed connection.
func (c *Conn) Close(context.Context) error {
	c.closeOnce.Do(func() {
		close(c.closed)
		c.mu.Lock()
		ws := c.ws
		c.mu.Unlock()
		if ws != nil {
			// Closing the socket is what unblocks a read parked on it.
			_ = ws.Close(websocket.StatusNormalClosure, "session ended")
		}
		if c.onClose != nil {
			c.onClose()
		}
	})
	return nil
}

// Bump invalidates queued persona audio, so nothing from an interrupted
// response plays out after the barge-in.
func (c *Conn) Bump() uint64 { return c.out.Bump() }

// JitterStats reports receive-path health for the media report.
func (c *Conn) JitterStats() audio.JitterStats { return c.jitter.Stats() }
