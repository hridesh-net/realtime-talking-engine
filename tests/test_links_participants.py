"""Invite links and the participants who redeem them.

Offline — an in-memory database, a fake casting model, no network.

Every assertion here was confirmed to fail against a deliberately broken
implementation first. The sabotages used, so the next reader can repeat them:
dropping the `expires_at` check in `_interview_id_from_token` (the 410s pass
instead), replacing `secrets.compare_digest` with `==` (the constant-time test
fails), storing the email as sent instead of normalised (the one-row test
splits into two), and `COALESCE(excluded.user_id, participants.user_id)` →
`excluded.user_id` (the attach test finds the id cleared again).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from candidate_agent.agent import VirtualCandidateAgent
from control_plane import api as api_module
from control_plane.database import init_db
from control_plane.main import build_app
from control_plane.repository import InterviewRepository
from tests.test_control_plane_candidates_api import JOB, FakeModel

SECRET = "shared-secret-for-tests"
AUTH = {"Authorization": f"Bearer {SECRET}"}


@pytest.fixture
def repo():
    return InterviewRepository(init_db(":memory:"))


@pytest.fixture
def client(repo, monkeypatch):
    monkeypatch.setenv("CONTROL_PLANE_SHARED_SECRET", SECRET)
    app = build_app(":memory:")
    app.dependency_overrides[api_module.get_repo] = lambda: repo
    app.dependency_overrides[api_module.get_candidate_agent] = lambda: VirtualCandidateAgent(
        model=FakeModel("fake-1", 0.35)
    )
    with TestClient(app) as c:
        yield c


def _interview(client, **over) -> str:
    res = client.post("/api/v1/interviews", json={**JOB, **over})
    assert res.status_code == 201, res.text
    return res.json()["id"]


def _mint(client, interview_id: str, *, minutes: int = 60) -> str:
    res = client.post(
        f"/api/v1/interviews/{interview_id}/links",
        json={"expires_at": (datetime.now(UTC) + timedelta(minutes=minutes)).isoformat()},
        headers=AUTH,
    )
    assert res.status_code == 201, res.text
    return res.json()["token"]


def _start(client, token: str, name: str, email: str, **over) -> dict:
    res = client.post(
        "/api/v1/sessions",
        json={
            "archetype": "nervous_fresher",
            "invite_token": token,
            "participant": {"name": name, "email": email},
            **over,
        },
    )
    assert res.status_code == 201, res.text
    return res.json()


# ---------------------------------------------------------------------------
# Minting, reading and revoking
# ---------------------------------------------------------------------------


def test_a_link_round_trips_from_mint_to_landing_form(client):
    interview_id = _interview(client, job_title="Field Sales Executive")
    minted = client.post(
        f"/api/v1/interviews/{interview_id}/links",
        json={"expires_at": (datetime.now(UTC) + timedelta(days=7)).isoformat()},
        headers=AUTH,
    )

    assert minted.status_code == 201, minted.text
    body = minted.json()
    assert body["interview_id"] == interview_id
    assert body["revoked_at"] is None
    # 32 bytes, URL-safe. Short enough to paste, long enough to be worth nothing
    # to a guesser.
    assert len(body["token"]) >= 40

    public = client.get(f"/api/v1/links/{body['token']}")
    assert public.status_code == 200, public.text
    assert public.json() == {
        "job_title": "Field Sales Executive",
        "duration_minutes": 60,
        "language": "english_indian",
        "expires_at": body["expires_at"],
    }


def test_the_public_link_never_echoes_the_jd_or_the_persona(client):
    """This route answers to whoever holds the token; its body is public."""
    interview_id = _interview(client, jd="SECRET-COMPENSATION-DETAIL and the territory plan")
    client.post(f"/api/v1/interviews/{interview_id}/candidates", headers=AUTH)
    token = _mint(client, interview_id)

    body = client.get(f"/api/v1/links/{token}").text

    assert "SECRET-COMPENSATION-DETAIL" not in body
    assert "Test Person" not in body  # the persona the fake model casts
    assert set(client.get(f"/api/v1/links/{token}").json()) == {
        "job_title",
        "duration_minutes",
        "language",
        "expires_at",
    }


def test_an_unknown_token_is_404_and_an_expired_one_is_410(client):
    interview_id = _interview(client)
    expired = client.post(
        f"/api/v1/interviews/{interview_id}/links",
        json={"expires_at": (datetime.now(UTC) - timedelta(seconds=1)).isoformat()},
        headers=AUTH,
    ).json()["token"]

    assert client.get("/api/v1/links/not-a-real-token").status_code == 404
    gone = client.get(f"/api/v1/links/{expired}")
    assert gone.status_code == 410
    assert "expired" in gone.json()["detail"]


def test_a_revoked_link_is_410_on_the_public_route(client):
    interview_id = _interview(client)
    token = _mint(client, interview_id)

    assert client.delete(f"/api/v1/links/{token}", headers=AUTH).status_code == 204

    gone = client.get(f"/api/v1/links/{token}")
    assert gone.status_code == 410
    assert "revoked" in gone.json()["detail"]


def test_revoking_twice_is_404_the_second_time(client):
    """The first revocation is the instant it stopped working; nothing moves it."""
    token = _mint(client, _interview(client))

    assert client.delete(f"/api/v1/links/{token}", headers=AUTH).status_code == 204
    assert client.delete(f"/api/v1/links/{token}", headers=AUTH).status_code == 404


def test_the_token_is_compared_in_constant_time(client, monkeypatch):
    """The decision to admit must not branch on how much of the token matched.

    Asserted by observing the call rather than by timing: a timing assertion in
    a test suite is a flake generator. What this pins is that
    `secrets.compare_digest` is what decides, so an edit to `==` fails here.
    """
    token = _mint(client, _interview(client))
    seen: list[tuple[str, str]] = []
    real = api_module.secrets.compare_digest

    def recording(a, b):
        seen.append((a, b))
        return real(a, b)

    monkeypatch.setattr(api_module.secrets, "compare_digest", recording)
    assert client.get(f"/api/v1/links/{token}").status_code == 200

    assert (token, token) in seen


def test_minting_a_link_for_an_unknown_interview_is_404(client):
    res = client.post(
        "/api/v1/interviews/no-such-interview/links",
        json={"expires_at": (datetime.now(UTC) + timedelta(days=1)).isoformat()},
        headers=AUTH,
    )

    assert res.status_code == 404


def test_the_link_minter_is_not_an_open_endpoint(client):
    """A route that hands out a credential must not be the first one with none."""
    interview_id = _interview(client)
    body = {"expires_at": (datetime.now(UTC) + timedelta(days=1)).isoformat()}

    assert client.post(f"/api/v1/interviews/{interview_id}/links", json=body).status_code == 401
    token = _mint(client, interview_id)
    assert client.delete(f"/api/v1/links/{token}").status_code == 401
    # The public read stays public.
    assert client.get(f"/api/v1/links/{token}").status_code == 200


# ---------------------------------------------------------------------------
# Opening a session through a link
# ---------------------------------------------------------------------------


def test_a_session_opened_on_a_link_records_the_participant(client):
    interview_id = _interview(client)
    token = _mint(client, interview_id)

    session = _start(client, token, "Asha Rao", "asha@example.com")

    assert session["interview_id"] == interview_id
    assert session["participant"]["name"] == "Asha Rao"
    assert session["participant"]["email"] == "asha@example.com"
    # And it is on the read-back and on the interview's session list.
    fetched = client.get(f"/api/v1/sessions/{session['id']}").json()
    assert fetched["participant"]["id"] == session["participant"]["id"]
    listed = client.get(f"/api/v1/interviews/{interview_id}/sessions").json()
    assert listed[0]["participant"]["name"] == "Asha Rao"


def test_an_expired_link_cannot_open_a_session(client):
    """Expiry is enforced at the moment a session is created, not by a sweeper."""
    interview_id = _interview(client)
    token = client.post(
        f"/api/v1/interviews/{interview_id}/links",
        json={"expires_at": (datetime.now(UTC) - timedelta(seconds=1)).isoformat()},
        headers=AUTH,
    ).json()["token"]

    res = client.post(
        "/api/v1/sessions",
        json={
            "archetype": "nervous_fresher",
            "invite_token": token,
            "participant": {"name": "Asha Rao", "email": "asha@example.com"},
        },
    )

    assert res.status_code == 410
    assert "expired" in res.json()["detail"]


def test_a_revoked_link_cannot_open_a_session(client):
    token = _mint(client, _interview(client))
    client.delete(f"/api/v1/links/{token}", headers=AUTH)

    res = client.post(
        "/api/v1/sessions",
        json={
            "archetype": "nervous_fresher",
            "invite_token": token,
            "participant": {"name": "Asha Rao", "email": "asha@example.com"},
        },
    )

    assert res.status_code == 410
    assert "revoked" in res.json()["detail"]


def test_a_token_without_a_participant_is_rejected(client):
    token = _mint(client, _interview(client))

    res = client.post(
        "/api/v1/sessions", json={"archetype": "nervous_fresher", "invite_token": token}
    )

    assert res.status_code == 422
    assert "participant" in res.text


def test_a_session_with_neither_token_nor_interview_is_rejected(client):
    res = client.post("/api/v1/sessions", json={"archetype": "nervous_fresher"})

    assert res.status_code == 422
    assert "interview_id is required" in res.text


def test_an_interview_id_that_disagrees_with_the_link_is_rejected(client):
    token = _mint(client, _interview(client))
    other = _interview(client, job_title="Something else")

    res = client.post(
        "/api/v1/sessions",
        json={
            "archetype": "nervous_fresher",
            "invite_token": token,
            "interview_id": other,
            "participant": {"name": "Asha Rao", "email": "asha@example.com"},
        },
    )

    assert res.status_code == 422
    assert "does not match the link" in res.text


def test_a_matching_interview_id_alongside_the_token_is_accepted(client):
    interview_id = _interview(client)
    token = _mint(client, interview_id)

    session = _start(client, token, "Asha Rao", "asha@example.com", interview_id=interview_id)

    assert session["interview_id"] == interview_id


def test_the_console_path_still_opens_a_session_without_a_participant(client):
    """No link, no participant — the console's own "Create & chat" button."""
    interview_id = _interview(client)

    res = client.post(
        "/api/v1/sessions", json={"interview_id": interview_id, "archetype": "nervous_fresher"}
    )

    assert res.status_code == 201, res.text
    assert res.json()["participant"] is None


