package session

import (
	"context"
	"fmt"
	"log/slog"
	"sort"
	"strconv"
	"strings"
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

// thinkerDeadline bounds how long a stall clip covers for the reasoning model
// before the actor gives up and uses the contract's own fallback directive.
// Missing it is a degradation, not a failure: the fallback is still
// persona-correct behaviour (plan §6 layer 3's floor).
const thinkerDeadline = 700 * time.Millisecond

// ledgerRefreshTurns is how often the compact "what you have already said"
// summary is re-injected into the speech model's context. Realtime models
// forget the detail of their own audio history; this is cheap insurance.
const ledgerRefreshTurns = 4

// ceilingReassertTurns is how often the knowledge ceiling is re-sent as a
// system item (plan §6 layer 4). Best-effort, like every pre-speech layer.
const ceilingReassertTurns = 5

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
	// utterance accumulates the interviewer's in-flight speech, so the
	// pre-gate classifies the whole question rather than one delta.
	utterance string
	// speaking is the Speaker session, nil until the connector hands one
	// off via cmdConnected.
	speaking ports.SpeakerSession
	// thinker is the persona's subconscious. Nil degrades the session to
	// the single-model path rather than refusing to run — either because
	// no Thinker was configured, or because it failed to connect.
	thinker ports.Thinker
	// gate classifies probes from partial speech, without a model call.
	gate ports.PreGate
	// ledger is what this persona has committed to saying. The actor is its
	// only writer.
	ledger ports.ClaimLedger

	// transport accepts the client's SDP offer. Nil is legal (no adapter
	// wired yet); AttachTransport then fails with ErrNoTransportConfigured
	// rather than panicking.
	transport ports.Transport
	// speaker opens the fatal, must-have realtime speech session. A nil
	// speaker makes the connector fail fatally — no mouth, no interview.
	speaker ports.Speaker
	// transcriber runs the independent ASR stream. Nil degrades the
	// session (flagged degraded:asr) rather than ending it — either
	// because none was configured, or its connect failed.
	transcriber ports.Transcriber
	// stall pre-synthesizes stall clips and the opening line. Nil degrades
	// the session (flagged degraded:stall) rather than ending it.
	stall ports.StallBank
	// judge, recorder and finalizer have no connect-time operation on
	// their ports (no Start/Warm to fail), so they are wired once at
	// construction and never touched by the connector.
	judge     ports.Judge
	recorder  ports.Recorder
	finalizer ports.Finalizer

	// silenceTimeout and sessionCap are the two session-scoped alarms'
	// durations. Zero disables the alarm rather than arming it at zero.
	silenceTimeout time.Duration
	sessionCap     time.Duration

	// connectTimeout bounds the connector's concurrent vendor starts.
	connectTimeout time.Duration
	// transportAttached is true once AttachTransport has accepted an
	// offer; a second attempt is a conflict, not a second connector.
	transportAttached bool
	// mediaConn is the accepted transport connection, set alongside
	// transportAttached.
	mediaConn ports.MediaConn
	// degradations lists every best-effort collaborator that failed to
	// connect this session, in the SessionIngest.Degradations vocabulary
	// (e.g. "degraded:asr"). Owner-goroutine only.
	degradations []string
	// stopped is closed exactly once, as run's very first deferred action,
	// so any goroutine started off the actor (the connector, the Speaker
	// event pump) can detect "the owner goroutine is gone" independent of
	// ctx — cmdStop exits run without cancelling ctx, and a goroutine that
	// only watched ctx.Done() would never learn that happened.
	stopped chan struct{}

	// unlocked is monotonic: the Thinker assesses, the actor decides, and
	// once depth is earned it is never taken back (plan §7).
	unlocked   bool
	unlockTurn int
	// lastLedgerInject and lastCeilingAssert drive the two cadences above.
	lastLedgerInject  int
	lastCeilingAssert int
	// turnGate is closed when the in-flight turn's async work becomes void
	// — the note arrived, the deadline passed, the interviewer barged in.
	// Without it the note pump only exits when the *session* ends, so a
	// session with twenty defers carries twenty stranded goroutines. Tying
	// it to the turn rather than the session is the same discipline as the
	// timer generations: cancellation has to be a fact, not a hope.
	turnGate chan struct{}

	// ---- inbound channels, per plan §4's policy table ---------------------
	control      chan command
	timerFire    chan timerFire
	micAudio     chan micFrame
	asrPartial   chan ports.Partial
	speakerAudio chan ports.SpeakerEvent
	speakerCtrl  chan ports.SpeakerEvent
	pregate      chan pregateVerdict
	notes        chan thinkerNote
	playoutBeat  chan heartbeat
	// speechOnset carries locally-detected speech starts from the media
	// connection. Onset only: end-of-turn belongs to the Transcriber,
	// because an energy threshold cannot tell a thinking pause from a
	// finished question, and the human here is composing one.
	speechOnset chan ports.VADEvent
}

