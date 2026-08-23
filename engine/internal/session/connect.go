package session

import (
	"context"
	"fmt"
	"sync"

	"skillbrew/engine/internal/ports"
)

// connectAttempt is the connector's own working state for one connect
// attempt: what each collaborator's Start (or Warm) call produced, before
// any decision about hand-off versus cleanup has been made.
type connectAttempt struct {
	speaker        ports.SpeakerSession
	speakerErr     error
	transcriberErr error
	thinkerErr     error
	stallErr       error

	// *Done records that a collaborator's call returned, so a timeout can be
	// attributed to whoever actually did not finish rather than blamed on
	// the Speaker by default. Written by the connect goroutines and read
	// only after they have all been waited on, so no lock is needed.
	transcriberDone bool
	thinkerDone     bool
	stallDone       bool
}

// connect is the per-session connector, spawned from handleAttachTransport
// once a transport is accepted. It concurrently starts every vendor-backed
// collaborator this session was wired with — Speaker.Start (fatal),
// Transcriber.Start, Thinker.Start and StallBank.Warm (all three
// non-fatal) — bounded by connectTimeout, then hands the result to the
// actor via a single cmdConnected (success) or cmdConnectFailed (fatal).
//
// Cleanup ownership is exact: the connector owns everything it creates
// until hand-off, and hand-off is all-or-nothing via that one command. If
// the actor has already stopped (cmdStop, which exits the owner loop
// without cancelling ctx), if ctx itself is cancelled, or if the fatal
// Speaker fails after a non-fatal collaborator already started, the
// connector closes everything it holds before returning rather than
// leaking a hand-off nobody will ever receive.
func (a *actor) connect(ctx context.Context, cfg ports.SessionCfg, persona ports.PersonaCtx) {
	connectCtx, cancel := context.WithCancel(ctx)
	defer cancel()

	var (
		wg  sync.WaitGroup
		res connectAttempt
	)
	wg.Add(1)
	go func() {
		defer wg.Done()
		res.speaker, res.speakerErr = a.speaker.Start(connectCtx, cfg)
	}()
	if a.transcriber != nil {
		wg.Add(1)
		go func() {
			defer wg.Done()
			res.transcriberErr = a.transcriber.Start(connectCtx)
			res.transcriberDone = true
		}()
	}
	if a.thinker != nil {
		wg.Add(1)
		go func() {
			defer wg.Done()
			res.thinkerErr = a.thinker.Start(connectCtx, persona)
			res.thinkerDone = true
		}()
	}
	if a.stall != nil {
		wg.Add(1)
		go func() {
			defer wg.Done()
			res.stallErr = a.stall.Warm(connectCtx)
			res.stallDone = true
		}()
	}

	allDone := make(chan struct{})
	go func() {
		wg.Wait()
		close(allDone)
	}()

	// The connect budget is sourced from the injected Clock, never
	// time.After directly — internal/session may never call it, and the
	// point is real: FakeClock is what makes "a slow vendor is bounded by
	// the connect timeout" a test that actually advances no real time.
	select {
	case <-allDone:
	case <-a.clock.After(a.connectTimeout):
		// Cancel every in-flight Start/Warm call and wait for them to
		// actually return before deciding anything — abandoning a
		// still-running goroutine here would be exactly the kind of leak
		// goleak exists to catch, timeout or not.
		cancel()
		<-allDone
		// Attribute the timeout to whoever actually failed to finish, and
		// only then decide whether it is fatal.
		//
		// This used to mark the Speaker failed whenever the *aggregate*
		// deadline fired, whatever the cause. Two things were wrong with
		// that. It overwrote a Speaker that had already started fine — live,
		// one that had come up in 847 ms — so the log blamed the mouth for a
		// slow stall bank. And because the Speaker is the one fatal
		// collaborator, a slow pre-synthesis ended the interview instead of
		// degrading it, which is precisely the classification D8 exists to
		// stop. A misattributed error is worse than a vague one: it sends
		// whoever is on call to read the wrong code.
		if res.speaker == nil && res.speakerErr == nil {
			res.speakerErr = fmt.Errorf("session: connect: speaker did not start within %s", a.connectTimeout)
		}
		// The non-fatal collaborators each report their own timeout. Their
		// Start/Warm calls return a cancellation error of their own once
		// cancel() lands, but not every implementation is obliged to, so the
		// deadline is recorded here rather than assumed.
		if a.transcriber != nil && res.transcriberErr == nil && !res.transcriberDone {
			res.transcriberErr = fmt.Errorf("session: connect: transcriber did not start within %s", a.connectTimeout)
		}
		if a.thinker != nil && res.thinkerErr == nil && !res.thinkerDone {
			res.thinkerErr = fmt.Errorf("session: connect: thinker did not start within %s", a.connectTimeout)
		}
		if a.stall != nil && res.stallErr == nil && !res.stallDone {
			res.stallErr = fmt.Errorf("session: connect: stall bank did not warm within %s", a.connectTimeout)
		}
	}

	if a.hasStopped(ctx) {
		a.closeAttempt(res)
		return
	}
	if res.speakerErr != nil {
		// No mouth, no interview. Whatever non-fatal collaborator did come
		// up is released too — nothing here will ever be handed off.
		a.closeAttempt(res)
		a.sendConnectFailed(ctx, fmt.Errorf("session: connect speaker: %w", res.speakerErr))
		return
	}
	a.sendConnected(ctx, res)
}

