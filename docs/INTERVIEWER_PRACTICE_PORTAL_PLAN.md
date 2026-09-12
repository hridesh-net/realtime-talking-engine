# Interviewer Practice in the SkillBrew Organization portal — implementation plan

Status: **v2, approved by the user 2026-09-10** (with `@google/genai` approved). **Build state 2026-09-11:** WP0–WP6 implemented and staged (uncommitted) on `feature/interviewer-practice`; portal gates green (tsc, eslint on all 90 changed files, 175 feature tests, `next build`); `scripts/check.sh` green here. **WP7 walkthrough 2026-09-11** (portal on :3002 with the SkillBrew backend stubbed locally, control plane on :8081): list + status tabs + search, wizard (both steps, validation, role facts), detail (Sessions/Practise/Cast/Compose), transcript panel, completed typed-session view, report generate → render → Show working toggle, and the same-origin report.html/recording proxy (200 / 404 / 401 without cookie) all PASS. NOT verified: live typed session, spoken session, audio download — every cast goes through Gemini and the `GEMINI_API_KEY` in this repo's `.env` is rejected by Google (`API_KEY_INVALID`), so role-fact auto-fill and session start return 502 (the portal surfaces the plain-sentence error as designed). Re-run those three with a valid key. Cosmetic: the portal's own `src/ui/Alert` paints `--grey-color-shade-9` (#454545 in the light theme) as its background, so every info/danger banner renders dark with low-contrast coloured text — pre-existing primitive from #354, not ours to restyle. Authored by Fable 5.1 after reading
both repos; reviewed independently by Opus (§7). Eighteen findings, six
blocking; all folded in below.

## 0. What this is

Add one new left-panel entry, **Interviewer Practice**, to the organization
portal (`skillbrew-organization`, Next.js App Router, port 3002) and behind it
the whole interview-watcher console: the interview list, the two-step create
wizard, the interview detail page (sessions, practise, cast, compose), the typed
live session, the spoken live session, and the development report. The portal
talks to the interview-watcher control plane over HTTP exactly as the existing
Vite console does today.

Nothing existing in the portal changes behaviour. The additions touch four
shared files (`Config.ts`, `CommonConfig.ts`, `store/index.ts`,
`Sidebar.tsx`) with append-only edits; everything else is new files under
`src/features/interviewer-practice/`, `src/app/interviewer-practice/` and one
route handler under `src/app/api/interviewer-practice/`.

Branding: the feature uses only the portal's fe-assets tokens
(`--primary-color`, `--grey-color-*`, `--font-*`, `--line-height-*`,
`--background-color`, `--body-bg`) and its `src/ui` primitives. The
interview-watcher palette (`--blue`, `--ink`, `--amber`…) is **not** ported.

## 1. Facts the plan rests on (verified by reading, not assumed)

Portal (`skillbrew-organization`, `develop` at `f401a169`, pulled today):

* Greenfield work must live in `src/features/<feature>/` + `src/ui/`, CSS
  Modules colocated, Redux under `features/<feature>/store/` with
  `<feature>.slice.ts / .thunk.ts / .selectors.ts / .types.ts`, colocated
  `*.test.tsx`. Reference pattern: `src/features/settings/`.
* Every HTTP call goes component → thunk → `ApiConfig` prefix → `GETAPI` /
  `POSTAPI` / … in `src/api/api.ts`. `api.ts` must not be modified. Its
  status-code table (`CODE` from fe-assets, verified in
  `skillbrew-fe-shared/src/constants/Constants.tsx`):

  | Status | `api.ts` resolves to | Toast |
  |---|---|---|
  | 200, 201 | the raw response body | `message` on success only if `toast_status` |
  | **202, 204** | **the whole axios response object** | if `toast_status` |
  | 400, 404 | the body | if `toast_status` |
  | **422, 409, 408** | body for 422; **`undefined` for 409/408** | **always**, `response.data?.message` |
  | 401 | token refresh against SkillBrew, then **logout of the whole portal** | — |
  | 403 | redirect to the Error403 page | — |
  | 500 | redirect to the Error500 page | — |
  | **410, 502** (no branch) | **`undefined`** | none |

  Both axios instances send `withCredentials: true` and `X-Organization-Id`
  from the `orgid` cookie. Neither can send a raw `audio/webm` body (JSON and
  multipart only). Every `ApiConfig` entry is an absolute URL, which axios
  honours over the instance `baseURL`.
* Every `RouteConfig` path is an absolute URL. `GuardedLink` renders a plain
  `<a>` for cross-origin hrefs and `router.push` with an absolute URL is a
  full reload, so the settings pilot strips the origin with
  `toSettingsPathname()` before navigating. Adding a `RouteConfig` entry with
  `"authentication"` automatically enrols its path in the login-redirect
  middleware (`src/proxy.ts` via `getAuthenticatedOrganizationPaths()`); the
  middleware passes `/api/*` through untouched and its matcher excludes
  `assets/`.
* Routes: thin `page.tsx` files wrapped in `ProtectedRoutes` with
  `RouteConfig.<Key>.permissions`; a feature `layout.tsx` wraps `<Layout>`
  (see `src/app/brew-voice/layout.tsx`). `params` is a Promise. A Route
  Handler precedent exists at `src/app/api/payment/key/route.ts`.
* Sidebar entries are hand-written `GuardedLink`s in
  `src/components/layout/Sidebar.tsx`; BrewVoice and HireFlow have no
  permission gate, AI Interview is gated on `view_interview`. Phosphor icons,
  `weight="fill"` when active. `__tests__/components/layout/Sidebar.test.tsx`
  asserts link presence.
* `src/ui` inventory: Alert, Avatar, Badge, Breadcrumb, Button, Card, Chip,
  Divider, ImageCrop, Input, Modal, Select, Tabs, Textarea. There is **no**
  Table, Toggle, Slider or progress bar. `chart.js` is a dependency with a
  radar precedent in `src/components/interview/user-result-v2/SkillRoleRadarChart.tsx`;
  `react-hook-form` + `yup` are dependencies. No new library without explicit
  approval. No raw `<svg>` in JSX. No `Swal.fire`; use
  `useConfirmationModal().openConfirm(...)`.
* Tests mock `@skillbrew/fe-assets` (`CODE = {}`), so a test must mock
  `@/api/api` (as `settings.thunk.test.ts` does), never exercise the real
  `api.ts`. Coverage thresholds are global. `npm run test` is not in CircleCI;
  lint, type-check and build are.
* Config: there is no `.env.example`; `.env.local` is gitignored; `NEXT_PUBLIC_*`
  is inlined at build time and the Docker build pulls env from AWS Secrets
  Manager. A new public env var is an ops action.
* **`node_modules` is absent.** `@skillbrew/*` packages come from AWS
  CodeArtifact (`.npmrc` needs `AWS_ACCOUNT_ID` and an auth token in the
  environment). Lint, type-check and tests cannot run until `npm install`
  succeeds.

interview-watcher (this repo):

* FastAPI at `/api/v1`, **no auth, no CORS middleware, no envelope**: success
  bodies are bare JSON, errors are `{"detail": …}`. `GET /voice-capability`
  has a top-level `detail` field on **success**, so `detail` cannot be the
  failure discriminator. No success body carries a boolean `status`
  (every `status` field is a `str`; report and analysis carry none at top
  level) — verified across `control_plane/schemas.py`, `report_engine/schema.py`,
  `analysis_agent/schema.py` and `owner_handover/*.json`.
* Status codes the API actually uses that `api.ts` swallows: **502** for
  every model/vendor failure (five sites), **410** for a deleted persona,
  **409** in seven places, 422 in four. `POST …/analyze` is **202**;
  `DELETE /candidates/{id}` is **204**.
* `GET /sessions/{id}/recording` already sets
  `Content-Disposition: inline; filename="session-{id}.webm"`;
  `report.html` is served from `control_plane/api.py` (~line 949).
* `tests/test_architecture.py::test_every_test_file_is_wired_into_the_gate`
  fails for any new `tests/test_*.py` not named in `scripts/check.sh`.
  `okf/concepts/runbooks/okf-maintenance.md` routes: new env var →
  `runbooks/dev-setup.md`; new test file → `subsystems/test-suite.md` and
  `runbooks/checks.md`; endpoint change → `contracts/rest-api.md` and
  `modules/control-plane-api.md`.
* The working tree is **mid-migration to Postgres + MinIO**: `.env.example`
  and `scripts/check.sh` already describe it, `main.py` still calls
  `init_db()` on startup, and `scripts/check.sh` now needs the Apple
  `container` stack (Postgres + MinIO) to go green. WP0 edits two of those
  files (`main.py`, `.env.example`) and must not disturb the migration work
  in them.
* The console's screens and API calls are in `ui/src/` (3.7k lines JSX, 1.3k
  lines CSS). `api.js` is the complete list of endpoints the port needs. Raw
  `<svg>` exists in `PersonaComposer.jsx` (the radar) and `Shell.jsx` (the
  console's own nav rail, which the portal `Layout` replaces and is
  intentionally not ported).
