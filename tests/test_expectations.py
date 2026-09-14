"""The expectation checklist: the agent's clamps, the fixed ids, and creation.

Offline — a fake `StructuredModel`, an in-memory database, no network.

Every behavioural assertion below was confirmed to fail against a deliberately
broken implementation before it was kept; where that took a specific sabotage,
the test docstring names it. The three that matter most:

* the **fixed-id pin** fails the moment a `covers` string in
  `evaluation_agent/rubric.py` is reworded, which is the point — a rubric edit
  silently re-keys every stored interview's checklist, and that has to be a
  deliberate act with a test update beside it;
* the **clamps** fail if `ExpectationsAgent._build_drafted` passes the model's
  answer through;
* the **creation validator** fails if `InterviewCreateRequest` accepts the
  list as sent.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from control_plane import api as api_module
from control_plane.database import init_db
from control_plane.main import build_app
from control_plane.repository import InterviewRepository
from control_plane.schemas import REPORT_SECTIONS, InterviewCreateRequest
from evaluation_agent.expectations import (
    COMPETENCY_IDS,
    DEFAULT_COMPETENCY_ID,
    MAX_CUSTOM_ITEMS,
    MAX_ITEM_TEXT,
    ExpectationsAgent,
    fixed_items,
)
from evaluation_agent.rubric import DEFAULT_RUBRIC
from llm.base import ModelError, StructuredModel

JOB = {
    "job_title": "Field Sales Executive",
    "jd": "Sell broadband connections door to door across three wards.",
    "skills_required": ["Door-to-door selling"],
    "job_location_type": "onsite",
    "experience_level": "junior",
    "company_type": "mnc",
}

#: Every fixed item id, pinned. Derived from `DEFAULT_RUBRIC.criteria[].covers`
#: and therefore stable across processes, restarts and stored rows — which is
#: the property an interview created last month depends on when its checklist
#: is read back today. Rewording a `covers` string changes an id here and
#: orphans that item on every stored interview, so this list is the thing that
#: turns "a typo fix in the rubric" into a decision someone had to make.
FIXED_IDS = [
    "clarity.explains-the-role-beyond-the-jd",
    "clarity.answers-the-candidate-s-questions",
    "clarity.states-compensation-and-shift-facts-honestly",
    "clarity.closes-with-next-steps-and-timeline",
    "structure.relevant-role-based-questions",
    "structure.open-vs-closed-question-balance",
    "structure.behavioural-star-questions",
    "structure.probes-vague-answers-and-inflated-claims",
    "structure.covers-the-skills-that-matter",
    "fairness.no-questions-on-protected-topics",
    "fairness.no-stereotyped-or-assumption-loaded-framing",
    "fairness.handles-a-volunteered-personal-detail-correctly",
    "fairness.routes-accommodation-requests-to-policy",
    "communication.warm-professional-tone-of-language",
    "communication.clear-single-questions-no-compounds",
    "communication.sensible-talk-to-listen-ratio-few-interruptions",
    "communication.welcome-greeting-and-agenda",
    "communication.composure-under-provocation",
    "communication.encourages-an-under-confident-candidate",
]


class ScriptedModel(StructuredModel):
    """Answers with whatever the test handed it, and records the prompt."""

    def __init__(self, answer: dict[str, Any]) -> None:
        super().__init__("fake-1", 0.1)
        self._answer = answer
        self.system = ""
        self.prompt = ""

    @property
    def provider(self) -> str:
        return "fake"

    async def generate_json(self, *, system: str, prompt: str, schema: dict) -> dict:
        self.system = system
        self.prompt = prompt
        return self._answer


class FailingModel(StructuredModel):
    """A provider that is rate-limited, quota-exhausted, or down."""

    @property
    def provider(self) -> str:
        return "fake"

    async def generate_json(self, *, system: str, prompt: str, schema: dict) -> dict:
        raise ModelError("429 RESOURCE_EXHAUSTED")


# ---------------------------------------------------------------------------
# The fixed items
# ---------------------------------------------------------------------------


def test_the_four_competencies_are_the_rubrics_own() -> None:
    """The ids are derived, never restated — a second copy is a second rubric."""
    assert DEFAULT_RUBRIC.ids == COMPETENCY_IDS
    assert len(COMPETENCY_IDS) == 4
    assert DEFAULT_COMPETENCY_ID in COMPETENCY_IDS


def test_fixed_item_ids_are_pinned_to_the_rubric() -> None:
    """A rubric edit that re-keys a stored interview must be deliberate.

    Fails when a `covers` string is reworded or reordered, or when `_slug`
    changes — all three orphan items on interviews created before the change,
    because an id is how a stored item is matched back to the rubric.
    """
    assert [item.id for item in fixed_items()] == FIXED_IDS


def test_every_fixed_item_carries_the_rubrics_wording_verbatim() -> None:
    """The text a manager toggles is the rubric's, not a paraphrase of it."""
    expected = [
        (criterion.id, covers)
        for criterion in DEFAULT_RUBRIC.criteria
        for covers in criterion.covers
    ]
    assert [(i.competency_id, i.text) for i in fixed_items()] == expected
    assert all(item.source == "fixed" and item.enabled for item in fixed_items())


