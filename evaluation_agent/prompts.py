"""Prompts for the evaluation layer.

Every prompt here drafts *statements* for a checklist the code already owns. The
model never decides which facts are on the list, only how each one reads for a
particular job.
"""

from __future__ import annotations

ROLE_FACTS_PERSONA = """You are a hiring operations analyst. You read a job description and
write down the handful of concrete facts a hiring manager must tell every
candidate about the role.

You write the fact as the manager would say it out loud, in one short sentence.
You never invent a number, a shift pattern, or a salary that the job description
does not support — if it is not there, you say so by leaving the fact empty."""

ROLE_FACTS_PROMPT = """Job title: {job_title}
Location: {location}

Job description:
{jd}

For each fact key below, write the one-sentence statement the manager should
convey for THIS role. Leave `statement` as an empty string when the job
description genuinely does not tell you — an empty fact is dropped from the
checklist, which is correct and far better than a plausible invention.

Fact keys and what each means:
- targets: the performance expectation, quota or volume
- shifts: working pattern, hours, rotational or fixed, week-offs
- location: where the person actually works from
- comp_band: pay range and how incentives work
- growth_path: what this role leads to, and roughly when
- next_steps: what happens after this interview and by when

Return JSON: {{"facts": [{{"key": "<one of the keys above>", "statement": "..."}}]}}
One entry per key, all {count} of them, in the order listed."""


def build_role_facts_prompt(*, job_title: str, jd: str, location: str, count: int) -> str:
    """Render the role-facts extraction prompt."""
    return ROLE_FACTS_PROMPT.format(
        job_title=job_title,
        jd=jd,
        location=location or "(not stated)",
        count=count,
    )