* Voice: two browser transports chosen by the minted credential's `provider`:
  OpenAI WebRTC (no SDK; SDP offer posted with `fetch` to `call_url` with
  `Content-Type: application/sdp` and a bearer ephemeral token — nothing
  `api.ts` can express) and Gemini Live over WebSocket via
  `@google/genai@2.20.0` (exact pin in `ui/package.json`) plus an AudioWorklet
  file loaded by URL. The stereo recording is uploaded in 10 s chunks as raw
  bytes with strict `seq` ordering.
* The report screen embeds `report.html` in an iframe and prints via
  `contentWindow.print()`; the audio download is an `<a download>`. Both work
  today only because Vite proxies `/api` to the same origin: a cross-origin
  iframe's `print` is not on the cross-origin-accessible property list and a
  cross-origin `download` attribute is ignored.

## 2. Decisions (settled here; not a menu)

**D1 — Where it lives.** Feature slug `interviewer-practice`, label
"Interviewer Practice", reducer key `interviewerPractice`, `RouteConfig` keys
`InterviewerPractice` and `CreateInterviewerPractice` (both
`["authentication"]`), `ApiConfig` key `InterviewerPractice`, `Config.ts`
constant `INTERVIEWER_PRACTICE_API_URL = process.env.NEXT_PUBLIC_INTERVIEWER_PRACTICE_API_URL ?? ""`.
**No default host**: an unset variable renders a configuration Alert on every
Interviewer Practice page instead of silently posting job descriptions and
transcripts, with the org cookie attached, to whichever host a default named.
Sidebar entry sits directly after "AI Interview", ungated like BrewVoice (no
permission codename exists for it on the SkillBrew backend; gating is a
follow-up once one does). Icon: `GraduationCapIcon`.

