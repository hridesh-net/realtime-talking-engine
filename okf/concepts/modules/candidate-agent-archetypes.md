---
type: Module
title: candidate_agent/archetypes.py
description: The fixed catalog of seven manager-stressing persona families, validated at registration.
resource: /candidate_agent/archetypes.py
tags: [archetypes, catalog, personas, determinism]
generated:
  by: claude-opus-5/okf-curator
  at: "2026-08-21T19:17:54Z"
verified:
  - by: claude-opus-5/okf-curator
    at: "2026-08-22T18:40:00Z"
status: stable
sources:
  - resource: /candidate_agent/archetypes.py
  - resource: /tests/test_candidate_rubric.py
---
# candidate_agent/archetypes.py

~800 lines, of which most is catalog data. `CATALOG_VERSION = "v2.0"`.

**v2.0 flipped what the catalog is for.** v1 was built so an interviewer could
practise *judging candidates*, so its entries were hiring outcomes
(`strong_hire`, `clear_reject`, `specialist_mismatch`). Nobody grades the
verdict any more — the manager is the assessed subject — so each v2 entry
pressures one **manager competency** instead. `verdict` survives as persona
metadata (it keeps a persona internally consistent while it is cast, and drives
the two defaults) and is **not** a scoring input.

# Schema

```python
TRAIT_NAMES = ("smartness", "dumbness", "seriousness", "effort",
               "interest", "honesty", "preparedness", "nervousness")
VERDICTS = ("select", "reject", "borderline")

# The five BRD v3 manager competencies. Re-declared here rather than imported:
# sibling agent packages never import each other.
RUBRIC_CRITERIA = ("clarity", "structure", "bias", "experience", "communication")
RUBRIC_LABELS: dict[str, str]        # id -> "Hiring with Clarity", ...
STRESS_LABELS = ("light", "moderate", "high", "very high")

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
    session_beats: list[str] = []           # what this persona tends to do
    stresses: dict[str, int] = {}           # criterion id -> pressure, 1-4
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
* any of the eight traits is missing,
* a `stresses` key is not a known rubric criterion, or its value is outside 1-4,
* `session_beats` is empty.

So a malformed archetype breaks the import, not a request.

## The catalog

| key | label | verdict | band | stresses hardest | adjacent | default |
|---|---|---|---|---|---|---|
| `cooperative_trap` | The cooperative candidate | select | 6–8 | bias 4 | | select |
| `evasive` | The evasive candidate | reject | 3–5 | structure 4 | | reject |
| `nervous_fresher` | The nervous fresher | select | 6–8 | communication 4, experience 4 | | |
| `inflated_resume` | The inflated resume | reject | 3–5 | structure 4 | | |
| `comp_first` | The comp-first candidate | borderline | 6–8 | clarity 4 | ✓ | |
| `defensive` | The defensive candidate | borderline | 5–7 | communication 4 | | |
| `rambler` | The rambler | borderline | 6–8 | structure 4 | | |

Every archetype carries exactly **4** `must_discover` signals. 2 select, 2
reject, 3 borderline. A test asserts every rubric criterion is stressed at
level ≥3 by at least one persona — no manager competency is left without a
persona that exercises it.

`comp_first` is the only one with `allows_adjacent_strength`: they are genuinely
competent, so the agent lets extra skills through unclamped for it alone.

## `session_beats` reach the live persona through casting, not the contract

The beats are **not** written into `engine_contract.py` and do not bump
`ENGINE_CONTRACT_VERSION`. They are rendered into the *casting* prompt
(`prompts.py`, `=== BEATS THIS PERSONA HITS IN THE SESSION ===`), where the
model turns them into `always_does` / `never_does` / `reveals_depth_when` — and
those land verbatim in the compiled prompt's `ALWAYS` and `NEVER` sections.
Verified against a live cast: `cooperative_trap` produced *"Volunteers a personal
detail about her recent marriage and future plans mid-interview"* in `ALWAYS`.

**This is model-mediated, not enforced.** Nothing guarantees the beat fires, or
fires at a particular moment. Deterministic scripting is `DisruptionSpec` in
pivot-plan Phase 3.2, deliberately deferred. The UI says "What they tend to do"
for exactly this reason.

## `stresses` is advisory

It records which manager competency a persona pressures and how hard, and feeds
the picker's stress bars. **It scores nothing** — there is no evaluation layer
yet, and by explicit product decision there is no critical-fail gate on any
criterion, including bias. Do not reintroduce one.

## Adding an archetype

Append a `_register(Archetype(...))` call. Nothing else — no agent, route, or
schema change. `test_ocp_new_archetype_needs_no_agent_change` proves it by
registering one at runtime — including asserting that its `session_beats` and
`stresses` arrive in `catalog()`, so the picker needs no UI edit either. The
rubric tests will immediately hold the new entry to weight-sum, trait-bound,
verdict-direction, criterion-validity and non-empty-beats rules.

Bump `CATALOG_VERSION` if you change an **existing** archetype: it feeds both
fingerprints, so stored personas should stop matching.

## Design constraint

Every archetype exists to stress one manager competency in a way no other entry
does. `interviewer_challenge` is where that justification is written down, and
`stresses` is where it is made machine-readable — a new archetype whose
challenge and stress profile duplicate an existing one is a duplicate.
