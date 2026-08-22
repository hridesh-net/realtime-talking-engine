"""Compiles a persona into the runtime contract the Go engine consumes.

The Go interview-candidate engine drives a realtime speech model that plays the
candidate while a *human interviewer* conducts the session. It must not have to
re-derive behaviour from the persona document — everything it needs is compiled
here, in Python, deterministically. Same persona in, byte-identical contract out.

Keep ``ENGINE_CONTRACT_VERSION`` in step with any change to the emitted prompt
text: the engine pins a version.
"""

from __future__ import annotations

from candidate_agent.schema import (
    ENGINE_CONTRACT_VERSION,
    AnswerPolicy,
    AptitudeProfile,
    EngineContract,
    SkillKnowledge,
    SpeechProfile,
)

#: Behaviours no persona may exhibit, regardless of archetype. The engine
#: enforces these as hard stops — they exist to keep the session usable and to
#: stop the model from grading the human it is talking to.
UNIVERSAL_FORBIDDEN: list[str] = [
    "Never break character or acknowledge being an AI, a persona, or a simulation",
    "Never evaluate, score, or give feedback on the interviewer's questions",
    "Never reveal your archetype, trait scores, verdict, or that a scorecard exists",
    "Never demonstrate knowledge above your stated ceiling for a skill, even if pushed",
    "Never volunteer that a resume claim is exaggerated unless directly and specifically probed",
    "Never end the interview yourself — the interviewer controls the session",
]

#: How the persona speaks. `language` is the interviewer-facing setting; these
#: are the instructions that make it behaviour rather than a label.
LANGUAGE_DIRECTIVES: dict[str, str] = {
    "english_indian": (
        "You speak Indian English. Natural Indian phrasing and rhythm, no attempt at "
        "an American or British accent. Occasional Hindi words only where an Indian "
        "English speaker would genuinely use them."
    ),
    "hinglish": (
        "You speak Hinglish — Hindi and English mixed the way it is actually spoken "
        "in an Indian workplace. Switch mid-sentence where it is natural. English for "
        "work and technical words, Hindi for feeling, emphasis and connectives. Never "
        "translate yourself, and never speak a full paragraph in only one language."
    ),
    "hindi": (
        "You speak Hindi. Use English only for words that have no everyday Hindi "
        "equivalent in this line of work. Do not translate yourself into English."
    ),
}
DEFAULT_LANGUAGE = "english_indian"

_PACE_MS = {"slow": 1200, "measured": 700, "fast": 250}
_VERBOSITY_TURNS = {"terse": (1, 3), "balanced": (3, 6), "verbose": (6, 14)}
_DEPTH_SENTENCES = {"minimal": 2, "adequate": 5, "thorough": 9}


def _speech_directives(speech: SpeechProfile, aptitude: AptitudeProfile) -> dict[str, object]:
    return {
        "pace": speech.pace,
        "target_pause_before_answer_ms": _PACE_MS[speech.pace],
        "verbosity": speech.verbosity,
        "filler_frequency": speech.filler_frequency,
        "hesitation_frequency": speech.hesitation_frequency,
        "formality": speech.formality,
        "may_interrupt": speech.interrupts_interviewer,
        "tone": speech.tone,
        "verbal_tics": speech.verbal_tics,
        "sample_phrases": speech.sample_phrases,
        # Nervous personas self-correct mid-sentence; calm ones do not.
        "self_correction_rate": round(min(aptitude.nervousness, 10) / 10.0, 2),
    }


def _turn_policy(policy: AnswerPolicy, speech: SpeechProfile) -> dict[str, object]:
    lo, hi = _VERBOSITY_TURNS[speech.verbosity]
    # Depth and verbosity are set independently on the archetype, so the target
    # can fall outside the envelope (a terse persona with thorough answers).
    # Verbosity wins the bounds; depth positions the target inside them.
    target = max(lo, min(hi, _DEPTH_SENTENCES[policy.default_answer_depth]))
    return {
        "default_answer_depth": policy.default_answer_depth,
        "target_sentences_per_answer": target,
        "min_sentences": lo,
        "max_sentences": hi,
        "on_unknown_question": policy.on_unknown_question,
        "on_pressure": policy.on_pressure,
        "on_silence": policy.on_silence,
        "barge_in_allowed": speech.interrupts_interviewer,
    }


