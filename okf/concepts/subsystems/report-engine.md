---
type: Subsystem
title: Report engine
description: The standalone manager-assessment report engine — one session bundle in, one deterministic report out, no database and no sibling imports.
resource: /report_engine
tags: [report, evaluation, manager-assessment, deterministic, signals, standalone]
generated:
  by: claude-opus-5
  at: "2026-08-27T00:00:00Z"
verified:
  - by: claude-opus-5
    at: "2026-08-27T00:00:00Z"
status: draft
sources:
  - resource: /report_engine/score.py
  - resource: /report_engine/judge.py
  - resource: /report_engine/validate.py
  - resource: /report_engine/narrate.py
  - resource: /report_engine/render.py
  - resource: /report_engine/acts.py
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

`status: draft` because phases 1–6 of the spec's build order are built and
phase 7 is not: there is no audio-derived English module. Phase 6, the judge,
landed 2026-08-27 — see [Determinism split](/concepts/determinism.md) for what
it is and is not allowed to author.

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

## What the reader gets

**The section list is the hiring manager's, not the engine's.** She named five
things and the default render is exactly those, in this order:

1. **Competency scorecard** — the four rubric criteria at `x/4` with a weight, a
   narrative and up to three plain-language bullets each.
2. **Q&A** — every question she asked, with its time, verbatim, and one tag.
3. **BEI questions** — the behavioural ones asked, and the ones that came out as
   hypotheticals instead.
4. **Strengths & gaps** — two columns, each item quoted.
5. **Areas to improve** — numbered, each with the sentence to say instead.

**The readiness index and the summary paragraph are not on her pages.** Both are
still computed, stored and stamped exactly as before — spec section 9's
comparability rules depend on the index existing — and both are printed in the
working, where a trainer reviewing the session will look. She asked for the four
competencies rather than one number rolled up from them, and a headline score
nobody asked for is a headline score that gets argued about.

Signal tables, the bias check, the basis panel and that overview are the
**working**, off by default: `to_html(report, detail=True)`, or `?detail=1` on
the HTML endpoint.

That is a reversal, and it is worth saying why. The previous default opened with
*How this report was produced* and ran six pages, most of them tables; a hiring
manager called it difficult to read, which it was. The working did not become
less true, it became a second click. What stays on the page unconditionally is
the footer's basis line — how many signals were counted, heard and judged — for
the reason in the next section.

**The question acts are rendered once.** The working's old five-column question
table is gone: the report itself now lists every question, and two renderings of
the same acts would be two places for one fact to be wrong in. The Q&A list also
translates the classifier's vocabulary — nobody being coached should have to
know what `double_barrelled` means to read their own report, so it prints as
*two questions in one*, and `situational` prints as *hypothetical*.

**BEI needs no new signal.** `behavioural` and `situational` are two of the six
types `acts.classify` already assigns, so the section is a view over the same
data the score uses, never a second opinion about it.

Scores are computed on the 0–10 scale the spec calibrated and *displayed* out of
four. Rescaling the numbers rather than their display would mean re-deriving
every threshold against a scale no study used.

## Three kinds of signal, and it says which on every row

**Counted** (`source="measured"`) signals are computed from the stored transcript
by code and are reproducible. **Heard** (`assessed`) signals come from the
[audio analysis](/concepts/subsystems/analysis-agent.md) and rest on a model's
reading of the recording. **Judged** signals come from the report judge reading
the transcript, and every claim under one carries a span matched word for word.

The distinction is not cosmetic. On a real session the counted fairness detector
returned **10/10, "no protected topics detected"**, on an interview containing
questions about household composition and salary history — asked in Hindi, which
an English lexicon cannot match. The heard signals brought that criterion to
6.24. The language downgrade deliberately does not weaken heard signals: they
read the language actually spoken.

Every report carries a **basis panel** stating how many signals were counted
versus heard, which model and instruction version produced the analysis, the
languages heard, and how many anchors were discarded. A trainer acting on a
number is owed that in the reader's language. The panel itself moved behind
`detail`; a one-line version of it did not, and is printed in the footer of every
report — the 10/10 above is exactly why a reader must never have to opt in to
learning which half of a number was heard.

## The determinism split, restated

Code owns every count, ratio, threshold comparison, sub-score, criterion score
and the readiness index; segmentation; question-act extraction and typing;
confidence downgrades; and the recommended next persona. Re-running on a stored
session **with no judge** must produce byte-identical output —
`tests/test_report_engine.py` asserts it on both the JSON and the HTML, and that
is still the regression harness.

