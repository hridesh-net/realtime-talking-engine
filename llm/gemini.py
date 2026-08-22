"""Gemini implementations of the model ports in :mod:`llm.base`."""

from __future__ import annotations

import json
from typing import Any

from llm.base import ChatMessage, ChatModel, ModelError, StructuredModel

#: Port role name -> Gemini role name. Gemini calls the assistant "model".
_ROLES = {"user": "user", "assistant": "model"}


def _client(api_key: str) -> Any:
    """Build the shared async Gemini client."""
    try:
        from google import genai
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise ModelError("google-genai is not installed") from exc
    return genai.Client(api_key=api_key)


class GeminiModel(StructuredModel):
    """Gemini backend using native JSON mode (``response_schema``)."""

    def __init__(self, model_id: str, temperature: float, api_key: str) -> None:
        super().__init__(model_id, temperature)
        self._client = _client(api_key)

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


class GeminiChatModel(ChatModel):
    """Gemini backend for free-text conversation turns.

    The persona prompt goes in ``system_instruction`` rather than as a leading
    user turn: the session replays the whole history on every turn, and a system
    instruction is the only slot the provider treats as standing context.
    """

    def __init__(self, model_id: str, temperature: float, api_key: str) -> None:
        super().__init__(model_id, temperature)
        self._client = _client(api_key)

    @property
    def provider(self) -> str:
        """Provider name."""
        return "gemini"

    async def generate_text(
        self,
        *,
        system: str,
        messages: list[ChatMessage],
    ) -> str:
        """Call Gemini with the conversation so far and return the next turn."""
        from google.genai import types

        contents = [
            types.Content(
                role=_ROLES.get(m["role"], "user"),
                parts=[types.Part.from_text(text=m["content"])],
            )
            for m in messages
        ]
        config = types.GenerateContentConfig(
            temperature=self.temperature,
            system_instruction=system,
        )
        try:
            response = await self._client.aio.models.generate_content(
                model=self.model_id,
                contents=contents,
                config=config,
            )
        except Exception as exc:
            raise ModelError(f"gemini call failed: {exc}") from exc

        return _require_text(response.text)


def _parse(text: str | None) -> dict[str, Any]:
    """Parse a JSON object response, rejecting anything that is not a dict."""
    try:
        payload = json.loads(text or "{}")
    except json.JSONDecodeError as exc:
        raise ModelError(f"model returned invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ModelError(f"model returned {type(payload).__name__}, expected an object")
    return payload


def _require_text(text: str | None) -> str:
    """Reject an empty completion — a silent blank turn stalls the session."""
    stripped = (text or "").strip()
    if not stripped:
        raise ModelError("model returned an empty reply")
    return stripped
