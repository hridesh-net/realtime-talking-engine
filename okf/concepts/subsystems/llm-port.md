---
type: Subsystem
title: LLM port
description: The provider abstraction and its two adapters — the only place a vendor SDK may appear.
resource: /llm
tags: [llm, port, gemini, openai, dip]
generated:
  by: claude-opus-5/okf-curator
  at: "2026-08-21T19:17:54Z"
verified:
  - by: claude-opus-5
    at: "2026-09-01T00:00:00Z"
  - by: claude-opus-5/okf-curator
    at: "2026-08-22T17:05:00Z"
  - by: kimi-code/okf-curator
    at: "2026-08-22T21:10:00Z"
status: stable
sources:
  - resource: /llm/base.py
  - resource: /llm/factory.py
  - resource: /llm/gemini.py
  - resource: /llm/openai_model.py
  - resource: /llm/openai_realtime.py
  - resource: /llm/gemini_live.py
---
# LLM port

> **`AudioModel`** is the fourth port — audio in, schema-constrained JSON out,
> for the [analysis agent](/concepts/subsystems/analysis-agent.md). Separate from
> `StructuredModel` because the payload differs: a caller wanting JSON from
> *text* must not be handed a port requiring bytes and a MIME type.
>
> `AUDIO_PROVIDERS` is **deliberately partial**, like `REALTIME_PROVIDERS`. Only
> Gemini reads audio natively, so `audio_analysis_available()` lets the UI hide
> the Analyse button rather than show one that errors.

`llm/` — the bottom of the stack. Imports nothing first-party. **The only
package allowed to import `google`, `openai`, or `google.genai`**, enforced by
an AST scan in `tests/test_architecture.py`.

| Module | Contents |
|---|---|
| `base.py` | `ModelClient` + [`StructuredModel`](/concepts/contracts/structured-model.md) + [`ChatModel`](/concepts/contracts/chat-model.md) + [`RealtimeBroker`](/concepts/contracts/realtime-voice.md) + `ModelError` |
| `gemini.py` | `GeminiModel` (native JSON mode via `response_schema`), `GeminiChatModel` |
| `openai_model.py` | `OpenAIModel` (JSON mode with the schema restated in the system turn), `OpenAIChatModel` |
| `gemini_live.py` | `GeminiLiveBroker` — mints ephemeral Live auth tokens with the whole session config sealed in `live_connect_constraints`; **owns `GEMINI_LIVE_VOICES`**, the 30-voice roster `candidate_agent.engine_contract` re-exports, **and its gender classification** (`GEMINI_FEMALE_VOICES` / `GEMINI_MALE_VOICES`) |
| `openai_realtime.py` | `OpenAIRealtimeBroker` — mints ephemeral WebRTC client secrets |
| `factory.py` | [`build_model` / `build_chat_model`](/concepts/modules/llm-factory.md) — the only place that knows which providers exist |

## Three ports, five adapters

| Port | Method | Used by |
|---|---|---|
| `StructuredModel` | `async generate_json(*, system, prompt, schema) -> dict` | expectation agent, persona casting, role-fact drafting, the future judge pass |
| `ChatModel` | `async generate_text(*, system, messages) -> str` | the live text session |
| `RealtimeBroker` | `async mint(*, session, ttl_seconds) -> RealtimeCredential` | the live **voice** session |

`RealtimeBroker` is the odd one out and deliberately so: nothing here ever
receives a model token through it. It mints a credential a *browser* redeems, so
the audio path is peer-to-vendor and never enters this process. See
[Realtime voice](/concepts/contracts/realtime-voice.md).

They are deliberately **not** one interface — see
[ChatModel § why this is not a method on StructuredModel](/concepts/contracts/chat-model.md).
Both inherit `ModelClient`, which carries `model_id`, `temperature`, and an
abstract `provider`, so the factory builds either through the same
`(model_id, temperature, api_key)` call. One error type throughout: `ModelError`.

A provider must implement both **text** ports. `PROVIDERS`, `CHAT_PROVIDERS`,
`API_KEY_VARS`, and `DEFAULT_MODEL_IDS` are asserted to carry identical key
sets, so a half-added provider fails the architecture gate rather than blowing
up at the first session turn.

`REALTIME_PROVIDERS` is the documented exception — a **subset**, because realtime
speech-to-speech is not something every vendor offers on comparable terms. Both
providers are entries today, **gemini first**: `build_realtime_broker` falls back
to `available[0]`, so table order is what makes Gemini Live the default talker.
A provider missing from the table simply has no voice mode.

The voice roster lives in `gemini_live.py` rather than in `candidate_agent`
because it is a vendor fact, and because it is *order-sensitive*: `pick_voice`
indexes into it, and a persona's `tts_voice_id` is stored at cast time and
spoken back months later. `engine_contract.GEMINI_TTS_VOICES` is a re-export of
the same object — `candidate_agent` → `llm` is the allowed direction — so the
two can never drift. `test_the_voice_roster_has_exactly_one_source_of_truth`
asserts identity, not equality.

**The roster's gender classification lives here too**, for the same reason and
one more. `GEMINI_FEMALE_VOICES` (14) and `GEMINI_MALE_VOICES` (16) are
frozensets recording the vendor-documented voice gender of every roster member,
taken from Google's Gemini-TTS voice table. It is a *vendor fact*, not a
preference — a voice is never reclassified, because moving a name between the
sets would silently re-voice every persona cast since. Casting imports them
(`candidate_agent.engine_contract.voices_for_presentation`) to keep a persona's
voice consistent with its `gender_presentation`; see
[engine_contract.py](/concepts/modules/candidate-agent-engine-contract.md).