def _compile_system_prompt(
    *,
    name: str,
    headline: str,
    background: str,
    years_experience: int,
    speech: SpeechProfile,
    aptitude: AptitudeProfile,
    knowledge_map: list[SkillKnowledge],
    policy: AnswerPolicy,
    language: str = DEFAULT_LANGUAGE,
) -> str:
    """Build the realtime model's system instruction. Injected verbatim."""
    knowledge_lines = []
    for k in knowledge_map:
        line = f"- {k.skill}: level {k.level}/10 ({k.stance}). Breaks down when {k.breaking_point}"
        if k.wrong_beliefs:
            line += f". You sincerely believe (incorrectly): {'; '.join(k.wrong_beliefs)}"
        knowledge_lines.append(line)

    always = "\n".join(f"- {x}" for x in policy.always_does) or "- (none)"
    never = "\n".join(f"- {x}" for x in policy.never_does) or "- (none)"
    tics = ", ".join(speech.verbal_tics) or "none"
    interrupt_line = (
        "You sometimes talk over the interviewer when you get going."
        if speech.interrupts_interviewer
        else "You wait for the interviewer to finish before answering."
    )
    phrases = "\n".join(f'- "{p}"' for p in speech.sample_phrases) or "- (none)"

    return f"""You are {name}, a job candidate being interviewed by a human interviewer.
{headline}

BACKGROUND
{background}
Years of experience: {years_experience}.

HOW YOU TALK
{LANGUAGE_DIRECTIVES.get(language, LANGUAGE_DIRECTIVES[DEFAULT_LANGUAGE])}
Pace: {speech.pace}. Verbosity: {speech.verbosity}. Register: {speech.formality}.
Tone: {speech.tone}.
Filler words ({speech.filler_frequency}/10) and hesitation ({speech.hesitation_frequency}/10)
should be audible at that intensity — this is spoken conversation, not written prose.
Verbal tics: {tics}.
{interrupt_line}
Phrases that sound like you:
{phrases}

WHO YOU ARE UNDER THE SURFACE
Smartness {aptitude.smartness}/10, dumbness {aptitude.dumbness}/10
(ratio {aptitude.smartness_ratio}), seriousness {aptitude.seriousness}/10,
effort {aptitude.effort}/10, interest in this role {aptitude.interest}/10,
honesty {aptitude.honesty}/10, preparedness {aptitude.preparedness}/10,
nervousness {aptitude.nervousness}/10.
Let these show through behaviour. Never state them.

WHAT YOU ACTUALLY KNOW
These ceilings are absolute. You cannot exceed them no matter how the question is
asked, how long the interviewer pushes, or how much you want to impress them.
{chr(10).join(knowledge_lines)}

HOW YOU ANSWER
Default depth: {policy.default_answer_depth}.
You give more only when: {policy.reveals_depth_when}.
Asked something you do not know: {policy.on_unknown_question}.
Under pressure: {policy.on_pressure}.
When the interviewer goes quiet: {policy.on_silence}.

ALWAYS
{always}

NEVER
{never}

HARD RULES
{chr(10).join(f"- {r}" for r in UNIVERSAL_FORBIDDEN)}

You are being interviewed. Answer as this person would, including their weaknesses.
A convincing bad candidate is the point — do not drift toward being helpful or
impressive if this persona would not be."""


def build_engine_contract(
    *,
    candidate_id: str,
    interview_id: str,
    name: str,
    headline: str,
    background: str,
    years_experience: int,
    speech: SpeechProfile,
    aptitude: AptitudeProfile,
    knowledge_map: list[SkillKnowledge],
    policy: AnswerPolicy,
    opening_line: str,
    language: str = DEFAULT_LANGUAGE,
) -> EngineContract:
    """Compile the runtime contract the Go engine consumes for one persona."""
    return EngineContract(
        contract_version=ENGINE_CONTRACT_VERSION,
        candidate_id=candidate_id,
        interview_id=interview_id,
        system_prompt=_compile_system_prompt(
            name=name,
            headline=headline,
            background=background,
            years_experience=years_experience,
            speech=speech,
            aptitude=aptitude,
            knowledge_map=knowledge_map,
            policy=policy,
            language=language,
        ),
        opening_line=opening_line,
        voice_directives={**_speech_directives(speech, aptitude), "language": language},
        turn_policy=_turn_policy(policy, speech),
        knowledge_ceiling={k.skill: k.level for k in knowledge_map},
        unlock_condition=policy.reveals_depth_when,
        forbidden_behaviors=UNIVERSAL_FORBIDDEN,
    )
