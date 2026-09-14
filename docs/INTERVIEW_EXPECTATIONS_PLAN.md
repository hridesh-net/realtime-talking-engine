# Interview expectations at creation — the competencies a manager is judged on

*Plan v3, 2026-09-13. Drafted by Fable against commit `4280481` plus the staged
audit cleanups; v2 folded in the product owner's answers of the same day, v3
their confirmation of the link path and the participant model. **Approved for
implementation.** Nothing here is built yet.*

## 0. What this is

The requirement, in the owner's words:

> Build the **Interview Expectations** when the interview is being created.
> Expectations are what exactly should be expected from the person who is
> taking the interview — the manager practising. They are also the
> **competencies** the report is prepared from. At creation the manager sees
> them as **toggles**, can turn each off or on, and can **add more as text**.
> Creation also carries **report toggles** — whether the transcript is in the
> report, whether the communication result is, whether a percentage score is.
> One interview, one configuration: **many people take the same interview**
> and every one of them gets the same competencies and the same report shape.
> The main way people will take it is a **link with an expiry**: they open it,
> fill a simple form asking for name and email, and start. SkillBrew accounts
> are for the people who *create* interviews; a SkillBrew user may also take
> one. **People using the same email are the same person**: their sessions
> across different interviews and personas link to that email so a single
> taker's history can be read as one.

So an interview becomes a *fixture*: a job, a persona set, a competency
checklist, a report shape and a link, created once and practised against by a
cohort.

## 1. Facts the plan rests on (verified by reading, not assumed)

1. **The four competencies already exist and are fixed configuration.**
   `evaluation_agent/rubric.py` — Hiring with Clarity 25, Structured
   Interviewing 30, Fair & Inclusive 25, Communication & Presence 20 — each with
   a `covers` list of the behaviours it measures. `report_engine` scores them
   from deterministic signals plus one judged model call under a veto.
   Decision on record (memory `product-direction-manager-assessment`): the
   rubric does not vary or scores stop being comparable; nothing caps or fails.