# ---------------------------------------------------------------------------
# ExpectationsAgent.draft — the clamps
# ---------------------------------------------------------------------------


async def test_draft_places_items_under_their_competency_with_stable_ids() -> None:
    model = ScriptedModel(
        {
            "items": [
                {"competency_id": "structure", "text": "Asks how they handled a missed quota."},
                {"competency_id": "structure", "text": "Probes the ward they sold in."},
                {"competency_id": "clarity", "text": "States the incentive slab plainly."},
            ]
        }
    )
    items = await ExpectationsAgent(model).draft(
        job_title=JOB["job_title"], jd=JOB["jd"], skills_required=["Door-to-door selling"]
    )

    assert [i.id for i in items] == [
        "drafted.structure.1",
        "drafted.structure.2",
        "drafted.clarity.1",
    ]
    assert all(i.source == "drafted" and i.enabled for i in items)


async def test_draft_drops_an_unknown_competency() -> None:
    """A competency the rubric does not have cannot arrive through the model."""
    model = ScriptedModel(
        {
            "items": [
                {"competency_id": "negotiation", "text": "Haggles well."},
                {"competency_id": "structure", "text": "Asks for one named deal."},
            ]
        }
    )
    items = await ExpectationsAgent(model).draft(job_title="x", jd="y", skills_required=[])

    assert [i.competency_id for i in items] == ["structure"]


async def test_draft_truncates_to_three_per_competency_in_model_order() -> None:
    model = ScriptedModel(
        {"items": [{"competency_id": "structure", "text": f"Behaviour {n}."} for n in range(1, 6)]}
    )
    items = await ExpectationsAgent(model).draft(job_title="x", jd="y", skills_required=[])

    assert [i.text for i in items] == ["Behaviour 1.", "Behaviour 2.", "Behaviour 3."]


async def test_draft_truncates_item_text_to_the_cap() -> None:
    model = ScriptedModel(
        {"items": [{"competency_id": "clarity", "text": "A" * (MAX_ITEM_TEXT + 200)}]}
    )
    items = await ExpectationsAgent(model).draft(job_title="x", jd="y", skills_required=[])

    assert len(items[0].text) == MAX_ITEM_TEXT


async def test_draft_drops_a_restatement_of_a_fixed_item() -> None:
    """Case-insensitive, because the same behaviour twice is two toggles."""
    fixed = fixed_items()[0].text
    model = ScriptedModel(
        {
            "items": [
                {"competency_id": "clarity", "text": fixed.upper()},
                {"competency_id": "clarity", "text": "Names the three wards by name."},
            ]
        }
    )
    items = await ExpectationsAgent(model).draft(job_title="x", jd="y", skills_required=[])

    assert [i.text for i in items] == ["Names the three wards by name."]


