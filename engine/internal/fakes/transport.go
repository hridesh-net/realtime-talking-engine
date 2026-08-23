package fakes

import (
	"context"
	"errors"
	"sync"

	"skillbrew/engine/internal/ports"
)

// mediaConnBufferSize sizes every FakeMediaConn inbound channel generously
// enough that a test pushing frames onto it never blocks on a full buffer.
const mediaConnBufferSize = 64

// FakeTransport is a scripted ports.Transport. Every Accept call returns a
// fixed SDP answer paired with a fresh FakeMediaConn (unless SetAcceptError
// has armed a failure), and records every offer it was given.
//
// Safe for concurrent use.
type FakeTransport struct {
	mu        sync.Mutex
	answer    []byte
	acceptErr error
	offers    [][]byte
	conns     []*FakeMediaConn
}

// NewFakeTransport returns a FakeTransport whose Accept calls return answer
// (copied) paired with a fresh FakeMediaConn.
func NewFakeTransport(answer []byte) *FakeTransport {
	cp := make([]byte, len(answer))
	copy(cp, answer)
	return &FakeTransport{answer: cp}
}

// Accept implements ports.Transport, recording offer and producing a fresh
// FakeMediaConn.
func (f *FakeTransport) Accept(ctx context.Context, offer []byte) ([]byte, ports.MediaConn, error) {
	if err := ctx.Err(); err != nil {
		return nil, nil, err
	}
	f.mu.Lock()
	defer f.mu.Unlock()
	cp := make([]byte, len(offer))
	copy(cp, offer)
	f.offers = append(f.offers, cp)
	if f.acceptErr != nil {
		return nil, nil, f.acceptErr
	}
	conn := newFakeMediaConn()
	f.conns = append(f.conns, conn)
	out := make([]byte, len(f.answer))
	copy(out, f.answer)
	return out, conn, nil
}

// SetAcceptError makes every subsequent Accept call return err after still
// recording the offer. Pass nil to clear it.
func (f *FakeTransport) SetAcceptError(err error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.acceptErr = err
}

// Offers returns every offer passed to Accept, in call order.
func (f *FakeTransport) Offers() [][]byte {
	f.mu.Lock()
	defer f.mu.Unlock()
	out := make([][]byte, len(f.offers))
	copy(out, f.offers)
	return out
}

// Conns returns every FakeMediaConn Accept has produced, in call order.
func (f *FakeTransport) Conns() []*FakeMediaConn {
	f.mu.Lock()
	defer f.mu.Unlock()
	out := make([]*FakeMediaConn, len(f.conns))
	copy(out, f.conns)
	return out
}

// FakeMediaConn is a scripted ports.MediaConn. Tests feed it inbound mic
// audio, playout heartbeats, and VAD events via PushAudioIn, PushHeartbeat,
// and PushSpeech — standing in for the browser and the local VAD detector —
// and it records every persona frame handed to SendAudio.
//
// Safe for concurrent use.
type FakeMediaConn struct {
	audioIn     chan ports.Frame
	heartbeats  chan ports.PlayoutHeartbeat
	speech      chan ports.VADEvent
	control     chan ports.ControlMessage
	sentControl []ports.ControlMessage

	mu        sync.Mutex
	closed    bool
	sentAudio []ports.Frame
}

func newFakeMediaConn() *FakeMediaConn {
	return &FakeMediaConn{
		audioIn:    make(chan ports.Frame, mediaConnBufferSize),
		heartbeats: make(chan ports.PlayoutHeartbeat, mediaConnBufferSize),
		speech:     make(chan ports.VADEvent, mediaConnBufferSize),
		control:    make(chan ports.ControlMessage, mediaConnBufferSize),
	}
}

// AudioIn implements ports.MediaConn, delivering whatever PushAudioIn was
// given.
func (c *FakeMediaConn) AudioIn() <-chan ports.Frame { return c.audioIn }

// SendAudio implements ports.MediaConn, recording frame.
func (c *FakeMediaConn) SendAudio(ctx context.Context, frame ports.Frame) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	c.sentAudio = append(c.sentAudio, frame)
	return nil
}

// Control implements ports.MediaConn, returning messages the browser sent.
func (c *FakeMediaConn) Control() <-chan ports.ControlMessage { return c.control }

// SendControl implements ports.MediaConn, recording the message rather than
// sending it anywhere.
func (c *FakeMediaConn) SendControl(ctx context.Context, msg ports.ControlMessage) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.closed {
		return errors.New("fakes: media conn closed")
	}
	c.sentControl = append(c.sentControl, msg)
	return nil
}

// SentControl returns every message passed to SendControl, in call order.
func (c *FakeMediaConn) SentControl() []ports.ControlMessage {
	c.mu.Lock()
	defer c.mu.Unlock()
	out := make([]ports.ControlMessage, len(c.sentControl))
	copy(out, c.sentControl)
	return out
}

// PushControl delivers a control message as though the browser had sent it.
func (c *FakeMediaConn) PushControl(msg ports.ControlMessage) {
	select {
	case c.control <- msg:
	default:
	}
}

// PlayoutHeartbeats implements ports.MediaConn, delivering whatever
// PushHeartbeat was given.
func (c *FakeMediaConn) PlayoutHeartbeats() <-chan ports.PlayoutHeartbeat { return c.heartbeats }

// Speech implements ports.MediaConn, delivering whatever PushSpeech was
// given.
func (c *FakeMediaConn) Speech() <-chan ports.VADEvent { return c.speech }

// Close implements ports.MediaConn. It is idempotent and closes every
// inbound channel so a pump reading from them observes end-of-stream, the
// same way a real connection tearing down would stop delivering. Releasing
// resources is not something a cancelled ctx should prevent, so Close
// ignores ctx and always succeeds.
func (c *FakeMediaConn) Close(ctx context.Context) error {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.closed {
		return nil
	}
	c.closed = true
	close(c.audioIn)
	close(c.heartbeats)
	close(c.speech)
	return nil
}

// PushAudioIn feeds one mic frame onto AudioIn, as if the browser had sent
// it. It reports whether the frame was delivered — false if the connection
// is already closed.
func (c *FakeMediaConn) PushAudioIn(f ports.Frame) bool {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.closed {
		return false
	}
	c.audioIn <- f
	return true
}

// PushHeartbeat feeds one playout heartbeat onto PlayoutHeartbeats, as if
// the browser had reported it. It reports whether the heartbeat was
// delivered — false if the connection is already closed.
func (c *FakeMediaConn) PushHeartbeat(hb ports.PlayoutHeartbeat) bool {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.closed {
		return false
	}
	c.heartbeats <- hb
	return true
}

// PushSpeech feeds one VAD event onto Speech, as if the local VAD detector
// had fired. It reports whether the event was delivered — false if the
// connection is already closed.
func (c *FakeMediaConn) PushSpeech(v ports.VADEvent) bool {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.closed {
		return false
	}
	c.speech <- v
	return true
}

// SentAudio returns every frame passed to SendAudio, in call order.
func (c *FakeMediaConn) SentAudio() []ports.Frame {
	c.mu.Lock()
	defer c.mu.Unlock()
	out := make([]ports.Frame, len(c.sentAudio))
	copy(out, c.sentAudio)
	return out
}

// Closed reports whether Close has been called.
func (c *FakeMediaConn) Closed() bool {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.closed
}

var _ ports.Transport = (*FakeTransport)(nil)
var _ ports.MediaConn = (*FakeMediaConn)(nil)
