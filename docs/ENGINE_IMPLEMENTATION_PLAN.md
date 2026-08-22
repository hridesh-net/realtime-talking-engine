# Go Engine Implementation Plan

> Implementation plan for the live-session engine in `engine/`. This is a plan,
> not code. Review it, argue with it, then we build in the phase order of §14.
>
> Companion docs: `docs/GO_ENGINE_CONTRACT.md` (contract spec),
> `owner_handover/engine_contract_sample.json` (real payload),
> `.golangci.yml` (lint standard), `scripts/check.sh` (CI gate).

---

## 1. Goals, non-goals, latency budget

### Goals

- Run live voice sessions where the AI plays a **persona** (today: job candidate)
  and a **human** practises against it. Persona-agnostic: persona, task,
  behaviour and goal arrive as data in a frozen engine contract; the engine
  hardcodes no interview concepts.
- <800ms voice-to-voice for the common path, with real expression (fillers,
  hesitation, backchannels) from the Speaker.
- Deterministic persona: same contract + `seed_fingerprint` ⇒ the same person —
  same false beliefs, same vagueness, same stalls — so two interviewers can be
  compared on one candidate.
- One brain, two parts: Speaker (realtime speech model) always owns the mouth;
  Thinker (reasoning model) is the persona's subconscious, running speculatively
  and continuously. They share one memory (the claims ledger). Neither decides
  anything the contract already decided.
- Ship a gradable session bundle (stereo recording, aligned transcripts, turn
  metadata, ceiling-breach flags, unlock turn) to S3 and notify the Python
  control plane. Grading stays in Python.
- ~50 simultaneous sessions per node.

### Non-goals

- No grading in the engine. No persona authoring in the engine. No LLM decides
  persona content at runtime — the Thinker retrieves and elaborates
  pre-committed material, never invents beliefs.
- No talking-during-tool-call. Silence after an in-character stall is accepted
  by the owner. We do not build audio-overlap machinery.
- No Go AEC. Echo handling is browser AEC + server-side gating (§11, OQ-1).
- No multi-node session migration; sessions are sticky to a node. Horizontal
  scale = more nodes behind session-aware routing (out of scope for v1).

### Latency budget (common path: human stops → persona audible)

| # | Hop | Budget (p50 / p95) | Notes |
|---|-----|--------------------|-------|
| 1 | Mic capture + browser Opus encode | 25 / 45 ms | 20 ms Opus frames + capture buffer |
| 2 | Network browser → engine (WebRTC) | 25 / 70 ms | one-way; TURN adds ~20 ms |
| 3 | Pion ingest + jitter buffer | 40 / 60 ms | fixed 40 ms depth, adaptive up to 60 |
| 4 | Opus decode + resample 48k→16k | 2 / 5 ms | CGo libopus + speexdsp |
| 5 | Engine → vendor WS upload | 20 / 40 ms | co-located region matters; pick node region near vendor |
| 6 | Vendor end-of-turn VAD + first audio | 350 / 500 ms | **the whole ballgame** — dominated by model, not us |
| 7 | Vendor → engine first audio chunk | 20 / 40 ms | |
| 8 | Resample 24k→48k + Opus encode + send | 10 / 20 ms | |
| 9 | Browser jitter buffer + playout | 45 / 70 ms | |
|   | **Total** | **~540 / ~850 ms** | slack lives almost entirely in hop 6 |

- `voice_directives.target_pause_before_answer_ms` (700 ms in the sample) is a
  **deliberate persona delay layered on top**, owned by an engine timer — it is
  not latency and must not be double-counted. When the vendor is slow, the
  timer absorbs it: pause timer = max(0, target − measured hops 6–7).
- **Stall path budget**: pre-gate verdict ≤ 250 ms after end-of-turn (it runs on
  partials so usually ready *before* end-of-turn); stall audio starts < 50 ms
  after a DEFER verdict (pre-synthesized, no LLM round-trip); Thinker note
  deadline 700 ms after end-of-turn; deadline miss ⇒ contract fallback
  (`turn_policy.on_unknown_question` / `on_pressure`). Silence between stall
  clip and answer is acceptable.
- Every hop gets a timestamp and a histogram (§12). If we can't see hop 6 per
  vendor per session, we can't run the Gemini A/B.

---

## 2. Architecture

Four planes; deterministic Go owns everything except two narrow model calls.

- **Media plane** — WebRTC/Pion last mile, Opus codec, jitter buffer,
  resampling, mic gate, playout tracking, recording tap. Deterministic.
- **Cognition plane** — Speaker (vendor realtime speech) and Thinker (reasoning
  model) behind ports, plus the async Judge. The only places a model runs.
- **Session plane** — the per-session actor: state machine, timers, pre-gate,
  stall bank, claims ledger, unlock state, truncation accounting. Deterministic.
- **Persistence plane** — event log, transcripts, stereo recording, S3 upload,
  ingest notify. Deterministic.

### What is deterministic code vs what a model may decide

| Decision | Owner |
|---|---|
| Who the persona is, its beliefs, ceilings, tics, stall phrases | Contract (compiled in Python at design time) |
| When to stall, which stall clip, when to give up on the Thinker | Engine (pre-gate, timers) |
| When to defer at all | Engine pre-gate (reliable) + optional model tool call (bonus) |
| What the persona's *wrong* answer is | Precompiled `precompiled_beliefs` in the contract |
| How to phrase it aloud, prosody, fillers | Speaker model (within `voice_directives`) |
| How to *elaborate* a pre-committed belief in context | Thinker (retrieval + elaboration only — notes, not scripts) |
| Whether `unlock_condition` flipped | Thinker assesses per turn; **engine actor owns the flip** (§7) |
| Whether a spoken answer breached a ceiling | Async Judge (detection); engine injects walk-back (mechanism) |
| Turn boundaries, barge-in, truncation ms | Engine (playout tracker) |

### Ports (all in `engine/internal/ports`)

| Port | Method sketch | Implementations |
|---|---|---|
| `Speaker` | `Start(ctx, SessionCfg) (SpeakerSession)`; session: `SendAudio`, `InjectSystemItem`, `CreateResponse(directives)`, `CancelResponse`, `Truncate(itemID, heardMs)`, `Events() <-chan SpeakerEvent` | `vendor/gemini` (default), `vendor/openairt` |
| `Thinker` | `Start(ctx, PersonaCtx)`; `FeedPartial(text)`, `RequestNote(deadline) <-chan Note`, `Reset()` | `vendor/thinkerllm` (any streaming LLM; model id config) |
| `Transcriber` | `Start(ctx)`; `SendAudio`, `Partials() <-chan Partial` | `vendor/openaitx` (transcription session), `vendor/localasr` (whisper.cpp/Vosk, spike) |
| `Transport` | `Accept(offer) (MediaConn)`; conn: `AudioIn() <-chan Frame`, `SendAudio(Frame)`, `Control() chan msg`, playout heartbeats | `transport/webrtc` (Pion), `transport/wsfallback` |
| `Store` | `PutObject(key, r)`, multipart, spool-on-failure | `store/s3`, `fakes` in-mem |
| `ContractSource` | `FetchContract(candidateID)`, `NotifyIngest(SessionIngest)` | `controlplane` HTTP client |
| `Judge` | `Submit(TurnForReview)`, `Verdicts() <-chan Verdict` | `judge/llm` (async; model id config) |
| `Clock` | `Now()`, `NewTimer(d)`, `After(d)` | real, `fakes.FakeClock` — **injected everywhere from day one** |
| `TTS` | `Synthesize(text, voiceID) (pcm)` | `vendor/geminitts` — stall bank + opening line pre-synthesis |

### ASCII diagram

