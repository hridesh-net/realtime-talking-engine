---
type: Subsystem
title: Live-session engine
description: Go engine that runs the live voice session — one brain, two parts, with the persona's mouth and its subconscious.
resource: /engine
tags: [engine, go, realtime, voice, session, dual-model]
generated:
  by: claude-opus-5
  at: "2026-08-21T21:40:00Z"
verified:
  - by: claude-opus-5
    at: "2026-08-23T18:00:00Z"
  - by: claude-opus-5
    at: "2026-08-21T21:40:00Z"
  - by: kimi-code/okf-curator
    at: "2026-08-22T21:10:00Z"
status: draft
sources:
  - resource: /docs/ENGINE_IMPLEMENTATION_PLAN.md
  - resource: /docs/GO_ENGINE_CONTRACT.md
  - resource: /docs/ENGINE_ONE_BRAIN_TWO_PARTS.html
  - resource: /engine/internal/ports
  - resource: /engine/internal/contract
  - resource: /engine/internal/arch
---
# Live-session engine

`engine/` — a Go module that runs the **live voice session**. It is the runtime
counterpart to everything else in this repo: the Python side decides *what* an
interview is, the engine performs it. Design and task breakdown live in
[the implementation plan](/docs/ENGINE_IMPLEMENTATION_PLAN.md); the payload it
consumes is specified in [the engine contract](/docs/GO_ENGINE_CONTRACT.md).

**Status: under construction — but a live interview now runs end to end.**

Working code: Phase 0 (skeleton, ports, contract types, config, fakes, layering
test, session manager), the Phase 1 turn loop (`session` — state table, timers,
playout tracker, barge-in, backpressure, turn records, sentence trim), the
deterministic pre-gate (`gate`), the claims ledger (`ledger`), the event log
(`obs`), the failable connector, the sample domain (`audio` — resampler, onset
detection, jitter buffer, send ring), the WebSocket/PCM transport
(`transport/wsfallback`), the stall bank (`stall`), and four vendor adapters:
`vendors/thinkerllm` and `vendors/judgellm` over the Gemini REST API (sharing
`vendors/shared/geminijson`), `vendors/gemini` over the Gemini **Live** API, and
`vendors/geminitts` for pre-synthesis.

Still `doc.go`-only placeholders: `record`, `store/s3`, `transcriptlog`,
`transport/webrtc`, `vendors/{openairt,openaitx,localasr}`, `controlplane`,
`judge`.

**What a live session does today**, verified against the real binary and the
real API: accepts a session, hands back a ticketed transport answer, connects
the Speaker, detects the interviewer's speech locally, ends their turn, plays a
pre-synthesized opening line in the contract's frozen voice, and returns to
LISTENING. Seven seconds of persona audio, captured off the wire.

**What it does not do yet.** There is no recording, no transcript artifact and
no S3 upload, so nothing is graded. `vendors/judgellm` is written and tested but
unwired — its verdicts reach `ceiling_flags` in M4. There is no Transcriber
adapter, so every session runs `degraded:asr` and end-of-turn comes from the
energy detector rather than from ASR. WebRTC does not exist; the WebSocket
transport is the fallback carrying the whole load, which means a lossy network
degrades into latency rather than into a glitch.

The Judge's offline fixture is worth reading correctly: its 25 labelled cases
run through the real adapter against **canned** model responses, so they pin the
HTTP envelope parsing, the JSON decode and verdict normalisation. They say
nothing about whether the model's judgement is any good. Measuring that needs a
live vendor call and is a separate, paid task.

## Live-verified vendor facts

These were measured against `gemini-3.1-flash-live-preview`, not read from
documentation, and several of them removed planned work.

* **Audio outside an activity window is discarded silently** — no bytes, no
  transcription, no error. A lost `activityStart` means the persona never hears
  the question and nothing downstream can tell, which is why the adapter opens
  the window itself on the first frame.
* **A bare `activityStart` is how a response is cancelled.** There is no cancel
  RPC. The server set `interrupted` 90 ms later, produced no further audio, and
  did not start a new response.
