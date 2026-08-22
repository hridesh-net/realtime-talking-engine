package config

import (
	"errors"
	"fmt"
	"sort"
	"strings"
)

// ErrRequired is the sentinel behind an Issue for a required key that was
// absent or empty.
var ErrRequired = errors.New("config: required value missing")

// ErrInvalid is the sentinel behind an Issue for a key that was present but
// failed to parse into its target type.
var ErrInvalid = errors.New("config: invalid value")

// Issue is one problem found while loading configuration: a single missing
// or malformed key.
type Issue struct {
	// Key is the environment variable name the issue relates to.
	Key string
	// Err wraps ErrRequired or ErrInvalid; errors.Is(issue, ErrRequired)
	// and errors.Is(issue, ErrInvalid) both work against an *Issue.
	Err error
}

// Error implements the error interface, revive error-strings style
// (lowercase, no trailing punctuation).
func (i *Issue) Error() string {
	return fmt.Sprintf("%s: %s", i.Key, i.Err)
}

// Unwrap enables errors.Is/errors.As to reach the sentinel behind Err.
func (i *Issue) Unwrap() error {
	return i.Err
}

// LoadError aggregates every problem found while loading configuration, so
// a half-configured deployment fails once with the complete list of missing
// or invalid keys, not one key at a time.
type LoadError struct {
	// Issues is never empty when LoadError is returned.
	Issues []*Issue
}

// Error implements the error interface. Keys are sorted so the message is
// deterministic across runs.
func (e *LoadError) Error() string {
	msgs := make([]string, len(e.Issues))
	for i, issue := range e.Issues {
		msgs[i] = issue.Error()
	}
	sort.Strings(msgs)
	return fmt.Sprintf("config: %d issue(s) loading configuration: %s", len(msgs), strings.Join(msgs, "; "))
}

// Is enables errors.Is(err, ErrRequired) or errors.Is(err, ErrInvalid)
// against a *LoadError: it reports true if any aggregated issue matches.
func (e *LoadError) Is(target error) bool {
	for _, issue := range e.Issues {
		if errors.Is(issue, target) {
			return true
		}
	}
	return false
}
