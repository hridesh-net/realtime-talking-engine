# Interviewer Practice — system flow (how it works right now)

*The end-to-end machinery behind the feature: the two repos, the request path,
every endpoint the portal calls, and the runtime seams that matter. For the
user-facing walkthrough, see
[INTERVIEWER_PRACTICE_UI_FLOW.md](./INTERVIEWER_PRACTICE_UI_FLOW.md).*

> Written 2026-09-12. Ground truth: `skillbrew-organization/src/features/
> interviewer-practice/*` (thunks, hooks, screens) and this repo's
> `control_plane/`. Cross-check with `okf/` for the control-plane internals.

---

## 1. Two repos, one feature

| Piece | Repo | Role |
|---|---|---|
| **Portal** | `skillbrew-organization` (Next.js App Router, port 3002 in dev) | Renders the feature as one sidebar tab; owns auth, routing, the live-call client, the browser recorder. |
| **Control plane** | `interview-watcher` (this repo — FastAPI, port 8081) | Owns the *what*: interviews, deterministic expectations, personas + answer keys, transcripts, recordings, reports, analysis. |
| **Voice vendor** | Gemini Live / OpenAI Realtime | Holds the live spoken conversation **directly with the browser**. Never proxied through SkillBrew. |
| **Live engine** *(not in this path)* | `smart-Interview` (Go/Rust) | The production real-time engine. **The portal does not use it today** — spoken practice uses the browser-to-vendor path below. |

The portal is the **second** HTTP consumer of the control plane (the in-repo
Vite `ui/` is the first). That drove a small **compatibility layer** in this
repo: opt-in `CORS_ALLOWED_ORIGINS`, an error envelope beside FastAPI's `detail`
(`status: false` + `message`), and a multipart door on the recording-chunk
endpoint.

---

## 2. The request path

```
Browser (portal page, localhost:3002 / org.app.skillbrew.ai)
   │
   │  JSON calls  ── api.ts (axios) ──▶  control plane directly
   │                                     base = NEXT_PUBLIC_INTERVIEWER_PRACTICE_API_URL
   │                                     (ApiConfig.InterviewerPractice)
   │
   │  Binary GETs ── /api/interviewer-practice/… ──▶ Next route handler ──▶ control plane
   │                 (report.html, recording)        (same-origin proxy, D2b)
   │
   └─ Live audio ── WebSocket / WebRTC ──▶ voice vendor (NOT SkillBrew)
```

**Two doors on purpose:**

- **JSON** goes **direct** to the control plane through the shared `api.ts`
  axios instances (`GETAPI/POSTAPI/DELETEAPI/POSTASFORMDATA`). Base URL comes
  from `INTERVIEWER_PRACTICE_API_URL` (env `NEXT_PUBLIC_INTERVIEWER_PRACTICE_API_URL`).
- **Bytes** (`report.html`, `recording`) go through a **same-origin Next.js
  passthrough** at `/api/interviewer-practice/[...path]`. Why: the report is
  embedded in an iframe and printed with `contentWindow.print()`, and the audio
  is an `<a download>` — neither works cross-origin. The route re-checks the
  portal session cookie (`access_token`/`refresh_token`) and only forwards two
  exact path shapes: `sessions/{id}/report.html` and `sessions/{id}/recording`.

Auth: every page is wrapped in `ProtectedRoutes` (permission
`RouteConfig.InterviewerPractice`); `src/proxy.ts` guards the routes on the
session cookies; `PermissionsContext` bootstraps identity/permissions from the
SkillBrew backend. **No new identity system** — SkillBrew owns identity.

---

## 3. State & the response envelope

- **Redux Toolkit** slice per feature; every server call is a `createAsyncThunk`
  in `store/interviewer-practice.thunk.ts`.
- Every thunk funnels the response through **`unwrapPractice`**, which
  normalises the two shapes the control plane can return — a bare body, or the
  `{status, data, message}` envelope — into `{ ok, data, message }`. A failed
  unwrap becomes `rejectWithValue(message)`; a thrown error becomes
  `practiceRejectMessage(err)`. Screens read selectors and dispatch; they never
  touch axios.

---

## 4. Endpoint catalogue (what the portal actually calls)

All relative to `ApiConfig.InterviewerPractice` unless marked *(proxy)*.

### Interviews
| Thunk | Method + path |
|---|---|
| `listPracticeInterviews` | `GET interviews{params}` |
| `createPracticeInterview` | `POST interviews` |
| `getPracticeInterview` | `GET interviews/{id}` |

