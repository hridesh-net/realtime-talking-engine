package ports

import (
	"context"
	"io"
)

// Store persists session bundle objects (recording, transcripts, event
// log) to durable storage. Implementations: store/s3 (multipart upload,
// retry, local spool-on-failure — an implementation concern, not part of
// this port's contract) and fakes.Store (in-memory).
type Store interface {
	// PutObject writes r to key, replacing any existing object there.
	PutObject(ctx context.Context, key string, r io.Reader) error
}
