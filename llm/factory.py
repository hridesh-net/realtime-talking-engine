"""Builds a model port implementation from environment configuration.

The one place that knows which providers exist. Agents receive an already-built
model, so nothing downstream of here imports a vendor SDK or reads provider
environment variables.

Model IDs are config, never hardcoded — see ``.env.example``.

Two registries, one per port. They are keyed identically on purpose: a provider
is only "supported" once it can serve both a structured call and a chat turn,
and an architecture test asserts the tables stay in step.
"""

from __future__ import annotations

import os
from collections.abc import Callable

from llm.base import ChatModel, ModelError, RealtimeBroker, StructuredModel
from llm.gemini import GeminiChatModel, GeminiModel
from llm.openai_model import OpenAIChatModel, OpenAIModel
from llm.openai_realtime import OpenAIRealtimeBroker

#: Provider name -> structured-output constructor. Adding a provider means
#: adding a row here, not editing an agent.
PROVIDERS: dict[str, Callable[[str, float, str], StructuredModel]] = {
    "gemini": GeminiModel,
    "openai": OpenAIModel,
}

#: Provider name -> free-text chat constructor. Same keys as ``PROVIDERS``.
CHAT_PROVIDERS: dict[str, Callable[[str, float, str], ChatModel]] = {
    "gemini": GeminiChatModel,
    "openai": OpenAIChatModel,
}

#: Provider name -> realtime-voice broker. **Deliberately partial.** Realtime
#: speech-to-speech is not something every provider offers on the same terms,
#: and pretending otherwise would mean shipping a broken Voice button for a
#: provider that cannot serve one. A provider missing here simply has no voice
#: mode; `test_ocp_realtime_table_is_a_documented_subset` asserts it is a subset
#: of PROVIDERS rather than equal to it.
REALTIME_PROVIDERS: dict[str, Callable[[str, str], RealtimeBroker]] = {
    "openai": OpenAIRealtimeBroker,
}

#: Realtime model per provider. Separate from DEFAULT_MODEL_IDS: a realtime
#: speech model is a different product line from the text model, and pointing
#: one at the other's id fails at mint time.
DEFAULT_REALTIME_MODEL_IDS: dict[str, str] = {
    "openai": "gpt-realtime-2",
}

#: Provider name -> environment variable holding its credential.
API_KEY_VARS: dict[str, str] = {
    "gemini": "GEMINI_API_KEY",
    "openai": "OPENAI_API_KEY",
}

DEFAULT_MODEL_IDS: dict[str, str] = {
    "gemini": "gemini-2.5-flash",
    "openai": "gpt-4o-mini",
}

#: Per-role env prefixes, checked before the shared fallback. A role exists so
#: one workload can be moved to a different provider or model without dragging
#: the others with it — the session runs hot and often, the judge runs once.
ROLE_PREFIXES: dict[str, str] = {
    "expectation": "EXPECTATION",
    "candidate": "CANDIDATE",
    "session": "SESSION",
    "judge": "JUDGE",
    "role_facts": "ROLE_FACTS",
    "voice": "VOICE",
}


def resolve_provider(role: str) -> str:
    """Pick a provider for ``role``: explicit config first, then available keys."""
    prefix = ROLE_PREFIXES.get(role)
    for var in (f"{prefix}_PROVIDER" if prefix else None, "LLM_PROVIDER"):
        if not var:
            continue
        name = (os.getenv(var) or "").strip().lower()
        if name:
            if name not in PROVIDERS:
                raise ModelError(
                    f"{var}={name!r} is not a known provider; "
                    f"choose one of {', '.join(sorted(PROVIDERS))}"
                )
            if not os.getenv(API_KEY_VARS[name]):
                raise ModelError(f"{var}={name!r} but {API_KEY_VARS[name]} is not set")
            return name

    for name in PROVIDERS:
        if os.getenv(API_KEY_VARS[name]):
            return name

    wanted = " or ".join(API_KEY_VARS[p] for p in PROVIDERS)
    raise ModelError(f"no provider credentials found; set {wanted}")


def resolve_model_id(role: str, provider: str) -> str:
    """Resolve the model ID for ``role``, falling back to the provider default."""
    prefix = ROLE_PREFIXES.get(role)
    if prefix:
        explicit = os.getenv(f"{prefix}_MODEL")
        if explicit:
            return explicit
    return os.getenv("LLM_MODEL") or DEFAULT_MODEL_IDS[provider]


def _credential(provider: str) -> str:
    api_key = os.getenv(API_KEY_VARS[provider])
    if not api_key:  # pragma: no cover - resolve_provider already checked
        raise ModelError(f"{API_KEY_VARS[provider]} is not set")
    return api_key


def build_model(role: str, temperature: float) -> StructuredModel:
    """Construct the configured structured-output model for ``role``.

    Args:
        role: A key of :data:`ROLE_PREFIXES` — selects the env prefix.
        temperature: Sampling temperature the agent requires.

    Raises:
        ModelError: No usable provider is configured.
    """
    provider = resolve_provider(role)
    return PROVIDERS[provider](resolve_model_id(role, provider), temperature, _credential(provider))


def build_chat_model(role: str, temperature: float) -> ChatModel:
    """Construct the configured conversational model for ``role``.

    Args:
        role: A key of :data:`ROLE_PREFIXES` — selects the env prefix.
        temperature: Sampling temperature the agent requires.

    Raises:
        ModelError: No usable provider is configured.
    """
    provider = resolve_provider(role)
    return CHAT_PROVIDERS[provider](
        resolve_model_id(role, provider), temperature, _credential(provider)
    )


def realtime_providers_available() -> list[str]:
    """Providers that can serve a voice session *and* have a credential set.

    The UI asks this before offering a Voice button: an empty list means voice
    is unavailable in this deployment, which is a configuration answer rather
    than an error.
    """
    return [p for p in REALTIME_PROVIDERS if os.getenv(API_KEY_VARS[p])]


def build_realtime_broker(role: str = "voice") -> RealtimeBroker:
    """Construct the configured realtime-voice broker for ``role``.

    Falls back to the first realtime-capable provider whose key is present,
    rather than to :func:`resolve_provider`'s answer — the text provider may
    well be one that offers no realtime API at all.

    Raises:
        ModelError: No realtime-capable provider is configured.
    """
    prefix = ROLE_PREFIXES.get(role)
    configured = (os.getenv(f"{prefix}_PROVIDER") or "").strip().lower() if prefix else ""
    if configured:
        if configured not in REALTIME_PROVIDERS:
            raise ModelError(
                f"{prefix}_PROVIDER={configured!r} has no realtime voice support; "
                f"choose one of {', '.join(sorted(REALTIME_PROVIDERS))}"
            )
        provider = configured
    else:
        available = realtime_providers_available()
        if not available:
            wanted = " or ".join(API_KEY_VARS[p] for p in REALTIME_PROVIDERS)
            raise ModelError(f"no realtime-capable provider configured; set {wanted}")
        provider = available[0]

    model_id = (os.getenv(f"{prefix}_MODEL") if prefix else None) or DEFAULT_REALTIME_MODEL_IDS[
        provider
    ]
    return REALTIME_PROVIDERS[provider](model_id, _credential(provider))
