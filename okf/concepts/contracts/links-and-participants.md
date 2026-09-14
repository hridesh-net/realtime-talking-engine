---
type: Contract
title: Links and participants
description: The expiring token an interview is taken through, and the email-keyed participant every session records.
resource: /control_plane/schemas.py
tags: [contract, links, participants, identity, expiry, privacy]
generated:
  by: claude-opus-5
  at: "2026-09-13T00:00:00Z"
verified:
  - by: claude-opus-5
    at: "2026-09-13T00:00:00Z"
status: stable
sources:
  - resource: /control_plane/schemas.py
  - resource: /control_plane/ports.py
  - resource: /control_plane/repository.py
  - resource: /control_plane/api.py
  - resource: /tests/test_links_participants.py
---
# Links and participants

> **The decision on record changed.** Until 2026-09-13 this service deliberately
> built no invite mechanism at all: SkillBrew owned identity, and a taker was a
> user id this repo never looked at. That was amended the same day. The split is
> now: **SkillBrew accounts create interviews; anyone with a link takes them; a
> SkillBrew user can take one too.**
>
> Two things forced the amendment, and neither is about ownership. **Expiry has
> to be enforced by whatever creates the session** — a check anywhere else is
> advisory. And **cross-interview history has to be joined where the sessions
> are** — a taker's five sessions against five personas only read as one history
> if something here knows they are one person.
>
> What did **not** change: no emails are sent from this service, there is no
> password, no login, no role and no user table. See
> [Project overview](/concepts/project-overview.md).

## Schema

```python
class InterviewLinkCreateRequest(BaseModel):
    expires_at: datetime

class InterviewLinkResponse(BaseModel):
    token: str                       # 32 bytes, secrets.token_urlsafe
    interview_id: str
    expires_at: datetime
    revoked_at: datetime | None = None
    created_at: datetime

class PublicLinkResponse(BaseModel):      # GET /links/{token} — the only public route
    job_title: str
    duration_minutes: int
    language: str
    expires_at: datetime

class ParticipantInput(BaseModel):        # what the landing form sends
    name: str                             # trimmed, must not be blank
    email: str                            # trimmed, lower-cased, shape-validated

class ParticipantResponse(BaseModel):
    id: str
    name: str
    email: str
    user_id: str = ""                     # "" when no SkillBrew id was ever supplied
    created_at: datetime
    last_seen_at: datetime

class ParticipantSessionRow(BaseModel):   # GET /participants/{id}/sessions
    session_id: str
    interview_id: str
    job_title: str
    archetype: str
    modality: str
    status: str
    started_at: datetime
    ended_at: datetime | None = None
    readiness_index: int | None = None
    competency_scores: dict[str, float | None] | None = None   # None == no report
```

`SessionCreateRequest` gains `invite_token`, `participant` and `user_id`, and
`interview_id` becomes optional. A model validator states the rule once: a token
**requires** a participant; without a token an `interview_id` is required.

## The token path, in order

`POST /sessions` with an `invite_token` does exactly this, and the order matters:

1. **Resolve the link.** Unknown token → **404**. Revoked → **410**. Past
   `expires_at` → **410**. An `interview_id` that disagrees with the link's →
   **422**; one that agrees is accepted.
2. **Upsert the participant**, before the persona is cast. A taker whose
   provider call then fails is still a known person the next time they try.
3. Everything after that is the same code the console path runs: look the
   persona up, cast it on the spot if it is not enrolled, write the session row
   with `participant_id` on it.

**Expiry is checked here and nowhere else.** There is no sweeper and no
background job; a link is a row with an `expires_at`, and the only moment that
matters is the one where someone tries to start an interview with it. That is
also why `LinkStore.get_link` returns the row whatever state it is in — see
[Storage ports](/concepts/contracts/storage-ports.md).

## The one public route

`GET /links/{token}` answers to whoever holds the token, so **everything on it
is public by construction**: four fields, exactly what a landing form needs to
render. The job description, the personas, the expectation checklist and the
report shape are all deliberately absent, and a test asserts the body carries
neither the JD nor a persona name.

404 for an unknown token, **410** for one that has expired or been revoked — the
holder of a link that ran out is told it ran out, rather than that it never
existed. The final accept is `secrets.compare_digest`, so the decision to admit
never branches on how much of the token matched; the lookup itself is an index
probe on 32 bytes of randomness, which is where the actual security is.

Everything else is behind `require_shared_secret`: minting, revoking, and both
participant routes. Nothing on the interview routes is authenticated today, and
**a link minter must not be the first open one** — so the gate that already
admitted the Go engine was renamed and reused rather than a second one invented.
The participant routes are behind it for a different reason: they expose one
named person's record.

## The same email is the same person

`participants.email` is UNIQUE and normalised before it reaches storage, so
`" Asha@Example.COM "` and `asha@example.com` are one row. Two rules live in the
upsert and each has a reason that is easy to get backwards:

* **The name follows the latest form.** There is nothing to arbitrate between
  two spellings, and the most recent one is what the person just typed.
* **`user_id` attaches and is never cleared.** `COALESCE(excluded.user_id,
  participants.user_id)`: taking one interview on a plain link does not undo
  being a SkillBrew user.

`EMAIL_PATTERN` is a shape check — one `@`, a dot in the domain, no whitespace —
and deliberately **not** `EmailStr`: this is an identity join key, not an address
anything delivers to, and pulling in a deliverability validator would imply a
guarantee this service does not make.

## Cross-interview history

`GET /participants/{id}/sessions` is the data the insight view reads: every
session across every interview, newest first, with the stored report's four
competency scores and readiness index when a report exists and nulls when it
does not. The numbers are **read from the stored report**, never recomputed — a
report is a fixed artifact with its provenance stamped on it, and a history view
that re-derived the numbers could disagree with the document a trainer is
holding.

404, not an empty list, for an unknown id. Unlike `GET /interviews/{id}/sessions`,
"nothing here" and "no such person" are different answers when the id identifies
an individual.

The insight *report* itself — trends across personas for one taker — is a
follow-on work package. The data model and this route landed first.

## Data hygiene

Name and email are personal data of a named employee, stored beside their
recording. Retention follows the recording's decision: **indefinite, deleted by
hand** ([Session recording](/concepts/contracts/session-recording.md)). Deleting
a person means deleting their sessions, their recordings and the participant row
by hand, in that order — `sessions.participant_id` is a real foreign key, so the
database will stop a delete that would orphan a session rather than let it
through. Neither field is ever copied into this bundle, a log or a fixture.

## Related

[REST API](/concepts/contracts/rest-api.md) ·
[Database schema](/concepts/contracts/database-schema.md) ·
[Storage ports](/concepts/contracts/storage-ports.md) ·
[Interview record](/concepts/contracts/interview-record.md) ·
`owner_handover/interview_link_schema.json`, `public_link_schema.json`,
`participant_session_schema.json`
