"""Virtual Candidate Agent.

Generates one persona per (interview, archetype). The split of responsibility is
deliberate and mirrors ``expectation_agent``:

* **Code owns** the archetype, the verdict, every trait score (seeded from
  SHA256 so the same interview reproduces the same person), the scorecard
  weights, the knowledge ceilings, and the engine contract.
* **The model owns** only what has to be grounded in this specific job: who this
  person is, what they can talk about, where they break down, what they get
  wrong, and how they sound.

Same seed in, same persona out — the training reports are only comparable
across interviewers if the candidate does not drift between sessions.
"""

from __future__ import annotations

import hashlib
import json
import random
from typing import Any

from candidate_agent import archetypes as catalog
from candidate_agent.archetypes import CATALOG_VERSION, TRAIT_NAMES, Archetype
from candidate_agent.engine_contract import build_engine_contract
from candidate_agent.prompts import (
    PERSONA,
    SYSTEM_GUARDRAILS,
    build_user_prompt,
    expectation_note,
)
from candidate_agent.schema import (
    CANDIDATE_DRAFT_JSON_SCHEMA,
    PERSONA_VERSION,
    AnswerPolicy,
    AptitudeProfile,
    HumanTraitProfile,
    InterviewerScorecard,
    ResumeClaim,
    ScorecardItem,
    SkillKnowledge,
    SpeechProfile,
    VirtualCandidate,
)
from llm.base import StructuredModel
from llm.factory import build_model

STANCES = ("solid", "shallow", "bluffs", "absent")


def _stance(raw: object, fallback: str) -> str:
    """Accept a stance only if it is one the schema allows."""
    return raw if isinstance(raw, str) and raw in STANCES else fallback


def _rng(seed: str) -> random.Random:
    digest = hashlib.sha256(seed.encode()).hexdigest()
    return random.Random(int(digest[:16], 16))