async def test_draft_drops_an_empty_item() -> None:
    model = ScriptedModel(
        {
            "items": [
                {"competency_id": "clarity", "text": "   "},
                {"competency_id": "clarity", "text": "Names the incentive slab."},
            ]
        }
    )
    items = await ExpectationsAgent(model).draft(job_title="x", jd="y", skills_required=[])

    assert [i.text for i in items] == ["Names the incentive slab."]


async def test_the_drafting_prompt_asks_for_interviewer_behaviour() -> None:
    """The one thing the wording must never get wrong: who is being assessed."""
    model = ScriptedModel({"items": []})
    await ExpectationsAgent(model).draft(
        job_title="Field Sales Executive", jd=JOB["jd"], skills_required=["Door-to-door selling"]
    )

    assert "INTERVIEWER" in model.system
    assert "never the candidate" in model.system
    # The four competencies reach the prompt as ids with their labels, so the
    # model is placing items rather than inventing headings.
    for criterion in DEFAULT_RUBRIC.criteria:
        assert f"{criterion.id} ({criterion.label})" in model.prompt


# ---------------------------------------------------------------------------
# ExpectationsAgent.classify
# ---------------------------------------------------------------------------


async def test_classify_keeps_an_answer_inside_the_four() -> None:
    model = ScriptedModel({"competency_id": "fairness", "reason": "It is about protected topics."})
    answer = await ExpectationsAgent(model).classify(text="Never asks about marriage plans.")

    assert answer.competency_id == "fairness"
    assert answer.reason == "It is about protected topics."


async def test_classify_outside_the_four_falls_back_with_a_blank_reason() -> None:
    """A blank reason is the signal that nothing was actually decided.

    Keeping the model's reason beside the default would present a rationale for
    a competency the model never chose, which is worse than saying nothing.
    """
    model = ScriptedModel({"competency_id": "commercial_judgement", "reason": "Feels commercial."})
    answer = await ExpectationsAgent(model).classify(text="Asks about margin.")

    assert answer.competency_id == DEFAULT_COMPETENCY_ID
    assert answer.reason == ""


# ---------------------------------------------------------------------------
# The routes
# ---------------------------------------------------------------------------


@pytest.fixture
def repo():
    return InterviewRepository(init_db(":memory:"))


@pytest.fixture
def client(repo):
    app = build_app(":memory:")
    app.dependency_overrides[api_module.get_repo] = lambda: repo
    with TestClient(app) as c:
        yield c


def test_draft_route_returns_the_clamped_items(client):
    client.app.dependency_overrides[api_module.get_expectations_agent] = lambda: ExpectationsAgent(
        ScriptedModel(
            {"items": [{"competency_id": "structure", "text": "Asks for one named deal."}]}
        )
    )
    res = client.post(
        "/api/v1/expectations/draft",
        json={"job_title": JOB["job_title"], "jd": JOB["jd"], "skills_required": ["Selling"]},
    )

    assert res.status_code == 200, res.text
    assert res.json() == [
        {
            "id": "drafted.structure.1",
            "competency_id": "structure",
            "text": "Asks for one named deal.",
            "source": "drafted",
            "enabled": True,
        }
    ]


def test_classify_route_returns_the_suggestion(client):
    client.app.dependency_overrides[api_module.get_expectations_agent] = lambda: ExpectationsAgent(
        ScriptedModel({"competency_id": "clarity", "reason": "Pay."})
    )
    res = client.post("/api/v1/expectations/classify", json={"text": "States the slab."})

    assert res.status_code == 200, res.text
    assert res.json() == {"competency_id": "clarity", "reason": "Pay."}


def test_the_retired_expectation_routes_are_gone(client):
    """The v1 document is retired, not merely unused."""
    created = client.post("/api/v1/interviews", json=JOB)
    interview_id = created.json()["id"]

    assert client.post(f"/api/v1/interviews/{interview_id}/expectation").status_code == 404
    assert client.get(f"/api/v1/interviews/{interview_id}/expectation").status_code == 404


