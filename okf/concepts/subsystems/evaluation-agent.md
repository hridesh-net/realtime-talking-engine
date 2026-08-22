---
type: Subsystem
title: Evaluation agent
description: The manager-assessment package — today the fixed role-fact checklist and its drafting agent; the rubric, signals and report land here next.
resource: /evaluation_agent
tags: [evaluation, manager-assessment, rubric, clarity-facts]
generated:
  by: claude-opus-5/okf-curator
  at: "2026-08-22T20:10:00Z"
verified:
  - by: kimi-code/okf-curator
    at: "2026-08-22T21:10:00Z"
status: draft
sources:
  - resource: /evaluation_agent/schema.py
  - resource: /evaluation_agent/role_facts.py
  - resource: /evaluation_agent/prompts.py
  - resource: /evaluation_agent/rubric.py
---
# Evaluation agent

`evaluation_agent/` — the package that owns **what the manager was supposed to
do, and whether they did it**. Sibling of `candidate_agent`; imports `llm` and
nothing else, enforced by `tests/test_architecture.py`.

`status: draft` because it is deliberately partial. The role-fact checklist and
[the rubric](/concepts/modules/evaluation-agent-rubric.md) are built; the
deterministic signals, the judge pass and the report are milestone M3 of the
Phase 0 MVP plan.

## Why it exists at all right now

The report's *"4 of 5 role facts conveyed"* panel needs a checklist to count
against, and that checklist has to exist before an interview is created. It is
the first piece of the evaluation layer that the configuration screen depends
on, so it landed with M1 rather than waiting for M3.

## The fixed checklist

```python
CLARITY_FACT_KEYS = ("targets", "shifts", "location",
                     "comp_band", "growth_path", "next_steps")

class ClarityFact(BaseModel):
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

`extract(job_title, jd, location) -> list[ClarityFact]`, temperature **0.1**,
because this is extraction and warmth here produces facts the job description
does not contain.

`_build` clamps the model's answer onto `CLARITY_FACT_KEYS`:

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
rather than an omission. Nothing yet scores a session against the rubric — the
signals, the judge and the report are M3.

## Where it is used

`POST /api/v1/role-facts` — the wizard's "✨ Auto-fill from the job description"
button. Deliberately **not** part of interview creation: the operator sees the
drafts and corrects them before anything is stored, and `POST /interviews` stays
a fast, model-free call.

## Related

[REST API](/concepts/contracts/rest-api.md) ·
[Interview record](/concepts/contracts/interview-record.md) ·
[Determinism split](/concepts/determinism.md)
