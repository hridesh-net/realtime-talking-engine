---
type: Contract
title: Interview record
description: The job spec accepted at creation and the interview record returned.
resource: /control_plane/schemas.py
tags: [contract, api, pydantic]
generated:
  by: claude-opus-5/okf-curator
  at: "2026-08-21T19:17:54Z"
verified:
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
    duration_minutes: int = 60          # gt=0, le=180
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
    candidate_notes: str = ""           # max_length=2000, layered on the archetype
    clarity_facts: list[ClarityFact] = []          # the role-fact checklist
    report_sections: dict[str, bool] = REPORT_SECTIONS   # 12 keys, 10 on by default
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

`ClarityFact` lives in [`evaluation_agent.schema`](/concepts/subsystems/evaluation-agent.md),
not here — the agent that produces it owns the model, and `control_plane` may
import downward. `REPORT_SECTIONS` is in `control_plane.schemas` because it
describes what the *console* shows, not what the evaluator computes.

## The three fields that do more than they look like

**`language`** is not a label. It reaches the casting prompt (so `opening_line`
and `sample_phrases` are written in it), the compiled `system_prompt`'s
`HOW YOU TALK` section, and the realtime transcription hint. Verified live: a
`hinglish` interview produces *"Main bahut excited hoon is opportunity ke liye."*
See [engine contract](/concepts/contracts/engine-contract.md).

**`candidate_notes`** is free text an operator types, which makes it the one
place in casting where someone could try to talk a persona out of its own
ceiling. The casting prompt subordinates it explicitly — *"It adds detail; it
does not replace anything"* — and the knowledge clamp in
`VirtualCandidateAgent._build_knowledge_map` enforces the band regardless of
what the note said. `test_operator_notes_cannot_override_the_archetype` covers
both halves.

**`proctoring` is recorded and never enforced.** No camera is accessed at any
setting. The field exists so the screen matches the specification and so the
setting is captured, but identity capture is deliberately deferred until data
retention is decided. Do not wire a camera to it without that decision.

Every enum-ish field is a Pydantic `pattern`, and the same values are re-asserted
as SQLite `CHECK` constraints — see [Database schema](/concepts/contracts/database-schema.md).
Changing one without the other produces a 500 at insert rather than a 422.

## What is deliberately absent

**Candidate and interviewer are not captured at creation.** The job spec is the
whole payload; assignment happens later through endpoints that do not exist yet.
The `interview_assignments` table is reserved for it.

## Fields to be careful with

* `start_url` is **computed on read**, not stored — it points at an engine endpoint that does not exist yet.
* `status` is only ever written as `scheduled`; the CHECK constraint allows `in_progress`, `completed`, `failed`, `cancelled`, but nothing transitions it.
* `ai_persona` is the **legacy** seeded persona, populated only when `mode == "training_interviewer"`, by `control_plane/persona.py`. It is unrelated to [virtual candidates](/concepts/contracts/virtual-candidate.md), which are the current mechanism. Two persona systems coexist.
* `duration_minutes` feeds the expectation's phase table, which has exact templates for 30/45/60 and linear scaling otherwise.
* `skills_required` strings are matched **case-insensitively but exactly** by the candidate agent's knowledge map, and re-emitted with the original spelling. Renaming a skill between interview creation and enrollment produces a persona missing that skill.

## Related

[REST API](/concepts/contracts/rest-api.md) ·
[repository.py](/concepts/modules/control-plane-repository.md) ·
`owner_handover/interview_create_schema.json`, `interview_response_schema.json`