```
 Browser (human interviewer)
  mic ──Opus/WebRTC──► ┌──────────────────────── engine/ (Go, one process) ───────────────────────┐
  spk ◄──Opus/WebRTC── │ transport/webrtc (Pion)  [WS/PCM fallback]                               │
  (data ch: heartbeats)│   decode → jitter buf → 48k PCM ──┬── resample 16k ──► Speaker vendor    │
                       │                                   ├── resample 24k ──► Transcriber       │
                       │                                   └──────────────────► Recorder (L ch)   │
                       │                                                                          │
                       │  ┌────────────── session actor (ONE goroutine, owns all state) ───────┐  │
                       │  │ state machine · timers(Clock) · pre-gate · stall bank · playout    │  │
                       │  │ tracker · CLAIMS LEDGER (single writer) · unlock state · event log │  │
                       │  └───┬──────────────┬───────────────┬──────────────┬─────────────┬───┘  │
                       │      │ audio/ctrl   │ partials      │ notes        │ turns       │ bundle│
                       │      ▼              ▼               ▼              ▼             ▼      │
                       │  Speaker port   Transcriber     Thinker port   Judge port    Store/S3   │
                       │  (Gemini Live   (OpenAI tx or   (reasoning     (async,       + ingest   │
                       │   WS 16k/24k)    local ASR)      LLM, notes)    sec-late)    notify ────┼──► Python
                       │      │ persona audio 24k → resample 48k → Recorder (R ch) → transport   │   control
                       └──────┴───────────────────────────────────────────────────────────────────┘   plane
```

Dependency direction (mirrors the repo rule "llm ← agents ← control_plane"):
**vendors/transports/stores → ports ← session core**; only `cmd/engined` wires
concrete adapters into the core. Vendor SDKs and API keys never leave
`internal/vendor/*` + `internal/config`.

---

## 3. Package layout

Go module rooted at `engine/` (`module skillbrew/engine`, Go ≥ 1.23). One line
each; deeper nesting only where a package grows past ~6 files.

```
engine/
  cmd/engined/              main: config → adapters → session manager → HTTP; the ONLY wiring point
  internal/config/          env + flags; the ONLY package that reads os.Getenv; model IDs live here
  internal/contract/        contract structs (match owner_handover schema), parse, validate, version pin
  internal/ports/           all interfaces + shared event/message types; imports nothing internal
  internal/session/         actor loop, state machine, turn lifecycle, timers, truncation accounting
  internal/ledger/          claims ledger: types, single-writer API, contradiction lookup, snapshots
  internal/gate/            deterministic pre-gate: lexicon match over partials, verdict + deadline
  internal/stall/           stall bank: pre-synth clip cache, picker (no immediate repeats), opening line
  internal/audio/           PCM types, resampler, jitter buffer, mic gate, zero-fill, level meter
  internal/record/          stereo recorder (presentation-timestamped), crash-safe finalize, drift reconcile
  internal/transcriptlog/   turn/utterance JSONL writers aligned to the recording timeline
  internal/vendor/gemini/   Gemini Live Speaker adapter (WS, 16k in / 24k out)
  internal/vendor/openairt/ OpenAI Realtime Speaker adapter (24k both ways, item.truncate)
  internal/vendor/openaitx/ OpenAI realtime transcription-session Transcriber adapter
  internal/vendor/localasr/ self-hosted streaming ASR Transcriber (whisper.cpp/Vosk — spike)
  internal/vendor/thinkerllm/ Thinker adapter over a streaming LLM API
  internal/vendor/geminitts/  TTS adapter for stall-bank/opening-line pre-synthesis
  internal/judge/           async post-hoc semantic judge (LLM behind Judge port), walk-back directives
  internal/transport/webrtc/  Pion: offer/answer, tracks, data channel, playout heartbeats
  internal/transport/wsfallback/ WebSocket/PCM last-mile fallback
  internal/store/s3/        S3 multipart upload, retry, local spool
  internal/controlplane/    ContractSource impl: fetch contract, POST ingest notify (idempotent)
  internal/obs/             structured logging (slog), per-hop latency metrics, cost meter
  internal/fakes/           FakeClock, scripted FakeSpeaker/Transcriber/Thinker, in-mem Store
  internal/arch/            architecture test (go list -deps assertions; see §10)
```

**Rules** (enforced by `internal/arch`): `ports` imports no sibling;
`session`/`ledger`/`gate`/`stall` import only `ports`, `contract`, `obs`;
`vendor/*`, `transport/*`, `store/*` import only `ports`, `config`, `obs`;
nothing outside `cmd/engined` imports a `vendor/*` or `transport/*` package;
`os.Getenv` only in `config`; no vendor model-id string literals outside
`config` and testdata.

---

## 4. Core state machine and the actor model

### The actor

One **owner goroutine per session** holds ALL mutable session state. No mutexes
on the latency path; everything else message-passes into it. It owns:

- state enum + current turn record
- claims ledger (single writer)
- all timers (pause-before-answer, stall deadline, thinker deadline, silence,
  session/cost caps) — created from the injected `Clock`
- playout tracker (samples sent vs ms heard, per persona response item)
- unlock state (monotonic bool + flip turn)
- pre-gate verdict for the in-flight interviewer utterance
- event log emitter (JSONL)

Pump goroutines (WS readers, Pion track readers, timer waiters) do no logic;
they convert I/O into messages. `select` has no priority, so the actor loop is
a **nested select**: drain control/timer channels with `default` first, then
block on the full set. Inbound channels and policy:

| Channel | Policy |
|---|---|
| control (start/stop/config) | unbounded queue, never drop |
| timerFired | never drop |
| micAudio (post-decode frames) | bounded; on overflow drop-oldest + counter |
| asrPartial | bounded, drop-oldest (a newer partial supersedes) |
| speakerEvent (audio, transcript, tool call, done) | bounded; audio drop-oldest, non-audio never drop (split channels) |
| thinkerNote | size 1, newest wins |
| judgeVerdict | unbounded (async, non-critical) |
| playoutHeartbeat | size 1, newest wins |

Recording taps are **outside** the actor: a dedicated writer goroutine per
session consumes timestamped frames from both directions; on its own overflow
it silence-fills, never blocks the media path (§9).

**Cancellation discipline**: every blocking read has an unblock path —
`ws.ReadMessage()` ignores ctx, so vendor adapters must pair ctx cancellation
with `SetReadDeadline`/`conn.Close()`. Cancelling a turn enters **DRAINING**:
buffered persona audio downstream of the cancel point is flushed (transport
out-ring cleared, vendor response cancelled, playout tracker closed for that
item) before the next state — otherwise stale audio plays after barge-in.
`goleak` in every test package; one missed path = one leaked goroutine per
session and at 50 sessions/node that is discovered in a week, not a year.

### States

```
CONNECTING → GREETING → LISTENING → (PRE_ANSWER | DEFERRED) → SPEAKING → LISTENING …
                                        DEFERRED → STALLING → SPEAKING
        any speaking-ish state --barge-in--> DRAINING → LISTENING
        any state --stop/caps/abandon--> WINDING_DOWN → FINALIZING → DONE
```

| State | Meaning |
|---|---|
| CONNECTING | transport up, contract loaded, stall bank synthesized, vendor sessions opening |
| GREETING | wait for interviewer's first utterance end, then play pre-synth `opening_line` |
| LISTENING | human speaking; partials → pre-gate + Thinker (speculative, from first word); mic → Speaker vendor |
| PRE_ANSWER | end-of-turn, verdict CONFIDENT; pause timer running (`target_pause_before_answer_ms` minus measured vendor latency); then `CreateResponse` |
| DEFERRED | verdict DEFER: stall clip queued (<50 ms), thinker deadline (700 ms) armed |
| STALLING | stall clip playing / silence; on note ⇒ inject note as system item + `CreateResponse`; on deadline ⇒ inject contract fallback directive + `CreateResponse` |
| SPEAKING | persona audio streaming out; playout tracker live; mic gated if `barge_in_allowed=false` |
| DRAINING | response cancelled: flush out-buffers, `Truncate(itemID, heardMs)`, cancel ALL turn timers, close turn record |
| WINDING_DOWN | in-character wrap (cost/duration cap or abandonment) |
| FINALIZING | recorder finalize, transcripts closed, S3 upload, ingest notify |

