---
type: Contract
title: Interview record
description: The job spec accepted at creation and the interview record returned.
resource: /control_plane/schemas.py
tags: [contract, api, pydantic]
generated:
  by: claude-opus-5
  at: "2026-09-14T00:00:00Z"
verified:
  - by: claude-opus-5
    at: "2026-09-14T00:00:00Z"
  - by: claude-opus-5
    at: "2026-09-13T00:00:00Z"
  - by: claude-opus-5
    at: "2026-09-12T00:00:00Z"
  - by: claude-opus-5
    at: "2026-09-10T00:00:00Z"
  - by: claude-opus-5/okf-curator
    at: "2026-08-21T19:17:54Z"
status: stable
sources:
  - resource: /control_plane/schemas.py
  - resource: /control_plane/repository.py
---
# Interview record

# Schema

```python
class InterviewConfigInput(BaseModel):
    duration_minutes: int = 60          # gt=0, le=MAX_INTERVIEW_MINUTES (180)
    question_mode: str = "AI"           # AI | HYBRID | MANUAL
    interview_mode: str = "STANDARD"    # STANDARD | DEEP

class InterviewCreateRequest(BaseModel):
    job_title: str
    jd: str
    skills_required: list[str]          # min_length=1
    job_location_type: str              # remote | onsite | hybrid
    experience_level: str               # junior | mid | senior
    company_type: str                   # startup | mnc
    mode: str = "live_interview"        # live_interview | training_interviewer
    # --- the training-wizard specification's configuration ---
    location: str = ""                  # where the role is based
    department: str = ""                # free text; the UI suggests, never constrains
    manager_level: str = ""             # e.g. "Frontline manager"
    language: str = "english_indian"    # english_indian | hinglish | hindi
    proctoring: str = "off"             # off | identity | full — recorded, never enforced
    persona_notes: str = ""             # max_length=2000, layered on the archetype
    role_facts: list[RoleFact] = []     # the role-fact checklist
    expectations: list[ExpectationItem] = fixed_items()   # validated, see below
    report_sections: dict[str, bool] = REPORT_SECTIONS   # 8 keys, 6 on by default
    config: InterviewConfigInput = ...
    scheduled_at: datetime | None = None
    metadata: dict[str, Any] = {}

class InterviewResponse(InterviewCreateRequest-ish):
    id: str                             # uuid4
    status: str                         # scheduled | in_progress | completed | failed | cancelled
    ai_persona: CandidatePersona | None = None    # legacy, training mode only
    created_at: datetime
    start_url: str                      # f"/api/v1/interviews/{id}/start"
```

`RoleFact` (renamed out of the `clarity` family on 2026-09-10 — see
[log.md](/log.md)) and `ExpectationItem` both live in
[`evaluation_agent`](/concepts/subsystems/evaluation-agent.md),
not here — the agent that produces them owns the model, and `control_plane` may
import downward. `REPORT_SECTIONS` is in `control_plane.schemas` because it
describes what the *report* shows, not what the evaluator computes.

## `expectations` — the granular rubric (2026-09-13)

The four competencies are **not** a field. They are
[`evaluation_agent/rubric.py`](/concepts/modules/evaluation-agent-rubric.md) and
are identical on every interview, because the report compares managers to each
other. What an interview carries is the list of behaviours under them:

```python
class ExpectationItem(BaseModel):
    id: str                  # "clarity.explains-the-role-beyond-the-jd" | "drafted.structure.1" | "custom.1"
    competency_id: str       # one of the rubric's four ids
    text: str                # max_length=200
    source: str              # fixed | drafted | custom
    enabled: bool = True     # the toggle the manager sees
```

What `POST /interviews` **and** `PATCH /interviews/{id}` enforce, in
`control_plane.schemas.validate_expectations`:

