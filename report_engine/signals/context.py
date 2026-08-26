"""The shared read-only view every signal module works from."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import Any

from report_engine.schema import Evidence, QuestionAct, SessionBundle, Turn

PACKS = Path(__file__).resolve().parent.parent / "packs"


def load_pack(name: str) -> dict[str, Any]:
    """Read a versioned pack from `report_engine/packs`."""
    return json.loads((PACKS / f"{name}.json").read_text(encoding="utf-8"))


@dataclass(frozen=True)
class Context:
    """Everything the signal modules read. Built once, never mutated."""

    bundle: SessionBundle
    acts: list[QuestionAct]
    segments: dict[int, str] = field(default_factory=dict)

    @property
    def turns(self) -> list[Turn]:
        """Every turn, in order."""
        return self.bundle.turns

    @cached_property
    def manager_turns(self) -> list[Turn]:
        """Only the manager's turns."""
        return [t for t in self.turns if t.speaker == "manager"]

    @cached_property
    def candidate_turns(self) -> list[Turn]:
        """Only the candidate's turns."""
        return [t for t in self.turns if t.speaker == "candidate"]

    @cached_property
    def manager_text(self) -> str:
        """All manager speech as one string, for cue detection."""
        return "\n".join(t.text for t in self.manager_turns)

    @property
    def is_voice(self) -> bool:
        """Whether timing-derived signals can be computed at all."""
        return self.bundle.session.modality == "voice"

    @property
    def duration_ms(self) -> int:
        """Session length on the transcript clock."""
        return max((t.elapsed_ms for t in self.turns), default=0)

    def evidence(self, turn_index: int, quote: str) -> Evidence:
        """Anchor a claim to a turn. Every finding in the report carries one."""
        turn = next((t for t in self.turns if t.index == turn_index), None)
        return Evidence(
            turn_index=turn_index,
            at_ms=turn.elapsed_ms if turn else 0,
            speaker=turn.speaker if turn else "manager",
            quote=quote.strip()[:400],
        )

    def acts_in(self, segment: str) -> list[QuestionAct]:
        """Question acts belonging to one segment."""
        return [a for a in self.acts if self.segments.get(a.turn_index) == segment]