// newActor constructs a session actor. It does not start the owner goroutine
// — call run in its own goroutine to do that.
func newActor(
	id string,
	c *contract.EngineContract,
	clock ports.Clock,
	logger *slog.Logger,
	events *obs.EventLog,
	deps Deps,
) *actor {
	fires := make(chan timerFire, timerBufferSize)
	return &actor{
		id:             id,
		contract:       c,
		clock:          clock,
		logger:         logger,
		events:         events,
		thinker:        deps.Thinker,
		gate:           deps.PreGate,
		ledger:         deps.Ledger,
		transport:      deps.Transport,
		speaker:        deps.Speaker,
		transcriber:    deps.Transcriber,
		stall:          deps.Stall,
		judge:          deps.Judge,
		recorder:       deps.Recorder,
		finalizer:      deps.Finalizer,
		connectTimeout: deps.ConnectTimeout,
		silenceTimeout: deps.SilenceTimeout,
		sessionCap:     deps.SessionDurationCap,
		state:          StateConnecting,
		timers:         newTimerSet(clock, fires),
		playout:        newPlayoutTracker(defaultSampleRate),
		turns:          newTurnTable(clock.Now()),
		stopped:        make(chan struct{}),

		control:      make(chan command, controlBufferSize),
		timerFire:    fires,
		micAudio:     make(chan micFrame, micAudioBufferSize),
		asrPartial:   make(chan ports.Partial, asrPartialBufferSize),
		speakerAudio: make(chan ports.SpeakerEvent, speakerAudioBufferSize),
		speakerCtrl:  make(chan ports.SpeakerEvent, speakerCtrlBufferSize),
		pregate:      make(chan pregateVerdict, 1),
		// Size 1, newest wins: a note for a turn that has moved on is
		// worthless, and holding a queue of them only delays discovering
		// that.
		notes:       make(chan thinkerNote, 1),
		playoutBeat: make(chan heartbeat, heartbeatBufferSize),
		speechOnset: make(chan ports.VADEvent, speechBufferSize),
	}
}

// Deps are the collaborators a session runs against. Almost every one is
// optional, and nil degrades rather than refuses to open — the right
// failure for a live interview (plan §11) — with two exceptions: Speaker
// and Transport are the persona's mouth and the media path, and a session
// with neither cannot run an interview at all, so the connector fails
// fatally without them (see the DepsFactory doc comment for the full
// failure classification).
//
// They arrive as ports rather than concrete types because internal/session may
// only import ports, contract and obs — the layering gate enforces it, and the
// reason is this: the orchestrator must not know which reasoning model, which
// lexicon implementation, or which ledger it is driving.
type Deps struct {
	Thinker ports.Thinker
	PreGate ports.PreGate
	Ledger  ports.ClaimLedger

	// Transport accepts the client's SDP offer. Fatal if nil once a client
	// actually tries to attach — no media path, no interview.
	Transport ports.Transport
	// Speaker opens the realtime speech session. Fatal if nil — no mouth,
	// no interview.
	Speaker ports.Speaker
	// Transcriber runs the independent ASR stream. Non-fatal: a failed or
	// absent Transcriber flags the session degraded:asr and it continues.
	Transcriber ports.Transcriber
	// Judge runs async, post-hoc semantic review. Non-fatal: it has no
	// connect-time operation, so it is wired at construction and never
	// blocks or fails the connect.
	Judge ports.Judge
	// Stall pre-synthesizes stall clips and the opening line. Non-fatal: a
	// failed or absent StallBank flags the session degraded:stall.
	Stall ports.StallBank
	// Recorder captures the dual-channel recording. Non-fatal by the
	// port's own contract (RecordingInfo.Degraded); no connect-time
	// operation, wired at construction.
	Recorder ports.Recorder
	// Finalizer assembles and hands off the finished bundle. Non-fatal by
	// the port's own contract; no connect-time operation, wired at
	// construction.
	Finalizer ports.Finalizer

	// ConnectTimeout bounds how long the per-session connector waits for
	// Speaker.Start, Transcriber.Start, Thinker.Start and StallBank.Warm
	// before giving up. It is a plain value, not read from the
	// environment here — internal/session may not import internal/config
	// — DepsFactory implementations project config.Config.ConnectTimeout
	// into this field.
	ConnectTimeout time.Duration

	// SilenceTimeout is how long the session tolerates an interviewer who
	// has stopped participating before winding down in character, and
	// SessionDurationCap is the hard wall-clock ceiling on one interview.
	//
	// Plain values for the same reason as ConnectTimeout: internal/session
	// may not import internal/config, so a DepsFactory projects them in.
	// Zero means "no cap", which is what every test that does not care
	// gets — the alarm is simply never armed.
	SilenceTimeout     time.Duration
	SessionDurationCap time.Duration
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
		a.closeTurnGate()
	}
	// The abandonment clock runs only while the session is actually
	// waiting on the interviewer. Centralised here rather than at each
	// edge for the same reason as the line above: LISTENING is entered
	// from five different places, and an alarm armed at four of them is
	// the kind of gap that reads as working.
	if to == StateListening {
		a.armSilenceCap()
	} else if from == StateListening {
		a.timers.cancel(timerSilence)
	}
	return true
}

