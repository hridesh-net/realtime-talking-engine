package fakes

import (
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"sync"

	"skillbrew/engine/internal/ports"
)

// ContractSource is a static ports.ContractSource. FetchContract serves the
// same pre-loaded payload to every call regardless of candidateID, and
// NotifyIngest records every call for test assertions instead of talking to
// a control plane.
//
// Safe for concurrent use.
type ContractSource struct {
	mu         sync.Mutex
	contract   []byte
	fetchErr   error
	notifyErr  error
	fetchedIDs []string
	ingests    []ports.SessionIngest
}

// NewContractSource returns a ContractSource that serves contractJSON
// verbatim to every FetchContract call. contractJSON is copied.
func NewContractSource(contractJSON []byte) *ContractSource {
	cp := make([]byte, len(contractJSON))
	copy(cp, contractJSON)
	return &ContractSource{contract: cp}
}

var (
	sampleContractOnce sync.Once
	sampleContractData []byte
	sampleContractErr  error
)

// NewSampleContractSource returns a ContractSource serving the checked-in
// fixture at internal/contract/testdata/engine_contract_sample.json — the
// sample contract used across engine tests. The file is located relative
// to this source file's own path (via runtime.Caller), not the caller's
// working directory, so it resolves correctly regardless of which package's
// test imports fakes.
func NewSampleContractSource() (*ContractSource, error) {
	sampleContractOnce.Do(func() {
		_, thisFile, _, ok := runtime.Caller(0)
		if !ok {
			sampleContractErr = errors.New("fakes: resolve sample contract path: runtime.Caller failed")
			return
		}
		path := filepath.Join(filepath.Dir(thisFile), "..", "contract", "testdata", "engine_contract_sample.json")
		// #nosec G304 -- path is derived from this source file's own
		// on-disk location, not from external or caller input.
		data, err := os.ReadFile(path)
		if err != nil {
			sampleContractErr = fmt.Errorf("fakes: read sample contract: %w", err)
			return
		}
		sampleContractData = data
	})
	if sampleContractErr != nil {
		return nil, sampleContractErr
	}
	return NewContractSource(sampleContractData), nil
}

// FetchContract implements ports.ContractSource, recording candidateID and
// returning the pre-loaded payload (or the error set by SetFetchError).
func (c *ContractSource) FetchContract(ctx context.Context, candidateID string) ([]byte, error) {
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	c.fetchedIDs = append(c.fetchedIDs, candidateID)
	if c.fetchErr != nil {
		return nil, c.fetchErr
	}
	out := make([]byte, len(c.contract))
	copy(out, c.contract)
	return out, nil
}

// NotifyIngest implements ports.ContractSource, recording ingest (or
// returning the error set by SetNotifyError).
func (c *ContractSource) NotifyIngest(ctx context.Context, ingest ports.SessionIngest) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	c.ingests = append(c.ingests, ingest)
	return c.notifyErr
}

// SetFetchError makes every subsequent FetchContract call return err. The
// call is still recorded. Pass nil to clear it.
func (c *ContractSource) SetFetchError(err error) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.fetchErr = err
}

// SetNotifyError makes every subsequent NotifyIngest call return err after
// still recording the ingest — matching the port's note that the engine may
// retry a failed, idempotent NotifyIngest. Pass nil to clear it.
func (c *ContractSource) SetNotifyError(err error) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.notifyErr = err
}

// FetchedCandidateIDs returns every candidateID passed to FetchContract, in
// call order.
func (c *ContractSource) FetchedCandidateIDs() []string {
	c.mu.Lock()
	defer c.mu.Unlock()
	out := make([]string, len(c.fetchedIDs))
	copy(out, c.fetchedIDs)
	return out
}

// Ingests returns every SessionIngest passed to NotifyIngest, in call
// order.
func (c *ContractSource) Ingests() []ports.SessionIngest {
	c.mu.Lock()
	defer c.mu.Unlock()
	out := make([]ports.SessionIngest, len(c.ingests))
	copy(out, c.ingests)
	return out
}

var _ ports.ContractSource = (*ContractSource)(nil)