2. **Report toggles already exist on the interview and are consumed by
   nothing.** `InterviewCreateRequest.report_sections: dict[str, bool]` (12
   keys copied from the wizard mockup's step 4) is validated, stored in
   `interviews.report_sections`, returned — and neither
   `control_plane/reporting.build_bundle` nor `report_engine/render.py` reads
   it. Several keys name sections the renderer does not have.
3. **The renderer has exactly five sections plus a `detail` tail.**
   `render.to_html`: scorecard (four cards, `x/4`, narrative, bullets, a
   covered/missed strip built from each signal's `checklist`) → Q&A → BEI →
   strengths against gaps → areas to improve → footer; `detail=True` appends
   the readiness index (0–100), the summary and every signal. The section list
   is the hiring manager's own cut (memory `hm-report-house-style`). There is
   **no transcript section**.
4. **The "draft, then the operator decides, then store" pattern exists.**
   `POST /api/v1/role-facts` drafts the six role facts from the JD; the wizard
   shows them; `POST /interviews` stores what the operator kept. Creation is a
   fast, model-free call by design.
5. **`report_engine` already accepts an org-named competency list.**
   `ReportConfig.skills: list[str]`, consumed by
   `signals/structure._competency_coverage` (cue match over the questions
   asked, weight 1.5, SOURCED Campion et al. 1997). `build_bundle` never fills
   it.
6. **The old `expectation_agent` is the wrong shape and is scheduled for
   deletion.** It generates a candidate-facing interviewer *plan* from the JD.
   Pivot plan Phase 2 task 7: retire it. Its two consumers are persona
   casting's `expectation_note` and the audio analysis context
   (`interview_expectation`, read by the analysis agent's
   `expectation_coverage` at **40 % weight**). The portal never calls it; the
   console has the two API functions but no screen.
7. **One interview, many sessions, is already the model.** `sessions` rows
   hang off an interview; configuration lives on the interview row and is
   read at report time. A session does **not** record who took it: no
   `user_id`, no name, no email; `SessionBundle.session.manager_id` is `""`.
   There is no link, token or expiry anywhere in the repo. The session and
   recording routes carry **no authentication** today.
8. **The judge may author sentences, never selection or numbers.**
   `report_engine/judge.py` + `validate.py`: verbatim spans only, no digits in
   prose, cannot add a finding code did not select. Every number printed on a
   report is a field of `AssessmentReport` computed in `score.py`.
9. **The determinism split** (`okf/concepts/determinism.md`): the model writes
   only what has to be grounded in the specific job; every score, weight and
   selection is code. The role-fact agent is the precedent for "the model
   drafts wording onto fixed keys and cannot add a key".

## 2. Decisions (settled here; not a menu)

**D1 — The four competencies are fixed, never toggled, and not a setting.**
They stay the report's four cards and the rubric's four weights on every
interview; the wizard does not offer them as switches. What is dynamic is the
**granular rubric underneath**: an interview carries a list of
`ExpectationItem { id, competency_id, text, source, enabled }` where
`competency_id` is one of the four fixed ids, `source` is
`fixed | drafted | custom`, and `enabled` is the toggle the manager sees.
* *fixed* items are the rubric's `covers` behaviours, one item each, present on
  every interview. They are what the deterministic signals already measure.
  They can be toggled off — the signal is still computed and stored, it just
  stops counting toward the card and stops rendering.
* *drafted* items are job-grounded wording the model proposes at creation
  (e.g. "Asks how the candidate handled a missed quota" under Structured for a
  sales role), the way role facts are drafted today.
* *custom* items are the manager's own text.

The four competencies are shown in the wizard only as the headings the items
are grouped under. "Communication result" in the owner's list is therefore the
Communication & Presence card, which is always present; what the manager can
switch is the items inside it.

**D2 — The model drafts wording and classifies, onto fixed keys, and nothing
else.** A new `ExpectationsAgent` in `evaluation_agent/` (beside
`RoleFactsAgent`, temperature 0.1, same clamp discipline) has two calls:
* `draft(job_title, jd, skills_required, location)` → *drafted* items, at most
  three per competency, each tagged with a competency id from the fixed set,
  truncated to 200 characters, deduplicated against the fixed items. It cannot
  add a competency, change a weight, or set `enabled`.
* `classify(text)` → the competency id a custom item belongs under, from the
  fixed four, with a one-line reason. **The manager can override the
  suggestion**; an answer outside the four is discarded and the UI falls back
  to Structured Interviewing with the reason blank. This is the "AI help" the
  owner asked for and it is the only thing the model decides about a custom
  item.

Two routes mirror `POST /role-facts`: `POST /api/v1/expectations/draft` and
`POST /api/v1/expectations/classify`. Both store nothing and answer 502 on a
provider failure. `POST /interviews` stores the final list; it rejects an
unknown competency id, an empty item text, more than `MAX_CUSTOM_ITEMS = 12`
custom items, or a fixed item whose text was edited (fixed items are
identified by id and their text comes from the rubric).

**D3 — Every item is scored by code from two observations.** For each enabled
drafted or custom item the report engine computes `met | partly | not_met`
from:
1. **counted** — a deterministic cue match over the manager's question acts,
   the mechanism `_competency_coverage` already uses (cues derived from the
   item text; the shipped role-family pack stays the fallback when an
   interview has no drafted or custom items);
2. **heard/read** — the judge returns, per item, a verdict and a verbatim
   span, which `validate.py` vetoes exactly as it vetoes `surfaced` verdicts
   today; on the audio path the analysis agent's `expectation_coverage` is
   pointed at this same list instead of the retired document.

Code combines the two: counted first; a judge verdict can raise `not_met` to
`partly` or `partly` to `met` only with a surviving span, never lower a
counted `met`. Each enabled item is one signal under its competency, so it
enters the card's score through the same renormalisation every signal does.
Fixed items keep their existing signals untouched; a disabled fixed item's
signal is computed, stored under `signals` and given weight 0.

**D4 — Items render inside their competency's card, not as a new section.**
The scorecard's covered/missed strip already lists each signal's checklist;
drafted and custom items join that strip under their competency with the same
✓/✗ and the judge's quote when one survived. Five sections stay five.

**D5 — `report_sections` is re-keyed to what the renderer can honour, and the
renderer honours it.** Same `dict[str, bool]`, same column, same unknown-key
validator; the key set becomes:

| key | default | numeric? | what it does |
|---|---|---|---|
| `scorecard` | on | yes — `x/4` per card from `score.py` | the four competency cards, incl. the expectations strip |
| `qna` | on | counts and timestamps | every question with time and tag |
| `bei` | on | counts | behavioural questions asked, hypotheticals asked instead |
| `strengths_gaps` | on | — (selected by code, worded under veto) | strengths against gaps with quotes |
| `areas` | on | — (selected by code, worded under veto) | numbered areas to improve with a Try line |
| `percentage_score` | **on** | yes — readiness 0–100 from `score._readiness` | the readiness index on the manager's page (today `detail`-only) |
| `transcript` | off | — | the full turn list, timestamped, appended after the areas |
| `summary` | off | — (judge prose under veto) | the summary paragraph on the manager's page (today `detail`-only) |

The owner's rule, applied: everything the current report shows stays on; a
number is on by default only if code computes it deterministically (the
readiness index is); prose that no number stands behind is off by default
(the summary). The transcript is raw evidence rather than a computation and
is off until asked for. **Every number on any rendered page is a field of the
stored `AssessmentReport` computed in `score.py`** — the judge is already
vetoed on digits, and WP2 adds a test that the rendered HTML contains no
numeral that is not traceable to a report field. The seven mockup keys that
name nothing the engine measures are dropped; a toggle that changes nothing
is the inert-guard pattern this repo forbids.

**D6 — `expectation_agent/` is retired in this work.** Pivot task 7: package,
v1 schema, the two endpoints, `ExpectationStore`/`ExpectationWorkflowStore`
(and the mix-ins on `EnrollmentStore`/`SessionWorkflowStore`), the
`interview_expectations` table (SQLite `_SCHEMA` plus a Postgres migration),
`tests/test_expectation_agent.py`, the console's two API functions. Casting's
`expectation_note` is built from `skills_required` and the enabled items; the
analysis context's `interview_expectation` becomes
`expectations: list[ExpectationItem]`. okf pages for the old agent are marked
superseded, not deleted.

**D7 — A link with an expiry, and a participant on every session.**
Confirmed by the owner 2026-09-13, superseding the decision on record that
this repo never builds invites (memory `skillbrew-owns-identity-and-invites`,
amended the same day). The split is now: **SkillBrew accounts create
interviews; anyone with a link takes them; a SkillBrew user can take one too.**
* **No emails are sent and no accounts exist here.** SkillBrew still owns
  authentication and the org. What this repo adds is a *token*, and a
  *participant* keyed by email, because expiry has to be enforced by the
  service that creates sessions and cross-interview history has to be joined
  where the sessions are.
* `participants`: `id` (PK), `email` (**UNIQUE**, normalised: trimmed,
  lower-cased, shape-validated), `name` (the most recent form value),
  `user_id NULL` (a SkillBrew user id when one is ever supplied for that
  email), `created_at`, `last_seen_at`. **This is an identity join key, not a
  user table**: no password, no login, no roles; rows are created or updated
  on session creation and never by a separate signup. A person who takes five
  interviews against five personas has five sessions and one participant row.
* `interview_links`: `token` (32 random bytes, URL-safe, PK), `interview_id`,
  `expires_at`, `revoked_at NULL`, `created_at`. Several links per interview
  are allowed (a cohort in March and one in June); one link serves any number
  of takers. `POST /interviews/{id}/links {expires_at}` → 201 with the token;
  `DELETE /links/{token}` revokes. Both sit behind the shared-secret gate
  (renamed `require_shared_secret`) until the portal's auth reaches this
  service — nothing on the interview routes is authenticated today, and a link
  minter must not be the first open one.
* `GET /links/{token}` is **public** and answers only what the landing form
  needs: job title, duration, language, `expires_at`; 404 unknown, **410**
  expired or revoked. Token comparison is constant-time; the response never
  echoes the JD or the persona.
* `POST /sessions` gains `invite_token` and `participant {name, email}`; a
  logged-in portal caller sends `participant` too (its own user's name and
  email) plus `user_id`. With a token the service resolves the interview from
  the link, enforces expiry **at that moment**, upserts the participant by
  email, and stores `participant_id` on the session. `sessions.participant_id`
  is nullable only for rows that predate this change; every new session has
  one.
* **Cross-interview history**: `GET /participants/{id}` (name, email, session
  count) and `GET /participants/{id}/sessions` (every session across every
  interview: interview title, persona, modality, dates, and the stored
  report's four competency scores and readiness when a report exists). That
  is the data the insight view reads; the insight *report* itself — trends
  across personas for one taker — is a follow-on work package once there is
  more than one session per person to look at. Both routes are behind the
  shared-secret gate: they expose one person's history.
* The report masthead names the participant; `SessionBundle.session.manager_id`
  carries the participant id and `manager_name` the name.
  `GET /interviews/{id}/sessions` lists the participant on each row.
* **Data hygiene**: name and email are personal data of a named employee,
  stored beside their recording. Retention follows the recording's decision
  (indefinite, deleted by hand — [Session recording](../okf/concepts/contracts/session-recording.md));
  deleting a person means deleting their sessions, recordings and the
  participant row by hand, in that order. Neither field is ever copied into
  okf, logs or fixtures.
* The **landing page** (the form) lives in the SkillBrew portal as a public
  route in its follow-on package; the `ui/` console gets a minimal
  `/take/{token}` screen so this repo can verify the flow end to end.

**D8 — Storage.** One new JSON column on `interviews` (`expectations`);
`report_sections` keeps its name and column; `sessions.participant_id`
(nullable FK); the `participants` and `interview_links` tables;
`interview_expectations` dropped.
SQLite `_SCHEMA` and `0001` change the way the 2026-09-10 renames did (with a
one-off script for an existing `.db`), Postgres gets
`0004_expectations_participants_links.sql`. Public Pydantic models change, so
`scripts/export_schemas.py` runs and `owner_handover/` is regenerated.

**D9 — The console gets the screens; the portal follows its own plan.** The
`ui/` wizard's step 2 gains the expectation list (draft button, items grouped
under the four headings with toggles, add-custom row with the classified
competency pre-selected and overridable) and the report-shape toggles; the
interview detail gains "Create link" with an expiry picker and copy; a
`/take/{token}` screen opens a session from the form. The SkillBrew portal's
screens are a separate repo and a follow-on work package under
`docs/INTERVIEWER_PRACTICE_PORTAL_PLAN.md`; the API is designed so the portal
needs only the calls the console makes.

## 3. Work packages

**WP1 — Domain, storage, API** (Python; Opus implements)
* `evaluation_agent/expectations.py`: `COMPETENCY_IDS`, `ExpectationItem`,
  `fixed_items()` from `DEFAULT_RUBRIC.covers`, `ExpectationsAgent.draft` and
  `.classify` with the role-fact clamp discipline. Prompts ask for behaviours
  *of the interviewer*, never of the candidate.
* `schemas.py`: `InterviewCreateRequest.expectations`, re-keyed
  `report_sections` (D5) with the unknown-key validator, `InterviewLink*`,
  `SessionCreateRequest.invite_token` / `.participant` / `.user_id`,
  `ParticipantInput`, `ParticipantResponse`, `ParticipantSessionRow`;
  response models; `MAX_CUSTOM_ITEMS`.
* `database.py` `_SCHEMA`, `migrations/0001` + `0004`, the one-off for an
  existing SQLite `.db`; `repository.py` create/get/list carry the new fields;
  `LinkStore` (create, get, revoke), `ParticipantStore` (upsert by email,
  get, list sessions with report scores) and a `LinkSessionStore` composite —
  narrowest port each, per the ISP test.
* `api.py`: the two expectation routes; `POST /interviews/{id}/links`,
  `DELETE /links/{token}`, `GET /participants/{id}`,
  `GET /participants/{id}/sessions` behind `require_engine_secret` (renamed
  `require_shared_secret`); public `GET /links/{token}`; `POST /sessions` with
  the token path and the participant upsert; retire the two old expectation
  routes and their ports.
* D6 retirement, casting note rebuilt, `export_schemas.py`, okf, log.
* Tests (offline): draft clamps (unknown competency dropped, >3 per
  competency truncated, duplicate of a fixed item dropped); classify clamps
  (answer outside the four → default with blank reason); create rejects an
  unknown competency id, an edited fixed item, a 13th custom item, an unknown
  section key, and accepts the defaults; a link round-trips, an expired or
  revoked one is 410 on GET and 410 on session creation, a token compared in
  constant time; two sessions with the same email in different case and
  whitespace share one participant row and the name follows the latest form;
  a `user_id` supplied later attaches to the existing row; the history route
  lists sessions across two interviews with their report scores and omits
  scores for a session without a report; the old expectation routes are 404;
  architecture green with the package removed.

**WP2 — Report engine and analysis** (Python; Opus implements after reading
the Campion/Levashina structured-interview literature on coverage measures
and the veto design in `report_engine/validate.py`)
* `report_engine/schema.py`: `ReportConfig.expectations`, `.sections`,
  `ItemResult`; `SessionMeta.participant_name`; `BUNDLE_VERSION` bumps.
* `signals/expectations.py`: one signal per enabled drafted or custom item
  (counted half, D3), attached to its competency; disabled fixed items get
  weight 0 in `score.py`.
* `judge.py` + `validate.py`: per-item verdict with span, vetoed like
  `surfaced`; code combines per D3.
* `render.py`: `to_html(report, *, sections, detail)`; transcript section;
  readiness and summary on-page when toggled; items in the card strip; the
  numeral-traceability test from D5.
* `control_plane/reporting.py`: `build_bundle` fills `report_config` and
  `manager_id`; `build_analysis_context` passes the items; `analysis_agent`
  INSTRUCTIONS §5.5 reworded to the item list (`INSTRUCTIONS.md` is
  versioned — bump).
* Tests: byte-identical no-judge output for the same bundle; each section
  toggle changes exactly its section; a disabled fixed item leaves the
  stored signal and removes it from the card; an item's counted verdict
  cannot be lowered by the judge; a judge span not in the transcript leaves
  the counted verdict standing; no numeral in the HTML without a report
  field behind it.

**WP3 — Console** (JSX; Sonnet implements)
* Wizard step 2: "Draft expectations", items grouped under the four headings
  with toggles, add-custom row that calls classify and pre-selects the
  competency, the eight report-shape toggles with D5 defaults. Interview
  detail: "Create link" (expiry picker, copy, revoke, list). `/take/{token}`:
  landing form → `POST /sessions` with the token → straight into the session
  view. `api.js` gains `draftExpectations`, `classifyExpectation`,
  `createLink`, `revokeLink`, `getLink`; loses the two old expectation calls.

**WP4 — Verification and bundle**
* Create an interview with two drafted items off, two custom items on,
  `transcript` on; mint a link with a five-minute expiry; open it twice as
  two participants, run a session each, then open a second interview's link
  as the first participant again; confirm both reports carry the same shape,
  the strip shows the items, the mastheads name each participant, the first
  participant's history lists two sessions across two interviews, and the
  link answers 410 after expiry. Offline gate green, Postgres gate green
  through Apple `container`. okf: new concept page for expectations and
  links, the retired agent marked superseded, contracts and repo map, the
  `skillbrew-owns-identity-and-invites` decision amended in the bundle and in
  memory, log.

Order: WP1 → WP2 → WP3 → WP4. WP1 and the schema half of WP2 can overlap; the
renderer waits for the schema.

## 4. Model split

Fable owns this plan and reviews each package's diff against sections 2 and 6.
Opus implements WP1/WP2 with the research reads named above; Sonnet implements
WP3 against the console's existing patterns. No fakes ship: both agents are
injected like every other agent, and the offline tests use the existing fake
`StructuredModel`.

## 5. Out of scope, on purpose

* Toggling or re-weighting the four competencies — fixed, per the owner.
* Sending email, authentication, rosters, assignment UI — SkillBrew owns
  them; `interview_assignments` is superseded by `participants` + links and
  is dropped in `0004` rather than left designed-not-built.
* The cross-interview insight report (trends for one taker across personas)
  — the data model and the history route land now; the view is its own WP.
* Per-session overrides of the interview's configuration.
* The portal screens (separate repo, follow-on WP).
* Scoring a custom item from audio prosody — the analysis agent reads it as
  coverage, nothing more.
* Authentication on the existing interview and session routes beyond the
  link minter — a separate decision the portal integration has to make.

## 6. Open questions

None. The one question v2 carried — whether the link and participant belong
in this service — was answered 2026-09-13: they do, with SkillBrew keeping
authentication and interview creation, and the same email meaning the same
person across interviews.
