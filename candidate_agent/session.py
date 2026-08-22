"""Candidate Session Agent — one persona turn in a live text interview.

Stateless by design. The control plane owns the session, its turns, and their
timestamps; this agent is handed the compiled contract plus the transcript so
far and returns the next thing the candidate says. Nothing here persists, and
nothing here decides *when* a turn happens.

The determinism split holds exactly as it does for casting: **code owns** the
system instruction (compiled and version-pinned in
:mod:`candidate_agent.engine_contract`), the transcript order, and the
speaker-to-role mapping; **the model owns** only the words of the reply.

Transcript turns arrive as plain mappings with ``speaker`` and ``text`` keys —
not the control plane's ``Turn`` model. Agents never import the control plane,
and the Go engine will hand over the same shape when the voice path lands.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from candidate_agent.prompts import build_session_system_prompt
from candidate_agent.schema import EngineContract
from llm.base import ChatMessage, ChatModel, ModelError
from llm.factory import build_chat_model

#: Transcript speakers. ``manager`` is the human being trained; ``candidate`` is
#: this persona. Kept as constants so a typo fails here rather than silently
#: replaying half the conversation in the wrong voice.
MANAGER = "manager"
CANDIDATE = "candidate"

#: speaker -> chat role. The persona is the assistant; everyone else is the user.
_ROLES = {MANAGER: "user", CANDIDATE: "assistant"}

#: Providers reject a history that opens on an assistant turn, and every session
#: opens on the persona's scripted opening line. This scene-setting turn goes in
#: front of it so the real transcript keeps its order and its first line.
SESSION_OPENER = "(The interviewer joins the call.)"


class CandidateSessionAgent:
    """Plays a cast persona through a typed interview, one turn at a time."""

    #: Warmer than casting: a session that reads like a form letter defeats the
    #: point. Nothing that has to be reproducible depends on this call.
    DEFAULT_TEMPERATURE = 0.8

    def __init__(self, model: ChatModel | None = None) -> None:
        # Injected for tests and for swapping providers; built from config
        # otherwise. This agent never imports a vendor SDK.
        self._model = model or build_chat_model("session", self.DEFAULT_TEMPERATURE)

    @property
    def model(self) -> str:
        """Model identifier, recorded against the session that used it."""
        return self._model.model_id

    async def reply(
        self,
        contract: EngineContract,
        turns: Sequence[Mapping[str, Any]],
    ) -> str:
        """Return the persona's next line, given the transcript so far.

        Args:
            contract: The persona's compiled engine contract. Its
                ``system_prompt`` is passed to the model verbatim.
            turns: The transcript, oldest first. Each turn needs a ``speaker``
                (``manager`` or ``candidate``) and a ``text``.

        Raises:
            ModelError: The provider failed, or the transcript is empty — there
                is nothing to reply to.
        """
        messages = self._to_messages(turns)
        if not messages:
            raise ModelError("cannot generate a reply from an empty transcript")
        return await self._model.generate_text(
            system=build_session_system_prompt(contract.system_prompt, contract.turn_policy),
            messages=messages,
        )

    @staticmethod
    def _to_messages(turns: Sequence[Mapping[str, Any]]) -> list[ChatMessage]:
        """Map the transcript onto chat roles, preserving order."""
        messages: list[ChatMessage] = [
            {"role": _ROLES.get(str(t["speaker"]), "user"), "content": str(t["text"])}
            for t in turns
        ]
        if messages and messages[0]["role"] == "assistant":
            messages.insert(0, {"role": "user", "content": SESSION_OPENER})
        return messages
