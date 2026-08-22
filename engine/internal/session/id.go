package session

import (
	"crypto/rand"
	"encoding/hex"
	"fmt"
)

// idBytes is the size of a session id's random payload. 16 bytes (128 bits)
// makes collision within one node's ~50 concurrent sessions (plan §1)
// astronomically unlikely without needing a coordinated counter.
const idBytes = 16

// newSessionID returns a random, URL-safe session identifier.
//
// Uniqueness comes from crypto/rand, not wall-clock time, deliberately:
// internal/session's injected ports.Clock exists to make turn timing
// deterministic under tests, and reusing it for id generation would make
// every FakeClock-driven test produce colliding ids unless the test also
// choreographed clock advances around id generation. Keeping id generation
// independent of Clock avoids that coupling entirely.
func newSessionID() (string, error) {
	var b [idBytes]byte
	if _, err := rand.Read(b[:]); err != nil {
		return "", fmt.Errorf("session: generate id: %w", err)
	}
	return hex.EncodeToString(b[:]), nil
}
