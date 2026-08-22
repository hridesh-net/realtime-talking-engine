---
type: Module
title: control_plane/repository.py
description: The SQLite adapter implementing every storage port — inserts, upserts, and JSON round trips.
resource: /control_plane/repository.py
tags: [repository, sqlite, storage, adapter]
generated:
  by: claude-opus-5/okf-curator
  at: "2026-08-21T19:17:54Z"
verified:
  - by: claude-opus-5/okf-curator
    at: "2026-08-22T17:05:00Z"
  - by: kimi-code/okf-curator
    at: "2026-08-22T21:10:00Z"
status: stable
sources:
  - resource: /control_plane/repository.py
  - resource: /control_plane/database.py
---
# control_plane/repository.py

465 lines. One class, `InterviewRepository`, satisfying `InterviewStore`,
`ExpectationStore`, `CandidateStore`, and `SessionStore` structurally — it
imports none of them.

# Schema

```python
def _utcnow() -> str          # datetime.now(UTC).isoformat()
def _new_id() -> str          # str(uuid.uuid4())
def _parse_ts(value: str) -> datetime   # the "Z" -> "+00:00" fix-up, one place

class InterviewRepository:
    def __init__(self, conn: sqlite3.Connection)
    def create(self, req) -> InterviewResponse          # L36
    def get(self, interview_id) -> InterviewResponse | None
    def list(self, status=None) -> list[InterviewResponse]
    def _row_to_response(self, row) -> InterviewResponse    # L122
    def save_expectation(self, expectation, model_used) -> None   # upsert
    def get_expectation(self, interview_id) -> InterviewExpectation | None
    def save_candidate(self, candidate, model_used) -> None       # upsert
    def list_candidates(self, interview_id) -> list[VirtualCandidate]
    def get_candidate(self, candidate_id) -> VirtualCandidate | None
    def get_candidate_by_archetype(self, interview_id, archetype) -> VirtualCandidate | None
    def delete_candidate(self, candidate_id) -> bool
    def create_session(self, *, interview_id, candidate_id, persona_key,
                       planned_minutes, opening_line, modality="text") -> SessionResponse
    def get_session(self, session_id) -> SessionResponse | None
    def append_turn(self, session_id, speaker, text) -> Turn
    def end_session(self, session_id, status="completed") -> SessionResponse | None
```

`import builtins` at the top exists solely so the `list` **method** can annotate
a return type of `builtins.list[...]` without shadowing.

## Writes

* **`create`** — generates the uuid, serializes `skills_required`/`config`/`metadata` to JSON, and for `mode == "training_interviewer"` also generates the [legacy persona](/concepts/subsystems/control-plane.md) and writes an `ai_personas` row in the same transaction. The M1 configuration fields ride along: `location`/`department`/`manager_level` as plain text, `language`/`proctoring` as CHECK-constrained enums, `clarity_facts` and `report_sections` as JSON columns. Then re-reads via `get()` and raises if it vanished.
* **`save_expectation`** — `ON CONFLICT(interview_id) DO UPDATE`; regenerating replaces.
* **`save_candidate`** — `ON CONFLICT(interview_id, archetype) DO UPDATE`, refreshing `candidate_id` and `updated_at` but leaving `created_at` at the first cast.

Both upserts persist `model_dump_json(exclude={"raw_model_output"})`, so the raw
draft never reaches disk.

## Sessions

* **`create_session`** — writes the session row, and for `modality == "text"` **also turn 0** (the persona's opening line, `elapsed_ms = 0`) in the same transaction, then re-reads. A text session whose transcript did not open with what the persona said would misreport time-to-first-question. A **voice** session skips that insert: the persona says the line aloud and the browser reports it back, so writing it here too would duplicate turn 0. This branch is the one non-obvious thing in the method — `test_a_voice_session_does_not_prewrite_the_opening_line` pins it.
* **`append_turn`** — reads `started_at`, stamps `at = now`, computes `elapsed_ms` (clamped at 0), takes the next index as `COALESCE(MAX(idx) + 1, 0)`, inserts, and returns the built `Turn`. Raises `KeyError` for an unknown session; the handler has already 404'd by then, so this is a guard, not a path.
* **`end_session`** — `UPDATE ... WHERE id = ? AND status = 'live'`. Re-ending a completed session updates nothing and returns the stored record unchanged, so `ended_at` never moves; an unknown id returns `None`.
* **`get_session`** — joins the persona's `name` for display, falling back to `"(deleted persona)"` rather than failing, because a transcript outlives the persona that produced it.

## Reads

Candidates and expectations are rehydrated from the **JSON column alone** —
`VirtualCandidate.model_validate_json(row["persona_json"])`. The indexed columns
(`verdict`, `archetype`, fingerprints) exist for querying and inspection, not for
reconstruction, so they can in principle drift from the document. `get_expectation`
additionally forces `raw_model_output = None` before validating.

`_row_to_response` handles the `"Z"` → `"+00:00"` timestamp fix-up and computes
`start_url` on the fly. Two M1 details live here: `clarity_facts` is rehydrated
into `ClarityFact` models from the JSON column, and `report_sections` is read as
`{**REPORT_SECTIONS, **stored}` — the code's defaults fill any key the row
lacks, so a section added to the code later appears (at its default) on
interviews created before it existed.

## Gotchas

* **Foreign keys do not cascade.** `PRAGMA foreign_keys = ON` is never issued, so deleting an interview orphans its personas and expectation. This is a `database.py`-level fix.
* `with self.conn:` gives transaction-per-statement-group semantics, not a connection context manager — the connection is never closed here (`main.py` closes the startup one).
* Every write re-serializes the whole persona document; a large training set is fine at this scale but this is not a partial-update design.
* `create` writes `status='scheduled'` as a SQL literal; nothing ever transitions it.
* `tests/test_session.py` exercises the session methods directly against `:memory:`. The interview, expectation, and candidate methods are still only covered indirectly.