### Turn lifecycle (full, with defer and barge-in)

1. Human starts speaking. Transcriber emits partials; each partial goes to
   pre-gate (incremental lexicon match) and Thinker (`FeedPartial`). Thinker is
   never cold: it has persona context + ledger and is already reasoning.
2. End-of-turn (vendor VAD and/or transcriber final). Actor closes the
   interviewer utterance, logs `probed_skill` from the pre-gate classification.
3. Pre-gate verdict, deadline 250 ms after end-of-turn (usually already ready):
   - **CONFIDENT** → PRE_ANSWER; pause timer; on fire, `CreateResponse` with
     turn-policy directives (sentence bounds, depth). Speaker answers alone.
   - **DEFER** → DEFERRED; stall clip out inside 50 ms; `RequestNote(700ms)`.
   - **Race lost** (no verdict by deadline) → treat as CONFIDENT; the system
     prompt is the backstop; log `pregate_race_lost`.
4. If the Speaker itself emits the defer tool call (bonus path), join into
   DEFERRED regardless of pre-gate verdict; per verified vendor facts the
   response has terminated, so no cancel needed — send tool output (the note or
   fallback) then `CreateResponse`.
5. Thinker note arrives → injected verbatim as a **system item** (a note: "you
   half-remember X; you sincerely believe [precompiled belief B7]; keep it
   vague, 2–3 sentences"), never as a script → `CreateResponse`. Deadline miss
   → inject `on_unknown_question`/`on_pressure` directive instead. Either way
   the Speaker phrases the words — no register seam.
6. SPEAKING: audio out through playout tracker → transport; right recording
   channel receives what was *heard* (§9). Sentence-bound enforcement: actor
   counts sentences from the speaker transcript stream; at `max_sentences` + a
   grace clause it issues `CancelResponse` (soft trim, logged).
7. Turn close: transcript finalized, Thinker extracts claims for the ledger
   (§5), turn submitted to Judge, ceiling re-assertion cadence checked (§6),
   unlock assessment recorded (§7), Thinker `Reset()` to the new ledger state.

**Barge-in** (human interrupts persona, `barge_in_allowed` honoured): VAD-on-mic
while SPEAKING → DRAINING: `CancelResponse`; compute `heardMs` from the playout
tracker (last browser heartbeat + extrapolation, **not** bytes sent);
`Truncate(itemID, heardMs)` so the vendor's history matches reality; flush
transport out-ring; cancel pause/stall/thinker timers (ghost-utterance bug
class); truncate right recording channel at `heardMs` and zero-fill; log
`barge_in{turn, heard_ms, sent_ms}`. Then LISTENING. If
`barge_in_allowed=false`: mic is gated to the Speaker vendor while SPEAKING
(echo defence, §11), but mic audio still reaches recorder and transcriber — an
ignored interruption attempt is itself feedback data.

`voice_directives.may_interrupt=true` (persona barging in on the human) is
Speaker-model behaviour; the engine only permits persona audio out during
LISTENING when this flag is set, and treats it as a normal SPEAKING entry.

---

## 5. The claims ledger

The concrete mechanism that makes Speaker + Thinker one brain, and the fix for
review finding 3 (turn-4-vs-turn-19 contradictions poisoning the product's own
feedback signal).

### Data model

```jsonc
// ledger entry (in-memory struct + JSONL event)
{
  "claim_id": "b7" | "r12",          // b* = precompiled belief, r* = runtime-observed
  "skill": "Redis",
  "statement": "Redis is single-threaded",   // canonical, short, declarative
  "stance": "asserted",               // asserted | denied | hedged
  "origin": "precompiled_belief" | "thinker_note" | "spoken_extracted",
  "turn": 4,
  "ts": "…",
  "supersedes": null                  // only via explicit walk-back (§6)
}
```

- **Single writer: the session actor.** Everything else proposes.
- **Seeded at load** from `contract.precompiled_beliefs` (§8) with turn=0 —
  the persona's false beliefs exist before the first question.
- **Appended per turn**: the Thinker's structured note output includes
  `claims_made` extracted from the persona's final turn transcript (it sees the
  transcript anyway; no extra model). The actor canonicalizes and appends.
- **Contradiction guard**: before a Thinker note is injected, the actor checks
  the note's `claims_to_make` against the ledger by skill; a contradiction
  downgrades the note to "restate what you said before" (deterministic, logged
  `contradiction_averted`). Walk-backs (§6) are the only sanctioned reversals
  and are recorded with `supersedes`.

### Consumption

- **Thinker** gets the full ledger in its context on every `Reset()` — it
  reasons over "what this person has already committed to".
- **Speaker** gets a compact system item — "Things you have already said in
  this interview: …" (claims as one-liners, ≤ ~15 lines, newest-first per
  skill) — refreshed every N turns (config, default 4) and always included
  with a defer injection. Realtime models forget audio history details; this
  is cheap insurance.
- **Judge** receives relevant claims with each turn under review.

### Persistence

Every ledger append is an event in the session events JSONL, so the grader
receives the belief timeline; the final ledger snapshot rides in the ingest
metadata. Determinism story: beliefs are precompiled per
`seed_fingerprint`, runtime only elaborates and restates them, and the
elaboration trail is fully logged — two sessions on the same contract share
identical seeded claims and diverge only in phrasing.

---

## 6. Ceiling enforcement — all layers, honestly labelled

| # | Layer | When | Mechanism | Nature |
|---|---|---|---|---|
| 1 | `system_prompt` "WHAT YOU ACTUALLY KNOW" | always | injected verbatim | **best-effort** (model compliance; drifts under pressure) |
| 2 | Precompiled beliefs + vague-deflection lines | design time | contract carries the persona's wrong/vague material so the model never has to invent competence downward | **deterministic content**, best-effort delivery |
| 3 | Deterministic pre-gate → stall → Thinker note | per turn, mid-utterance | low-ceiling probe classified from partials ⇒ DEFER; note retrieves belief `b*` and prescribes vagueness | **best-effort with a floor**: deadline miss falls back to `on_unknown_question`/`on_pressure`, which is still persona-correct |
| 4 | Periodic re-assertion | every N turns (config, default 5) and whenever pre-gate sees a probe on a skill with ceiling ≤ 3 | re-send the ceiling block as a system item | best-effort |
| 5 | Sentence bounds | per response | actor-enforced `max_sentences` trim | **guaranteed** (length only, not depth) |
| 6 | **Post-hoc semantic Judge** | async, seconds late | per persona turn: question + answer + skill + ceiling + beliefs → `{breach, severity, rationale, walkback_hint}` | **guaranteed to run and label**; cannot un-say audio |
| 7 | In-character walk-back | next natural turn after a flagged breach, config-gated (`WALKBACK_ENABLED`, default on) | system directive: recant in character ("actually, I'm not sure that was right — I've mostly just read about it"); ledger entry with `supersedes` | best-effort repair |

**Honest statement**: no pre-speech layer is a guarantee — a fluent in-character
level-6 answer against a ceiling of 3 is a *semantic-depth* failure no regex or
lexicon catches (review finding 1). The guarantees are: (5) length, (6) every
persona turn is judged and breaches are flagged in the grading metadata so the
interviewer is never *credited* for depth that wasn't supposed to exist, and
(3)'s floor — when we defer, the worst case is the contract's own fallback
behaviour. Vagueness (review finding 8: `system design: 1` = "bluffs") is a
first-class generation target: precompiled `vague_deflections` give the model
literal vague material, Thinker notes prescribe vagueness explicitly, and the
fidelity harness (§13) scores vagueness separately from wrongness.

