"""Prompts for the evaluation layer.

Every prompt here drafts *statements* for a checklist the code already owns. The
model never decides which facts are on the list, only how each one reads for a
particular job.

Two subjects share that rule and must not be confused. The role facts are about
the **role**. The expectation items are about the **interviewer** — the hiring
manager being assessed — and never about the candidate, which is the single
thing the drafting prompt below repeats most.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

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


# ---------------------------------------------------------------------------
# Expectation items
#
# Short and schema-constrained on purpose: both calls sit in the creation
# wizard, both run on whatever light model the `expectations` role is pointed
# at, and both must answer with one JSON object and no reasoning around it.
# ---------------------------------------------------------------------------

EXPECTATIONS_DRAFT_PERSONA = """You coach hiring managers on how to run an interview.

The person being assessed is the INTERVIEWER, never the candidate. Every line
you write is something the interviewer should DO or SAY in this interview —
"Asks how they handled a missed quota", not "Has handled a missed quota".

You write one short behaviour per line, in the present tense, starting with a
verb. You add nothing the job description does not support, and you never
invent a competency: you only place behaviours under the ones you are given."""

EXPECTATIONS_DRAFT_PROMPT = """Job title: {job_title}
Location: {location}
Skills this role requires: {skills_required}

Job description:
{jd}

Competencies this interviewer is scored on, and what each already covers:
{competency_block}

Propose extra behaviours that are specific to THIS job and are not already
covered above. At most {per_competency} per competency, at most {max_chars}
characters each. Behaviours of the INTERVIEWER. Propose nothing for a
competency where the job description gives you nothing to add — fewer, sharper
items beat filler.

Return one JSON object and nothing else:
{{"items": [{{"competency_id": "<one of the ids above>", "text": "..."}}]}}"""

EXPECTATIONS_CLASSIFY_PERSONA = """You file one interviewer behaviour under one competency.

You answer with exactly one of the competency ids you are given, plus one short
line saying why. You never invent an id and you never explain your reasoning at
length."""

EXPECTATIONS_CLASSIFY_PROMPT = """Competencies and what each covers:
{competency_block}

The interviewer behaviour to file:
{text}

Return one JSON object and nothing else:
{{"competency_id": "<one of the ids above>", "reason": "<one short line>"}}"""


def _competency_block(competencies: Sequence[dict[str, Any]]) -> str:
    """The four competencies as the prompts show them: id, label, what it covers."""
    lines = []
    for competency in competencies:
        covers = "; ".join(str(c) for c in competency.get("covers", []))
        lines.append(f"- {competency['id']} ({competency['label']}): {covers}")
    return "\n".join(lines)


def build_expectations_draft_prompt(
    *,
    job_title: str,
    jd: str,
    skills_required: Sequence[str],
    location: str,
    competencies: Sequence[dict[str, Any]],
    per_competency: int,
    max_chars: int,
) -> str:
    """Render the expectation-drafting prompt."""
    return EXPECTATIONS_DRAFT_PROMPT.format(
        job_title=job_title,
        location=location or "(not stated)",
        skills_required=", ".join(skills_required) or "(not stated)",
        jd=jd,
        competency_block=_competency_block(competencies),
        per_competency=per_competency,
        max_chars=max_chars,
    )


def build_expectations_classify_prompt(*, text: str, competencies: Sequence[dict[str, Any]]) -> str:
    """Render the prompt that files one custom item under a competency."""
    return EXPECTATIONS_CLASSIFY_PROMPT.format(
        competency_block=_competency_block(competencies),
        text=text,
    )
