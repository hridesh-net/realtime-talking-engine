---
type: Contract
title: Realtime voice
description: The RealtimeBroker port, the ephemeral credential, and the two browser-to-vendor media paths (Gemini Live over WebSocket, OpenAI Realtime over WebRTC) that keep the persona code-owned.
resource: /llm/base.py
tags: [contract, voice, realtime, webrtc, websocket, gemini, openai, security]
generated:
  by: claude-opus-5/okf-curator
  at: "2026-08-23T19:30:00Z"
verified:
  - by: claude-opus-5
    at: "2026-09-01T00:00:00Z"
  - by: claude-opus-5
    at: "2026-08-23T19:30:00Z"
  - by: claude-opus-5/okf-curator
    at: "2026-08-22T18:20:00Z"
status: stable
sources:
  - resource: /llm/base.py
  - resource: /llm/gemini_live.py
  - resource: /llm/openai_realtime.py
  - resource: /candidate_agent/voice.py
  - resource: /control_plane/api.py
  - resource: /ui/src/VoiceSessionView.jsx
  - resource: /ui/src/geminiLive.js
---
# Realtime voice

```python
@dataclass(frozen=True)
class RealtimeCredential:
    value: str          # ephemeral secret, one session, expires
    expires_at: int     # unix seconds
    model: str
    call_url: str       # where the browser posts its SDP offer;
                        # empty for providers whose SDK owns the endpoint

class RealtimeBroker(ABC):
    def __init__(self, model_id: str) -> None
    @property def model_id(self) -> str
    @property @abstractmethod def provider(self) -> str
    @property @abstractmethod def voices(self) -> tuple[str, ...]
    @abstractmethod
    async def mint(self, *, session: dict[str, Any],
                   ttl_seconds: int) -> RealtimeCredential
```

## Two providers, one contract

Since 2026-09-01 there are **two talkers**, and which one runs is configuration:

| | **gemini** (default) | **openai** |
|---|---|---|
| Broker | `llm/gemini_live.py` | `llm/openai_realtime.py` |
| Model | `gemini-3.1-flash-live-preview` | `gpt-realtime-2` |
| Transport | WebSocket, opened by `@google/genai` | WebRTC, SDP offer/answer |
| Credential | ephemeral **auth token**, passed as the JS SDK's `apiKey` | ephemeral **client secret**, `Authorization: Bearer` |
| `call_url` | **empty** — the SDK owns the endpoint | `https://api.openai.com/v1/realtime/calls` |
| Audio | raw PCM: 16 kHz mono up, 24 kHz mono down, base64 | Opus over RTP, negotiated |
| Transcripts | the model transcribes both sides in-session | a separate STT model (`TRANSCRIBE_MODEL`) for the manager |
| Session cap | ~15 minutes audio-only; resumes across it | none observed |
| Browser config | passes `client_config` on connect; constrained fields are enforced server-side | none — everything is sealed in the secret |

`build_realtime_broker` auto-detects by taking the first row of
`REALTIME_PROVIDERS` whose key is present, and **gemini leads the table**, so a
deployment with both keys talks through Gemini Live. `VOICE_PROVIDER=openai`
keeps the WebRTC path.

## The shape of the thing

**The live call never touches this service.** The browser holds the session
with the vendor directly. Routing 24 kHz PCM through Python would add hundreds
of milliseconds to a budget measured in hundreds of milliseconds, and a spoken
interview that lags is not a spoken interview. This is still exactly true of
both real-time paths — the second provider did not change it.

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
browser ─ WS: PCM 16k up / 24k down ─► Gemini Live      (default)
        └ WebRTC: SDP + Opus ────────► OpenAI Realtime  (VOICE_PROVIDER=openai)
   │                                        ▲
   │ POST /sessions/{id}/realtime            │ ephemeral token / bearer secret
   ▼                                        │
control plane ── mint(session) ─────────────┘
   │  compiles instructions, opening line, voice, turn detection
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

