package session

import (
	"context"
	"log/slog"

	"skillbrew/engine/internal/contract"
	"skillbrew/engine/internal/ports"
)

// controlBufferSize sizes the stub actor's control channel. Plan §4 specifies
// the control queue as unbounded/never-drop; the stub defines no commands yet
// that could fill it, so a generous buffer stands in. Phase 1's backpressure
// task (§14 task 14) revisits this if real command traffic needs a true
// unbounded queue.
const controlBufferSize = 64

// command is one control-plane instruction delivered to a session actor's
// owner goroutine. Phase 1 (plan §4, §14 task 9) extends this with the real
// command set — turn signals, config updates, barge-in triggers. The stub
// actor only needs to receive control traffic and shut down cleanly, so the
// type carries no payload yet; it exists now so the channel's shape does not
// change under Phase 1.
type command struct{}

// actor is the per-session owner goroutine of plan §4: exactly one goroutine
// holds all mutable session state, so nothing here needs a mutex — every
// field is touched only from inside run. Everything else communicates with
// it by sending on control.
//
// This stub does not yet hold the state enum, turn record, claims ledger,
// timers, or playout tracker plan §4 lists — Phase 1 adds those on top of
// this shape. What this stub gets right, because Phase 1 builds directly on
// it, is the goroutine's lifecycle: it starts clean, drains queued control
// traffic before exiting, and exits the instant ctx is cancelled, with no
// leaked goroutine.
type actor struct {
	id       string
	contract *contract.EngineContract
	clock    ports.Clock
	logger   *slog.Logger

	control chan command
}

// newActor constructs a session actor. It does not start the owner
// goroutine — call run in its own goroutine to do that.
func newActor(id string, c *contract.EngineContract, clock ports.Clock, logger *slog.Logger) *actor {
	return &actor{
		id:       id,
		contract: c,
		clock:    clock,
		logger:   logger,
		control:  make(chan command, controlBufferSize),
	}
}

// run is the actor's owner goroutine: the only goroutine that ever touches
// actor's fields after construction. It returns the instant ctx is
// cancelled, closing done on its way out so callers (Manager.StopSession,
// Manager.Shutdown) can block until this goroutine has fully exited — the
// synchronization the "zero goroutines after stop" guarantee depends on.
//
// The loop is plan §4's nested select: a non-blocking drain of control
// runs first on every iteration, so any control traffic already queued gets
// processed before cancellation is honoured — "shutdown drains rather than
// abandons" (plan §11) rather than abandoning queued work mid-flight. Only
// once control is empty does the loop block, waiting on ctx.Done() and
// control together. Timer and media channels join this select in Phase 1;
// today ctx.Done() is the only real exit path, which is exactly this task's
// scope.
func (a *actor) run(ctx context.Context, done chan<- struct{}) {
	defer close(done)
	a.logger.Info("session actor started")
	defer a.logger.Info("session actor stopped")

	for {
		select {
		case cmd, ok := <-a.control:
			if !ok {
				return
			}
			a.handle(cmd)
			continue
		default:
		}

		select {
		case <-ctx.Done():
			a.logger.Info("session actor stopping", "reason", ctx.Err())
			return
		case cmd, ok := <-a.control:
			if !ok {
				return
			}
			a.handle(cmd)
		}
	}
}

// handle processes one control command. The stub has no commands to act on;
// Phase 1 (plan §4, §14 task 9) fills this in alongside the real command set
// and the state machine it drives.
func (a *actor) handle(command) {
}
