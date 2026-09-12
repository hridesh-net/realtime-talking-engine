package session

import (
	"fmt"
	"strings"
	"time"

	"skillbrew/engine/internal/ports"
)

// The harness context is the actor-owned, bounded transcript used to give a
// future Thinker a faithful view of the live conversation. It deliberately
// lives next to the actor rather than behind a concurrent store: the actor is
// the only writer, so recording transcript events cannot contend with the
// media loop or introduce a second ordering source.
const (
	defaultHarnessCapacity       = 128
	defaultHarnessSnapshotLength = 8
)

type harnessSource string

const (
	harnessSourceHuman   harnessSource = "human"
	harnessSourcePersona harnessSource = "persona"
)

// harnessTranscriptEntry is one currently retained transcript item. Interim
// items are replaced semantically (with a new sequence) as a vendor revises
// them; final items remain until bounded compaction removes them.
type harnessTranscriptEntry struct {
	Sequence  uint64
	Source    harnessSource
	Text      string
	Final     bool
	Timestamp time.Time
	Turn      int
	ItemID    string
}

// harnessTurnSnapshot is the compact, final-only shape the Thinker prompt is
// built from. Human and persona text for the same engine turn are merged into
// one record, so interim ASR revisions never reach the prompt snapshot.
// Sequence is the newest transcript entry that contributed, which is what
// makes the published history version content-derived: it moves only when a
// finalized turn changes, never when an in-flight revision arrives.
type harnessTurnSnapshot struct {
	Turn     int
	Human    string
	Persona  string
	Sequence uint64
}

type harnessKey struct {
	source harnessSource
	id     string
}

// harnessContext is actor-owned and must only be touched by the actor
// goroutine. entries is bounded; snapshot is independently bounded so the
// Thinker context remains useful after transcript compaction.
type harnessContext struct {
	capacity       int
	snapshotLimit  int
	nextSequence   uint64
	entries        []harnessTranscriptEntry
	active         map[harnessKey]uint64
	closed         map[harnessKey]uint64
	finalSnapshots []harnessTurnSnapshot
	version        uint64
}

func newHarnessContext(capacity int) *harnessContext {
	if capacity <= 0 {
		capacity = defaultHarnessCapacity
	}
	return &harnessContext{
		capacity:      capacity,
		snapshotLimit: defaultHarnessSnapshotLength,
		active:        make(map[harnessKey]uint64),
		closed:        make(map[harnessKey]uint64),
	}
}

// recordHuman records a Transcriber partial/final or a Speaker
// InputTranscript. A repeated key is an ASR revision, not a new utterance.
func (h *harnessContext) recordHuman(text string, final bool, itemID string, at time.Time, turn int) bool {
	version := h.version
	if itemID == "" {
		itemID = fmt.Sprintf("turn-%d", turn)
	}
	key := harnessKey{source: harnessSourceHuman, id: itemID}
	if strings.TrimSpace(text) == "" {
		if final {
			h.finalize(key, at, turn)
		}
		return h.version != version
	}
	h.upsert(key, text, final, at, turn)
	return h.version != version
}

// recordPersonaDelta accumulates OutputTranscriptDelta chunks for one
// response. The response becomes final when ResponseDone (or barge-in) closes
// the persona turn.
func (h *harnessContext) recordPersonaDelta(text, responseID string, at time.Time, turn int) bool {
	version := h.version
	if strings.TrimSpace(text) == "" {
		return false
	}
	if responseID == "" {
		responseID = fmt.Sprintf("turn-%d", turn)
	}
	key := harnessKey{source: harnessSourcePersona, id: responseID}
	if sequence, ok := h.active[key]; ok {
		if entry, found := h.entryBySequence(sequence); found {
			h.replace(key, entry.Text+text, false, at, turn)
			return h.version != version
		}
		delete(h.active, key)
	}
	h.upsert(key, text, false, at, turn)
	return h.version != version
}

// recordPersonaFinal is used for pre-synthesized persona speech — the opening
// line and the stall clips — which has no Speaker transcript event of its own.
// An empty id keys the item by turn; a stall clip passes its own id because
// the answer that follows it lands in the same turn.
func (h *harnessContext) recordPersonaFinal(text, id string, at time.Time, turn int) bool {
	version := h.version
	if strings.TrimSpace(text) == "" {
		return false
	}
	if id == "" {
		id = fmt.Sprintf("turn-%d", turn)
	}
	h.upsert(harnessKey{source: harnessSourcePersona, id: id}, text, true, at, turn)
	return h.version != version
}