**D2 — The control plane meets the portal halfway, additively.** Three
changes in interview-watcher, none of which alters an existing response for
the existing console:

1. `CORSMiddleware` with `allow_origins` from `CORS_ALLOWED_ORIGINS`
   (comma-separated; empty = middleware not installed), `allow_credentials=True`,
   `allow_methods=["*"]`, `allow_headers=["*"]`.
2. Exception handlers for `HTTPException` and `RequestValidationError` that
   return `{"detail": <unchanged>, "status": false, "message": <string>}`.
   This is **load-bearing for 409 and 422**: `api.ts` toasts
   `response.data?.message` on those unconditionally, and today that is an
   empty toast. For 400/404/422 the portal's thunks also read `message`.
3. `POST /sessions/{id}/recording/chunks` accepts `multipart/form-data` with a
   `chunk` file field in addition to the raw body; the stored `mime_type` comes
   from the part's content type.

Explicitly rejected: remapping 502/410 to codes `api.ts` understands. Those
codes are the documented contract (502 "is the vendor's answer") and the
existing console reads them. The portal handles them as `undefined` (D3).

**D2b — Report HTML and recording bytes are proxied same-origin, not fetched
cross-origin.** One Next Route Handler,
`src/app/api/interviewer-practice/[...path]/route.ts`, forwards **GET only**
for exactly two path shapes — `sessions/{id}/report.html` (query string
passed through) and `sessions/{id}/recording` — to
`INTERVIEWER_PRACTICE_API_URL`, streaming the body and the upstream
`Content-Type` / `Content-Disposition`. It refuses any other path with 404
and refuses requests without the `access_token` or `refresh_token` cookie
with 401 (the same test `src/proxy.ts` applies). Because the iframe and the
`<audio>`/download link are then same-origin, `contentWindow.print()` and
`<a download>` work with **no server change and no new tab**, and the
report stays a pure function of its stored JSON (no `?print=1` script
injection). Cost accepted: webm bytes traverse the Node server. The JSON API
still goes direct via CORS (D2), never through this handler.

