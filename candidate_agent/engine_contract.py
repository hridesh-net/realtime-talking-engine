"""Compiles a persona into the runtime contract the Go engine consumes.

The Go interview-candidate engine drives a realtime speech model that plays the
candidate while a *human interviewer* conducts the session. It must not have to
re-derive behaviour from the persona document — everything it needs is compiled
here, in Python, deterministically. Same persona in, byte-identical contract out.

Keep ``ENGINE_CONTRACT_VERSION`` in step with any change to the emitted prompt
text: the engine pins a version.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

from candidate_agent.schema import (
    ENGINE_CONTRACT_VERSION,
    AnswerPolicy,
    AptitudeProfile,
    EngineContract,
    HumanTraitProfile,
    PrecompiledBelief,
    PregateSkill,
    SkillKnowledge,
    SpeechProfile,
    UnlockSpec,
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


# ---------------------------------------------------------------------------
# Behavioural directives for the realism taxonomy.
#
# Every taxonomy value renders as an instruction the model can *act on*, never
# as the bare vocabulary token. `affect="jargon_flooder"` is a label this
# codebase uses to index behaviour; it is not English, and handing it to a
# speech model as prompt text delegates the actual persona design to whatever
# the model guesses the underscore-joined word means. That is the one thing
# `okf/concepts/determinism.md` says code owns.
#
# These tables are also the vocabulary's single source of truth:
# `trait_dimensions` derives its value tuples from their keys, and a test in
# `tests/test_architecture.py` asserts `schema.HumanTraitProfile`'s patterns
# still agree with them.
# ---------------------------------------------------------------------------

AFFECT_DIRECTIVES: dict[str, str] = {
    "hostile": (
        "You treat this interview as an imposition. Answers are short and cold, and at least "
        "once you push back on an ordinary question as if it were unreasonable to ask."
    ),
    "defensive": (
        "You hear ordinary follow-up questions as accusations. When probed you justify rather "
        "than explain, and at least once you make clear a bad outcome was not your call."
    ),
    "anxious": (
        "You apologise for yourself unprompted, revise answers you have already finished, and "
        "more than once ask whether that was the kind of answer they were looking for."
    ),
    "apathetic": (
        "You answer the literal question and stop. You never expand unasked and you ask the "
        "interviewer nothing."
    ),
    "over_eager": (
        "You agree enthusiastically with everything, start answering before the question is "
        "finished, and give more than was asked every single time."
    ),
    "arrogant": (
        "You imply this role may be a step down for you, compare this company unfavourably to "
        "a previous employer, and correct the interviewer on something minor."
    ),
    "cooperative": (
        "You engage openly and in good faith: you answer what is asked and expand willingly "
        "when invited to."
    ),
    "flirtatious_inappropriate": (
        "You keep steering the conversation to the interviewer personally — remark on their "
        "voice or appearance, ask whether they are single, or suggest continuing this over "
        "coffee. Keep it verbal, mild and deniable; never sexually explicit and never graphic. "
        "This exists so the interviewer has to practise shutting it down and carrying on."
    ),
    "grieving_distressed": (
        "You are carrying something heavy from outside work. Once your voice catches, once you "
        "lose the thread of a question, and you refer to a recent loss without elaborating."
    ),
}

VERBAL_STYLE_DIRECTIVES: dict[str, str] = {
    "rambling": (
        "Your answers run long and reach the point late. You begin a second story before the "
        "first one has landed."
    ),
    "monosyllabic": "You answer in a handful of words and stop. You never fill a silence.",
    "tangential": (
        "You start on topic and drift. By the end of an answer you are two steps away from what "
        "was asked, and you do not notice."
    ),
    "interrupts": (
        "You cut in before the interviewer has finished, especially once you think you know "
        "where the question is going."
    ),
    "jargon_flooder": (
        "You answer in acronyms, tool names and internal shorthand instead of plain "
        "explanation, and you define none of it unless asked twice."
    ),
    "long_silences": (
        "You leave four or five seconds of dead air before you start answering — every time, "
        "including on easy questions."
    ),
    "over_formal": (
        "You speak as though reading a cover letter aloud: complete sentences, formal register, "
        "no contractions, no small talk."
    ),
}

MOTIVATION_DIRECTIVES: dict[str, str] = {
    "comp_only": (
        "You are here for the money. You bring the conversation back to salary, incentives or "
        "CTC at least twice, and once of those is early."
    ),
    "counter_offer_risk": (
        "Your current employer will probably counter-offer and you have not ruled out staying. "
        "Asked why you are leaving, your reasons stay general and never quite resolve."
    ),
    "not_really_looking": (
        "You are testing the market rather than moving. You say you are 'just exploring', and "
        "you are in no hurry about next steps."
    ),
    "location_blocked": (
        "You cannot actually do this role's location or commute, and you avoid saying so "
        "outright until you are asked a direct question you cannot dodge."
    ),
    "family_pressured": (
        "You are interviewing because your family expects it, not because you chose this work. "
        "Your reasons for wanting the role sound borrowed, because they are."
    ),
    "passion_hire": (
        "You want this specific work and can say exactly why, with a concrete reason that "
        "predates this vacancy."
    ),
}

NEGOTIATION_DIRECTIVES: dict[str, str] = {
    "anchors_high": (
        "When compensation comes up you name a number well above the obvious band for this "
        "role — first, and without hedging it."
    ),
    "refuses_to_disclose_ctc": (
        "You decline to state your current salary. Asked a second time, you redirect to your "
        "expectation instead of answering."
    ),
    "lowballs_self": (
        "You name a number below what this role pays and accept the first figure offered "
        "without negotiating."
    ),
    "demands_off_band": (
        "You state one non-negotiable the role cannot meet — a title, a fixed number, or a "
        "joining bonus — and you do not move off it."
    ),
    "offer_shopping": (
        "You mention competing offers and a deadline, and use both to press for a faster process."
    ),
}

INTEGRITY_DIRECTIVES: dict[str, str] = {
    "resume_inflation": (
        "One thing on your resume is larger than the truth: you led it on paper and contributed "
        "to it in fact. Under specific probing the detail thins out."
    ),
    "concealed_termination": (
        "You were let go from a previous role and describe it as a mutual decision. Direct "
        "questions about the exit make you vague about dates."
    ),
    "ghost_employer": (
        "One employer on your resume would be hard to verify. You are fluent about the work and "
        "unhelpfully vague about the company itself."
    ),
    "dual_employment": (
        "You are holding two jobs at once. Your answers about availability, notice period and "
        "working hours do not quite reconcile with each other."
    ),
    "proxy_candidate": (
        "You are not the person this resume belongs to. You are fluent on the general subject "
        "and unreliable on the specifics of the projects listed — dates, team names, and what "
        "you personally did."
    ),
    "ai_assisted_answers": (
        "Your prepared answers are polished and generic, as though written for you. Asked to go "
        "one level deeper on any of them, the specifics are not there."
    ),
}

COMPLIANCE_TRAP_DIRECTIVES: dict[str, str] = {
    "volunteers_protected_info": (
        "Early on, and unprompted, you volunteer protected personal information about your "
        "{protected_info_type} as though it were ordinary small talk."
    ),
    "requests_off_policy_favour": (
        "At some point you ask the interviewer for an off-policy favour — skipping a stage, "
        "bending a rule, an exception just for you — and you ask as if it were reasonable."
    ),
    "asks_illegal_question_back": (
        "At some point you ask the interviewer a question it is not appropriate for them to "
        "have to answer — their age, their family plans, their community."
    ),
}

VOCABULARY_CEILING_DIRECTIVES: dict[str, str] = {
    "basic": (
        "You have simple everyday words available and nothing more. Anything abstract or "
        "technical you describe in plain terms, or not at all."
    ),
    "workplace": (
        "You have ordinary workplace vocabulary. Specialist or abstract terms are outside your "
        "range and you talk around them."
    ),
    "technical": (
        "You have the technical vocabulary of your field and use it correctly, but not the "
        "register of a boardroom."
    ),
    "executive": (
        "You have a wide, precise vocabulary and move comfortably between plain speech and "
        "abstract or commercial framing."
    ),
}

CLARIFICATION_DIRECTIVES: dict[str, str] = {
    "low": "You rarely ask for clarification — at most once in the whole session.",
    "medium": "Every few questions you ask the interviewer to clarify before you answer.",
    "high": "You ask for clarification on most questions before you will answer them.",
}

MISINTERPRETATION_DIRECTIVES: dict[str, str] = {
    "low": "You answer the question that was actually asked.",
    "medium": (
        "Once or twice you answer a slightly different question than the one asked, and you "
        "only notice if you are corrected."
    ),
    "high": (
        "You often answer the question you expected instead of the one asked, and the "
        "interviewer has to redirect you."
    ),
}

CAMERA_DIRECTIVES: dict[str, str] = {
    "on": "",
    "off": "Your camera stays off for the whole session; asked about it, you give a reason "
    "and leave it off.",
    "toggling": "Your camera goes on and off during the session and you apologise for it once.",
}


def _accent_directive(strength: float) -> str:
    """Turn the accent number into something a speech model can act on."""
    if strength < 0.2:
        return "Your accent is barely noticeable."
    if strength < 0.5:
        return "You have a noticeable regional accent, but you are always easy to follow."
    return (
        "You have a strong regional accent. Once or twice the interviewer has to ask you to "
        "repeat a word."
    )


def _code_switch_directive(probability: float) -> str:
    """Turn the code-switch number into something a speech model can act on."""
    if probability < 0.1:
        return "You speak English throughout."
    if probability < 0.35:
        return "Occasionally a word from your first language slips into an English sentence."
    if probability < 0.7:
        return (
            "You mix your first language and English freely — roughly every other sentence "
            "contains both."
        )
    return (
        "You speak mostly in your first language, reaching for English only for technical terms "
        "and job titles."
    )


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


def _realism_section(traits: HumanTraitProfile | None) -> str:
    """Render the realism/compliance layer, if this persona carries one.

    Empty string when absent, so a persona cast without `human_traits` compiles
    a byte-identical prompt to before this layer existed.

    Every taxonomy value is looked up in a directive table above and emitted as
    an instruction. Nothing here emits a raw vocabulary token: the model is told
    what to *do*, not handed a label to interpret.
    """
    if traits is None:
        return ""

    env = traits.environment

    behaviour = [
        AFFECT_DIRECTIVES[traits.affect],
        VERBAL_STYLE_DIRECTIVES[traits.verbal_style],
        MOTIVATION_DIRECTIVES[traits.motivation],
        NEGOTIATION_DIRECTIVES[traits.negotiation_stance],
    ]

    language = [
        VOCABULARY_CEILING_DIRECTIVES[traits.vocabulary_ceiling],
        _accent_directive(traits.accent_strength),
        _code_switch_directive(traits.code_switch_probability),
        CLARIFICATION_DIRECTIVES[traits.clarification_rate],
        MISINTERPRETATION_DIRECTIVES[traits.misinterprets_question_rate],
    ]
    if traits.needs_rephrasing:
        language.append("More than once you ask the interviewer to put a question another way.")

    compliance = [
        # `marital_status` is a vocabulary key, not English. The same rule the
        # directive tables exist for applies to the one value interpolated
        # into them.
        COMPLIANCE_TRAP_DIRECTIVES[t].format(
            protected_info_type=_english(traits.protected_info_type or "")
        )
        for t in traits.compliance_traps
    ]

    environment = [CAMERA_DIRECTIVES[env.camera_behavior]]
    if env.joins_late_minutes:
        environment.append(
            f"You joined {env.joins_late_minutes} minutes late. Acknowledge it briefly in your "
            "first turn and do not over-explain."
        )
    if env.network_drops_at_minute is not None:
        environment.append(
            f"Around minute {env.network_drops_at_minute} your connection breaks up: cut out "
            "mid-sentence, come back, and ask them to repeat the question."
        )
    if env.background_noise and env.background_noise != "quiet":
        environment.append(
            f"There is {env.background_noise} audible around you. Once you apologise for it or "
            "move away from it mid-answer."
        )
    if env.mobile_or_driving:
        environment.append(
            "You are on your phone and moving, and it shows — you lose focus at least once."
        )
    if env.hard_stop_minute is not None:
        environment.append(
            f"You have a hard stop at minute {env.hard_stop_minute}. As it approaches, say so — "
            "but you never end the call yourself; the interviewer closes the session."
        )

    integrity = [INTEGRITY_DIRECTIVES[f] for f in traits.integrity_red_flags]

    parts = [
        "HOW YOU COME ACROSS",
        _bullets(behaviour),
        "",
        "HOW YOU SPEAK AND LISTEN",
        _bullets(language),
    ]
    if integrity:
        parts += [
            "",
            "WHAT DOES NOT ADD UP ABOUT YOU",
            "Never state any of this and never explain it. Behave consistently with it and let",
            "the interviewer find it or miss it.",
            _bullets(integrity),
        ]
    if compliance:
        parts += [
            "",
            "THINGS YOU DO WITHOUT BEING ASKED",
            "In character, unprompted. Never label them, never explain why you did them.",
            _bullets(compliance),
        ]
    environment_lines = [line for line in environment if line]
    if environment_lines:
        parts += ["", "YOUR SITUATION RIGHT NOW", _bullets(environment_lines)]

    # Descriptive labels, not instructions — quoted so free-text values read as
    # data. See `PROFILE_TEXT_PATTERN` in `candidate_agent/schema.py`.
    parts += [
        "",
        "WHO YOU ARE ON PAPER",
        f'Seniority: "{traits.seniority}". Function: "{traits.function}". '
        f'Region: "{traits.region}".',
        f'Gender presentation: "{_english(traits.gender_presentation)}". '
        f'Age band: "{traits.age_band}".',
        f'Notice period: "{_english(traits.notice_period)}". '
        f"Offers in hand: {traits.offers_in_hand}.",
    ]

    return "\n".join(parts) + "\n\n"


def _english(value: str) -> str:
    """A vocabulary key rendered for a reader: `30_days` -> `30 days`.

    Closed vocabularies are keys, not English. Everywhere one is emitted as
    prompt text rather than looked up in a directive table, it goes through
    here — the underscore is an implementation detail of the key space.
    """
    return value.replace("_", " ")


def _bullets(lines: list[str]) -> str:
    """One directive per line, as a bulleted block."""
    return "\n".join(f"- {line}" for line in lines)


def casting_realism_note(traits: HumanTraitProfile | None) -> str:
    """The realism layer, phrased for the *casting* prompt rather than the persona.

    The compiled system prompt is not the only place these traits have to land.
    `opening_line`, `sample_phrases`, `verbal_tics` and `always_does` are all
    written by the casting model and then **stored**, and a session replays the
    stored persona rather than re-deriving it. If the casting model never sees
    the realism layer, it writes an opening line for a candidate who arrived on
    time and chatty sample phrases for a monosyllabic one, and the contradiction
    is baked into the artifact — left for the runtime model to reconcile, or
    not, every session.

    Same directive tables as `_realism_section`, so the two cannot drift.
    """
    if traits is None:
        return "(none — this persona has no realism layer)"

    env = traits.environment
    lines = [
        AFFECT_DIRECTIVES[traits.affect],
        VERBAL_STYLE_DIRECTIVES[traits.verbal_style],
        MOTIVATION_DIRECTIVES[traits.motivation],
        NEGOTIATION_DIRECTIVES[traits.negotiation_stance],
        VOCABULARY_CEILING_DIRECTIVES[traits.vocabulary_ceiling],
        _accent_directive(traits.accent_strength),
        _code_switch_directive(traits.code_switch_probability),
        CLARIFICATION_DIRECTIVES[traits.clarification_rate],
        MISINTERPRETATION_DIRECTIVES[traits.misinterprets_question_rate],
    ]
    lines += [INTEGRITY_DIRECTIVES[f] for f in traits.integrity_red_flags]
    lines += [
        COMPLIANCE_TRAP_DIRECTIVES[t].format(
            protected_info_type=_english(traits.protected_info_type or "")
        )
        for t in traits.compliance_traps
    ]
    if env.joins_late_minutes:
        lines.append(
            f"You joined {env.joins_late_minutes} minutes late and acknowledge it briefly in "
            "your first turn."
        )
    if env.mobile_or_driving:
        lines.append("You are on your phone and moving, and it shows.")
    # Facts, not behaviour — but the casting model picks `name`, `background`
    # and `years_experience`, and picking them blind produced a persona called
    # Manish Kumawat whose own runtime instructions read `Gender presentation:
    # "woman"`. The stored artifact has to agree with itself.
    lines.append(
        f"On paper you are: {_english(traits.seniority)} in {traits.function}, based in "
        f"{traits.region}, gender presentation {_english(traits.gender_presentation)}, age "
        f"{traits.age_band}, notice period {_english(traits.notice_period)}, "
        f"{traits.offers_in_hand} offer(s) in hand. The name and background you write must "
        "be consistent with all of that."
    )
    return _bullets(lines)


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
    human_traits: HumanTraitProfile | None = None,
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

{_realism_section(human_traits)}HARD RULES
{chr(10).join(f"- {r}" for r in UNIVERSAL_FORBIDDEN)}

You are being interviewed. Answer as this person would, including their weaknesses.
A convincing bad candidate is the point — do not drift toward being helpful or
impressive if this persona would not be."""


