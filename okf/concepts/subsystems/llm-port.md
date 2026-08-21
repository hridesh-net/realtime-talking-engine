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
    at: "2026-08-21T19:17:54Z"
status: stable
sources:
  - resource: /llm/base.py
  - resource: /llm/factory.py
  - resource: /llm/gemini.py
  - resource: /llm/openai_model.py
---
# LLM port

`llm/` — the bottom of the stack. Imports nothing first-party. **The only
package allowed to import `google`, `openai`, or `google.genai`**, enforced by
an AST scan in `tests/test_architecture.py`.

| Module | Contents |
|---|---|
| `base.py` | [`StructuredModel` ABC + `ModelError`](/concepts/contracts/structured-model.md) |
| `gemini.py` | `GeminiModel` — native JSON mode via `response_schema` |
| `openai_model.py` | `OpenAIModel` — JSON mode with the schema restated in the system turn |
| `factory.py` | [`build_model(role, temperature)`](/concepts/modules/llm-factory.md) — the only place that knows which providers exist |

## The shape

One method: `async generate_json(*, system, prompt, schema) -> dict`. One error
type: `ModelError`. Two properties every backend exposes: `model_id`,
`temperature`, plus an abstract `provider` name.

Agents receive an **already-built** model. They never call the factory for
credentials, never read `GEMINI_API_KEY`, and never import an SDK — tested three
separate ways.

## Configuration

Resolution order per role: `<ROLE>_PROVIDER`/`<ROLE>_MODEL` → `LLM_PROVIDER`/
`LLM_MODEL` → the provider default. Roles are `expectation` and `candidate`.
Defaults: `gemini` → `gemini-2.5-flash`, `openai` → `gpt-4o-mini`. Model IDs are
config, never hardcoded at a call site.

With no `*_PROVIDER` set, the factory picks the first provider whose API key is
present, iterating `PROVIDERS` in insertion order — **Gemini first**.

## Temperatures

Set by the agent, not the config: expectation **0.1** (the document must be
stable across runs), candidate **0.35** (personas need texture, and everything
reproducible is computed outside the model anyway).

## Adding a provider

Add the class, then one row each in `PROVIDERS`, `API_KEY_VARS`, and
`DEFAULT_MODEL_IDS`. That is the whole change — proven by an OCP test that
registers a provider at runtime.
