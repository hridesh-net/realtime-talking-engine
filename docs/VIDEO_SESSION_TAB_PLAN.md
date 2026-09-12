# Interviewer Practice — spoken sessions in their own tab, with video

*Plan v2, 2026-09-12. Scope agreed with the product owner the same day.
Portal only (`skillbrew-organization`, branch `feature/interviewer-practice`);
the control plane in this repo gets a small set of hardening changes. The
standalone console `ui/` is untouched.*

*v2 folds in two independent reviews (Claude Opus 5 and Claude Sonnet 5,
both run against the real trees). What each changed is marked* **[rev]**.
*Where a reviewer was wrong or was overruled, §7 says so.*

## 0. What was asked, in the owner's words

1. "On voice sessions a separate tab should open" — today the session replaces
   the interview page in the same tab (`router.push` to
   `/interviewer-practice/{id}/sessions/{sessionId}`).
2. "This time we need Video as well not just Audio" — clarified as: **show the
   manager's own camera** in the session and **record it** with the session.
   Not in scope: streaming the camera to the persona, or a persona avatar.
3. "Remove Chat session option" — every way to *start* a typed session goes;
   old typed sessions stay readable. UI only; the API keeps `modality: text`.
4. "Camera should be on for every voice session; remove the proctoring
   options — we don't need proctoring."

## 1. Facts this plan rests on (all verified today)

| # | Fact | How verified |
|---|---|---|
| F1 | A single `MediaRecorder` fed a camera track plus the existing merged stereo audio, `video/webm;codecs=vp8,opus`, keeps **two Opus channels** with the left/right split intact; ffmpeg decodes it and `pan=mono\|c0=cN` separates the sides cleanly (left test tone on ch 0, right on ch 1, nine orders of magnitude apart). | Spike in Chrome, 6.95 s clip, `ffprobe`/`ffmpeg` on the upload |
| F1b | **[rev]** The same holds on a ~6.7-minute clip, which is what exercises the analysis agent's real path: `duration_ms` and a `cut()` at `-ss 240` (its `WINDOW_MS` is 240 s). See §1.1 for the measured numbers. | Second spike, 400 s, same page |
| F2 | The chunk endpoint stores whatever `Content-Type` arrives at `seq 0` as the recording's `mime_type`; there is no validation and no `audio/` assumption (`control_plane/api.py:687-705`, `repository.py:516-569`). One recording per session by primary key. | Code read |
| F3 | Nothing downstream reads the container directly: `analysis_agent/audio.py` transcodes every window through ffmpeg to WAV (`-ac 2 -ar 16000`), the report engine never opens the file, `reporting.py` passes an empty path. | Code read |
| F4 | **[rev, corrected]** Of the three ffmpeg call sites, only the `duration_ms` decode fallback (`audio.py:84-89`, output `-f null`) decodes the video stream. `cut()` (`-f wav pipe:1`) and `scripts/transcribe_recording.py` (`.wav` output) never select video — the WAV muxer takes no video stream, and the long spike's stream mapping shows only Opus — so a `-vn` there would be inert. Opus also predicted a **correctness** failure: the fallback takes the *last* `time=` ffmpeg prints, and with a video track longer than the audio (the camera starts first and stops last) that could be the video's length, pushing a window past the audio. On the ffmpeg here (8.0.1) that did **not** reproduce — a fixture with 150 s of video and 100 s of audio reports 1:40 with or without `-vn`. The deployed host runs an unpinned static "release" build from johnvansickle.com (`bootstrap.sh.tftpl:98`), so the version is not the same and the progress-reporting rule has changed between majors. `-vn` on the fallback is therefore kept for two reasons that hold on any version: it skips decoding the video (trivial on a solid-colour canvas, real CPU on 45 minutes of camera footage), and it pins the answer to the audio length by construction. | Opus review; long spike and the two fixtures in §1.1 |
| F5 | `GET /sessions/{id}/recording` and the analyze endpoint read the **whole file into memory** (`repository.py:769-777`; `api.py:775` and `:831`), and analyze then writes a scratch copy to `/tmp` that is never deleted (`api.py:845-846`). Fine at ~30 MB/h of Opus; not fine at video sizes on an 8 GB root volume. | Code read |
| F6 | The portal's chrome comes from exactly one file, `src/app/interviewer-practice/layout.tsx` — nine lines wrapping `<Layout>`. No route groups exist in `src/app/` today. | Code read |
| F7 | The portal's recording proxy (`src/app/api/interviewer-practice/[...path]/route.ts`) forwards GET without `Range` and copies only `Content-Type` / `Content-Disposition`. | Code read |
| F8 | `proctoring` is stored and never enforced anywhere; the OKF gate says "do not wire a camera to it without a retention decision" (`okf/concepts/contracts/interview-record.md:84-87`). The owner has decided: camera unconditional, proctoring removed. Retention is a separate question — see §6. | Code read + owner answer |
| F9 | Starlette 1.6.0 / FastAPI 0.141.1 are what `.venv` holds; `FileResponse` parses `Range`, answers 206 with `Content-Range`, sets `accept-ranges: bytes`, and 416s an unsatisfiable range (`starlette/responses.py:319, 362-418`). Its `content_disposition_type` defaults to `attachment`. `pyproject.toml` only floors `fastapi>=0.110`; there is no lockfile. | `.venv` inspected |
| F10 | `src/proxy.ts` prefix-matches `/interviewer-practice`, so any route beneath it is already an authenticated route; `RouteConfig` needs no new entry. `Sidebar.tsx:139` highlights on `pathname.includes("/interviewer-practice")`. | Code read |
| F11 | `SessionSummary` (`control_plane/schemas.py:376-396`) carries `has_recording: bool` and no mime type; the sessions table cannot know whether a row's recording is video without a schema change. | Code read |
| F12 | Nothing in the feature sets `NavigationGuard`'s dirty flag, so the "leave this page?" guard never engages during a live call today; there is no `beforeunload` either. | grep `setIsDirty` |

