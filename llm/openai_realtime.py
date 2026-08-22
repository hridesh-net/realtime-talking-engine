"""OpenAI implementation of :class:`~llm.base.RealtimeBroker`.

Mints an ephemeral client secret against ``POST /v1/realtime/client_secrets``.
The browser redeems it by posting an SDP offer to
``https://api.openai.com/v1/realtime/calls`` with
``Authorization: Bearer <value>`` and ``Content-Type: application/sdp``.

Verified against the live API on 2026-08-22: the endpoint accepts the whole
session document — ``instructions``, ``audio.input.transcription``,
``audio.input.turn_detection`` (``semantic_vad`` with ``eagerness``),
``audio.output.voice`` and ``speed`` — and echoes it back on the response.
"""

from __future__ import annotations

from typing import Any

from llm.base import ModelError, RealtimeBroker, RealtimeCredential

#: Where the browser redeems the credential. Not configurable — it is the
#: vendor's endpoint, and the browser needs it alongside the secret.
CALL_URL = "https://api.openai.com/v1/realtime/calls"

#: Voices the Realtime API accepts, confirmed by minting one session per name.
#: Ordered, because persona voice assignment indexes into it deterministically.
VOICES: tuple[str, ...] = (
    "alloy",
    "ash",
    "ballad",
    "cedar",
    "coral",
    "echo",
    "marin",
    "sage",
    "shimmer",
    "verse",
)


class OpenAIRealtimeBroker(RealtimeBroker):
    """Mints ephemeral Realtime session credentials for the browser."""

    def __init__(self, model_id: str, api_key: str) -> None:
        super().__init__(model_id)
        try:
            from openai import AsyncOpenAI
        except ImportError as exc:  # pragma: no cover - dependency is declared
            raise ModelError("openai is not installed") from exc
        self._client = AsyncOpenAI(api_key=api_key)

    @property
    def provider(self) -> str:
        """Provider name."""
        return "openai"

    @property
    def voices(self) -> tuple[str, ...]:
        """Voices the Realtime API accepts."""
        return VOICES

    async def mint(
        self,
        *,
        session: dict[str, Any],
        ttl_seconds: int,
    ) -> RealtimeCredential:
        """Mint a browser-redeemable Realtime credential."""
        payload = {**session, "type": "realtime", "model": self.model_id}
        try:
            result = await self._client.realtime.client_secrets.create(
                expires_after={"anchor": "created_at", "seconds": ttl_seconds},
                session=payload,  # type: ignore[arg-type]
            )
        except Exception as exc:
            raise ModelError(f"openai realtime session mint failed: {exc}") from exc

        value = getattr(result, "value", None)
        expires_at = getattr(result, "expires_at", None)
        if not isinstance(value, str) or not isinstance(expires_at, int):
            raise ModelError("openai returned no usable client secret")

        return RealtimeCredential(
            value=value,
            expires_at=expires_at,
            model=self.model_id,
            call_url=CALL_URL,
        )
