# Interviewer Practice wizard — the BrewVoice flow, with expectations and report configuration

Status: **v2, approved by the user 2026-09-14 with all §6 defaults; BUILT and
walked through the same day.** WP0 (Opus), WP1 (Sonnet), WP2 (Sonnet), WP3
(Opus), WP4 (Sonnet), all staged and uncommitted in their repos; Fable wired
the steps and ran the gate. **Walkthrough on `localhost:3002` against the local
control plane, all PASS:** create on Next → `?index=1&draft=1` → four drafted
items appended to the 19 fixed under the four headings → a fixed item switched
off (count 22 of 23, row muted) → add-your-own classified to *Hiring with
Clarity*, appended as Custom with a remove control → transcript and summary
switched on → Preview shows 23 active with drafted + custom and the eight
report chips → Finish → detail page → "Edit expectations" reopens step 2 with
the stored list → a fresh interview at `?index=1` shows the Draft button and
makes no model call. **One defect found and fixed at the gate:** Preview read
the interview loaded when step 2 mounted, so the save was invisible until a
reload; the slice now replaces the loaded interview with the PATCH response
(`interviewer-practice.slice.ts`, reducer test added). **Not verified:**
drafting through Gemini — the repo's key had exhausted its free-tier daily
quota (429), so the local API ran with `EXPECTATIONS_PROVIDER=openai` for the
walkthrough; the code path is provider-agnostic. Gates: `scripts/check.sh` 30
PASS; portal `tsc`, `eslint` on changed files, `jest` 251/251, `next build`
clean. Basics edits after creation are display-only (no update route for basic
fields — a follow-on if wanted).

## 0. What this is

The user asked, 2026-09-14: *"this same flow should be followed in Interviewer
Practice as well; along with these there will be additional configurations
which is report configurations, and in place of compatibility checks the
Expectations will be shown but in the same format"*, agreed to the six
recommendations that became D1–D6, and added *"generate the expectation with
the help of LLM like Gemini"*.

So the portal's **New interview** wizard in `skillbrew-organization` becomes a
three-step flow shaped like BrewVoice's **New role**:

| BrewVoice | Interviewer Practice |
|---|---|
| Step 1 *Role basics* — saves the role on **Next** | Step 1 *Basics* — saves the **interview** on Next |
| Step 2 *Screening setup* — generated **compatibility checks** as toggle rows, collapsed *Additional configuration* | Step 2 *Expectations* — model-drafted **expectation items** as toggle rows under the four fixed competencies, an add-your-own row, collapsed *Report configuration* |
| Step 3 *Preview* — Save as draft / Launch | Step 3 *Preview* — Finish |

Expectations are drafted by the control plane's existing
`POST /api/v1/expectations/draft`, which calls the configured model — Gemini by
default (`EXPECTATIONS_PROVIDER` → `LLM_PROVIDER` → first provider with a key,
Gemini first). Nothing new is built for generation. What is new is one update
route so step 2 can edit the record step 1 created.

## 1. Facts the plan rests on (verified by reading; corrections from review marked ✎)

**BrewVoice, observed on production 2026-09-14**

1. Step 1: job title, location, description (5000 cap), experience, salary,
   work type, work mode, up to ten skill chips; a collapsed optional
   *Organization details* override below. **Next** creates the role at once
   (toast "Role created successfully"); the URL becomes
   `/roles/create/{id}?index=1`; the `<h1>`, sub-line **and breadcrumb** become
   "Edit role" / "Updates apply to future calls; in-flight calls keep their
   current context."
2. Step 2 section numbers continue from step 1 (3…7). Section 3 shows
   "Generating compatibility checks…" and polls `GET roles/{id}` (3 s initial,
   1.5 s interval, 50 attempts — `src/components/brew-voice/create/ScreeningSetup.tsx:48-50`);
   after that: "Could not load compatibility checks. Please try again." +
   **Retry**, Preview disabled. Production produced 10 checks in ~25 s, all
   on, all *Recommended*; each row is a switch, a label, the tag, the question
   text; "Estimated call length … 10 checks · ~9–10 min" drops to 9 when one is
   switched off and the row greys. Toggles are saved with
   `PUT roles/{id}/compatibility-config/ {checks}` on the way to Preview.
