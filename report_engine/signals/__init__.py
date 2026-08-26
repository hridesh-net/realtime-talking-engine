"""Deterministic signal extraction.

Every signal declares its modality and returns `value=None` with a reason when
it cannot be measured, rather than a zero. A fake zero silently penalises a
manager for the modality they were given.
"""

from __future__ import annotations

from report_engine.schema import SignalResult
from report_engine.signals import clarity, communication, fairness, structure
from report_engine.signals.context import Context

__all__ = ["Context", "extract_all"]


def extract_all(ctx: Context) -> list[SignalResult]:
    """Every signal, in report order."""
    return [
        *structure.extract(ctx),
        *clarity.extract(ctx),
        *fairness.extract(ctx),
        *communication.extract(ctx),
    ]
