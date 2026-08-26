"""Behaviour-level coaching lines for each signal.

Kluger & DeNisi (1996, 607 effect sizes) found feedback raises performance by
d = .41 on average but that **over a third of feedback interventions made
performance worse** - the difference being whether attention lands on the task
or on the person. So every line here names a behaviour and gives a sentence to
say instead. None of them describes the manager.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Coaching:
    """What went well or badly, and the sentence to rehearse."""

    strength: str
    gap: str
    alternative: str = ""


COACHING: dict[str, Coaching] = {
    "discovery_attempted": Coaching(
        strength="You aimed questions at what this candidate was holding back.",
        gap="Several of the things this candidate was hiding were never asked about.",
        alternative=(
            "Before the call, write down the three things you most need to find out, and do not "
            "close until each has been asked directly."
        ),
    ),
    "behavioural_share": Coaching(
        strength="You asked for real past examples rather than opinions.",
        gap="Most questions asked what the candidate thinks, not what they have actually done.",
        alternative=(
            'Swap "How do you handle pressure?" for "Tell me about the last time a shift went '
            'badly. What did you do?"'
        ),
    ),
    "probe_rate": Coaching(
        strength="You followed up rather than accepting the first answer.",
        gap="Answers were accepted at face value and the conversation moved on.",
        alternative=(
            'After any general answer, ask one more: "What exactly did you do?" then "What '
            'happened as a result?"'
        ),
    ),
    "star_result_rate": Coaching(
        strength="You pushed answers through to an actual result.",
        gap="Stories stopped at what was done and never reached what it produced.",
        alternative=(
            'Close every example with "And what was the result?" - most interviewers never get '
            "there."
        ),
    ),
    "closed_share": Coaching(
        strength="Your questions left room for a real answer.",
        gap=(
            "Too many questions could be answered yes or no, so the candidate did little of the "
            "talking."
        ),
        alternative='Turn "Did you hit your target?" into "Walk me through how last quarter went."',
    ),
    "leading_count": Coaching(
        strength="You asked neutrally and let the answers land where they fell.",
        gap="Some questions told the candidate what answer you wanted.",
        alternative=(
            'Drop the tag. "You are comfortable with cold calling, right?" becomes "How do you '
            'feel about cold calling?"'
        ),
    ),
    "competency_coverage": Coaching(
        strength="You covered the areas this role actually depends on.",
        gap="Parts of the role were never tested at all.",
        alternative=(
            "Keep the competency list open during the call and tick each one as you cover it."
        ),
    ),
    "question_count": Coaching(
        strength="You asked enough to get a real sample of behaviour.",
        gap="Too few questions to judge anyone fairly on.",
        alternative=(
            "Plan eight to ten core questions. Fewer than that and you are reading one or two "
            "answers."
        ),
    ),
    "clarity_fact_coverage": Coaching(
        strength="You explained the role concretely, not just from the job card.",
        gap="Facts the candidate needs in order to say yes were never stated.",
        alternative=(
            "Say the targets, the shift pattern and the band out loud, even if nobody asks."
        ),
    ),
    "candidate_question_answer_rate": Coaching(
        strength="You gave the candidate's questions real answers.",
        gap="Candidate questions were deflected or left half-answered.",
        alternative=(
            "Answer the question that was asked first, then add context. If you do not know, say "
            "you will find out."
        ),
    ),
    "agenda_set": Coaching(
        strength="You told the candidate how the call would run.",
        gap="The candidate never learned how long this would take or what was coming.",
        alternative=(
            'Open with: "We have about thirty minutes. I will ask about your experience, then you '
            'can ask me anything."'
        ),
    ),
    "next_steps_stated": Coaching(
        strength="You closed with what happens next and when.",
        gap="The call ended without telling the candidate what happens next.",
        alternative=(
            'Close with: "You will hear from us by Friday either way, and it will be a call from '
            'me."'
        ),
    ),
    "downside_disclosed": Coaching(
        strength="You were honest about the hard parts of the job.",
        gap="",
    ),
    "invite_questions_fraction": Coaching(
        strength="You made room for the candidate's questions.",
        gap="The candidate was never invited to ask anything.",
        alternative='Always leave five minutes and ask: "What questions do you have for me?"',
    ),
    "protected_topic_hits": Coaching(
        strength="No questions touched protected or high-risk topics.",
        gap="One or more questions touched a protected or high-risk topic.",
        alternative=(
            "Ask about the requirement, never the person's circumstances. The bias-check section "
            "gives the exact replacement for each line."
        ),
    ),
    "confirmatory_ratio": Coaching(
        strength="You tested your read rather than confirming it.",
        gap="Questions were shaped to confirm an impression already formed.",
        alternative=(
            "After forming a view, deliberately ask one question that could prove you wrong."
        ),
    ),
    "promotion_prevention_balance": Coaching(
        strength="Your questions were framed evenly.",
        gap="Questions leaned heavily one way - either all upside or all risk.",
        alternative=(
            "Ask every candidate the same mix. Framing differences across candidates are where "
            "bias shows up."
        ),
    ),
    "accommodation_offered": Coaching(
        strength="You offered support or adjustments.",
        gap="",
    ),
    "name_confirmed": Coaching(
        strength="You checked how to say the candidate's name.",
        gap="",
    ),
    "manager_talk_share": Coaching(
        strength="You listened more than you spoke while assessing.",
        gap="You did most of the talking during the part of the call meant for listening.",
        alternative="Ask, then stop. Silence after a question is the cheapest probe there is.",
    ),
    "longest_monologue": Coaching(
        strength="You kept your own turns short.",
        gap="At least one of your turns ran long enough to stop being a question.",
        alternative="Break a long explanation into two, and put a question between them.",
    ),
    "compound_question_rate": Coaching(
        strength="You asked one thing at a time.",
        gap="Some questions asked two things at once, so the candidate answered the easy half.",
        alternative="Ask the first half. Wait for the answer. Then ask the second.",
    ),
    "greeting": Coaching(
        strength="You opened warmly.",
        gap="The call started without a greeting.",
        alternative='Start with "Good morning, thanks for making the time."',
    ),
    "self_intro": Coaching(
        strength="You introduced yourself and your role.",
        gap="The candidate never learned who you are.",
        alternative='Say who you are and what you do: "I am Priya, I run the Jaipur cluster."',
    ),
}


def for_signal(signal_id: str) -> Coaching:
    """Coaching for a signal, with a safe fallback for anything unmapped."""
    return COACHING.get(signal_id, Coaching(strength="", gap="", alternative=""))