---

## 7. `unlock_condition` — owner, mechanism, logging

**Owner: the session actor.** The Thinker assesses; the actor decides and logs.

- Design time: the control plane compiles `unlock_condition` prose into a
  structured `unlock_spec` (§8): `{kind: "never" | "conditional", condition:
  "<prose>", hints: […]}`. The sample persona ("never reveals depth") compiles
  to `kind: "never"` and the runtime short-circuits — no per-turn assessment.
- Runtime (`kind: "conditional"`): the Thinker's per-turn structured output
  includes `unlock_assessment: {met: bool, evidence: "<quote>"}` judged against
  `condition`. The actor flips its **monotonic** unlock bool on the first
  `met=true`, logs `unlock_flipped {turn, evidence}` (the contract spec
  explicitly requires the flip turn), and from then on issues
  `CreateResponse` directives allowing depth up to the ceiling instead of
  `default_answer_depth`.
- The flip turn + evidence ride in the ingest metadata — "did the interviewer
  earn the unlock, and when" is a headline feedback signal.
- Failure mode: Thinker outage ⇒ unlock can only stay unflipped; logged as
  `unlock_assessment_degraded` so the grader discounts it.

---

## 8. Control-plane changes required (Python side)

These are prerequisites for engine Phases 3–5 and fix review finding 2
(runtime-invented wrong answers void `seed_fingerprint` determinism — beliefs
must be precompiled at design time, which is also this repo's own rule in
`okf/concepts/determinism.md`).

### 8.1 Contract extension — `contract_version: "v1.1"`

New fields in the engine contract (compiled deterministically in
`candidate_agent/engine_contract.py` alongside the existing seeds — the sample
already carries per-skill "You sincerely believe (incorrectly)" text; this
promotes it to structured data):

```jsonc
"precompiled_beliefs": {
  "Redis": [
    {"claim_id": "b3",
     "statement": "Redis is always faster than a relational database, so just use it for everything.",
     "elaborations": ["…2–3 pre-authored ways this persona expands the belief…"],
     "vague_deflections": ["I mean, we mostly just… used it for caching, it worked fine."]}
  ], …
},
"stall_phrases": ["Hmm, let me think…", "That's, uh… that's a good question…"],  // persona-voiced, derived from verbal_tics/sample_phrases
"pregate_lexicon": {                      // per skill: aliases + breaks_down_when trigger phrases
  "system design": {"aliases": ["design a system", "architecture", "data model", "API contract", "scale this"],
                     "defer_at_or_below": 3}
},
"unlock_spec": {"kind": "never"} ,        // or {"kind": "conditional", "condition": "...", "hints": [...]}
"tts_voice_id": "…"                       // must equal the Speaker voice so stall clips have no voice seam
```

All of it frozen under `fingerprint`; belief selection keyed off
`seed_fingerprint` so re-casting the same persona reproduces the same beliefs.

### 8.2 New ingest endpoint

`POST /api/v1/sessions/{session_id}/ingest` — the engine's single write-back.
New handler in `control_plane/`, depending on the narrowest port in
`control_plane/ports.py` (repo hard rule). Pydantic model (public ⇒ schema
export required):

```jsonc
{
  "session_id": "…", "candidate_id": "…", "interview_id": "…",
  "contract_fingerprint": "…", "engine_version": "…",
  "started_at": "…", "ended_at": "…", "end_reason": "interviewer_ended | abandoned | cost_cap | error",
  "s3": {"audio_wav": "s3://…/audio.wav", "transcript_jsonl": "s3://…", "events_jsonl": "s3://…"},
  "turns": [{"turn": 1, "speaker": "human|persona", "start_ms": 0, "end_ms": 8200,
              "text": "…", "probed_skill": "Redis", "unlock_met": false,
              "deferred": true, "fallback_used": false}],
  "ceiling_flags": [{"turn": 9, "skill": "Go", "severity": "high", "rationale": "…", "walked_back_turn": 11}],
  "unlock_flip": {"turn": 14, "evidence": "…"} ,   // or null
  "suppressed_answers": [...],                     // contract spec requires these
  "metrics": {"voice_to_voice_p50_ms": 610, "stall_rate": 0.22, "cost_usd": 1.42, …},
  "degradations": ["asr_outage_12:03–12:05"]
}
```

Idempotent on `session_id` (engine retries with an idempotency key). Receipt
triggers the existing grading path (scorecard × transcript).

### 8.3 Process obligations (repo hard rules)

- `.venv/bin/python scripts/export_schemas.py` after the contract v1.1 and
  ingest models land (CI fails otherwise).
- okf: update the engine-contract concept and `okf/concepts/determinism.md`
  (precompiled beliefs are the determinism mechanism), add an engine/ routing
  entry to `okf/concepts/repo-map.md`, new concept page for the ingest flow;
  one `okf/log.md` line per change, per `okf/concepts/runbooks/okf-maintenance.md`.
- Architecture tests: handlers on narrow ports, no agent persistence — the new
  ingest handler must pass `tests/test_architecture.py` unmodified.

---

## 9. Recording and S3 pipeline

The recording is the grading ground truth; correctness beats convenience.

- **Format**: one stereo WAV, 48 kHz s16le. **LEFT = human** (post-jitter
  decoded mic), **RIGHT = persona** (vendor 24 kHz output resampled to 48 kHz,
  as *played*). Plus `transcript.jsonl` (both sides, per utterance:
  `{speaker, text, start_ms, end_ms}` on the recording timeline) and
  `events.jsonl` (state transitions, ledger, defers, flags — the actor's
  event log verbatim).
- **Alignment (review finding 6)**: writes are by **presentation timestamp**
  from the session's monotonic media clock; gaps are **zero-filled**, never
  dropped-and-closed-up — dropping from one channel shifts every subsequent
  sample and permanently desyncs the pair and every transcript timestamp.
  Vendor/browser clock drift is measured continuously (RTP timestamps vs local
  clock) and reconciled at mux time (per-channel drift correction ≤ a few ms/h
  via occasional sample insert/drop at zero-crossings, logged).
- **Truncation truth (review finding 5)**: the right channel records only up to
  `heardMs` per response item (playout-tracker value from browser heartbeats),
  zero-filled beyond — the recording, the vendor's history, and the transcript
  all agree on what was actually heard.
- **Off the critical path**: recorder is a per-session writer goroutine fed by
  bounded channels; overflow ⇒ silence-fill + counter, never backpressure on
  the media path. Like a logger/tracer: its failure degrades the bundle, never
  the session.
- **Crash safety**: write raw `audio.pcm.part` + `audio.meta.json` (format,
  channel map, start ts); finalize to WAV (header fixup) on clean close. On
  engine start, a recovery sweep finalizes orphaned `.part` files, uploads
  them, and fires late ingest notifies.
- **Upload lifecycle**: FINALIZING → S3 multipart under
  `s3://{bucket}/sessions/{session_id}/{audio.wav, transcript.jsonl,
  events.jsonl}` with retry/backoff; on persistent failure, spool to local disk
  and drain on next start. Ingest notify (§8.2) only after all objects land.
- **Rides along for grading**: everything in the §8.2 payload — turn table
  with `probed_skill`, defer/fallback flags, ceiling flags, unlock flip,
  suppressed answers, ledger timeline (in events.jsonl), metrics, degradations.

---

## 10. CI — extending `scripts/check.sh`

`check.sh` already auto-detects Go files, but runs `go vet ./...` from the repo
root, which fails once the module lives at `engine/`. Change the Go block to
target the module:

