---
type: Subsystem
title: Evaluation agent
description: The manager-assessment configuration — the fixed rubric, the role-fact checklist, and the expectation items with their two drafting agents. The scoring that consumes them lives in report_engine/.
resource: /evaluation_agent
tags: [evaluation, manager-assessment, rubric, role-facts, expectations]
generated:
  by: claude-opus-5
  at: "2026-09-13T00:00:00Z"
verified:
  - by: claude-opus-5
    at: "2026-09-13T00:00:00Z"
  - by: claude-fable-5-1
    at: "2026-09-13T00:00:00Z"
  - by: claude-opus-5
    at: "2026-09-10T00:00:00Z"
  - by: kimi-code/okf-curator
    at: "2026-08-22T21:10:00Z"
status: stable
sources:
  - resource: /evaluation_agent/schema.py
  - resource: /evaluation_agent/role_facts.py
  - resource: /evaluation_agent/prompts.py
  - resource: /evaluation_agent/rubric.py
  - resource: /evaluation_agent/expectations.py
---
# Evaluation agent

`evaluation_agent/` — the package that owns **what the manager was supposed to
do, and whether they did it**. Sibling of `candidate_agent`; imports `llm` and
nothing else, enforced by `tests/test_architecture.py`.

This package is deliberately small and now complete for what it owns: the
role-fact checklist, [the rubric](/concepts/modules/evaluation-agent-rubric.md)
and [the expectation items](/concepts/modules/evaluation-agent-expectations.md).
The deterministic signals, the judge pass and the report — milestone M3 of the
Phase 0 MVP plan — were built in **`report_engine/`** (2026-08-26/27), not
here, because that package imports nothing first-party by rule. The two meet in
`control_plane/reporting.py`, which imports `DEFAULT_RUBRIC` from this package
to assemble the session bundle the report engine scores. See
[Report engine](/concepts/subsystems/report-engine.md).

## Why it exists at all right now

The report's *"4 of 5 role facts conveyed"* panel needs a checklist to count
against, and that checklist has to exist before an interview is created. It is
the first piece of the evaluation layer that the configuration screen depends
on, so it landed with M1 rather than waiting for M3.

## The fixed checklist

```python
ROLE_FACT_KEYS = ("targets", "shifts", "location",
                     "comp_band", "growth_path", "next_steps")

class RoleFact(BaseModel):
    key: str          # one of the above
    statement: str    # this interview's wording; "" means not applicable here
```

**The keys are fixed in code, and that is the whole point.** The report compares
managers to each other, so the checklist cannot vary per interview or the scores
stop being comparable — the same argument that fixes the trait axes in
`candidate_agent`. What varies per interview is the *statement* of each fact.

A fact with an empty `statement` is **not on that interview's checklist**: it is
neither counted nor scored against. That is how the spec's "4 of 5" arises —
five facts were stated at configuration time, four were conveyed in the session.

## `RoleFactsAgent` — the model drafts wording, never the list

`extract(job_title, jd, location) -> list[RoleFact]`, temperature **0.1**,
because this is extraction and warmth here produces facts the job description
does not contain.

`_build` clamps the model's answer onto `ROLE_FACT_KEYS`:

* a key that is not on the list is **discarded** — a hallucinated seventh fact cannot reach the report and quietly change what managers are measured against;
* a key the model omitted comes back with an empty statement rather than vanishing, so the operator sees what was not answered instead of a silently shortened checklist;
* every statement is truncated to 300 characters.

The prompt instructs the model to leave a fact empty when the description does
not support it. Verified against the live model: a JD naming a target and a
shift pattern produced statements for `targets`, `shifts` and `location`, and
left `comp_band`, `growth_path` and `next_steps` **empty** rather than inventing
a salary band.

## The rubric — org-owned configuration, not generated content

[`rubric.py`](/concepts/modules/evaluation-agent-rubric.md) holds the scoring
instrument itself: the training-wizard specification's four criteria (Clarity
25, Structured 30, Fair & Inclusive 25, Communication & Presence 20), readiness
bands that reproduce the spec's own examples (74 → Competent, 48 → Developing,
39 → Needs practice), and `load_rubric(path)` for a validated JSON override.
**No criterion is a critical-fail gate** — the mockup shows one on Fair &
Inclusive, which contradicts the standing rule that the report is an analytical
estimate; `test_the_rubric_has_no_critical_fail_gate` keeps that a decision
rather than an omission. Scoring against this rubric happens in
`report_engine/score.py`, fed by `control_plane/reporting.py`; the rubric's
weights are the only thing this package contributes to a score.

`determine_interview_type(experience_level, company_type)` also lives in
`rubric.py` (2026-09-13). It is a four-row deterministic table that moved here
from the retired `expectation_agent/rubric.py` because it was the only thing
that package computed which anything still read: both cast paths tell the
casting model what shape of conversation the persona is walking into, and the
alternative was a hardcoded `"mixed"` in two places.

## The expectation items — the same discipline, a second checklist

[`expectations.py`](/concepts/modules/evaluation-agent-expectations.md) (2026-09-13)
is `role_facts.py`'s pattern applied to the granular rubric *under* the four
competencies. `fixed_items()` derives one `ExpectationItem` per behaviour in
`DEFAULT_RUBRIC.criteria[].covers`, with a deterministic id. `ExpectationsAgent`
drafts job-grounded extras and files a manager's own item under one of the four,
and cannot do anything else: not add a competency, not change a weight, not set
`enabled`.

The thing to hold in mind when reading it: **the subject is the interviewer**.
The role facts are about the role; an expectation item is a behaviour of the
hiring manager being assessed, never of the candidate, and the drafting prompt
repeats that more than anything else it says.

## Where it is used

`POST /api/v1/role-facts` — the wizard's "✨ Auto-fill from the job description"
button. `POST /api/v1/expectations/draft` and `.../classify` are the same shape
of call for the expectation list. All three are deliberately **not** part of
interview creation: the operator sees the drafts and corrects them before
anything is stored, and `POST /interviews` stays a fast, model-free call.

`control_plane/reporting.py` passes the interview's **enabled** items into the
analysis context (`AnalysisContext.expectations`), and `control_plane/api.py`
passes them into every cast, so the persona is written to make those behaviours
worth performing.

## Related

[REST API](/concepts/contracts/rest-api.md) ·
[Interview record](/concepts/contracts/interview-record.md) ·
[evaluation_agent/expectations.py](/concepts/modules/evaluation-agent-expectations.md) ·
[evaluation_agent/role_facts.py](/concepts/modules/evaluation-agent-role-facts.md) ·
[Determinism split](/concepts/determinism.md)
