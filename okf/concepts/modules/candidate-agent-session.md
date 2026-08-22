---
type: Module
title: candidate_agent/session.py
description: Plays a cast persona through one typed interview turn — stateless, contract-verbatim, no persistence.
resource: /candidate_agent/session.py
tags: [candidate, session, chat, srp, determinism]
generated:
  by: claude-opus-5/okf-curator
  at: "2026-08-22T17:05:00Z"
verified:
  - by: claude-opus-5/okf-curator
    at: "2026-08-22T17:05:00Z"
status: stable
sources:
  - resource: /candidate_agent/session.py
  - resource: /candidate_agent/prompts.py
  - resource: /tests/test_session.py
---
# candidate_agent/session.py

```python
MANAGER   = "manager"
CANDIDATE = "candidate"
_ROLES    = {MANAGER: "user", CANDIDATE: "assistant"}
SESSION_OPENER = "(The interviewer joins the call.)"

class CandidateSessionAgent:
    DEFAULT_TEMPERATURE = 0.8
    def __init__(self, model: ChatModel | None = None) -> None
    @property def model(self) -> str
    async def reply(self, contract: EngineContract,
                    turns: Sequence[Mapping[str, Any]]) -> str
    @staticmethod def _to_messages(turns) -> list[ChatMessage]
```

## What it owns, and what it refuses to own

**Code owns** the system instruction (compiled and version-pinned by
[`engine_contract.py`](/concepts/modules/candidate-agent-engine-contract.md),
appended to — never edited — by
`prompts.build_session_system_prompt`), the transcript order, and the
speaker→role mapping. **The model owns** only the words of the reply. This is
the same split as casting, restated for the conversation; see
[Determinism](/concepts/determinism.md).

The agent is **stateless**. It does not know a session id, does not time a turn,
and does not decide when a turn happens — the control plane owns all three.
`test_agent_does_not_persist` asserts the instance holds exactly one attribute,
the model.

## Transcript turns are plain mappings, not `Turn`

`reply` takes `Sequence[Mapping[str, Any]]` needing only `speaker` and `text`,
**not** `control_plane.schemas.Turn`. Agents never import the control plane
(architecture test), and the Go engine will hand over the same shape when the
voice path lands — so the input type must belong to neither side.

## The two traps

1. **A history that opens on the assistant.** Every session's turn 0 is the
   persona's scripted opening line, and providers reject a conversation whose
   first message is an assistant turn. `_to_messages` prepends
   `SESSION_OPENER` as a scene-setting user turn when — and only when — the
   first real turn is the candidate's. Real turns keep their order and their
   content; nothing is dropped or rewritten.
2. **An empty transcript.** `reply` raises `ModelError` rather than asking the
   model to open the interview. The opening line is contract data, written at
   session creation by the repository; generating one here would produce a
   second, different opening.

Unknown speaker labels fall back to `"user"` — a mis-labelled turn shows up as a
visibly mis-attributed line rather than a provider error.

## The text-mode preamble

`prompts.build_session_system_prompt(system_prompt, turn_policy)` returns the
contract prompt verbatim, then appends `TEXT_MODE_PREAMBLE`: keep the fillers and
hesitations, emit words only (no stage directions, asterisks, speaker labels, or
markdown), one turn at a time, never write the interviewer's line, never drift
into being an assistant. The length rule is interpolated from the contract's
`turn_policy` (`target_sentences_per_answer`, `max_sentences`) so verbosity stays
a property of the archetype rather than of the prompt.

It lives in `prompts.py` because prompt modules build strings and perform no I/O
— `test_srp_prompt_modules_do_not_call_models` enforces that.

## Testing

`tests/test_session.py` (offline) drives it with a `FakeChatModel` that records
the exact call: system prompt starts with the contract's, preamble and length
rule present, roles mapped, order preserved, scene-setter added only when
needed, empty transcript rejected.
