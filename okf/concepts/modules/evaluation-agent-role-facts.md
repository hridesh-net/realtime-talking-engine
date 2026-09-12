---
type: Module
title: evaluation_agent/role_facts.py
description: Drafts the per-interview wording of the fixed role-fact checklist — the model writes statements, never the list.
resource: /evaluation_agent/role_facts.py
tags: [evaluation, role-facts, agent, determinism]
generated:
  by: kimi-code/okf-curator
  at: "2026-08-22T21:10:00Z"
verified:
  - by: claude-opus-5
    at: "2026-09-10T00:00:00Z"
status: stable
sources:
  - resource: /evaluation_agent/role_facts.py
  - resource: /evaluation_agent/prompts.py
  - resource: /evaluation_agent/schema.py
---
# evaluation_agent/role_facts.py

74 lines. Turns a job description into statements for the fixed fact checklist.

# Schema

```python
class RoleFactsAgent:
    DEFAULT_TEMPERATURE = 0.1        # extraction, not invention
    def __init__(self, model: StructuredModel | None = None)   # build_model("role_facts", 0.1)
    @property def model(self) -> str
    async def extract(self, *, job_title: str, jd: str,
                      location: str = "") -> list[RoleFact]
    @staticmethod _build(draft) -> list[RoleFact]           # the clamp
```

## One concept, one name (2026-09-10)

This family used to answer to two names: the endpoint was already
`POST /role-facts` and the agent already `RoleFactsAgent`, while the column, the
Pydantic field, the model and the key tuple were all named after `clarity`
instead. Everything is now `role_facts` / `RoleFact` / `ROLE_FACT_KEYS`.

**`clarity` the rubric competency was deliberately left alone.** "Hiring with
Clarity" is one of the four things a manager is scored on (spec §5.B), and it
keeps its module `report_engine/signals/clarity.py`, its `CRITERION =
"clarity"`, its rubric id and its label. The rename exists to separate the
*input* — facts about the role — from the *competency* those facts evidence.
Conflating them is exactly what the old name did.

## The clamp is the design

The checklist itself is `ROLE_FACT_KEYS`, defined in code
([the subsystem page](/concepts/subsystems/evaluation-agent.md) explains why it
cannot vary per interview). `_build` clamps the model's answer onto it:

* a key that is not on the list is **discarded** — a hallucinated seventh fact
  cannot reach the report and quietly change what managers are measured against;
* a key the model omitted returns with an **empty statement** rather than
  vanishing — the operator sees what was not answered instead of a silently
  shortened checklist;
* statements are truncated to 300 characters;
* the return is always every key, in catalog order.

The prompt meets the clamp halfway: it tells the model to leave a fact empty
when the job description does not support it, because an empty fact is dropped
from that interview's checklist — *"far better than a plausible invention"*.

## Where it is called

`POST /api/v1/role-facts` — the wizard's auto-fill button. Nothing is stored;
the operator edits the drafts and the corrected list arrives later inside
`InterviewCreateRequest.role_facts`. `POST /interviews` itself stays
model-free.