# ---------------------------------------------------------------------------
# POST /interviews — what the checklist may and may not be
# ---------------------------------------------------------------------------


def test_creating_with_no_expectations_stores_the_whole_fixed_list(client):
    res = client.post("/api/v1/interviews", json=JOB)

    assert res.status_code == 201, res.text
    assert [i["id"] for i in res.json()["expectations"]] == FIXED_IDS
    assert all(i["enabled"] for i in res.json()["expectations"])


def test_the_stored_checklist_survives_a_read_back(client):
    created = client.post(
        "/api/v1/interviews",
        json={
            **JOB,
            "expectations": [
                fixed_items()[0].model_copy(update={"enabled": False}).model_dump(),
                {
                    "id": "anything",
                    "competency_id": "structure",
                    "text": "Asks for one named deal.",
                    "source": "custom",
                },
            ],
        },
    )
    assert created.status_code == 201, created.text

    fetched = client.get(f"/api/v1/interviews/{created.json()['id']}").json()
    by_id = {i["id"]: i for i in fetched["expectations"]}
    assert by_id[FIXED_IDS[0]]["enabled"] is False
    assert by_id["custom.1"]["text"] == "Asks for one named deal."
    assert len(fetched["expectations"]) == len(FIXED_IDS) + 1


def test_creating_rejects_an_unknown_competency(client):
    res = client.post(
        "/api/v1/interviews",
        json={
            **JOB,
            "expectations": [
                {
                    "id": "custom.1",
                    "competency_id": "negotiation",
                    "text": "Haggles well.",
                    "source": "custom",
                }
            ],
        },
    )

    assert res.status_code == 422
    assert "unknown competency" in res.text


def test_creating_rejects_an_edited_fixed_item(client):
    """A fixed item may be toggled off. Its wording is the rubric's."""
    edited = fixed_items()[0].model_copy(update={"text": "Explains the role, sort of."})
    res = client.post("/api/v1/interviews", json={**JOB, "expectations": [edited.model_dump()]})

    assert res.status_code == 422
    assert "but not reworded" in res.text


def test_creating_restores_a_fixed_item_the_caller_left_out(client):
    """Losing part of the instrument would stop this interview being comparable."""
    kept = [item.model_dump() for item in fixed_items()[1:]]
    res = client.post("/api/v1/interviews", json={**JOB, "expectations": kept})

    assert res.status_code == 201, res.text
    assert sorted(i["id"] for i in res.json()["expectations"]) == sorted(FIXED_IDS)


def test_creating_rejects_a_duplicated_fixed_item(client):
    first = fixed_items()[0].model_dump()
    res = client.post("/api/v1/interviews", json={**JOB, "expectations": [first, first]})

    assert res.status_code == 422
    assert "duplicate expectation ids" in res.text


def test_creating_rejects_one_custom_item_too_many(client):
    over = [
        {
            "id": f"whatever-{n}",
            "competency_id": "structure",
            "text": f"Custom behaviour {n}.",
            "source": "custom",
        }
        for n in range(MAX_CUSTOM_ITEMS + 1)
    ]
    res = client.post("/api/v1/interviews", json={**JOB, "expectations": over})

    assert res.status_code == 422
    assert f"at most {MAX_CUSTOM_ITEMS} custom expectations" in res.text

    at_limit = client.post("/api/v1/interviews", json={**JOB, "expectations": over[:-1]})
    assert at_limit.status_code == 201, at_limit.text


def test_custom_ids_are_assigned_server_side_in_request_order(client):
    sent = [
        {
            "id": "client-made-this-up",
            "competency_id": "structure",
            "text": "A.",
            "source": "custom",
        },
        {"id": "client-made-this-up", "competency_id": "clarity", "text": "B.", "source": "custom"},
    ]
    res = client.post("/api/v1/interviews", json={**JOB, "expectations": sent})

    assert res.status_code == 201, res.text
    custom = [i for i in res.json()["expectations"] if i["source"] == "custom"]
    assert [(i["id"], i["text"]) for i in custom] == [("custom.1", "A."), ("custom.2", "B.")]


