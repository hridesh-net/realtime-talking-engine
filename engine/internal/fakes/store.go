package fakes

import (
	"context"
	"fmt"
	"io"
	"sync"

	"skillbrew/engine/internal/ports"
)

// Store is an in-memory ports.Store. It replaces store/s3 for offline
// tests: PutObject copies r's full contents into a map keyed by key, with
// no network, no multipart, no spool.
//
// Safe for concurrent use.
type Store struct {
	mu      sync.Mutex
	objects map[string][]byte
}

// NewStore returns an empty in-memory Store.
func NewStore() *Store {
	return &Store{objects: make(map[string][]byte)}
}

// PutObject implements ports.Store, replacing any existing object at key.
func (s *Store) PutObject(ctx context.Context, key string, r io.Reader) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	data, err := io.ReadAll(r)
	if err != nil {
		return fmt.Errorf("fakes: read object %q: %w", key, err)
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	s.objects[key] = data
	return nil
}

// Get returns the bytes last written to key, and whether key has ever been
// written.
func (s *Store) Get(key string) ([]byte, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	data, ok := s.objects[key]
	if !ok {
		return nil, false
	}
	out := make([]byte, len(data))
	copy(out, data)
	return out, true
}

// Keys returns every key ever written to, in no particular order.
func (s *Store) Keys() []string {
	s.mu.Lock()
	defer s.mu.Unlock()
	out := make([]string, 0, len(s.objects))
	for k := range s.objects {
		out = append(out, k)
	}
	return out
}

var _ ports.Store = (*Store)(nil)
