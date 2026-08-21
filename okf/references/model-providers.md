---
type: Reference
title: Model providers
description: Gemini and OpenAI structured-output behaviour, and what the adapters compensate for.
resource: https://ai.google.dev/gemini-api/docs
tags: [reference, gemini, openai, structured-output]
generated:
  by: claude-opus-5/okf-curator
  at: "2026-08-21T19:17:54Z"
status: stable
sources:
  - resource: /llm/gemini.py
  - resource: /llm/openai_model.py
---
# Model providers

Two backends behind [`StructuredModel`](/concepts/contracts/structured-model.md).
Both are async; both return a parsed dict or raise `ModelError`.

## Gemini — `google-genai`

`genai.Client(api_key=...).aio.models.generate_content(model, contents, config)`
with `types.GenerateContentConfig(temperature, response_mime_type="application/json",
response_schema=schema, system_instruction=system)`.

Native schema-constrained output: the schema goes in the request, not the prompt.
`system_instruction` is a first-class config field. Default model id:
`gemini-2.5-flash`.

Worth knowing: the Developer API is strict about JSON Schema features and
historically rejects `additionalProperties`. The schemas here do not use it, so
no stripping is needed — but a new schema that does will fail at the API, not at
validation.

## OpenAI — `openai`

`AsyncOpenAI(api_key=...).chat.completions.create(model, messages, temperature,
response_format={"type": "json_object"})`.

**JSON mode guarantees syntactic validity, not conformance**, so the adapter
restates the schema inside the system turn:

```python
instruction = f"{system}\n\nReturn one JSON object matching this JSON Schema exactly:\n{json.dumps(schema)}"
```

That asymmetry is documented in the adapter's docstring. `AsyncOpenAI` is used
deliberately — the sync client would block the event loop, and these calls are
served from an async request handler. Default model id: `gpt-4o-mini`.

(OpenAI's newer strict structured-output modes would remove the need to restate
the schema; the adapter does not use them today.)

## Shared behaviour

Both import their SDK inside `__init__`, raising `ModelError` on `ImportError`,
so the modules import cleanly without the dependency present. Both use an
identical `_parse` that raises on invalid JSON and on any JSON that is not an
object — `null`, a list, or a bare string are all errors, never a silent empty
dict.

## Temperatures in use

| Caller | Temperature | Why |
|---|---|---|
| `InterviewExpectationAgent` | 0.1 | the document must be stable across runs |
| `VirtualCandidateAgent` | 0.35 | personas need texture; everything reproducible is computed outside the model |