# ---------------------------------------------------------------------------
# Participants — the same email is the same person
# ---------------------------------------------------------------------------


def test_the_same_email_in_a_different_case_is_the_same_person(client):
    """One row, and the name follows the most recent form."""
    token = _mint(client, _interview(client))

    first = _start(client, token, "Asha Rao", "  Asha@Example.COM ")
    second = _start(client, token, "Asha R.", "asha@example.com")

    assert first["participant"]["id"] == second["participant"]["id"]
    assert first["participant"]["email"] == "asha@example.com"
    assert second["participant"]["name"] == "Asha R."
    assert (
        client.get(f"/api/v1/participants/{first['participant']['id']}", headers=AUTH).json()[
            "name"
        ]
        == "Asha R."
    )


def test_last_seen_at_moves_and_created_at_does_not(client):
    token = _mint(client, _interview(client))

    first = _start(client, token, "Asha Rao", "asha@example.com")
    second = _start(client, token, "Asha Rao", "asha@example.com")

    assert second["participant"]["created_at"] == first["participant"]["created_at"]
    assert second["participant"]["last_seen_at"] >= first["participant"]["last_seen_at"]


def test_a_user_id_supplied_later_attaches_and_is_never_cleared(client):
    """Arriving on a plain link once does not undo being a SkillBrew user."""
    token = _mint(client, _interview(client))

    anonymous = _start(client, token, "Asha Rao", "asha@example.com")
    assert anonymous["participant"]["user_id"] == ""

    attached = _start(client, token, "Asha Rao", "asha@example.com", user_id="sb-user-42")
    assert attached["participant"]["id"] == anonymous["participant"]["id"]
    assert attached["participant"]["user_id"] == "sb-user-42"

    again = _start(client, token, "Asha Rao", "asha@example.com")
    assert again["participant"]["user_id"] == "sb-user-42"