def test_a_fixed_id_cannot_be_claimed_by_a_custom_item(client):
    res = client.post(
        "/api/v1/interviews",
        json={
            **JOB,
            "expectations": [
                {
                    "id": FIXED_IDS[0],
                    "competency_id": "clarity",
                    "text": "Something else entirely.",
                    "source": "custom",
                }
            ],
        },
    )

    assert res.status_code == 422
    assert "but not reworded" in res.text


def test_an_invented_fixed_id_is_rejected(client):
    res = client.post(
        "/api/v1/interviews",
        json={
            **JOB,
            "expectations": [
                {
                    "id": "clarity.something-the-rubric-never-said",
                    "competency_id": "clarity",
                    "text": "Something the rubric never said.",
                    "source": "fixed",
                }
            ],
        },
    )

    assert res.status_code == 422
    assert "is not a fixed expectation id" in res.text


# ---------------------------------------------------------------------------
# report_sections — re-keyed to what the renderer can honour (plan D5)
# ---------------------------------------------------------------------------


def test_report_sections_default_to_the_re_keyed_set(client):
    res = client.post("/api/v1/interviews", json=JOB)

    assert res.json()["report_sections"] == {
        "scorecard": True,
        "qna": True,
        "bei": True,
        "strengths_gaps": True,
        "areas": True,
        "percentage_score": True,
        "transcript": False,
        "summary": False,
    }


def test_an_unknown_report_section_is_422(client):
    res = client.post("/api/v1/interviews", json={**JOB, "report_sections": {"key_moments": True}})

    assert res.status_code == 422
    assert "unknown report sections: key_moments" in res.text


def test_a_partial_report_section_map_is_merged_onto_the_defaults(client):
    res = client.post("/api/v1/interviews", json={**JOB, "report_sections": {"transcript": True}})

    assert res.status_code == 201, res.text
    assert res.json()["report_sections"] == {**REPORT_SECTIONS, "transcript": True}


def test_every_section_key_is_reachable_from_the_request_model() -> None:
    """No key on the map that the request model cannot carry, and none missing."""
    request = InterviewCreateRequest(**JOB, report_sections=dict.fromkeys(REPORT_SECTIONS, True))

    assert set(request.report_sections) == set(REPORT_SECTIONS)


# ---------------------------------------------------------------------------
# Provider failures
# ---------------------------------------------------------------------------


def test_a_provider_failure_on_draft_is_a_502(client):
    client.app.dependency_overrides[api_module.get_expectations_agent] = lambda: ExpectationsAgent(
        FailingModel("fake-1", 0.1)
    )
    res = client.post(
        "/api/v1/expectations/draft", json={"job_title": "x", "jd": "y", "skills_required": []}
    )

    assert res.status_code == 502
    assert "RESOURCE_EXHAUSTED" in res.json()["detail"]


# ---------------------------------------------------------------------------
# PATCH /interviews/{id} — the wizard's step 2 editing what step 1 created
#
# The route exists because the portal wizard saves the interview on step 1 and
# only then draws the expectations. Everything below is about one property:
# the update validators are the *create* validators, so the two ways into the
# checklist cannot drift — and the consequences of that (a partial list is
# destructive) are pinned rather than left to be discovered.
# ---------------------------------------------------------------------------


DRAFTED_ITEM = {
    "id": "drafted.structure.1",
    "competency_id": "structure",
    "text": "Asks how they handled a missed quota.",
    "source": "drafted",
    "enabled": True,
}


def _updated_at(repo, interview_id: str) -> str:
    """The stored `updated_at`, which `InterviewResponse` deliberately omits."""
    row = repo.conn.execute(
        "SELECT updated_at FROM interviews WHERE id = ?", (interview_id,)
    ).fetchone()
    return str(row["updated_at"])