* **There is no client-side truncation API**, so `Truncate` returns
  `ErrTruncateUnsupported` and the recording's right channel stays the grading
  ground truth (D4).
* **A bracketed marker convention makes things worse.** Teaching the persona a
  `[[DIRECTION]]` marker caused it to fabricate its own marker spans — four
  turns out of four with the marker, none without — and those spans reached the
  transcript while never reaching the audio. A plain parenthetical note is
  obeyed, unspoken, and leaves the transcript faithful. **Never teach the
  compiled prompt a marker convention.**
* **A turn can complete with a full transcript and zero audio.** Observed once
  in twelve connections: the persona silent while the transcript said it spoke.
  The adapter reports it as `SpeakerError{Code:"silent_turn"}`.
* **The connection is not the session.** The API caps a connection at around ten
  minutes and sends GoAway before cutting it, while an interview runs 45–60, so
  resumption and context compression are not optimisations — they are the only
  way one logical session spans the interview (D5).

Note the directory is `vendors`, plural. Go reserves any directory named
`vendor` — a package beneath one cannot be imported by path at all — so the
Phase 0 layout had to be renamed. The reason now lives in
`internal/arch/graph.go` beside the rule that depends on it.

## The inversion that shapes everything

In this product the **AI plays the candidate and a human interviewer practises
against it**. That is the reverse of a normal voice-AI interview product, and it
inverts the timing budget: an interviewer's question runs 5–15 seconds where a
candidate's answer runs 30–90. The reasoning model therefore has roughly a fifth
of the thinking window the usual "think while the user talks" design assumes.

The persona's own contract supplies the compensation — `target_pause_before_answer_ms`,
`hesitation_frequency`, `filler_frequency` — because a candidate pausing before
answering is in character, not a stall. See
[determinism](/concepts/determinism.md) for why that material is compiled in
Python rather than invented at runtime.

## One brain, two parts

| Part | Role |
|---|---|
| **Speaker** | The mouth and the fast front brain. A realtime speech-to-speech model that always owns the voice; it is never replaced as the speaker. |
| **Thinker** | The subconscious. A reasoning model that holds who this person actually is, runs speculatively and continuously, and is consulted when the Speaker is unsure what it may say. |

[`docs/ENGINE_ONE_BRAIN_TWO_PARTS.html`](/docs/ENGINE_ONE_BRAIN_TWO_PARTS.html) draws
the mechanism: the anatomy, a millisecond timeline of both the confident and the
deferring turn, and what the shared ledger prevents. Open it in a browser.

These are two parts of **one** brain, not two agents — which is why they share a
per-session claims ledger. Without it the persona is *randomly* wrong across
turns, where a real weak candidate is *consistently* wrong. That distinction
matters because "did the candidate contradict themselves" is a signal the
interviewer is being trained to detect.

The Thinker is a **persona oracle, not a knowledge oracle**: asked what to say,
it answers "what would this person say", never "what is correct". For a weak
persona the right output is a vague or confidently wrong answer.

## Layering

Enforced by `go test ./internal/arch`, mirroring
[the Python architecture rules](/concepts/architecture.md):

```
vendors / transports / stores  →  ports  ←  session core
                       only cmd/engined wires concrete adapters
```

* `internal/ports` imports no other internal package.
* `internal/session`, `ledger`, `gate`, `stall` import only `ports`, `contract`, `obs`.
  The check matches by prefix, so a future subpackage is restricted too — it used
  to compare for exact equality, which would have let `internal/session/foo` slip
  the rule silently.
* Nothing outside `cmd/engined` imports a vendor, transport or store adapter.
  One carve-out, deliberately narrow: a package under `internal/vendors/` may
  import `internal/vendors/shared/`, where wire plumbing common to several
  adapters lives. Sibling-to-sibling imports stay forbidden, because "any vendor
  may import any vendor" would legalise a Speaker adapter reaching into a
  reasoning-model adapter — the exact coupling the rule exists to prevent.