Consequence of F1–F3: **the video rides in the same recording, same chunk
protocol, same row.** No schema change, no second artifact, no new endpoint.
The stored `mime_type` becomes `video/webm;codecs=vp8,opus` and the one place
that plays it picks `<video>` or `<audio>` from that.

### 1.1 Long-spike measurements **[rev]**

Same page as F1 (canvas video at 15 fps, 440 Hz left / 880 Hz right through a
`ChannelMergerNode`), `MediaRecorder` `video/webm;codecs=vp8,opus` at
350 kbps, 10 s chunks POSTed in sequence and appended — the production
protocol. 400 s requested.

| Check | Result |
|---|---|
| Stored file | 6.5 MB, `Content-Type: video/webm;codecs=vp8,opus` |
| `ffprobe -show_format` duration | `N/A` — the fallback runs, exactly as for today's audio files |
| Decode fallback, last `time=` | `00:06:40.56` with and without `-vn`; 0.56 s wall clock either way on this trivial video |
| `cut()` at `-ss 240 -t 240` (the agent's second window) | 160.57 s of WAV back (400.56 − 240 = 160.56 ✓); stream mapping lists **only** `opus → pcm_s16le`; 0.29 s |
| Left/right split at 250–252 s | ch 0: 440 Hz at 2.75e17 vs 880 Hz at 9.3e6; ch 1: the reverse. Separation intact four minutes in |
| Fixture, video 150 s / audio 100 s, live WebM (no header duration) | fallback reports `00:01:40.00` with and without `-vn` on ffmpeg 8.0.1 (see F4) |

What the spike cannot show: A/V drift over a real call with a real camera, and
decode cost on real footage. Both are walkthrough checks in WP-D.

## 2. Decisions (one recommendation each — not a menu)

**D1 — The session opens through a launcher route, in a new tab.**
New page `/interviewer-practice/{id}/sessions/start?archetype={key}`
(`start`, not `new`, so it can never shadow a session id **[rev]**). The
Voice button's click handler does one synchronous thing —
`window.open(launcherUrl, "_blank")` — so popup blockers never fire. The
launcher tab:

1. dispatches `resetPracticeSessionFlowState` so a stale rejection from an
   earlier attempt cannot render on mount **[rev]**;
2. loads the interview (`getPracticeInterviewAction`) — the launcher has a
   fresh Redux store and needs `config.duration_minutes` for
   `planned_minutes`, which the session clock renders **[rev]**;
3. shows *Casting {persona}…* with the job title, calls `POST /sessions`
   (voice), stores the new session id in `sessionStorage` under a key derived
   from the launcher URL, and `router.replace`s to the session URL;
4. on reload, finds that key and `router.replace`s to the existing session
   instead of casting again **[rev]** — today's buttons are `disabled` while
   busy, so a double click creates one session, and a reload must not be the
   way to create two.

*Wizard's "Create & talk":* the interview must exist before a session can
start, and an `await` between the click and `window.open` gets blocked. The
wizard therefore opens the launcher route **with no parameters**,
synchronously — it renders a real chrome-free page reading *Preparing your
interview… keep this tab open* — then creates the interview (and, on the
custom-persona path, casts it, which is the tens-of-seconds "Casting…" the
wizard already shows) and finally points the tab at the full launcher URL
with `tab.location.replace(absoluteUrl)`. On failure it closes the tab and
shows the error in the wizard. The wizard tab itself goes to the interview
detail page. **[rev]** — v1 pre-opened `about:blank`, which on the custom
path would have been a blank white tab for the length of a casting call.

**D2 — The session tab is chrome-free, by deleting one file.** **[rev]**
`src/app/interviewer-practice/layout.tsx` goes; the four pages that keep the
chrome (`page.tsx`, `create/page.tsx`, `[id]/page.tsx`,
`[id]/sessions/[sessionId]/report/page.tsx`) wrap their body in `<Layout>`
themselves. The launcher and the live session render without it. No route
groups, no file moves, no existing URL changes, nothing for `npm run build`
to conflict on. The report keeps the chrome: from the ended screen, "Open
report" navigates the session tab to it.

*Leaving the tab.* "Back" becomes **Close**. `window.close()` works on a
script-opened tab (and survives the launcher's `router.replace`); if the tab
was reached any other way — bookmark, restored session — it silently does
nothing, so the button falls back to navigating to the interview page when
`window.opener` is null **[rev]**. While `phase === "live"`, a `beforeunload`
handler asks before the tab is closed, because closing it mid-call drops the
last chunk and never posts `/end`, leaving the session live forever
**[rev]** (F12: there was no such protection before either; the new primary
exit makes it necessary).

**D3 — Camera is acquired separately from the mic, and its failure is not fatal.**
`useVoiceCall` asks for the mic exactly as today, then asks for the camera
(`640×360`, `15 fps`, `facingMode: user`) **before the provider branch**, so
both transports get it **[rev]**. The camera request sits in **its own
`try/catch`** inside `connect()` — the function's single outer `try` turns
any throw into `phase: "error"`, which is right for the mic and wrong for the
camera **[rev]**. Denied or absent camera → the interview proceeds
audio-only and the screen says so in one line. The track lives in a ref next
to `micRef`, is stopped in the `cancelled` branch (the mic already is), in
`finish()` and in the unmount cleanup, and `swapMic` never touches it
**[rev]**. Nothing camera-related may enter the connect effect's dependency
list or the recorder's `useMemo` inputs: a changed identity there re-runs the
effect, whose cleanup closes the call and reconnects with a fresh credential
and a fresh persona greeting **[rev]**.

A self-view tile (`<video muted playsInline>`) sits above the transcript. A
**Camera on/off** button toggles `track.enabled`, like Mute: an off camera
records black frames, which is honest, the same way a muted mic records
silence. No camera device picker in this iteration — one mic picker already
exists and a second selector on the bar was judged not worth its space; the
OS default camera is used, and the `videoinput` filter in `enumerateDevices`
gets a comment saying that is deliberate **[rev]**.

**D4 — One container, video preferred, audio fallback.**
`useStereoRecorder` becomes `useSessionRecorder`. `supported` keeps meaning
exactly what it means today (can this browser record `audio/webm;codecs=opus`
at all) — it gates the audio graph and the Gemini playback context and must
not change **[rev]**. The *upgrade* to video is decided **inside `start()`**
from the track it is handed: given a camera track and
`isTypeSupported("video/webm;codecs=vp8,opus")`, it records
`new MediaStream([cameraTrack, mergedAudioTrack])` at
`videoBitsPerSecond: 350_000`; otherwise today's audio recording; otherwise
none. Chunking, `seq`, retry, give-up and finalize are unchanged. The audio
graph (merger, left = manager, right = persona) is untouched — F1 is what
makes this safe, and the camera never enters Web Audio.

Chunk size grows from ~80 KB to ~500 KB per 10 s. That is a sustained
~400 kbps upload; the serial queue backs up on a slow uplink but the give-up
path only trips on three *failed* POSTs, not on slowness, so the 10 s
interval and the retry constants stay **[rev, considered]**.

Size: ~160 MB per hour of video plus ~30 MB/h of Opus, against ~30 MB/h
today. See D5 and §5.

**D5 — Control plane hardening, no protocol change.**
1. `-vn` on the `duration_ms` decode fallback only (F4), with a **video
   fixture** in the test so it can fail. Not on `cut()` or the transcribe
   script — inert flags fail the repo's own bar.
2. Serve the recording from disk, not memory (F5): `RecordingStore.read_recording`
   is **replaced** by `open_recording(session_id) -> (RecordingMeta, Path)`
   — after this change `read_recording` has no caller and no test, so it is
   deleted from the port, the adapter and the three OKF pages that mention it
   **[rev]**. `GET /sessions/{id}/recording` becomes
   `FileResponse(path, media_type=meta.mime_type, filename=..., content_disposition_type="inline")`
   — the explicit `inline` keeps today's header (F9) **[rev]** — which also
   answers `Range`, so a `<video>` can probe. The analyze endpoint hands the
   agent the real path and **drops the scratch copy**, which also removes the
   never-deleted `/tmp` file **[rev]**.
3. The portal proxy (F7) forwards the request's `Range` header upstream and
   copies `Accept-Ranges` and `Content-Range` back with the upstream status
   (206 or 200); `Content-Length` is left to the runtime on the streamed body
   **[rev]**.

This keeps the local spool as the storage. The object store port
(`control_plane/object_store.py`) is built and unwired; its `open()` returns a
stream, not a path, so when that migration lands the Range answer moves to
the store (presigned or ranged GET) and `open_recording` changes shape. That
is the planned seam, not a surprise **[rev, Sonnet]**.

**D6 — Chat is removed from the portal UI only.**
`PractiseTab`, `CastTab` and both wizard footers lose their Chat buttons;
`WizardAction` becomes `"open" | "voice"`. `components/TextSession/` is
deleted with its test and export, **and so is the Redux tail that only it
used**: `takePracticeTurnAction`, `takePracticeTurnState`, the slice slot and
reducers, the `PracticeTurnRequest` type, and the barrel exports; the two
generic POST-error tests that used that thunk as their vehicle are re-pointed
at another POST thunk so the coverage stays **[rev]**. `LiveSessionScreen`
gains two explicit branches it does not have today: a stored text session →
*"Typed sessions are no longer held live. The transcript is on the interview
page."* with a link back; and a **load failure** → an error notice — today
that case falls through to `<TextSession>` **[rev]**. Strings that assumed
two modalities are rewritten: the sessions table's "Text sessions have no
recording" title, the "Audio & report" header, the raw `{session.modality}`
in `TranscriptPanel`, and the "{n} spoken" stat **[rev]**. The table's *Chat*
label for historic rows stays, because those rows are real. `PracticeModality`
keeps `"text"` because the API still returns it and four test fixtures rely on
it. `index.ts` is marked "frozen after WP1"; removing dead exports from it is
the right exception and this plan says so **[rev]**.

**D7 — Proctoring is removed from the wizard.**
`PRACTICE_PROCTORING`, the wizard field, its yup rule, the `proctoring:` key
in `buildPayload`, and `PracticeInterviewCreateRequest.proctoring` go.
**`PracticeInterview.proctoring` (the response type) stays** — the API keeps
returning it and two test fixtures set it **[rev]**. The control plane's
column keeps its default `"off"` and is not touched in this iteration (a
migration, a console change and a schema re-export, none on the portal's
path); §6 lists it. A repo-wide grep for `proctor` hits the portal's
unrelated assessment/interview proctoring feature — **do not act on those**
**[rev]**.

**D8 — The interview page refreshes itself when the manager comes back.**
`InterviewDetail` re-fetches sessions and candidates on `visibilitychange`
(visible) and `focus`, throttled to once per five seconds.

**D9 — Consent copy says what is now true.**
Connecting screen: *"This call is recorded — your microphone and camera — and
stored with the session. Reports built from it are shared with mentors and
trainers."* Proceeding past it remains the consent event.

**D10 — One player, chosen by mime type.** **[rev, narrowed]**
The only place a recording is *played* today is `VoiceSession`'s ended state;
it becomes `<video controls>` when `recording.mime_type` starts with `video/`,
else `<audio controls>`. The sessions table offers a download link, not a
player, and cannot know the mime (F11): its column becomes **Recording &
report** with a neutral title; no schema change. The report page has no
player and gets none — not asked for.

## 3. Work packages and ToDos

### WP-A — Control plane hardening (this repo, ~half a day)
- [x] A1 `analysis_agent/audio.py`: `-vn` on the decode fallback in `duration_ms`. Test: a live-mode VP8+Opus WebM built in the test from `testsrc` (150 s) and `sine` (100 s) with `-live 1`, asserting `duration_ms` returns the **audio** length. On ffmpeg 8 this passes with or without the flag (F4); it is the behavioural contract the deployed, differently-versioned ffmpeg has to meet, and the docstring says so rather than pretending the flag is what the test guards.
- [x] A2 `control_plane/ports.py` + `repository.py`: `open_recording` replaces `read_recording`; `GET /sessions/{id}/recording` → `FileResponse(..., content_disposition_type="inline")`; analyze passes the path, no scratch copy. Endpoint tests: a `video/webm` seq-0 chunk is stored with that mime and served with it and `inline`; a `Range: bytes=0-9` request gets 206 with `Content-Range`; the existing round-trip tests keep passing.
- [x] A3 OKF: `contracts/session-recording.md` gains "The container may carry a video track" (channel semantics unchanged; what the analysis path does); `contracts/storage-ports.md` and `modules/control-plane-repository.md` lose `read_recording` and gain `open_recording`; `contracts/interview-record.md` records the proctoring outcome and the retention answer from §6; `subsystems/analysis-agent.md` one line; `log.md` entry. `scripts/check.sh` green.

### WP-B — Portal: tab + chrome-free session (~1 day)
- [x] B1 Delete `interviewer-practice/layout.tsx`; wrap the four chrome pages in `<Layout>` (D2). `Sidebar.test.tsx` still passes.
- [x] B2 Launcher page `[id]/sessions/start` per D1 (reset → load interview → cast → replace; `sessionStorage` dedupe; parameterless "Preparing…" state; error state with retry). Utils: `practiceLaunchPath(interviewId, archetype?)`. Tests for all four states.
- [x] B3 `PractiseTab` / `CastTab`: Voice → `window.open(practiceLaunchPath(...), "_blank")` synchronously; `handleStartSession` in `InterviewDetail` goes away. Tests updated with a stubbed `window.open`.
- [x] B4 Wizard "Create & talk" per D1 (pre-opened launcher, absolute URL, close on failure); "Create" alone still routes the current tab to the detail page. Tests.
- [x] B5 `VoiceSession`: Close with opener fallback, `beforeunload` while live, "Open report" once ended, breadcrumb removed. D8 focus refresh in `InterviewDetail`.

### WP-C — Portal: camera + recording (~1 day)
- [x] C1 `useVoiceCall`: camera per D3 (own try/catch, before the provider branch, ref-held, released in cancelled/finish/unmount, never in effect deps); `cameraStream`, `cameraOn`, `toggleCamera`, `cameraNotice` in the hook result.
- [x] C2 `useStereoRecorder` → `useSessionRecorder` per D4: `start(destination, cameraTrack?)` resolves the mime inside; `supported` unchanged. Unit tests for video / audio-fallback / unsupported. Rewrite the existing fixtures that this breaks: the single `getUserMedia` mock must answer audio and video constraints differently, and the "cannot record" case must not rely on `isTypeSupported.mockReturnValueOnce(false)` now that it is asked twice **[rev]**.
- [x] C3 `VoiceSession`: self-view tile, Camera on/off (Phosphor `VideoCamera` / `VideoCameraSlash`), D9 copy, D10 player. CSS Modules with fe-assets tokens only.
- [x] C4 `SessionsTable` column and titles per D10; thunk filename stays `chunk-N.webm`.
- [x] C5 Chat removal (D6) and proctoring removal (D7), complete lists as written there; tests updated; `LiveSessionScreen.test.tsx` gets the error-branch and text-branch cases.

### WP-E — Landing page in the BrewVoice pattern (added 2026-09-12, owner's screenshots)
The owner asked, after WP-A–C were built, that opening Interviewer Practice look
like the BrewVoice dashboard landing, while the interview detail stays as built
(its Cast tab already carries the persona cards, its tiles the per-interview
stats). Research found BrewVoice is legacy global CSS with no `src/ui`
primitives, so the values are ported into CSS Modules rather than its classes,
and that everything the rail needs comes from `GET /interviews` alone
(`created_at`, `status`, `ai_persona`, `config.duration_minutes`), plus the one
org-wide `GET /voice-capability`; sessions and candidates are per-interview
endpoints and are not fetched on the landing.
- [ ] E1 `PracticePageHead` gains an optional icon tile; landing head = icon + "Interviewer Practice" + tagline.
- [ ] E2 `InterviewList`: two-column grid (`1fr 14.75rem`, collapses at 64rem); one filter-bar row on the tab underline — status tabs with count pills (real vocabulary, client-side counts), spacer, search, pill "New interview"; three skeleton cards while loading; dashed centered empty card; `InterviewCard` list unchanged.
- [ ] E3 `InterviewListRail` (same folder, no barrel export), **mirroring the BrewVoice rail block for block** (owner's screenshot, 11:21): hero **Interviews created** card in the agent-card slot (icon tile with rings, all-time count, "n cast with a persona"); **TODAY'S STATS** — per-status counts of interviews created today by `created_at`, average duration, Voice available/off, BrewVoice's row and colour styling; **NEXT INTERVIEW** — nearest future `scheduled_at` with a clock line, else "No upcoming interviews"; **PRACTICE PARTNER CAN** — six static, true capability strings with check icons. **No Latest interviews block** (the owner removed it).
- [ ] E4 Tests for all three; feature and full gates; build.

### WP-D — Gate (~half a day)
- [ ] D1 Both repos: `scripts/check.sh` here; `npm run lint && npm run type-check && npm test && npm run build` in the portal.
- [ ] D2 Browser walkthrough on `localhost:3002` (needs the owner's signed-in session): Voice from Practise tab → new chrome-free tab → camera + mic prompts → self-view live → end → `<video>` plays and seeks → **Close** actually closes → sessions table shows the row after switching back → report opens; wizard "Create & talk" both paths; reload the launcher and confirm no second session. Then `ffprobe` the stored file: two streams, `channels=2`, and **a spoken word near the end lines up with the lips** (A/V drift over a real call is the one thing no spike measures) **[rev]**.
- [x] D3 (owner answered 2026-09-12: **leave at 20 GB for now**; the arithmetic is in `infra/README.md`, no Terraform change) Data volume: `infra/terraform/variables.tf` `data_volume_gb` defaults to 20 GB and that volume also holds the SQLite database — at ~190 MB per session-hour it fills in ~100 session-hours and the control plane stops writing, not just recordings **[rev]**. Owner decides the size; recommendation in the approval message. Not applied without that answer.
- [ ] D4 Update `docs/INTERVIEWER_PRACTICE_UI_FLOW.md` and `docs/INTERVIEWER_PRACTICE_SYSTEM_FLOW.md`; memory updated.

Order: A → B → C → D. B and C can run in parallel on separate agents; they
touch `VoiceSession.tsx` in different places, so one merge.

## 4. What is deliberately not done

- No camera sent to the persona; no persona avatar. Separate plans if wanted.
- No camera device picker. No resolution/bitrate control in the UI.
- No change to the chunk protocol, the `session_recordings` table,
  `RecordingMeta` or `SessionSummary`. `channel_layout` keeps its meaning.
- `proctoring` column and the console's proctoring chips stay (D7).
- Safari: `MediaRecorder` there produces `video/mp4`, not WebM; it falls back
  to today's audio path or to no recording, as today. Chrome/Edge are the
  supported browsers for the portal.
- No object-store migration; see D5's last paragraph.

## 5. Risks and what answers them

| Risk | Answer |
|---|---|
| Popup blocker eats the new tab | `window.open` is the first synchronous call in both click handlers (B3, B4). Verified in the walkthrough, both paths. |
| A camera-dependent value reconnects the call | D3/D4: refs only, mime decided inside `start()`, `supported` unchanged. C2's tests cover the branches; the walkthrough covers the call staying up. |
| Analysis window past the end of the audio | A1's `-vn` plus its video fixture. |
| Disk on the API host | D3 in WP-D; owner decision. |
| `MediaRecorder` WebM has no cues, so seeking is imprecise | True today for audio too. `FileResponse` + `Range` lets the browser probe; exact seeking needs a remux we do not do. |
| Camera permission dialog blocks automation | It is browser chrome; the walkthrough is manual, as WP7 already was. |
| A/V drift over a long call | Walkthrough check in D2. If it drifts, the fix is to start the recorder from the camera track's own `MediaStream` clock; not pre-built. |
| Black frames when camera is off | Intended (D3), documented next to the toggle. |

## 6. Open question for the owner — retention

The OKF gate on cameras was "not without a retention decision". Recordings
today are kept indefinitely and deleted by hand, and that was decided for
stereo audio. Video of a named employee's face, kept indefinitely, is a
different posture. This plan does **not** decide it; A3 records whichever
answer the owner gives. The two honest options: keep "indefinite, manual
deletion" and say so explicitly in the contract, or set a retention period
(which needs a purge job — a follow-up, not this plan).

## 7. Reviewer points not taken, and why

- **Route groups (v1) vs deleting the layout file** — Opus's simpler shape was
  taken; the route-group mechanism was correct but unnecessary.
- **Raise `CHUNK_INTERVAL_MS` for video (Opus)** — not taken; the give-up path
  trips on failed POSTs, not slow ones, and 400 kbps sustained is modest.
  Revisit if the walkthrough shows a backlog.
- **Route `open_recording` through the object store now (Sonnet)** — not
  taken; the store's `open()` returns a stream and cannot answer `Range`. The
  seam is named in D5 instead.
- **Add `-vn` to `cut()` and the transcribe script (v1, Sonnet agreed)** —
  dropped after Opus showed the WAV muxer never maps video; an inert flag with
  a test that cannot fail is exactly what this repo forbids.
- **Sonnet's suggestion that the launcher pass `planned_minutes` in the
  query** — the launcher loads the interview instead; it needs the title for
  its own screen anyway, and a query value can be edited.

## 8. Follow-ups outside this plan

- Drop `proctoring` from `InterviewCreateRequest`, the tables (migration
  `0002`), the console wizard and the exported schemas.
- Retention/deletion job, once §6 is answered.
- Wire recordings to the object store (`storage-ports.md`) — designed, unbuilt,
  and now more urgent.
- Pin Starlette (F9): `pyproject.toml` floors FastAPI only; a fresh install
  elsewhere could resolve an older `FileResponse`.
