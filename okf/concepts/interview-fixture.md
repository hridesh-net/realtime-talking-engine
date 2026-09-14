---
type: Concept
title: The interview as a fixture — the 2026-09-13 direction
description: What the product is now — one interview created once by a SkillBrew user, carrying its competency checklist, report shape and link, taken by many people whose history joins on email — and which half of it is built.
resource: /docs/INTERVIEW_EXPECTATIONS_PLAN.md
tags: [direction, product, expectations, links, participants, cohort]
generated:
  by: claude-fable-5-1
  at: "2026-09-14T00:00:00Z"
verified:
  - by: claude-opus-5
    at: "2026-09-14T00:00:00Z"
  - by: claude-fable-5-1
    at: "2026-09-13T00:00:00Z"
status: stable
sources:
  - resource: /docs/INTERVIEW_EXPECTATIONS_PLAN.md
  - resource: /evaluation_agent/expectations.py
  - resource: /control_plane/schemas.py
  - resource: /control_plane/api.py
---
# The interview as a fixture

Decided with the product owner on 2026-09-13 and written up as
`docs/INTERVIEW_EXPECTATIONS_PLAN.md` (v3, approved). This page is the short
form an agent should hold in mind before touching interviews, sessions,
reports or identity. It supersedes the framing in the older pages where they
disagree; those pages were updated the same day.

## The shape

An **interview** is a fixture created once and practised against by a cohort:

| Part | What it is | Where it lives |
|---|---|---|
| The job | title, JD, skills, location and the M1 configuration | `interviews` row |
| The persona set | archetypes cast against the job | `virtual_candidates` |
| The **expectation checklist** | the behaviours the *interviewer* is measured on, grouped under the four fixed competencies | `interviews.expectations` — [Interview record](/concepts/contracts/interview-record.md) |
| The **report shape** | which sections the report shows | `interviews.report_sections` — eight keys, [Interview record](/concepts/contracts/interview-record.md) |
| The **link** | a token with an expiry that takers arrive on | `interview_links` — [Links and participants](/concepts/contracts/links-and-participants.md) |

A **session** is one person taking that fixture once. Every session of an
interview gets the same checklist and the same report shape — configuration is
never per session. Who took it is a **participant**, keyed by email:

* **SkillBrew accounts create interviews.** Anyone holding a link takes one; a
  SkillBrew user may take one too.
* **The same email is the same person.** Sessions across different interviews
  and personas join on one `participants` row so a taker's history reads as
  one. There is no password, login, role or user table here, and this service
  sends no email — SkillBrew keeps authentication and the org. This amended
  the earlier boundary ([Decisions](/decisions.md)).

## The invariants that do not move

* **The four competencies are fixed** (`evaluation_agent/rubric.py`) and are
  never a per-interview setting. They are the report's four cards and the
  rubric's four weights everywhere, or managers stop being comparable.
* **What varies is the granular list under them**: the rubric's own
  behaviours (*fixed*, toggle only), job-grounded items a model *drafts*, and
  items the manager types (*custom*, filed under a competency the model
  suggests and the manager may override). The model writes wording and a
  label; it cannot add a competency, change a weight, or set `enabled`.
  [evaluation_agent/expectations.py](/concepts/modules/evaluation-agent-expectations.md).
* **Every number on a report is deterministic code.** A section is on by
  default only if the engine has it; a number is on by default only if code
  computes it (the readiness percentage is); prose no number stands behind is
  off (the summary); the transcript is evidence, not a computation, and is off
  until asked for.
* **A toggle that changes nothing does not ship.** Seven of the twelve mockup
  section keys were dropped for that reason.
* **Personal data stays out of the bundle.** A participant's name and email
  are a named employee's data, stored beside their recording under the
  recording's retention decision, never copied into okf, logs or fixtures.

## What is built, and what is not (2026-09-14)

* **Built (WP1, staged 2026-09-13)**: the checklist and its two model calls
  (`POST /expectations/draft`, `POST /expectations/classify`), the re-keyed
  section map, links (`POST /interviews/{id}/links`, public `GET
  /links/{token}` with 410 on expiry or revocation, `DELETE /links/{token}`),
  participants (`POST /sessions` with `invite_token` + `participant`, the two
  history routes), Postgres `0004`, the SQLite one-off, the retirement of
  `expectation_agent/`. `require_shared_secret` gates the link minter and the
  participant routes.
* **Built (2026-09-14)**: `PATCH /interviews/{id}` — the fixture's checklist and
  report shape are **editable after creation**, which the wizard in
  `skillbrew-organization` needs because it saves the interview on step 1 and
  draws the expectation toggles on step 2. Two fields only, `expectations` and
  `report_sections`, through the one-method `InterviewEditor` port. Editing is
  allowed at any time, including once sessions exist: a report already
  generated keeps its stored scores, and one generated later scores the current
  list. The 409-after-the-first-session rule the wizard plan first proposed was
  dropped before it was built — it would have been unreachable and unreadable,
  which is the inert guard this repo forbids.
* **Not built — WP2**: nothing yet *scores* an expectation item and the
  renderer does not *honour* `report_sections`. Both are stored and passed
  through; a manager switching `transcript` on sees no change until WP2.
* **Not built — WP3**: the console screens (draft, toggles, add-custom,
  create-link, `/take/{token}`); the portal's screens are a separate repo.
* **Not built — WP4**: the end-to-end run with a real link and two
  participants.
* **Follow-on, not in the plan's scope**: the cross-interview **insight
  view** for one taker (the data model and history route exist); the portal
  landing page.

## Where to go next

[Interview record](/concepts/contracts/interview-record.md) ·
[Links and participants](/concepts/contracts/links-and-participants.md) ·
[REST API](/concepts/contracts/rest-api.md) ·
[Determinism split](/concepts/determinism.md) ·
[Report engine](/concepts/subsystems/report-engine.md) ·
[Backlog](/backlog.md)
