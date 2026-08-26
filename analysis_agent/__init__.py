"""Audio analysis agent.

Takes one session's recording and the expectation it was held against, and
returns structured observations. It does **not** produce a report: the report
engine composes one from this analysis, and human trainers read that.

The agent's operating instructions live in `INSTRUCTIONS.md` beside this module,
versioned and shipped with the code, because they decide what every report is
ultimately built from.
"""

from analysis_agent.agent import AudioAnalysisAgent
from analysis_agent.schema import (
    ANALYSIS_INSTRUCTIONS_VERSION,
    AnalysisContext,
    SessionAnalysis,
)

__all__ = [
    "ANALYSIS_INSTRUCTIONS_VERSION",
    "AnalysisContext",
    "AudioAnalysisAgent",
    "SessionAnalysis",
]
