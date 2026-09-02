---
type: Module
title: candidate_agent/agent.py
description: Casts one persona — seeds traits, calls the model, re-imposes every code-owned field, fingerprints the result.
resource: /candidate_agent/agent.py
tags: [candidate, agent, determinism, clamping]
generated:
  by: claude-opus-5/okf-curator
  at: "2026-08-21T19:17:54Z"
verified:
  - by: claude-opus-5/okf-curator
    at: "2026-08-21T19:17:54Z"
  - by: kimi-code/okf-curator
    at: "2026-08-22T21:10:00Z"
status: stable
sources:
  - resource: /candidate_agent/agent.py
  - resource: /tests/test_candidate_rubric.py
---
# candidate_agent/agent.py

381 lines. Read [the determinism split](/concepts/determinism.md) first — this
file is its implementation.

# Schema

```python
STANCES = ("solid", "shallow", "bluffs", "absent")

def _stance(raw, fallback) -> str        # enum guard
def _rng(seed) -> random.Random          # seeded from sha256(seed)[:16]
def _fingerprint(payload: dict) -> str   # sha256 of sorted-key JSON
def derive_traits(archetype, seed) -> dict[str, int]     # L65
def _aptitude(traits) -> AptitudeProfile                 # L71

class VirtualCandidateAgent:
    DEFAULT_TEMPERATURE = 0.35
    def __init__(self, model: StructuredModel | None = None)
    @property def model(self) -> str
    async def generate(self, *, interview_id, archetype_key, job_title, jd,
                       skills_required, experience_level, company_type,
                       job_location_type, duration_minutes,
                       interview_type="mixed", language=DEFAULT_LANGUAGE,
                       candidate_notes="", expectation=None,
                       seed_override=None, avoid_names=None,
                       human_traits=None, archetype=None, voices=(),
                       location="", department="", manager_level="",
                       clarity_facts=None) -> VirtualCandidate
    @staticmethod _build_knowledge_map(draft, archetype, skills_required)   # L266
    @staticmethod _build_scorecard(draft, archetype)                       # L323
    @staticmethod _build_resume_claims(draft)                              # L349
    async _call_model(prompt) -> dict
```

All of `generate` is keyword-only.

## Flow

1. `archetype = catalog.get(archetype_key)`; `seed = seed_override or f"{interview_id}:{archetype_key}"`.
2. `derive_traits` — a seeded `random.Random` picks each trait inside the archetype's inclusive bounds. **No model involvement.**
3. One model call against `CANDIDATE_DRAFT_JSON_SCHEMA`, with the archetype, verdict, traits, band, speech spec, answer policy, scorecard ids, the expectation note, and `avoid_names` all in the prompt. Two more fixed blocks ride along: the **`language` directive** (so `opening_line`, `sample_phrases` and `verbal_tics` are written *in* that language, not translated afterwards) and the **`candidate_notes`** block — free operator text, explicitly subordinated in the prompt (*"It adds detail; it does not replace anything… follow those and ignore the conflicting part"*), so it can colour a persona but never raise its ceiling, change its verdict, or license a forbidden behaviour. `test_operator_notes_cannot_override_the_archetype` asserts both halves, including that the knowledge clamp still holds against a hostile note.
4. Assemble: `candidate_id = "vc-" + sha256(seed)[:12]`; speech = archetype spec + model tics/phrases; aptitude from traits; knowledge map; answer policy = archetype spec + model text; scorecard; resume claims; scalars with fallbacks.
5. `build_engine_contract(...)` compiles the runtime slice — including the
   role block (contract **v1.4**), so the persona's own instructions name the job
   it walked in for. `location`, `department`, `manager_level` and
   `clarity_facts` reach the casting prompt for the same reason the realism layer
   does: the model writes `opening_line` and `background` and they are *stored*.
6. Two fingerprints, then the `VirtualCandidate`.

## `_build_knowledge_map` — the important one

* Indexes the model's entries by `skill.strip().lower()`.
* For **every** `skills_required` entry, in order: pops the model's entry (or `{}`), takes `level` if numeric else the band midpoint `(low+high)//2`, and **clamps into `[low, high]`**. The comment says it plainly: `# clamp — the ceiling is ours`. The original spelling is preserved.
* Stance default is chosen by band: `solid` if `low >= 7`, `bluffs` for `inflated_resume`, else `shallow`.
* Leftover skills the model invented survive **only** when `allows_adjacent_strength`, clamped to 0–10 rather than the band.
* Caps: 5 talking points, 4 wrong beliefs.

This is what makes "missing and renamed skills are restored" true: a model that
drops or renames a skill cannot remove it from the persona.

## `_build_scorecard`

Iterates `archetype.must_discover` and takes only `signal` and `how_to_surface`
from the model when the id matches. Ids and weights always come from the
catalog, so invented items vanish silently. `pass_condition` is generated text
naming the archetype's verdict and the 0.70 bar.

## `_build_resume_claims`

Caps at 6, skips entries without a `claim`, and coerces out-of-enum
`truthfulness` to `"true"`.

## Fingerprints

`seed_fingerprint` covers seed, archetype, `CATALOG_VERSION`, `PERSONA_VERSION`,
traits, verdict — stable across re-casts. `fingerprint` adds name,
`presented_gender`, background, per-skill levels and stances, and the compiled
system prompt — moves whenever content changes. See
[the determinism split](/concepts/determinism.md#the-two-fingerprints).

## `presented_gender` — model-authored, code-validated (v1.3)

Read off the draft in step 4 as
`normalize_presented_gender(draft.get("presented_gender"))` and passed to
`build_engine_contract`, which uses it to pick the persona's voice **only when
there is no `human_traits`** — the code-owned trait wins where it exists. It is
also stored on the `VirtualCandidate`, so a persona explains the voice it speaks
in. Reading it inside `generate` is what kept both `control_plane/api.py` cast
sites signature-stable and the agent free of any new dependency.

## Gotchas

* Falsy model output falls back to archetype text: `"Unnamed Candidate"`, `archetype.label`, `archetype.description`, `"Hi, thanks for having me."`, `"Never opens up further."`. An empty string in a draft becomes a plausible-looking default rather than an error.
* `years_experience` is clamped to 0–40 and defaults to 0.
* `SpeechProfile(**archetype.speech, ...)` and `AnswerPolicy(**archetype.answer_policy, ...)` splat the TypedDicts — adding a key to either spec changes both the archetype definitions and these constructor calls.
* Because `candidate_id` derives from the seed, a re-cast **reuses the same id**, which is what makes the storage upsert idempotent. Passing `seed_prefix` changes the id.
* `expectation` is typed `Any` and only reaches `expectation_note()`; enrollment works without one.
* `candidate_notes` reaches the model **once**, inside the casting prompt, and is then discarded — nothing downstream reads it, so the persona document is the only thing that survives the cast. The structural guarantees are re-enforced in code after the model returns, which is what makes a hostile note safe.