// armSilenceCap starts the abandonment alarm, if one is configured.
//
// A zero duration means no cap. That is deliberate rather than a missing
// default: a cap of zero would fire immediately and end every session on its
// first tick, so the only safe reading of "unset" is "not armed".
func (a *actor) armSilenceCap() {
	if a.silenceTimeout <= 0 {
		return
	}
	a.timers.arm(timerSilence, a.silenceTimeout)
}

// armSessionCap starts the hard duration ceiling, if one is configured.
func (a *actor) armSessionCap() {
	if a.sessionCap <= 0 {
		return
	}
	a.timers.arm(timerSession, a.sessionCap)
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
	// Defers run LIFO, so this ordering is deliberate: close(a.stopped)
	// fires first, giving the connector and the Speaker event pump the
	// earliest possible signal that the owner goroutine is gone (cmdStop
	// exits this loop without cancelling ctx, so ctx.Done() alone would
	// never tell them); closeCollaborators then releases whatever was
	// actually handed off during normal operation; drainPendingConnect
	// catches a cmdConnected that raced into the buffered control channel
	// after this loop stopped reading it — a hand-off a select alone
	// cannot fully close off, since a buffered send succeeds whether or
	// not anyone is still receiving; close(done) runs last, so by the time
	// callers unblock on it every collaborator this run reached is closed.
	defer close(done)
	defer a.drainPendingConnect()
	defer a.closeCollaborators()
	defer a.timers.cancelAll()
	defer a.closeTurnGate()
	defer close(a.stopped)
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
		case n := <-a.notes:
			a.handleNote(ctx, n)
		case hb := <-a.playoutBeat:
			a.playout.heartbeat(hb.ItemID, hb.PlayedMs, hb.At)
		case ev := <-a.speechOnset:
			a.handleSpeechOnset(ctx, ev)
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
		if a.transition(StateGreeting, "interviewer joined") {
			// The hard duration cap starts when the interview does, not
			// when the actor was constructed: a session can sit in
			// CONNECTING while nobody is talking, and charging that to
			// the interviewer's hour would cut a real interview short.
			a.armSessionCap()
		}
	case cmdStop:
		a.windDown(ctx, cmd.Reason)
		return true
	case cmdAttachTransport:
		return a.handleAttachTransport(ctx, cmd)
	case cmdConnected:
		a.handleConnected(ctx, cmd.Connected)
	case cmdConnectFailed:
		a.handleConnectFailed(ctx, cmd.Err)
		return true
	}
	return false
}

// degradation reasons, in the SessionIngest.Degradations vocabulary (see
// ports.SessionIngest's doc comment). Recorded on the actor and emitted to
// the event log the moment a non-fatal collaborator fails to connect.
const (
	degradedASR     = "degraded:asr"
	degradedThinker = "degraded:thinker"
	degradedStall   = "degraded:stall"
)

// handleAttachTransport accepts the client's SDP offer and, on success,
// spawns the per-session connector. A session negotiates media exactly
// once: a second attempt is a conflict, not a second connector.
//
// Transport.Accept runs here, on ctx (the actor's own run context, never
// wrapped in connectTimeout) rather than inside connect: SDP answer
// generation is local and cheap by the port's own contract, and bundling it
// into the vendor-connect budget would make a slow vendor look like a bad
// offer.
//
// It returns true exactly when it has itself ended the session (the nil
// Transport and nil Speaker fatal branches both call handleConnectFailed
// directly rather than going through the cmdConnectFailed command, so
// handle's own dispatch can't tell the loop to exit for them — this is how
// it does).
func (a *actor) handleAttachTransport(ctx context.Context, cmd command) bool {
	if a.transportAttached {
		a.replyAttach(cmd.Reply, attachOutcome{Err: ErrTransportAlreadyAttached})
		return false
	}
	if a.transport == nil {
		// Fatal per the connect failure classification — no media path, no
		// interview — same as a nil Speaker. Unlike that case there is no
		// answer to give back (Accept was never attempted), so the caller
		// gets the error and the session winds down in the background.
		a.replyAttach(cmd.Reply, attachOutcome{Err: ErrNoTransportConfigured})
		a.handleConnectFailed(ctx, ErrNoTransportConfigured)
		return true
	}
	answer, conn, err := a.transport.Accept(ctx, cmd.Offer)
	if err != nil {
		a.replyAttach(cmd.Reply, attachOutcome{Err: fmt.Errorf("session: accept transport offer: %w", err)})
		return false
	}
	a.transportAttached = true
	a.mediaConn = conn
	a.emit("transport_attached", nil)

	if a.speaker == nil {
		// Fatal per the connect failure classification — no mouth, no
		// interview — but the media handshake itself succeeded, so the
		// caller still gets its answer before the session winds down.
		a.replyAttach(cmd.Reply, attachOutcome{Answer: answer})
		a.handleConnectFailed(ctx, ErrNoSpeakerConfigured)
		return true
	}

	cfg, persona := a.buildConnectInputs()
	go a.connect(ctx, cfg, persona)
	a.replyAttach(cmd.Reply, attachOutcome{Answer: answer})
	return false
}

