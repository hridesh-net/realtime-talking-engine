---
type: Subsystem
title: Report engine
description: The standalone manager-assessment report engine — one session bundle in, one deterministic report out, no database and no sibling imports.
resource: /report_engine
tags: [report, evaluation, manager-assessment, deterministic, signals, standalone]
generated:
  by: claude-opus-5
  at: "2026-08-26T00:00:00Z"
verified:
  - by: claude-opus-5
    at: "2026-08-26T00:00:00Z"
status: draft
sources:
  - resource: /report_engine/score.py
  - resource: /report_engine/acts.py
  - resource: /report_engine/signals
  - resource: /report_engine/schema.py
  - resource: /docs/REPORT_ENGINE_SCORING_SPEC.md
---
# Report engine

`report_engine/` — turns one completed session into a manager development
report. **The specification lives in
[`docs/REPORT_ENGINE_SCORING_SPEC.md`](/references/report-engine-spec.md)**; this
page is the routing card for the code.

`status: draft` because phases 1–5 of the spec's build order are built (the
complete deterministic report) and phases 6–7 are not: no judge pass, and no
audio-derived English module.

## Why it imports nothing first-party

`ALLOWED_IMPORTS["report_engine"] = set()`. It is the only package in the repo
that depends on no other, and that is deliberate: **the rubric travels in the
input bundle** rather than being imported from `evaluation_agent`.

Sibling agent packages may not import each other, so the alternative was a
second copy of the rubric policed by a drift test — the repo already pays that
price once, in `test_rubric_vocabulary_agrees_across_the_two_agents`. Passing
the rubric as data costs nothing, keeps it org-owned configuration, and is what
makes "standalone" literally true: `python -m report_engine bundle.json` reads a
file and writes a report, touching no database and no network.

`scripts/make_bundle.py` is the piece that *does* import the sibling packages,
assembling a bundle from `control_plane.db`, from a plain turn list, or from the
worked example in `tests/fixtures/demo_turns.json`.

## The determinism split, restated

Code owns every count, ratio, threshold comparison, sub-score, criterion score
and the readiness index; segmentation; question-act extraction and typing;
confidence downgrades; and the recommended next persona. Re-running on a stored
session must produce byte-identical output — `tests/test_report_engine.py`
asserts it on both the JSON and the HTML.

Nothing here calls a model today. When the judge lands (spec phase 6) it will
own reasoning prose and quote selection only, and code will veto any claim whose
evidence span is not found verbatim in the transcript.

## The pipeline

```
bundle -> language gate -> question acts -> segments -> signals -> scores -> render
```

| Module | Owns |
|---|---|
| `schema.py` | `SessionBundle` in, `AssessmentReport` out |
| `language.py` | the BRD D-6 gate — always detects, optionally refuses |
| `acts.py` | the **question act**, the unit of analysis, and its type |
| `segment.py` | OPEN / ASSESS / CANDIDATE_Q / CLOSE |
| `signals/` | one module per rubric criterion |
| `transfer.py` | the only place a raw measurement becomes a score |
| `score.py` | aggregation, confidence, findings, next practice |
| `coach.py` | the behaviour-level line and the sentence to say instead |
| `render.py` | JSON and a self-contained HTML page |
| `packs/` | dated jurisdiction and competency packs |

## Three rules the tests enforce

* **An unmeasurable signal is never a zero.** It carries `value=None` and a
  reason. A fake zero penalises a manager for the modality they were given.
* **Positive-only markers never penalise absence.** Offering an adjustment or
  checking name pronunciation earns points; not doing so costs none, because no
  effect-size research supports a penalty.
* **Nothing caps or fails.** A protected-topic hit lowers Fair & Inclusive and
  raises a flag; it does not touch the other criteria or the index. This is the
  same standing rule `test_the_rubric_has_no_critical_fail_gate` guards.

## The two operator toggles

`scoring_options.english_weight` (null = advisory panel; a float adds a fifth
criterion and scales the rubric's four by `1 − w`) and
`scoring_options.language_gate`. **Both break comparability**, so both are
stamped on `Provenance` and any cohort view must segment on them rather than
average across settings.

## Related

[Evaluation agent](/concepts/subsystems/evaluation-agent.md) ·
[evaluation_agent/rubric.py](/concepts/modules/evaluation-agent-rubric.md) ·
[Session transcript](/concepts/contracts/session-transcript.md) ·
[Session recording](/concepts/contracts/session-recording.md) ·
[Determinism split](/concepts/determinism.md)
