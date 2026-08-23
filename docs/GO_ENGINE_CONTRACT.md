# Go engine contract — running a virtual candidate

> **Design note, not an implementation.** The interview-candidate engine is a
> separate Go build. This document specifies what the control plane hands it
> and what it must guarantee in return, so the persona format is right before
> the engine exists. No Go code lives in this repo.

How the Go **interview-candidate engine** consumes a persona cast by this
control plane. The engine plays the candidate; a **human interviewer** conducts
the session. Afterwards the transcript is graded against the persona's
scorecard to produce interviewer feedback.

## Flow

```
control plane (Python)                    interview-candidate engine (Go)
──────────────────────                    ───────────────────────────────
POST /interviews                  ──┐
POST /interviews/{id}/expectation   │  design time
POST /interviews/{id}/candidates  ──┘

                                          GET /candidates/{cid}/engine-contract
                                          → inject system_prompt into the
                                            realtime model, apply voice_directives
                                            and turn_policy, run the session

                                          GET /candidates/{cid}/scorecard
                                          → grade the transcript, emit the
                                            interviewer feedback report
```

The engine needs exactly two reads. It never parses the full persona document,
never sees the archetype key, and never re-derives prompt text.

## `GET /api/v1/candidates/{candidate_id}/engine-contract`

Schema: `owner_handover/engine_contract_schema.json`.
Sample: `owner_handover/engine_contract_sample.json`.
Generate Go structs from the schema, or hand-write them to match it.


**`contract_version`** — pin it. Reject a contract whose major version the
engine does not implement rather than running a persona you cannot honour.

**Now `v1.3`** (2026-08-25). The minor bump adds the fields the dual-model
runtime needs compiled at design time. All are optional — a v1.0–v1.2 contract
parses with them zero-valued and the engine degrades to the single-model path
rather than refusing to run.

| Field | Why the engine needs it |
|---|---|
| `precompiled_beliefs[]` | Seeds the claims ledger at turn 0: `{claim_id, skill, statement, elaborations, vague_deflections}`. The persona's false beliefs exist before the first question. Inventing one at runtime would void `seed_fingerprint`. |
| `stall_phrases[]` | Persona-voiced filler, synthesized at load, so a defer starts playing inside 50 ms while the reasoning model is still thinking. Drawn from this persona's own tics — a stall clip in another register is the seam the two-model design exists to hide. |
| `pregate_lexicon{}` | Per skill: `{aliases, defer_at_or_below}`. Matched incrementally against partial speech so the engine can start stalling before the question finishes. |
| `unlock_spec` | `{kind: never\|conditional, condition, hints}`. `never` short-circuits per-turn unlock assessment entirely — most personas never unlock and paying a reasoning call every turn to re-learn that is waste. |
| `tts_voice_id` | The voice stall clips are synthesized in. **Must equal the speech model's voice.** Empty means the engine resolves it with the same deterministic rule (`sha256(candidate_id) % len(voices)`). |

**Earlier minors** (both still apply):

**`v1.2`** (2026-08-24). Two minor bumps landed on separate branches and
each called itself `v1.1`; the merge is a third shape, so it takes its own
number rather than leaving two different prompts sharing one version string.

* `v1.1` added a language line at the top of `system_prompt`'s `HOW YOU TALK`
  section and a `language` key to `voice_directives`. A persona may speak
  Hinglish or Hindi, so anything the engine does with the transcript must not
  assume English.
* `v1.2` adds an optional realism layer to `system_prompt` for personas carrying
  a `human_traits` profile, and — for **every** persona, with or without one —
  moves `HARD RULES` to the end of the prompt. If the engine matches on prompt
  section order anywhere, that is the change to look at.

The engine needs no change for either: it parses by major version and retains
the minor, which `contract_test.go` already covers.

**`system_prompt`** — inject verbatim as the realtime model's system
instruction. It is compiled deterministically in Python from the persona
(`candidate_agent/engine_contract.py`); the same persona always produces the
same bytes. Do not edit, summarise, or append to it. Anything the engine needs
to add (session framing, audio config) goes in a separate turn.

**`opening_line`** — the candidate's first utterance, in their voice. Speak it
after the interviewer's greeting rather than letting the model improvise, so
every session starts in character.

