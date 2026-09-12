# Interviewer Practice — UI & user flow

*How the feature works from the user's seat: what they see, what they click, and
where each screen leads. For the machinery behind it, see
[INTERVIEWER_PRACTICE_SYSTEM_FLOW.md](./INTERVIEWER_PRACTICE_SYSTEM_FLOW.md).*

> Written 2026-09-12 against the ported feature in
> `skillbrew-organization/src/features/interviewer-practice` and the control
> plane in this repo. Screen names are the real components.

---

## What this is, in one line

A **training rig for interviewers**. The product casts a virtual candidate with
a hidden personality and an answer key; a *human* plays the interviewer against
it, typed or spoken; afterwards the human gets a report on how they interviewed.
The candidate is the sparring partner — **the human is the one being assessed.**

It lives inside the SkillBrew Organization portal as one sidebar tab,
**"Interviewer Practice"**, and reaches the interview-watcher control plane over
HTTP behind the portal's normal sign-in.

---

## Who gets in

The tab and every screen under it are gated by `ProtectedRoutes` with the
`InterviewerPractice` permission set. A signed-in org member with the interview
permission sees the tab; anyone else never reaches it. There is no separate
login for this feature — it rides the portal's SkillBrew session.

---

## The map

```
Sidebar ▸ Interviewer Practice
│
├─ /interviewer-practice ............... Interview list        (all practice interviews)
│   └─ [+ New interview] ────────────┐
│                                     ▼
├─ /interviewer-practice/create ....... Interview wizard       (one long form → creates one interview)
│
└─ /interviewer-practice/{id} ......... Interview detail       (four tabs)
    │   Tabs:  Sessions · Practise · Cast · Compose
    │
    ├─ start a session ──────────────┐
    │                                 ▼
    ├─ /{id}/sessions/{sessionId} ..... Live session           (typed OR spoken, decided by the session)
    │
    └─ /{id}/sessions/{sessionId}/report  Report               (the write-up + audio + analysis)
```

---

## Screen 1 — Interview list

The landing screen. A card per practice interview: job title, status badge
(*Scheduled / In progress / Completed / Failed / Cancelled*), and a way in.

- **What the user does:** scans existing interviews, opens one, or clicks
  **New interview** to build one.
- **Where it goes:** a card → the detail screen; the button → the wizard.

## Screen 2 — Interview wizard (`/create`)

One form that defines *what* the interview is. The user fills:

- **Job title** and **Job description** — the only two required fields.
- **Location**, **Department** (free text, with suggestions like Sales /
  Network / Engineering), **Manager level**.
- **Language** — English (Indian) / Hinglish / Hindi.
- **Proctoring** — Off / Identity check / Full.
- Job location type, experience level, company type, and a **duration** (default
  20 min).
- **Persona notes** — free-text steer for the candidate persona.

Two assists on this screen:

- **Draft the role-fact checklist from the JD** — the user can have the model
  *draft* the six role facts a good interviewer should disclose (Targets,
  Shifts, Location, Compensation, Growth path, Next steps). Nothing is saved
  from the draft; the user edits the drafts, and the checklist itself is fixed
  in code — the draft only fills in the wording.
- **Persona composer / picker** — optionally line up who they'll practise
  against right from the wizard.

On submit the interview is created and the user lands on its **detail** screen.

## Screen 3 — Interview detail (`/{id}`)

The hub for one interview. A header (title + status badge, back arrow) over four
tabs:

| Tab | What it's for |
|---|---|
| **Sessions** | Every practice run against this interview, with status and a link to each report. This is the history. |
| **Practise** | Pick a persona *type* and start immediately. Each start casts a **fresh person** of that type — a different individual every time. Buttons: **Chat** (typed) and, when voice is available, a mic option. **Cast only** creates the persona without starting. |
| **Cast** | The personas already cast for this interview, as cards (name, archetype, traits, past verdict). Start a **Chat** or **spoken** session against a specific one, or remove one. |
| **Compose** | Hand-build a custom persona (traits, notes) instead of drawing an archetype from the catalog. |

A **"Voice off"** notice appears on the Practise/Cast tabs when the server
reports voice isn't available, so the mic buttons never look broken.

**Starting a session** (from Practise or Cast) creates a live session and routes
the user straight into it. The session remembers whether it's typed or spoken —
so a refresh lands on the right screen.

## Screen 4 — Live session (`/{id}/sessions/{sessionId}`)

One URL, two faces. The screen loads the session, reads its **modality**, and
renders one of:

### Typed session (`TextSession`)
A chat view. The **user types the interviewer's turns**; the candidate persona
replies in character. The user drives the whole interview — asks, probes,
follows up — then **ends** the session. The transcript is the record.

### Spoken session (`VoiceSession`)
A live call:

1. On open, the screen asks for the **microphone** and opens the call. The
   persona **speaks first** with its opening line.
2. The user talks; the persona answers in a voice fixed per-persona. A
   **"hearing you"** indicator lights while the user speaks; interim captions
   show both sides.
3. Controls: **mute**, a **mic picker**, noise-suppression toggle, and
   **hang up**.
4. The whole call is **recorded in the browser** (both voices, two channels)
   while it runs — the user doesn't do anything to make that happen.
5. On hang-up the call ends, the recording finalizes, and the transcript below
   is the stored record. A **Download** control offers the audio.

> The spoken call's audio goes **browser ↔ voice vendor directly** for
> conversational latency; it never streams through SkillBrew. What SkillBrew
> keeps is the transcript and the browser's own recording.

## Screen 5 — Report (`/{id}/sessions/{sessionId}/report`)

What the trainer came for. For a finished session:

- If no report exists yet, a **Generate report** button; it can be
  **regenerated** with options.
- The report body is the **report engine's own HTML**, shown in an iframe —
  the same document the user downloads, so screen and file can't drift.
- **Readiness** and scores are colour-toned (green ≥ 65, amber ≥ 45, else low).
- **Download PDF** = the browser printing that very iframe.
- The audio is offered as a **download**.
- An **Analysis panel** shows the audio-derived analysis: it kicks off in the
  background, shows *Analysing…* while it runs, then the result. If the
  manager's speech wasn't detected as English, the screen says so plainly —
  *"Nothing was scored rather than scored wrongly."*

---

## The happy path, end to end (user's words)

1. Open **Interviewer Practice**.
2. **New interview** → fill the job, optionally draft the role facts → **Create**.
3. On the detail screen, go to **Practise**, pick a persona, click **Chat** (or
   the mic).
4. Run the interview — type your questions, or talk. End / hang up.
5. Open the **report**, read the write-up, play or download the audio, print to
   PDF.

Everything a trainer needs is those five steps; the rest of the tabs are for
managing personas and re-running.

---

## Things worth knowing as a user

- **A code change is not the same as a config change.** If voice or a model
  looks down, it's usually the deployment's API key/quota, not the screens —
  see the system-flow doc's "known operational traps".
- **Each "Practise" start is a new person.** Practising the same archetype twice
  gives two different individuals, on purpose — you're rehearsing a *type*, not
  memorising one script.
- **The report is about the interviewer.** Scores, readiness and the prose all
  judge how the *human* ran the session, not how the persona "did".