**D3 — One error path, written once.** `features/interviewer-practice/store/unwrap.ts`
exports `unwrapPractice(res)`:

* `res === undefined` → `rejectWithValue("The interview service did not
  complete this request. If a model provider refused, try again.")` — this is
  the 409 (already toasted by `api.ts`), 410 and 502 case;
* `res?.status === false` → `rejectWithValue(res.message)` (400/404/422);
* an axios response (`typeof res.status === "number"` and `res.data !==
  undefined`) → `res.data` (202/204), never the response object (RTK's
  serializable check);
* otherwise → `res` (200/201 body).

Every thunk passes `toast_status=false` so `api.ts` never toasts
"undefined" on success. `api.ts` will still toast the envelope `message` on
409/422/408 by itself; the feature does **not** toast those a second time.
Components render `error` from Redux state inline (Alert) and toast only
their own successes with feature copy. This knowingly diverges from the
house `if (res?.status) return res?.data` idiom, and the divergence lives in
that one helper so a reviewer sees it once.

**D4 — Redux holds request state; the live conversation is local.** One
`ReduxState<T>` key per endpoint in the house pattern. The chat transcript,
voice interim text and recording queue stay in component/hook state fed by
`dispatch(thunk).unwrap()`, because the house `pending` reducer nulls `data`
and would blank a transcript mid-interview.

**D5 — Routes.**

| Path | Screen | Route file |
|---|---|---|
| `/interviewer-practice` | interview list | `app/interviewer-practice/page.tsx` |
| `/interviewer-practice/create` | two-step wizard | `app/interviewer-practice/create/page.tsx` |
| `/interviewer-practice/[id]?tab=sessions\|practise\|cast\|compose` | interview detail | `app/interviewer-practice/[id]/page.tsx` |
| `/interviewer-practice/[id]/sessions/[sessionId]` | live session (typed or spoken, by `modality`) | `app/interviewer-practice/[id]/sessions/[sessionId]/page.tsx` |
| `/interviewer-practice/[id]/sessions/[sessionId]/report` | development report | `…/report/page.tsx` |

`app/interviewer-practice/layout.tsx` wraps `<Layout>`. Path builders in
`features/interviewer-practice/utils.ts` (`practicePath(id?)`,
`practiceSessionPath(id, sid)`, `practiceReportPath(id, sid)`) derive from
`RouteConfig.InterviewerPractice.path` **and strip the origin** the way
`toSettingsPathname()` does, so in-feature navigation is client-side. No
string literals in components.

**D6 — Voice ships with both transports; `@google/genai` needs your approval.**
The OpenAI WebRTC path needs no library. The Gemini path needs
`@google/genai@2.20.0` and the PCM worklet served as a static file from
`public/assets/interviewer-practice/pcm-worklet.js` — under `assets/` because
the middleware matcher excludes it and it cannot collide with the `[id]`
segment. The SDP `fetch` to the vendor's `call_url` and the Gemini WebSocket
are calls to the **vendor**, not to SkillBrew (`call_url` comes from the mint
response, so no URL is hardcoded and no `WebSocketConfig` entry applies); they
live in `hooks/useVoiceCall.ts` with a comment saying why they bypass
`api.ts`. If `@google/genai` is not approved, the Gemini branch renders an
Alert saying the provider is not supported in this portal and the deployment
sets `VOICE_PROVIDER=openai`.

**D7 — No raw SVG, no emoji glyphs, no new `src/ui` primitives.** Persona
icons and tab glyphs become Phosphor icons in a feature-local map. The
composer's radar reuses the in-repo chart.js radar pattern. The four
primitives the screens need and `src/ui` lacks — `DataTable`, `Toggle`,
`RangeInput`, `LevelBar` (stress bars, completion bar) — are built **once**
by WP1 under `features/interviewer-practice/components/primitives/` so the
parallel screen packages share them. Promotion to `src/ui` is a later,
separate PR.