3. Section 7 *Additional configuration* is collapsed: strict-fit hard-stop
   rules, "set a value, then switch it on".
4. Step 3 *Preview* is read-only cards; *Compatibility* lists only the active
   checks as chips with the count; Back / Save as draft / Launch role.
5. ✎ Routing: **one optional catch-all page**
   `src/app/brew-voice/roles/create/[[...id]]/page.tsx` awaiting
   `params: Promise<{id?: string[]}>`; `create/index.tsx` normalises to
   `?index=0` on mount (`router.replace`, `:139`), clamps the index
   (`parseWizardIndex`, `:47`), redirects to `?index=0` when `idx > 0` and no
   role exists (`:162`); the step bar is `<button>`s disabled until an id
   exists; leaving step 0 with unsaved edits asks first
   (`useOptionalNavigationGuard` + `useConfirmationModal`, `:16-17, :62`).
6. "Paste a JD to auto-extract" fires only on a real paste event.

**Control plane (`interview-watcher`)**

7. `POST /api/v1/interviews` is the only write; there is no update route
   (`control_plane/api.py` `@router.*` census; `okf/concepts/contracts/rest-api.md`).
   `InterviewStore` (`control_plane/ports.py:40`) has `create`, `get`, `list`.
   `SessionStore.list_sessions(interview_id)` exists at `ports.py:170`.
   `status` is only ever written as `scheduled` (`interview-record.md:173`).
8. `InterviewCreateRequest.expectations` defaults to `fixed_items()` — **19**
   fixed items (clarity 4, structure 5, fairness 4, communication 6);
   `_valid_expectations` (`schemas.py:172-`) enforces the competency ids,
   verbatim fixed wording (422), **restores omitted fixed items enabled**,
   rewrites custom ids to `custom.{n}` in request order, caps custom at 12.
   ✎ `_known_sections_only` (`:164-170`) returns `{**REPORT_SECTIONS, **v}` —
   it merges over the **code defaults**, not over the stored row
   (`tests/test_expectations.py::test_a_partial_report_section_map_is_merged_onto_the_defaults`).
9. ✎ The four competency ids **and labels are already served**:
   `GET /api/v1/candidate-archetypes` returns `rubric_criteria: [{id, label}]`
   (`api.py:239`), and the portal already reads them — `usePracticeCatalog()`
   exposes `criteria` (`hooks/usePracticeCatalog.ts:46`) and the wizard
   destructures it (`InterviewWizard.tsx:103`). Labels: *Hiring with Clarity*,
   *Structured Interviewing*, *Fair & Inclusive*, *Communication & Presence*
   (`evaluation_agent/rubric.py:72-107`).
10. `report_sections: dict[str, bool]`, eight D5 keys — `scorecard`, `qna`,
    `bei`, `strengths_gaps`, `areas`, `percentage_score` on; `transcript`,
    `summary` off; unknown keys 422. ✎ **Nothing outside storage reads them
    today**: the only non-test readers are `database.py`, `schemas.py`,
    `repository.py`. The repo says so itself — `interview-record.md`: *"WP2
    [of the expectations plan] is what makes the renderer honour them; today
    they are stored and returned"*; `okf/decisions.md:62` cut the mockup's
    twelve keys to these eight because *"an inert toggle is the guard this repo
    forbids."*
11. `POST /expectations/draft` `{job_title, jd, skills_required, location}` →
    `list[ExpectationItem]` (`source: drafted`), **synchronous**, stores
    nothing, 502 on model failure; `ExpectationsAgent._build_drafted` discards
    restatements of fixed items and unknown competencies, so an **empty list is
    a legal answer**. `POST /expectations/classify` `{text}` →
    `{competency_id, reason}`. Both via `Depends(get_expectations_agent)`.
12. Storage: `expectations` and `report_sections` are JSON columns on
    `interviews`; `create` writes them with `created_at, updated_at`
    (`repository.py:120-142`); `get` reads back with `or fixed_items()`
    (`:225`) — harmless for updates because a validated list is never empty.
13. ✎ `scripts/export_schemas.py` writes to **`owner_handover/`** (`:45`) and
    exports `InterviewResponse` but **not** `InterviewCreateRequest`; a new
    request model is exported only if added to its `EXPORTS` list.
