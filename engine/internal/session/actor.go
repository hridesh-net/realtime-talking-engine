package session

import (
	"context"
	"log/slog"
	"time"

	"skillbrew/engine/internal/contract"
	"skillbrew/engine/internal/obs"
	"skillbrew/engine/internal/ports"
)

// defaultSampleRate is the PCM16 rate every Speaker adapter normalizes to at
// the vendor boundary.
const defaultSampleRate = 24000

// pregateDeadline bounds the wait for a pre-gate verdict after end-of-turn
// (plan §4 step 3). Losing the race is not an error: the system prompt is the
// backstop, so the turn proceeds as CONFIDENT and the loss is logged.
const pregateDeadline = 250 * time.Millisecond

// actor is the per-session owner goroutine of plan §4: exactly one goroutine
// holds all mutable session state, so nothing here needs a mutex — every
// field is touched only from inside run. Everything else message-passes in.
//
// The pumps that feed it (transport readers, transcriber, Speaker event
// stream, timer waiters) carry no logic. They convert I/O into messages. All
// the decisions live here, in one place, single-threaded, which is what makes
// a real-time turn loop testable at all.
type actor struct {
	id       string
	contract *contract.EngineContract
	clock    ports.Clock
	logger   *slog.Logger
	events   *obs.EventLog

	// ---- state, owner-goroutine only -------------------------------------
	state   State
	turn    int
	timers  *timerSet
	playout *playoutTracker
	turns   *turnTable
	// sentences enforces the response's sentence bound, reset per response.
	sentences sentenceCounter
	// probedSkill is the pre-gate's classification for the in-flight turn.
	probedSkill string
	// deferred and fallbackUsed describe how the in-flight persona turn was
	// produced, and ride out in the turn record for the grader.
	deferred     bool
	fallbackUsed bool
	drops        drops
	// pendingVerdict is the pre-gate result for the utterance in flight.
	pendingVerdict *pregateVerdict
	// speaking is the Speaker session, nil until CONNECTING completes.
	speaking ports.SpeakerSession

	// ---- inbound channels, per plan §4's policy table ---------------------
	control      chan command
	timerFire    chan timerFire
	micAudio     chan micFrame
	asrPartial   chan ports.Partial
	speakerAudio chan ports.SpeakerEvent
	speakerCtrl  chan ports.SpeakerEvent
	pregate      chan pregateVerdict
	playoutBeat  chan heartbeat
}

// newActor constructs a session actor. It does not start the owner goroutine
// — call run in its own goroutine to do that.
func newActor(
	id string,
	c *contract.EngineContract,
	clock ports.Clock,
	logger *slog.Logger,
	events *obs.EventLog,
) *actor {
	fires := make(chan timerFire, timerBufferSize)
	return &actor{
		id:       id,
		contract: c,
		clock:    clock,
		logger:   logger,
		events:   events,
		state:    StateConnecting,
		timers:   newTimerSet(clock, fires),
		playout:  newPlayoutTracker(defaultSampleRate),
		turns:    newTurnTable(clock.Now()),

		control:      make(chan command, controlBufferSize),
		timerFire:    fires,
		micAudio:     make(chan micFrame, micAudioBufferSize),
		asrPartial:   make(chan ports.Partial, asrPartialBufferSize),
		speakerAudio: make(chan ports.SpeakerEvent, speakerAudioBufferSize),
		speakerCtrl:  make(chan ports.SpeakerEvent, speakerCtrlBufferSize),
		pregate:      make(chan pregateVerdict, 1),
		playoutBeat:  make(chan heartbeat, heartbeatBufferSize),
	}
}

// emit writes one event stamped from the session clock.
func (a *actor) emit(typ string, fields map[string]any) {
	a.events.Emit(a.clock.Now(), typ, a.turn, fields)
}

// transition moves to a new state, refusing and logging an illegal edge
// rather than silently taking it. An illegal transition is a bug in the
// caller, and a real-time loop that quietly accepts one produces a session
// that is wrong in a way nobody can reconstruct afterwards.
func (a *actor) transition(to State, reason string) bool {
	from := a.state
	if from == to {
		return true
	}
	if !canTransition(from, to) {
		a.logger.Error("illegal state transition",
			"from", from.String(), "to", to.String(), "reason", reason)
		a.emit("illegal_transition", map[string]any{
			"from": from.String(), "to": to.String(), "reason": reason,
		})
		return false
	}
	a.state = to
	a.emit("state_transition", map[string]any{
		"from": from.String(), "to": to.String(), "reason": reason,
	})
	// Leaving a speaking-ish state for a listening one closes the turn's
	// alarms. Doing it here rather than at each call site is what stops a
	// stall timer outliving the turn that armed it.
	if from.speakingish() && !to.speakingish() {
		a.timers.cancelTurnScoped()
	}
	return true
}