```bash
# scripts/check.sh — go section becomes:
if [[ -f engine/go.mod ]]; then
    if command -v go >/dev/null 2>&1; then
        run "go format (gofmt)"  bash -c '[[ -z "$(gofmt -l engine)" ]] || { gofmt -l engine; false; }'
        run "go vet"             bash -c 'cd engine && go vet ./...'
        run "go build"           bash -c 'cd engine && go build ./...'
        run "go tests (-race)"   bash -c 'cd engine && go test -race ./...'
        run "go architecture"    bash -c 'cd engine && go test ./internal/arch'
        if command -v golangci-lint >/dev/null 2>&1; then
            run "go lint (golangci-lint)" bash -c 'cd engine && golangci-lint run --config ../.golangci.yml'
        else
            skip "go lint (golangci-lint)" "not installed (brew install golangci-lint)"
        fi
    else
        skip "go checks" "go toolchain not installed"
    fi
fi
```

Gates: gofmt, vet, build, `go test -race` (race detector always on in CI — this
codebase is all concurrency), architecture test, golangci-lint against the
staged `.golangci.yml`. Live vendor tests are tagged `//go:build live` and run
only under `scripts/check.sh --live` (`cd engine && go test -tags live
./...`), matching the Python convention that model calls cost money and are
opt-in.

**`internal/arch` asserts** (via `go list -deps -json ./...` + a small AST
pass):

1. No package outside `cmd/engined` imports `internal/vendor/…`,
   `internal/transport/…`, or `internal/store/…` (ports-only dependency rule —
   the Go mirror of "vendor SDKs only inside `llm/`").
2. `internal/ports` imports no other internal package.
3. `internal/session`, `internal/ledger`, `internal/gate`, `internal/stall`
   import only `ports`, `contract`, `obs`, stdlib.
