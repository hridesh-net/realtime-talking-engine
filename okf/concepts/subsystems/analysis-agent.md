---
type: Subsystem
title: Audio analysis agent
description: Listens to a session's recording against the expectation it was held against, and returns structured observations — not a report.
resource: /analysis_agent
tags: [analysis, audio, multimodal, persona, manager-assessment]
generated:
  by: claude-opus-5
  at: "2026-08-26T00:00:00Z"
verified:
  - by: claude-opus-5
    at: "2026-08-26T00:00:00Z"
status: draft
sources:
  - resource: /analysis_agent/INSTRUCTIONS.md
  - resource: /analysis_agent/agent.py
  - resource: /analysis_agent/harness.py
  - resource: /analysis_agent/audio.py
---
# Audio analysis agent

`analysis_agent/` — one session's **recording** in, one `SessionAnalysis` out.
It builds no report, persists nothing and computes no final score: the
[report engine](/concepts/subsystems/report-engine.md) composes from what this
returns, and human trainers read that.

`status: draft` because it is wired end to end and running against production
recordings, but has been exercised on a handful of sessions rather than a cohort.

## Why the audio and not the transcript

The stored transcript comes from the live realtime STT and is **materially wrong
on code-mixed speech**. On one real session it rendered *"May I know what's your
background?"* as *"May I introduce myself?"* — a different interview behaviour
entirely, which the report would then have credited — and turned a Hindi
question into Urdu script that matched no English pattern at all.

The consequence downstream was worse than a bad transcript. That session
contained questions about household composition and salary history, asked in
Hindi, and the counted fairness detector scored it **10/10, "no protected topics
detected"**. Reading the audio is what closes that hole.

## `INSTRUCTIONS.md` is the specification

The agent's operating rules live in
[`analysis_agent/INSTRUCTIONS.md`](/references/analysis-instructions.md),
versioned and shipped as package data, read at runtime rather than embedded in a
string literal — so the rules every report rests on are reviewable as prose and
a change to them shows up in a diff as prose.

**Changing that file changes what every report is built from.** It carries
`ANALYSIS_INSTRUCTIONS_VERSION`, which is stamped onto every stored analysis;
two analyses are only comparable when it matches.

## The weighting: 60% persona, 40% coverage

The dominant half of the judgement is **how the manager handled the person in
front of them**, not how much of the plan they got through. The expectation is
written before anyone speaks; the interview is a conversation with a specific
candidate.

The case that forces it: a manager who reads a disengaged or plainly unsuited
candidate in the first minutes and closes politely and early **has done the
right thing**, and will have covered almost none of the expectation. Scoring
coverage first marks that down as a failure when it is the correct call.

So coverage is scored against **reachable** items — an item is not a gap if the
interview was rightly closed before it arose, or the candidate had already made
it moot — and `EarlyEndAssessment` separates a *judged close* (evidence
gathered, fair chance given, civil exit) from an *abandoned interview*. The test
is not duration; it is whether there was evidence before the decision.

The weights live in `schema.py` and are applied in `harness.py`. **The model
assesses each half separately and never sees them.**

## The harness exists for two reasons, and the second is the surprising one

Windowing handles recordings too long for one request. It also fixes a defect
that only shows up on real audio: **un-windowed, the model returned 21 of 53
turns ending after the recording did**, the furthest at 9m06s on a 5m46s file. A
model loses track of elapsed time over long audio and confabulates the clock.

Four-minute windows with code applying the offsets bring anchors back in range.
Two details carry the fix:

* Anchors are validated against **the window they came from**, not merely the
  whole recording — a late window's overshoot otherwise hides under the earlier
  windows' headroom, which is exactly how a 352 s timestamp survived a 346 s
  recording.
* Rejected anchors are counted into `dropped_anchors` and surfaced on the
  report, never silently discarded. A model that confabulates timestamps is
  something the operator should be able to see.

Windows run concurrently, so a twenty-minute interview costs about the same
wall-clock as a six-minute one — roughly a minute either way.

## What the model may not do

Set out in full in `INSTRUCTIONS.md` §8, but the load-bearing ones: never
produce a final score, band or hiring recommendation; never assess the
candidate; never infer caste, religion, region or age from a name, accent or
voice; and **never rate warmth or confidence as a score** — acoustic emotion
inference is unreliable and culturally biased, and this is Indian-English
frontline speech. Tone is described with anchors and left for a human to read.

## It needs ffmpeg on PATH, and nothing else in the repo does

`analysis_agent/audio.py` shells out to **`ffprobe`** for a recording's duration
and **`ffmpeg`** to cut it into windows and write each as WAV. They are
subprocesses, not a vendor SDK, which is why they live here rather than behind
the `llm/` boundary — but they are still a hard runtime dependency, and the only
one in this repository that is not a Python package.

The failure is narrow and therefore easy to miss: the control plane starts fine,
serves the console fine, and generates reports fine. Only **Analyse** fails, with

```
AudioError: ffmpeg/ffprobe not found on PATH
```

That is exactly how it reached production on 2026-08-27 — the deploy that first
shipped `analysis_agent/` to the instance did not ship the binary it shells out
to, because `infra/` had been written before this package existed and nothing
named the dependency. Amazon Linux 2023 has no ffmpeg package at all, so
`infra/terraform/templates/bootstrap.sh.tftpl` now installs the static build
alongside Caddy, for the same reason and with the same shape.

**Codec requirement, not just presence.** The browser recorder produces WebM
with Opus, so an ffmpeg build without the `matroska,webm` demuxer or the `opus`
decoder satisfies `shutil.which` and then fails on the first real recording.
Check the decoders, not just the binary.

## Related

[Report engine](/concepts/subsystems/report-engine.md) ·
[Session recording](/concepts/contracts/session-recording.md) ·
[LLM port](/concepts/subsystems/llm-port.md) — the `AudioModel` port ·
[What a session costs](/references/pricing.md) ·
[Determinism split](/concepts/determinism.md)