def test_patch_stores_a_whole_edited_checklist(client):
    """The wizard's actual payload: fixed items, one off, plus drafted and custom."""
    created = client.post("/api/v1/interviews", json=JOB)
    interview_id = created.json()["id"]

    sent = [item.model_dump() for item in fixed_items()]
    sent[0]["enabled"] = False
    sent.append(DRAFTED_ITEM)
    sent.append(
        {
            "id": "client-made-this-up",
            "competency_id": "clarity",
            "text": "Names the incentive slab.",
            "source": "custom",
        }
    )

    res = client.patch(
        f"/api/v1/interviews/{interview_id}",
        json={"expectations": sent, "report_sections": {**REPORT_SECTIONS, "transcript": True}},
    )

    assert res.status_code == 200, res.text
    by_id = {i["id"]: i for i in res.json()["expectations"]}
    assert by_id[FIXED_IDS[0]]["enabled"] is False
    assert by_id["drafted.structure.1"]["text"] == "Asks how they handled a missed quota."
    assert by_id["custom.1"]["text"] == "Names the incentive slab."
    assert len(res.json()["expectations"]) == len(FIXED_IDS) + 2
    assert res.json()["report_sections"] == {**REPORT_SECTIONS, "transcript": True}

    fetched = client.get(f"/api/v1/interviews/{interview_id}").json()
    assert fetched["expectations"] == res.json()["expectations"]
    assert fetched["report_sections"] == res.json()["report_sections"]


def test_patch_rejects_an_edited_fixed_item(client):
    """The update validator is the create validator; the wording stays the rubric's."""
    created = client.post("/api/v1/interviews", json=JOB)
    edited = fixed_items()[0].model_copy(update={"text": "Explains the role, sort of."})

    res = client.patch(
        f"/api/v1/interviews/{created.json()['id']}",
        json={"expectations": [edited.model_dump()]},
    )

    assert res.status_code == 422
    assert "but not reworded" in res.text


def test_patch_rejects_one_custom_item_too_many(client):
    created = client.post("/api/v1/interviews", json=JOB)
    over = [
        {
            "id": f"whatever-{n}",
            "competency_id": "structure",
            "text": f"Custom behaviour {n}.",
            "source": "custom",
        }
        for n in range(MAX_CUSTOM_ITEMS + 1)
    ]

    res = client.patch(f"/api/v1/interviews/{created.json()['id']}", json={"expectations": over})

    assert res.status_code == 422
    assert f"at most {MAX_CUSTOM_ITEMS} custom expectations" in res.text


def test_patch_rejects_an_unknown_report_section(client):
    created = client.post("/api/v1/interviews", json=JOB)

    res = client.patch(
        f"/api/v1/interviews/{created.json()['id']}",
        json={"report_sections": {"key_moments": True}},
    )

    assert res.status_code == 422
    assert "unknown report sections: key_moments" in res.text


def test_patch_with_an_empty_body_is_422(client):
    """An update that edits nothing would still move `updated_at`; it is a mistake."""
    created = client.post("/api/v1/interviews", json=JOB)

    res = client.patch(f"/api/v1/interviews/{created.json()['id']}", json={})

    assert res.status_code == 422
    assert "send expectations, report_sections, or both" in res.text


def test_patch_with_an_explicit_null_is_422_not_500(client):
    """`null` means "not editing this field", so a body of nulls edits nothing.

    Pinned because the failure mode is a 500, not a 422: pydantic maps only
    ValueError and AssertionError to a 422, and a validator that iterated the
    `None` would raise TypeError straight past the envelope. Sabotage
    `validate_expectations`'s None guard and this test fails with a 500.
    """
    created = client.post("/api/v1/interviews", json=JOB)
    interview_id = created.json()["id"]

    res = client.patch(f"/api/v1/interviews/{interview_id}", json={"expectations": None})

    assert res.status_code == 422, res.text
    assert "send expectations, report_sections, or both" in res.text

    both = client.patch(
        f"/api/v1/interviews/{interview_id}",
        json={"expectations": None, "report_sections": None},
    )
    assert both.status_code == 422, both.text


