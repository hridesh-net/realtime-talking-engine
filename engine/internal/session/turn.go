package session

import (
	"strings"
	"time"
)

// Speaker roles in a turn record.
const (
	speakerHuman   = "human"
	speakerPersona = "persona"
)

// TurnRecord is one turn of the interview as the engine observed it.
//
// The field set is the ingest payload of plan §8.2, not a debug convenience:
// this is what the control plane grades against. `ProbedSkill`, `Deferred` and
// `FallbackUsed` exist so a feedback report can say *the manager probed Redis,
// the persona deferred, and the fallback fired* rather than guessing from the
// transcript alone.
type TurnRecord struct {
	Turn        int    `json:"turn"`
	Speaker     string `json:"speaker"`
	StartMs     int    `json:"start_ms"`
	EndMs       int    `json:"end_ms"`
	Text        string `json:"text"`
	ProbedSkill string `json:"probed_skill,omitempty"`
	Deferred    bool   `json:"deferred,omitempty"`
	// FallbackUsed marks a turn where the Thinker missed its deadline and
	// the contract's own on_unknown_question / on_pressure directive stood
	// in. The grader discounts depth claims on such a turn.
	FallbackUsed bool `json:"fallback_used,omitempty"`
	// Trimmed marks a response cut short by the sentence-bound enforcer.
	Trimmed bool `json:"trimmed,omitempty"`
	// BargedIn marks a persona turn the interviewer interrupted.
	BargedIn bool `json:"barged_in,omitempty"`
	// HeardMs is how much of a barged-in persona turn was actually heard.
	HeardMs int `json:"heard_ms,omitempty"`
}

// turnTable accumulates the session's turn records in order.
//
// Actor-owned; not safe for concurrent use.
type turnTable struct {
	records []TurnRecord
	// open is the turn currently being built, nil between turns.
	open *TurnRecord
	// start is the session's origin on the injected clock, so turn
	// timestamps are relative milliseconds rather than wall clock.
	start time.Time
}

func newTurnTable(start time.Time) *turnTable {
	return &turnTable{start: start}
}

// begin opens a new turn. An already-open turn is closed first, so a missing
// close cannot silently merge two turns into one.
func (t *turnTable) begin(turn int, speaker string, now time.Time) {
	if t.open != nil {
		t.close(now)
	}
	t.open = &TurnRecord{
		Turn:    turn,
		Speaker: speaker,
		StartMs: t.msSince(now),
	}
}

// appendText adds transcript text to the open turn.
func (t *turnTable) appendText(text string) {
	if t.open == nil || text == "" {
		return
	}
	t.open.Text += text
}

// close finalizes the open turn and appends it to the table.
func (t *turnTable) close(now time.Time) {
	if t.open == nil {
		return
	}
	t.open.EndMs = t.msSince(now)
	t.open.Text = strings.TrimSpace(t.open.Text)
	t.records = append(t.records, *t.open)
	t.open = nil
}

// tagLast records the pre-gate's classification on the most recently closed
// turn — the interviewer utterance the verdict was about.
func (t *turnTable) tagLast(skill string, deferred bool) {
	if len(t.records) == 0 {
		return
	}
	last := &t.records[len(t.records)-1]
	if last.Speaker != speakerHuman {
		return
	}
	last.ProbedSkill = skill
	last.Deferred = deferred
}

// Records returns the finished turns.
func (t *turnTable) Records() []TurnRecord { return t.records }

func (t *turnTable) msSince(now time.Time) int {
	d := now.Sub(t.start)
	if d < 0 {
		return 0
	}
	return int(d / time.Millisecond)
}

// sentenceCounter counts completed sentences in a streaming transcript.
//
// The engine enforces `max_sentences` by trimming rather than by asking the
// model nicely: length is one of the few ceiling layers that can actually be
// *guaranteed* (plan §6 layer 5), and a persona that runs long is a persona
// the interviewer never gets to interrupt.
//
// The grace clause matters. Cutting mid-sentence sounds like a dropped call,
// not like a person finishing a thought, so the trim waits until the persona
// has completed its allowance *and started another one* before cancelling.
type sentenceCounter struct {
	completed int
	// pendingText is true when non-terminator text has arrived since the
	// last completed sentence — i.e. a new sentence is under way.
	pendingText bool
}

func (c *sentenceCounter) reset() {
	c.completed = 0
	c.pendingText = false
}

// feed consumes one transcript delta and reports whether the response has
// exceeded its allowance and should be trimmed.
func (c *sentenceCounter) feed(delta string, maxSentences int) bool {
	for _, r := range delta {
		switch r {
		case '.', '!', '?':
			if c.pendingText {
				c.completed++
				c.pendingText = false
			}
		case ' ', '\t', '\n', '\r':
			// Whitespace neither starts nor ends a sentence.
		default:
			c.pendingText = true
		}
	}
	if maxSentences <= 0 {
		return false
	}
	// Allowance spent *and* another sentence begun: the grace clause is
	// over.
	return c.completed >= maxSentences && c.pendingText
}