// replyAttach delivers a cmdAttachTransport's outcome, when the caller left
// a Reply channel to receive it. reply is always a fresh channel buffered
// for exactly one send (Manager.AttachTransport's own doing), so this never
// blocks the owner goroutine on a caller that gave up.
func (a *actor) replyAttach(reply chan<- attachOutcome, out attachOutcome) {
	if reply == nil {
		return
	}
	reply <- out
}

// buildConnectInputs projects the contract (and, where wired, the ledger)
// into the primitive shapes the Speaker and Thinker ports take. It runs on
// the owner goroutine specifically so the ledger read stays on the one
// goroutine allowed to touch it — internal/ledger.Ledger is deliberately
// not safe for concurrent use, and the connector runs concurrently with
// this one.
func (a *actor) buildConnectInputs() (ports.SessionCfg, ports.PersonaCtx) {
	cfg := ports.SessionCfg{
		SessionID:    a.id,
		SystemPrompt: a.contract.SystemPrompt,
		VoiceID:      a.contract.TTSVoiceID,
		MayInterrupt: a.contract.VoiceDirectives.MayInterrupt,
	}
	persona := ports.PersonaCtx{SystemPrompt: a.contract.SystemPrompt}
	if a.ledger != nil {
		persona.LedgerSummary = a.ledger.ThinkerSummary()
	}
	return cfg, persona
}

// recordDegradation records one best-effort collaborator's connect failure
// (surfaced later in SessionIngest.Degradations) and emits an event so it
// reaches the session's event log at the moment it happens, not only at
// the end.
func (a *actor) recordDegradation(what string) {
	a.degradations = append(a.degradations, what)
	a.emit("degraded", map[string]any{"what": what})
}

// handleConnected wires in the connector's all-or-nothing result: the
// fatal Speaker session, already open, and whichever non-fatal
// collaborators actually came up. It starts the Speaker event pump — the
// one thing this milestone consumes the connected session for — and drops
// (and flags degraded) any collaborator that failed to connect.
func (a *actor) handleConnected(ctx context.Context, out *connectOutcome) {
	a.speaking = out.Speaker
	a.emit("speaker_connected", nil)
	if out.TranscriberFailed {
		a.transcriber = nil
		a.recordDegradation(degradedASR)
	}
	if out.ThinkerFailed {
		a.thinker = nil
		a.recordDegradation(degradedThinker)
	}
	if out.StallFailed {
		a.stall = nil
		a.recordDegradation(degradedStall)
	}
	go pumpSpeakerEvents(ctx, a.speaking, a.speakerAudio, a.speakerCtrl, &a.drops)
	if a.mediaConn != nil {
		// Started here rather than at attach: until the Speaker is up there
		// is nothing to do with the interviewer's audio, and forwarding it
		// to a nil session would drop it while looking like it worked.
		go pumpMediaConn(ctx, a.mediaConn, a)
	}
}

// handleConnectFailed winds the session down, in character, on a fatal
// connect failure — no Speaker within budget means no interview.
func (a *actor) handleConnectFailed(ctx context.Context, err error) {
	a.emit("connect_failed", map[string]any{"err": err.Error()})
	a.windDown(ctx, "error")
}