They are **membership only** — order stays in `GEMINI_LIVE_VOICES` and nowhere
else, since `pick_voice` hashes against an ordered sequence — and they must
**partition** the roster: `test_the_gender_sets_partition_the_roster` asserts
union and disjointness, so a voice appended to the roster without being
classified fails the offline suite rather than becoming unreachable for
gendered personas.

Agents receive an **already-built** model. They never call the factory for
credentials, never read `GEMINI_API_KEY`, and never import an SDK — tested three
separate ways.

## Configuration

Resolution order per role: `<ROLE>_PROVIDER`/`<ROLE>_MODEL` → `LLM_PROVIDER`/
`LLM_MODEL` → the provider default. Roles are `expectation`, `candidate`,
`session`, `judge`, and `role_facts` — one per workload, so the hot path (a session call per
turn) can move provider without dragging the once-per-interview calls with it.
`judge` is wired in config ahead of the evaluation layer that will use it;
`role_facts` backs the evaluation agent's checklist drafting.
`resolve_transcribe_model()` reads `TRANSCRIBE_MODEL` (default
`gpt-4o-transcribe`) for the OpenAI voice path only — Gemini Live transcribes
both sides in-session and ignores it. It is a bare env read rather than a role
because it names a transcriber, not a provider.
`voice` resolves against the realtime-capable providers **only** — it does not
fall through to `LLM_PROVIDER`, because the text provider may offer no realtime
API at all, and a fallback there would fail at mint time with a confusing error.
Defaults: `gemini` → `gemini-3.7-flash`, `openai` → `gpt-4o-mini`. Model IDs are
config, never hardcoded at a call site.

With no `*_PROVIDER` set, the factory picks the first provider whose API key is
present, iterating `PROVIDERS` in insertion order — **Gemini first**.

## Two Gemini keys, one silent failover (2026-09-01)

A Gemini key stops working for reasons that have nothing to do with the request:
free-tier quota resets on the project's clock, a key is rotated out of the
console, a burst trips the per-key rate limit. Any one of those takes down
casting, the live session and the Voice button at once, and all of them are
fixed by trying the *same* call on a *different* key.

`FALLBACK_API_KEY_VARS` in the factory names the extra variables — today
`{"gemini": ("GEMINI_API_KEY2",)}`. When a provider has more than one key set,
every build function constructs **one adapter per key** and wraps them in the
matching class from `llm/failover.py`
(`FailoverStructuredModel`, `FailoverChatModel`, `FailoverAudioModel`,
`FailoverRealtimeBroker`). The wrapper *is* the port — same interface, same
`ModelError` contract, same `provider`/`model_id`/`temperature` — so nothing
outside `llm/` knows it exists and neither the REST API nor the browser changes.

| | |
|---|---|
| **What fails over** | Only a **key-shaped** failure: `looks_like_a_key_failure` reads a 401/403/429 off the vendor exception's `code`/`status_code`/`response.status_code`, or finds one of `KEY_FAILURE_MARKERS` (`resource_exhausted`, `permission_denied`, `unauthenticated`, `quota`, `rate limit`, an invalid or expired API key) in the message, or a word-bounded bare status number. |
| **What does not** | Everything else, on the first attempt, unchanged. A malformed request or a parse failure fails identically on every key; running it twice doubles the latency and the bill to reach the same exception. |
| **How many attempts** | Each key at most once, in order. The last key's failure is raised as-is. |
| **Afterwards** | **Sticky, process-wide.** A fallback that worked is preferred by later calls, including through a *different* wrapper instance — `build_model` is called per agent, so per-instance memory would forget the switch immediately. A dead primary is paid for once per process. |
| **Logging** | One warning per switch, server-side. Nothing reaches the client. |

Two boundaries worth keeping. `API_KEY_VARS` still decides whether a provider is
**configured** — `resolve_provider`, `realtime_providers_available` and
`audio_analysis_available` read only the primary, so `GEMINI_API_KEY2` alone is
not a Gemini deployment. And the wrapping happens **after** the table lookup:
`PROVIDERS` / `REALTIME_PROVIDERS` still hold the vendor classes, whose
`(model_id, temperature, api_key)` and `(model_id, api_key)` constructor shapes
`tests/test_architecture.py` pins. With one key the bare adapter is returned and
no wrapper is built at all.

Deliberately *not* a general retry layer: it does not retry the same key, does
not back off, and does not touch 5xx. A model that is overloaded is a different
problem with a different fix.

## Temperatures

Set by the agent, not the config: expectation **0.1** (the document must be
stable across runs), role-facts **0.1** (extraction — warmth here produces facts
the job description does not contain), candidate **0.35** (personas need texture, and everything
reproducible is computed outside the model anyway), session **0.8** (a persona
that answers like a form letter defeats the exercise; nothing reproducible
depends on the call). Voice sessions set no temperature — the realtime vendor
owns sampling, and the persona is shaped by the compiled instructions instead.

## Adding a provider

Add **both** text classes — a `StructuredModel` and a `ChatModel` — then one row
each in `PROVIDERS`, `CHAT_PROVIDERS`, `API_KEY_VARS`, and `DEFAULT_MODEL_IDS`.
Voice is optional: add a `RealtimeBroker` plus rows in `REALTIME_PROVIDERS`,
`DEFAULT_REALTIME_MODEL_IDS` and `candidate_agent.voice._SESSION_BUILDERS` only
if that vendor has a realtime API. That is the whole change — proven by an OCP test that
registers a provider at runtime.
