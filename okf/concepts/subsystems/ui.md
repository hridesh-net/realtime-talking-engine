---
type: Subsystem
title: Test UI
description: The React + Vite console, aligned to the SkillBrew.AI design mockup — shell, wizard, persona picker, sessions table, and the two session views.
resource: /ui
tags: [ui, react, vite, frontend]
generated:
  by: claude-opus-5/okf-curator
  at: "2026-08-21T19:17:54Z"
verified:
  - by: claude-opus-5/okf-curator
    at: "2026-08-22T18:55:00Z"
status: stable
sources:
  - resource: /ui/src/api.js
  - resource: /ui/src/App.jsx
  - resource: /ui/src/VoiceSessionView.jsx
  - resource: /ui/src/SessionView.jsx
  - resource: /ui/src/Shell.jsx
  - resource: /ui/src/Wizard.jsx
  - resource: /ui/src/PersonaPicker.jsx
  - resource: /ui/src/InterviewList.jsx
  - resource: /ui/src/InterviewDetail.jsx
  - resource: /ui/vite.config.js
  - resource: /ui/package.json
---
# Test UI

`ui/` — React 18 + Vite 5, no framework beyond that, no state library, no
TypeScript.

**The design source of truth is `interview_training_wizard (1).html`** at the
repo root — a static mockup of the SkillBrew.AI console. `src/index.css` is a
port of its stylesheet with the **class names kept identical**, so a change to
the mockup can be diffed against the sheet. Design tokens: `--blue #0555C8`,
`--orange #DA6220`, Open Sans, 12px radius, pill buttons.

The mockup describes the *finished* product. Three of its screens are
deliberately **not** built, because no endpoint produces their data: the manager
cohort with readiness scores and bias flags, the report-section configuration,
and the CSV manager upload. Its "report covers" card also carries a
critical-fail gate on Fair & Inclusive — **do not port that**; it contradicts
the standing decision that no criterion has a hard limit. Where the mockup shows
a number this service cannot produce, the tile shows `—` and says why.

```bash
cd ui && npm install && npm run dev     # http://localhost:3000
```

Vite proxies `/api` → `http://127.0.0.1:8081`, so **start the API first**.

## Files

| File | Screen | Data |
|---|---|---|
| `src/api.js` | Thin `fetch` wrapper over `/api/v1`, one function per endpoint; unwraps FastAPI's `detail` into `Error.message` | — |
| `src/App.jsx` | Screen switch over `'list' \| 'create' \| 'detail' \| 'session'` in one `useState`. A router would be a dependency to express `if` | all loaders |
| `src/Shell.jsx` | Icon rail, topbar, breadcrumbs, footer | none |
| `src/InterviewList.jsx` | Landing screen: interview cards, status tabs, search | `GET /interviews` |
| `src/Wizard.jsx` | Two-step new interview: Basics, then the picker | `POST /interviews` |
| `src/PersonaPicker.jsx` | `.plist` + sticky `.detail` — traits, beats, stress bars | `GET /candidate-archetypes` |
| `src/InterviewDetail.jsx` | Tabs: Sessions (table + transcript panel), Practise, Cast | candidates + `GET /interviews/{id}/sessions` |
| `src/SessionView.jsx` | The typed interview | session endpoints |
| `src/VoiceSessionView.jsx` | The **spoken** interview — WebRTC to the vendor | realtime + transcript |
| `src/index.css` | Ported mockup stylesheet | — |

`api.js` covers the interview, expectation, archetype, candidate, and session
endpoints. It does **not** cover the engine-contract or scorecard endpoints —
those are for the Go engine and the grading pipeline, not the operator.

## The wizard

