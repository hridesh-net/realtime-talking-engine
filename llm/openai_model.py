"""OpenAI implementation of :class:`~llm.base.StructuredModel`."""

from __future__ import annotations

import json
from typing import Any

from llm.base import ModelError, StructuredModel


class OpenAIModel(StructuredModel):
    """OpenAI backend using JSON mode.

    Uses ``AsyncOpenAI``: the synchronous client would block the event loop, and
    the control plane serves these calls from an async request handler.
    """

    def __init__(self, model_id: str, temperature: float, api_key: str) -> None:
        super().__init__(model_id, temperature)
        try:
            from openai import AsyncOpenAI
        except ImportError as exc:  # pragma: no cover - dependency is declared
            raise ModelError("openai is not installed") from exc
        self._client = AsyncOpenAI(api_key=api_key)

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


def _parse(text: str | None) -> dict[str, Any]:
    """Parse a JSON object response, rejecting anything that is not a dict."""
    try:
        payload = json.loads(text or "{}")
    except json.JSONDecodeError as exc:
        raise ModelError(f"model returned invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ModelError(f"model returned {type(payload).__name__}, expected an object")
    return payload