@pytest.mark.parametrize("email", ["not-an-email", "no@domain", "two@@ats.com", "with space@x.io"])
def test_a_malformed_email_is_rejected(client, email):
    token = _mint(client, _interview(client))

    res = client.post(
        "/api/v1/sessions",
        json={
            "archetype": "nervous_fresher",
            "invite_token": token,
            "participant": {"name": "Asha Rao", "email": email},
        },
    )

    assert res.status_code == 422


def test_a_blank_name_is_rejected(client):
    token = _mint(client, _interview(client))

    res = client.post(
        "/api/v1/sessions",
        json={
            "archetype": "nervous_fresher",
            "invite_token": token,
            "participant": {"name": "   ", "email": "asha@example.com"},
        },
    )

    assert res.status_code == 422


# ---------------------------------------------------------------------------
# Cross-interview history
# ---------------------------------------------------------------------------


def test_the_history_route_lists_sessions_across_two_interviews(client, repo):
    """The point of keying a participant on email: one taker, one history."""
    first_interview = _interview(client, job_title="Field Sales Executive")
    second_interview = _interview(client, job_title="Retail Store Manager")
    first = _start(client, _mint(client, first_interview), "Asha Rao", "asha@example.com")
    second = _start(client, _mint(client, second_interview), "Asha Rao", "ASHA@example.com")
    participant_id = first["participant"]["id"]
    assert participant_id == second["participant"]["id"]

    # One session has a report; the other does not.
    repo.save_report(
        first["id"],
        {
            "session_id": first["id"],
            "readiness_index": 62,
            "band": "Developing",
            "criteria": [
                {"id": "clarity", "score": 2.5},
                {"id": "structure", "score": 3.0},
                {"id": "fairness", "score": 4.0},
                {"id": "communication", "score": 1.5},
            ],
            "provenance": {"scoring_version": "v1", "rubric_version": "v1.0"},
        },
    )

    rows = client.get(f"/api/v1/participants/{participant_id}/sessions", headers=AUTH)
    assert rows.status_code == 200, rows.text
    by_session = {r["session_id"]: r for r in rows.json()}
    assert set(by_session) == {first["id"], second["id"]}

    reported = by_session[first["id"]]
    assert reported["job_title"] == "Field Sales Executive"
    assert reported["interview_id"] == first_interview
    assert reported["readiness_index"] == 62
    assert reported["competency_scores"] == {
        "clarity": 2.5,
        "structure": 3.0,
        "fairness": 4.0,
        "communication": 1.5,
    }

    unreported = by_session[second["id"]]
    assert unreported["job_title"] == "Retail Store Manager"
    assert unreported["readiness_index"] is None
    assert unreported["competency_scores"] is None


