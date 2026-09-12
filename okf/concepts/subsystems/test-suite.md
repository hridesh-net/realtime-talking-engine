---
type: Subsystem
title: Test suite
description: Offline checks that enforce architecture and determinism, plus live scenario scripts that call the model.
resource: /tests
tags: [tests, pytest, architecture, determinism]
generated:
  by: claude-opus-5
  at: "2026-09-10T19:00:00Z"
verified:
  - by: claude-opus-5
    at: "2026-09-10T18:00:00Z"
  - by: claude-opus-5
    at: "2026-09-10T12:00:00Z"
  - by: claude-opus-5
    at: "2026-09-10T00:00:00Z"
  - by: claude-opus-5
    at: "2026-08-23T19:30:00Z"
  - by: claude-opus-5
    at: "2026-08-23T18:00:00Z"
  - by: claude-opus-5/okf-curator
    at: "2026-08-22T17:05:00Z"
status: stable
sources:
  - resource: /tests/infra.py
  - resource: /tests/conftest.py
  - resource: /tests/test_migrations.py
  - resource: /tests/test_object_store.py
  - resource: /tests/test_architecture.py
  - resource: /tests/test_candidate_rubric.py
  - resource: /tests/test_session.py
  - resource: /tests/test_voice.py
  - resource: /tests/test_gemini_live_mint.py
  - resource: /tests/test_recording.py
  - resource: /tests/test_portal_compat.py
  - resource: /tests/test_candidate_agent.py
  - resource: /tests/test_expectation_agent.py
---
# Test suite

> **`tests/test_analysis_agent.py`** (19 tests) covers the analysis harness
> without a model or an API key: where a window's timestamps land, which anchors
> are rejected, and the 60/40 weighting — including the case the design exists
> for, that a manager who read the room and closed early is not marked down for
> coverage.
>
> **`tests/test_report_engine.py`** (38 tests) covers the report engine and the
> control-plane seam: determinism on both JSON and HTML, question typing
> including the unpunctuated shapes ASR produces, the restraint-persona rule,
> the two operator toggles, and composed-persona resolution.
>
> **`tests/test_report_judge.py`** (25 tests) covers what the judge veto lets
> through. A judge cannot be pinned by byte-identical regression, so what is
> pinned instead is the boundary: a fabricated span is dropped and the claim with
> it, a `surfaced` verdict credited to the manager's own words is refused, prose
> stating a number falls back to the composed sentence, and the judge cannot add
> a finding code did not select. Every test drives `judge.overlay` — the whole
> judge minus the network hop — with hand-written model output, so no model is
> called and none is needed.

Two kinds of test, and the distinction matters: the offline ones defend rules,
the live ones check model behaviour and cost money.

## Offline — run always

### `tests/test_architecture.py` (350 ln)

SOLID and layering as failing tests (BRD NFR-003). AST-based, parametrized over
every module. Full breakdown in [Architecture](/concepts/architecture.md).

The standout is `test_ocp_new_provider_needs_no_agent_change` /
`test_ocp_new_archetype_needs_no_agent_change`: they *register* a new provider
and archetype at runtime and prove the system absorbs them, rather than asserting
that extension is theoretically possible.

### `tests/test_candidate_rubric.py` (401 ln)

The real safety net for the persona pipeline. Groups:

* **Catalog integrity** — scorecard weights sum to 1.0 per archetype; archetypes are well-formed; exactly two defaults, one of each verdict; the catalog covers the intended space; the payload is serializable.
* **Determinism** — traits land inside archetype bounds; the same seed reproduces the same person; different interviews produce different people; `smartness_ratio` points the same direction as the verdict.
* **Clamping and repair** — the model cannot exceed the knowledge band; missing and renamed skills are restored; adjacent strength survives only where allowed.
* **Scorecard** — catalog ids and weights survive; model wording is used only when ids match.
* **Language and operator notes** — every language reaches both the casting prompt and the compiled contract; a hostile `persona_notes` stays subordinated in the prompt and the knowledge clamp holds regardless.
* **Engine contract** — self-consistency (`min ≤ target ≤ max`, ceilings present); the system prompt carries the behavioural contract; **the system prompt is byte-stable**.
* **The voice matches how the persona presents** (v1.5) — a `woman` persona compiles a `tts_voice_id` in the female set and a `man` persona one in the male set, checked over 200 candidate ids rather than one because `pick_voice` is a modulus and a single id could pass by luck; `non_binary` and `unspecified` draw from the whole roster unchanged; the filter preserves roster order; and the choice is still deterministic for a given `(candidate_id, presentation)`.
* **The trait-less cast path too** (v1.6) — a full `agent.generate` against a fake casting model: a draft declaring `presented_gender` gets a matching voice with `human_traits=None`, `neutral`/absent leaves the unfiltered pick alone, code-owned traits beat a conflicting declaration, and a bad enum value degrades to the full roster without raising. Cast over **eight** interview ids whose unfiltered picks are deliberately mixed male and female, plus an explicit `assert moved` that the filter changed at least one — a single id would have landed on the right gender by luck half the time, which is exactly how the production bug survived v1.5's tests.
* **Validation** — resume claims reject bad truthfulness values.

### `tests/test_session.py` (280 ln)

The live text session, entirely offline: a `FakeChatModel` records the exact
call, and the endpoints run under `TestClient` with `get_repo` and
`get_session_agent` overridden. Groups:

* **The agent** — the contract's `system_prompt` reaches the model unedited; the text-mode preamble and the turn-policy length rule are present; roles map and order is preserved; the scene-setting turn is prepended only when the transcript opens on the candidate; an empty transcript raises; the agent holds no state but its model.
* **Storage** — turn 0 is the opening line at `elapsed_ms = 0`; indexes and timestamps advance; re-ending a session does not move `ended_at`; appending to an unknown session raises.
* **Endpoints** — the full round trip (start → turn → end → fetch), 409 on a finished session, 404 on an unknown interview, 422 on an unknown archetype.

The persona fixture is **built in code**, not cast — the casting agent is not
exercised here, so nothing in this file can reach the network.

### `tests/test_voice.py`

The voice session, offline — the broker is faked, so no audio and no vendor call.
The point it defends: **everything this service decides about a voice session is
decided before the vendor is involved**, and is therefore testable here.

* **Compilation (OpenAI)** — voice is stable per persona and spread across personas; the contract prompt reaches the instructions verbatim; pace drives speed and eagerness; `may_interrupt` overrides pace; an unknown pace falls back instead of raising; the transcriber is injected rather than hardcoded, and is handed a vocabulary hint composed from the contract's skills; the model hears a denoised mic.
* **Compilation (Gemini)** — the same prompt verbatim plus the opening line; the stored `tts_voice_id` is what the session speaks in, falling back to the same `pick_voice` rule; VAD silence tracks pace and stays inside 500–800 ms; both transcriptions, resumption and the history flag are present.
* **The opening line** — it reaches the instructions on both providers, and a contract without one gets no block at all (so hand-built contracts still compile).
* **Dispatch** — `build_voice_session` returns the shape the named provider speaks, passes the configured transcriber through, and raises `ValueError` on a provider nobody can compile for rather than guessing.
* **One voice roster** — `llm.gemini_live.GEMINI_LIVE_VOICES` *is* `engine_contract.GEMINI_TTS_VOICES` (identity, not equality), 30 names.
* **The roster's gender sets partition it** — `GEMINI_FEMALE_VOICES` (14) ∪ `GEMINI_MALE_VOICES` (16) is the roster, and they are disjoint. A voice appended to the roster without a classification fails here rather than becoming unreachable for gendered personas.
* **Two invariants no persona may switch off** — the human can always interrupt (`interrupt_response` / `START_OF_ACTIVITY_INTERRUPTS`), and their speech is always transcribed.
* **Storage** — a voice session does not pre-write turn 0; a text one still does.
* **Endpoints** — minting seals the persona and never leaks the prompt *or the opening line* into the response, on either provider; the Gemini response carries `client_config` and an empty `call_url`, the OpenAI one carries the STT model and `near_field`; transcript records without generating; a bad speaker label is 422; a finished session refuses both mint and transcript; a deleted persona is 410 while the session survives; a vendor failure is 502; `voice-capability` answers rather than raising and names both keys.