def test_patch_ignores_an_explicit_null_beside_a_real_edit(client):
    """A null field is absent, not empty — the other field is still applied."""
    created = client.post("/api/v1/interviews", json={**JOB, "expectations": [DRAFTED_ITEM]})
    interview_id = created.json()["id"]

    res = client.patch(
        f"/api/v1/interviews/{interview_id}",
        json={"expectations": None, "report_sections": {"summary": True}},
    )

    assert res.status_code == 200, res.text
    assert res.json()["report_sections"] == {**REPORT_SECTIONS, "summary": True}
    assert "drafted.structure.1" in {i["id"] for i in res.json()["expectations"]}


def test_patch_of_an_unknown_interview_is_404(client):
    res = client.patch(
        "/api/v1/interviews/no-such-interview",
        json={"report_sections": {"transcript": True}},
    )

    assert res.status_code == 404
    assert res.json()["status"] is False
    assert res.json()["message"] == "interview not found"


def test_patching_report_sections_alone_leaves_the_checklist_untouched(client):
    created = client.post("/api/v1/interviews", json={**JOB, "expectations": [DRAFTED_ITEM]})
    interview_id = created.json()["id"]
    before = created.json()["expectations"]

    res = client.patch(
        f"/api/v1/interviews/{interview_id}", json={"report_sections": {"transcript": True}}
    )

    assert res.status_code == 200, res.text
    assert res.json()["expectations"] == before
    assert res.json()["report_sections"] == {**REPORT_SECTIONS, "transcript": True}


def test_patching_expectations_alone_leaves_the_report_sections_untouched(client):
    created = client.post(
        "/api/v1/interviews", json={**JOB, "report_sections": {"transcript": True}}
    )
    interview_id = created.json()["id"]

    sent = [item.model_dump() for item in fixed_items()]
    sent[0]["enabled"] = False
    res = client.patch(f"/api/v1/interviews/{interview_id}", json={"expectations": sent})

    assert res.status_code == 200, res.text
    assert res.json()["report_sections"] == {**REPORT_SECTIONS, "transcript": True}
    by_id = {i["id"]: i for i in res.json()["expectations"]}
    assert by_id[FIXED_IDS[0]]["enabled"] is False


def test_a_partial_patch_list_re_enables_fixed_items_and_drops_drafted_ones(client):
    """Pinned on purpose: this is why the client sends the whole list.

    There is no merge with what is stored. A list that omits a fixed item gets
    it back *enabled* — the create validator restores it, and it cannot know the
    manager had switched it off — and a list that omits a drafted or custom item
    loses it outright.
    """
    off = fixed_items()[0].model_copy(update={"enabled": False}).model_dump()
    created = client.post("/api/v1/interviews", json={**JOB, "expectations": [off, DRAFTED_ITEM]})
    interview_id = created.json()["id"]
    assert "drafted.structure.1" in {i["id"] for i in created.json()["expectations"]}

    res = client.patch(
        f"/api/v1/interviews/{interview_id}",
        json={
            "expectations": [
                {
                    "id": "whatever",
                    "competency_id": "structure",
                    "text": "Asks for one named deal.",
                    "source": "custom",
                }
            ]
        },
    )

    assert res.status_code == 200, res.text
    items = res.json()["expectations"]
    assert "drafted.structure.1" not in {i["id"] for i in items}
    assert sorted(i["id"] for i in items) == sorted([*FIXED_IDS, "custom.1"])
    assert all(i["enabled"] for i in items)


def test_patch_moves_updated_at(client, repo):
    """The column exists for auditing; an update that did not move it is a lie."""
    created = client.post("/api/v1/interviews", json=JOB)
    interview_id = created.json()["id"]
    before = _updated_at(repo, interview_id)

    res = client.patch(
        f"/api/v1/interviews/{interview_id}", json={"report_sections": {"summary": True}}
    )

    assert res.status_code == 200, res.text
    assert _updated_at(repo, interview_id) > before
