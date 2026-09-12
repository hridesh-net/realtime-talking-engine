package controlplane

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
)

// spool is the on-disk queue of ingest payloads the control plane could
// not take: one file per session, written atomically, drained on the next
// start. The file name is the session id when that is filesystem-safe and
// a hash of it otherwise; the session id the drain posts to comes from the
// payload, never from the name.
type spool struct {
	dir string
}

var safeName = regexp.MustCompile(`^[A-Za-z0-9_-]{1,120}$`)

func newSpool(dir string) *spool {
	return &spool{dir: dir}
}

type spooled struct {
	name      string
	sessionID string
	payload   []byte
}

func (s *spool) put(sessionID string, payload []byte) error {
	if err := os.MkdirAll(s.dir, 0o700); err != nil {
		return fmt.Errorf("spool: create %s: %w", s.dir, err)
	}
	final := filepath.Join(s.dir, fileName(sessionID)+".json")
	tmp, err := os.CreateTemp(s.dir, ".ingest-*.tmp")
	if err != nil {
		return fmt.Errorf("spool: create temp file: %w", err)
	}
	if _, err := tmp.Write(payload); err != nil {
		_ = tmp.Close()
		_ = os.Remove(tmp.Name())
		return fmt.Errorf("spool: write: %w", err)
	}
	if err := tmp.Close(); err != nil {
		_ = os.Remove(tmp.Name())
		return fmt.Errorf("spool: close: %w", err)
	}
	if err := os.Rename(tmp.Name(), final); err != nil {
		_ = os.Remove(tmp.Name())
		return fmt.Errorf("spool: rename into place: %w", err)
	}
	return nil
}

func (s *spool) list() ([]spooled, error) {
	entries, err := os.ReadDir(s.dir)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, nil
		}
		return nil, fmt.Errorf("spool: read %s: %w", s.dir, err)
	}
	var out []spooled
	for _, e := range entries {
		if e.IsDir() || !strings.HasSuffix(e.Name(), ".json") {
			continue
		}
		payload, err := os.ReadFile(filepath.Join(s.dir, e.Name()))
		if err != nil {
			return nil, fmt.Errorf("spool: read %s: %w", e.Name(), err)
		}
		id, err := sessionIDOf(payload)
		if err != nil {
			// Not ours, or corrupt. Leave it for a human; do not post it.
			continue
		}
		out = append(out, spooled{name: e.Name(), sessionID: id, payload: payload})
	}
	sort.Slice(out, func(i, j int) bool { return out[i].name < out[j].name })
	return out, nil
}

func (s *spool) remove(name string) {
	_ = os.Remove(filepath.Join(s.dir, name))
}

func fileName(sessionID string) string {
	if safeName.MatchString(sessionID) {
		return sessionID
	}
	sum := sha256.Sum256([]byte(sessionID))
	return "id-" + hex.EncodeToString(sum[:16])
}