// windDown takes the session out in character, then finalizes.
func (a *actor) windDown(_ context.Context, reason string) {
	a.timers.cancelAll()
	a.closeTurnGate()
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
	case timerThinker:
		// The stall clip bought 700 ms and the reasoning model did not
		// answer. The contract's own directive stands in — still the
		// persona behaving correctly, just without the retrieved detail.
		a.useFallback(ctx, "deadline")
	case timerPlayout:
		// A pre-synthesized clip finished. Nothing else will ever say so:
		// these are not vendor responses, so no ResponseDone arrives, and
		// ResponseDone is SPEAKING's only legal exit.
		a.playout.close(a.clock.Now())
		a.closePersonaTurn(false, 0)
		a.transition(StateListening, "clip played out")
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
			a.utterance = ""
		}
		// Classify from the question's first half. A defer has to put a
		// stall clip on the wire inside 50 ms of end-of-turn, and nothing
		// that thinks answers in 50 ms — so the decision is made while the
		// interviewer is still talking.
		a.utterance = p.Text
		if a.gate != nil && a.state == StateListening {
			if v := a.gate.Classify(a.utterance); v.Skill != "" {
				a.pendingVerdict = &pregateVerdict{
					Skill: v.Skill, Defer: v.Defer, Turn: a.turn + 1,
				}
			}
		}
		// The reasoning model is never cold at end-of-turn: it has been
		// reading the question since the first word.
		if a.thinker != nil {
			if err := a.thinker.FeedPartial(ctx, p.Text); err != nil {
				a.logger.Warn("thinker feed failed", "err", err)
			}
		}
		return
	}
	//exhaustive:ignore -- the default below *emits*, so a state added later
	// cannot fall through unobserved; see .golangci.yml for when this
	// suppression is allowed.
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
		a.armClipPlayout(ctx, a.contract.OpeningLine)
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
	default:
		// An interviewer utterance ended in a state that has nothing to do
		// with one — mid-drain after a barge-in, most plausibly. Dropping
		// it is the right behaviour; dropping it silently is not, because
		// a transcript with a missing utterance and no event explaining
		// the gap is unreconstructable after the fact.
		a.emit("utterance_end_ignored", map[string]any{"state": a.state.String()})
	}
}

// armClipPlayout starts the alarm that ends a pre-synthesized clip.
//
// The opening line and the stall clips are audio the engine already holds,
// not vendor responses, so no ResponseDone will arrive to close the turn —
// and ResponseDone is SPEAKING's only legal exit. The alarm is turn-scoped,
// so a barge-in cancels it through the existing cancelTurnScoped and the
// clip does not "finish" after the persona was already interrupted.
func (a *actor) armClipPlayout(ctx context.Context, text string) {
	a.timers.arm(timerPlayout, a.playClip(ctx, text))
}

// playClip sends a pre-synthesized clip to the browser and reports how long it
// will play.
//
// Sent as one frame rather than paced into 20 ms pieces on purpose. The
// transport's send ring is half a second deep and drops oldest, so feeding a
// five-second clip through it frame by frame would shed all but the tail —
// the persona would open with the last half-second of its own greeting. The
// clip is already rendered and the browser buffers it, so there is nothing to
// pace.
func (a *actor) playClip(ctx context.Context, text string) time.Duration {
	clip, ok := a.openingClip()
	if !ok {
		// No clip to play. The turn is still timed so the session moves on:
		// a persona that opens silently is a blemish, one that hangs in
		// SPEAKING forever is a dead interview.
		a.emit("clip_unavailable", map[string]any{"estimated_from": "text"})
		return estimateSpeechDuration(text)
	}
	d, exact := clipPlayTime(clip)
	if !exact {
		a.emit("clip_unmeasurable", map[string]any{"estimated_from": "text"})
		return estimateSpeechDuration(text)
	}

	itemID := fmt.Sprintf("clip-%d", a.turn)
	a.playout.begin(itemID, a.clock.Now())
	a.playout.sent(len(clip.Samples), clip.SampleRateHz)
	if a.mediaConn != nil {
		frame := ports.Frame{
			PCM:          clip.Samples,
			SampleRateHz: clip.SampleRateHz,
			Timestamp:    a.clock.Now(),
		}
		if err := a.mediaConn.SendAudio(ctx, frame); err != nil {
			a.logger.Warn("send opening clip failed", "err", err)
		}
	}
	a.emit("clip_played", map[string]any{"ms": d.Milliseconds(), "item_id": itemID})
	return d
}

// openingClip returns the pre-synthesized opening line, if the bank has one.
func (a *actor) openingClip() (ports.PCM16Audio, bool) {
	if a.stall == nil {
		return ports.PCM16Audio{}, false
	}
	return a.stall.OpeningLine()
}

// clipPlayTime is a clip's true duration, and whether it could be computed.
func clipPlayTime(clip ports.PCM16Audio) (time.Duration, bool) {
	if clip.SampleRateHz <= 0 || len(clip.Samples) == 0 {
		return 0, false
	}
	samples := int64(len(clip.Samples) / bytesPerSamplePCM16)
	return time.Duration(samples * int64(time.Second) / int64(clip.SampleRateHz)), true
}

