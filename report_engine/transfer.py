"""Transfer functions — the only place a raw measurement becomes a score.

Keeping them here and naming them per signal means the shape of every
raw-to-score conversion is auditable in one file, which is what makes a
disputed score answerable.
"""

from __future__ import annotations


def _clamp(value: float) -> float:
    """Clamp to 0..10 and round.

    Rounding here rather than at each call site is what keeps the report's
    numbers stable: binary float noise in a sub-score propagates into the
    criterion mean and then into the readiness index, and "the same 62" has to
    survive a re-run to mean anything.
    """
    return round(max(0.0, min(10.0, value)), 2)


def linear_up(value: float, lo: float, hi: float) -> float:
    """0 at or below `lo`, 10 at or above `hi`. More is better."""
    if hi <= lo:
        raise ValueError("linear_up needs hi > lo")
    return _clamp((value - lo) / (hi - lo) * 10.0)


def linear_down(value: float, lo: float, hi: float) -> float:
    """10 at or below `lo`, 0 at or above `hi`. Less is better."""
    if hi <= lo:
        raise ValueError("linear_down needs hi > lo")
    return _clamp((hi - value) / (hi - lo) * 10.0)


def hit_rate(value: float) -> float:
    """A 0..1 proportion straight onto 0..10."""
    return _clamp(value * 10.0)


def boolean(value: bool, *, when_false: float = 0.0) -> float:
    """Present or absent."""
    return 10.0 if value else when_false


def penalty_count(count: int, step: float = 3.0) -> float:
    """Full marks at zero, dropping `step` points per occurrence."""
    return _clamp(10.0 - count * step)


def plateau(value: float, lo: float, hi: float, ceiling: float) -> float:
    """Full marks inside [lo, hi], decaying linearly out to `ceiling`.

    Used where both too little and too much are wrong — talk share being the
    case that motivated it.
    """
    if value < lo:
        return _clamp(value / lo * 10.0) if lo > 0 else 10.0
    if value <= hi:
        return 10.0
    if value >= ceiling:
        return 0.0
    return _clamp((ceiling - value) / (ceiling - hi) * 10.0)
