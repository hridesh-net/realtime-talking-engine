"""Regenerate the v1.3 sample `EngineContract`, from the compiler, not by hand.

``owner_handover/engine_contract_sample.json`` and its Go-side twin at
``engine/internal/contract/testdata/engine_contract_sample.json`` exist to show
(and test against) exactly what `candidate_agent.engine_contract` emits. A
hand-edited sample defeats that purpose — it can drift from the compiler and
nothing would notice. So this script drives the real compiling functions
(`build_engine_contract` and the helpers it calls: `compile_precompiled_beliefs`,
`compile_stall_phrases`, `compile_pregate_lexicon`, `compile_unlock_spec`,
`pick_voice`) over persona data lifted from
``owner_handover/candidate_output_sample.json`` — no live model call, no
network, fully deterministic.

The source persona is "Mateo Rodriguez" (the `clear_reject` sample already in
that file). Its `knowledge_map` predates `belief_elaborations` /
`vague_deflections` / `probe_aliases` (those fields were added to the schema
after that fixture was last regenerated from a live call), so this script
layers in literal, persona-consistent material for those fields — the same
kind of content the casting model would have authored into `CandidateDraft`
(see the "owned by the model" column of `okf/concepts/determinism.md`). That is
authoring *input* to the compiler, not hand-authoring the compiled contract
itself: every field that ends up in the emitted JSON — `precompiled_beliefs`,
`pregate_lexicon`, `stall_phrases`, `unlock_spec`, `tts_voice_id` — is still
produced by running the real compiler functions over that input.

Run:  .venv/bin/python scripts/export_engine_contract_sample.py
      .venv/bin/python scripts/export_engine_contract_sample.py --check
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candidate_agent.engine_contract import (  # noqa: E402
    DEFAULT_LANGUAGE,
    GEMINI_TTS_VOICES,
    build_engine_contract,
)
from candidate_agent.schema import (  # noqa: E402
    AnswerPolicy,
    AptitudeProfile,
    SkillKnowledge,
    SpeechProfile,
)

CANDIDATE_ID = "vc-0c4aff82e1cb"
INTERVIEW_ID = "5331accd-5df3-449e-9562-a1a0d5e16fbf"

NAME = "Mateo Rodriguez"
HEADLINE = (
    "Backend Engineer with experience in Go and distributed systems, focused on "
    "service development."
)
BACKGROUND = (
    "Mateo has spent 5 years working at a mid-sized e-commerce company, primarily "
    "maintaining existing Go services and implementing new features based on "
    "well-defined specifications. He has some exposure to Redis for caching and "
    "message queues, and understands microservices at a high level."
)
YEARS_EXPERIENCE = 5
OPENING_LINE = (
    "Hi, thanks for having me. I'm Mateo Rodriguez, excited to learn more about "
    "this Senior Backend Engineer role."
)

SPEECH = SpeechProfile(
    pace="measured",
    verbosity="balanced",
    filler_frequency=5,
    hesitation_frequency=6,
    formality="neutral",
    interrupts_interviewer=False,
    tone="vague, generic, textbook",
    verbal_tics=["You know...", "Like...", "I mean...", "Basically...."],
    sample_phrases=[
        "So, distributed systems are, like, when you have multiple computers working together.",
        "Redis is a really fast key-value store, good for caching.",
        "Microservices help you scale by breaking things into smaller pieces.",
        "I've worked with Go, it's very performant and has good concurrency.",
        "System design is about planning out how a system will work.",
    ],
)

APTITUDE = AptitudeProfile(
    smartness=3,
    dumbness=7,
    smartness_ratio=0.3,
    seriousness=4,
    effort=3,
    interest=6,
    honesty=6,
    preparedness=4,
    nervousness=4,
)

POLICY = AnswerPolicy(
    default_answer_depth="minimal",
    reveals_depth_when=(
        "This persona never reveals depth. When pressed, he restates his initial "
        "generic answers in slightly different words or waits for the interviewer "
        "to rephrase the question."
    ),
    on_unknown_question="guess_vaguely",
    on_pressure="restates the same generic answer in different words",
    on_silence="waits for the interviewer to move on",
    always_does=[
        "Provides generic, textbook definitions for technical terms.",
        "Uses buzzwords without concrete examples.",
        "Waits for the interviewer to prompt the next question after a brief answer.",
        "Avoids taking direct ownership for past project failures or challenges.",
    ],
    never_does=[
        "Propose multiple solutions with trade-offs.",
        "Ask clarifying questions about scale or specific constraints.",
        "Reference concrete production incidents or learnings.",
        "Demonstrate deep understanding of Go's strengths or weaknesses for specific use cases.",
    ],
)

# ``knowledge_map`` — lifted from the "clear_reject" persona in
# owner_handover/candidate_output_sample.json (`talking_points`,
# `breaking_point`, level, stance, first `wrong_belief` all verbatim from
# there), with a second wrong belief, `belief_elaborations`,
# `vague_deflections` and `probe_aliases` layered in on three of the five
# skills — enough to exercise every v1.3 field, in the model-authored voice
# the original casting draft for this persona would have used.
KNOWLEDGE_MAP = [
    SkillKnowledge(
        skill="Go",
        level=3,
        stance="shallow",
        talking_points=[
            "Go is good for concurrency with goroutines and channels.",
            "It's compiled and fast.",
            "Static typing helps catch errors.",
        ],
        breaking_point=(
            "Explaining `context.Context` propagation in a complex microservice call "
            "chain or the difference between `select` and `sync.WaitGroup` for "
            "different concurrency patterns."
        ),
        wrong_beliefs=[
            "Go's garbage collector is completely deterministic and never causes latency spikes.",
            "A goroutine leak will always crash the process immediately, so you'd always "
            "know when you have one.",
        ],
        belief_elaborations=[
            "He'll insist the GC runs on a fixed schedule and that's why their service "
            "never sees pauses in production.",
            "Pushed further, he says the runtime would just panic and exit if you leaked "
            "goroutines, so a silent leak isn't something he thinks is possible.",
        ],
        vague_deflections=[
            "It's, you know, mostly automatic — Go just handles memory for you in the background.",
            "I mean, the runtime is pretty good about cleaning that stuff up eventually, "
            "so I don't worry about it too much.",
        ],
        probe_aliases=[
            "garbage collector",
            "goroutines",
            "channels",
            "concurrency",
            "select statement",
            "golang",
        ],
    ),
    SkillKnowledge(
        skill="distributed systems",
        level=2,
        stance="shallow",
        talking_points=[
            "Distributed systems are multiple machines working together.",
            "They offer scalability and fault tolerance.",
            "Challenges include network latency and data consistency.",
        ],
        breaking_point=(
            "Explaining how to handle eventual consistency conflicts in a multi-region "
            "setup or designing a robust leader election mechanism."
        ),
        wrong_beliefs=[
            "All distributed systems problems can be solved with a message queue.",
            "Eventual consistency means the data is simply wrong until someone notices "
            "and fixes it by hand.",
        ],
        belief_elaborations=[
            "He'll say you just put a queue in front of anything flaky and the ordering "
            "sorts itself out on its own.",
            "Pressed on it, he describes eventual consistency as a bug you're expected "
            "to patch manually rather than a property the system settles into.",
        ],
        vague_deflections=[
            "It's basically about, like, things eventually syncing up across the servers.",
            "There's a lot of nuance there, but broadly it just works itself out over time.",
        ],
        probe_aliases=[
            "distributed system design",
            "consistency model",
            "eventual consistency",
            "leader election",
            "CAP theorem",
            "multi-region",
        ],
    ),
    SkillKnowledge(
        skill="Redis",
        level=3,
        stance="shallow",
        talking_points=[
            "Redis is an in-memory data store.",
            "It's great for caching and session management.",
            "Supports various data structures like strings, hashes, lists.",
        ],
        breaking_point=(
            "Explaining Redis cluster sharding strategies or how to handle cache "
            "invalidation for highly dynamic data."
        ),
        wrong_beliefs=[
            "Redis is always faster than a relational database, so just use it for everything.",
            "Redis data is automatically durable the moment you write it, the same as a "
            "database with a transaction log.",
        ],
        belief_elaborations=[
            "He'll argue there's no real reason to ever reach for Postgres once Redis is "
            "on the table.",
            "Pressed on durability, he insists a Redis write is already safe on disk "
            "before the client even gets its response back.",
        ],
        vague_deflections=[
            "It's basically an in-memory thing, so it's fast — that's really the main point.",
            "I mean, it persists eventually, I haven't gotten too deep into the internals.",
        ],
        probe_aliases=[
            "redis cluster",
            "cache invalidation",
            "persistence",
            "sharding",
            "RDB",
            "AOF",
        ],
    ),
    SkillKnowledge(
        skill="microservices",
        level=3,
        stance="shallow",
        talking_points=[
            "Microservices break down monolithic applications.",
            "They allow independent deployment and scaling.",
            "Teams can work on services independently.",
        ],
        breaking_point=(
            "Discussing strategies for distributed transactions or how to manage API "
            "versioning across many services."
        ),
        wrong_beliefs=[
            "More microservices always means better scalability and easier development.",
        ],
        probe_aliases=[
            "service boundaries",
            "API versioning",
            "distributed transactions",
            "service mesh",
        ],
    ),
    SkillKnowledge(
        skill="system design",
        level=1,
        stance="bluffs",
        talking_points=[
            "System design is about planning the architecture.",
            "You need to consider scalability, reliability, and performance.",
            "It involves choosing the right technologies.",
        ],
        breaking_point=(
            "Designing a new service from scratch, including data models, API "
            "contracts, and scaling considerations, beyond a high-level diagram."
        ),
        wrong_beliefs=[
            "System design is mostly about drawing boxes and arrows, the implementation "
            "details come later.",
        ],
        probe_aliases=[
            "system design interview",
            "capacity planning",
            "data model",
            "API contract",
            "scaling strategy",
        ],
    ),
]

#: Destinations that must carry an identical copy of the compiled contract —
#: the Python-side handover doc, and the Go engine's own test fixture.
OUTPUTS = [
    ROOT / "owner_handover" / "engine_contract_sample.json",
    ROOT / "engine" / "internal" / "contract" / "testdata" / "engine_contract_sample.json",
]


def _rendered() -> str:
    """The compiled contract, as the exact bytes both output files hold."""
    contract = build_engine_contract(
        candidate_id=CANDIDATE_ID,
        interview_id=INTERVIEW_ID,
        name=NAME,
        headline=HEADLINE,
        background=BACKGROUND,
        years_experience=YEARS_EXPERIENCE,
        speech=SPEECH,
        aptitude=APTITUDE,
        knowledge_map=KNOWLEDGE_MAP,
        policy=POLICY,
        opening_line=OPENING_LINE,
        human_traits=None,
        language=DEFAULT_LANGUAGE,
        voices=GEMINI_TTS_VOICES,
    )
    return json.dumps(contract.model_dump(mode="json"), indent=2) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit non-zero if either output file differs from what the compiler produces",
    )
    args = parser.parse_args()

    content = _rendered()

    stale: list[Path] = []
    for path in OUTPUTS:
        current = path.read_text() if path.exists() else None
        if current == content:
            continue
        if args.check:
            stale.append(path)
            continue
        path.write_text(content)
        print(f"wrote {path.relative_to(ROOT)}")

    if args.check:
        if stale:
            print(
                "engine contract sample(s) are stale; run scripts/export_engine_contract_sample.py:"
            )
            for path in stale:
                print(f"  - {path.relative_to(ROOT)}")
            return 1
        print("engine contract sample(s) match the compiler")
    return 0


if __name__ == "__main__":
    sys.exit(main())
