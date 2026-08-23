package session

import "time"

// bytesPerSamplePCM16 is 2: PCM16 mono, the format every Speaker adapter
// normalizes to at the vendor boundary.
const bytesPerSamplePCM16 = 2

// playoutTracker estimates how much of the persona's current response the
// human has actually *heard*.
//
// This is the number barge-in truncation must use, and it is not the number
// of bytes sent. Audio sits in the transport's out-ring, in the browser's
// jitter buffer, and in the output device — send five seconds and interrupt,
// and the human may have heard two. Truncating the vendor's history at
// bytes-sent tells the model the persona said things nobody heard, and every
// later turn reasons from that false history.
//
// So the browser reports what it has actually played, every 250 ms over the
// data channel, and this extrapolates forward from the last report using the
// clock. Extrapolation is capped at bytes-sent: the human cannot have heard
// audio that was never transmitted.
//
// Actor-owned; not safe for concurrent use.
type playoutTracker struct {
	sampleRate int

	// itemID is the response item currently playing, "" when idle.
	itemID string
	// sentSamples counts samples handed to the transport for this item.
	sentSamples int
	// heardMsReported is the browser's last heartbeat for this item.
	heardMsReported int
	// heartbeatAt is when that heartbeat was received, on the session clock.
	heartbeatAt time.Time
	// started is when the item began playing.
	started time.Time
	// haveHeartbeat distinguishes "played zero" from "never reported".
	haveHeartbeat bool
}

func newPlayoutTracker(sampleRate int) *playoutTracker {
	return &playoutTracker{sampleRate: sampleRate}
}

// begin starts tracking a new response item.
func (p *playoutTracker) begin(itemID string, now time.Time) {
	p.itemID = itemID
	p.sentSamples = 0
	p.heardMsReported = 0
	p.heartbeatAt = now
	p.started = now
	p.haveHeartbeat = false
}

// sent records audio handed to the transport.
func (p *playoutTracker) sent(frameBytes int) {
	if p.itemID == "" {
		return
	}
	p.sentSamples += frameBytes / bytesPerSamplePCM16
}

// heartbeat records the browser's report of how much it has played.
//
// Reports are monotonic per item: a late-arriving stale heartbeat must not
// walk the estimate backwards, or a barge-in immediately after one truncates
// too early and the vendor believes the persona said less than it did.
func (p *playoutTracker) heartbeat(itemID string, playedMs int, now time.Time) {
	if itemID != p.itemID || playedMs < p.heardMsReported {
		return
	}
	p.heardMsReported = playedMs
	p.heartbeatAt = now
	p.haveHeartbeat = true
}

// sentMs is everything handed to the transport, in milliseconds.
func (p *playoutTracker) sentMs() int {
	if p.sampleRate <= 0 {
		return 0
	}
	return p.sentSamples * 1000 / p.sampleRate
}

// heardMs is the current best estimate of what the human has heard.
//
// From the last heartbeat plus elapsed time since it, capped at what was
// actually sent. With no heartbeat yet — the first 250 ms of an item, or a
// transport with no data channel — it extrapolates from the item start, which
// degrades to "assume it all played" and is the safe direction: truncating
// too late leaves the vendor believing the persona said slightly more than it
// did, which reads as the persona being interrupted mid-word. Truncating too
// early invents silence the human did hear.
func (p *playoutTracker) heardMs(now time.Time) int {
	if p.itemID == "" {
		return 0
	}
	base, since := p.heardMsReported, p.heartbeatAt
	if !p.haveHeartbeat {
		base, since = 0, p.started
	}
	elapsed := int(now.Sub(since) / time.Millisecond)
	if elapsed < 0 {
		elapsed = 0
	}
	heard := base + elapsed
	if sent := p.sentMs(); heard > sent {
		heard = sent
	}
	if heard < 0 {
		heard = 0
	}
	return heard
}

// close stops tracking the current item and returns its final heard estimate.
func (p *playoutTracker) close(now time.Time) int {
	heard := p.heardMs(now)
	p.itemID = ""
	return heard
}

// active reports whether an item is currently being tracked.
func (p *playoutTracker) active() bool { return p.itemID != "" }
