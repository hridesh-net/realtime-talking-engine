package controlplane

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"net/url"
	"strings"
	"time"

	"skillbrew/engine/internal/ports"
)

const (
	contractPathFmt = "/api/v1/candidates/%s/engine-contract"
	ingestPathFmt   = "/api/v1/sessions/%s/ingest"

	// maxContractBytes bounds a contract body. A compiled contract is tens
	// of kilobytes; a megabyte is a misrouted response, not a persona.
	maxContractBytes = 4 << 20
	maxErrorBytes    = 2048
	defaultTimeout   = 15 * time.Second
)

// ErrIngestSpooled reports that the control plane could not be reached and
// the ingest payload was written to the spool for a later DrainSpool. The
// session's outcome is not lost; it is not yet delivered.
var ErrIngestSpooled = errors.New("controlplane: ingest spooled for later delivery")

// defaultBackoff is the wait before each retry of a failed ingest report:
// three attempts in about three seconds, which covers a control-plane
// restart without holding the session's finalization open for long.
var defaultBackoff = []time.Duration{500 * time.Millisecond, 2 * time.Second}

// Client is the HTTP ContractSource. Safe for concurrent use.
type Client struct {
	baseURL *url.URL
	secret  string
	http    *http.Client
	logger  *slog.Logger
	backoff []time.Duration
	spool   *spool
}

var _ ports.ContractSource = (*Client)(nil)

// Option configures a Client.
type Option func(*Client)

// WithHTTPClient injects the HTTP client, for tests and for callers that
// need their own transport settings.
func WithHTTPClient(c *http.Client) Option {
	return func(cl *Client) { cl.http = c }
}

// WithBackoff sets the waits between ingest attempts. No waits means a
// single attempt.
func WithBackoff(waits ...time.Duration) Option {
	return func(cl *Client) { cl.backoff = append([]time.Duration(nil), waits...) }
}

// WithSpoolDir enables the on-disk spool for ingest payloads the control
// plane could not take. The directory is created on first use.
func WithSpoolDir(dir string) Option {
	return func(cl *Client) { cl.spool = newSpool(dir) }
}

// New builds a client for the control plane at baseURL, authenticating
// every call with the shared secret as a bearer token.
func New(baseURL, secret string, logger *slog.Logger, opts ...Option) (*Client, error) {
	u, err := url.Parse(strings.TrimRight(baseURL, "/"))
	if err != nil || u.Scheme == "" || u.Host == "" {
		return nil, fmt.Errorf("controlplane: base URL %q is not an absolute http(s) URL", baseURL)
	}
	if secret == "" {
		return nil, errors.New("controlplane: shared secret is empty")
	}
	if logger == nil {
		logger = slog.Default()
	}
	c := &Client{
		baseURL: u,
		secret:  secret,
		http:    &http.Client{Timeout: defaultTimeout},
		logger:  logger,
		backoff: defaultBackoff,
	}
	for _, opt := range opts {
		opt(c)
	}
	return c, nil
}

// FetchContract implements ports.ContractSource. A 404 is reported as
// ports.ErrContractNotFound so the session layer can answer the caller with
// the same status rather than a gateway error; nothing here is retried,
// because session creation is interactive and a slow failure is worse than
// a fast one.
func (c *Client) FetchContract(ctx context.Context, candidateID string) ([]byte, error) {
	if candidateID == "" {
		return nil, errors.New("controlplane: empty candidate id")
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet,
		c.endpoint(fmt.Sprintf(contractPathFmt, url.PathEscape(candidateID))), nil)
	if err != nil {
		return nil, fmt.Errorf("controlplane: build contract request: %w", err)
	}
	c.authorize(req)
	req.Header.Set("Accept", "application/json")

	resp, err := c.http.Do(req)
	if err != nil {
		return nil, fmt.Errorf("controlplane: fetch contract for %q: %w", candidateID, err)
	}
	defer func() { _ = resp.Body.Close() }()

	switch resp.StatusCode {
	case http.StatusOK:
		body, err := io.ReadAll(io.LimitReader(resp.Body, maxContractBytes+1))
		if err != nil {
			return nil, fmt.Errorf("controlplane: read contract for %q: %w", candidateID, err)
		}
		if len(body) > maxContractBytes {
			return nil, fmt.Errorf("controlplane: contract for %q exceeds %d bytes", candidateID, maxContractBytes)
		}
		return body, nil
	case http.StatusNotFound:
		return nil, fmt.Errorf("controlplane: candidate %q: %w", candidateID, ports.ErrContractNotFound)
	default:
		return nil, fmt.Errorf("controlplane: fetch contract for %q: %s", candidateID, describe(resp))
	}
}