### `tests/test_gemini_live_mint.py` (`--live`)

Not a scenario — one mint against the real Live API, to check the vendor still
accepts a whole `LiveConnectConfig` inside `live_connect_constraints` on the
configured model id. That is the one thing the offline suite cannot see: it
passes either way, and the failure lands in the browser. Skips cleanly without
`GEMINI_API_KEY`.

### `tests/test_key_failover.py`

The [second Gemini key](/concepts/subsystems/llm-port.md#two-gemini-keys-one-silent-failover-2026-09-01),
offline — no vendor, no network, no key. Everything failover decides is decided
before an SDK is involved.

* **Classification** — the seven vendor phrasings that mean the credential failed (`RESOURCE_EXHAUSTED`, `PERMISSION_DENIED`, an invalid or expired key, a rate limit, `401 Unauthenticated`), and the five that mean the *request* failed (`INVALID_ARGUMENT`, unparseable JSON, an empty reply, `500`, `503`) and must therefore never be retried. A status code on the wrapped vendor exception classifies even when the message is terse.
* **Two near-misses, asserted in both directions** — the substring "rate" appears inside `generate_content`, which is in every Gemini error message, so matching it would fail over on malformed requests; and a bare `429` classifies while `4291` in a request id does not.
* **Behaviour** — a rate-limited primary answers from key 2; the *next* call skips the dead key entirely; stickiness survives a rebuild, because `build_model` runs per agent; a non-key error propagates with key 2 never called; the last key's failure is raised unchanged; and the wrapper reports the inner model's `provider`/`model_id`/`temperature`.
* **The factory** — one key returns the bare adapter, two build one adapter per key in order, a whitespace-only second key is not a key, and `GEMINI_API_KEY2` alone leaves the provider unconfigured.

### `tests/test_migrations.py` — the first suite that needs a server

Everything else in this directory is offline. This one needs a real Postgres,
because what it checks cannot be faked: the DDL has to be executed by the
engine that will execute it in production.

* **The runner** — a fresh database gets the whole schema; the ledger records the file's sha256; `--check` is clean afterwards; re-applying returns `[]` and adds no row; an extra file is **pending** (exit 1) while an edited or deleted applied file is **drift** (exit 2); `assert_current` names the pending file.
* **A migration that fails midway records nothing for itself.** The file is one transaction, so a `0002` whose second statement raises leaves `0001` applied, `0002` unrecorded, and the table its first statement created absent.
* **The advisory lock serialises two runners.** The migration sleeps, so the second thread is guaranteed to arrive mid-transaction. Without `pg_advisory_xact_lock` it would read an empty ledger and run the same `CREATE TABLE` — the test would then see a duplicate-relation error or two ledger rows. This is a test that can fail, not a description of a mechanism.
* **The two foreign-key decisions.** `sessions.candidate_id` and `interview_assignments.candidate_id` have **no** FK constraint, `sessions.interview_id` does; deleting an interview cascades to sessions, turns and personas; deleting a *persona* leaves the session and its transcript standing; and the candidate primary key can be rewritten out from under a session. SQLite ignored all of this, so nothing else in the suite can notice a tidy-minded edit that adds the constraint back.
* **The type mapping** — the JSON columns really are `jsonb`, the timestamps really are `timestamptz`, `language_gate` is `boolean`, `byte_size` is `bigint`, and a `skills_required` written as an object is rejected by its `jsonb_typeof` CHECK.

### `tests/infra.py` and `tests/conftest.py` — where the server comes from

`infra.py` is the single provisioning helper, used by both `conftest.py` and
`scripts/check.sh`. If `TEST_DATABASE_URL` (and `TEST_S3_*` for the object
store) are set it provisions **nothing** and uses them; otherwise it starts
throwaway `postgres:16-alpine` and `minio` containers with **Apple
`container`** — never Docker, which is not installed in this project;
`docker.io/...` in the image names is a registry hostname, not a runtime. It
does **not** start the runtime itself: `container system start` is a
machine-level action with a one-time kernel download behind it, so an
unavailable runtime raises `InfraUnavailableError`, which `check.sh` turns into
**NOT RUN**. `python -m tests.infra up [postgres|s3|all]` prints `export` lines plus a
`TEST_INFRA_HANDLE`; `python -m tests.infra down <handle>` stops what it
started. `check.sh` asks for `all` since 2026-09-10, when
`tests/test_object_store.py` gave it a suite that needs the object store; it
asked for `postgres` alone before that, and the rule behind both is the same —
a gate must not be held up by infrastructure none of its suites touch, and must
not run without infrastructure one of them does. **Containers are reached on their own IP, not a published host port.** Apple
`container` 1.2.0 accepts `-p 127.0.0.1:<host>:<guest>` and even binds a
listener that completes a TCP handshake, but the forwarded connection is
dropped the moment a real protocol exchange starts. Measured on 2026-09-10:
`nc` reported the host port open while `psycopg` on that same port failed with
"server closed the connection unexpectedly", and the container's own log said
`database system is ready to accept connections` — the server was fine, the
forwarder was not. `infra.py` therefore publishes no ports at all and reads
`.status.networks[0].ipv4Address` from `container inspect`, which also removes
the free-port race that publishing needed. A host-port binding that handshakes
and then fails is worse than one that refuses outright: it makes a readiness
probe that only opens a socket report success.

`temporary_database()` is the same thing for one scratch database,
migrated and dropped, for the live scenario scripts.

Two decisions in `conftest.py` worth keeping:

* **Every fixture is lazy.** Nothing is provisioned, connected to or created until a test asks for it, so `pytest tests/test_voice.py` on a laptop with no container runtime behaves exactly as it did before these files existed.
* **Isolation is `TRUNCATE ... CASCADE`, not a database per test.** A database per test is cleaner and costs about a second each — `CREATE DATABASE` copies a template and every connection is re-established — which would put the Python gate minutes behind. The whole gate is meant to stay near thirty seconds. The schema is created once per session, by running `migrate.apply` rather than loading a dump, so **every run exercises the migration path itself**.

`InfraUnavailableError` is deliberately allowed to propagate out of the session
fixture rather than becoming a `pytest.skip`: a database-backed suite that
cannot reach a database must never report itself as passed.

The SQLite suites are untouched — they still build their own
`init_db(":memory:")` connections. Rewriting them onto the pool lands with the
repository switch.

### `tests/test_object_store.py` — one contract, both adapters, a real MinIO

The second suite that needs a server, and the reason it needs a real one is the
same as the migrations': what it checks cannot be faked. Almost every test is
parametrized over `FilesystemObjectStore` and `S3ObjectStore`, because the
point of the port is that the deployed service and a laptop with no bucket
behave identically — a test that ran against one of them would let the two
drift and stay green.

* **The contract, on both** — put/open round trip; the content type comes back out; put overwrites; a missing key is `None` (not an exception); the five range cases (start only, start+end inclusive, a single byte, an end past EOF clamped, a start beyond EOF empty); a negative bound raises; an empty object reads empty at any range; and the same illegal keys are refused by both (`..`, an absolute key, an empty segment, the content-type sidecar suffix).
* **A 9 MiB object, on both** — past boto3's own 8 MiB multipart threshold, with a ranged read that straddles the 8 MiB part boundary, where a multipart upload that lost or reordered a part reads fine at the head and wrong exactly there.
* **S3 only** — `S3_PREFIX` lands in the real object key (asserted against the bucket with a separate boto3 client, not by asking the adapter); the ETag of the 9 MiB object carries a part count (`<hex>-2`), which is the *evidence* the multipart path ran; and a missing bucket raises instead of reading as a missing object.
* **No stub, and no skip.** Without a reachable MinIO the S3 fixture raises: the S3 half ERRORs and the run is red (measured: 18 passed, 21 errors). A storage adapter checked against a fake proves only that the fake matches the fake.

### `tests/test_recording.py`

Session recording, offline — no audio codec, no network, no file-backed
database. Every test writes to `tmp_path` via
`InterviewRepository(conn, recordings_dir=tmp_path)`, the same way
`RECORDINGS_DIR` points the real service at disk, so nothing here touches the
repo's real recordings directory.

* **Adapter** — the first chunk creates the recording row and its file; chunks append in order and `byte_size` accumulates; an out-of-order `seq` raises; `finalize` is idempotent and does not move `updated_at` on a repeat call, or on an unknown session (returns `None`); a chunk after finalize raises; `get_session` carries `recording` and `list_sessions` flags `has_recording` correctly before and after the first chunk.
* **Endpoints** — the full round trip (three chunks → finalize → GET returns the concatenated bytes with the stored `Content-Type`); wrong seq is 409; a text session's chunk POST is 409; an unknown session is 404 on all three routes; a GET before any chunk landed is 404; an empty chunk body is 422.

See [Session recording](/concepts/contracts/session-recording.md) for what
each of these enforces and why.

### `tests/test_portal_compat.py`

The SkillBrew organization portal calls this service cross-origin through a
shared axios layer it does not own, and three additions in `main.py` and the
chunk handler meet it halfway. Every test here is really the same assertion
twice: the new behaviour exists, **and** what the console already sees is
untouched.

* **The error envelope** — a 404, a 409 and a 422 each carry `detail`, `status: false` and `message`; the 422's `detail` is still FastAPI's pydantic error *list* and every error's `loc` and `msg` appears in the one-line `message`; Starlette's own unmatched-route 404 is enveloped too (which only holds because the handler is registered on starlette's `HTTPException`, not FastAPI's subclass); a dict detail becomes a `json.dumps` message; an exception's headers survive; and 204/304 still carry no body.
* **Multipart chunks** — a three-chunk multipart upload and a three-chunk raw upload produce the same stored bytes, `mime_type`, `byte_size` and `next_seq`, and the same `Content-Type` back out of `GET .../recording`. The 409s (wrong seq, text session), the 404 (unknown session) and the 422 (empty part) are asserted on the multipart path as well, plus the 422 for a multipart body with no `chunk` field.
* **CORS** — `cors_allowed_origins()` trims and splits the list; a named origin gets a preflight and `access-control-allow-credentials: true` on both the preflight and the real response; an unnamed origin gets no header; and with the variable unset (with `load_dotenv` stubbed, so a developer's own `.env` cannot decide what "unset" means) **no** `access-control-*` header is emitted at all, because no middleware is installed.

Each of these was confirmed to fail against a deliberately broken
implementation before being kept — the envelope keys dropped, the `message`
blanked, the multipart branch removed, the part's content type ignored, the
body-suppression guard deleted, the headers dropped, CORS never installed, and
CORS installed unconditionally with a wildcard.

## Live — `scripts/check.sh --live`

Run as scripts, not through pytest:

```bash
.venv/bin/python tests/test_expectation_agent.py   # 5 job-spec scenarios
.venv/bin/python tests/test_candidate_agent.py     # 6 archetypes + determinism
```

The candidate suite asserts verdicts and traits come from the catalog, knowledge
stays under the ceiling, every required skill is covered, names are unique within
a training set, and the same seed reproduces the same person. The expectation
suite validates each generated document against the guardrails — including the
two (skill coverage, `min_duration_minutes` ceiling) that code does *not*
re-impose.

## The Go engine's suite

A separate module with its own gates, run from inside `engine/`. Roughly 270
tests across 15 packages, always under `-race`, with per-test
`goleak.VerifyNone` rather than a `TestMain` sweep — a leak should name the test
that caused it.

| Package | What its tests are for |
|---|---|
| `internal/arch` | The layering rules themselves, including synthetic fixtures that fail against the *old* code, so each rule is evidence a hole was real rather than a description of one |
| `internal/session` | The turn loop: state table, timers, barge-in, the connector's failure classification, and the media seam |
| `internal/audio` | The resampler measured against its quality bar (87–88 dB SNR, 111 dB out-of-band rejection, p99 70 µs/frame), onset detection, jitter concealment, the send ring |
| `internal/transport/wsfallback` | Ticketed attach over a real socket, resampling, heartbeats, and that `SendAudio` never blocks |
| `internal/vendors/gemini` | The Speaker adapter driven against a **local WebSocket**, so the riskiest package in the build tests offline; plus the repo's first `//go:build live` tests |
| `internal/vendors/{thinkerllm,judgellm,geminitts}`, `internal/stall` | Adapter behaviour over `httptest`, and the Judge's 25-case offline fixture |

Two conventions are load-bearing here. `internal/session` may not call
`time.Now`, `time.After` or `time.NewTimer` **even in tests** — the layering gate
enforces it — so turn timing is always driven by `FakeClock` and never by wall
time. And the resampler's latency gate is a **test**, not a benchmark, because a
benchmark nobody reads cannot fail; it scales its budget under `-race`, where
instrumentation costs an order of magnitude and the number stops describing
production.

### Every fix is re-introduced before it is believed

The discipline this suite is maintained under: when a fix is claimed, put the
fault back and watch the guard fail, then revert. It has repeatedly caught tests
that could not fail — a deadlock test whose fake vendor kept draining the socket
so writes never blocked; a done-when that asserted on the wrong contract field;
a layering rule that was inert for an entire directory tree while its suite
stayed green.

## Gaps

* **The interview, expectation, and enrollment routes are still untested.** `test_session.py` covers the session handlers and the session SQL; the skip-unless-regenerate branch, the 422 on unknown archetypes at enrollment, and the interview/expectation SQL remain uncovered. The pattern to copy is already in `test_session.py`.
* No live scenario exercises a session end to end against a real provider. The pivot plan's Phase 5 task 30 adds one scripted session per persona under `--live`.
* **Nothing automated exercises real audio.** The WebRTC handshake and the data-channel event names were verified by hand against the live API on 2026-08-22, and the Gemini Live SDK surface against the pinned packages on 2026-09-01 (both recorded in [Realtime voice](/concepts/contracts/realtime-voice.md)); a vendor rename would pass every test here and fail in the browser. The event-name mapping in `VoiceSessionView.jsx`, the PCM framing in `geminiLive.js`, and the resumption/`goAway` handling are the fragile surfaces. `tests/test_gemini_live_mint.py` covers the mint half of that and nothing more.
* Nothing checks that `EXPECTATION_JSON_SCHEMA` matches `InterviewExpectation` — two hand-maintained representations of one shape.
* `expectation_agent/agent.py` has no offline test of its overwrite logic, which is where its determinism guarantee actually lives.
* No JS tests for `ui/`.

## Guards added with the Phase 0 MVP (2026-08-22)

Three tests exist to stop a decision being reversed by accident rather than to
catch a bug:

* `test_operator_notes_cannot_override_the_archetype` — free operator text reaches the casting prompt, so this asserts both that the prompt subordinates it and that the knowledge clamp still holds afterwards.
* `test_rubric_vocabulary_agrees_across_the_two_agents` — `candidate_agent` re-declares the rubric criterion ids because siblings may not import each other. The control plane sits above both and is the only place they can be compared.
* `test_the_rubric_has_no_critical_fail_gate` — the design mockup specifies a gate on Fair & Inclusive that the standing product rule forbids. If a gate is ever wanted it must arrive as a deliberate edit to this test, not as a quiet field on a criterion.