// run is the actor's owner goroutine: the only goroutine that ever touches
// the actor's fields after construction. It returns the instant ctx is
// cancelled, closing done on its way out so callers can block until this
// goroutine has fully exited.
//
// The loop is plan §4's nested select. `select` has no priority, so a single
// flat select would let a saturated audio channel starve control and timer
// traffic — a stop command queued behind a hundred audio frames, a deadline
// fired but not acted on. The loop therefore drains control and timers
// non-blockingly first, and only blocks on the full set once both are empty.
func (a *actor) run(ctx context.Context, done chan<- struct{}) {
	defer close(done)
	defer a.timers.cancelAll()
	a.logger.Info("session actor started")
	defer a.logger.Info("session actor stopped")
	a.emit("session_started", map[string]any{"session_id": a.id})

	for {
		// Priority drain: decisions before media, always.
		select {
		case cmd, ok := <-a.control:
			if !ok {
				return
			}
			if a.handle(ctx, cmd) {
				return
			}
			continue
		case f := <-a.timerFire:
			a.handleTimer(ctx, f)
			continue
		default:
		}

		select {
		case <-ctx.Done():
			a.logger.Info("session actor stopping", "reason", ctx.Err())
			a.emit("session_stopped", map[string]any{"reason": ctx.Err().Error()})
			return
		case cmd, ok := <-a.control:
			if !ok {
				return
			}
			if a.handle(ctx, cmd) {
				return
			}
		case f := <-a.timerFire:
			a.handleTimer(ctx, f)
		case p := <-a.asrPartial:
			a.handlePartial(ctx, p)
		case v := <-a.pregate:
			a.handlePregate(ctx, v)
		case hb := <-a.playoutBeat:
			a.playout.heartbeat(hb.ItemID, hb.PlayedMs, hb.At)
		case ev := <-a.speakerCtrl:
			a.handleSpeakerEvent(ctx, ev)
		case ev := <-a.speakerAudio:
			a.handleSpeakerEvent(ctx, ev)
		case m := <-a.micAudio:
			a.handleMic(ctx, m)
		}
	}
}

// handle processes one control command. It returns true when the actor should
// exit its loop.
func (a *actor) handle(ctx context.Context, cmd command) bool {
	switch cmd.Kind {
	case cmdInterviewerJoined:
		a.transition(StateGreeting, "interviewer joined")
	case cmdStop:
		a.windDown(ctx, cmd.Reason)
		return true
	}
	return false
}

// windDown takes the session out in character, then finalizes.
func (a *actor) windDown(_ context.Context, reason string) {
	a.timers.cancelAll()
	if a.transition(StateWindingDown, reason) {
		a.transition(StateFinalizing, reason)
		a.transition(StateDone, reason)
	}
	a.emit("session_stopped", map[string]any{"reason": reason})
}

// handleTimer acts on one alarm, ignoring stale fires.
//
// The generation check is what makes cancellation real: stopping a timer does
// not retract a fire already in flight, so without it a stall alarm cancelled
// during barge-in still drives a response for a turn that no longer exists.
func (a *actor) handleTimer(ctx context.Context, f timerFire) {
	if !a.timers.live(f) {
		a.emit("timer_stale", map[string]any{"kind": f.Kind.String()})
		return
	}
	a.timers.cancel(f.Kind)
	a.emit("timer_fired", map[string]any{"kind": f.Kind.String()})

	switch f.Kind {
	case timerPregate:
		// Race lost. The system prompt is the backstop, so proceed as
		// CONFIDENT rather than stalling on a verdict that never came.
		a.emit("pregate_race_lost", nil)
		a.beginAnswer(ctx, "pregate race lost")
	case timerPause:
		a.createResponse(ctx, "pause elapsed")
	case timerSilence, timerSession:
		a.windDown(ctx, f.Kind.String()+" cap")
	}
}