// speechWordsPerMinute is the rate the text estimate assumes: unhurried
// conversational English, which is what a candidate's opening line is.
const speechWordsPerMinute = 150

// estimateSpeechDuration guesses how long text takes to say aloud, bounded at
// both ends. The floor keeps an empty or one-word line from closing the turn
// in the same tick it opened; the ceiling keeps a pathological contract from
// parking the session in SPEAKING for minutes.
func estimateSpeechDuration(text string) time.Duration {
	const (
		floor   = 750 * time.Millisecond
		ceiling = 30 * time.Second
	)
	words := len(strings.Fields(text))
	d := time.Duration(words) * time.Minute / speechWordsPerMinute
	if d < floor {
		return floor
	}
	if d > ceiling {
		return ceiling
	}
	return d
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
		a.beginDefer(ctx)
		return
	}
	a.beginAnswer(ctx, "pregate confident")
}

// beginDefer enters DEFERRED: a stall clip covers the gap while the reasoning
// model retrieves what this persona is allowed to say about the probed skill.
//
// With no Thinker wired the defer collapses immediately to the contract's own
// fallback directive, which is still persona-correct behaviour — the floor of
// plan §6 layer 3, not a failure.
func (a *actor) beginDefer(ctx context.Context) {
	if !a.transition(StateDeferred, "pregate defer") {
		return
	}
	a.emit("defer_started", map[string]any{"skill": a.probedSkill})
	if a.thinker == nil {
		a.useFallback(ctx, "no thinker")
		return
	}
	a.timers.arm(timerThinker, thinkerDeadline)
	a.openTurnGate()
	go a.awaitNote(ctx, a.thinker.RequestNote(ctx, a.clock.Now().Add(thinkerDeadline)),
		a.turn, a.turnGate)
}

// awaitNote pumps one Thinker note into the actor. A pump, not logic: it
// carries no decisions, which is what keeps every decision on one goroutine.
func (a *actor) awaitNote(
	ctx context.Context, ch <-chan ports.Note, turn int, gate <-chan struct{},
) {
	select {
	case note, ok := <-ch:
		if !ok {
			return
		}
		select {
		case a.notes <- thinkerNote{Note: note, Turn: turn}:
		case <-gate:
		case <-ctx.Done():
		}
	case <-gate:
	case <-ctx.Done():
	}
}

// openTurnGate starts a fresh gate for the in-flight turn, closing any
// previous one so its pump cannot outlive the turn it belonged to.
func (a *actor) openTurnGate() {
	a.closeTurnGate()
	a.turnGate = make(chan struct{})
}

// closeTurnGate voids the in-flight turn's async work.
func (a *actor) closeTurnGate() {
	if a.turnGate != nil {
		close(a.turnGate)
		a.turnGate = nil
	}
}

// handleNote injects the reasoning model's note and lets the speech model
// phrase it.
//
// The note is injected as a *system item*, never spoken verbatim: the speech
// model does the talking so there is no register seam between the stall clip
// and the answer. That is the whole reason the two models are one brain rather
// than a relay.
func (a *actor) handleNote(ctx context.Context, n thinkerNote) {
	if n.Turn != a.turn || a.state != StateDeferred && a.state != StateStalling {
		a.emit("note_discarded", map[string]any{"turn": n.Turn, "state": a.state.String()})
		return
	}
	a.timers.cancel(timerThinker)
	a.closeTurnGate()
	a.assessUnlock(n.Note)
	a.recordSpokenClaims(n.Note)

	text := n.Note.Text
	// Contradiction guard: a note that reverses a live claim is downgraded
	// to a restatement rather than injected. Deterministic, logged, and no
	// model call — the alternative is a persona that argues with itself and
	// a report that cannot tell whose fault that was.
	if a.ledger != nil {
		for _, claim := range n.Note.ClaimsToMake {
			if existing, reason, found := a.ledger.FindContradiction(a.probedSkill, claim); found {
				a.emit("contradiction_averted", map[string]any{
					"claim": claim, "existing": existing.ClaimID, "reason": reason,
				})
				text = "Restate what you already said about " + a.probedSkill +
					": " + existing.Statement + ". Do not contradict it."
				break
			}
		}
		for _, claim := range n.Note.ClaimsToMake {
			a.ledger.Append(a.probedSkill, claim, ports.StanceAsserted,
				ports.OriginThinkerNote, a.turn, a.clock.Now())
		}
	}
	a.injectSystemItem(ctx, text, "thinker_note")
	a.createResponse(ctx, "note injected")
}