4. `os.Getenv`/`os.LookupEnv` appear only in `internal/config` ("agents never
   read API keys").
5. No string literal matching `^(gemini-|gpt-|models/)` outside
   `internal/config` and `testdata/` ("model IDs are config, never hardcoded").
6. `time.Now`/`time.After`/`time.NewTimer` are not called in `internal/session`
   (Clock injection is mandatory, or turn-timing tests are permanently flaky).

---

## 11. Failure modes and degradation

| Failure | Detection | Behaviour |
|---|---|---|
| Speaker vendor WS drop / stall | read error, heartbeat gap, no-audio watchdog (5 s into a response) | Reconnect ≤ 2 attempts / 5 s: new session, re-inject `system_prompt` + ledger summary + last 4 turns (text); resume LISTENING. Else WINDING_DOWN with an in-character exit line from `stall_phrases` bank, full bundle upload, `end_reason: "error"` |
| Thinker timeout (per turn) | 700 ms deadline | Contract fallback directive (`on_unknown_question` / `on_pressure`) — persona-correct by construction; log `thinker_deadline_miss` |
| Thinker outage (session) | consecutive misses ≥ 3 | Disable DEFER path (pre-gate verdicts become CONFIDENT + re-assert ceiling item each low-ceiling probe); unlock assessment degraded (§7); session continues, flagged `degraded:thinker` |
| ASR/Transcriber outage | stream error / no partials while VAD-active | Pre-gate disabled (it needs partials); rely on system prompt + bonus tool-call + Judge; probed-skill labels fall back to Speaker's input transcription if available; flagged `degraded:asr` |
| Browser network loss | ICE disconnected | ICE restart 10 s window; then hold session 60 s for rejoin (persona "waits", `on_silence`); then abandonment path |
| UDP blocked | ICE failure at setup | WS/PCM fallback transport (higher latency accepted, logged) |
| Cost cap (config `SESSION_COST_CAP_USD`, default 5) or duration cap | cost meter (§12) | WINDING_DOWN: persona wraps in character ("I think I need to drop in a moment…"), full upload, `end_reason: "cost_cap"` |
| Abandonment | silence > `ABANDON_AFTER_S` (default 300) | apply `on_silence` once, then end + upload, `end_reason: "abandoned"` |
| S3 unavailable | upload retries exhausted | local spool, drain on next start; ingest notify deferred until objects land |
| Control-plane down at ingest | notify retries exhausted | spool the ingest payload; a startup sweeper retries; idempotency key makes duplicates safe |
| Echo self-interruption (finding 7) | — | Browser AEC required (`echoCancellation: true`) **and** server mic gate: while SPEAKING with `barge_in_allowed=false`, mic frames go to recorder+transcriber but not to the Speaker vendor; with `barge_in_allowed=true` we trust browser AEC plus an energy-vs-reference heuristic (mic energy must exceed a floor scaled by current persona playout level) before honouring barge-in. No Go AEC (AEC3 is C++; not worth CGo scope in v1) — OQ-1 |

---

## 12. Observability

Per session, emitted as metrics (OTLP/Prometheus) and summarized into ingest
`metrics`:

- **Latency**: histogram per hop of §1 (capture→decode, decode→vendor-send,
  vendor first-audio, playout), voice-to-voice p50/p95, stall-start latency,
  pre-gate verdict latency, thinker note latency.
- **Behaviour**: turns, defer rate, pregate_race_lost count, thinker deadline
  misses, stall-clip usage histogram (repeat detection), barge-ins with
  `sent_ms − heard_ms` delta, sentence-bound trims, re-assertions, contradiction
  aversions, walk-backs, unlock flip turn.
- **Quality of media**: packet loss, PLC activations, jitter-buffer depth,
  audio-drop counters per channel, recorder silence-fills, measured clock drift.
- **Cost**: metered per vendor from usage events where provided, else computed
  from audio seconds × configured rates (Gemini ≈ $0.005/min in, $0.018/min
  out; Thinker/Judge/ASR/TTS token- or minute-metered); running total drives
  the cost cap; final number in ingest.
- **Health**: goroutine count per session (leak canary), channel overflow
  counters, reconnect counts, degradation flags.
- **Logs**: `slog` structured, `session_id` on every line; the events JSONL is
  the authoritative per-session trace and ships in the bundle.

---

## 13. Testing strategy

**Offline (the bulk — runs in `check.sh`, no network, FakeClock everywhere):**

- Actor/state machine: table-driven transition tests; scripted
  FakeSpeaker/FakeTranscriber tapes drive full turn lifecycles: confident path,
  defer→note, defer→deadline-fallback, barge-in mid-answer, barge-in during
  stall, tool-call join, silence. Assert: no ghost timer fires, no stale audio
  after DRAINING, truncation ms == heartbeat-derived heard ms, event log exact.
- Race + leak: `go test -race`, `goleak`, 1000× session churn test.
- Pre-gate: fixture set of interviewer utterances (≥100, built from the sample
  persona's skills + paraphrases) with expected verdicts; precision/recall
  floor asserted (target ≥0.9 recall on ceiling-≤3 probes; misses are
  acceptable *only* because layer 6 catches what slips).
- Ledger: seeding, append, contradiction lookup, supersede, snapshot
  determinism (same inputs ⇒ byte-identical JSONL).
- Audio: resampler SNR benchmarks; jitter buffer under synthetic loss/reorder;
  PLC actually invoked on signalled loss; recorder sample-exact alignment
  fixtures (gap zero-fill, barge-in truncation, injected 50 ppm drift over a
  simulated hour ⇒ <10 ms desync); crash-recovery (`kill -9`, finalize sweep).
- Adapter conformance: one shared contract-test suite runs against FakeSpeaker,
  Gemini adapter (mocked WS), OpenAI adapter (mocked WS) — same semantics for
  inject/cancel/truncate/events.

**Live (`--live` tag, costs money):**

- Vendor smoke per adapter: opening line spoken; defer tool call observed at
  least once (bonus path); truncate honoured (vendor transcript matches).
- Latency measurement session feeding §1's budget with real numbers.
- Gemini 2.5 native audio vs 3.1 Flash Live A/B (prosody, async-tool support,
  hop-6 latency, cost) — decision memo.

**Persona fidelity (inherently fuzzy — measure, don't assert booleans):**

Harness: a scripted interviewer (text or TTS) runs a fixed probe script against
a live session on the sample contract; an offline rubric judge (mirroring
`tests/test_candidate_rubric.py` philosophy) scores each answer on:

- **Ceiling adherence**: judged depth ≤ ceiling per probed skill (report breach
  rate; gate on a threshold, e.g. ≤1 high-severity breach per 20 low-ceiling
  probes *after* walk-backs).
- **Vagueness** (finding 8): for `bluffs`-tier skills, answers must be scored
  vague/generic, not confidently specific — a *specific correct* answer and a
  *specific wrong-but-deep* answer both fail.
- **Consistency**: run the script twice on the same contract; diff the claims
  ledgers — seeded claims must match exactly; no intra-session contradictions
  without a `supersedes` walk-back.
- **Stall naturalness**: manual listen pass on stall-clip seams (voice match,
  OQ-2) — human ears, checklist, not automated.

Reports trend over time; thresholds gate releases, not every commit.

---

## 14. Step-by-step ToDos

Ordered; a task depends on all unchecked structure above it unless a `dep:`
says otherwise. Each is one focused piece of work with a "done when".

### Phase 0 — Walking skeleton and plumbing

- [ ] **1. Module + skeleton.** `engine/go.mod` (Go ≥1.23), package tree of §3
  with doc.go stubs, `cmd/engined` serving `/healthz`.
  *Done when:* `cd engine && go build ./...` and `go vet ./...` pass.
- [ ] **2. CI wiring.** Apply the §10 change to `scripts/check.sh` (module-aware
  go block, `-race`, arch test slot, `--config ../.golangci.yml`, live tag under
  `--live`).
  *Done when:* `scripts/check.sh` runs the go gates green alongside Python.
- [ ] **3. Config package.** All env/flags (`GEMINI_API_KEY`, `OPENAI_API_KEY`,
  `SPEAKER_MODEL_ID`, `THINKER_MODEL_ID`, `JUDGE_MODEL_ID`, `TTS_MODEL_ID`,
  `ASR_MODEL_ID`, S3 bucket/region, control-plane URL + shared secret, cost
  cap, timer defaults) parsed in `internal/config` only; typed struct out.
  *Done when:* unit tests pass with fake env; no default is a hardcoded model
  id elsewhere.
- [ ] **4. Contract types.** Structs matching
  `owner_handover/engine_contract_schema.json` (v1.0 fields now; v1.1 fields of
  §8.1 added in task 32), parse + validate + **major-version pinning**.
  *Done when:* the sample contract round-trips; a fabricated `v2.0` contract is
  rejected with a clear error.
- [ ] **5. Ports.** All interfaces + event/message types of §2 in
  `internal/ports`, doc comments per revive.
  *Done when:* compiles; `ports` imports no sibling package.
- [ ] **6. Fakes.** `internal/fakes`: FakeClock (manual advance, deterministic
  timer order), scripted FakeSpeaker/FakeTranscriber/FakeThinker (event tapes),
  in-mem Store, static ContractSource serving the sample contract.
  *Done when:* a smoke test drives one fake end-to-end.
- [ ] **7. Architecture test.** `internal/arch` per §10 (dep graph, env, model-id
  literals, `time.Now` ban in session).
  *Done when:* deliberately adding a vendor import to `session` fails the test.
- [ ] **8. Session manager + HTTP.** `POST /v1/sessions {candidate_id}` →
  ContractSource fetch → spawn actor (stub) → session id + transport-offer URL;
  `DELETE` stops it.
  *Done when:* create/stop against fakes leaves zero goroutines (goleak).

### Phase 1 — Actor, turn loop, **barge-in** (fakes only — barge-in is built here, early, because it exercises cancellation, draining, timers and truncation at once)

- [ ] **9. Actor loop.** One owner goroutine, message types + channel policies
  of §4, nested-select priority (control/timers before media), ctx cancellation
  with explicit unblock paths.
  *Done when:* 1000× start/stop churn is `-race`- and goleak-clean.
- [ ] **10. State machine + event log.** States/transitions of §4; every
  transition and decision emits a JSONL event.
  *Done when:* table-driven tests cover all legal transitions and reject
  illegal ones; event log matches golden files.
- [ ] **11. Timers.** Pause-before-answer (vendor-latency-compensated), pre-gate
  deadline, stall deadline, thinker deadline, silence, cost/duration caps — all
  via injected Clock, all cancelled on state exit.
  *Done when:* FakeClock tests prove zero ghost fires after barge-in and after
  session stop.
- [ ] **12. Playout tracker.** Sent-samples ledger per response item; playout
  heartbeat message (newest-wins) → `heardMs` extrapolation.
  *Done when:* unit test — send 5 s, heartbeat says 2.1 s played, barge-in ⇒
  `Truncate` called with 2100 ± one frame.
- [ ] **13. Barge-in end-to-end on fakes.** SPEAKING → DRAINING: cancel
  response, flush out-ring, truncate at heardMs, cancel all turn timers, log
  `barge_in`, land in LISTENING. Also: barge-in during STALLING, and
  `barge_in_allowed=false` (gate, no truncation, attempt logged).
  *Done when:* scripted tapes show zero stale frames post-drain and correct
  events for all three variants.
- [ ] **14. Backpressure.** Ring buffers + drop counters per §4 table;
  never-drop control path proven under overload.
  *Done when:* overload test drops audio frames only; control/timer messages
  100% delivered.
- [ ] **15. Turn lifecycle (confident path).** LISTENING → PRE_ANSWER →
  SPEAKING with sentence-bound trim, turn records, `probed_skill` slot (stub
  classifier).
  *Done when:* a full fake conversation produces a correct turn table.

### Phase 2 — Real media path and Speaker vendors

- [ ] **16. Pion WebRTC transport.** Offer/answer endpoint, Opus track each
  way, data channel (control + playout heartbeats every 250 ms), ICE servers
  from config.
  *Done when:* a throwaway browser page loopbacks audio through the engine.
- [ ] **17. CGo Opus + jitter buffer.** libopus decode/encode (CGo), a real
  jitter buffer (not `SampleBuilder`) with loss signalling into the decoder so
  PLC/FEC actually engage.
  *Done when:* 5% synthetic loss yields continuous PCM with nonzero PLC
  counter; buffer depth metric exported.
- [ ] **18. Resampler.** 48k↔16k and 24k→48k; benchmark speexdsp (CGo) vs best
  pure-Go candidate, pick by SNR + p99 cost; document the CGo/cross-compile
  consequence (task 57).
  *Done when:* benchmark committed; chosen impl <1 ms/20 ms-frame p99.
- [ ] **19. WS/PCM fallback transport.** Same `Transport` port; auto-selected
  on ICE failure.
  *Done when:* loopback works with UDP blocked (packet-filter sim).
- [ ] **20. Gemini Live Speaker adapter.** WS session: verbatim
  `system_prompt` injection, voice-directive mapping, 16 kHz in / 24 kHz out,
  transcript + usage events, defer tool declared, interruption/truncation
  semantics mapped to the port, read-deadline-based cancellation.
  *Done when:* live smoke (`-tags live`) speaks the sample `opening_line` and
  answers one question end-to-end through a real browser.
- [ ] **21. Echo defence.** Mic gate per §11 (`barge_in_allowed=false`: gate to
  vendor, still record/transcribe) + energy-vs-reference heuristic for the
  `true` case.
  *Done when:* speaker-on-loudspeaker loopback session produces zero
  self-interruptions across 10 persona answers.
- [ ] **22. Per-hop latency instrumentation.** Timestamps at every §1 hop
  boundary, histograms in `internal/obs`, voice-to-voice derived metric.
  *Done when:* a live session prints the §1 table with real numbers.
- [ ] **23. OpenAI Realtime Speaker adapter.** Port parity incl.
  `conversation.item.truncate(audio_end_ms)` and the
  function-call-terminates-response flow (send `function_call_output` +
  `response.create`).
  *Done when:* the shared adapter conformance suite passes both adapters;
  live smoke green; switching vendors is a config change only.
- [ ] **24. TURN.** coturn (or managed) config, credentials from config,
  mobile-network test.
  *Done when:* session establishes on a TURN-only (UDP-blocked, NATed) network
  sim.

### Phase 3 — Pre-gate, stall bank, Thinker

- [ ] **25. Transcriber port + OpenAI transcription adapter.** Independent
  transcription session (`type: "transcription"`), 24 kHz feed, live partial
  deltas, `delay` tier from config.
  *Done when:* live test shows partials trailing speech by <500 ms.
- [ ] **26. Local ASR spike.** whisper.cpp vs Vosk vs Moonshine behind the same
  port: partial latency, WER on interview audio, CPU per stream at 50 sessions.
  *Done when:* decision memo with numbers appended to §15 / OQ-3; loser code
  deleted or parked.
- [ ] **27. Deterministic pre-gate.** Incremental `pregate_lexicon` matching
  over partials (dep: task 32 for the field; until then, derive a lexicon from
  the sample contract in testdata), verdict CONFIDENT/DEFER, 250 ms
  post-end-of-turn deadline with lost-race fallback + event.
  *Done when:* fixture suite (≥100 utterances) hits agreed precision/recall;
  FakeClock test proves deadline behaviour.
- [ ] **28. Stall bank + opening line.** At contract load: synthesize
  `stall_phrases` + `opening_line` via TTS port with `tts_voice_id` (== Speaker
  voice), cache PCM in memory; picker avoids immediate repeats; GREETING plays
  the pre-synth opening line after the interviewer's first utterance.
  *Done when:* DEFER → first stall sample at transport <50 ms (FakeClock +
  bench); manual listen confirms no voice seam (OQ-2 checkpoint).
- [ ] **29. Thinker adapter.** Continuous speculative operation: persona
  context + ledger at `Reset()`, `FeedPartial` streams the question in,
  `RequestNote(deadline)` returns structured JSON `{note, claims_to_make,
  claims_made(prev turn), unlock_assessment, confidence}`; cancel/restart on new
  utterance; never a cold call.
  *Done when:* fed a typical 8 s question via fakes, a note is ready before
  end-of-turn in ≥80% of fixture runs (model-latency simulated), and live
  smoke produces well-formed JSON.
- [ ] **30. Defer flow integration.** Wire §4 steps 3–5: DEFER → stall →
  note-inject → `CreateResponse`; deadline miss → `on_unknown_question` /
  `on_pressure` directive; silence-after-stall accepted (no filler loop).
  *Done when:* scripted tests cover note-in-time, deadline-miss, and barge-in
  during STALLING; live session audibly stalls then answers in character.
- [ ] **31. Model tool-call defer (bonus path).** Tool declared to the Speaker;
  a call joins the DEFERRED flow (response already terminated per vendor
  semantics).
  *Done when:* live Gemini test triggers it at least once; disabling the tool
  entirely changes no offline test outcome (proving we never rely on it).

### Phase 4 — Ledger, ceilings, unlock (control plane first)

- [ ] **32. Control plane: contract v1.1.** Add `precompiled_beliefs`,
  `stall_phrases`, `pregate_lexicon`, `unlock_spec`, `tts_voice_id` to the
  Pydantic contract models + deterministic compilation in
  `candidate_agent/engine_contract.py` (belief/lexicon content authored at
  design time, keyed off `seed_fingerprint`, frozen under `fingerprint`);
  regenerate `owner_handover/engine_contract_{schema,sample}.json` via
  `scripts/export_schemas.py`; update okf concept + `okf/concepts/determinism.md`
  + `okf/log.md`.
  *Done when:* `scripts/check.sh` fully green on the Python side; sample shows
  the new fields; engine task 4 structs extended and version bumped.
- [ ] **33. Claims ledger.** `internal/ledger` per §5: seed from
  `precompiled_beliefs`, actor-only writes, canonicalization, contradiction
  lookup by skill, `supersedes`, JSONL events, deterministic snapshot.
  *Done when:* unit tests incl. byte-identical snapshots for identical inputs.
- [ ] **34. Ledger → both models.** Full ledger into Thinker context at
  `Reset()`; compact "what you've said" system item to the Speaker every N
  turns and with every defer injection; contradiction guard downgrades notes.
  *Done when:* offline tests show the guard averting a planted contradiction;
  live session log shows the injected items.
- [ ] **35. Ceiling re-assertion cadence.** Layer 4 of §6: every N turns and on
  every pre-gate low-ceiling probe.
  *Done when:* event log shows re-assertions exactly at policy points in a
  scripted 20-turn run.
- [ ] **36. Unlock evaluation.** §7: `unlock_spec` kinds, Thinker
  `unlock_assessment`, actor-owned monotonic flip, `unlock_flipped{turn,
  evidence}` event, depth directive switch, degraded path.
  *Done when:* tests cover `never` (sample contract — no assessments run),
  conditional-met, conditional-never-met, thinker-outage.
- [ ] **37. Async Judge.** `internal/judge`: per persona turn submit
  (question, answer, skill, ceiling, beliefs, ledger extract) → seconds-late
  verdict `{breach, severity, rationale, walkback_hint}`; results into events +
  ingest `ceiling_flags`; never blocks the media path.
  *Done when:* eval set of ≥20 labelled turns (breaches incl. *semantic-depth*
  ones, clean, and correctly-vague) meets agreed precision; latency irrelevant
  by design.
- [ ] **38. Walk-back.** Config-gated: on a high-severity flag, inject a
  next-turn in-character recant directive; ledger `supersedes`; linkage in
  `ceiling_flags.walked_back_turn`.
  *Done when:* live test yields an audible in-character walk-back and correct
  ledger/event linkage.

### Phase 5 — Recording, S3, ingest

- [ ] **39. Stereo recorder.** §9: presentation-timestamped writes, zero-fill
  gaps (never close-up), dedicated writer goroutine, silence-fill on overflow,
  L=human/R=persona at 48 kHz.
  *Done when:* fixtures with gaps and overlaps decode to sample-exact expected
  waveforms (marker-tone test).
- [ ] **40. Heard-truth right channel.** Right channel truncated at `heardMs`
  on barge-in (dep: 12/13), zero-filled remainder.
  *Done when:* barge-in fixture shows recording, transcript timestamps, and
  truncation event all agreeing to ±one frame.
- [ ] **41. Crash-safe finalize.** `.pcm.part` + sidecar → WAV header fixup on
  close; startup recovery sweep finalizes, uploads, late-notifies.
  *Done when:* `kill -9` mid-session test recovers a playable, aligned file on
  restart.
- [ ] **42. Drift reconciliation.** Continuous drift measurement, mux-time
  correction, drift metric.
  *Done when:* injected 50 ppm drift over a simulated hour leaves <10 ms
  channel desync.
- [ ] **43. Transcript + events JSONL.** `internal/transcriptlog`: both sides
  on the recording timeline; events JSONL is the actor log verbatim.
  *Done when:* a replayed fixture session produces a bundle where every
  transcript span lands inside its audio span.
- [ ] **44. S3 store.** Multipart upload, retry/backoff, local spool + startup
  drain, bundle layout of §9.
  *Done when:* injected 503 storms still land the bundle; spool drains after
  restart.
- [ ] **45. Control plane: ingest endpoint.** §8.2: Pydantic models, handler on
  a narrow port (passes `tests/test_architecture.py`), idempotent on
  `session_id`, triggers grading; `export_schemas.py`; okf concept page +
  `okf/log.md` line.
  *Done when:* Python tests green; `scripts/check.sh` green.
- [ ] **46. Ingest notify client.** `internal/controlplane`: retry/backoff,
  idempotency key, spool-on-failure, fires only after all S3 objects land.
  *Done when:* duplicate notify proven idempotent; control-plane-down test
  drains on restart.

### Phase 6 — Degradation, fidelity, A/B

- [ ] **47. Vendor reconnect.** §11 row 1: context rebuild (system_prompt +
  ledger summary + last turns) inside 5 s, else graceful in-character end +
  full upload.
  *Done when:* kill-the-vendor-WS-mid-answer test recovers or ends cleanly with
  a complete bundle, never a hang.
- [ ] **48. Thinker/ASR degradation.** §11 rows 3–4: degraded modes, flags in
  ingest `degradations`, session survives.
  *Done when:* fault-injection tests pass for both, with correct flags.
- [ ] **49. Caps + abandonment.** Cost meter wired to caps; WINDING_DOWN
  in-character wrap; silence abandonment via `on_silence`.
  *Done when:* simulated overrun and 300 s silence both end with full bundles
  and correct `end_reason`.
- [ ] **50. Persona fidelity harness.** §13: scripted interviewer probe script,
  rubric judge scoring ceiling adherence / vagueness / consistency,
  seed-replay ledger diff, report artifact; runs under a live flag.
  *Done when:* harness produces a scored report on the sample contract twice
  and the seeded-claims diff is empty.
- [ ] **51. Speaker A/B.** Gemini 2.5 native audio vs 3.1 Flash Live (prosody
  by ear + fidelity harness, async-tool availability, hop-6 latency, cost) and
  a check against OpenAI mini as the outside option.
  *Done when:* decision memo with numbers; `SPEAKER_MODEL_ID` default set
  accordingly.

### Phase 7 — Hardening, scale, ship

- [ ] **52. 50-session soak.** Synthetic browser peers (headless loopback
  clients) on one node; CPU/mem/goroutines/latency under load; tune ring sizes.
  *Done when:* p95 voice-to-voice <800 ms at 50 concurrent sessions for 60
  min; zero goroutine growth; all 50 bundles land.
- [ ] **53. Chaos pass.** Packet loss bursts, vendor stalls, slow S3, clock
  jumps (NTP step), OOM-adjacent memory pressure.
  *Done when:* no crash, no hung session, every session ends in DONE with a
  bundle or a spooled bundle.
- [ ] **54. Observability finish.** §12 complete: metrics endpoint/OTLP export,
  per-session cost in ingest, dashboard/alert list documented (latency p95,
  breach rate, deadline-miss rate, spool depth).
  *Done when:* one live session's full §12 set is visible end to end.
- [ ] **55. Security pass.** gosec clean; keys only via `internal/config`;
  ingest auth (shared secret or mTLS — OQ-6 decided); TURN credential rotation;
  recording PII/retention posture documented.
  *Done when:* checklist reviewed with the owner; gosec green in CI.
- [ ] **56. Build/deploy pipeline.** CGo-aware builds (dockerized or zig cc)
  for linux/amd64 + arm64, Dockerfile, version stamped into ingest
  `engine_version`.
  *Done when:* CI produces both images; a container passes the live smoke.
- [ ] **57. okf + docs closeout.** Engine concept pages (architecture, actor
  model, ledger, recording), `okf/concepts/repo-map.md` routes `engine/`
  paths, ops runbook; `okf/log.md` lines for every change per the maintenance
  runbook.
  *Done when:* the okf maintenance checklist passes; a newcomer can route from
  any `engine/` path to the right page.

**58 tasks. Sequencing summary**: 32 (contract v1.1) blocks 33–36 and the final
form of 27/28; 45 (ingest endpoint) blocks 46; barge-in (13) lands in Phase 1
against fakes and is re-verified against real vendors in 20/23; nothing in
Phases 0–1 needs a network.

---

## 15. Open questions / risks needing a human decision or a spike

| # | Question / risk | Why it matters | Proposed default |
|---|---|---|---|
| OQ-1 | **Trust browser AEC for barge-in?** Users on laptop speakers without headsets will echo; server heuristic (§11) is crude; no Go AEC exists without C++ CGo scope. | Wrong call ⇒ persona interrupts itself or real barge-ins are eaten. | v1: require `echoCancellation:true`, ship the energy heuristic, show a "headset recommended" UI hint; revisit AEC3 CGo only if soak data demands it. |
| OQ-2 | **Stall-clip voice seam.** TTS voice must be indistinguishable from the Speaker's live voice; same-named voices across Gemini TTS and Live are *probably* close but unverified. | A seam breaks immersion at the exact moment the persona is "thinking". | Spike in task 28: synthesize + listen; if seamy, fall back to capturing the Speaker model's own audio for stall phrases in a warm-up turn at session start (costlier, guaranteed match). |
| OQ-3 | **ASR choice** (OpenAI transcription session vs whisper.cpp/Vosk/Moonshine). Owner wants open-source/cheap; local ASR at 50 streams/node is a real CPU bill. | Pre-gate reliability and per-session cost. | Task 26 spike decides with numbers; OpenAI adapter ships first so Phase 3 is never blocked. |
| OQ-4 | **Judge calibration.** Semantic-depth breach detection precision, model choice, and whether walk-backs default on. Too eager ⇒ personas constantly recanting; too lax ⇒ finding 1 unfixed. | The only guaranteed ceiling layer. | Task 37 eval set gates it; walk-back on but severity-gated to `high`; grader always sees raw flags either way. |
| OQ-5 | **Who authors `pregate_lexicon`/`precompiled_beliefs` content at design time?** It's model-authored in the Python casting flow (fine — design-time, frozen under `fingerprint`) but quality varies. | Bad lexicon ⇒ pre-gate misses; bad beliefs ⇒ flat persona. | Casting-time generation + the existing offline rubric extended to score them (Python side, task 32). |
| OQ-6 | **Engine ↔ control-plane auth** for contract fetch + ingest (shared secret vs mTLS), and where the engine runs relative to the control plane. | Ingest carries the grading ground truth. | Shared bearer secret in v1, mTLS when multi-node lands. |
| OQ-7 | **`unlock_condition` prose → `unlock_spec` compilation fidelity.** Misclassifying a conditional persona as `never` silently deletes a product feature. | Unlock timing is a headline feedback signal. | Compile with the casting model, verify with the rubric test, log both prose and spec in the contract. |
| OQ-8 | **Gemini session-length / reconnect limits** (live sessions have duration caps and resumption tokens whose behaviour under our reconnect flow is unverified for long interviews, 45–60 min). | Mid-interview identity loss. | Spike inside task 20: verify session resumption vs our context-rebuild path; prefer vendor resumption when available. |
| OQ-9 | **CGo cross-compilation cost** (libopus, maybe speexdsp, maybe whisper.cpp): slower CI, dockerized builds, platform matrix. | Team velocity + CI time. | Accepted in §14 task 56; keep CGo confined to `internal/audio` + `vendor/localasr` so a pure-Go fallback path stays possible. |
| OQ-10 | **Recording consent/retention.** Sessions record a real human's voice to S3. | Legal/product, not engineering. | Owner decision before first external user; engine ships retention-tag support on the bucket layout. |

### Three biggest risks (opinionated)

1. **Hop 6 (vendor end-of-turn → first audio) blows the 800 ms budget** on real
   networks — everything we control sums to ~200 ms; if Gemini's p95 is 600 ms+
   the target slips and only vendor choice (A/B, task 51) fixes it.
2. **Semantic ceiling drift** stays the product's soft underbelly: layers 1–5
   are best-effort, and the Judge only *labels*. If breach rates in the fidelity
   harness are high, the product needs the walk-back path to work well — which
   is itself a naturalness risk.
3. **Stereo recording integrity** under barge-in + drift + crash is where
   silent data corruption lives; it is the grading ground truth, and a subtle
   desync poisons every downstream feedback report. Hence tasks 39–43 carry the
   strictest sample-exact tests in the plan.
