// Package obs provides structured logging (slog), per-hop latency metrics,
// and the cost meter.
package obs

import (
	"encoding/json"
	"io"
	"sort"
	"sync"
	"time"
)

// Event is one line of a session's JSONL event log.
//
// The event log is not debug output. It is the grader's record of what the
// engine decided and why: which skill was probed, whether the turn deferred,
// whether a ceiling was breached, when the unlock flipped. A feedback report
// that cannot point at the moment it is describing is not defensible, so
// every transition and decision emits one of these.
//
// Fields are deliberately flat and primitive. This is read by Python, by a
// human debugging a bad session, and by tests comparing against golden files.
type Event struct {
	// Seq orders events within a session. Monotonic from 1, assigned by the
	// emitter, so a reader never has to disambiguate two events sharing a
	// timestamp.
	Seq int `json:"seq"`
	// TS is the session clock, not wall time — it comes from the injected
	// Clock so a FakeClock test produces byte-identical logs.
	TS time.Time `json:"ts"`
	// Type is the event name, e.g. "state_transition", "barge_in".
	Type string `json:"type"`
	// Turn is the turn this event belongs to, 0 before the first turn.
	Turn int `json:"turn"`
	// Fields carries the event's payload. Marshalled with sorted keys so
	// golden-file comparison is stable.
	Fields map[string]any `json:"fields,omitempty"`
}

// EventLog writes session events as JSONL.
//
// Safe for concurrent use: the actor is the main emitter, but the recorder
// and the Judge's verdict pump write here too, and they are not on the
// actor's goroutine.
type EventLog struct {
	mu  sync.Mutex
	w   io.Writer
	enc *json.Encoder
	seq int
}

// NewEventLog returns an EventLog writing JSONL to w.
func NewEventLog(w io.Writer) *EventLog {
	enc := json.NewEncoder(w)
	return &EventLog{w: w, enc: enc}
}

// Emit writes one event. A write failure is dropped rather than returned:
// losing the log must never take down a live interview, and every caller is
// on a path where there is nothing useful to do with the error anyway.
func (l *EventLog) Emit(ts time.Time, typ string, turn int, fields map[string]any) {
	if l == nil {
		return
	}
	l.mu.Lock()
	defer l.mu.Unlock()
	l.seq++
	_ = l.enc.Encode(Event{
		Seq:    l.seq,
		TS:     ts.UTC(),
		Type:   typ,
		Turn:   turn,
		Fields: sortedFields(fields),
	})
}

// Count returns how many events have been emitted. Tests assert on it; the
// runtime does not.
func (l *EventLog) Count() int {
	l.mu.Lock()
	defer l.mu.Unlock()
	return l.seq
}

// sortedFields returns fields with keys in a stable order.
//
// encoding/json already sorts map keys, so this exists for the nil/empty
// case: an empty map and a nil map marshal differently under omitempty, and
// golden files should not depend on which one a caller happened to pass.
func sortedFields(f map[string]any) map[string]any {
	if len(f) == 0 {
		return nil
	}
	keys := make([]string, 0, len(f))
	for k := range f {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	out := make(map[string]any, len(f))
	for _, k := range keys {
		out[k] = f[k]
	}
	return out
}
