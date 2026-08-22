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
---
# LLM port

`llm/` — the bottom of the stack. Imports nothing first-party. **The only
package allowed to import `google`, `openai`, or `google.genai`**, enforced by
an AST scan in `tests/test_architecture.py`.

| Module | Contents |
|---|---|
| `base.py` | `ModelClient` + [`StructuredModel`](/concepts/contracts/structured-model.md) + [`ChatModel`](/concepts/contracts/chat-model.md) + [`RealtimeBroker`](/concepts/contracts/realtime-voice.md) + `ModelError` |
| `gemini.py` | `GeminiModel` (native JSON mode via `response_schema`), `GeminiChatModel` |
| `openai_model.py` | `OpenAIModel` (JSON mode with the schema restated in the system turn), `OpenAIChatModel` |
| `openai_realtime.py` | `OpenAIRealtimeBroker` — mints ephemeral WebRTC credentials; the only realtime provider |
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
speech-to-speech is not something every vendor offers on comparable terms.
OpenAI is the only entry today. A provider missing from it simply has no voice
mode.

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
`voice` resolves against the realtime-capable providers **only** — it does not
fall through to `LLM_PROVIDER`, because the text provider may offer no realtime
API at all, and a fallback there would fail at mint time with a confusing error.
Defaults: `gemini` → `gemini-2.5-flash`, `openai` → `gpt-4o-mini`. Model IDs are
config, never hardcoded at a call site.

With no `*_PROVIDER` set, the factory picks the first provider whose API key is
present, iterating `PROVIDERS` in insertion order — **Gemini first**.

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
Voice is optional: add a `RealtimeBroker` plus rows in `REALTIME_PROVIDERS` and
`DEFAULT_REALTIME_MODEL_IDS` only if that vendor has a realtime API. That is the whole change — proven by an OCP test that
registers a provider at runtime.
