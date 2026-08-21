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
    at: "2026-08-21T19:17:54Z"
status: stable
sources:
  - resource: /llm/factory.py
  - resource: /.env.example
---
# llm/factory.py

93 lines.

# Schema

```python
PROVIDERS: dict[str, Callable[[str, float, str], StructuredModel]] = {
    "gemini": GeminiModel, "openai": OpenAIModel}
API_KEY_VARS   = {"gemini": "GEMINI_API_KEY", "openai": "OPENAI_API_KEY"}
DEFAULT_MODEL_IDS = {"gemini": "gemini-2.5-flash", "openai": "gpt-4o-mini"}
ROLE_PREFIXES  = {"expectation": "EXPECTATION", "candidate": "CANDIDATE"}

def resolve_provider(role: str) -> str          # L44
def resolve_model_id(role: str, provider: str) -> str   # L69
def build_model(role: str, temperature: float) -> StructuredModel   # L79
```

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

* `resolve_model_id` falls back to `LLM_MODEL` **regardless of provider**, so setting `LLM_MODEL=gemini-2.5-flash` while forcing `CANDIDATE_PROVIDER=openai` sends a Gemini model id to OpenAI. Per-role vars avoid it.
* Adding a role means adding a `ROLE_PREFIXES` entry; an unknown role silently skips the per-role lookup and uses only the shared fallback.
* `build_model` re-reads the key after `resolve_provider` already checked it — the second check is marked `# pragma: no cover`.

## Adding a provider

One row in each of `PROVIDERS`, `API_KEY_VARS`, `DEFAULT_MODEL_IDS`, plus the
class in `llm/`. Nothing downstream changes;
`test_ocp_new_provider_needs_no_agent_change` proves it by registering one at
runtime.