// handlePartial feeds an in-progress interviewer utterance forward and closes
// the turn on the first final.
func (a *actor) handlePartial(ctx context.Context, p ports.Partial) {
	if !p.Final {
		// The interviewer is still speaking. Open their turn on the first
		// partial so start_ms reflects when they began, not when they
		// stopped.
		if a.state == StateListening && a.turns.open == nil {
			a.turns.begin(a.turn+1, speakerHuman, a.clock.Now())
			a.pendingVerdict = nil
		}
		return
	}
	switch a.state {
	case StateGreeting:
		// The interviewer's first utterance has ended: play the
		// pre-synthesized opening line. Both halves are turns — the
		// greeting is where a manager either sets the frame or does not,
		// and "Hiring with Clarity" is scored partly on it.
		a.turn++
		if a.turns.open == nil {
			a.turns.begin(a.turn, speakerHuman, a.clock.Now())
		}
		a.turns.appendText(p.Text)
		a.turns.close(a.clock.Now())
		if !a.transition(StateSpeaking, "greeting") {
			return
		}
		a.sentences.reset()
		a.turns.begin(a.turn, speakerPersona, a.clock.Now())
		a.turns.appendText(a.contract.OpeningLine)
		a.emit("opening_line", nil)
	case StateListening:
		a.turn++
		if a.turns.open == nil {
			a.turns.begin(a.turn, speakerHuman, a.clock.Now())
		}
		a.turns.appendText(p.Text)
		a.turns.close(a.clock.Now())
		a.emit("utterance_end", map[string]any{"text": p.Text})
		// A verdict filed while the interviewer was still speaking belongs
		// to the utterance that just ended. Comparing turn numbers here is
		// wrong by construction — it was filed before the increment above.
		if v := a.pendingVerdict; v != nil {
			a.applyVerdict(ctx, *v)
			return
		}
		// No verdict yet — give it the deadline before defaulting.
		a.timers.arm(timerPregate, pregateDeadline)
	}
}

// handlePregate records or applies a pre-gate verdict.
//
// The pre-gate classifies from partial transcripts, so a verdict usually
// arrives *before* the interviewer has finished speaking — that is the whole
// point of it, since a defer must start stalling within 50 ms of end-of-turn.
// The signal for "apply it now" is therefore whether end-of-turn has already
// happened, which is exactly what the pre-gate deadline being armed means.
// Keying off the state instead was wrong: the actor is still LISTENING at
// end-of-turn, so a verdict arriving then was filed as pending and never
// applied, and every turn fell through to the race-lost fallback.
func (a *actor) handlePregate(ctx context.Context, v pregateVerdict) {
	if a.timers.isArmed(timerPregate) {
		a.timers.cancel(timerPregate)
		a.applyVerdict(ctx, v)
		return
	}
	if a.state == StateListening {
		a.pendingVerdict = &v
	}
}

// applyVerdict branches the turn on the pre-gate's classification.
func (a *actor) applyVerdict(ctx context.Context, v pregateVerdict) {
	a.pendingVerdict = nil
	a.probedSkill = v.Skill
	a.deferred = v.Defer
	a.fallbackUsed = false
	// The probed skill belongs to the interviewer's turn that just closed:
	// "what did the manager ask about" is the question the grader needs
	// answered, and it is only knowable after the pre-gate has classified.
	a.turns.tagLast(v.Skill, v.Defer)
	a.emit("pregate_verdict", map[string]any{
		"skill": v.Skill, "defer": v.Defer,
	})
	if v.Defer {
		a.transition(StateDeferred, "pregate defer")
		return
	}
	a.beginAnswer(ctx, "pregate confident")
}

// beginAnswer enters PRE_ANSWER and arms the human-pause delay.
func (a *actor) beginAnswer(_ context.Context, reason string) {
	if !a.transition(StatePreAnswer, reason) {
		return
	}
	pause := time.Duration(a.contract.VoiceDirectives.TargetPauseBeforeAnswerMs) * time.Millisecond
	if pause <= 0 {
		pause = time.Millisecond
	}
	a.timers.arm(timerPause, pause)
}

// createResponse asks the Speaker for the persona's turn.
func (a *actor) createResponse(ctx context.Context, reason string) {
	if !a.transition(StateSpeaking, reason) {
		return
	}
	if a.speaking == nil {
		return
	}
	a.sentences.reset()
	a.turns.begin(a.turn, speakerPersona, a.clock.Now())
	tp := a.contract.TurnPolicy
	err := a.speaking.CreateResponse(ctx, ports.ResponseDirectives{
		MinSentences:    tp.MinSentences,
		MaxSentences:    tp.MaxSentences,
		TargetSentences: tp.TargetSentencesPerAnswer,
		AnswerDepth:     tp.DefaultAnswerDepth,
	})
	if err != nil {
		a.logger.Error("create response failed", "err", err)
		a.emit("create_response_failed", map[string]any{"err": err.Error()})
	}
}