def test_the_history_route_omits_another_persons_sessions(client):
    interview_id = _interview(client)
    token = _mint(client, interview_id)
    asha = _start(client, token, "Asha Rao", "asha@example.com")
    _start(client, token, "Bhavna Iyer", "bhavna@example.com")

    rows = client.get(
        f"/api/v1/participants/{asha['participant']['id']}/sessions", headers=AUTH
    ).json()

    assert [r["session_id"] for r in rows] == [asha["id"]]


def test_an_unknown_participant_is_404_on_both_history_routes(client):
    assert client.get("/api/v1/participants/nobody", headers=AUTH).status_code == 404
    assert client.get("/api/v1/participants/nobody/sessions", headers=AUTH).status_code == 404


def test_the_history_routes_are_behind_the_shared_secret(client):
    """They expose one named person's record, so they are not open."""
    token = _mint(client, _interview(client))
    participant_id = _start(client, token, "Asha Rao", "asha@example.com")["participant"]["id"]

    assert client.get(f"/api/v1/participants/{participant_id}").status_code == 401
    assert client.get(f"/api/v1/participants/{participant_id}/sessions").status_code == 401


def test_an_unconfigured_secret_refuses_rather_than_admits(client, monkeypatch):
    """A deployment that forgot the secret gets a 503, not an open endpoint."""
    monkeypatch.delenv("CONTROL_PLANE_SHARED_SECRET", raising=False)
    interview_id = _interview(client)

    res = client.post(
        f"/api/v1/interviews/{interview_id}/links",
        json={"expires_at": (datetime.now(UTC) + timedelta(days=1)).isoformat()},
        headers=AUTH,
    )

    assert res.status_code == 503


# ---------------------------------------------------------------------------
# The report masthead
# ---------------------------------------------------------------------------


def test_the_bundle_names_the_participant_rather_than_the_job(client, repo):
    """`manager_id`/`manager_name` were a blank and the job title standing in."""
    from control_plane import reporting

    interview_id = _interview(client)
    session = _start(client, _mint(client, interview_id), "Asha Rao", "asha@example.com")

    bundle = reporting.build_bundle(
        repo.get(interview_id), repo.get_session(session["id"]), None, None
    )

    assert bundle.session.manager_id == session["participant"]["id"]
    assert bundle.session.manager_name == "Asha Rao"


def test_a_session_without_a_participant_still_builds_a_bundle(client, repo):
    """Sessions that predate participants must still produce a readable report."""
    from control_plane import reporting

    interview_id = _interview(client, job_title="Field Sales Executive")
    created = client.post(
        "/api/v1/sessions", json={"interview_id": interview_id, "archetype": "nervous_fresher"}
    ).json()

    bundle = reporting.build_bundle(
        repo.get(interview_id), repo.get_session(created["id"]), None, None
    )

    assert bundle.session.manager_id == ""
    assert bundle.session.manager_name == "Field Sales Executive"