// finalizePersona closes the active response matching responseID. If a
// vendor's done event omits or changes the response id, the most recent active
// persona item is the safe fallback because the actor serializes responses.
func (h *harnessContext) finalizePersona(responseID string, at time.Time, turn int) {
	key := harnessKey{source: harnessSourcePersona, id: responseID}
	if _, ok := h.active[key]; !ok {
		var found bool
		key, found = h.latestActive(harnessSourcePersona)
		if !found {
			return
		}
	}
	h.finalize(key, at, turn)
}

func (h *harnessContext) upsert(key harnessKey, text string, final bool, at time.Time, turn int) {
	if _, closed := h.closed[key]; closed {
		return
	}
	if _, ok := h.active[key]; ok {
		h.replace(key, text, final, at, turn)
		return
	}
	h.append(harnessTranscriptEntry{
		Sequence:  h.next(),
		Source:    key.source,
		Text:      text,
		Final:     final,
		Timestamp: at,
		Turn:      turn,
		ItemID:    key.id,
	})
	entry := h.entries[len(h.entries)-1]
	if final {
		h.recordSnapshot(entry)
		h.closed[key] = entry.Sequence
		h.pruneClosed()
	} else {
		h.active[key] = entry.Sequence
	}
	h.version++
}

func (h *harnessContext) replace(key harnessKey, text string, final bool, at time.Time, turn int) {
	sequence, ok := h.active[key]
	if !ok {
		h.upsert(key, text, final, at, turn)
		return
	}
	idx, found := h.indexBySequence(sequence)
	if !found {
		delete(h.active, key)
		h.upsert(key, text, final, at, turn)
		return
	}
	// Remove the prior revision before appending the replacement. This keeps
	// entries monotonically ordered even if another source emitted an event in
	// between two ASR revisions.
	h.entries = append(h.entries[:idx], h.entries[idx+1:]...)
	h.rebuildActive()
	h.append(harnessTranscriptEntry{
		Sequence:  h.next(),
		Source:    key.source,
		Text:      text,
		Final:     final,
		Timestamp: at,
		Turn:      turn,
		ItemID:    key.id,
	})
	entry := h.entries[len(h.entries)-1]
	if final {
		h.recordSnapshot(entry)
		h.closed[key] = entry.Sequence
		h.pruneClosed()
	} else {
		h.active[key] = entry.Sequence
	}
	h.version++
}

func (h *harnessContext) finalize(key harnessKey, at time.Time, turn int) {
	sequence, ok := h.active[key]
	if !ok {
		return
	}
	idx, found := h.indexBySequence(sequence)
	if !found {
		delete(h.active, key)
		return
	}
	entry := h.entries[idx]
	if turn == 0 {
		turn = entry.Turn
	}
	h.replace(key, entry.Text, true, at, turn)
	h.closed[key] = h.nextSequence
	h.pruneClosed()
}

func (h *harnessContext) append(entry harnessTranscriptEntry) {
	h.entries = append(h.entries, entry)
	if len(h.entries) > h.capacity {
		h.entries = h.entries[len(h.entries)-h.capacity:]
		h.rebuildActive()
	}
}

func (h *harnessContext) next() uint64 {
	h.nextSequence++
	return h.nextSequence
}

func (h *harnessContext) entryBySequence(sequence uint64) (harnessTranscriptEntry, bool) {
	idx, ok := h.indexBySequence(sequence)
	if !ok {
		return harnessTranscriptEntry{}, false
	}
	return h.entries[idx], true
}

func (h *harnessContext) indexBySequence(sequence uint64) (int, bool) {
	for i := len(h.entries) - 1; i >= 0; i-- {
		if h.entries[i].Sequence == sequence {
			return i, true
		}
	}
	return 0, false
}

func (h *harnessContext) latestActive(source harnessSource) (harnessKey, bool) {
	var (
		latest harnessKey
		found  bool
		seq    uint64
	)
	for key, activeSequence := range h.active {
		if key.source == source && (!found || activeSequence > seq) {
			latest, seq, found = key, activeSequence, true
		}
	}
	return latest, found
}

func (h *harnessContext) rebuildActive() {
	h.active = make(map[harnessKey]uint64)
	for _, entry := range h.entries {
		if !entry.Final {
			h.active[harnessKey{source: entry.Source, id: entry.ItemID}] = entry.Sequence
		}
	}
}