The judge owns prose and quote selection only. Code vetoes any claim whose
evidence span is not in the transcript verbatim, refuses a `surfaced` verdict
credited to the manager's own words, and rejects prose stating a number — the
numbers are computed here and printed beside the sentence, so a judge free to
write them too could contradict them. A vetoed claim falls back to the sentence
`narrate.py` composed from the measurement, so a veto costs polish and never
costs a section. The full table is in
[Determinism split](/concepts/determinism.md).

## The pipeline

```
bundle -> language gate -> question acts -> segments -> signals -> scores
       -> narrate -> [judge -> validate -> rescore] -> render
```

The judge is a *decoration pass*, not a step inside `build_report`: the
deterministic report is built first and complete, then `judge.apply` overlays
what survives the veto. A `must_discover` verdict that survives becomes a
`discovery_surfaced` signal and the report is **rebuilt** through
`build_report(bundle, extra_signals=[...])` rather than patched, so every number
downstream of it is still derived in one place.

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
| `narrate.py` | the sentences code composes from the measurements alone |
| `judge.py` | the one model call — spec section 6 |
| `validate.py` | the veto: verbatim spans, who spoke, no numbers in prose |
| `render.py` | JSON and a self-contained HTML page |
| `packs/` | dated jurisdiction and competency packs |

`scripts/transcribe_recording.py` turns a stereo recording into a turn list.
Each channel is transcribed separately, so speaker labels are exact rather than
a diarisation guess — the payoff of `manager_left_candidate_right`.

## Three rules the tests enforce

* **An unmeasurable signal is never a zero.** It carries `value=None` and a
  reason. A fake zero penalises a manager for the modality they were given.
* **Positive-only markers never penalise absence.** Offering an adjustment or
  checking name pronunciation earns points; not doing so costs none, because no
  effect-size research supports a penalty.
* **A restraint item is not scored like a question.** Some `must_discover`
  signals are "do not ask" (`cooperative_trap`'s heaviest is *"Move back to the
  role without asking a single follow-up"*). Counting those by question-overlap
  inverts the measurement, so they are excluded and left to the judge.
* **Some signals are reported and never scored.** Pace and fillers, by
  specification; promotion/prevention framing, because one session cannot
  distinguish differential framing from a single risk-framed question.
* **Question detection does not trust the question mark.** On a voice session
  the punctuation is the transcriber's guess.
* **Nothing caps or fails.** A protected-topic hit lowers Fair & Inclusive and
  raises a flag; it does not touch the other criteria or the index. This is the
  same standing rule `test_the_rubric_has_no_critical_fail_gate` guards.

## Configurable perspective and skills

`ReportConfig` carries two org-owned settings. **Perspective**
(`manager`/`coach`/`reviewer`) changes the person a finding is written in and
never how hard it lands — Kluger & DeNisi's task-versus-self split is what makes
the second person safe, and the coaching lines are already written about the
question rather than the person. **Skills** replace the shipped role-family
competency pack, which is only a stand-in for the job-analysis-based content
that is the first of Campion, Palmer & Campion's fifteen structure components.

## The two operator toggles

`scoring_options.english_weight` (null = advisory panel; a float adds a fifth
criterion and scales the rubric's four by `1 − w`) and
`scoring_options.language_gate`. **Both break comparability**, so both are
stamped on `Provenance` and any cohort view must segment on them rather than
average across settings.

## Why the judge does not break "imports nothing"

Spec section 10 wrote `ALLOWED_IMPORTS["report_engine"] = {"llm"}` because the
judge needs a model. The code kept `set()`. The model arrives instead as a
**structural type** — `judge.JudgeModel` is a `Protocol` with one method, and
`llm.base.StructuredModel` satisfies it without either package knowing about the
other. `control_plane/reporting.py`, which already imports both, does the wiring.

The consequence, stated plainly: **the CLI cannot run the judge.** It has no way
to build a model, so `python -m report_engine bundle.json` is always the
deterministic report. That is the price of the standalone property, and it is
also what keeps the offline path honest — the thing the regression suite runs is
the thing the CLI runs.

## Related

[Evaluation agent](/concepts/subsystems/evaluation-agent.md) ·
[evaluation_agent/rubric.py](/concepts/modules/evaluation-agent-rubric.md) ·
[Session transcript](/concepts/contracts/session-transcript.md) ·
[Session recording](/concepts/contracts/session-recording.md) ·
[Determinism split](/concepts/determinism.md)