**D8 — Forms.** The wizard's step 1 is `react-hook-form` + `yup` (required:
job title, JD, at least one skill). Segmented choices use `Chip`. Department
is an `Input` with a native `<datalist>` of suggestions.

**D9 — Identity stays SkillBrew's.** The portal already sends
`X-Organization-Id`; the control plane ignores it today. Scoping interviews
per organization is a follow-up. **Constraint for that follow-up**: the
control plane must never answer the portal with 401 or 403 — `api.ts` turns
401 into a SkillBrew token refresh and then a portal-wide logout, and 403
into the portal's error page.

**D10 — Git.** Work happens on a new branch from `develop` named
`SBW-<ticket>` (ticket number needed — see §6). Commits follow
`SBW-<n>: feat(…)` with no `Co-Authored-By`. **Nothing is committed by the
agents**; changes are left staged for you.

## 3. Work packages

Each package owns its files exclusively. Packages in the same phase run in
parallel. "Done when" is the acceptance test the implementer must show.

### Phase A — foundations (parallel)

**WP0 — control plane additions (interview-watcher, Python).**
Owns: `control_plane/main.py` (middleware and handlers only; the startup
`init_db` line and everything migration-related is left exactly as found),
the chunk handler in `control_plane/api.py`, `.env.example` (one new
documented variable, `CORS_ALLOWED_ORIGINS`), `scripts/check.sh` (one new
gate row), `tests/test_portal_compat.py` (new), and the okf pages
`contracts/rest-api.md`, `contracts/session-recording.md`,
`modules/control-plane-api.md`, `subsystems/control-plane.md`,
`subsystems/test-suite.md`, `runbooks/checks.md`, `runbooks/dev-setup.md`,
`log.md`.
Does: D2 items 1–3.
Done when: `scripts/check.sh` is green with the Apple `container` stack
running (Postgres + MinIO — that is the current gate's cost, not something
this package adds); new tests prove (a) a 404 and a 422 body each carry
`detail`, `status: false` and `message`, (b) a multipart chunk upload stores
the same bytes and `mime_type` as the raw upload and the raw path is
unchanged, (c) with `CORS_ALLOWED_ORIGINS=http://localhost:3002` a preflight
from that origin is answered with credentials allowed and with it unset no
CORS header is emitted; the existing console's tests pass untouched.

**WP1 — portal plumbing, skeleton and shared pieces (skillbrew-organization).**
Owns: `src/config/Config.ts`, `src/config/CommonConfig.ts`,
`src/store/index.ts`, `src/components/layout/Sidebar.tsx`,
`__tests__/components/layout/Sidebar.test.tsx`,
`public/assets/interviewer-practice/pcm-worklet.js`,
`src/app/api/interviewer-practice/[...path]/route.ts` (+ its test), every
file under `src/app/interviewer-practice/**`, and in
`src/features/interviewer-practice/`: `index.ts`, `types.ts`,
`constants.ts`, `utils.ts`, `utils.test.ts`, `store/*` (slice, thunk,
selectors, types, `unwrap.ts`, `unwrap.test.ts`,
`interviewer-practice.thunk.test.ts`), `hooks/usePracticeCatalog.ts`,
`components/PracticePageHead/`, `components/PracticeConfigAlert/`,
`components/primitives/*` (D7), **and a typed stub file for every component
folder Phase B will fill** (`export const InterviewList = () => null` style,
one per WP2a/2b/3/4/5/6 component, each with its `index.ts`).
Does: D1, D2b, D3, D4, D5, D7. Types are transcribed from
`owner_handover/*.json` plus `report_engine/schema.py` and
`analysis_agent/schema.py`. **Every thunk the later packages need is written
here** (list/create/get interview, archetypes, trait dimensions, role facts,
candidates list/enroll/delete, sessions list/start/get/turn/end/transcript,
voice capability, realtime credential, recording chunk (multipart) /
finalize, report generate/get, analysis start/status). After WP1 lands,
`index.ts`, `store/*`, `app/**` and the primitives are **frozen**; Phase B
packages replace the contents of their own component folders only.
Sidebar entry added with one new test asserting the link, its href and its
active state; one test asserts `/interviewer-practice` is in
`getAuthenticatedOrganizationPaths()`.
Done when: `npm run type-check`, `npm run lint`, `npm run test` pass; the
thunk tests (mocking `@/api/api`) cover a 200 body, a `status:false` body,
`undefined`, and an axios-shaped 202/204 response; the route handler test
covers the two allowed paths, a disallowed path (404) and a missing cookie
(401); navigating to `/interviewer-practice` from the sidebar shows the
placeholder inside the portal chrome, and with the env var unset shows the
configuration Alert.

