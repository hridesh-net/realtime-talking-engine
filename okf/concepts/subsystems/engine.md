---
type: Subsystem
title: Live-session engine
description: Go engine that runs the live voice session — one brain, two parts, with the persona's mouth and its subconscious.
resource: /engine
tags: [engine, go, realtime, voice, session, dual-model]
generated:
  by: claude-fable-5-1
  at: "2026-09-12T23:00:00Z"
verified:
  - by: claude-fable-5-1
    at: "2026-09-12T23:00:00Z"
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
  - resource: /docs/LIVE_TALKING_ENGINE_HARNESS.drawio
  - resource: /engine/internal/ports
  - resource: /engine/internal/contract
  - resource: /engine/internal/arch
---
# Live-session engine

`engine/` — a Go module that runs the **live voice session**. It is the runtime
counterpart to everything else in this repo: the Python side decides *what* an
interview is, the engine performs it. Design and task breakdown live in
the implementation plan (`docs/ENGINE_IMPLEMENTATION_PLAN.md`); the payload it
consumes is specified in the engine contract (`docs/GO_ENGINE_CONTRACT.md`).

**Status: under construction — but a live interview now runs end to end.**

Working code: Phase 0 (skeleton, ports, contract types, config, fakes, layering
test, session manager), the Phase 1 turn loop (`session` — state table, timers,
playout tracker, barge-in, backpressure, turn records, sentence trim), the
deterministic pre-gate (`gate`), the claims ledger (`ledger`), the event log
(`obs`), the failable connector, the sample domain (`audio` — resampler, onset
detection, jitter buffer, send ring), the WebSocket/PCM transport
(`transport/wsfallback`), the stall bank (`stall`), the actor-owned
[harness context](#the-harness-context-and-the-two-windows), and five vendor
adapters: `vendors/thinkerllm` and `vendors/judgellm` over the Gemini REST API
(sharing `vendors/shared/geminijson`), `vendors/gemini` over the Gemini **Live**
API, `vendors/geminitts` for pre-synthesis, and `vendors/openaitx`, the
independent Transcriber over the OpenAI Realtime transcription session.

`controlplane` is real too: the HTTP `ContractSource` that fetches each
persona and reports each finished session — see
[the control plane seam](#the-control-plane-seam) below.

Still `doc.go`-only placeholders: `record`, `store/s3`, `transcriptlog`,
`transport/webrtc`, `vendors/{openairt,localasr}`, `judge`.

**What a live session does today**, verified against the real binary and the
real API: accepts a session, hands back a ticketed transport answer, connects
the Speaker, detects the interviewer's speech locally, ends their turn, plays a
pre-synthesized opening line in the contract's frozen voice, and returns to
LISTENING. Seven seconds of persona audio, captured off the wire.

**What it does not do yet.** There is no recording adapter, no transcript
artifact and no S3 upload, so nothing is graded: the actor now writes both
channels and the barge-in truncation to the `Recorder` port, but `engined`
constructs none. `vendors/judgellm` is written and tested but unwired — its
verdicts reach `ceiling_flags` in M4. A session runs `degraded:asr` only when
`ASR_MODEL_ID` or `OPENAI_API_KEY` is unset or the ASR stream fails after
connect; on that path end-of-turn comes from the energy detector and the Speaker's
own input transcript is the human text — fed live to the pre-gate and the
Thinker like ASR partials, so the two-brain path works there too, only with a
cruder boundary. WebRTC does not exist; the WebSocket transport is
the fallback carrying the whole load, which means a lossy network degrades into
latency rather than into a glitch. **Not yet done end to end**: `engined` has not
been run with ASR configured against a browser; the adapter and the actor seams
are verified separately (live vendor test, offline session tests). The stall
grace and the confident-path note window have not been heard live either — the
bounds are reasoned, not measured.

The Judge's offline fixture is worth reading correctly: its 25 labelled cases
run through the real adapter against **canned** model responses, so they pin the
HTTP envelope parsing, the JSON decode and verdict normalisation. They say
nothing about whether the model's judgement is any good. Measuring that needs a
live vendor call and is a separate, paid task.

## The control plane seam

`internal/controlplane` is the `ports.ContractSource` over the Python
control plane's HTTP API, and since 2026-09-12 the **only** contract source
`engined` will construct — `internal/fakes` is test-only again, and the
`-dev-sample-contract` switch that served one checked-in persona to every
session is gone. Configuration: `CONTROL_PLANE_BASE_URL` and
`CONTROL_PLANE_SHARED_SECRET` (sent as a bearer token; the control plane
answers 503 without its own copy).

* **Fetch** — `GET /api/v1/candidates/{id}/engine-contract`, no retry
  (session creation is interactive). 404 maps to `ports.ErrContractNotFound`,
  which the manager wraps and the HTTP layer answers as **404** rather than the
  502 an unreachable control plane gets.
* **Report** — `POST /api/v1/sessions/{id}/ingest` with
  `Idempotency-Key: <session id>`, the moment the actor stops for any reason.
  The manager's `reportIngest` goroutine waits on the actor's `done`, builds
  `actor.ingest()` — turn table, degradations, unlock flip, suppressed skills,
  end reason (`interviewer_ended | abandoned | duration_cap | error`), a
  SHA-256 fingerprint of the contract bytes, `session.EngineVersion` (set from
  `-ldflags -X main.version`) and per-session metrics — and hands it to the
  client. Retry on 5xx/network with backoff; 409 counts as delivered; a 4xx
  otherwise is never retried. If the control plane stays down the payload is
  spooled under `SPOOL_DIR/ingest` and `engined` drains the spool at startup
  before taking sessions. `Manager.Drain` lets shutdown wait for in-flight
  reports.
* **One session id on both sides.** `POST /v1/sessions` accepts an optional
  `session_id` (`[A-Za-z0-9_-]{1,120}`) so the portal can open the
  control-plane session first — that is where the recording lands — and have
  the engine's ingest close that same row. The engine still mints an id when
  none is given.
* **Layering.** `internal/controlplane` is in the adapter set the layering
  test polices: only `cmd/engined` may import it, and it imports only
  `ports` among internal packages.

Contract: [Session ingest](/concepts/contracts/session-ingest.md).

## The harness context and the two windows

`docs/LIVE_TALKING_ENGINE_HARNESS.drawio` (rendered as `.png`/`.svg` beside it)
is the design: both live transcripts — the interviewer's ASR and what the
Speaker actually spoke — land in one **harness context**, the Thinker reasons
from it, and its direction reaches the Speaker only in two silences. The
implementation (2026-09-12, Codex phases 1–2b, then corrected):

* **`session/harness_context.go`** is actor-owned, so the actor is its only
  writer and there is one ordering source. Human items are keyed by the ASR
  item id (a repeated key is a *revision*, not a new utterance); persona text
  accumulates per response id and finalizes on `ResponseDone`, barge-in or clip
  playout. Storage is bounded (128 entries), and separately the last eight
  **finalized turns** are kept as `{turn, human, persona}` records. Closed keys
  reject late revisions, with a bounded tombstone set.
* **Which transcript is canonical.** With `vendors/openaitx` running, its
  partials are the human transcript and the Speaker's `InputTranscript` is
  ignored — recording both would put one utterance in the snapshot twice under
  two ids. Without it, the Speaker's fragments accumulate under the turn's own
  key and the energy detector's final closes that same key.
* **The snapshot the Thinker gets is history only**: the finalized turns
  *before* the current one. The current question is not in it — it streams in
  through `FeedPartial`, and the speculation that starts is what has to survive
  to end-of-turn. `Version` is content-derived (the newest contributing
  transcript sequence), so it moves when a turn finalizes and never on an
  interim revision.
* **Window B** — `closePersonaTurn` → `refreshThinker`: `Reset` with the full
  ledger, then `SetHarnessSnapshot` for the next turn. Before this `Reset` was an
  interface method nothing called, so the Thinker reasoned from the ledger as it
  stood at connect for the whole interview. The note's `claims_made` is asked
  for as what the candidate actually said in its last answer in that history,
  which is the "claims made" half of the diagram's Window B.
* **Window A, on every turn** — `requestNote` republishes the same history
  under the current turn and asks for the note. `thinkerllm` treats an
  unchanged `Version` as a no-op and keeps its speculation; a changed one
  abandons it. Codex's first draft versioned every revision and abandoned on any
  change, which made every defer a cold call — precisely the latency the
  speculative path exists to remove. The two verdicts differ only in what they
  wait for:
  * **CONFIDENT** (`beginAnswer`): the note is requested with the persona's own
    `target_pause_before_answer_ms` as its deadline. If it lands inside the
    pause it steers the answer (system item, ledger, unlock); if not, the pause
    elapses, `note_late` is logged and the Speaker answers alone. No stall on
    this path — a confident persona does not buy time. Before this the note was
    requested only on DEFER, and every confident turn threw away a speculation
    that had already been paid for.
  * **DEFER** (`beginDefer`): the note is requested with the 700 ms Thinker
    deadline, and `timerPause` is armed for a **grace** of the same pause,
    bounded to 50–350 ms (`stallGrace`). A note that is already there lands
    inside the grace and no clip plays. When the grace runs out `beginStall`
    enters STALLING: one of the persona's own pre-synthesized phrases plays
    (`PickStall` now returns the phrase with the clip, because a partly-warmed
    bank compacts its clips and an index would name the wrong words), the
    phrase opens the persona's turn record and lands in the harness, and the
    note or the deadline moves the turn on. If the clip ends first the persona
    stays quiet — the accepted silence after an in-character stall, never a
    second canned phrase. **This is where the diagram overrides the plan**: the
    plan put the stall clip on the wire inside 50 ms of every defer; the
    diagram's latency rule makes the phrase the cover for a miss, not the path.
    Until this change no stall clip was ever played at all — `PickStall` had no
    caller and STALLING was never entered, so a deferred turn was a bare pause.
* **Never mid-sentence.** `handleNote` accepts a note only in PRE_ANSWER,
  DEFERRED or STALLING; `createResponse` closes the turn gate so a note that
  arrives once the persona is talking reaches the log and nothing else.
* **Degraded input transcription.** With no Transcriber, the Speaker's
  `InputTranscript` fragments are routed through the same partial path ASR
  uses (cumulative text under the turn's own key), so the pre-gate classifies
  and the Thinker reads while the interviewer talks. A fragment that trails the
  energy detector's end-of-turn is appended to the question it belongs to
  (`late_transcript_fragment`), never to the next one. If the ASR stream dies
  mid-question the utterance stays ASR-owned until the energy detector closes
  it, so the Speaker cannot re-supply the same words.
* **The note guard.** A note is discarded if its turn, its history version or
  the state no longer match. The version compared is the finalized history, not
  the revision counter: an interviewer adding "um, and also" while the note is
  in flight must not cost the persona its answer (`TestAnInterimRevisionDuringDeferDoesNotDiscardTheNote`).

**Live-verified OpenAI facts** (`gpt-4o-mini-transcribe`, 2026-09-12, the
`//go:build live` test in `vendors/openaitx`):

* The beta form is gone: `OpenAI-Beta: realtime=v1` plus
  `transcription_session.update` is rejected with "The Realtime Beta API is no
  longer supported". Codex's adapter shipped that form and its offline test
  accepted it, which is the whole reason the live test exists. The GA form is
  `session.update` with `session.type: transcription` and the format,
  transcription model and `server_vad` nested under `audio.input`.
* Setup is accepted in about one second; a four-second 16 kHz question streamed
  in 20 ms frames came back verbatim 1.8 s after the last frame, as 12 cumulative
  revisions and one final, all under one stable `item_id` — the key the actor
  revises by.
* The vendor's server VAD decides the item boundary, so a long thinking pause
  mid-question ends the turn. That is the trade the design already made ("a
  Transcriber owns end-of-turn"); the pause length is not tuned yet.

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

`docs/ENGINE_ONE_BRAIN_TWO_PARTS.html` draws
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
the engine contract spec (`docs/GO_ENGINE_CONTRACT.md`). It also retains the
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

## Configuration

`engine/internal/config.Load` reads named environment variables only (no
`os.Getenv` anywhere else — the layering test forbids it), through a lookup
function so tests inject a map. **Required** means `engined` refuses to start
without it; every issue is reported at once, not one per restart. Verified
against `config.go` on 2026-09-13.

| Var | Default | Meaning |
|---|---|---|
| `GEMINI_API_KEY`, `OPENAI_API_KEY` | required | Vendor keys, same names as the Python side. `GEMINI_API_KEY2` is **ignored** — the key failover is a Python feature |
| `SPEAKER_MODEL_ID`, `THINKER_MODEL_ID`, `JUDGE_MODEL_ID`, `TTS_MODEL_ID`, `ASR_MODEL_ID` | required | One model per part. Which vendor/model is live is an operational decision, never a code default. `ASR_MODEL_ID` is an OpenAI Realtime transcription model; the Transcriber is only built when `OPENAI_API_KEY` is also set |
| `SPEAKER_VENDOR` | `gemini` | `gemini` or `openai` backs the Speaker adapter |
| `CONTROL_PLANE_BASE_URL`, `CONTROL_PLANE_SHARED_SECRET` | required | The [control plane seam](#the-control-plane-seam); the secret goes out as a bearer token |
| `S3_BUCKET`, `S3_REGION` | required | Session-bundle storage — required by the loader even though `store/s3` is still `doc.go` |
| `S3_PREFIX`, `S3_ENDPOINT`, `S3_FORCE_PATH_STYLE` | empty / `false` | Prefix and S3-compatible override (MinIO) |
| `PREGATE_DEADLINE_MS` | `250` | Deterministic pre-gate budget |
| `STALL_DEADLINE_MS` | `50` | Stall-clip start budget |
| `THINKER_DEADLINE_MS` | `700` | Window for the Thinker's note on a deferred turn |
| `PAUSE_BEFORE_ANSWER_DEFAULT_MS` | `700` | Persona pause when the contract gives none. The stall grace is derived from the persona's pause and clamped to 50–350 ms in `actor.go` |
| `ABANDON_AFTER_S` | `300` | Silence cap → `end_reason: abandoned` |
| `SESSION_DURATION_CAP_S` | `3600` | Session cap → `end_reason: duration_cap` |
| `CONNECT_TIMEOUT_S` | `15` | Speaker connect budget; failure → `end_reason: error` |
| `WALKBACK_ENABLED`, `DEFER_TOOL_ENABLED` | `true` | Feature toggles for the walk-back and the defer tool |
| `WEBRTC_ICE_SERVERS`, `TURN_URL`, `TURN_USERNAME`, `TURN_CREDENTIAL` | Google STUN / empty | Signalling settings for the WebRTC transport, which does not exist yet; `wsfallback` ignores them |
| `SPOOL_DIR` | `./spool` | Ingest spool (`SPOOL_DIR/ingest`) and, once built, the bundle spool. Shared with the control plane |
| `METRICS_ADDR` | empty | Metrics HTTP listener; blank disables it |
| `GEMINI_TTS_VOICES` | the 30-name roster in `.env.example` | Ordered, **append-only**: a persona's frozen voice is `hash(candidate_id) mod len`, so reordering repoints existing personas |

`.env.example` is the operator-facing copy of this table and carries the same
defaults; when the two disagree, `config.go` wins and both must be fixed.

## Checks

`scripts/check.sh` runs gofmt, vet, build, `go test -race`, the layering test and
golangci-lint against `.golangci.yml`, all from inside the module. Vendor tests
are tagged `//go:build live` and run only under `--live`, matching the Python
convention that model calls cost money. See [checks](/concepts/runbooks/checks.md).