### Catalogue (read-mostly reference)
| Thunk | Method + path |
|---|---|
| `listPracticeArchetypes` | `GET candidate-archetypes` |
| `listPracticeTraitDimensions` | `GET trait-dimensions` |
| `draftPracticeRoleFacts` | `POST role-facts` — drafts the checklist wording from a JD; **stored nowhere**, edited before create |

### Candidates (personas)
| Thunk | Method + path |
|---|---|
| `listPracticeCandidates` | `GET interviews/{id}/candidates` |
| `enrollPracticeCandidates` | `POST interviews/{id}/candidates` (cast / re-cast) |
| `deletePracticeCandidate` | `DELETE candidates/{id}` |

### Sessions — typed
| Thunk | Method + path |
|---|---|
| `startPracticeSession` | `POST sessions` |
| `takePracticeTurn` | `POST sessions/{id}/turns` (interviewer turn → persona reply) |
| `endPracticeSession` | `POST sessions/{id}/end` |
| `getPracticeSession` | `GET sessions/{id}` |
| `listPracticeSessions` | `GET interviews/{id}/sessions` |

### Sessions — spoken
| Thunk | Method + path |
|---|---|
| `getPracticeVoiceCapability` | `GET voice-capability` (is voice on? which provider?) |
| `mintPracticeRealtimeCredential` | `POST sessions/{id}/realtime` (server seals persona into an ephemeral credential) |
| `appendPracticeTranscript` | `POST sessions/{id}/transcript` (records a spoken turn, **no** model reply) |

### Recording (browser-captured)
| Thunk | Method + path |
|---|---|
| `appendPracticeRecordingChunk` | `POST sessions/{id}/recording/chunks?seq=N` — **multipart**, one ~10 s `chunk` file part; `seq` in the query string |
| `finalizePracticeRecording` | `POST sessions/{id}/recording/finalize` |

### Report
| Thunk | Method + path |
|---|---|
| `generatePracticeReport` | `POST sessions/{id}/report{query}` — options ride as query params, body empty, stamped into provenance |
| `getPracticeReport` | `GET sessions/{id}/report` |
| *(proxy)* report body | `GET /api/interviewer-practice/sessions/{id}/report.html` → iframe + print |

### Analysis (audio-derived)
| Thunk | Method + path |
|---|---|
| `startPracticeAnalysis` | `POST sessions/{id}/analyze` — answers **202**, returns immediately |
| `getPracticeAnalysisStatus` | `GET sessions/{id}/analysis` (poll: running / complete / failed) |
| `getPracticeAnalysisBody` | `GET sessions/{id}/analysis/full` |
| *(proxy)* audio | `GET /api/interviewer-practice/sessions/{id}/recording` → `<a download>` |

---

## 5. Typed-session flow

```
Practise/Cast ── startPracticeSession(POST sessions) ──▶ session {id, modality:"text"}
   route to /{id}/sessions/{sid}  ──▶ LiveSessionScreen reads session, modality=text ──▶ TextSession
   loop:  user types turn ── takePracticeTurn(POST sessions/{sid}/turns) ──▶ persona reply appended
   user ends ── endPracticeSession(POST sessions/{sid}/end)
   later: report + (no audio for typed)  →  Report screen
```

The persona reply is a model call server-side, in character, grounded on the
persona's sealed answer key.

## 6. Spoken-session flow (the interesting one)

Owned by `hooks/useVoiceCall.ts` + `hooks/useStereoRecorder.ts`;
`VoiceSession.tsx` is presentation only.

```
start (modality:"voice") ──▶ /{id}/sessions/{sid} ──▶ VoiceSession
 useVoiceCall:
   1. mintPracticeRealtimeCredential(POST sessions/{sid}/realtime)
        server compiles persona instructions + seals them into an ephemeral credential
   2. getUserMedia(mic)  +  open transport chosen by credential.provider:
        gemini → WebSocket, raw PCM (lib/geminiLive.ts); opening line nudged by one synthetic turn
        openai → WebRTC, SDP offer vs client secret; opening line = response.create as turn 0
   3. conversation runs browser ↔ vendor directly (low latency; SkillBrew not in the media path)
   4. each finalized turn ── appendPracticeTranscript(POST sessions/{sid}/transcript) ──▶ stamped server-side
 useStereoRecorder (in parallel, whole call):
   ChannelMerger(mic left + vendor audio right) → MediaStreamDestination → MediaRecorder
   every ~10 s: appendPracticeRecordingChunk(POST …/recording/chunks?seq=N, multipart)
 hang up:
   endPracticeSession  +  finalizePracticeRecording
   → Report screen can generate report, play/download audio, run analysis
```