The response ([`RealtimeCredentialResponse`](/concepts/contracts/rest-api.md))
carries `client_secret`, `expires_at`, `model`, `provider`, `call_url`, `voice`,
`stt_source`, `noise_reduction` and `client_config`. It does **not** carry
`instructions` or the opening line. The persona prompt — with its knowledge
ceilings, its unlock condition, and its forbidden behaviours — is sealed into
the minted credential vendor-side. A client that could read those could also
edit them, and the interviewer would be practising against a persona they had
configured themselves.

`client_config` is the one field handed to a client to pass back to a vendor,
and it exists only because a WebSocket client has to supply its own connect
config. It carries transcription toggles, turn-detection timings, session
resumption and the history flag — connect parameters, none of which author
persona behaviour. `test_the_client_config_never_carries_the_persona` and the
endpoint's mint test both assert the prompt and the opening line are absent
from it.

### How the seal works, per provider

* **openai** — the whole session document goes into
  `POST /v1/realtime/client_secrets`; the browser only ever holds the returned
  secret and a URL.
* **gemini** — the whole `LiveConnectConfig` (system instruction, voice,
  modality, both transcriptions, VAD, resumption, history) goes into
  `CreateAuthTokenConfig.live_connect_constraints`. Constrained fields are
  **enforced server-side for the life of the token**: the browser still passes
  a config on `live.connect`, and it cannot talk the vendor out of any of them.
  `lock_additional_fields` additionally pins `temperature`, `top_p` and `top_k`
  — knobs we deliberately did not set, so a client cannot reach for them either.

The credential's TTL is `REALTIME_TTL_SECONDS = 600`: long enough for a slow page
load plus a microphone permission prompt, short enough that a leaked one is
worthless by the time anyone finds it. The Gemini token additionally carries
`new_session_expire_time` of 120 s (how long it may *start* a call) and
`uses=2` — one reconnect, because the ~15-minute audio cap makes reconnecting
the normal path rather than an error case.

## Delivering the opening line

The persona's `opening_line` is authored at cast time and stored on the session.
In text mode the control plane writes it as turn 0. **In voice mode nobody can
write a turn on the persona's behalf**, so it is delivered as an instruction:
`build_voice_system_prompt(..., opening_line=...)` appends a `THE FIRST THING
YOU SAY` block — appended, never interpolated into the compiled contract — used
by both providers.

An instruction is not enough on its own, because neither vendor generates
anything until something arrives. Each path nudges once:

| | Nudge |
|---|---|
| openai | on the data channel's `onopen`, send `{"type": "response.create"}` |
| gemini | after connect, `sendClientContent` one synthetic turn — *"[The call connects. The interviewer has just joined and is waiting.]"* — with `turnComplete: true` (needs `historyConfig.initialHistoryInClientContent`, legal only before the first real turn) |

**The nudge is never stored.** What lands in the transcript is what the persona
actually says back, through the normal output-transcription path, like any other
turn.

## Surviving the session cap and reconnects (gemini)

An audio-only Live session is capped around fifteen minutes and the server sends
`goAway` before cutting it. `sessionResumption: {}` in the connect config makes
the server issue `sessionResumptionUpdate` messages; `ui/src/geminiLive.js`
keeps the latest `newHandle` where `resumable` is true and, on `goAway`, opens a
new session on the same token passing `sessionResumption: {handle}`. The
persona's `GainNode` is created once and outlives the reconnect, so the audio
graph — and therefore the stereo recording — is untouched by it. If the token
itself has expired the caller re-mints through the same endpoint, which is
permitted while the session row is still `live`.

## The recording path is unchanged

Both providers feed the same graph: the manager's mic on channel 0 of a
`ChannelMerger`, the persona on channel 1, merged into one
`MediaStreamDestination` that `MediaRecorder` chunks. On WebRTC the persona
arrives as a remote `MediaStream`; on Gemini it is the `GainNode` that
`geminiLive.js` schedules its decoded 24 kHz buffers through, connected to
**both** the speakers and the merger. See
[Session recording](/concepts/contracts/session-recording.md).

