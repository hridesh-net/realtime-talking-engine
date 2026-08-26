"""Standalone manager-assessment report engine.

One session bundle in, one report out. Reads no database, holds no session
state, and imports no sibling agent package — the rubric travels in the bundle.

See `docs/REPORT_ENGINE_SCORING_SPEC.md` for the scoring specification and the
provenance of every threshold.
"""

from report_engine.schema import AssessmentReport, SessionBundle
from report_engine.score import build_report

__all__ = ["AssessmentReport", "SessionBundle", "build_report"]