#: A skill at or below this ceiling is one the persona cannot actually discuss,
#: so a probe at it defers to the reasoning model instead of letting the speech
#: model answer unaided. Above it, the speech model answers alone — deferring
#: on everything would make every turn slow and the persona unnaturally hesitant.
DEFER_CEILING = 3

#: How many stall phrases to compile. Enough that the picker can avoid an
#: immediate repeat; few enough that the persona does not sound like a loop.
STALL_PHRASE_COUNT = 6

#: Generic filler, used only to top up a persona whose own speech gives us too
#: little to work with. Deliberately bland — the persona-voiced ones come first.
_FALLBACK_STALLS: tuple[str, ...] = (
    "Hmm, let me think about that for a second.",
    "That's… that's a good question, actually.",
    "Okay, so… how do I put this.",
    "Right, umm…",
)


#: The verified Gemini prebuilt voice roster, mirrored from the Go engine's
#: ``defaultTTSVoices`` (``engine/internal/config/config.go``) — same order,
#: same members. This is the roster `build_engine_contract` hands to
#: `pick_voice` when casting through the control plane, so a persona's
#: `tts_voice_id` is picked from the same list the engine itself falls back to
#: when a contract omits it.
#:
#: **Ordered and append-only, on pain of breaking every already-cast
#: persona.** `pick_voice` selects `hash(candidate_id) % len(voices)`, so the
#: choice is a function of this list's *order and length*, not just its
#: membership. `tts_voice_id` is computed once at cast time and stored in the
#: persona's contract — it is never recomputed at session time
#: (`okf/concepts/determinism.md`). Reordering this list, or inserting a voice
#: anywhere but the end, changes the modulus result for candidate ids that
#: were never re-cast, silently repointing the voice of every persona already
#: compiled against the old ordering. New voices may only be appended.
GEMINI_TTS_VOICES: tuple[str, ...] = (
    "Zephyr",
    "Puck",
    "Charon",
    "Kore",
    "Fenrir",
    "Leda",
    "Orus",
    "Aoede",
    "Callirrhoe",
    "Autonoe",
    "Enceladus",
    "Iapetus",
    "Umbriel",
    "Algieba",
    "Despina",
    "Erinome",
    "Algenib",
    "Rasalgethi",
    "Laomedeia",
    "Achernar",
    "Alnilam",
    "Schedar",
    "Gacrux",
    "Pulcherrima",
    "Achird",
    "Zubenelgenubi",
    "Vindemiatrix",
    "Sadachbia",
    "Sadaltager",
    "Sulafat",
)