14. ✎ `tests/test_architecture.py` checks ports from **hardcoded lists**
    `NARROW_PORTS` (`:218`) and `COMPOSITION_PORTS` (`:230`); a port not listed
    is not checked.

**Portal (`skillbrew-organization`, branch `feature/interviewer-practice`)**

15. The wizard is one 768-line component,
    `components/InterviewWizard/InterviewWizard.tsx`, two steps: Basics →
    Candidate (`PersonaPicker`, custom compose). **Creation happens on step 2**
    in `onCreate` / `onCreateCustom`, coupled to the "Create & talk" popup
    handling and to enrolling a composed persona. 11 tests in
    `InterviewWizard.test.tsx`, including two guards — *"offers neither a chat
    action nor a proctoring choice"* and *"sends no proctoring field on the
    create payload"*.
16. ✎ `persona_notes` is edited **only** on wizard step 2
    (`InterviewWizard.tsx:733-741`, sent at `:214`); nothing on the detail
    page writes it. ✎ `PersonaComposer`'s `singleMode` (10 references across
    `PersonaComposer.tsx` and `composer.utils.ts`) exists solely for the
    wizard; `ComposeTab.tsx` uses the full mode. `PersonaPicker` is also used
    by `PractiseTab.tsx:52`.
17. `types.ts`: `PracticeReportSections` (`:30`) and `report_sections` on both
    the create request (`:46`) and `PracticeInterview` (`:82`) **already
    exist**; only `expectations` is missing. Nothing in the feature calls draft
    or classify.
18. ✎ `src/api/api.ts` on **409** toasts `response.data?.message` and resolves
    to `undefined` regardless of `toast_status` (`:191-192`); `unwrapPractice`
    then yields the generic *PRACTICE_INCOMPLETE_MESSAGE* (`store/unwrap.ts:44-45`).
    A 409 body can never be shown inline. **422** returns the body, so its
    message does reach the inline error (also toasted unconditionally).
    **500** navigates the whole portal to the error page.
19. Feature primitives: `Toggle` (`label, checked, onChange, hint?, disabled?`)
    renders `label` **visibly** and as `aria-label`; `LevelBar`, `RangeInput`,
    `DataTable`. Helpers `practicePath(id?)`, `practiceCreatePath()` in
    `utils.ts:33-38`. `RouteConfig` entries with `"authentication"` feed
    `getAuthenticatedOrganizationPaths()` (`CommonConfig.ts:343+`); BrewVoice
    has **no** route entry for its id variant and composes the URL inline.
    `sessions/start/page.tsx` wraps `useSearchParams` consumers in `<Suspense>`.
20. No i18n library in `package.json`; strings are literal English.
21. Any public Pydantic change requires `.venv/bin/python scripts/export_schemas.py`
    or CI fails (`CLAUDE.md`).

## 2. Decisions (D1–D6 agreed with the user 2026-09-14; ✎ marks what v2 changed)

**D1 — Step 1 saves the interview; a new `PATCH /api/v1/interviews/{id}` lets
step 2 edit it.** Body `InterviewUpdateRequest { expectations?: list[ExpectationItem] | None,
report_sections?: dict[str, bool] | None }`; a body with neither → 422.
Validation is the create validators lifted to module functions
`validate_expectations(v)` / `validate_report_sections(v)`, each returning
`None` untouched when given `None` (an explicit `null` must be a 422 or a
no-op, never a `TypeError` → 500). 200 → `InterviewResponse`; 404 unknown id.
The handler depends on one new narrow port `InterviewEditor`
(`update(interview_id, req) -> InterviewResponse | None`), listed in
`NARROW_PORTS`. ✎ **No 409 "after the first session" rule.** Review showed it
would be unreachable within this plan (sessions are cast on the detail page
*after* the wizard) and unreadable through `api.ts` (409 bodies never reach the
inline error) — an inert guard, which this repo forbids. Editing is allowed at
any time; a report already generated keeps its stored scores, and a report
generated later scores the current item list. **The client always sends the
whole list and all eight section keys** (fact 8: partial bodies are destructive
— omitted fixed items come back enabled, omitted drafted/custom items vanish,
omitted section keys reset to defaults). `update` also sets `updated_at`.