| Rule | On violation |
|---|---|
| every `competency_id` is one of the four | 422 |
| non-empty `text` | 422 |
| a **fixed** id carries the rubric's wording verbatim | 422 — toggled off, never reworded |
| a `source: fixed` item whose id is not a fixed id | 422 |
| ids are unique after normalisation | 422 |
| at most `MAX_CUSTOM_ITEMS` (12) custom items | 422 |
| a missing fixed item | **added back, enabled** — a half-instrument is not comparable |
| a custom item's id | **overwritten** with `custom.{n}` in request order |

Omitting the field stores `fixed_items()` with everything enabled. An empty list
does the same, through the restore rule. The repository fills `[]` in with
`fixed_items()` on read as well, which is what makes rows written before
2026-09-13 still report a full checklist.

**The restore rule is what makes a partial update destructive** (2026-09-14).
`PATCH` runs the same validator, and it cannot know which omissions were
deliberate: a list that leaves out a fixed item the manager had switched off
gets it back *enabled*, and a list that leaves out a drafted or custom item
loses it. There is no merge with the stored row — the validator only ever sees
the body. So an editing client sends the whole list, every time.
`tests/test_expectations.py::test_a_partial_patch_list_re_enables_fixed_items_and_drops_drafted_ones`
pins it so nobody has to rediscover it.

## `report_sections` — re-keyed 2026-09-13

Eight keys, and every one of them is a section
[`report_engine/render.py`](/concepts/subsystems/report-engine.md) actually has:
`scorecard`, `qna`, `bei`, `strengths_gaps`, `areas`, `percentage_score` on by
default; `transcript` and `summary` off. The twelve keys copied from the wizard
mockup named seven sections the engine does not measure — a toggle that changes
nothing is the inert guard this repo forbids. The defaults follow one rule: what
the report shows today stays on, a number is on by default only when code
computes it deterministically (the readiness index is), prose no number stands
behind is off, and raw evidence is off until asked for. **WP2 is what makes the
renderer honour them**; today they are stored and returned.

The same "no merge" rule as `expectations`, one level simpler:
`validate_report_sections` merges what arrives onto `REPORT_SECTIONS` — the
**code defaults**, not the stored row — so a `PATCH` carrying one key resets the
other seven. Send all eight.

## `InterviewUpdateRequest` — the only write after creation (2026-09-14)

```python
class InterviewUpdateRequest(BaseModel):
    expectations: list[ExpectationItem] | None = None   # validate_expectations
    report_sections: dict[str, bool] | None = None      # validate_report_sections
    # model_validator: both None -> 422
```

Two fields, because the portal wizard saves the interview on step 1 and draws
the expectation toggles on step 2; nothing else on the record is editable and
the job spec stays creation's. The validators are module functions shared with
`InterviewCreateRequest` rather than methods copied onto it — two copies of the
checklist rules would be two instruments, and they would drift on the first
rubric change.

Both validators return `None` unchanged when given `None`, and that is a **500
this would otherwise ship**: the fields are optional, so an explicit
`"expectations": null` reaches the field validator, and pydantic maps only
`ValueError`/`AssertionError` to a 422 — a `TypeError` from iterating `None`
escapes the error envelope as an unhandled exception. With the guard, `null`
simply means "not editing this field"; a body where both are null or absent
edits nothing and the model validator makes it a 422 rather than a no-op that
still moved `updated_at`.

`updated_at` is always in the repository's `SET` clause, which is also what
keeps the clause non-empty whatever else is present — so there is no branch in
`InterviewRepository.update` for a body that edits nothing.

## The three fields that do more than they look like

**`language`** is not a label. It reaches the casting prompt (so `opening_line`
and `sample_phrases` are written in it), the compiled `system_prompt`'s
`HOW YOU TALK` section, and the realtime transcription hint. Verified live: a
`hinglish` interview produces *"Main bahut excited hoon is opportunity ke liye."*
See [engine contract](/concepts/contracts/engine-contract.md).

