"""OpenAI implementations of the model ports in :mod:`llm.base`."""

from __future__ import annotations

import json
from typing import Any

from llm.base import ChatMessage, ChatModel, ModelError, StructuredModel


def _client(api_key: str) -> Any:
    """Build the shared async OpenAI client.

    ``AsyncOpenAI``: the synchronous client would block the event loop, and the
    control plane serves these calls from an async request handler.
    """
    try:
        from openai import AsyncOpenAI
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise ModelError("openai is not installed") from exc
    return AsyncOpenAI(api_key=api_key)


class OpenAIModel(StructuredModel):
    """OpenAI backend using JSON mode."""

    def __init__(self, model_id: str, temperature: float, api_key: str) -> None:
        super().__init__(model_id, temperature)
        self._client = _client(api_key)

    @property
    def provider(self) -> str:
        """Provider name."""
        return "openai"

    async def generate_json(
        self,
        *,
        system: str,
        prompt: str,
        schema: dict[str, Any],
    ) -> dict[str, Any]:
        """Call OpenAI with JSON-object output.

        The schema is restated in the system turn because JSON mode guarantees
        syntactic validity, not conformance.
        """
        instruction = (
            f"{system}\n\nReturn one JSON object matching this JSON Schema exactly:\n"
            f"{json.dumps(schema)}"
        )
        try:
            response = await self._client.chat.completions.create(
                model=self.model_id,
                messages=[
                    {"role": "system", "content": instruction},
                    {"role": "user", "content": prompt},
                ],
                temperature=self.temperature,
                response_format={"type": "json_object"},
            )
        except Exception as exc:
            raise ModelError(f"openai call failed: {exc}") from exc

        return _parse(response.choices[0].message.content)


class OpenAIChatModel(ChatModel):
    """OpenAI backend for free-text conversation turns."""

    def __init__(self, model_id: str, temperature: float, api_key: str) -> None:
        super().__init__(model_id, temperature)
        self._client = _client(api_key)

    @property
    def provider(self) -> str:
        """Provider name."""
        return "openai"

    async def generate_text(
        self,
        *,
        system: str,
        messages: list[ChatMessage],
    ) -> str:
        """Call OpenAI with the conversation so far and return the next turn."""
        payload = [{"role": "system", "content": system}, *messages]
        try:
            response = await self._client.chat.completions.create(
                model=self.model_id,
                messages=payload,
                temperature=self.temperature,
            )
        except Exception as exc:
            raise ModelError(f"openai call failed: {exc}") from exc

        return _require_text(response.choices[0].message.content)


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
