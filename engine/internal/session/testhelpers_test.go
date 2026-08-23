package session

import (
	"io"

	"skillbrew/engine/internal/obs"
)

// newTestEventLog exists so the internal tests can build a log without
// importing obs at every call site.
func newTestEventLog(w io.Writer) *obs.EventLog { return obs.NewEventLog(w) }
