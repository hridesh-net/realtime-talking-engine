---
type: Reference
title: Report engine scoring specification
description: The research-backed deterministic scoring design the report engine implements, and the provenance of every threshold in it.
resource: /docs/REPORT_ENGINE_SCORING_SPEC.md
tags: [reference, report, scoring, determinism, research]
generated:
  by: claude-opus-5
  at: "2026-08-26T00:00:00Z"
status: stable
sources:
  - resource: /docs/REPORT_ENGINE_SCORING_SPEC.md
---
# Report engine scoring specification

756 lines, `docs/REPORT_ENGINE_SCORING_SPEC.md`. The design document for
[`report_engine/`](/concepts/subsystems/report-engine.md). Read it before
changing any threshold, because the numbers are not arbitrary and several of
them contradict the obvious intuition.

## Why it exists separately from the code

Every threshold carries one of two tags, and the distinction is the point:

* **`SOURCED`** — from published research or a named industry dataset, cited inline.
* **`CALIBRATION`** — the *metric* is research-backed, the *cut point* is not.
  It ships as versioned configuration with an engineering-judgment starting
  value.

Most cut points are `CALIBRATION`. A manager who disputes their score is owed a
straight answer about which is which, and that answer cannot live in a comment.

## The findings that shaped the design

| Finding | Consequence in code |
|---|---|
| Structured interviews validate at **r = .42** vs ~.19 unstructured (Sackett et al. 2022) — now the best single predictor, ahead of GMA at .31 | Structure carries the heaviest rubric weight |
| Huffcutt & Arthur (1994): validity runs .20 → .35 → .56 → **.57** across structure levels — the last step is +.01 | Probing is never penalised; banning follow-ups buys nothing |
| Kluger & DeNisi (1996): feedback averages d = .41 but **over a third of interventions made performance worse**, the split being task-focus vs person-focus | `coach.py` names a behaviour and a sentence to say instead, never a trait; at most 3 development areas |
| Filled-pause rate **rises** with proficiency (C1 8.6/min vs A2 3.1/min) and does not discriminate level (r = −.08 n.s.) | Fillers are measured and never scored — the folk "um counter" measures a habit |
| Juncture-pause proportion is the strongest CEFR predictor at **r = .84**, stronger than speech rate | The English module needs word-level timings, hence the recording |
| No peer-reviewed optimal interviewer:candidate talk ratio exists for selection interviews | Talk-share bands are tagged `CALIBRATION` from Gong/BrightHire industry proxies, and say so |
| The four-fifths rule compares selection *rates across applicant groups* | Adverse impact is absent per session; it is a cohort metric only |

## Decisions recorded in section 11

The English weighting toggle, the language gate, sourcing word timings from the
browser's stereo recording rather than the Go engine, measuring intelligibility
alongside CEFR, and BRD **D-8** resolved: reports are reviewed by mentors and
trainers, which makes provenance stamping and quote anchoring mandatory rather
than nice-to-have.

## Related

[Report engine](/concepts/subsystems/report-engine.md) ·
[BRD v3](/references/brd.md) ·
[Determinism split](/concepts/determinism.md)