// NotifyIngest implements ports.ContractSource. Idempotent on the session
// id, which rides as the Idempotency-Key header as well as in the body; a
// 409 therefore means "already have it" and counts as delivered.
func (c *Client) NotifyIngest(ctx context.Context, ingest ports.SessionIngest) error {
	if ingest.SessionID == "" {
		return errors.New("controlplane: ingest has no session id")
	}
	payload, err := json.Marshal(toWire(ingest))
	if err != nil {
		return fmt.Errorf("controlplane: encode ingest for %q: %w", ingest.SessionID, err)
	}

	var last error
	attempts := len(c.backoff) + 1
	for attempt := 0; attempt < attempts; attempt++ {
		last = c.postIngest(ctx, ingest.SessionID, payload)
		if last == nil {
			return nil
		}
		var rejected *rejectedError
		if errors.As(last, &rejected) {
			return last
		}
		if attempt == attempts-1 {
			break
		}
		c.logger.Warn("controlplane: ingest attempt failed; retrying",
			"session_id", ingest.SessionID, "attempt", attempt+1, "err", last)
		if err := wait(ctx, c.backoff[attempt]); err != nil {
			last = err
			break
		}
	}

	if c.spool == nil {
		return last
	}
	if err := c.spool.put(ingest.SessionID, payload); err != nil {
		return fmt.Errorf("controlplane: ingest for %q undelivered (%w) and not spooled: %w", ingest.SessionID, last, err)
	}
	c.logger.Warn("controlplane: ingest spooled", "session_id", ingest.SessionID, "err", last)
	return fmt.Errorf("controlplane: ingest for %q: %w: %w", ingest.SessionID, ErrIngestSpooled, last)
}

// DrainSpool re-sends every spooled ingest payload once, deleting the ones
// the control plane accepted or rejected outright and keeping the rest for
// the next drain. It reports how many were delivered and the first delivery
// error, if any.
func (c *Client) DrainSpool(ctx context.Context) (int, error) {
	if c.spool == nil {
		return 0, nil
	}
	entries, err := c.spool.list()
	if err != nil {
		return 0, err
	}
	delivered := 0
	var first error
	for _, e := range entries {
		if err := ctx.Err(); err != nil {
			return delivered, err
		}
		err := c.postIngest(ctx, e.sessionID, e.payload)
		var rejected *rejectedError
		switch {
		case err == nil:
			delivered++
			c.spool.remove(e.name)
		case errors.As(err, &rejected):
			// It will never be accepted; keeping it would retry forever.
			c.logger.Error("controlplane: spooled ingest rejected; dropping", "session_id", e.sessionID, "err", err)
			c.spool.remove(e.name)
			if first == nil {
				first = err
			}
		default:
			if first == nil {
				first = err
			}
		}
	}
	return delivered, first
}

// rejectedError is a definitive refusal: a 4xx that is neither a conflict
// (already ingested) nor a rate limit. Retrying it cannot help.
type rejectedError struct {
	status int
	body   string
}

func (e *rejectedError) Error() string {
	return fmt.Sprintf("control plane rejected the ingest: HTTP %d: %s", e.status, e.body)
}

func (c *Client) postIngest(ctx context.Context, sessionID string, payload []byte) error {
	req, err := http.NewRequestWithContext(ctx, http.MethodPost,
		c.endpoint(fmt.Sprintf(ingestPathFmt, url.PathEscape(sessionID))), bytes.NewReader(payload))
	if err != nil {
		return fmt.Errorf("build ingest request: %w", err)
	}
	c.authorize(req)
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Idempotency-Key", sessionID)

	resp, err := c.http.Do(req)
	if err != nil {
		return fmt.Errorf("post ingest: %w", err)
	}
	defer func() { _ = resp.Body.Close() }()
	switch {
	case resp.StatusCode == http.StatusOK, resp.StatusCode == http.StatusCreated,
		resp.StatusCode == http.StatusConflict:
		_, _ = io.Copy(io.Discard, resp.Body)
		return nil
	case resp.StatusCode == http.StatusTooManyRequests, resp.StatusCode >= 500:
		return errors.New(describe(resp))
	default:
		body, _ := io.ReadAll(io.LimitReader(resp.Body, maxErrorBytes))
		return &rejectedError{status: resp.StatusCode, body: strings.TrimSpace(string(body))}
	}
}

// wait sleeps for d unless ctx ends first.
func wait(ctx context.Context, d time.Duration) error {
	timer := time.NewTimer(d)
	defer timer.Stop()
	select {
	case <-timer.C:
		return nil
	case <-ctx.Done():
		return ctx.Err()
	}
}

func (c *Client) endpoint(path string) string {
	return c.baseURL.String() + path
}

func (c *Client) authorize(req *http.Request) {
	req.Header.Set("Authorization", "Bearer "+c.secret)
}

// describe renders a non-success response for an error message: the status
// and a bounded slice of the body, since the control plane's error envelope
// says what was wrong in its first line.
func describe(resp *http.Response) string {
	body, _ := io.ReadAll(io.LimitReader(resp.Body, maxErrorBytes))
	text := strings.TrimSpace(string(body))
	if text == "" {
		return fmt.Sprintf("HTTP %d", resp.StatusCode)
	}
	return fmt.Sprintf("HTTP %d: %s", resp.StatusCode, text)
}
