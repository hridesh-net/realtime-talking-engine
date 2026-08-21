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
    language: str = "en"

class InterviewCreateRequest(BaseModel):
    job_title: str
    jd: str
    skills_required: list[str]          # min_length=1
    job_location_type: str              # remote | onsite | hybrid
    experience_level: str               # junior | mid | senior
    company_type: str                   # startup | mnc
    mode: str = "live_interview"        # live_interview | training_interviewer
    config: InterviewConfigInput = ...
    scheduled_at: datetime | None = None
    metadata: dict[str, Any] = {}

class InterviewResponse(BaseModel):
    id: str                             # uuid4
    job_title, jd, skills_required, job_location_type,
    experience_level, company_type, mode: ...
    status: str                         # scheduled (only value written today)
    config: InterviewConfigInput
    ai_persona: CandidatePersona | None = None    # legacy, training mode only
    scheduled_at: datetime | None
    created_at: datetime
    start_url: str                      # f"/api/v1/interviews/{id}/start"
    metadata: dict[str, Any]
```

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
