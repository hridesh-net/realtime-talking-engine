---
type: Reference
title: Analysis agent instructions
description: The shipped, versioned rules the audio analysis agent works under — the document every report is ultimately built from.
resource: /analysis_agent/INSTRUCTIONS.md
tags: [reference, analysis, instructions, rules]
generated:
  by: claude-opus-5
  at: "2026-08-26T00:00:00Z"
status: stable
sources:
  - resource: /analysis_agent/INSTRUCTIONS.md
---
# Analysis agent instructions

345 lines, `analysis_agent/INSTRUCTIONS.md`, version `v1.1`. Read at runtime and
shipped as package data — this is code's input, not documentation about it.

## Why it is a document

Every report is built from what the analysis observed, and what the analysis
observes is decided here. Keeping the rules as prose in a file means a change to
them arrives as a reviewable diff of sentences rather than as an edited f-string
buried in a prompt builder.

## The rules are tests, not descriptions

Each observation type carries a decision procedure. A sample, to show the shape:

| Rule | The test |
|---|---|
| Requirement vs protected topic | **The subject of the sentence.** "Can you work rotational shifts?" is a requirement question. "Will your family allow rotational shifts?" is a protected-topic question about the same requirement. |
| Surfaced | Both halves required: the manager **asked**, and the candidate **revealed**. A detail the candidate volunteered unasked is `volunteered`, not `surfaced`. |
| Restraint items | Where `how_to_surface` says *not* to ask, surfaced means the manager **refrained**. Read the instruction before deciding which kind you are looking at. |
| Behavioural question | A specific past event the candidate personally experienced. "How do you handle X" is **not** behavioural. |
| Interruption | Manager speech cutting across the candidate. Backchannels — "hmm", "haan", "okay" — are explicitly not interruptions. |
| Gap | Only if the item was **reachable**: time remained and the candidate was engaged enough to answer. |

## Three instincts it overrides

1. **Saying little is not doing well.** A manager who barely spoke asked no bad
   questions and made no bad framings; where a criterion has no positive
   evidence, rate low rather than rewarding the absence of failure.
2. **Fluency is not competence.** A confident, well-spoken manager who never
   probed did not interview well.
3. **Ending early is not a failure by default.** See
   [the subsystem page](/concepts/subsystems/analysis-agent.md).

## Version

`ANALYSIS_INSTRUCTIONS_VERSION` in `analysis_agent/schema.py` must be bumped
whenever this file changes in a way that alters what the model is asked to do.
It is stamped onto every stored analysis and printed on every report.

## Related

[Audio analysis agent](/concepts/subsystems/analysis-agent.md) ·
[Report engine scoring specification](/references/report-engine-spec.md)