Step 1 renders **every** field the training-wizard specification asks for:
job title, location, job description, department (the mockup's combo box),
manager level, duration, skills, the language the candidate opens in, and
proctoring. All are real fields on `InterviewCreateRequest`.

Two carry help text that says what they actually do, because both could
otherwise be mistaken for decoration:

* **Language** — *"Reaches the persona's prompt and the speech-to-text hint, not just this label."*
* **Proctoring** — *"Recorded on the interview. **No camera is accessed yet** at any setting."* Saying so on screen is the point; a proctoring control that silently does nothing is worse than no control.

Step 1 also holds the **role-fact checklist**: six fixed fields, an
`✨ Auto-fill from the job description` button calling `POST /role-facts`, and a
banner explaining why the list is fixed. A blank field drops that fact from the
interview's checklist, and the section header counts what remains — *"3 of 6 on
this interview's checklist"*.

The **Additional notes for the candidate** textarea sits on step 2, beneath the
picker, exactly where the specification puts it, with help text stating what it
cannot do.

## The persona picker

Everything in the detail panel comes from `GET /candidate-archetypes`:
`label`/`description` in the header, `trait_bounds` as ranges, `session_beats`
as the run list, `stresses` as the bars, `tags` as pills. The rubric labels come
from the same response (`rubric_criteria`), not from a UI-side copy.

The one thing that lives in the UI is the emoji per key (`ICONS` in
`PersonaPicker.jsx`) — presentation, so it does not belong in the domain
catalog. An unmapped key still renders, with a fallback glyph.

The run-list heading is **"What they tend to do"**, not "what they'll do". Beats
are model-mediated through casting; see
[archetypes.py](/concepts/modules/candidate-agent-archetypes.md).

## The sessions table

The mockup's version of this screen is a manager cohort with readiness, bands
and bias flags. There is no manager roster and no evaluation layer, so the table
lists what does exist — the sessions held — with columns Candidate / Mode /
Turns / Started / Status, and the right-hand panel shows the stored transcript
instead of a report. The fourth stat tile reads **Readiness —, "no evaluation
layer yet"** rather than being omitted, so the gap is visible rather than
silently missing.

Interview status badges use the real vocabulary from `control_plane/database.py`
(`scheduled | in_progress | completed | failed | cancelled`), not the mockup's
running/draft/archived — a tab that can never match anything is worse than no
tab.

## Conducting an interview

**Chat** and **🎙 Voice** sit on the persona detail panel (both in the wizard's
step 2 and the detail screen's Practise tab) and on every cast candidate card.
Both call `POST /sessions` — differing only in `modality` — which casts the
persona first if that archetype is not yet enrolled, so an untouched interview
goes from "pick a persona" to "talking to them" in one click, at the cost of a
~15s casting call (the button reads *Casting…*).

The wizard's step 2 goes further: **Create & chat** / **🎙 Create & talk**
create the interview and open the session in one action, so a first-time user
reaches a live conversation without visiting the detail screen at all.

The Voice button is enabled from `GET /api/v1/voice-capability`, asked once at
mount. When voice is unconfigured the button is disabled **and the reason is
printed** next to the persona list — a greyed-out control with no explanation is
the thing an operator files a bug about.

`App.jsx` renders the session view **instead of** the console, not beside it —
inside the shell, so the breadcrumb still says where you are. An interview
conducted with a job-spec form in peripheral vision is not the exercise being
trained. Leaving the session refreshes both the candidate list and the sessions
table, since a session may have cast a persona on the fly and is itself a new
row.

`VoiceSessionView` notes:

* **The audio does not pass through our API.** It mints a credential, opens a `RTCPeerConnection` to the vendor, and streams mic in / persona out directly. See [Realtime voice](/concepts/contracts/realtime-voice.md).
* Transcript POSTs are **chained, not parallel** (`queueRef`). The server assigns each turn's index on arrival, so two in flight at once could land out of order and mis-sequence the stored conversation.
* Ending the call awaits that queue **before** `POST /end` — a turn posted after the session closes would 409 and vanish from the record.
* Interim (`.delta`) transcripts render greyed and italic; only `.completed` / `.done` are persisted. What you see mid-sentence is not yet in the database.
* The mic track is toggled via `track.enabled` rather than being stopped, so unmuting does not re-trigger the browser permission prompt.
* First use raises Chrome's microphone permission dialog. That is browser chrome, not page UI — nothing in the app can pre-grant it.

`SessionView` notes:

* The transcript on screen is the **server's** transcript — each turn arrives with its own index and `elapsed_ms`. The one exception is the manager's own line, echoed optimistically and rolled back (with the text restored to the composer) if the turn call fails.
* Enter sends, Shift+Enter breaks the line. Reaching for a button between every question kills interview pace.
* Ending the session swaps the composer for the stored-record notice; the transcript stays on screen.

## Notes

* `ui/` is excluded from ruff and mypy; there is no JS lint or test setup.
* `node_modules/` and `ui/dist/` are gitignored; `package-lock.json` is committed.
* The AI-calling actions are slow and each shows its own pending state: *Generating…*, *Casting…*, and the session's *typing…* bubble. Enrollment is one serial model call per archetype; a session turn is one call round trip (~2–8s on `gemini-2.5-flash`).
* Sessions are now **listed** on the detail screen, but there is no *resume*. Closing the tab loses the live connection; the transcript is still stored and readable from the table. For a voice session the call is gone — a WebRTC peer connection is not re-establishable from a reload, so a reopened live session shows its transcript and nothing else.
* Open Sans is loaded from Google Fonts in `index.html`. It is the only external request the UI makes, and the stack falls back to `system-ui` offline.
* No JS test setup, so both session views are covered only by the Python endpoint tests plus manual use.