Nothing between the microphone and that merger processes the signal — no
RNNoise, no denoise worklet, no gate. Browser noise suppression is a
`getUserMedia` constraint on the *live track* and the operator can switch it
off; beyond that the recording stays raw on purpose, because it is the evidence
`report_engine/validate.py` checks quotes against. A recording we have quietly
rewritten is not evidence of anything.

## Vendor facts — OpenAI Realtime, verified live 2026-08-22

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

## Vendor facts — Gemini Live, SDK surface verified 2026-09-01

Against the pinned SDKs (`google-genai` 2.21.0 server-side, `@google/genai`
2.20.0 in the browser), not from memory:

| | |
|---|---|
| Mint | `client.aio.auth_tokens.create(config=CreateAuthTokenConfig(expire_time, new_session_expire_time, uses, live_connect_constraints, lock_additional_fields))` → `AuthToken(name, expire_time, …)`; `name` **is** the credential and `expire_time` is an RFC 3339 string |
| Constraint | `LiveConnectConstraints{model, config}` where `config` is a full `LiveConnectConfig` |
| Redeem | `new GoogleGenAI({apiKey: <token>, httpOptions: {apiVersion: 'v1alpha'}})`, then `ai.live.connect({model, config, callbacks})` |
| Audio up | `session.sendRealtimeInput({audio: {data: <base64>, mimeType: 'audio/pcm;rate=16000'}})` — raw 16-bit LE PCM, mono |
| Audio down | 24 kHz PCM mono, base64, in `serverContent.modelTurn.parts[].inlineData.data` |
| Modality | `responseModalities: ['AUDIO']` only; text arrives via the transcriptions, never alongside audio |
| VAD | `realtimeInputConfig.automaticActivityDetection{prefixPaddingMs, silenceDurationMs}` + `activityHandling: 'START_OF_ACTIVITY_INTERRUPTS'` |

Server messages this repo reads:

| Message | Becomes |
|---|---|
| `serverContent.inputTranscription.text` | fragments of the **manager's** turn |
| `serverContent.outputTranscription.text` | fragments of the **candidate's** turn |
| `serverContent.turnComplete` | the boundary that commits both accumulated turns |
| `serverContent.interrupted` | stop and drop scheduled persona audio (barge-in) |
| `sessionResumptionUpdate.newHandle` (when `resumable`) | saved for the next reconnect |
| `goAway` | reconnect now, on the saved handle |

Note the asymmetry against OpenAI: Gemini has **no per-side "transcript
finalised" event**. Both sides arrive as fragments and `turnComplete` is the
only boundary, so `VoiceSessionView` accumulates fragments and commits the
manager's turn then the candidate's when it fires.

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
`DEFAULT_REALTIME_MODEL_IDS`, advertise its `voices`, and add a row to
`_SESSION_BUILDERS` in
[`candidate_agent/voice.py`](/concepts/modules/candidate-agent-voice.md).

The second provider landing is where that file's anticipated seam was actually
split — and the answer was **not** a neutral schema. Each builder emits the
vendor's own document shape; what is shared is the *decisions* (the same
compiled prompt, the same opening line, the same persona voice, the same "the
human can always interrupt" rule), which is the part that has to stay identical.
A neutral schema translated twice would have added a layer whose only job was to
be translated away. `session_facts()` reads the client-visible half back out of
whichever document it is handed, so the control plane never branches on a
provider name.

## Related

[candidate_agent/voice.py](/concepts/modules/candidate-agent-voice.md) ·
[Session transcript](/concepts/contracts/session-transcript.md) ·
[Session recording](/concepts/contracts/session-recording.md) ·
[Run an interview](/concepts/runbooks/run-an-interview.md) ·
[Live-session engine](/concepts/subsystems/engine.md)