**Design rule stated in the code:** *media is peer-to-vendor, truth is
server-side.* The client can't be trusted with the persona's answer key or the
transcript of record, so the server compiles the persona into the credential and
stamps every turn; but the client owns the audio because latency demands it.

The stereo recorder graph feeds **only** the recorder — it does **not** route to
the speakers, so recording never causes echo/feedback in the room.

## 7. Report & analysis flow

- **Report** = a model **judge pass** writes the prose; `report_engine/
  validate.py` vetoes any quote not verbatim in the transcript and any sentence
  that asserts a number. Everything numeric/scored is computed in code, not by
  the model. The report a trainer reads is ~2 pages of plain language; signal
  tables sit behind a `detail` flag.
- The portal shows the engine's **own HTML** in a same-origin iframe (D2b), so
  the on-screen report and the printed PDF are the same bytes.
- **Analysis** is the audio-derived module: `POST …/analyze` → 202, screen polls
  `GET …/analysis` until `complete`, then pulls `…/analysis/full`. If the
  manager's speech isn't detected as English, it returns *not scored* by design
  (`degraded:asr` is the current default — there is no independent ASR adapter
  yet).

## 8. Determinism (why so little is left to the model)

Archetype, verdict, every trait score, scorecard weights, knowledge ceilings,
phase durations, evaluation criteria and weights are **computed in code**, seeded
from `SHA256(interview_id + archetype)`. The model authors only what must be
grounded in the specific job (persona texture, the report prose, the role-fact
*wording*). This is the organizing principle of the whole repo — see
`okf/concepts/determinism.md`. Architecture rules that enforce the layering
(vendor SDKs only in `llm/`, agents never persist, handlers depend on the
narrowest port) are executable tests in `tests/test_architecture.py`.

## 9. Model providers & known operational traps

- Two backends behind `StructuredModel`: **Gemini** (`google-genai`, native
  schema-constrained output, default id `gemini-3.7-flash`) and **OpenAI**
  (`gpt-4o-mini`, schema restated in the system turn).
- ⚠️ **The flash default rate-limits under load.** On a free-tier / low-quota
  Gemini project, `gemini-3.7-flash` returns `429 RESOURCE_EXHAUSTED` (sometimes
  surfaced as `503 UNAVAILABLE`) after a few quick calls; the control plane maps
  that to a **502**, which is what a failing session looks like. A `429` is
  key-shaped so failover tries the next key — but a second free-tier key on the
  same overloaded model doesn't help, and a `503` is **not** classified as
  key-shaped, so it's raised as-is (this is why "failover didn't rescue it").
- **Both fixes are config, no code:** pin a steadier model via `LLM_MODEL` (or a
  per-role `<ROLE>_MODEL`), and give the deployment a key with real quota. Model
  IDs are config precisely so this is a `.env` change. `gemini-2.5-flash` is
  retired (404); `gemini-3.5/3.6-flash` are steadier under load.

## 10. Storage & deployment state (as of 2026-09-11)

- **Storage:** SQLite is the zero-config default; a **PostgreSQL** schema and an
  **object-store port** (filesystem + S3/MinIO adapters) now exist beside it, both
  exercised by `check.sh` under Apple `container` (`migrations (postgres)`,
  `object store (minio)`). Postgres is the intended bridge to the runtime engine.
- **Deployed:** `prod` is live at `https://interview.opsintelai.com` (one EC2
  box). Control plane, `ui/` and the report engine work there; `engined` has
  never started on it, so engine-run voice sessions don't happen in prod — the
  spoken path in production is the **browser-to-vendor** flow documented above.

---

## 11. One-glance sequence (spoken session, full stack)

```
Portal page ─POST sessions──────────────▶ Control plane      (create voice session)
Portal page ─POST sessions/{id}/realtime▶ Control plane      (mint sealed credential)
Browser     ─WS/WebRTC──────────────────▶ Voice vendor       (live audio, both ways)
Browser     ─POST …/transcript──────────▶ Control plane      (each turn, stamped)
Browser     ─POST …/recording/chunks────▶ Control plane      (10 s multipart chunks)
Portal page ─POST …/end, …/finalize─────▶ Control plane      (close + seal recording)
Portal page ─POST …/report{opts}────────▶ Control plane      (judge pass + validate)
Portal page ─GET  /api/…/report.html────▶ Next proxy ─▶ CP   (iframe + print → PDF)
Portal page ─POST …/analyze (202)───────▶ Control plane      (background audio analysis)
Portal page ─GET  …/analysis (poll)─────▶ Control plane      (until complete)
Portal page ─GET  /api/…/recording──────▶ Next proxy ─▶ CP   (audio download)
```