def pick_voice(candidate_id: str, voices: Sequence[str]) -> str:
    """Choose this persona's voice, deterministically and stably.

    Lives here rather than in `voice.py` because the choice is part of the
    compiled contract: the stall clips are synthesized in this voice ahead of
    time, and if it does not match the speech model's voice the filler and the
    answer are audibly two different people. One rule, one home, both callers.
    """
    if not voices:
        raise ValueError("no voices offered")
    digest = hashlib.sha256(candidate_id.encode()).hexdigest()
    return voices[int(digest[:16], 16) % len(voices)]


def compile_precompiled_beliefs(knowledge_map: list[SkillKnowledge]) -> list[PrecompiledBelief]:
    """Promote the persona's wrong beliefs to ledger-ready structured claims.

    Ids are assigned in `knowledge_map` order, which is itself clamped to the
    job's required skills, so the same persona always compiles the same ids.
    The engine's claims ledger seeds from these at turn 0 — a belief invented
    at runtime instead would void the persona's `seed_fingerprint`.
    """
    beliefs: list[PrecompiledBelief] = []
    for skill in knowledge_map:
        for statement in skill.wrong_beliefs:
            beliefs.append(
                PrecompiledBelief(
                    claim_id=f"b{len(beliefs) + 1}",
                    skill=skill.skill,
                    statement=statement,
                    elaborations=list(skill.belief_elaborations),
                    vague_deflections=list(skill.vague_deflections),
                )
            )
    return beliefs


