---
type: Contract
title: ChatModel
description: The provider-agnostic conversation port — free-text turns for the live session, separate from StructuredModel by design.
resource: /llm/base.py
tags: [contract, llm, port, dip, isp, session]
generated:
  by: claude-opus-5/okf-curator
  at: "2026-08-22T17:05:00Z"
verified:
  - by: claude-opus-5/okf-curator
    at: "2026-08-22T17:05:00Z"
status: stable
sources:
  - resource: /llm/base.py
  - resource: /llm/gemini.py
  - resource: /llm/openai_model.py
---
# ChatModel

```python
ChatMessage = dict[str, str]        # {"role": "user" | "assistant", "content": str}

class ModelClient(ABC):             # shared by both ports
    def __init__(self, model_id: str, temperature: float) -> None
    @property def model_id(self) -> str
    @property def temperature(self) -> float
    @property @abstractmethod def provider(self) -> str

class ChatModel(ModelClient):
    @abstractmethod
    async def generate_text(self, *, system: str,
                            messages: list[ChatMessage]) -> str
```

## Why this is not a method on `StructuredModel`

Interface segregation, and it is not cosmetic. The two jobs share nothing but
"call a model": one returns a validated object the code will index into, the
other returns prose a human will read. Folding `generate_text` into
`StructuredModel` would hand every persona-casting call site a conversation
method it must never use, and hand the session agent a JSON-schema method that
would quietly re-introduce structure into a free-text turn.

`ModelClient` carries only the configuration both need — model id, temperature,
provider name — so the uniform `(model_id, temperature, api_key)` constructor
still builds either port. `test_isp_the_two_model_ports_stay_separate` asserts
neither ABC subclasses the other and neither leaks the other's method.

## The four guarantees

1. **`generate_text` returns a non-empty `str`** — never `None`, never JSON. Both adapters route the completion through a private `_require_text` that raises on a blank reply: a silent empty turn stalls the session rather than failing it.
2. **`system` is applied verbatim.** The caller compiled it deterministically ([EngineContract](/concepts/contracts/engine-contract.md)); an adapter that edits, summarises, or reorders it changes the persona.
3. **`messages` are sent in the order given, with roles preserved.** History order *is* the conversation.
4. **Failure raises `ModelError`**, never a provider-specific exception.

## The two implementations

| | `GeminiChatModel` | `OpenAIChatModel` |
|---|---|---|
| Call | `client.aio.models.generate_content` with `contents=[Content(...)]` | `client.chat.completions.create` |
| Roles | `user` / **`model`** — mapped through `_ROLES` | `user` / `assistant`, sent as-is |
| System instruction | `system_instruction` config field | first message, `role: "system"` |

**The role-name trap:** Gemini calls the assistant `model`, not `assistant`. The
port's vocabulary is `user`/`assistant`; `llm/gemini.py::_ROLES` translates.
Anything unrecognised falls back to `user`, so a bad speaker label degrades to a
visible mis-attributed turn rather than a provider error.

Both vendor modules now build their client through a shared module-level
`_client(api_key)` helper, keeping the SDK import inside the call — the modules
still import cleanly without the dependency installed.

## Adding a provider

A provider is only "supported" once it serves **both** ports. Add the
`StructuredModel` class *and* the `ChatModel` class, then one row each in
`PROVIDERS`, `CHAT_PROVIDERS`, `API_KEY_VARS`, `DEFAULT_MODEL_IDS`
([`llm/factory.py`](/concepts/modules/llm-factory.md)).
`test_ocp_new_provider_needs_no_agent_change` asserts all four tables carry the
same key set.

## Consumers

* [`candidate_agent/session.py`](/concepts/modules/candidate-agent-session.md) — the only consumer today, at temperature **0.8**.
* The `judge` role is reserved in `ROLE_PREFIXES` and `.env.example` for the evaluation layer, which will use [`StructuredModel`](/concepts/contracts/structured-model.md), not this port.
