package session

import "fmt"

// State is one node of the session state machine (plan §4).
//
// The enum is closed and the legal transitions are a table rather than
// scattered `if` statements, because the expensive bugs in a real-time turn
// loop are the transitions nobody wrote down: audio arriving in DRAINING,
// a stall timer firing after the turn already closed, a response created
// while one is still in flight. A table can be tested exhaustively; a
// scatter of conditionals cannot.
type State int

const (
	// StateConnecting is the entry state: transport up, contract loaded,
	// stall bank synthesized, vendor sessions opening.
	StateConnecting State = iota
	// StateGreeting waits for the interviewer's first utterance to end,
	// then plays the pre-synthesized opening line.
	StateGreeting
	// StateListening means the human is speaking. Partials feed the
	// pre-gate and the Thinker; mic audio goes to the Speaker.
	StateListening
	// StatePreAnswer is end-of-turn with a CONFIDENT pre-gate verdict: the
	// pause timer runs, then the Speaker answers unaided.
	StatePreAnswer
	// StateDeferred is end-of-turn with a DEFER verdict: a stall clip is
	// queued and the Thinker has been asked for a note.
	StateDeferred
	// StateStalling is the stall clip playing while the Thinker thinks.
	StateStalling
	// StateSpeaking is persona audio streaming out with the playout
	// tracker live.
	StateSpeaking
	// StateDraining is a cancelled response: flush buffers, truncate at
	// what was actually heard, cancel every turn timer, close the turn.
	StateDraining
	// StateWindingDown is an in-character wrap on a cap or abandonment.
	StateWindingDown
	// StateFinalizing closes transcripts, finalizes the recording and
	// notifies ingest.
	StateFinalizing
	// StateDone is terminal.
	StateDone
)

// String renders the state as it appears in the event log. These strings are
// part of the log contract the grader reads, so they are stable.
func (s State) String() string {
	switch s {
	case StateConnecting:
		return "CONNECTING"
	case StateGreeting:
		return "GREETING"
	case StateListening:
		return "LISTENING"
	case StatePreAnswer:
		return "PRE_ANSWER"
	case StateDeferred:
		return "DEFERRED"
	case StateStalling:
		return "STALLING"
	case StateSpeaking:
		return "SPEAKING"
	case StateDraining:
		return "DRAINING"
	case StateWindingDown:
		return "WINDING_DOWN"
	case StateFinalizing:
		return "FINALIZING"
	case StateDone:
		return "DONE"
	default:
		return fmt.Sprintf("State(%d)", int(s))
	}
}

// speakingish reports whether persona audio may be in flight in this state,
// and therefore whether a barge-in has anything to interrupt. DEFERRED counts:
// a stall clip is already queued by the time that state is entered.
func (s State) speakingish() bool {
	switch s {
	case StateGreeting, StatePreAnswer, StateDeferred, StateStalling, StateSpeaking:
		return true
	default:
		return false
	}
}

// terminating reports whether the session is on its way out and ordinary turn
// transitions no longer apply.
func (s State) terminating() bool {
	return s == StateWindingDown || s == StateFinalizing || s == StateDone
}

// legalTransitions is the complete turn-loop transition table of plan §4.
//
// It deliberately excludes the two universal edges — barge-in into DRAINING
// from any speaking-ish state, and the wind-down path from anywhere — which
// canTransition applies on top. Encoding those per-source would mean 11 rows
// repeating the same two entries, and a table that repetitive stops being
// read.
var legalTransitions = map[State][]State{
	StateConnecting:  {StateGreeting},
	StateGreeting:    {StateListening, StateSpeaking},
	StateListening:   {StatePreAnswer, StateDeferred},
	StatePreAnswer:   {StateSpeaking},
	StateDeferred:    {StateStalling, StateSpeaking},
	StateStalling:    {StateSpeaking},
	StateSpeaking:    {StateListening},
	StateDraining:    {StateListening},
	StateWindingDown: {StateFinalizing},
	StateFinalizing:  {StateDone},
	StateDone:        nil,
}

// canTransition reports whether from → to is legal.
//
// Three rules, in order: a terminal state goes nowhere; the wind-down path is
// reachable from anywhere that is not already terminating (caps and
// abandonment do not wait for a convenient moment); barge-in reaches DRAINING
// from any state where persona audio may be playing. Everything else must be
// in the table.
func canTransition(from, to State) bool {
	if from == StateDone {
		return false
	}
	if to == StateWindingDown {
		return !from.terminating()
	}
	if to == StateDraining {
		return from.speakingish()
	}
	for _, allowed := range legalTransitions[from] {
		if allowed == to {
			return true
		}
	}
	return false
}