// hasStopped reports whether the owner goroutine is known to be gone
// (a.stopped, closed as run's first deferred action) or ctx is done. Both
// are checked non-blockingly: this is a snapshot, not a wait.
func (a *actor) hasStopped(ctx context.Context) bool {
	select {
	case <-a.stopped:
		return true
	default:
	}
	select {
	case <-ctx.Done():
		return true
	default:
	}
	return false
}

// sendConnected attempts the connector's one and only hand-off. If the
// actor is gone by the time the send would happen, res's collaborators are
// closed here instead — the same "owns it until hand-off" rule applied at
// the last possible moment.
func (a *actor) sendConnected(ctx context.Context, res connectAttempt) {
	cmd := command{Kind: cmdConnected, Connected: &connectOutcome{
		Speaker:           res.speaker,
		TranscriberFailed: res.transcriberErr != nil,
		ThinkerFailed:     res.thinkerErr != nil,
		StallFailed:       res.stallErr != nil,
	}}
	select {
	case a.control <- cmd:
	case <-a.stopped:
		a.closeAttempt(res)
	case <-ctx.Done():
		a.closeAttempt(res)
	}
}

// sendConnectFailed delivers a fatal connect failure. Nothing further to
// clean up here — closeAttempt has already run in connect before this is
// called — so a lost race against actor shutdown is simply dropped.
func (a *actor) sendConnectFailed(ctx context.Context, err error) {
	cmd := command{Kind: cmdConnectFailed, Err: err}
	select {
	case a.control <- cmd:
	case <-a.stopped:
	case <-ctx.Done():
	}
}

// closeAttempt releases whatever a connect attempt actually opened, for the
// case where the result will never be handed off: a fatal Speaker failure,
// or the actor already gone. Only collaborators that actually started
// (err == nil) are closed — a nil Speaker.Start result on error is not a
// session to close, and a collaborator that never ran (nil in Deps) has
// nothing to release either.
func (a *actor) closeAttempt(res connectAttempt) {
	bg := context.Background()
	if res.speaker != nil {
		_ = res.speaker.Close(bg)
	}
	if a.transcriber != nil && res.transcriberErr == nil {
		_ = a.transcriber.Close(bg)
	}
	if a.thinker != nil && res.thinkerErr == nil {
		_ = a.thinker.Close(bg)
	}
	// StallBank has no Close method on the port — Warm only pre-computes
	// clips in memory, nothing to release.
}

// closeConnectOutcome mirrors closeAttempt for the drain-on-exit path in
// run: a cmdConnected that raced into the buffered control channel after
// the owner loop stopped reading it still names collaborators nobody will
// ever use.
func (a *actor) closeConnectOutcome(out *connectOutcome) {
	bg := context.Background()
	if out.Speaker != nil {
		_ = out.Speaker.Close(bg)
	}
	if a.transcriber != nil && !out.TranscriberFailed {
		_ = a.transcriber.Close(bg)
	}
	if a.thinker != nil && !out.ThinkerFailed {
		_ = a.thinker.Close(bg)
	}
}

// closeCollaborators releases every vendor-backed resource the session
// picked up over its lifetime: the connected Speaker session, the
// transcriber and thinker if they came up, and the accepted media
// connection. Called unconditionally as part of run's teardown, regardless
// of which of the two ways run exits — this is specifically what makes the
// Speaker event pump exit on a cmdStop-driven stop: closing a.speaking
// closes its Events() stream, which is the pump's other exit condition
// besides ctx.Done().
func (a *actor) closeCollaborators() {
	bg := context.Background()
	if a.speaking != nil {
		if err := a.speaking.Close(bg); err != nil {
			a.logger.Warn("speaker session close failed", "err", err)
		}
	}
	if a.transcriber != nil {
		if err := a.transcriber.Close(bg); err != nil {
			a.logger.Warn("transcriber close failed", "err", err)
		}
	}
	if a.thinker != nil {
		if err := a.thinker.Close(bg); err != nil {
			a.logger.Warn("thinker close failed", "err", err)
		}
	}
	if a.mediaConn != nil {
		if err := a.mediaConn.Close(bg); err != nil {
			a.logger.Warn("media connection close failed", "err", err)
		}
	}
}

