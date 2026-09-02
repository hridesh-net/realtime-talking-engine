---
type: Module
title: llm/factory.py
description: Resolves provider and model from environment config — the only place that knows which providers exist.
resource: /llm/factory.py
tags: [llm, config, factory, ocp]
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
  - resource: /llm/factory.py
  - resource: /.env.example
---
# llm/factory.py

178 lines.

# Schema

```python
PROVIDERS: dict[str, Callable[[str, float, str], StructuredModel]] = {
    "gemini": GeminiModel, "openai": OpenAIModel}
CHAT_PROVIDERS: dict[str, Callable[[str, float, str], ChatModel]] = {
    "gemini": GeminiChatModel, "openai": OpenAIChatModel}
API_KEY_VARS   = {"gemini": "GEMINI_API_KEY", "openai": "OPENAI_API_KEY"}
FALLBACK_API_KEY_VARS = {"gemini": ("GEMINI_API_KEY2",)}   # tried on a key-shaped failure
DEFAULT_MODEL_IDS = {"gemini": "gemini-3.7-flash", "openai": "gpt-4o-mini"}  # pinned, not `-latest`
REALTIME_PROVIDERS: dict[str, Callable[[str, str], RealtimeBroker]] = {
    "gemini": GeminiLiveBroker,              # deliberately PARTIAL;
    "openai": OpenAIRealtimeBroker}          # ORDER decides the default
DEFAULT_REALTIME_MODEL_IDS = {"gemini": "gemini-3.1-flash-live-preview",
                              "openai": "gpt-realtime-2"}
DEFAULT_TRANSCRIBE_MODEL = "gpt-4o-transcribe"   # OpenAI voice path only
ROLE_PREFIXES  = {"expectation": "EXPECTATION", "candidate": "CANDIDATE",
                  "session": "SESSION", "judge": "JUDGE",
                  "role_facts": "ROLE_FACTS", "voice": "VOICE"}

def resolve_provider(role: str) -> str
def resolve_model_id(role: str, provider: str) -> str
def build_model(role: str, temperature: float) -> StructuredModel
def build_chat_model(role: str, temperature: float) -> ChatModel
def realtime_providers_available() -> list[str]
def build_realtime_broker(role: str = "voice") -> RealtimeBroker
def resolve_transcribe_model() -> str
```

Two registries, one per [model port](/concepts/contracts/chat-model.md), keyed
identically. `resolve_provider` validates against `PROVIDERS` alone — which is
safe only because the key sets are asserted equal in
`test_ocp_new_provider_needs_no_agent_change`. Add a provider to one table and
not the other and `build_chat_model` raises `KeyError`, not `ModelError`; the
architecture test is what stops that reaching runtime.

## Resolution order

**Provider** — `<ROLE>_PROVIDER`, then `LLM_PROVIDER`. An explicit value is
validated twice: it must be a known provider (else `ModelError` listing the
known ones) **and** its API key must be set (else `ModelError` naming the
variable). Only if neither variable is set does it fall through to "first
provider with a key present", iterating `PROVIDERS` in insertion order —
**Gemini first**. With no keys at all: `ModelError: no provider credentials
found; set GEMINI_API_KEY or OPENAI_API_KEY`.

**Model id** — `<ROLE>_MODEL`, then `LLM_MODEL`, then `DEFAULT_MODEL_IDS[provider]`.

Note the asymmetry: an empty-string `<ROLE>_PROVIDER` is treated as unset (it is
stripped and falsiness-checked), which is what makes the blank entries in
`.env.example` harmless.

## Gotchas

* `resolve_model_id` falls back to `LLM_MODEL` **regardless of provider**, so setting `LLM_MODEL=gemini-3.7-flash` while forcing `CANDIDATE_PROVIDER=openai` sends a Gemini model id to OpenAI. Per-role vars avoid it.
* Adding a role means adding a `ROLE_PREFIXES` entry; an unknown role silently skips the per-role lookup and uses only the shared fallback.
* Both builders re-read the key after `resolve_provider` already checked it, via the shared `_credential` helper — the second check is marked `# pragma: no cover`.
* **`build_realtime_broker` does not use `resolve_provider`.** It resolves against `REALTIME_PROVIDERS` alone, because the configured text provider may have no realtime API — falling through to it would fail at mint time with an error about the wrong thing. An explicit `VOICE_PROVIDER` naming a provider without realtime support is rejected up front, by name.
* `realtime_providers_available()` exists so the UI can ask *before* offering a Voice button. No key configured is a configuration answer (`available: false`), not an error.
* **`REALTIME_PROVIDERS` order is behaviour, not tidiness.** With no `VOICE_PROVIDER` set, `build_realtime_broker` takes `available[0]` — so putting `gemini` first is what makes Gemini Live the default talker in a deployment holding both keys. `VOICE_PROVIDER=openai` keeps the WebRTC path.
* **`resolve_transcribe_model()` is a bare env read, not a role.** `TRANSCRIBE_MODEL` names a *transcriber*, not a provider, and it applies to the OpenAI voice path alone — Gemini Live transcribes both sides in-session. It lives here because env reads live here: `candidate_agent.voice` is handed the answer rather than reaching for `os.environ` itself.
* `judge` is a live role prefix with no consumer yet. Setting `JUDGE_MODEL` today changes nothing; it is here so the evaluation layer lands without an env-var migration.
* `role_facts` backs the [evaluation agent](/concepts/subsystems/evaluation-agent.md)'s checklist drafting at temperature 0.1 — extraction, so pin it to a steady model rather than a creative one.

## More than one key per provider

`_credentials(provider)` returns the primary from `API_KEY_VARS` followed by
whatever `FALLBACK_API_KEY_VARS` names, empties and whitespace dropped. Every
`build_*` function then constructs **one adapter per key** and, when there is
more than one, wraps them in the matching class from
[`llm/failover.py`](/concepts/subsystems/llm-port.md#two-gemini-keys-one-silent-failover-2026-09-01).
With a single key — the normal case — the bare adapter is returned and no
wrapper exists.

Two invariants this must not break, both pinned by `tests/test_architecture.py`:

* **The tables still hold vendor classes.** Wrapping happens *after* the lookup,
  never inside `PROVIDERS` / `REALTIME_PROVIDERS`, because the LSP tests assert
  those constructors take `(model_id, temperature, api_key)` and
  `(model_id, api_key)`.
* **A fallback key is not a configuration.** `resolve_provider`,
  `realtime_providers_available` and `audio_analysis_available` read
  `API_KEY_VARS` only, so `GEMINI_API_KEY2` on its own leaves Gemini unavailable
  — as it should, since there is nothing to fall back *from*.

## Adding a provider

One row in each of `PROVIDERS`, `CHAT_PROVIDERS`, `API_KEY_VARS`, and
`DEFAULT_MODEL_IDS`, plus **two** classes in `llm/` — one per port. Nothing downstream changes;
`test_ocp_new_provider_needs_no_agent_change` proves it by registering one at
runtime. A row in `FALLBACK_API_KEY_VARS` is optional and independent: it gives
that provider a second key with no other change anywhere.
