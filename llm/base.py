"""Provider-agnostic model ports.

Dependency inversion: the agents depend on these abstractions, never on a vendor
SDK. Adding a provider means adding an implementation, not editing an agent
(open/closed), and any implementation is substitutable for any other because the
contracts below are the whole surface (Liskov).

Two ports, because two jobs with nothing in common beyond "call a model":

* :class:`StructuredModel` — one shot, one JSON object matching a schema. Used
  wherever code needs fields it can validate (persona casting, the judge pass).
* :class:`ChatModel` — a multi-turn conversation returning free text. Used by
  the live session, where the reply *is* the product and a schema would only
  get in the way.
* :class:`RealtimeBroker` — not a call at all. It mints a scoped credential so a
  *browser* can hold a speech-to-speech session with the vendor directly, which
  is the only way to get conversational latency. See
  :class:`RealtimeCredential`.

Interface segregation applies here as much as it does to storage: a session
agent that needs free text must not inherit a JSON-schema method it never calls.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

#: One conversation turn as the ports speak it: ``{"role": ..., "content": ...}``
#: with ``role`` in ``{"user", "assistant"}``. Provider-neutral on purpose —
#: mapping these onto a vendor's own role names is the implementation's job.
ChatMessage = dict[str, str]


class ModelError(RuntimeError):
    """Raised when a provider call fails or returns unusable output."""


class ModelClient(ABC):
    """Configuration every model port shares: which model, how warm, whose."""

    def __init__(self, model_id: str, temperature: float) -> None:
        self._model_id = model_id
        self._temperature = temperature

    @property
    def model_id(self) -> str:
        """The provider's model identifier, recorded alongside generated output."""
        return self._model_id

    @property
    def temperature(self) -> float:
        """Sampling temperature this instance was configured with."""
        return self._temperature

    @property
    @abstractmethod
    def provider(self) -> str:
        """Short provider name, e.g. ``gemini`` or ``openai``."""


class StructuredModel(ModelClient):
    """A chat model constrained to return one JSON object matching a schema.

    Implementations must honour three guarantees, or substituting one for
    another silently changes agent behaviour:

    1. ``generate_json`` returns a parsed ``dict`` — never a string, never None.
    2. ``system`` is applied as a system-level instruction, not prepended to the
       user turn, so provider-side caching and safety behave consistently.
    3. Failure raises :class:`ModelError`, not a provider-specific exception.
    """

    @abstractmethod
    async def generate_json(
        self,
        *,
        system: str,
        prompt: str,
        schema: dict[str, Any],
    ) -> dict[str, Any]:
        """Return one JSON object matching ``schema``.

        Args:
            system: System-level instruction (persona and guardrails).
            prompt: The user turn.
            schema: JSON Schema the response must satisfy.

        Raises:
            ModelError: The provider failed or returned unparseable output.
        """


class ChatModel(ModelClient):
    """A multi-turn conversational model returning one free-text reply.

    Implementations must honour four guarantees, for the same substitutability
    reason as above:

    1. ``generate_text`` returns a non-empty ``str`` — never None, never JSON.
    2. ``system`` is applied as a system-level instruction, verbatim. The caller
       compiled it deterministically; an implementation that edits, summarises,
       or reorders it changes the persona.
    3. ``messages`` are sent in the order given, with roles preserved. History
       order is the conversation.
    4. Failure raises :class:`ModelError`, not a provider-specific exception.
    """

    @abstractmethod
    async def generate_text(
        self,
        *,
        system: str,
        messages: list[ChatMessage],
    ) -> str:
        """Return the next assistant turn as plain text.

        Args:
            system: System-level instruction. Applied verbatim.
            messages: Conversation so far, oldest first. Each item is
                ``{"role": "user" | "assistant", "content": str}``.

        Raises:
            ModelError: The provider failed or returned an empty reply.
        """


class AudioModel(ModelClient):
    """A model that reads audio and answers against a JSON schema.

    Separate from :class:`StructuredModel` for the same reason `ChatModel` is
    separate: the payload differs. A caller that needs schema-constrained JSON
    from *text* must not be handed a port that requires bytes and a MIME type,
    and an adapter for a text-only model must not be forced to pretend it can
    hear.
    """

    async def analyze_audio(
        self,
        *,
        audio: bytes,
        mime_type: str,
        system: str,
        prompt: str,
        schema: dict[str, Any],
    ) -> dict[str, Any]:
        """Analyse one span of audio, returning JSON matching `schema`.

        Implementations raise :class:`ModelError` on transport or parse failure
        so callers never see a vendor exception type.
        """
        raise NotImplementedError


@dataclass(frozen=True)
class RealtimeCredential:
    """A short-lived secret a browser may use to open a realtime voice session.

    Deliberately not the account API key. The browser talks straight to the
    vendor for media — that is what keeps latency sane — so the thing it holds
    must be scoped to one session and expire on its own.
    """

    #: The ephemeral secret. Safe to hand to one browser; still a secret.
    value: str
    #: Unix seconds. The browser must open its connection before this.
    expires_at: int
    #: The realtime model the session was minted against.
    model: str
    #: The vendor endpoint the browser posts its SDP offer to.
    call_url: str


class RealtimeBroker(ABC):
    """Mints per-session credentials for a vendor's realtime voice API.

    Not a third way to call a model — the control plane never sees this audio.
    The broker's whole job is to push the vendor's session *configuration*
    (persona instructions, voice, turn detection) into a credential the browser
    can redeem, so the media path stays browser-to-vendor while the persona
    stays code-owned.

    Implementations must honour:

    1. ``mint`` returns a credential whose ``value`` is scoped to one session
       and expires. Never return the account key.
    2. ``session`` is passed to the vendor as given. It was compiled
       deterministically; an implementation that rewrites it changes the persona.
    3. Failure raises :class:`ModelError`.
    """

    def __init__(self, model_id: str) -> None:
        self._model_id = model_id

    @property
    def model_id(self) -> str:
        """The realtime model identifier sessions are minted against."""
        return self._model_id

    @property
    @abstractmethod
    def provider(self) -> str:
        """Short provider name, e.g. ``openai``."""

    @property
    @abstractmethod
    def voices(self) -> tuple[str, ...]:
        """Voice names this provider accepts, in a stable order.

        Stable order matters: the caller picks a persona's voice by indexing
        into this tuple with a hash of the persona, so reordering it would give
        every existing persona a new voice.
        """

    @abstractmethod
    async def mint(
        self,
        *,
        session: dict[str, Any],
        ttl_seconds: int,
    ) -> RealtimeCredential:
        """Mint a browser-redeemable credential for one voice session.

        Args:
            session: Vendor session configuration, compiled by the caller.
                Passed through unchanged apart from the model id.
            ttl_seconds: How long the credential stays redeemable.

        Raises:
            ModelError: The provider rejected the request.
        """