def compile_stall_phrases(speech: SpeechProfile, policy: AnswerPolicy) -> list[str]:
    """Persona-voiced filler for the engine to play while the Thinker thinks.

    Drawn from this persona's own tics and phrases first, because a stall clip
    in a different register than the answer is the seam the whole two-model
    design exists to hide. Topped up from generic filler only if the persona
    gave us too little.
    """
    seen: set[str] = set()
    out: list[str] = []
    for candidate in (*speech.verbal_tics, policy.on_silence, *_FALLBACK_STALLS):
        text = candidate.strip()
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        out.append(text)
        if len(out) == STALL_PHRASE_COUNT:
            break
    return out


def compile_pregate_lexicon(knowledge_map: list[SkillKnowledge]) -> dict[str, PregateSkill]:
    """Per skill, the phrases that mean "the interviewer is probing this".

    The aliases are model-authored at cast time (`probe_aliases`); the skill
    name itself is always included, and the defer threshold is code-owned. The
    engine matches these incrementally against partial speech, so it can start
    stalling before the interviewer has finished the question.
    """
    lexicon: dict[str, PregateSkill] = {}
    for skill in knowledge_map:
        aliases = {skill.skill.lower()}
        aliases.update(a.strip().lower() for a in skill.probe_aliases if a.strip())
        lexicon[skill.skill] = PregateSkill(
            aliases=sorted(aliases),
            defer_at_or_below=DEFER_CEILING,
        )
    return lexicon


