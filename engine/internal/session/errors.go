package session

import "errors"

// ErrEmptyCandidateID is returned by Manager.CreateSession when the caller
// supplies an empty candidate id. The HTTP handler maps it to 400 Bad
// Request: a missing candidate id is a client mistake, not an engine
// failure.
var ErrEmptyCandidateID = errors.New("session: candidate_id is required")

// ErrSessionNotFound is returned by Manager.StopSession and Manager.Lookup
// when no live session matches the given id — either it never existed or it
// has already been stopped. The HTTP handler maps it to 404 Not Found.
var ErrSessionNotFound = errors.New("session: not found")

// ErrContractRejected is wrapped around every error contract.Parse returns
// from Manager.CreateSession, regardless of which of contract.Parse's own
// failure modes produced it (malformed JSON, a failed validation, or an
// unsupported major version — only the latter two carry contract's own
// sentinels). A contract the engine cannot run is always a client-supplied-
// persona problem, never an engine failure: the HTTP handler matches this
// sentinel to map every case uniformly to 400 Bad Request rather than 500.
var ErrContractRejected = errors.New("session: contract rejected")

// ErrTransportAlreadyAttached is returned by Manager.AttachTransport when a
// session's transport has already been accepted. The HTTP handler maps it
// to 409 Conflict: a session negotiates media exactly once, and a second
// offer is a client retry racing its own first call, not a new attempt to
// service.
var ErrTransportAlreadyAttached = errors.New("session: transport already attached")

// ErrNoTransportConfigured is returned by Manager.AttachTransport when the
// session was built with no ports.Transport (e.g. the walking-skeleton
// wiring in cmd/engined before the real adapter lands). The HTTP handler
// maps it to 502 Bad Gateway: the caller did nothing wrong, the engine has
// no media adapter to accept the offer with.
var ErrNoTransportConfigured = errors.New("session: no transport configured")

// ErrNoSpeakerConfigured is the fatal connect failure recorded when a
// session has no ports.Speaker wired: no mouth, no interview. The transport
// handshake may still have succeeded — this only ends the session, in
// character, with end_reason "error"; it never surfaces as an HTTP error.
var ErrNoSpeakerConfigured = errors.New("session: no speaker configured")