// snapshot returns a defensive, bounded view of the finalized turns *before*
// currentTurn — the conversation history a Thinker reasons over. The current
// turn is deliberately excluded: its question reaches the Thinker live through
// FeedPartial, and the whole point of that path is that the speculation it
// started must survive to end-of-turn. Publishing the current turn here would
// change the version at every defer and throw that speculation away.
func (h *harnessContext) snapshot(currentTurn int) ports.HarnessSnapshot {
	turns := make([]ports.HarnessTurn, 0, len(h.finalSnapshots))
	for _, turn := range h.finalSnapshots {
		if turn.Turn >= currentTurn {
			continue
		}
		turns = append(turns, ports.HarnessTurn{
			Turn:    turn.Turn,
			Human:   turn.Human,
			Persona: turn.Persona,
		})
	}
	return ports.HarnessSnapshot{
		Version:     h.historyVersion(currentTurn),
		CurrentTurn: currentTurn,
		Turns:       turns,
	}
}

// historyVersion identifies the finalized history before currentTurn. Two
// equal versions mean the same finalized turns; the internal revision counter
// (version) is not used here because it also moves on interim revisions.
func (h *harnessContext) historyVersion(currentTurn int) uint64 {
	var version uint64
	for _, turn := range h.finalSnapshots {
		if turn.Turn < currentTurn && turn.Sequence > version {
			version = turn.Sequence
		}
	}
	return version
}

// pruneClosed keeps stale-item protection bounded along with transcript
// storage. The actor's turn and snapshot version guards cover late notes;
// this small tombstone set covers late ASR revisions without growing per
// session forever.
func (h *harnessContext) pruneClosed() {
	limit := h.capacity * 2
	for len(h.closed) > limit {
		var oldest harnessKey
		var sequence uint64
		first := true
		for key, seq := range h.closed {
			if first || seq < sequence {
				oldest, sequence, first = key, seq, false
			}
		}
		delete(h.closed, oldest)
	}
}

func (h *harnessContext) recordSnapshot(entry harnessTranscriptEntry) {
	for i := range h.finalSnapshots {
		if h.finalSnapshots[i].Turn != entry.Turn {
			continue
		}
		switch entry.Source {
		case harnessSourceHuman:
			h.finalSnapshots[i].Human = strings.TrimSpace(entry.Text)
		case harnessSourcePersona:
			// The persona can finalize twice in one turn — a stall clip
			// and then the answer it covered — and both were said, so
			// they join. A human final is a revision and replaces.
			h.finalSnapshots[i].Persona = joinSpoken(h.finalSnapshots[i].Persona, entry.Text)
		}
		if entry.Sequence > h.finalSnapshots[i].Sequence {
			h.finalSnapshots[i].Sequence = entry.Sequence
		}
		return
	}
	snapshot := harnessTurnSnapshot{Turn: entry.Turn, Sequence: entry.Sequence}
	switch entry.Source {
	case harnessSourceHuman:
		snapshot.Human = strings.TrimSpace(entry.Text)
	case harnessSourcePersona:
		snapshot.Persona = strings.TrimSpace(entry.Text)
	}
	h.finalSnapshots = append(h.finalSnapshots, snapshot)
	if len(h.finalSnapshots) > h.snapshotLimit {
		h.finalSnapshots = h.finalSnapshots[len(h.finalSnapshots)-h.snapshotLimit:]
	}
}

// joinSpoken appends one finalized persona item to a turn's persona text.
func joinSpoken(existing, text string) string {
	text = strings.TrimSpace(text)
	if existing == "" {
		return text
	}
	if text == "" {
		return existing
	}
	return existing + " " + text
}

// entriesSnapshot returns a defensive copy for tests and future actor-owned
// prompt builders.
func (h *harnessContext) entriesSnapshot() []harnessTranscriptEntry {
	entries := make([]harnessTranscriptEntry, len(h.entries))
	copy(entries, h.entries)
	return entries
}

// finalTurnSnapshot returns only completed, compacted turn summaries.
func (h *harnessContext) finalTurnSnapshot() []harnessTurnSnapshot {
	snapshot := make([]harnessTurnSnapshot, len(h.finalSnapshots))
	copy(snapshot, h.finalSnapshots)
	return snapshot
}