* Adapters under `vendors/`, `transport/` and `store/` import only `ports`,
  `config`, `obs`, `audio` and `vendors/shared` **among internal packages**;
  third-party and stdlib imports are unrestricted, since these are the packages
  that exist to speak to the outside world.
* `os.Getenv` / `os.LookupEnv` appear only in `internal/config` — the Go mirror of
  "agents never read API keys".
* No vendor model-id string literals outside `internal/config` — model IDs are config.
* `internal/session` never calls `time.Now`, `time.After` or `time.NewTimer` —
  in tests too. The `Clock` port is injected, or turn-timing tests are
  permanently flaky.

## Alarms

Six timer kinds, all of them now armed somewhere in production code. Three were
not: `timerSilence` and `timerSession` were declared and never armed, so §11's
abandonment behaviour and the hard duration cap did not exist, and `timerStall`
was dead three ways over — never armed, no handler, present only in `String()`.
It has been deleted rather than fixed, since `timerThinker` already does its
documented job.

`timerPlayout` replaced it, and exists for a specific reason: the opening line
and the stall clips are **pre-synthesized audio, not vendor responses**, so no
`ResponseDone` will ever arrive for them — and `ResponseDone` is SPEAKING's only
legal exit. Without it the greeting was a dead end that ended every real session
before it began. It is turn-scoped, so a barge-in cancels it.

The two session-scoped caps read zero as *not armed*, never as *fire
immediately*: zero is what an unset config value looks like, and the other
reading ends every session on its first tick.

## Which interruption flag

`turn_policy.barge_in_allowed` is whether the **human** may interrupt the
persona. `voice_directives.may_interrupt` is the reverse — the persona's licence
to talk over the human — and is passed through to the vendor in `SessionCfg`.

They are easy to conflate from the names, and the actor did conflate them for
the whole of Phase 1, gating barge-in on `may_interrupt` while `barge_in_allowed`
was read nowhere in the module. The test helper now sets the two to **opposite**
values deliberately, so code reaching for the wrong one fails immediately rather
than passing by coincidence.

## Contract versioning

`internal/contract` pins the **major** version and rejects anything else, per
[the engine contract spec](/docs/GO_ENGINE_CONTRACT.md). It also retains the
**minor**, because minor bumps are additive and therefore accepted — meaning a
newer contract can reach an older engine and have its new fields silently
dropped by the decoder. Features gated on a later minor call `RequireMinor` so a
version skew fails loudly. v1.1 is taken by the M1 language line, an additive
prompt change the engine needed no edit for (its own `contract_test.go` covers
the case).

The current version is **v1.3** (`ENGINE_CONTRACT_VERSION` in
`candidate_agent/schema.py`). It carries the five dual-model runtime fields —
`precompiled_beliefs`, `stall_phrases`, `pregate_lexicon`, `unlock_spec` and
`tts_voice_id`. All five are optional, so a v1.0–v1.2 contract still parses and
the engine degrades to the single-model path rather than refusing to open an
interview; `engine_contract_sample_v1_0.json` is kept as a real old contract to
test exactly that, rather than a v1.3 sample with its version string overwritten.

Optional does not mean harmless to omit. A contract that reaches the engine
without those fields seeds an empty pre-gate lexicon, zero precompiled beliefs
and no stall phrases — so DEFER can never fire, and the persona invents its false
beliefs at runtime, which is the precise non-determinism they exist to remove.
Both sample contracts sat at v1.0 long after the schema moved to v1.3 for this
reason, and nothing in `check.sh` could see it; `scripts/export_engine_contract_sample.py`
regenerates them from the real compiler and `export_schemas.py --check` now fails
if the version or any of the five fields drifts.

## Checks

`scripts/check.sh` runs gofmt, vet, build, `go test -race`, the layering test and
golangci-lint against `.golangci.yml`, all from inside the module. Vendor tests
are tagged `//go:build live` and run only under `--live`, matching the Python
convention that model calls cost money. See [checks](/concepts/runbooks/checks.md).