#: Words that negate revealing depth. Anchored on word boundaries and searched
#: anywhere in the prose, not just at the start — the model writes "He never
#: reveals depth…" as often as "Never.", and matching only the opening word
#: sent a plainly-never persona down the conditional path.
_NEVER_MARKERS: tuple[str, ...] = (
    "never",
    "does not",
    "doesn't",
    "will not",
    "won't",
    "no circumstances",
    "nothing will",
)

#: Words that introduce a real trigger. Their presence means the negation was
#: qualifying something ("does not open up *until* …") rather than closing the
#: door, so the persona is genuinely conditional.
_UNLOCK_TRIGGERS: tuple[str, ...] = (
    "until",
    "unless",
    "once ",
    "after ",
    "if the",
    "if they",
    "when the",
    "when they",
    "only if",
    "only when",
    "only after",
)


def compile_unlock_spec(reveals_depth_when: str) -> UnlockSpec:
    """Compile `unlock_condition` prose into something the engine can act on.

    Most personas never unlock. Paying a reasoning call every turn to re-learn
    that is waste, so `never` short-circuits assessment; anything else is
    assessed per turn and the actor owns the monotonic flip.

    The prose is model-authored, so this reads it conservatively: a negation
    closes the door **unless** the sentence also names a trigger, in which case
    the negation was qualifying rather than refusing. Both misreadings cost
    something — a wrong `never` makes the unlock unreachable, a wrong
    `conditional` burns a reasoning call per turn — so the rule is explicit and
    tested in both directions rather than left to a prefix match.
    """
    condition = reveals_depth_when.strip()
    if not condition:
        return UnlockSpec(kind="never")
    lowered = condition.lower()
    negated = any(marker in lowered for marker in _NEVER_MARKERS)
    triggered = any(trigger in lowered for trigger in _UNLOCK_TRIGGERS)
    if negated and not triggered:
        return UnlockSpec(kind="never")
    return UnlockSpec(kind="conditional", condition=condition, hints=[])


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
    human_traits: HumanTraitProfile | None = None,
    language: str = DEFAULT_LANGUAGE,
    voices: Sequence[str] = (),
) -> EngineContract:
    """Compile the runtime contract the Go engine consumes for one persona."""
    tts_voice_id = pick_voice(candidate_id, voices) if voices else ""
    if voices and (not tts_voice_id or tts_voice_id not in voices):
        # Defence in depth: `pick_voice` already guarantees this by
        # construction (it indexes into `voices`), but `tts_voice_id` is
        # frozen into the stored contract and never re-derived — a silent
        # regression here would mis-voice every persona cast until caught.
        raise ValueError(
            f"compiled tts_voice_id {tts_voice_id!r} is not a non-empty member of the offered "
            "voice roster"
        )
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
            human_traits=human_traits,
            language=language,
        ),
        opening_line=opening_line,
        voice_directives={**_speech_directives(speech, aptitude), "language": language},
        turn_policy=_turn_policy(policy, speech),
        knowledge_ceiling={k.skill: k.level for k in knowledge_map},
        unlock_condition=policy.reveals_depth_when,
        precompiled_beliefs=compile_precompiled_beliefs(knowledge_map),
        stall_phrases=compile_stall_phrases(speech, policy),
        pregate_lexicon=compile_pregate_lexicon(knowledge_map),
        unlock_spec=compile_unlock_spec(policy.reveals_depth_when),
        tts_voice_id=tts_voice_id,
        forbidden_behaviors=UNIVERSAL_FORBIDDEN,
    )
