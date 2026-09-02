"""Second-credential failover for a provider that hands out more than one key.

A Gemini key can stop working mid-day for reasons that have nothing to do with
the request: the project's free-tier quota resets on someone else's clock, a key
gets rotated out of the console, a burst trips the per-key rate limit. Every one
of those surfaces to a hiring manager as a cast that failed or a voice session
that would not start, and every one of them is fixed by trying the *same* call
against a *different* key.

So: the factory builds one inner port instance per configured key and wraps them
in one of the classes below. The wrapper is the port — same interface, same
`ModelError` contract — and nothing downstream of `llm/` knows it exists. The API
does not change, the client sees nothing, and a deployment with a single key gets
no wrapper at all.

Three rules keep this from becoming a retry loop in disguise:

**Only key-shaped failures fail over.** `looks_like_a_key_failure` classifies;
anything else propagates untouched on the first attempt. A malformed request, a
schema the model could not satisfy, a parse error — those fail identically on
every key, and running them twice would double the latency and the bill to reach
the same exception.

**One extra attempt per key, never a loop.** The call is tried against each key
at most once, in order, and the last key's failure is raised as-is.

**Stickiness is process-wide.** Once a fallback key succeeds, later calls start
there — including calls through a *different* wrapper instance, because
`build_model` is called per agent and per-instance memory would forget the
switch immediately. A dead primary is paid for once per process, not once per
call. `reset_preferences()` exists so tests do not leak that state into each
other.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, TypeVar

from llm.base import (
    AudioModel,
    ChatMessage,
    ChatModel,
    RealtimeBroker,
    RealtimeCredential,
    StructuredModel,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")
R = TypeVar("R")

#: HTTP / gRPC statuses that mean "this credential cannot do this", as opposed
#: to "this request was wrong". 401 unauthenticated, 403 permission denied, 429
#: exhausted — all three are answered by trying another key, and none of them is
#: answered by trying the same key again.
KEY_FAILURE_STATUSES: frozenset[int] = frozenset({401, 403, 429})

#: Substrings that identify the same three conditions when only prose survives.
#: The adapters wrap vendor exceptions as ``ModelError(f"gemini call failed:
#: {exc}")``, so the vendor's own status name is usually still in the text.
#:
#: Deliberately **specific**. The obvious short marker "rate" appears inside
#: `generate_content`, which is in the message of every Gemini failure — it would
#: classify every error as key-shaped and fail over on malformed requests too.
#: For the same reason "expired" and "invalid" are only matched next to "key".
KEY_FAILURE_MARKERS: tuple[str, ...] = (
    "api key not valid",
    "api_key_invalid",
    "invalid api key",
    "invalid_api_key",
    "expired api key",
    "api key expired",
    "permission_denied",
    "permission denied",
    "resource_exhausted",
    "unauthenticated",
    "too many requests",
    "rate limit",
    "rate_limit",
    "ratelimit",
    "quota",
)

#: The same statuses again, for when a flattened message carries the number but
#: not the name ("gemini call failed: 429"). Word-bounded so a request id or a
#: token count cannot masquerade as one; a bare `in` test would match the "403"
#: inside any longer digit run.
_STATUS_IN_TEXT = re.compile(r"(?<!\d)(401|403|429)(?!\d)")

#: provider -> index of the key that last worked. Module-level on purpose; see
#: the module docstring on stickiness.
_preferred: dict[str, int] = {}


def reset_preferences() -> None:
    """Forget which key last worked. For tests, and for nothing else."""
    _preferred.clear()


def _chain(exc: BaseException) -> list[BaseException]:
    """The exception and everything it was raised from, innermost last."""
    seen: list[BaseException] = []
    current: BaseException | None = exc
    while current is not None and current not in seen:
        seen.append(current)
        current = current.__cause__ or current.__context__
    return seen


def looks_like_a_key_failure(exc: BaseException) -> bool:
    """Whether ``exc`` says the *credential* failed rather than the request.

    Checked structurally first — a status attribute on the vendor exception is
    unambiguous — then by message, because the adapters flatten vendor
    exceptions into `ModelError` text before anything here sees them.

    Conservative by design: a false positive costs one wasted retry, but it also
    means a genuinely broken request runs twice. A false negative just means a
    failover we could have done and did not, which is the pre-existing
    behaviour.
    """
    for link in _chain(exc):
        for attr in ("code", "status_code", "status"):
            value = getattr(link, attr, None)
            if isinstance(value, int) and value in KEY_FAILURE_STATUSES:
                return True
        response = getattr(link, "response", None)
        value = getattr(response, "status_code", None)
        if isinstance(value, int) and value in KEY_FAILURE_STATUSES:
            return True
        text = str(link).lower()
        if any(marker in text for marker in KEY_FAILURE_MARKERS):
            return True
        if _STATUS_IN_TEXT.search(text):
            return True
    return False


def _attempt_order(provider: str, count: int) -> list[int]:
    """Key indexes to try, the last known-good one first."""
    start = _preferred.get(provider, 0)
    if start >= count:  # a key was removed from config since we remembered it
        start = 0
    return [(start + offset) % count for offset in range(count)]


async def call_with_failover(
    provider: str,
    instances: Sequence[T],
    invoke: Callable[[T], Awaitable[R]],
) -> R:
    """Run ``invoke`` against each key in turn, stopping at the first success.

    Only a key-shaped failure moves on to the next key. Anything else — and the
    final key's failure, whatever its shape — is raised to the caller unchanged,
    so the `ModelError` contract the ports promise is preserved exactly.
    """
    order = _attempt_order(provider, len(instances))
    for position, index in enumerate(order):
        try:
            result = await invoke(instances[index])
        except Exception as exc:
            is_last = position == len(order) - 1
            if is_last or not looks_like_a_key_failure(exc):
                raise
            logger.warning(
                "%s key #%d failed (%s); retrying on key #%d",
                provider,
                index + 1,
                exc,
                order[position + 1] + 1,
            )
            continue
        if _preferred.get(provider, 0) != index:
            logger.warning("%s now using key #%d for subsequent calls", provider, index + 1)
            _preferred[provider] = index
        return result
    raise AssertionError("unreachable: the final attempt either returns or raises")


class FailoverStructuredModel(StructuredModel):
    """`StructuredModel` over one inner model per key."""

    def __init__(self, provider: str, instances: Sequence[StructuredModel]) -> None:
        super().__init__(instances[0].model_id, instances[0].temperature)
        self._provider = provider
        self._instances = list(instances)

    @property
    def provider(self) -> str:
        """Provider name — the wrapper is indistinguishable from its inners."""
        return self._provider

    async def generate_json(
        self, *, system: str, prompt: str, schema: dict[str, Any]
    ) -> dict[str, Any]:
        """One JSON object, from whichever key answers."""
        return await call_with_failover(
            self._provider,
            self._instances,
            lambda m: m.generate_json(system=system, prompt=prompt, schema=schema),
        )


class FailoverChatModel(ChatModel):
    """`ChatModel` over one inner model per key."""

    def __init__(self, provider: str, instances: Sequence[ChatModel]) -> None:
        super().__init__(instances[0].model_id, instances[0].temperature)
        self._provider = provider
        self._instances = list(instances)

    @property
    def provider(self) -> str:
        """Provider name — the wrapper is indistinguishable from its inners."""
        return self._provider

    async def generate_text(self, *, system: str, messages: list[ChatMessage]) -> str:
        """The next assistant turn, from whichever key answers."""
        return await call_with_failover(
            self._provider,
            self._instances,
            lambda m: m.generate_text(system=system, messages=messages),
        )


class FailoverAudioModel(AudioModel):
    """`AudioModel` over one inner model per key."""

    def __init__(self, provider: str, instances: Sequence[AudioModel]) -> None:
        super().__init__(instances[0].model_id, instances[0].temperature)
        self._provider = provider
        self._instances = list(instances)

    @property
    def provider(self) -> str:
        """Provider name — the wrapper is indistinguishable from its inners."""
        return self._provider

    async def analyze_audio(
        self,
        *,
        audio: bytes,
        mime_type: str,
        system: str,
        prompt: str,
        schema: dict[str, Any],
    ) -> dict[str, Any]:
        """One audio analysis, from whichever key answers."""
        return await call_with_failover(
            self._provider,
            self._instances,
            lambda m: m.analyze_audio(
                audio=audio,
                mime_type=mime_type,
                system=system,
                prompt=prompt,
                schema=schema,
            ),
        )


class FailoverRealtimeBroker(RealtimeBroker):
    """`RealtimeBroker` over one inner broker per key.

    Worth failing over even though nothing here calls the model: `mint` is the
    one request in a voice session that goes through this process, so a dead key
    is the difference between a working Voice button and a 502.
    """

    def __init__(self, provider: str, instances: Sequence[RealtimeBroker]) -> None:
        super().__init__(instances[0].model_id)
        self._provider = provider
        self._instances = list(instances)

    @property
    def provider(self) -> str:
        """Provider name — the wrapper is indistinguishable from its inners."""
        return self._provider

    @property
    def voices(self) -> tuple[str, ...]:
        """The roster — a vendor fact, identical on every key."""
        return self._instances[0].voices

    async def mint(self, *, session: dict[str, Any], ttl_seconds: int) -> RealtimeCredential:
        """One browser credential, minted on whichever key answers."""
        return await call_with_failover(
            self._provider,
            self._instances,
            lambda b: b.mint(session=session, ttl_seconds=ttl_seconds),
        )
