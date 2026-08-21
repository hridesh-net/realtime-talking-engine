"""Gemini implementation of :class:`~llm.base.StructuredModel`."""

from __future__ import annotations

import json
from typing import Any

from llm.base import ModelError, StructuredModel


class GeminiModel(StructuredModel):
    """Gemini backend using native JSON mode (``response_schema``)."""

    def __init__(self, model_id: str, temperature: float, api_key: str) -> None:
        super().__init__(model_id, temperature)
        try:
            from google import genai
        except ImportError as exc:  # pragma: no cover - dependency is declared
            raise ModelError("google-genai is not installed") from exc
        self._client = genai.Client(api_key=api_key)

    @property
    def provider(self) -> str:
        """Provider name."""
        return "gemini"

    async def generate_json(
        self,
        *,
        system: str,
        prompt: str,
        schema: dict[str, Any],
    ) -> dict[str, Any]:
        """Call Gemini with schema-constrained JSON output."""
        from google.genai import types

        config = types.GenerateContentConfig(
            temperature=self.temperature,
            response_mime_type="application/json",
            response_schema=schema,
            system_instruction=system,
        )
        try:
            response = await self._client.aio.models.generate_content(
                model=self.model_id,
                contents=prompt,
                config=config,
            )
        except Exception as exc:
            raise ModelError(f"gemini call failed: {exc}") from exc

        return _parse(response.text)


def _parse(text: str | None) -> dict[str, Any]:
    """Parse a JSON object response, rejecting anything that is not a dict."""
    try:
        payload = json.loads(text or "{}")
    except json.JSONDecodeError as exc:
        raise ModelError(f"model returned invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ModelError(f"model returned {type(payload).__name__}, expected an object")
    return payload