// trimResponse cuts a response that has run past its sentence allowance.
//
// A soft trim: the vendor stops generating, the audio already sent still
// plays. Length is one of the few ceiling layers that is an actual guarantee
// rather than best-effort model compliance (plan §6 layer 5), and a persona
// that monologues is one the interviewer never gets to practise interrupting.
func (a *actor) trimResponse(ctx context.Context) {
	if a.state != StateSpeaking || a.speaking == nil {
		return
	}
	if a.turns.open != nil {
		a.turns.open.Trimmed = true
	}
	if err := a.speaking.CancelResponse(ctx); err != nil {
		a.logger.Warn("sentence-bound trim failed", "err", err)
	}
	a.emit("sentence_trim", map[string]any{
		"sentences": a.sentences.completed,
		"max":       a.contract.TurnPolicy.MaxSentences,
	})
	a.sentences.reset()
}

// closePersonaTurn finalizes the in-flight persona turn record.
func (a *actor) closePersonaTurn(bargedIn bool, heardMs int) {
	if a.turns.open == nil {
		return
	}
	a.turns.open.ProbedSkill = a.probedSkill
	a.turns.open.Deferred = a.deferred
	a.turns.open.FallbackUsed = a.fallbackUsed
	a.turns.open.BargedIn = bargedIn
	a.turns.open.HeardMs = heardMs
	a.turns.close(a.clock.Now())
}

// Turns returns the session's turn table. Read after the actor has stopped.
func (a *actor) Turns() []TurnRecord { return a.turns.Records() }

// handleMic forwards the interviewer's audio to the Speaker, honouring the
// mic gate when the persona does not allow barge-in.
//
// Even when gated, the frame still reaches the recorder and transcriber
// upstream of here: an ignored interruption attempt is itself feedback data.
func (a *actor) handleMic(ctx context.Context, m micFrame) {
	if a.speaking == nil {
		return
	}
	if a.state == StateSpeaking && !a.contract.VoiceDirectives.MayInterrupt {
		return
	}
	if err := a.speaking.SendAudio(ctx, m.Frame); err != nil {
		a.logger.Warn("send audio failed", "err", err)
	}
}

// handleSpeakerEvent reacts to the Speaker's normalized event stream.
func (a *actor) handleSpeakerEvent(ctx context.Context, ev ports.SpeakerEvent) {
	switch e := ev.(type) {
	case ports.AudioDelta:
		if !a.playout.active() {
			a.playout.begin(e.ResponseID, a.clock.Now())
		}
		a.playout.sent(len(e.Frame.PCM))
	case ports.OutputTranscriptDelta:
		a.turns.appendText(e.Text)
		if a.sentences.feed(e.Text, a.contract.TurnPolicy.MaxSentences) {
			a.trimResponse(ctx)
		}
	case ports.SpeechStarted:
		a.bargeIn(ctx)
	case ports.ResponseDone:
		a.playout.close(a.clock.Now())
		a.closePersonaTurn(false, 0)
		a.transition(StateListening, "response done")
	}
}

// bargeIn takes a speaking session into DRAINING: cancel the response,
// truncate the vendor's history at what was actually *heard*, kill every turn
// alarm, and land back in LISTENING.
//
// Truncating at heardMs rather than bytes-sent is the point. Audio sits in the
// out-ring, the jitter buffer and the output device; telling the vendor the
// persona said things nobody heard poisons every later turn's reasoning.
func (a *actor) bargeIn(ctx context.Context) {
	if !a.state.speakingish() {
		a.emit("barge_in_ignored", map[string]any{"state": a.state.String()})
		return
	}
	if !a.contract.VoiceDirectives.MayInterrupt && a.state == StateSpeaking {
		// The persona does not yield. The attempt is still recorded — an
		// interviewer who tried to interrupt and was talked over is
		// feedback, not noise.
		a.emit("barge_in_refused", map[string]any{"state": a.state.String()})
		return
	}
	now := a.clock.Now()
	itemID := a.playout.itemID
	sentMs := a.playout.sentMs()
	heardMs := a.playout.close(now)

	if !a.transition(StateDraining, "barge-in") {
		return
	}
	a.timers.cancelTurnScoped()

	if a.speaking != nil {
		if err := a.speaking.CancelResponse(ctx); err != nil {
			a.logger.Warn("cancel response failed", "err", err)
		}
		if itemID != "" {
			if err := a.speaking.Truncate(ctx, itemID, heardMs); err != nil {
				a.logger.Warn("truncate failed", "err", err)
			}
		}
	}
	a.closePersonaTurn(true, heardMs)
	a.emit("barge_in", map[string]any{
		"item_id": itemID, "heard_ms": heardMs, "sent_ms": sentMs,
	})
	a.transition(StateListening, "drained")
}
