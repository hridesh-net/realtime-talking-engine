package ports

import "context"

// FinalizeInput is everything a Finalizer needs to assemble and hand off
// one session's finished bundle: the recording Recorder produced and the
// ingest payload describing the session it belongs to.
type FinalizeInput struct {
	// Recording is what Recorder.Finalize returned for this session.
	Recording RecordingInfo
	// Ingest is the session's full ingest payload — see SessionIngest.
	Ingest SessionIngest
}

// Finalizer assembles a finished session's bundle (recording plus ingest
// metadata) and hands it off to durable storage and the control plane.
// Implementation: internal/finalize, composing a Store and a
// ContractSource.
type Finalizer interface {
	// Finalize completes the handoff for one session. It is the last step
	// in a session's lifecycle; a failure here degrades the bundle's
	// availability, never the interview that already happened.
	Finalize(ctx context.Context, in FinalizeInput) error
}