// drainPendingConnect catches a cmdConnected (or a pending
// cmdAttachTransport) still sitting in the control channel's buffer once
// the owner loop has stopped reading it. A select-based hand-off narrows
// this race but cannot close it entirely: a buffered channel accepts a
// send whether or not anyone is still receiving, so without this drain a
// connector that wins that last race leaks the very collaborators it
// successfully connected.
func (a *actor) drainPendingConnect() {
	for {
		select {
		case cmd := <-a.control:
			switch {
			case cmd.Connected != nil:
				a.closeConnectOutcome(cmd.Connected)
			case cmd.Kind == cmdAttachTransport:
				a.replyAttach(cmd.Reply, attachOutcome{Err: ErrSessionNotFound})
			}
		default:
			return
		}
	}
}

// pumpSpeakerEvents drains sess.Events() into the actor's two Speaker
// channels under two different policies (plan §4):
//
//   - ports.AudioDelta goes through offerDrop onto audio, bounded and
//     drop-oldest. Under jitter the freshest frame reflects reality; the
//     stalest is the one worth losing.
//   - Everything else — transcript deltas, input transcripts, tool calls,
//     speech-started, response-done, Speaker errors — is a blocking send
//     onto ctrl. Transcript deltas are control, not audio: the actor counts
//     sentences from them to enforce max_sentences, so dropping one
//     silently corrupts that.
//
// Every blocking send carries the ctx.Done() escape. Without it, session
// teardown (ctrl full, nobody left to drain it) strands this pump forever
// even though Events() itself may never close either — goleak would start
// failing intermittently, not reliably, which is the dangerous kind of
// missing escape.
//
// The pump exits when Events() closes or ctx is done, and never outlives
// the session: closeCollaborators closes sess as part of the actor's own
// teardown specifically so Events() ends here too.
func pumpSpeakerEvents(
	ctx context.Context,
	sess ports.SpeakerSession,
	audio chan ports.SpeakerEvent,
	ctrl chan ports.SpeakerEvent,
	d *drops,
) {
	events := sess.Events()
	for {
		select {
		case ev, ok := <-events:
			if !ok {
				return
			}
			if _, isAudio := ev.(ports.AudioDelta); isAudio {
				if offerDrop(audio, ev) {
					d.SpeakerAudio.Add(1)
				}
				continue
			}
			select {
			case ctrl <- ev:
			case <-ctx.Done():
				return
			}
		case <-ctx.Done():
			return
		}
	}
}

// pumpMediaConn forwards one media connection's inbound streams into the
// actor's mailbox.
//
// Without it the media plane and the turn loop are two working halves that
// never meet: micAudio and playoutBeat are read by the actor's loop and, until
// this existed, written by nothing in production — so a browser could attach,
// stream audio, and have none of it reach the session.
//
// The policy split mirrors the Speaker pump. Audio is drop-oldest: losing a
// frame is a glitch, and blocking here stops the whole connection being read,
// which would silence the heartbeats and speech signals travelling beside it.
// Heartbeats are newest-wins for the same reason they exist — only the latest
// playout position matters. Speech events never drop: an onset drives the
// vendor activity window, and the live API discards audio sent outside one in
// silence.
func pumpMediaConn(ctx context.Context, conn ports.MediaConn, a *actor) {
	audio := conn.AudioIn()
	beats := conn.PlayoutHeartbeats()
	speech := conn.Speech()

	for {
		select {
		case <-ctx.Done():
			return
		case f, ok := <-audio:
			if !ok {
				return
			}
			if offerDrop(a.micAudio, micFrame{Frame: f, At: f.Timestamp}) {
				a.drops.MicAudio.Add(1)
			}
		case hb, ok := <-beats:
			if !ok {
				beats = nil
				continue
			}
			if offerDrop(a.playoutBeat, heartbeat{ItemID: hb.ItemID, PlayedMs: hb.HeardMs, At: hb.At}) {
				a.drops.Heartbeats.Add(1)
			}
		case ev, ok := <-speech:
			if !ok {
				speech = nil
				continue
			}
			select {
			case a.speechOnset <- ev:
			case <-ctx.Done():
				return
			}
		}
	}
}