// useFallback stands the contract's own directive in for a note that never
// arrived. Persona-correct behaviour, and marked so the grader discounts any
// depth claimed on this turn.
func (a *actor) useFallback(ctx context.Context, reason string) {
	a.closeTurnGate()
	a.fallbackUsed = true
	directive := a.contract.TurnPolicy.OnUnknownQuestion
	if directive == "" {
		directive = a.contract.TurnPolicy.OnPressure
	}
	a.emit("thinker_fallback", map[string]any{"reason": reason, "directive": directive})
	a.injectSystemItem(ctx, directive, "fallback_directive")
	a.createResponse(ctx, "thinker deadline missed")
}

// injectSystemItem adds context to the speech model without producing audio.
func (a *actor) injectSystemItem(ctx context.Context, text, kind string) {
	if a.speaking == nil || text == "" {
		return
	}
	if err := a.speaking.InjectSystemItem(ctx, text); err != nil {
		a.logger.Warn("inject system item failed", "kind", kind, "err", err)
		return
	}
	a.emit("system_item_injected", map[string]any{"kind": kind})
}

// assessUnlock applies the Thinker's judgement about unlock_condition.
//
// **The Thinker assesses; the actor decides** (plan §7). The flip is monotonic
// — depth once earned is never taken back — and both the turn and the evidence
// ride out in the ingest metadata, because "did the interviewer earn the
// unlock, and when" is a headline feedback signal.
func (a *actor) assessUnlock(n ports.Note) {
	if a.unlocked || n.Unlock == nil || !n.Unlock.Met {
		return
	}
	if a.contract.UnlockSpec.Kind != "conditional" {
		// kind == "never" short-circuits: no assessment should have run,
		// and a Thinker claiming otherwise does not get to override the
		// contract.
		a.emit("unlock_ignored", map[string]any{"kind": a.contract.UnlockSpec.Kind})
		return
	}
	a.unlocked = true
	a.unlockTurn = a.turn
	a.emit("unlock_flipped", map[string]any{
		"turn": a.turn, "evidence": n.Unlock.Evidence,
	})
}

// recordSpokenClaims appends what the persona actually said last turn.
func (a *actor) recordSpokenClaims(n ports.Note) {
	if a.ledger == nil {
		return
	}
	for _, claim := range n.ClaimsMade {
		a.ledger.Append(a.probedSkill, claim, ports.StanceAsserted,
			ports.OriginSpoken, a.turn-1, a.clock.Now())
	}
}

// refreshContext re-injects the two standing reminders on their cadences.
//
// Both are best-effort layers (plan §6 layer 4). The ledger summary exists
// because realtime models forget the detail of their own audio history; the
// ceiling re-assertion because prompt adherence drifts under sustained
// pressure, which is exactly when an interviewer is probing hardest.
func (a *actor) refreshContext(ctx context.Context) {
	if a.ledger != nil && a.turn-a.lastLedgerInject >= ledgerRefreshTurns {
		a.lastLedgerInject = a.turn
		a.injectSystemItem(ctx, a.ledger.SpeakerSummary(0), "ledger_summary")
	}
	lowCeiling := a.probedSkill != "" && a.contract.KnowledgeCeiling[a.probedSkill] <= 3
	if a.turn-a.lastCeilingAssert >= ceilingReassertTurns || lowCeiling {
		a.lastCeilingAssert = a.turn
		a.injectSystemItem(ctx, a.ceilingBlock(), "ceiling_reassertion")
	}
}

