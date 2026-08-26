---
type: Contract
title: Realtime voice
description: The RealtimeBroker port, the ephemeral credential, and the browser-to-vendor media path that keeps the persona code-owned.
resource: /llm/base.py
tags: [contract, voice, realtime, webrtc, openai, security]
generated:
  by: claude-opus-5/okf-curator
  at: "2026-08-23T19:30:00Z"
verified:
  - by: claude-opus-5
    at: "2026-08-23T19:30:00Z"
  - by: claude-opus-5/okf-curator
    at: "2026-08-22T18:20:00Z"
status: stable
sources:
  - resource: /llm/base.py
  - resource: /llm/openai_realtime.py
  - resource: /candidate_agent/voice.py
  - resource: /control_plane/api.py
  - resource: /ui/src/VoiceSessionView.jsx
---
# Realtime voice

```python
@dataclass(frozen=True)
class RealtimeCredential:
    value: str          # ephemeral secret, one session, expires
    expires_at: int     # unix seconds
    model: str
    call_url: str       # where the browser posts its SDP offer

class RealtimeBroker(ABC):
    def __init__(self, model_id: str) -> None
    @property def model_id(self) -> str
    @property @abstractmethod def provider(self) -> str
    @property @abstractmethod def voices(self) -> tuple[str, ...]
    @abstractmethod
    async def mint(self, *, session: dict[str, Any],
                   ttl_seconds: int) -> RealtimeCredential
```

## The shape of the thing

**The live call never touches this service.** The browser holds a WebRTC
session with the vendor directly. Routing 24 kHz PCM through Python would add
hundreds of milliseconds to a budget measured in hundreds of milliseconds, and
a spoken interview that lags is not a spoken interview. This is still exactly
true of the real-time path — nothing here changed it.

What did change: the browser now also **records** the call — both the
manager's mic and the persona's remote track, merged to stereo — and uploads
it to this service in 10-second chunks, *out of band* from the WebRTC media
path and off the latency budget above. That upload is not part of the live
call; it happens after each chunk is already captured, on its own queue, and a
slow or failed upload never touches the conversation itself. See
[Session recording](/concepts/contracts/session-recording.md) for the chunk
protocol, the channel layout, and why the browser — not this service, not the
Go engine — is the one holding the audio to record it from.

```
browser ──── WebRTC audio ────► OpenAI Realtime
   │                                  ▲
   │ POST /sessions/{id}/realtime      │ Authorization: Bearer <ephemeral>
   ▼                                  │
control plane ── mint(session) ───────┘
   │  compiles instructions, voice, turn detection
   └─ POST /sessions/{id}/transcript  ◄── browser reports each finalised turn
```

So: **media is peer-to-vendor, truth is server-side.** The control plane keeps
the two things that must not be client-controlled — the compiled persona and the
transcript — and gives up the one thing it has no business holding, the audio.

## Why this is a broker and not a third model port

`mint` is not a way to call a model; nothing in this repo ever receives a token
from it. It pushes *configuration* — persona instructions, voice, turn detection
— into a credential someone else redeems.
`test_isp_the_realtime_broker_is_not_a_model_port` asserts it neither subclasses
nor exposes anything from [`StructuredModel`](/concepts/contracts/structured-model.md)
or [`ChatModel`](/concepts/contracts/chat-model.md).

## What the browser is never given

The response ([`RealtimeCredentialResponse`](/concepts/contracts/session-transcript.md))
carries `client_secret`, `expires_at`, `model`, `call_url`, and `voice`. It does
**not** carry `instructions`. The persona prompt — with its knowledge ceilings,
its unlock condition, and its forbidden behaviours — is sealed into the minted
credential vendor-side. A client that could read those could also edit them, and
the interviewer would be practising against a persona they had configured
themselves.

The credential's TTL is `REALTIME_TTL_SECONDS = 600`: long enough for a slow page
load plus a microphone permission prompt, short enough that a leaked one is
worthless by the time anyone finds it.

## Vendor facts, verified live 2026-08-22

Against the project's own key, not from memory:

| | |
|---|---|
| Mint | `POST https://api.openai.com/v1/realtime/client_secrets` with `{expires_after: {anchor, seconds}, session: {...}}` |
| Redeem | `POST https://api.openai.com/v1/realtime/calls`, `Authorization: Bearer <value>`, `Content-Type: application/sdp`, body = raw SDP offer, returns the SDP answer |
| CORS | The calls endpoint returns `access-control-allow-origin: *` and allows `authorization, content-type`, so the browser may post directly |
| Data channel | `oai-events` |
| Voices | `alloy ash ballad cedar coral echo marin sage shimmer verse` — all ten accepted |
| Models | `gpt-realtime-2` (default), `gpt-realtime-2.1`, `gpt-realtime-2.1-mini`, `gpt-realtime-mini` |

Data-channel events this repo reads:

| Event | Becomes |
|---|---|
| `conversation.item.input_audio_transcription.delta` / `.completed` | the **manager's** turn (`.transcript`) |
| `response.output_audio_transcript.delta` / `.done` | the **candidate's** turn (`.transcript`) |
| `input_audio_buffer.speech_started` / `.speech_stopped` | the "hearing you" indicator |
| `error` | surfaced to the operator |

Note the asymmetry: the user's transcription finalises on `.completed`, the
assistant's on `.done`. There is no `.done` for input audio.

## The honest limitation

This is **Speaker-only**. The vendor's realtime model both decides what the
persona knows and says it, with the knowledge ceiling carried only as prompt
text. There is no deterministic pre-gate, no claims ledger, and no false-belief
injection — those are the whole point of the Go
[live-session engine](/concepts/subsystems/engine.md)'s Thinker, which is still
parked at Phase 0.

Practical consequence: **a voice persona can be argued above its knowledge
ceiling more easily than a text one**, because nothing outside the prompt is
enforcing it. Text sessions run the same prompt but at a temperature and cadence
that make drift easier to spot. Treat voice as the realism path and text as the
fidelity path until the engine lands.

## Adding a provider

Unlike the text tables, `REALTIME_PROVIDERS` is **deliberately partial** — see
[`llm/factory.py`](/concepts/modules/llm-factory.md). A provider without a
realtime implementation simply has no Voice button; `GET /api/v1/voice-capability`
reports that as a configuration answer rather than an error.

To add one: implement `RealtimeBroker`, add a row to `REALTIME_PROVIDERS` and
`DEFAULT_REALTIME_MODEL_IDS`, and advertise its `voices`. If that vendor's
session document differs in shape from OpenAI's, that is the moment to split
[`candidate_agent/voice.py`](/concepts/modules/candidate-agent-voice.md) behind a
neutral schema — not before.

## Related

[candidate_agent/voice.py](/concepts/modules/candidate-agent-voice.md) ·
[Session transcript](/concepts/contracts/session-transcript.md) ·
[Session recording](/concepts/contracts/session-recording.md) ·
[Run an interview](/concepts/runbooks/run-an-interview.md) ·
[Live-session engine](/concepts/subsystems/engine.md)
