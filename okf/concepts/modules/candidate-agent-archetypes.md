---
type: Module
title: candidate_agent/archetypes.py
description: The fixed catalog of eleven persona families, validated at registration.
resource: /candidate_agent/archetypes.py
tags: [archetypes, catalog, personas, determinism]
generated:
  by: claude-opus-5/okf-curator
  at: "2026-08-21T19:17:54Z"
verified:
  - by: claude-opus-5/okf-curator
    at: "2026-08-21T19:17:54Z"
status: stable
sources:
  - resource: /candidate_agent/archetypes.py
  - resource: /tests/test_candidate_rubric.py
---
# candidate_agent/archetypes.py

987 lines, of which ~900 are the catalog data. `CATALOG_VERSION = "v1.0"`.

# Schema

```python
TRAIT_NAMES = ("smartness", "dumbness", "seriousness", "effort",
               "interest", "honesty", "preparedness", "nervousness")
VERDICTS = ("select", "reject", "borderline")

class SpeechSpec(TypedDict):        pace, verbosity, filler_frequency,
                                    hesitation_frequency, formality,
                                    interrupts_interviewer, tone
class AnswerPolicySpec(TypedDict):  default_answer_depth, on_unknown_question,
                                    on_pressure, on_silence

@dataclass(frozen=True)
class ScorecardSignal:  id, signal, weight, how_to_surface

@dataclass(frozen=True)
class Archetype:
    key, label, description, verdict, interviewer_challenge
    traits: dict[str, tuple[int, int]]      # inclusive bounds per trait
    knowledge_band: tuple[int, int]         # inclusive competence band
    speech: SpeechSpec
    answer_policy: AnswerPolicySpec
    must_discover: list[ScorecardSignal]
    interviewer_failure_modes: list[str]
    allows_adjacent_strength: bool = False
    default_slot: str | None = None         # "select" | "reject"
    tags: list[str] = []
    @property trait_bounds_json -> dict[str, list[int]]

ARCHETYPES: dict[str, Archetype]            # populated by _register at import

def get(key) -> Archetype                   # KeyError lists known keys
def default_keys() -> list[str]             # selects first, then rejects
def catalog() -> list[dict]                 # serializable, for the UI
```

## Registration validates

`_register` raises at **import time** if:

* `must_discover` weights do not sum to exactly 1.0 (rounded to 4dp),
* the verdict is not in `VERDICTS`,
* any of the eight traits is missing.

So a malformed archetype breaks the import, not a request.

## The catalog

| key | verdict | band | adjacent | default |
|---|---|---|---|---|
| `strong_hire` | select | 7–10 | | select |
| `clear_reject` | reject | 1–4 | | reject |
| `lazy` | reject | 4–6 | | |
| `smart_but_lazy` | borderline | 7–9 | | |
| `disengaged` | reject | 4–6 | | |
| `eager_underqualified` | borderline | 2–5 | | |
| `confident_bluffer` | reject | 2–5 | | |
| `resume_inflater` | reject | 3–5 | | |
| `nervous_but_capable` | select | 7–9 | | |
| `rambler` | borderline | 6–8 | | |
| `specialist_mismatch` | borderline | 2–5 | ✓ | |

Every archetype carries exactly **4** `must_discover` signals. 2 select, 5
reject, 4 borderline.

`specialist_mismatch` is the only one with `allows_adjacent_strength` — its point
is genuine depth in the *wrong* stack, so the agent lets extra skills through
unclamped for it alone.

## Adding an archetype

Append a `_register(Archetype(...))` call. Nothing else — no agent, route, or
schema change. `test_ocp_new_archetype_needs_no_agent_change` proves it by
registering one at runtime, and the rubric tests will immediately hold the new
entry to weight-sum, trait-bound, and verdict-direction rules.

Bump `CATALOG_VERSION` if you change an **existing** archetype: it feeds both
fingerprints, so stored personas should stop matching.

## Design constraint

From the module docstring: *"Every archetype exists to test one specific
interviewer skill. A persona that does not challenge the interviewer in a
distinct way does not belong here."* `interviewer_challenge` is where that
justification is written down — a new archetype without a distinct one is a
duplicate.
