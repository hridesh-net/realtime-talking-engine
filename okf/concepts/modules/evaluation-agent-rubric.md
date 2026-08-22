---
type: Module
title: evaluation_agent/rubric.py
description: The fixed manager rubric — four criteria, weights, readiness bands, and an optional JSON override.
resource: /evaluation_agent/rubric.py
tags: [evaluation, rubric, scoring, determinism]
generated:
  by: kimi-code/okf-curator
  at: "2026-08-22T21:10:00Z"
status: stable
sources:
  - resource: /evaluation_agent/rubric.py
  - resource: /tests/test_architecture.py
---
# evaluation_agent/rubric.py

139 lines. **Org-owned configuration, not generated content.** The rubric must be
identical across every session or manager scores stop being comparable, which is
the whole point of the report — so it is code with an optional file override,
never something a model authors per interview.

# Schema

```python
class Criterion(BaseModel):  id, label, weight: float (0,1], covers: list[str]
class Band(BaseModel):       label, floor: int [0,100]   # inclusive; highest match wins
class Rubric(BaseModel):
    version: str
    criteria: list[Criterion]
    bands: list[Band]
    @property ids -> tuple[str, ...]        # criterion ids, in report order
    def band_for(readiness: int) -> str

RUBRIC_VERSION = "v1.0"
DEFAULT_RUBRIC = Rubric(...)                # the spec's four criteria
def load_rubric(path: str | Path | None = None) -> Rubric
```

## The default instrument

| id | label | weight |
|---|---|---|
| `clarity` | Hiring with Clarity | 0.25 |
| `structure` | Structured Interviewing | 0.30 |
| `fairness` | Fair & Inclusive | 0.25 |
| `communication` | Communication & Presence | 0.20 |

Bands: Needs practice ≥ 0, Developing ≥ 45, Competent ≥ 65 — these reproduce the
specification's own examples (74 → Competent, 48 → Developing, 39 → Needs
practice). Each criterion's `covers` list is shown to the manager verbatim in
the report.

**These are the training-wizard specification's four criteria, not the BRD's
five.** The mockup is the newer artefact and defines the MVP. `candidate_agent`
re-declares the same ids as `RUBRIC_CRITERIA` for its `stresses` maps — sibling
agent packages never import each other, so
`test_rubric_vocabulary_agrees_across_the_two_agents` (in the control-plane
tests, which sit above both) is the drift guard.

## No critical-fail gate, by decision

Nothing here caps, fails or overrides a score: the report is an analytical
estimate. The design mockup shows Fair & Inclusive as a gating criterion; that
contradicts the standing rule and is knowingly **not** implemented.
`test_the_rubric_has_no_critical_fail_gate` asserts no criterion carries a
`gate` or `cap` field and the weights sum to 1.0, so a gate must arrive as a
deliberate change to that test, not as a quiet field. A bias incident raises a
flag that the session row and the cohort count read; it does not move a number.

## `load_rubric` — the one escape hatch

`load_rubric(path)` reads a JSON override so weights can be retuned — or the
criteria expanded back to the BRD's five — without touching the judge, the
signals, or the report layout. It validates: weights must sum to 1.0 (4dp) and
criterion ids must be unique. With no path it returns `DEFAULT_RUBRIC`.

**The caller resolves the path — this package never reads the environment**, the
same rule the model adapters follow for API keys.
