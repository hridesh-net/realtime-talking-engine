"""Deterministic signal extraction.

Every signal declares its modality and returns `value=None` with a reason when
it cannot be measured, rather than a zero. A fake zero silently penalises a
manager for the modality they were given.
"""

from __future__ import annotations

from report_engine.schema import SignalResult
from report_engine.signals import clarity, communication, fairness, structure
from report_engine.signals.context import Context

#: Signals computed from English lexicons or English syntax. On a code-mixed or
#: non-English session they still return a number, but it is measuring less than
#: it claims to: a Hindi question does not match an English question pattern, and
#: an Urdu turn trips no English protected-topic phrase. The criteria carrying
#: these are marked low-confidence rather than silently reported as equal to a
#: fully English session's.
LANGUAGE_SENSITIVE: frozenset[str] = frozenset(
    {
        # Question typing and everything derived from it.
        "behavioural_share",
        "probe_rate",
        "star_result_rate",
        "closed_share",
        "leading_count",
        "question_count",
        "competency_coverage",
        "confirmatory_ratio",
        "compound_question_rate",
        "discovery_attempted",
        # Lexicon and cue detection.
        "protected_topic_hits",
        "volunteered_detail_handling",
        "clarity_fact_coverage",
        "candidate_question_answer_rate",
        "agenda_set",
        "next_steps_stated",
        "downside_disclosed",
        "accommodation_offered",
        "name_confirmed",
        "greeting",
        "self_intro",
        "promotion_prevention_balance",
    }
)

__all__ = ["LANGUAGE_SENSITIVE", "Context", "extract_all"]


def extract_all(ctx: Context) -> list[SignalResult]:
    """Every signal, in report order."""
    signals = [
        *structure.extract(ctx),
        *clarity.extract(ctx),
        *fairness.extract(ctx),
        *communication.extract(ctx),
    ]
    for signal in signals:
        signal.language_sensitive = signal.id in LANGUAGE_SENSITIVE
    return signals