**`persona_notes`** — renamed on 2026-09-10, because the field is not notes
*about* a job applicant: it is colour layered on the persona's archetype, and it
feeds the persona's casting prompt — is free text an operator types, which makes
it the one place in casting where someone could try to talk a persona out of its
own ceiling. The casting prompt subordinates it explicitly — *"It adds detail; it
does not replace anything"* — and the knowledge clamp in
`VirtualCandidateAgent._build_knowledge_map` enforces the band regardless of
what the note said. `test_operator_notes_cannot_override_the_archetype` covers
both halves.

**`proctoring` is recorded and never enforced, and nothing will ever be wired to
it.** The field exists so the screen matches the specification and so the setting
is captured. It was written with a gate on it — *"identity capture is deliberately
deferred until data retention is decided; do not wire a camera to it without that
decision"* — and on **2026-09-12 that gate was resolved, against wiring it up**:

* The retention decision was taken. Recordings, video included, are **kept
  indefinitely and deleted by hand**, stated explicitly in
  [Session recording](/concepts/contracts/session-recording.md).
* A camera *is* now captured on voice sessions — but **unconditionally, and
  independently of this field**. It is the manager's own camera on a practice
  call, not identity proctoring of a candidate, and gating it on a setting whose
  meaning is "proctor the candidate" would have conflated two different things.
* The portal no longer sends `proctoring` at all. The **column stays**, with its
  default `"off"`: dropping it means a migration, a console change and a schema
  re-export, none of which were on the path of this change. It is a follow-up,
  listed in `docs/VIDEO_SESSION_TAB_PLAN.md` §8.

So `proctoring` is now a **vestigial field**: written, stored, read by nothing,
and with its one plausible future use explicitly assigned elsewhere.

Every enum-ish field is a Pydantic `pattern`, and the same values are re-asserted
as SQLite `CHECK` constraints — see [Database schema](/concepts/contracts/database-schema.md).
Changing one without the other produces a 500 at insert rather than a 422.

## What is deliberately absent

**Who takes the interview is not captured at creation.** An interview is a
*fixture*: a job, a persona set, a competency checklist and a report shape,
created once and practised against by a cohort. Takers arrive later, through
[a link](/concepts/contracts/links-and-participants.md), and each one becomes a
`participant` row keyed on their email. `interview_assignments` — designed and
never written — was dropped on 2026-09-13 in favour of that.

## Fields to be careful with

* `start_url` is **computed on read**, not stored — it points at an engine endpoint that does not exist yet.
* `status` is only ever written as `scheduled`; the CHECK constraint allows `in_progress`, `completed`, `failed`, `cancelled`, but nothing transitions it.
* `ai_persona` is the **legacy** seeded persona, populated only when `mode == "training_interviewer"`, by `control_plane/persona.py`. It is unrelated to [virtual candidates](/concepts/contracts/virtual-candidate.md), which are the current mechanism. Two persona systems coexist.
* `duration_minutes` is the session clock and is echoed by the public link route; nothing else reads it.
* `duration_minutes`' ceiling is `schemas.MAX_INTERVIEW_MINUTES`, shared with `SessionCreateRequest.planned_minutes` — the portal launcher opens a session with this interview's `duration_minutes`, so a lower session cap rejects a valid interview. Move the constant, never one field. See [Session transcript](/concepts/contracts/session-transcript.md).
* `skills_required` strings are matched **case-insensitively but exactly** by the candidate agent's knowledge map, and re-emitted with the original spelling. Renaming a skill between interview creation and enrollment produces a persona missing that skill.

## Related

[REST API](/concepts/contracts/rest-api.md) ·
[repository.py](/concepts/modules/control-plane-repository.md) ·
`owner_handover/interview_response_schema.json`, `interview_update_schema.json`
(`InterviewCreateRequest` is deliberately **not** exported — the handover
describes what the service returns and what a wizard may edit, and the create
body is documented here)
