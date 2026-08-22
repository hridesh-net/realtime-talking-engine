---
type: Contract
title: StructuredModel
description: The provider-agnostic model port — one method, three guarantees.
resource: /llm/base.py
tags: [contract, llm, port, dip]
generated:
  by: claude-opus-5/okf-curator
  at: "2026-08-21T19:17:54Z"
verified:
  - by: claude-opus-5/okf-curator
    at: "2026-08-22T17:05:00Z"
status: stable
sources:
  - resource: /llm/base.py
  - resource: /llm/gemini.py
  - resource: /llm/openai_model.py
---
# StructuredModel

One of **two** ports in `llm/base.py`. This one is for calls whose answer the
code will index into; [`ChatModel`](/concepts/contracts/chat-model.md) is for
free-text conversation turns. They share `ModelClient` (model id, temperature,
provider) and nothing else — see that page for why they are not one interface.

```python
class ModelError(RuntimeError): ...

class StructuredModel(ModelClient):
    # from ModelClient: __init__(model_id, temperature), model_id,
    #                   temperature, abstract provider
    @abstractmethod
    async def generate_json(self, *, system: str, prompt: str,
                            schema: dict[str, Any]) -> dict[str, Any]
```

## The three guarantees

Stated in the docstring, and they are the substitutability contract — break one
and swapping providers silently changes agent behaviour:

1. **`generate_json` returns a parsed `dict`** — never a string, never `None`.
2. **`system` is applied as a system-level instruction**, not prepended to the user turn, so provider-side caching and safety behave consistently.
3. **Failure raises `ModelError`**, never a provider-specific exception.

`tests/test_architecture.py` enforces the shape of this: every backend shares the
base signature, implements the whole contract, and is constructible through one
uniform call `(model_id, temperature, api_key)`.

## The two implementations

| | `GeminiModel` | `OpenAIModel` |
|---|---|---|
| Call | `client.aio.models.generate_content` | `client.chat.completions.create` |
| Schema enforcement | native `response_schema` | `response_format={"type": "json_object"}` **plus the schema restated in the system turn** |
| System instruction | `system_instruction` config field | first message, `role: "system"` |
| Async | `genai.Client(...).aio` | `AsyncOpenAI` |

The OpenAI adapter restates the schema because JSON mode guarantees *syntactic*
validity, not conformance — a documented asymmetry, not an oversight.

Both import their SDK **inside `__init__`**, raising `ModelError` on
`ImportError`, so the module imports cleanly without the dependency installed.
Both share an identical private `_parse` that rejects non-dict JSON.

## Adding a provider

1. Implement `StructuredModel` **and** [`ChatModel`](/concepts/contracts/chat-model.md) in `llm/` — a provider that serves only one port is not supported, and the factory tables are asserted to hold the same keys.
2. Add a row to `PROVIDERS`, `CHAT_PROVIDERS`, `API_KEY_VARS`, and `DEFAULT_MODEL_IDS` in [`llm/factory.py`](/concepts/modules/llm-factory.md).
3. Nothing else. `tests/test_architecture.py::test_ocp_new_provider_needs_no_agent_change` registers a provider at runtime and proves the agents absorb it.

Keep the SDK import inside `__init__` and keep `_parse`'s dict check — the agents
assume a dict comes back or an exception is raised, with no third case.