### Phase B — screens (parallel, all depend on WP1; WP3 also on WP2b)

**WP2a — list and wizard.** Owns `components/InterviewList/`,
`components/InterviewCard/`, `components/InterviewWizard/` (steps, role-fact
fields, skills editor), `components/PersonaPicker/` (list + sticky detail:
trait bounds, session beats, stress bars from `rubric_criteria`/`stress_labels`).
Behaviour ported 1:1 from `ui/src/InterviewList.jsx`, `Wizard.jsx`,
`PersonaPicker.jsx`, including "Create interview" / "Create & chat" /
"Create & talk" (voice button disabled with the capability's `detail` as
tooltip when voice is off) and the custom-persona path via enrollment.
Done when: tests cover status tabs and search on the list, wizard validation,
auto-fill from JD (mocked thunk) and the three submit actions' navigation.

**WP2b — persona composer.** Owns `components/PersonaComposer/` (+ the
chart.js radar sub-component and a folder-local `composer.utils.ts` holding
`personaSpecError`). Ported from `ui/src/PersonaComposer.jsx`: every option
comes from `GET /trait-dimensions`; `function` and `region` free text with
the same length caps. Supports both `singleMode` (wizard) and batch cast
(detail).
Done when: tests cover spec validation and that the radar receives the
selected presets' scores.

**WP3 — interview detail.** Owns `components/InterviewDetail/` with
`SessionsTable`, `TranscriptPanel`, `PractiseTab`, `CastTab` (`CandidateCard`,
`HumanTraits`), `ComposeTab`. Loads the interview with `GET /interviews/{id}`
(the console passed the object in memory; a URL-addressed page must fetch).
Delete uses `useConfirmationModal`. Audio download is a same-origin
`<a download>` to the D2b handler.
Done when: tests cover the four tabs, opening a transcript, start-session
navigation for text and voice, and delete confirmation.

**WP4 — typed session.** Owns `components/TextSession/`. Ported from
`ui/src/SessionView.jsx`: optimistic manager turn, server reply, Enter sends,
end interview, elapsed clock against `planned_minutes`.
Done when: tests cover send/reply, failure rollback, and end.

**WP5 — spoken session.** Owns `components/VoiceSession/`,
`hooks/useVoiceCall.ts`, `hooks/useStereoRecorder.ts`, `lib/geminiLive.ts`
(port of `ui/src/geminiLive.js`). Ported from `ui/src/VoiceSessionView.jsx`:
mint credential → mic → transport by provider → stereo merger → MediaRecorder
10 s chunks posted through the recording-chunk thunk as multipart with
strict seq and give-up-once semantics → transcript turns posted through a
chained queue → finalize on end. Mic picker, mute, noise-suppression toggle,
"hearing you" indicator preserved.
Done when: tests (with `MediaRecorder`, `AudioContext`, `RTCPeerConnection`
and the Gemini module mocked) cover the OpenAI event → transcript mapping,
chunk seq advancing only on success, give-up after retries, and teardown on
unmount. A manual run against the local control plane holds a real spoken
session on whichever provider the local `.env` selects.

**WP6 — report.** Owns `components/ReportView/`, `components/AnalysisPanel/`.
Same-origin iframe of `report.html` through the D2b handler (with the
`?detail=1` toggle), "Download PDF" prints the iframe, generate/regenerate,
analysis start (202 → normalised by `unwrapPractice`) + 4 s polling, "rebuild
with analysis" affordance, the `unscoreable` banner.
Done when: tests cover no-report → generate, polling to complete, and the
detail toggle changing the iframe `src`.