def _fingerprint(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def derive_traits(archetype: Archetype, seed: str) -> dict[str, int]:
    """Pick trait scores inside the archetype bounds. Deterministic in `seed`."""
    rng = _rng(seed)
    return {name: rng.randint(*archetype.traits[name]) for name in TRAIT_NAMES}


def _aptitude(traits: dict[str, int]) -> AptitudeProfile:
    smart, dumb = traits["smartness"], traits["dumbness"]
    total = smart + dumb
    ratio = round(smart / total, 2) if total else 0.5
    return AptitudeProfile(smartness_ratio=ratio, **traits)


class VirtualCandidateAgent:
    """Casts virtual candidates for interviewer-training sessions."""

    #: Personas need texture, so this runs warmer than the expectation agent.
    #: Everything that must be reproducible is computed outside the model.
    DEFAULT_TEMPERATURE = 0.35

    def __init__(self, model: StructuredModel | None = None) -> None:
        # Injected for tests and for swapping providers; built from config
        # otherwise. This agent never imports a vendor SDK.
        self._model = model or build_model("candidate", self.DEFAULT_TEMPERATURE)

    @property
    def model(self) -> str:
        """Model ID recorded against generated personas."""
        return self._model.model_id

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------

    async def generate(
        self,
        *,
        interview_id: str,
        archetype_key: str,
        job_title: str,
        jd: str,
        skills_required: list[str],
        experience_level: str,
        company_type: str,
        job_location_type: str,
        duration_minutes: int,
        interview_type: str = "mixed",
        expectation: Any | None = None,
        seed_override: str | None = None,
        avoid_names: list[str] | None = None,
        human_traits: HumanTraitProfile | None = None,
        archetype: Archetype | None = None,
    ) -> VirtualCandidate:
        """Cast one persona for this interview and archetype.

        Args:
            interview_id: Interview the persona belongs to.
            archetype_key: Key from `candidate_agent.archetypes`.
            job_title: Role being interviewed for.
            jd: Job description text.
            skills_required: Skills the persona must have an opinion about.
            experience_level: junior, mid, or senior.
            company_type: startup or mnc.
            job_location_type: remote, onsite, or hybrid.
            duration_minutes: Interview length.
            interview_type: Type from the expectation document.
            expectation: Expectation document to ground the persona in, if any.
            seed_override: Replaces the default seed for reproducible casts.
            avoid_names: Names already used in this training set.
            human_traits: Optional realism/compliance layer (see
                `trait_dimensions.compose_human_traits`) — code-derived, never
                seen or authored by the model.
            archetype: A composed archetype to cast instead of looking
                `archetype_key` up in the catalog. Personas composed per
                interview are validated but never registered, so there is
                nothing in the catalog to find.

        Returns:
            The assembled persona, including its engine contract.
        """
        if archetype is None:
            archetype = catalog.get(archetype_key)
        elif archetype.key != archetype_key:
            raise ValueError(
                f"archetype key mismatch: {archetype.key!r} passed for {archetype_key!r}"
            )
        seed = seed_override or f"{interview_id}:{archetype_key}"

        # ---- Deterministic pre-computation (the model cannot override these) ----
        traits = derive_traits(archetype, seed)
        band_low, band_high = archetype.knowledge_band

        draft = await self._call_model(
            build_user_prompt(
                job_title=job_title,
                jd=jd,
                skills_required=skills_required,
                experience_level=experience_level,
                company_type=company_type,
                job_location_type=job_location_type,
                duration_minutes=duration_minutes,
                interview_type=interview_type,
                archetype_key=archetype.key,
                archetype_label=archetype.label,
                archetype_description=archetype.description,
                verdict=archetype.verdict,
                interviewer_challenge=archetype.interviewer_challenge,
                session_beats=archetype.session_beats,
                traits=traits,
                speech=archetype.speech,
                policy=archetype.answer_policy,
                band_low=band_low,
                band_high=band_high,
                allows_adjacent_strength=archetype.allows_adjacent_strength,
                must_discover=[
                    {"id": s.id, "generic_signal": s.signal} for s in archetype.must_discover
                ],
                expectation_note=expectation_note(expectation),
                avoid_names=avoid_names,
            )
        )

        candidate_id = f"vc-{hashlib.sha256(seed.encode()).hexdigest()[:12]}"

        speech = SpeechProfile(
            **archetype.speech,
            verbal_tics=[str(t) for t in draft.get("verbal_tics", [])][:6],
            sample_phrases=[str(p) for p in draft.get("sample_phrases", [])][:8],
        )
        aptitude = _aptitude(traits)
        knowledge_map = self._build_knowledge_map(draft, archetype, skills_required)
        policy = AnswerPolicy(
            **archetype.answer_policy,
            reveals_depth_when=draft.get("reveals_depth_when") or "Never opens up further.",
            always_does=[str(x) for x in draft.get("always_does", [])][:6],
            never_does=[str(x) for x in draft.get("never_does", [])][:6],
        )
        scorecard = self._build_scorecard(draft, archetype)
        resume_claims = self._build_resume_claims(draft)

        name = str(draft.get("name") or "Unnamed Candidate").strip()
        headline = str(draft.get("headline") or archetype.label).strip()
        background = str(draft.get("background") or archetype.description).strip()
        years = max(0, min(40, int(draft.get("years_experience") or 0)))
        opening_line = str(draft.get("opening_line") or "Hi, thanks for having me.").strip()

        engine = build_engine_contract(
            candidate_id=candidate_id,
            interview_id=interview_id,
            name=name,
            headline=headline,
            background=background,
            years_experience=years,
            speech=speech,
            aptitude=aptitude,
            knowledge_map=knowledge_map,
            policy=policy,
            opening_line=opening_line,
            human_traits=human_traits,
        )

        # Reproducibility claim: everything here is derived from the seed alone,
        # so a re-cast of the same interview and archetype reproduces it exactly.
        seed_fingerprint = _fingerprint(
            {
                "seed": seed,
                "archetype": archetype.key,
                "catalog_version": CATALOG_VERSION,
                "persona_version": PERSONA_VERSION,
                "traits": traits,
                "verdict": archetype.verdict,
                "human_traits": human_traits.model_dump() if human_traits else None,
            }
        )
        # Integrity claim: covers the model-authored content too, so a stored
        # persona that has been edited or re-cast no longer matches.
        fingerprint = _fingerprint(
            {
                "seed_fingerprint": seed_fingerprint,
                "name": name,
                "background": background,
                "knowledge": {k.skill: k.level for k in knowledge_map},
                "stances": {k.skill: k.stance for k in knowledge_map},
                "system_prompt": engine.system_prompt,
            }
        )

        candidate = VirtualCandidate(
            persona_version=PERSONA_VERSION,
            candidate_id=candidate_id,
            interview_id=interview_id,
            archetype=archetype.key,
            archetype_label=archetype.label,
            catalog_version=CATALOG_VERSION,
            name=name,
            headline=headline,
            background=background,
            years_experience=years,
            verdict=archetype.verdict,
            verdict_rationale=str(draft.get("verdict_rationale") or archetype.description).strip(),
            speech_profile=speech,
            aptitude=aptitude,
            knowledge_map=knowledge_map,
            resume_claims=resume_claims,
            answer_policy=policy,
            interviewer_scorecard=scorecard,
            engine_contract=engine,
            human_traits=human_traits,
            fingerprint=fingerprint,
            seed_fingerprint=seed_fingerprint,
            seed=seed,
        )
        candidate.raw_model_output = draft
        return candidate

    # ------------------------------------------------------------------
    # Deterministic assembly helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_knowledge_map(
        draft: dict[str, Any], archetype: Archetype, skills_required: list[str]
    ) -> list[SkillKnowledge]:
        """Every required skill present exactly once, clamped to the band."""
        low, high = archetype.knowledge_band
        by_skill = {
            str(e.get("skill", "")).strip().lower(): e
            for e in draft.get("knowledge_map", [])
            if isinstance(e, dict)
        }

        if low >= 7:
            stance_default = "solid"
        elif archetype.key == "inflated_resume":
            stance_default = "bluffs"
        else:
            stance_default = "shallow"
        entries: list[SkillKnowledge] = []

        for skill in skills_required:
            raw = by_skill.pop(skill.strip().lower(), None) or {}
            level = raw.get("level")
            level = int(level) if isinstance(level, (int, float)) else (low + high) // 2
            entries.append(
                SkillKnowledge(
                    skill=skill,
                    level=max(low, min(high, level)),  # clamp — the ceiling is ours
                    stance=_stance(raw.get("stance"), stance_default),
                    talking_points=[str(t) for t in raw.get("talking_points", [])][:5],
                    breaking_point=str(
                        raw.get("breaking_point") or "Pushed one level below a textbook definition."
                    ),
                    wrong_beliefs=[str(w) for w in raw.get("wrong_beliefs", [])][:4],
                )
            )

        # Adjacent-stack strengths are allowed through unclamped for personas
        # whose whole point is being strong somewhere else.
        if archetype.allows_adjacent_strength:
            for raw in by_skill.values():
                skill = str(raw.get("skill", "")).strip()
                if not skill:
                    continue
                level = raw.get("level")
                entries.append(
                    SkillKnowledge(
                        skill=skill,
                        level=max(0, min(10, int(level) if isinstance(level, (int, float)) else 8)),
                        stance=_stance(raw.get("stance"), "solid"),
                        talking_points=[str(t) for t in raw.get("talking_points", [])][:5],
                        breaking_point=str(raw.get("breaking_point") or "Rarely breaks down here."),
                        wrong_beliefs=[str(w) for w in raw.get("wrong_beliefs", [])][:4],
                    )
                )
        return entries

    @staticmethod
    def _build_scorecard(draft: dict[str, Any], archetype: Archetype) -> InterviewerScorecard:
        """Weights come from the catalog; the model only re-words the signals."""
        drafted = {
            str(d.get("id")): d for d in draft.get("must_discover", []) if isinstance(d, dict)
        }
        items = [
            ScorecardItem(
                id=s.id,
                signal=str(drafted.get(s.id, {}).get("signal") or s.signal),
                weight=s.weight,
                how_to_surface=str(drafted.get(s.id, {}).get("how_to_surface") or s.how_to_surface),
            )
            for s in archetype.must_discover
        ]
        return InterviewerScorecard(
            expected_verdict=archetype.verdict,
            interviewer_challenge=archetype.interviewer_challenge,
            must_discover=items,
            interviewer_failure_modes=archetype.interviewer_failure_modes,
            pass_condition=(
                "The interviewer surfaces signals totalling at least 0.70 weight and "
                f"records a verdict of '{archetype.verdict}' with specific evidence."
            ),
        )

    @staticmethod
    def _build_resume_claims(draft: dict[str, Any]) -> list[ResumeClaim]:
        claims: list[ResumeClaim] = []
        for raw in draft.get("resume_claims", [])[:6]:
            if not isinstance(raw, dict) or not raw.get("claim"):
                continue
            truth = raw.get("truthfulness")
            claims.append(
                ResumeClaim(
                    claim=str(raw["claim"]),
                    truthfulness=truth if truth in ("true", "exaggerated", "false") else "true",
                    probe_that_exposes_it=str(
                        raw.get("probe_that_exposes_it") or "Ask what they personally implemented."
                    ),
                )
            )
        return claims

    async def _call_model(self, prompt: str) -> dict[str, Any]:
        """Delegate to the injected provider."""
        return await self._model.generate_json(
            system=f"{PERSONA}\n\n{SYSTEM_GUARDRAILS}",
            prompt=prompt,
            schema=CANDIDATE_DRAFT_JSON_SCHEMA,
        )
