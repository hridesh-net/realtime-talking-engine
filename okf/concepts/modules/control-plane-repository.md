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
    at: "2026-08-21T19:17:54Z"
status: stable
sources:
  - resource: /control_plane/repository.py
  - resource: /control_plane/database.py
---
# control_plane/repository.py

273 lines. One class, `InterviewRepository`, satisfying `InterviewStore`,
`ExpectationStore`, and `CandidateStore` structurally — it imports none of them.

# Schema

```python
def _utcnow() -> str          # datetime.now(UTC).isoformat()
def _new_id() -> str          # str(uuid.uuid4())

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
```

`import builtins` at the top exists solely so the `list` **method** can annotate
a return type of `builtins.list[...]` without shadowing.

## Writes

* **`create`** — generates the uuid, serializes `skills_required`/`config`/`metadata` to JSON, and for `mode == "training_interviewer"` also generates the [legacy persona](/concepts/subsystems/control-plane.md) and writes an `ai_personas` row in the same transaction. Then re-reads via `get()` and raises if it vanished.
* **`save_expectation`** — `ON CONFLICT(interview_id) DO UPDATE`; regenerating replaces.
* **`save_candidate`** — `ON CONFLICT(interview_id, archetype) DO UPDATE`, refreshing `candidate_id` and `updated_at` but leaving `created_at` at the first cast.

Both upserts persist `model_dump_json(exclude={"raw_model_output"})`, so the raw
draft never reaches disk.

## Reads

Candidates and expectations are rehydrated from the **JSON column alone** —
`VirtualCandidate.model_validate_json(row["persona_json"])`. The indexed columns
(`verdict`, `archetype`, fingerprints) exist for querying and inspection, not for
reconstruction, so they can in principle drift from the document. `get_expectation`
additionally forces `raw_model_output = None` before validating.

`_row_to_response` handles the `"Z"` → `"+00:00"` timestamp fix-up and computes
`start_url` on the fly.

## Gotchas

* **Foreign keys do not cascade.** `PRAGMA foreign_keys = ON` is never issued, so deleting an interview orphans its personas and expectation. This is a `database.py`-level fix.
* `with self.conn:` gives transaction-per-statement-group semantics, not a connection context manager — the connection is never closed here (`main.py` closes the startup one).
* Every write re-serializes the whole persona document; a large training set is fine at this scale but this is not a partial-update design.
* `create` writes `status='scheduled'` as a SQL literal; nothing ever transitions it.
* No test exercises this file directly.
