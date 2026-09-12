// Package controlplane implements the ContractSource port over the Python
// control plane's HTTP API: it fetches a candidate's engine contract before a
// session opens and reports the finished session's ingest payload afterwards.
//
// The ingest report is the engine's single write-back and the control plane
// treats it as idempotent on session id, so the client retries server-side
// and network failures with backoff and, when the control plane stays down,
// spools the payload to disk for a later drain. A payload the control plane
// rejects outright (4xx other than a conflict or a rate limit) is never
// retried: it will not succeed on the second attempt either, and the error
// carries the status so the log says what was wrong.
package controlplane
