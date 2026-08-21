"""Provider-agnostic structured-output port.

Dependency inversion: the agents depend on this abstraction, never on a vendor
SDK. Adding a provider means adding an implementation, not editing an agent
(open/closed), and any implementation is substitutable for any other because the
contract below is the whole surface (Liskov).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class ModelError(RuntimeError):
    """Raised when a provider call fails or returns unusable output."""


class StructuredModel(ABC):
    """A chat model constrained to return one JSON object matching a schema.

    Implementations must honour three guarantees, or substituting one for
    another silently changes agent behaviour:

    1. ``generate_json`` returns a parsed ``dict`` — never a string, never None.
    2. ``system`` is applied as a system-level instruction, not prepended to the
       user turn, so provider-side caching and safety behave consistently.
    3. Failure raises :class:`ModelError`, not a provider-specific exception.
    """

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