**`voice_directives`** — audio-layer settings:

| Field | Use |
|---|---|
| `pace`, `target_pause_before_answer_ms` | Delay before the persona starts speaking |
| `verbosity`, `filler_frequency`, `hesitation_frequency` | 0–10 intensities for disfluency injection |
| `formality`, `tone` | Register |
| `may_interrupt` | Whether the persona may barge in on the interviewer |
| `self_correction_rate` | 0–1, derived from nervousness — mid-sentence restarts |
| `verbal_tics`, `sample_phrases` | Voice anchors for the realtime model |
| `language` | **v1.1.** `english_indian` \| `hinglish` \| `hindi`. Set the STT language hint from it — but send **no** hint for `hinglish`: no transcription model accepts a language *set* (verified against the live vendor API, 2026-08-22), and pinning either half mangles the other. |

**`turn_policy`** — turn-taking limits. `target_sentences_per_answer` always
sits inside `[min_sentences, max_sentences]`; enforce the bounds and treat the
target as the aim.

**`knowledge_ceiling`** — the hard part. `{"Go": 3, "system design": 1}` means
this persona may never demonstrate more than that level, no matter how the
interviewer asks. Realtime models drift helpful under pressure, so treat this as
a runtime guard, not a hint. Suggested enforcement:

1. Include it in the system prompt (already done — the `WHAT YOU ACTUALLY KNOW`
   section).
2. Re-assert it as a system item every N turns, or whenever the interviewer
   pushes on a low-ceiling skill.
3. Optionally post-check answers on low-ceiling skills before they are spoken.

A persona that answers above its ceiling invalidates the training session: the
interviewer gets credit for depth that was never supposed to be there.

**`unlock_condition`** — what the interviewer must do before the persona gives a
deeper answer. This is the whole point of `smart_but_lazy` and
`nervous_but_capable`. The engine should keep answers at
`turn_policy.default_answer_depth` until the condition is met, then allow depth
up to the ceiling. Whether the condition was met is itself a feedback signal —
log the turn where it flipped.

**`forbidden_behaviors`** — hard stops. Most important: the persona must never
break character, never evaluate the interviewer, and never disclose that a
scorecard exists. If the interviewer asks "are you an AI", stay in character.

## `GET /api/v1/candidates/{candidate_id}/scorecard`

The ground-truth answer key, used **after** the session. Never expose it to the
realtime model — a persona that knows what it is being probed for will lead the
interviewer to it.

```json
{
  "expected_verdict": "reject",
  "interviewer_challenge": "Reach a defensible no-hire backed by specific evidence...",
  "must_discover": [
    {"id": "depth_absent", "signal": "...", "weight": 0.35, "how_to_surface": "..."}
  ],
  "interviewer_failure_modes": ["Decides in the first five minutes and stops probing"],
  "pass_condition": "The interviewer surfaces signals totalling at least 0.70 weight..."
}
```

Grading, per session:

1. For each `must_discover` item, decide from the transcript whether the
   interviewer surfaced it. `how_to_surface` describes the probe that would
   have.
2. Sum the `weight` of surfaced items — `must_discover` weights always total
   `1.0`, so the sum is a 0–1 discovery score.
3. Compare the interviewer's recorded verdict against `expected_verdict`.
4. Check `interviewer_failure_modes` against what actually happened; each one
   that occurred is a concrete "what to improve" line.

`pass_condition` is the default bar: ≥ 0.70 discovery **and** the right verdict.
Both halves matter — the right verdict reached by luck is not a good interview,
and thorough probing that lands on the wrong call is not either.

## Session state the engine should record

For the feedback report to say anything useful, log per turn:

- speaker, text, timestamp
- which required skill the interviewer was probing
- whether the `unlock_condition` had been met at that point
- any answer the engine suppressed for exceeding a ceiling

## Determinism

`seed_fingerprint` is stable for a given `(interview_id, archetype)` — the same
person, every time, so two interviewers can be compared on the same candidate.
`fingerprint` covers the model-authored content as well and moves whenever the
persona is re-cast; use it to detect that a stored persona changed underneath a
training set.
