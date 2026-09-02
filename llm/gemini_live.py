"""Gemini implementation of :class:`~llm.base.RealtimeBroker`.

Mints an *ephemeral auth token* (``auth_tokens.create``) that the browser hands
straight to the JS SDK as its API key. There is no SDP offer and no call URL:
the Live API is a WebSocket the vendor's SDK opens for itself, so
:attr:`~llm.base.RealtimeCredential.call_url` comes back empty.

The whole point of this broker is the *seal*. ``live_connect_constraints``
carries a complete :class:`~google.genai.types.LiveConnectConfig` — system
instruction, voice, response modality, both transcription toggles, turn
detection and resumption — and the server enforces every field in it for the
life of the token. The browser still passes a config on ``live.connect``, but a
constrained field is not something it can talk the vendor out of: the persona
instructions are never sent to the client and could not be overridden if they
were. ``lock_additional_fields`` pins the sampling knobs we deliberately did
*not* set, so a client cannot reach for them either.

``uses=2`` rather than 1: an audio-only Live session is capped at roughly
fifteen minutes and the server sends ``goAway`` before cutting it, so one
reconnect on the same token is the normal path, not an error case. Past that
the browser re-mints.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from llm.base import ModelError, RealtimeBroker, RealtimeCredential

#: Prebuilt voices the Live API speaks with. **This tuple is the single source
#: of truth for the roster** — `candidate_agent.engine_contract` re-exports it
#: as ``GEMINI_TTS_VOICES`` so the voice baked into a persona's contract at cast
#: time and the voice the session actually speaks in cannot drift apart.
#:
#: **Ordered and append-only, on pain of breaking every already-cast persona.**
#: `pick_voice` selects `hash(candidate_id) % len(voices)`, so the choice is a
#: function of this list's *order and length*, not just its membership.
#: `tts_voice_id` is computed once at cast time and stored in the persona's
#: contract — it is never recomputed at session time
#: (`okf/concepts/determinism.md`). Reordering this list, or inserting a voice
#: anywhere but the end, changes the modulus result for candidate ids that were
#: never re-cast, silently repointing the voice of every persona already
#: compiled against the old ordering. New voices may only be appended.
GEMINI_LIVE_VOICES: tuple[str, ...] = (
    "Zephyr",
    "Puck",
    "Charon",
    "Kore",
    "Fenrir",
    "Leda",
    "Orus",
    "Aoede",
    "Callirrhoe",
    "Autonoe",
    "Enceladus",
    "Iapetus",
    "Umbriel",
    "Algieba",
    "Despina",
    "Erinome",
    "Algenib",
    "Rasalgethi",
    "Laomedeia",
    "Achernar",
    "Alnilam",
    "Schedar",
    "Gacrux",
    "Pulcherrima",
    "Achird",
    "Zubenelgenubi",
    "Vindemiatrix",
    "Sadachbia",
    "Sadaltager",
    "Sulafat",
)

#: The vendor-documented voice gender of every roster member, split in two.
#: Source: Google's Gemini-TTS prebuilt voice table
#: (docs.cloud.google.com/text-to-speech/docs/gemini-tts), which is the same
#: roster the Live API speaks with.
#:
#: **This is a vendor fact, not a preference.** A voice is never reclassified —
#: the classification describes how the synthesized voice actually sounds, and
#: moving a name between the sets would silently re-voice every persona cast
#: since. The two sets must **partition** `GEMINI_LIVE_VOICES` exactly: every
#: roster voice appears in exactly one, and neither holds a name that is not on
#: the roster. A voice appended to the roster must be added to exactly one of
#: them in the same commit; `tests/test_voice.py` fails otherwise.
#:
#: Membership only — order lives in `GEMINI_LIVE_VOICES` and nowhere else,
#: because `pick_voice` hashes against an *ordered* sequence. Callers filter the
#: roster through these sets and keep its order (see
#: `candidate_agent.engine_contract.voices_for_presentation`).
GEMINI_FEMALE_VOICES: frozenset[str] = frozenset(
    {
        "Achernar",
        "Aoede",
        "Autonoe",
        "Callirrhoe",
        "Despina",
        "Erinome",
        "Gacrux",
        "Kore",
        "Laomedeia",
        "Leda",
        "Pulcherrima",
        "Sulafat",
        "Vindemiatrix",
        "Zephyr",
    }
)

#: The other half of the partition. See `GEMINI_FEMALE_VOICES`.
GEMINI_MALE_VOICES: frozenset[str] = frozenset(
    {
        "Achird",
        "Algenib",
        "Algieba",
        "Alnilam",
        "Charon",
        "Enceladus",
        "Fenrir",
        "Iapetus",
        "Orus",
        "Puck",
        "Rasalgethi",
        "Sadachbia",
        "Sadaltager",
        "Schedar",
        "Umbriel",
        "Zubenelgenubi",
    }
)

#: How long the token stays usable for *opening a new session*, as opposed to
#: how long the sessions it opened may run. Short on purpose: the browser mints
#: and connects in one breath, and a token that can still start a fresh call
#: minutes later is a token worth stealing.
NEW_SESSION_WINDOW_SECONDS = 120

#: Sampling knobs we deliberately leave at their defaults. Naming them here
#: pins them server-side, so a client cannot warm the persona up (or cool it
#: down) by passing its own values on connect.
LOCKED_FIELDS: tuple[str, ...] = ("temperature", "top_p", "top_k")


def _expires_at(token: Any, fallback: datetime) -> int:
    """Unix seconds the token stops being redeemable.

    The vendor returns ``expire_time`` as an RFC 3339 string. If it comes back
    absent or unparseable we fall back to the deadline we asked for, which is
    the same instant by construction — the browser only needs to know it must
    connect before then.
    """
    raw = getattr(token, "expire_time", None)
    if isinstance(raw, str) and raw:
        try:
            return int(datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp())
        except ValueError:
            pass
    return int(fallback.timestamp())


class GeminiLiveBroker(RealtimeBroker):
    """Mints ephemeral Gemini Live tokens for the browser."""

    def __init__(self, model_id: str, api_key: str) -> None:
        super().__init__(model_id)
        try:
            from google import genai
        except ImportError as exc:  # pragma: no cover - dependency is declared
            raise ModelError("google-genai is not installed") from exc
        self._client = genai.Client(api_key=api_key)

    @property
    def provider(self) -> str:
        """Provider name."""
        return "gemini"

    @property
    def voices(self) -> tuple[str, ...]:
        """Voices the Live API accepts."""
        return GEMINI_LIVE_VOICES

    async def mint(
        self,
        *,
        session: dict[str, Any],
        ttl_seconds: int,
    ) -> RealtimeCredential:
        """Mint a browser-redeemable Live token with the persona sealed inside."""
        from google.genai import types

        deadline = datetime.now(UTC) + timedelta(seconds=ttl_seconds)
        try:
            token = await self._client.aio.auth_tokens.create(
                config=types.CreateAuthTokenConfig(
                    expire_time=deadline,
                    new_session_expire_time=datetime.now(UTC)
                    + timedelta(seconds=NEW_SESSION_WINDOW_SECONDS),
                    uses=2,
                    live_connect_constraints=types.LiveConnectConstraints(
                        model=self.model_id,
                        config=_connect_config(session),
                    ),
                    lock_additional_fields=list(LOCKED_FIELDS),
                )
            )
        except Exception as exc:
            raise ModelError(f"gemini live token mint failed: {exc}") from exc

        name = getattr(token, "name", None)
        if not isinstance(name, str) or not name:
            raise ModelError("gemini returned no usable auth token")

        return RealtimeCredential(
            value=name,
            expires_at=_expires_at(token, deadline),
            model=self.model_id,
            # The JS SDK owns the Live endpoint; there is nothing to POST to.
            call_url="",
        )


def _connect_config(session: dict[str, Any]) -> Any:
    """Translate the compiled session document into the SDK's typed config.

    ``candidate_agent.voice`` builds a plain dict — it must not import a vendor
    SDK — using the Live API's own wire names, so this is a mapping and not a
    reinterpretation. The client-visible half is passed through as given: it is
    the same object the browser receives, which is what makes "what the server
    sealed" and "what the browser connects with" the same configuration.
    """
    from google.genai import types

    client_config = session.get("client_config") or {}
    if not isinstance(client_config, dict):
        raise ModelError("gemini session document has no client_config")

    vad = ((client_config.get("realtimeInputConfig") or {}).get("automaticActivityDetection")) or {}
    history = client_config.get("historyConfig") or {}

    return types.LiveConnectConfig(
        system_instruction=str(session.get("system_instruction", "")),
        response_modalities=list(client_config.get("responseModalities") or ["AUDIO"]),
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                    voice_name=str(session.get("voice", ""))
                )
            )
        ),
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        session_resumption=types.SessionResumptionConfig(),
        history_config=types.HistoryConfig(
            initial_history_in_client_content=bool(
                history.get("initialHistoryInClientContent", True)
            )
        ),
        realtime_input_config=types.RealtimeInputConfig(
            automatic_activity_detection=types.AutomaticActivityDetection(
                prefix_padding_ms=int(vad.get("prefixPaddingMs", 200)),
                silence_duration_ms=int(vad.get("silenceDurationMs", 650)),
            ),
            activity_handling=types.ActivityHandling.START_OF_ACTIVITY_INTERRUPTS,
        ),
    )