// ceilingBlock renders the persona's hard limits as a system item.
func (a *actor) ceilingBlock() string {
	if len(a.contract.KnowledgeCeiling) == 0 {
		return ""
	}
	skills := make([]string, 0, len(a.contract.KnowledgeCeiling))
	for skill := range a.contract.KnowledgeCeiling {
		skills = append(skills, skill)
	}
	sort.Strings(skills)
	var b strings.Builder
	b.WriteString("These ceilings are absolute, whatever you are asked:\n")
	for _, skill := range skills {
		b.WriteString("- ")
		b.WriteString(skill)
		b.WriteString(": level ")
		b.WriteString(strconv.Itoa(a.contract.KnowledgeCeiling[skill]))
		b.WriteString("/10\n")
	}
	return b.String()
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
	a.refreshContext(ctx)

	tp := a.contract.TurnPolicy
	depth := tp.DefaultAnswerDepth
	if a.unlocked {
		// The interviewer earned it. Depth up to the ceiling — never past
		// it; unlocking is permission to stop holding back, not permission
		// to know more than the persona knows.
		depth = "thorough"
	}
	err := a.speaking.CreateResponse(ctx, ports.ResponseDirectives{
		MinSentences:    tp.MinSentences,
		MaxSentences:    tp.MaxSentences,
		TargetSentences: tp.TargetSentencesPerAnswer,
		AnswerDepth:     depth,
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

// release stops every alarm and voids any in-flight async work. The actor
// does this on its way out; tests that drive it directly must do the same.
func (a *actor) release() {
	a.timers.cancelAll()
	a.closeTurnGate()
}

// Turns returns the session's turn table. Read after the actor has stopped.
func (a *actor) Turns() []TurnRecord { return a.turns.Records() }

// handleSpeechOnset reacts to locally-detected speech from the interviewer.
//
// Onset is the barge-in trigger. The vendor's own SpeechStarted is not used
// for it: automatic activity detection is disabled, so the vendor has no view
// of the human's microphone at all, and the engine's own detector is the only
// thing that knows the interviewer has started talking. Offset is end-of-turn
// only on the degraded path — see below.
func (a *actor) handleSpeechOnset(ctx context.Context, ev ports.VADEvent) {
	if ev.Started {
		a.emit("speech_onset", map[string]any{"energy_db": ev.EnergyDB})
		if a.state.speakingish() {
			a.bargeIn(ctx)
		}
		return
	}
	a.emit("speech_offset", map[string]any{"energy_db": ev.EnergyDB})
	if a.transcriber != nil {
		// A Transcriber is running and owns end-of-turn. An energy
		// threshold cannot tell a thinking pause from a finished question,
		// and the human here is a manager composing one.
		return
	}
	// The degraded path, which plan §11 row 4 promised and did not have:
	// with no Transcriber, nothing could ever produce the final partial
	// that ends a turn, so the session reached GREETING and stayed there.
	a.emit("degraded_end_of_turn", map[string]any{"source": "energy_vad"})
	a.handlePartial(ctx, ports.Partial{Text: a.utterance, Final: true})
}

// handleMic forwards the interviewer's audio to the Speaker, honouring the
// mic gate when the persona does not allow barge-in.
//
// Even when gated, the frame still reaches the recorder and transcriber
// upstream of here: an ignored interruption attempt is itself feedback data.
func (a *actor) handleMic(ctx context.Context, m micFrame) {
	if a.speaking == nil {
		return
	}
	// The interviewer is present the moment their audio starts arriving.
	// Nothing else in production ever moved the session out of CONNECTING —
	// cmdInterviewerJoined had no producer at all — so GREETING was
	// unreachable and no interview could ever begin.
	if a.state == StateConnecting {
		if a.transition(StateGreeting, "interviewer audio") {
			a.armSessionCap()
		}
	}
	if a.state.speakingish() && !a.contract.TurnPolicy.BargeInAllowed {
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
			// Keyed on ItemID, not ResponseID: ItemID is what the browser
			// echoes back on every playout heartbeat, so tracking anything
			// else means no heartbeat ever matches and heardMs silently
			// degrades to "assume it all played".
			a.playout.begin(e.ItemID, a.clock.Now())
		}
		a.playout.sent(len(e.Frame.PCM), e.Frame.SampleRateHz)
		a.sendToBrowser(ctx, e)
	case ports.InputTranscript:
		// The Speaker's own transcription of the interviewer. Verified live:
		// it still fires with the vendor's automatic voice detection off,
		// which makes it the ASR fallback when the Transcriber is gone. It
		// supplies the text; the energy detector supplies the boundary.
		if e.Text != "" {
			a.utterance += e.Text
		}
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
	default:
		// An event kind this build does not handle. Emitted rather than
		// dropped: ports.SpeakerEvent is an open interface that four
		// adapters implement, and a silently ignored event is how a
		// vendor adding a kind becomes a session that behaves subtly
		// wrongly with nothing in the log to say why.
		a.emit("speaker_event_unhandled", map[string]any{
			"go_type": fmt.Sprintf("%T", ev),
		})
	}
}

// sendToBrowser hands one frame of persona audio to the media connection.
//
// The transport queues and returns — it must, since this runs on the actor's
// own goroutine — so a slow client sheds frames there rather than stalling the
// turn loop here.
func (a *actor) sendToBrowser(ctx context.Context, d ports.AudioDelta) {
	if a.mediaConn == nil {
		return
	}
	if err := a.mediaConn.SendAudio(ctx, d.Frame); err != nil {
		a.logger.Warn("send persona audio failed", "err", err)
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
	if !a.contract.TurnPolicy.BargeInAllowed {
		// The persona does not yield. The attempt is still recorded — an
		// interviewer who tried to interrupt and was talked over is
		// feedback, not noise.
		//
		// No state test here: speakingish() above has already established
		// that persona audio is in flight, and the gate applies to all of
		// it. Testing StateSpeaking as well — which this did — meant a
		// no-barge-in persona still yielded during its own opening line
		// and its own stall clips, the two moments a nervous interviewer
		// is most likely to talk over it.
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