### Phase C — gate

**WP7 — verification and hand-off.** Owns nothing new. Preconditions: `npm
install` has succeeded in the portal; the Apple `container` stack is up for
this repo's gate. Runs in the portal: `npm run lint`, `npm run type-check`,
`npm run test`, `npm run sonar` (needs `SONAR_TOKEN`); runs `scripts/check.sh`
here; starts the control plane with
`CORS_ALLOWED_ORIGINS=http://localhost:3002` and the portal with
`NEXT_PUBLIC_INTERVIEWER_PRACTICE_API_URL=http://127.0.0.1:8081/api/v1/`,
then walks every screen end to end in the browser: create an interview, cast,
hold a typed session, hold a spoken session, generate a report, download the
audio, print the report. Leaves both repos staged, uncommitted, and reports
exactly what passed and what did not. **Deployment step (ops, not code):**
`NEXT_PUBLIC_INTERVIEWER_PRACTICE_API_URL` must be added to the portal's AWS
secret before the next portal build, and the deployed control plane's
`CORS_ALLOWED_ORIGINS` must name the portal origin.

## 4. Model split

Fable authored this plan and resolves any fork found during implementation.
WP0 → Opus. WP1 → Opus (it defines the types, thunks, primitives and stubs
every other package consumes). WP2a, WP2b, WP3, WP4, WP6 → Sonnet in parallel
once WP1 lands. WP5 → Opus (browser media is the riskiest port). WP7 → the
lead, in the real browser, not a subagent's word.

## 5. Out of scope, on purpose

* Organization scoping of interviews and any auth between the portal and the
  control plane (D9).
* Cohort, roster, assignments (`interview_assignments` stays unused).
* Promoting anything to `@skillbrew/fe-assets` or adding `src/ui` primitives.
* The Postgres/MinIO migration already in this working tree.
* Retiring the Vite console in `ui/`; it keeps working unchanged.

## 6. Needs your answer before code starts

1. **Jira ticket number** for the branch and commit prefix (`SBW-____`).
2. **`@google/genai@2.20.0` as a new portal dependency** — approve, or ship
   OpenAI-only voice for now (D6).
3. **Run `npm install` in `skillbrew-organization`** — it needs your
   CodeArtifact credentials (`AWS_ACCOUNT_ID` and the token in `.npmrc`).
   Until it succeeds no lint, type-check or test can run there. In this
   session: `! cd ~/Projects/Skillbrew/skillbrew-organization && npm install`.

## 7. Independent review

Reviewer: **Opus** (general-purpose agent, read-only), 2026-09-10, against
plan v1. Fable 5.1 authored both versions. Kimi was not available.

Blocking findings, all verified by the author against the code and adopted:
the 401/403 mapping in `api.ts` was inverted (fixed in §1, constraint added
to D9); the 202/204 branches return the axios response and sit under WP3's
delete and WP6's analysis start (D3 normalises them); `api.ts` toasts 409/422/408
unconditionally so v1's "toasts are the feature's" was false (D3 rewritten,
envelope `message` now load-bearing); WP0 could not go green without owning
`scripts/check.sh` (added) and four more okf pages (added); WP1's route
pages and `index.ts` imported components other packages owned (WP1 now ships
stubs and those files are frozen after it).

Major findings adopted: 502/410 resolve to `undefined` and the envelope never
reaches the user for them (D3 gives them a concrete message; remapping the
codes rejected in D2); v1's premise that the Postgres/MinIO migration was
untouched by WP0 was stale (restated in §1 and WP0); path builders must strip
the origin (D5); the worklet path collided with `[id]` and the auth middleware
(moved under `public/assets/`); no default API URL and an ops step for the
secret (D1, WP7).

Design alternative adopted: the reviewer proposed proxying `report.html` and
the recording through a Next Route Handler instead of `?print=1` /
`?download=1` server hacks. Adopted as D2b — it needs no control-plane change
for those two endpoints and keeps the report a pure function of stored JSON.
The reviewer's suggestion of a shared primitives folder was adopted as D7.

Not adopted: nothing. Two minor notes were informational only (CI does not
run Jest; `@mui/x-charts` is dead config).