**D2 — Three steps: Basics → Expectations → Preview. Persona choice leaves the
wizard.** Casting and "Create & talk" already live on the detail page's Cast and
Practise tabs. ✎ **`persona_notes` moves to step 1** as the last optional
field of the Basics card ("Notes for the persona"), because the wizard was its
only editor. ✎ `PersonaComposer`'s `singleMode` and its helpers are deleted
with the wizard's compose path — no dead branches left behind.

**D3 — Role facts stay on step 1 as a collapsed optional section** ("Role facts
the manager must convey"), auto-fill button unchanged.

**D4 — "Report configuration" is the eight `report_sections` toggles** in step
2's collapsed *Additional configuration*, D5 defaults. ✎ **Stated plainly: the
renderer does not honour these yet** (fact 10). Building the toggles now means
shipping a control that stores a preference the report ignores until the
expectations plan's WP2 lands. **This is a product call for the user (§6 Q1)**;
the plan's default is to build the toggles now *and* pull the expectations
plan's WP2 forward as the next piece of work, so the toggles are never live
without a renderer behind them.

**D5 — Drafting on step 2, synchronous, with the BrewVoice loading contract.**
✎ Trigger: arriving from step 1 carries `?index=1&draft=1`; the step consumes
the flag once and calls `POST /expectations/draft` with the interview's job
title, JD, skills and location. On a plain load of `?index=1` with no `drafted`
item present, it shows a **"Draft from the job description"** button instead of
calling automatically (an empty draft is legal, so "no drafted items" must not
mean "call the model on every mount"). While drafting: "Drafting expectations…"
with the dots loader; on failure: "Could not draft expectations. Please try
again." + **Retry**; Preview disabled while drafting or failed. No polling —
the route is synchronous. Initial state on any load is the **stored list
intact** (fixed + drafted + custom, with their `enabled` flags); a draft result
is appended to the fixed items and de-duplicated by id. Competency headings and
their order come from `usePracticeCatalog().criteria` (fact 9) — never a
portal-side copy. ✎ Each row is the `Toggle` primitive with `label` = the item
text (it renders the label; no second text node) plus a `Chip` tag *Fixed* /
*Drafted* / *Custom*; off rows get a muted wrapper class; count bar "N of M
on". Fixed items toggle only. Drafted items toggle only. ✎ **Custom items can
be removed** (an × on the row). **Add your own**: `Input` ≤200 chars + **Add**
→ `POST /expectations/classify` → `Select` pre-set to the returned competency
(overridable; on classify failure the `Select` is simply unselected with the
plain-sentence error and the manager picks) → append `source: custom`,
enabled. Client caps custom at 12 with the hint "Up to 12 custom items." Ids
for custom items are assigned client-side as `custom.{n}` in list order and the
server renumbers them the same way, so removal cannot collide. Leaving for
Preview sends one PATCH with the full `{expectations, report_sections}`.

**D6 — Preview ends with one button, Finish, to the detail page.** No draft
status, no launch.

**D7 — Routing mirrors BrewVoice exactly.** ✎ One page
`src/app/interviewer-practice/create/[[...id]]/page.tsx` replaces
`create/page.tsx`; it awaits `params` and renders the wizard inside
`<Suspense>` (it reads `useSearchParams`). `?index` is normalised to `0` on
mount, clamped to 0–2, and forced back to `0` when `index > 0` and no id
exists. After the create succeeds: `router.push(practiceCreatePath(id) +
"?index=1&draft=1")`; `practiceCreatePath` gains the optional id. ✎ **No new
`RouteConfig` entry** (the `[id]` literal would leak into the authenticated
path list); the existing `CreateInterviewerPractice` entry already covers the
prefix. With an id the `<h1>`, sub-line **and breadcrumb** become "Edit
interview" / "Updates apply to future sessions; a session already running
keeps its context." ✎ The step bar is clickable buttons, disabled until an id
exists; leaving step 1 or step 2 with unsaved edits asks first through
`useOptionalNavigationGuard` + `useConfirmationModal`, as BrewVoice does.

**D8 — ✎ Deleted.** The rubric ids and labels come from
`GET /candidate-archetypes` through `usePracticeCatalog`, which the wizard
already uses. No constants, no new route.

**D9 — Branding and conventions are the portal's.** fe-assets tokens, CSS
Modules, feature `Toggle`, `src/ui` `Card/Chip/Select/Input/Button`, Phosphor
icons, RHF + yup on the basics form, colocated tests, thunk naming
`{op}{Feature}Action`, commits `SBW-<n>: type(desc)`.

**D10 — ✎ An "Edit expectations" entry on the detail page** (a small link in
the page head → `practiceCreatePath(id) + "?index=1"`). Without it a manager
whose draft failed, or who wants to change a toggle after Finish, has no way
back but typing a URL. It is one link and one test, and it is what makes D1's
route worth having after day one. (Was §6 Q2 in v1; now in, pending the user's
approval of this plan.)

## 3. Work packages

Exclusive file ownership per package; no two packages touch the same file.
The user approves the plan, then WP0 and WP1 start in parallel.

### WP0 — Control plane: the update route (`interview-watcher`)

Owns: `control_plane/schemas.py`, `control_plane/ports.py`,
`control_plane/repository.py`, `control_plane/api.py`,
`tests/test_expectations.py`, `tests/test_architecture.py` (the two port
lists only), `scripts/export_schemas.py`, `owner_handover/` (regenerated), and
OKF: `okf/concepts/contracts/rest-api.md`, `okf/concepts/contracts/interview-record.md`,
`okf/concepts/contracts/storage-ports.md`, `okf/concepts/modules/control-plane-api.md`,
`okf/concepts/modules/control-plane-repository.md`,
`okf/concepts/subsystems/control-plane.md`, `okf/concepts/interview-fixture.md`,
`okf/concepts/runbooks/create-an-interview.md`, `okf/concepts/runbooks/checks.md`,
`okf/concepts/repo-map.md` (row for this plan doc), `okf/current-state.md`,
`okf/backlog.md`, `okf/log.md`.

1. `schemas.py`: lift the two validator bodies into `validate_expectations`
   / `validate_report_sections`, each `None`-safe; `InterviewCreateRequest`
   calls them; add `InterviewUpdateRequest` (both fields `| None = None`, a
   `model_validator` rejecting a body with neither).
2. `ports.py`: `class InterviewEditor(Protocol)` with `update(...)`;
   `InterviewRepository` gains it. `tests/test_architecture.py`: add
   `InterviewEditor` to `NARROW_PORTS`.
3. `repository.py`: `update` runs one `UPDATE interviews SET expectations = ?,
   report_sections = ?, updated_at = ? WHERE id = ?` for the fields present,
   then returns `self.get(id)`; `None` when the row is missing.
4. `api.py`: `@router.patch("/interviews/{interview_id}", response_model=InterviewResponse)`
   depending on `InterviewEditor`; 404 when `update` returns `None`; 422 from
   validation with the `status:false + message` envelope as today.
5. `scripts/export_schemas.py`: add `InterviewUpdateRequest` to `EXPORTS`;
   regenerate `owner_handover/`.
6. Tests (`tests/test_expectations.py`): PATCH happy path storing drafted +
   custom + a disabled fixed item, read back exactly; reworded fixed → 422;
   13 custom → 422; unknown section key → 422; empty body → 422; explicit
   `"expectations": null` → 422 (never 500); unknown id → 404; PATCH of
   `report_sections` alone leaves `expectations` untouched and vice versa;
   **a partial expectations list re-enables omitted fixed items and drops
   omitted drafted ones** (pinned on purpose — it is why the client sends the
   whole list); `updated_at` changes.
7. `scripts/check.sh` green; OKF pages updated; `okf/log.md` line.

Done when: `scripts/check.sh` passes, `owner_handover/` is regenerated, and a
`curl -X PATCH` against a running service returns the updated record.

### WP1 — Portal plumbing (`skillbrew-organization`)

Owns: `src/features/interviewer-practice/types.ts`, `utils.ts`,
`store/interviewer-practice.thunk.ts`, `store/interviewer-practice.slice.ts`,
`store/interviewer-practice.selectors.ts`, `store/interviewer-practice.types.ts`,
`store/interviewer-practice.thunk.test.ts`, `utils.test.ts` (if present).

1. `types.ts`: `PracticeExpectationItem { id, competency_id, text, source:
   'fixed'|'drafted'|'custom', enabled }`; `expectations` on
   `PracticeInterview`; `PracticeInterviewUpdateRequest`;
   `PRACTICE_REPORT_SECTION_LABELS` (eight keys → label + default, D5 order).
   `report_sections` types already exist — do not duplicate.
2. `utils.ts`: `practiceCreatePath(interviewId?)`.
3. Thunks: `draftPracticeExpectationsAction` (POST `expectations/draft`),
   `classifyPracticeExpectationAction` (POST `expectations/classify`),
   `updatePracticeInterviewAction` (PATCH `interviews/{id}`), role-facts
   pattern, `toast_status=false`; slice states + selectors.
4. Thunk tests: success, `status:false`, `undefined` for each.

Done when: `tsc`, `eslint` on changed files and the tests pass.

### WP2 — Wizard shell, step 1, routing, and the compose-path removal

Owns: `components/InterviewWizard/InterviewWizard.tsx` (orchestrator),
`InterviewWizard.module.css`, `InterviewWizard.test.tsx`, new
`components/InterviewWizard/steps/BasicsStep.tsx` + `.module.css` + `.test.tsx`,
`src/app/interviewer-practice/create/[[...id]]/page.tsx` (replaces
`create/page.tsx`, which is deleted), `components/PersonaComposer/PersonaComposer.tsx`,
`components/PersonaComposer/composer.utils.ts` and their tests (singleMode
removal only).

1. Orchestrator: reads the id from `params`, `index` from `useSearchParams`
   (normalise / clamp / redirect per D7); with an id, dispatches
   `getPracticeInterviewAction` and shows the existing loader; renders the
   clickable, guarded step bar; mounts `BasicsStep` / `ExpectationsStep` /
   `PreviewStep`; sets head title, sub-line and breadcrumb per D7.
2. `BasicsStep`: the current step-1 form verbatim, plus `persona_notes` as the
   last optional field (D2), role facts collapsed (D3). **Next** →
   `createPracticeInterviewAction` with the payload as today — **neither**
   `expectations` **nor** `report_sections` is sent, so both land at their
   server defaults — → toast "Interview created." →
   `router.push(practiceCreatePath(id) + "?index=1&draft=1")`. Inline error on
   failure as today. Unsaved-leave guard.
3. Remove `onCreate`, `onCreateCustom`, `openLaunchTab`, `afterCreate`,
   `PersonaPicker` and the step-2 card from the wizard; delete `singleMode`
   from `PersonaComposer` and `composer.utils`.
4. Tests: Next disabled until valid; **the two existing guards kept** (no chat
   action / no proctoring choice; no proctoring field on the payload); creates
   and routes to `?index=1&draft=1`; sends no `expectations` /
   `report_sections`; loads by id and mounts step 2 / 3; forces `?index=0`
   when there is no id; create failure shows the error.

Done when: tests pass and `/interviewer-practice/create` → Next lands on
`/interviewer-practice/create/{id}?index=1&draft=1` against the local control
plane.

### WP3 — Step 2: expectations and report configuration

Owns: new `components/InterviewWizard/steps/ExpectationsStep.tsx` + `.module.css`
+ `.test.tsx`; new `components/ExpectationList/` (`ExpectationList.tsx`,
`.module.css`, `.test.tsx`, `index.ts`); new `components/ReportConfig/`
(`ReportConfig.tsx`, `.module.css`, `.test.tsx`, `index.ts`).

1. `ExpectationsStep` — section 3 *Expectations — what the manager is judged
   on*, subtitle "Drafted from the job description; switch off what this
   interview should not measure." State initialises from the stored list (D5);
   `draft=1` triggers the draft once; otherwise the **Draft from the job
   description** button; loading / failed / ready states per D5; count bar
   "N of M on".
2. `ExpectationList` — groups by `criteria` order from `usePracticeCatalog`;
   row = `Toggle` (label = text) + `Chip` tag; muted wrapper when off; × on
   custom rows. Section 4 **Add your own** per D5.
3. `ReportConfig` — section 5 *Additional configuration — Report
   configuration*, collapsed; eight `Toggle`s from
   `PRACTICE_REPORT_SECTION_LABELS`; hint "Six on by default; transcript and
   summary are off."
4. **Preview →** disabled while drafting, failed, or PATCH in flight; on click
   `updatePracticeInterviewAction({ expectations: <whole list>,
   report_sections: <all eight> })` → `router.push(?index=2)`; failure shows
   the plain-sentence error inline (a 422 message reaches it; anything else
   shows the generic sentence — fact 18). Unsaved-leave guard.
5. Tests: initial state from the stored list including disabled items;
   `draft=1` drafts once and appends without duplicating ids; plain load shows
   the Draft button and does not call; Retry re-dispatches; toggle flips
   `enabled` and the count; add-your-own classifies, pre-selects, appends
   `custom.{n}`, caps at 12; remove custom renumbers; Preview PATCHes the
   **full** body and routes; failure states.

Done when: tests pass; against the local control plane with a valid Gemini key,
entering step 2 from step 1 draws drafted items and Preview stores them
(verified with `GET /interviews/{id}`).

### WP4 — Step 3, the detail-page entry, and the gate

Owns: new `components/InterviewWizard/steps/PreviewStep.tsx` + `.module.css` +
`.test.tsx`; `components/InterviewDetail/InterviewDetail.tsx` + its test (the
D10 link only); `docs/INTERVIEWER_PRACTICE_PORTAL_PLAN.md` (status line).
`okf/log.md` is WP0's file; Fable appends the walkthrough line at the gate.

1. `PreviewStep`: read-only `Card`s — *Interview* (title, location, level,
   company type, duration, language, department, manager level, notes), *Role
   facts* ("n of 6"), *Expectations* ("N active"; enabled items as `Chip`s
   under the four headings), *Report* (sections on). **Back** (`?index=1`) and
   **Finish** → `router.push(practicePath(id))`.
2. D10 link on the detail page head.
3. Gate: `npm run lint` on all changed files, `npm run test`, `tsc`,
   `next build`; `scripts/check.sh` in interview-watcher; browser walkthrough
   on `localhost:3002` via the local auth stub
   (`~/Projects/Skillbrew/tmp/skillbrew_auth_stub.py` → `/dev-login`):
   create → draft → toggle a fixed item off → add a custom item → remove it →
   flip a report toggle → Preview → Finish → detail page shows the stored
   expectations → "Edit expectations" reopens step 2 with the stored list →
   reload of `?index=1` shows the Draft button, not a call. Restore the
   portal's `AGENTS.md` after each dev-server start. Then memory updates.

Done when: every gate is green and the status line records what was and was
not verified.

### Dependencies

`WP0 ∥ WP1` → `WP2 ∥ WP3` (both need WP1; WP3's live check needs WP0) → `WP4`.

## 4. Model split

Fable authored this plan and resolves any fork found during implementation.
WP0 → Opus (the validators every create depends on). WP1 → Sonnet. WP2 →
Sonnet. WP3 → Opus (the interaction-heavy screen). WP4 → Sonnet, with Fable
running the browser walkthrough. Each agent gets its package section, file
list and "done when"; no agent edits outside its list.

## 5. Out of scope, on purpose

* A draft status or "launch" for interviews (D6).
* Any change to the `ui/` console (expectations plan D9).
* Generating expectations anywhere but the existing `ExpectationsAgent`; no
  second generator, no polling.
* Making the renderer honour `report_sections` — that is the expectations
  plan's WP2, recommended as the very next piece of work (D4).
* Operator toggles for English weighting and the language gate.
* Paste-triggered auto-extract on the JD.
* The public `/take/{token}` landing page and link minting.
* i18n — the portal has no i18n library; strings stay literal.

## 6. Open questions for the user (defaults in bold)

1. **Report toggles before the renderer honours them (D4).** Build them now
   with the expectations plan's WP2 scheduled next — **default** — or hold D4
   until WP2 lands and ship the wizard with expectations only?
2. **D10, the "Edit expectations" link on the detail page** — in (**default**)
   or out?
3. **Editing after sessions exist (D1).** Allowed, with later reports scoring
   the current list (**default**), or should the link in D10 hide once a
   session exists? (A hidden link is a UI choice, not an inert server guard.)

## 7. Review findings not adopted, and why

* *"D8 constants"* — adopted in the opposite direction: D8 deleted, catalog used.
* *"i18n"* — reviewer agreed none is needed; recorded in §5.
* *"Compose a composition port `InterviewEditor + SessionStore` for the 409"* —
  moot once the 409 was dropped; the handler needs `InterviewEditor` only.
* The reviewer's suggestion to use `Toggle.hint` for the tag — a `Chip` beside
  the label matches BrewVoice's *Recommended* tag placement; `hint` is a
  second line and is left free for future use.
