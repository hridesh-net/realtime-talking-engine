---
type: Runbook
title: Run an interview
description: Conduct a live interview against a persona — typed or spoken — browser flow, curl flow, and what to check when it misbehaves.
resource: /control_plane/api.py
tags: [runbook, session, interview, ui, curl]
generated:
  by: claude-opus-5/okf-curator
  at: "2026-08-22T17:05:00Z"
verified:
  - by: claude-opus-5/okf-curator
    at: "2026-08-22T17:05:00Z"
status: stable
sources:
  - resource: /control_plane/api.py
  - resource: /ui/src/SessionView.jsx
  - resource: /candidate_agent/session.py
  - resource: /ui/src/VoiceSessionView.jsx
---
# Run an interview

You play the hiring manager. A cast persona plays the candidate. Every turn is
stored with a server-side timestamp, because that transcript is what the
evaluation layer will read.

## In the browser

```bash
.venv/bin/python -m control_plane.main    # :8081 — start this first
cd ui && npm run dev                      # :3000
```

1. Create an interview (or **Select** an existing one).
2. Scroll to **Enroll virtual candidates**. Every archetype card carries **Chat** and **🎙 Voice** — so does every already-enrolled candidate card.
3. Click either. An un-enrolled archetype is cast first (~15s, the button reads *Casting…*); an enrolled one starts immediately.

**Chat** — the console is replaced by the chat view, the persona's opening line
already there. **Enter** sends, **Shift+Enter** breaks the line.

**🎙 Voice** — Chrome asks for microphone access the first time; **you have to
click Allow yourself**, it is browser chrome and nothing in the app can grant it.
Then just talk. There is no push-to-talk, and you can interrupt the persona
mid-sentence — that is deliberate, since interrupting a rambler is one of the
skills being trained. **Mute** stops the persona hearing you without dropping the
call.

Either way, **End interview** closes the session and leaves the stored transcript
on screen; **Back** returns to the console.

Two ports, one prerequisite: Vite proxies `/api` to `127.0.0.1:8081`, so a
`Failed to fetch` in the UI almost always means the API is not running.

## By curl

```bash
IV=$(curl -s localhost:8081/api/v1/interviews | jq -r '.[0].id')

SID=$(curl -s -X POST localhost:8081/api/v1/sessions \
  -H 'Content-Type: application/json' \
  -d "{\"interview_id\":\"$IV\",\"archetype\":\"nervous_fresher\",\"planned_minutes\":20}" \
  | jq -r .id)

curl -s -X POST localhost:8081/api/v1/sessions/$SID/turns \
  -H 'Content-Type: application/json' \
  -d '{"text":"Walk me through your last role."}' | jq

curl -s -X POST localhost:8081/api/v1/sessions/$SID/end | jq .status
curl -s localhost:8081/api/v1/sessions/$SID | jq '.turns[] | {index, speaker, elapsed_ms}'
```

Archetype keys come from `GET /api/v1/candidate-archetypes`.

### Voice, by curl

You cannot hold the call from a shell — WebRTC needs a browser — but you can
check every step up to it:

```bash
curl -s localhost:8081/api/v1/voice-capability | jq
# {"available": true, "providers": ["openai"], "detail": "voice ready via openai"}

SID=$(curl -s -X POST localhost:8081/api/v1/sessions -H 'Content-Type: application/json' \
  -d "{\"interview_id\":\"$IV\",\"archetype\":\"rambler\",\"modality\":\"voice\"}" | jq -r .id)

curl -s -X POST localhost:8081/api/v1/sessions/$SID/realtime | jq 'del(.client_secret)'
# {"session_id": ..., "expires_at": ..., "model": "gpt-realtime-2",
#  "call_url": "https://api.openai.com/v1/realtime/calls", "voice": "verse"}
```

A voice session starts with `turns: []` — the persona *says* its opening line and
the browser reports it back through `POST /sessions/{id}/transcript`.

## When it misbehaves

| Symptom | Cause |
|---|---|
| `409 session is completed, not live` | The session was ended. Start a new one; re-opening is refused on purpose. |
| `410 the persona for this session has been deleted` | The candidate was removed underneath a live session. The transcript survives; the session cannot continue. |
| `422 unknown archetype` | Key not in the catalog — check `GET /api/v1/candidate-archetypes`. |
| `ModelError: no provider credentials found` | `.env` has no `GEMINI_API_KEY` / `OPENAI_API_KEY`. See [Dev setup](/concepts/runbooks/dev-setup.md). |
| Replies contain `*sighs*` or stage directions | The text-mode preamble is being ignored or was edited. See [session.py](/concepts/modules/candidate-agent-session.md). |
| The persona is too polished for its archetype | A casting problem, not a session one — check the traits on the candidate card, then the archetype's bounds. |
| **🎙 Voice** is greyed out | No realtime provider. The reason is printed beside the persona list; `GET /api/v1/voice-capability` says the same thing. Set `OPENAI_API_KEY`. |
| `502` from `/realtime` | The vendor refused the mint — usually the key lacks Realtime access, or `VOICE_MODEL` names a text model instead of a realtime one. The detail carries their message. |
| Voice call connects, no audio | Check the browser gave microphone permission, and that the tab is not muted. `output_audio_buffer.started` on the data channel means the persona is speaking even if you cannot hear it. |
| Voice transcript is missing turns | Only finalised transcripts are stored — greyed italic text on screen has not been persisted yet. A `transcript not saved` banner means the POST failed. |
| The voice persona answers above its knowledge ceiling | Known Speaker-only limitation: in voice mode the ceiling is prompt text with nothing enforcing it. See [Realtime voice](/concepts/contracts/realtime-voice.md). Reproduce in **Chat** to confirm whether the persona or the modality is at fault. |

Latency is one model round trip per turn: roughly 2–8s on `gemini-2.5-flash`.
Point `SESSION_PROVIDER` / `SESSION_MODEL` at something else to trade cost
against pace without touching the casting or expectation calls.

## What is not here yet

No report. Ending a session stores the transcript and stops — the evaluation
layer (deterministic signals, judge pass, analytical report) is Phase 4 of the
pivot plan. No session list, no resume-by-id in the UI, and no timeout sweep, so
`status = "abandoned"` is never set.

On the voice side specifically: no recording is kept (only the transcript), no
timing telemetry is extracted, and the persona is **Speaker-only** — the
knowledge-ceiling enforcement, false-belief gating and claims ledger all live in
the Go engine's Thinker, which is still parked at Phase 0.

## Related

[Create an interview](/concepts/runbooks/create-an-interview.md) ·
[Realtime voice](/concepts/contracts/realtime-voice.md) ·
[Session transcript](/concepts/contracts/session-transcript.md) ·
[REST API § Sessions](/concepts/contracts/rest-api.md) ·
[Test UI](/concepts/subsystems/ui.md)
