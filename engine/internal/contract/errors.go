package contract

import (
	"errors"
	"fmt"
)

// ErrUnsupportedVersion is the sentinel behind UnsupportedVersionError, for
// callers that only need errors.Is and not the version details.
var ErrUnsupportedVersion = errors.New("contract: unsupported version")

// UnsupportedVersionError reports a contract_version whose major version
// this engine build does not implement. Reject the contract rather than run
// a persona the engine cannot honour.
type UnsupportedVersionError struct {
	// Version is the raw contract_version string from the payload.
	Version string
	// SupportedMajor is the major version this engine build implements.
	SupportedMajor int
}

// Error implements the error interface.
func (e *UnsupportedVersionError) Error() string {
	return fmt.Sprintf("contract: unsupported contract_version %q, this engine implements major version %d",
		e.Version, e.SupportedMajor)
}

// Is enables errors.Is(err, ErrUnsupportedVersion).
func (e *UnsupportedVersionError) Is(target error) bool {
	return target == ErrUnsupportedVersion
}

// ErrInvalidContract is the sentinel behind ValidationError.
var ErrInvalidContract = errors.New("contract: invalid")

// ValidationError reports a contract that parsed as JSON but violates a
// required field or an invariant the contract itself declares (e.g.
// turn_policy.target_sentences_per_answer within [min_sentences,
// max_sentences]).
type ValidationError struct {
	// Field is the JSON field path that failed validation.
	Field string
	// Reason describes the violation in a lowercase, non-punctuated phrase
	// (revive error-strings style).
	Reason string
}

// Error implements the error interface.
func (e *ValidationError) Error() string {
	return fmt.Sprintf("contract: invalid %s: %s", e.Field, e.Reason)
}

// Is enables errors.Is(err, ErrInvalidContract).
func (e *ValidationError) Is(target error) bool {
	return target == ErrInvalidContract
}
