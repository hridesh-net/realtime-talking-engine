---
type: Module
title: evaluation_agent/expectations.py
description: The granular rubric under the four fixed competencies — deterministic fixed items, and the agent that drafts wording and files a custom one.
resource: /evaluation_agent/expectations.py
tags: [evaluation, expectations, agent, determinism, rubric]
generated:
  by: claude-opus-5
  at: "2026-09-13T00:00:00Z"
verified:
  - by: claude-opus-5
    at: "2026-09-13T00:00:00Z"
status: stable
sources:
  - resource: /evaluation_agent/expectations.py
  - resource: /evaluation_agent/prompts.py
  - resource: /evaluation_agent/rubric.py
  - resource: /tests/test_expectations.py
---
# evaluation_agent/expectations.py

~260 lines, added 2026-09-13. `role_facts.py`'s discipline applied to a second
checklist — and the replacement for the retired
[expectation agent](/concepts/subsystems/expectation-agent.md), which generated
a *per-interview rubric* from a JD and was therefore the wrong shape for a
product where the rubric is fixed configuration.

# Schema

```python
COMPETENCY_IDS: tuple[str, ...] = DEFAULT_RUBRIC.ids   # derived, never restated
DEFAULT_COMPETENCY_ID = "structure"
ITEM_SOURCES = ("fixed", "drafted", "custom")
MAX_CUSTOM_ITEMS = 12
MAX_DRAFTED_PER_COMPETENCY = 3
MAX_ITEM_TEXT = 200
MAX_CLASSIFY_REASON = 200

class ExpectationItem(BaseModel):
    id: str; competency_id: str; text: str; source: str; enabled: bool = True

class ExpectationClassification(BaseModel):
    competency_id: str; reason: str = ""

def fixed_items() -> list[ExpectationItem]          # the rubric's own covers[], in order
def fixed_text_by_id() -> dict[str, str]            # id -> the rubric's wording

class ExpectationsAgent:
    DEFAULT_TEMPERATURE = 0.1
    def __init__(self, model: StructuredModel | None = None)  # build_model("expectations", 0.1)
    @property def model(self) -> str
    async def draft(self, *, job_title, jd, skills_required, location="") -> list[ExpectationItem]
    async def classify(self, *, text: str) -> ExpectationClassification
    @staticmethod _build_drafted(draft) -> list[ExpectationItem]       # the clamp
    @staticmethod _build_classification(answer) -> ExpectationClassification
```

## The ids are the contract

A fixed item's id is `f"{competency_id}.{_slug(covers)}"` — `_slug` lowercases,
replaces every non-alphanumeric run with `-`, strips and caps at 60. It is
deterministic by construction, which is the whole point: a stored interview
holds these ids, and an interview created last month has to match back to the
rubric today.

**So rewording a `covers` string in `rubric.py` re-keys every stored
interview's checklist.** `tests/test_expectations.py::test_fixed_item_ids_are_pinned_to_the_rubric`
lists all nineteen ids and fails when one moves, which is what turns "a typo fix
in the rubric" into a decision someone had to make rather than an accident.

Drafted ids are `drafted.{competency_id}.{n}`, numbered per competency in model
order. Custom ids are `custom.{n}`, **assigned server-side** by
`InterviewCreateRequest` in request order — whatever the client sent is
overwritten, so a client cannot mint an id that collides with anything.

## The clamps — four ways the model can be wrong, each discarded

`_build_drafted` is where the determinism split is actually enforced:

| The model says | What happens |
|---|---|
| a `competency_id` the rubric does not have | **dropped** |
| a fourth item under one competency | **dropped**, in model order — the first three win |
| 800 characters of prose | truncated to `MAX_ITEM_TEXT` |
| a restatement of a fixed item, in any case | **dropped** — two toggles for one behaviour is not a checklist |
| an empty or whitespace text | **dropped** |

The `seen` set is seeded with every fixed item's case-folded text and grows as
items are accepted, so an exact repeat inside one answer is dropped too. (The
plan specified deduplication against the fixed items; extending the same set to
accepted items falls out of the implementation and is recorded in
[log.md](/log.md).)

`_build_classification` has one clamp and it degrades rather than raises: an
answer outside the four competencies becomes `DEFAULT_COMPETENCY_ID` with a
**blank reason**. Losing the whole add-item interaction over a bad label is the
worse failure, and keeping the model's reason beside a competency it never chose
would present a rationale for a decision nobody made.

## What the prompts say, and the one thing they must not get wrong

`EXPECTATIONS_DRAFT_PERSONA` opens on it: *"The person being assessed is the
INTERVIEWER, never the candidate."* An item is something the hiring manager
should **do or say** — "Asks how they handled a missed quota", not "Has handled
a missed quota". `test_the_drafting_prompt_asks_for_interviewer_behaviour`
asserts the framing survives an edit, and that all four competencies reach the
prompt as `id (label)` so the model is *placing* items rather than inventing
headings.

Both prompts are short, ask for one JSON object and no reasoning around it, and
are JSON-schema constrained with an `enum` on `competency_id`. They run in the
creation wizard on whatever light model the `expectations` role points at
(`EXPECTATIONS_PROVIDER` / `EXPECTATIONS_MODEL`), so the clamps exist precisely
because a small model will sometimes ignore the enum.

## Where it is used

* `POST /api/v1/expectations/draft` and `.../classify` — the wizard's two calls, storing nothing.
* `InterviewCreateRequest.expectations` — `fixed_items()` is the default factory and `fixed_text_by_id()` is what rejects an edited fixed item. See [Interview record](/concepts/contracts/interview-record.md).
* `control_plane/reporting.build_analysis_context` — the **enabled** items reach the audio analysis as coverage context.
* `control_plane/api._enabled_expectations` — the same list reaches every persona cast, so the persona makes those behaviours worth performing.

WP2 is what makes the report engine *score* an item; today they are stored,
returned, cast against and analysed against.

## Related

[Evaluation agent](/concepts/subsystems/evaluation-agent.md) ·
[evaluation_agent/rubric.py](/concepts/modules/evaluation-agent-rubric.md) ·
[Determinism split](/concepts/determinism.md) ·
[Interview record](/concepts/contracts/interview-record.md)
