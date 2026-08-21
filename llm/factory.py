"""Builds a :class:`~llm.base.StructuredModel` from environment configuration.

The one place that knows which providers exist. Agents receive an already-built
model, so nothing downstream of here imports a vendor SDK or reads provider
environment variables.

Model IDs are config, never hardcoded — see ``.env.example``.
"""

from __future__ import annotations

import os
from collections.abc import Callable

from llm.base import ModelError, StructuredModel
from llm.gemini import GeminiModel
from llm.openai_model import OpenAIModel

#: Provider name -> constructor. Adding a provider means adding a row here,
#: not editing an agent.
PROVIDERS: dict[str, Callable[[str, float, str], StructuredModel]] = {
    "gemini": GeminiModel,
    "openai": OpenAIModel,
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

#: Per-role env prefixes, checked before the shared fallback.
ROLE_PREFIXES: dict[str, str] = {
    "expectation": "EXPECTATION",
    "candidate": "CANDIDATE",
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


def build_model(role: str, temperature: float) -> StructuredModel:
    """Construct the configured model for ``role``.

    Args:
        role: ``expectation`` or ``candidate`` — selects the env prefix.
        temperature: Sampling temperature the agent requires.

    Raises:
        ModelError: No usable provider is configured.
    """
    provider = resolve_provider(role)
    api_key = os.getenv(API_KEY_VARS[provider])
    if not api_key:  # pragma: no cover - resolve_provider already checked
        raise ModelError(f"{API_KEY_VARS[provider]} is not set")
    return PROVIDERS[provider](resolve_model_id(role, provider), temperature, api_key)
