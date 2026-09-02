// The Gemini Live half of a spoken interview.
//
// Everything vendor-specific about the WebSocket path lives here so
// VoiceSessionView only has to know "connect, hand me transcripts, tell me when
// the persona is speaking". The other provider (OpenAI Realtime, WebRTC) stays
// inline in the view, because its transport *is* the browser's own RTCPeerConnection.
//
// What this owns:
//   * capture  — a 16 kHz AudioContext feeding the PCM worklet, whose Int16
//                batches go out as base64 on sendRealtimeInput.
//   * playback — 24 kHz PCM chunks decoded into AudioBuffers and scheduled back
//                to back through one GainNode, so the persona's voice does not
//                gap between chunks. That GainNode is handed back to the caller,
//                which wires it to the speakers *and* to the stereo recording.
//   * survival — the server warns (goAway) before the ~15-minute audio cap and
//                keeps handing us resumption handles; reconnecting with the
//                latest handle is a seam in the audio, not the end of the call.
//
// The persona instructions are not here and never will be: they were sealed
// into the ephemeral token server-side. `config` below is the non-secret
// connect config the control plane returned alongside it.

import { GoogleGenAI } from '@google/genai'
import pcmWorkletUrl from './audio/pcmWorklet.js?url'

const INPUT_SAMPLE_RATE = 16000
const OUTPUT_SAMPLE_RATE = 24000

// A little ahead of "now" so the first chunk of a turn is not scheduled in the
// past on a busy main thread, which is what makes the start of a sentence click.
const SCHEDULE_LEAD_SECONDS = 0.08

const toBase64 = (buffer) => {
  const bytes = new Uint8Array(buffer)
  let binary = ''
  // Chunked because String.fromCharCode(...bytes) blows the argument limit on
  // anything bigger than a few tens of kilobytes.
  for (let i = 0; i < bytes.length; i += 0x8000) {
    binary += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000))
  }
  return btoa(binary)
}

const fromBase64 = (b64) => {
  const binary = atob(b64)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i)
  return bytes
}

/**
 * Open a Gemini Live session for one interview.
 *
 * @param {object} opts
 * @param {object} opts.cred        The minted credential: client_secret, model, client_config.
 * @param {MediaStream} opts.stream The microphone stream (already constrained by the caller).
 * @param {AudioContext} opts.playbackCtx Context the persona's audio is played through. The
 *   caller owns it because it is the same graph the stereo recording is tapped from.
 * @param {object} opts.on          Callbacks: open, inputTranscript, outputTranscript,
 *   turnComplete, interrupted, level, error, close.
 * @returns {Promise<object>} A handle with `outputNode`, `setStream`, `close`.
 */
export async function connectGeminiLive({ cred, stream, playbackCtx, on = {} }) {
  const ai = new GoogleGenAI({
    // The ephemeral token IS the API key on this path — it is scoped to one
    // session, carries the sealed config, and expires on its own.
    apiKey: cred.client_secret,
    httpOptions: { apiVersion: 'v1alpha' },
  })

  // Persona audio goes through one gain node for its whole life, so the caller
  // can wire it to the speakers and to the recording merger once and never
  // again — reconnects swap the session underneath it, not the graph.
  const outputNode = playbackCtx.createGain()

  // Capture runs in its own context because it must be 16 kHz; the playback
  // context is 48 kHz (whatever the device gives us) and resamples the 24 kHz
  // persona audio on the way out.
  const captureCtx = new AudioContext({ sampleRate: INPUT_SAMPLE_RATE })
  await captureCtx.audioWorklet.addModule(pcmWorkletUrl)
  const worklet = new AudioWorkletNode(captureCtx, 'pcm-worklet')
  // A worklet with no destination is not pulled by the graph in some browsers.
  // Muted, so nothing of the manager's own voice reaches their speakers.
  const sink = captureCtx.createGain()
  sink.gain.value = 0
  worklet.connect(sink).connect(captureCtx.destination)

  let micSource = captureCtx.createMediaStreamSource(stream)
  micSource.connect(worklet)

  let session = null
  let closed = false
  let resumptionHandle = null
  // Where the next chunk of persona audio starts, in playbackCtx time. Reset on
  // every interruption and at the start of each turn.
  let playHead = 0
  let scheduled = []

  const stopPlayback = () => {
    scheduled.forEach((node) => {
      try {
        node.stop()
      } catch {
        // Already ended — stopping twice throws and means nothing.
      }
    })
    scheduled = []
    playHead = 0
  }

  const play = (b64) => {
    const bytes = fromBase64(b64)
    const samples = new Int16Array(bytes.buffer, bytes.byteOffset, bytes.byteLength / 2)
    const buffer = playbackCtx.createBuffer(1, samples.length, OUTPUT_SAMPLE_RATE)
    const channel = buffer.getChannelData(0)
    for (let i = 0; i < samples.length; i++) channel[i] = samples[i] / 0x8000
    const node = playbackCtx.createBufferSource()
    node.buffer = buffer
    node.connect(outputNode)
    const now = playbackCtx.currentTime
    if (playHead < now) playHead = now + SCHEDULE_LEAD_SECONDS
    node.start(playHead)
    playHead += buffer.duration
    scheduled.push(node)
    node.onended = () => {
      scheduled = scheduled.filter((n) => n !== node)
    }
  }

  worklet.port.onmessage = (e) => {
    on.level?.(e.data.rms)
    if (!session || closed) return
    try {
      session.sendRealtimeInput({
        audio: { data: toBase64(e.data.pcm), mimeType: `audio/pcm;rate=${INPUT_SAMPLE_RATE}` },
      })
    } catch (err) {
      on.error?.(err)
    }
  }

  const handleMessage = (message) => {
    const content = message.serverContent
    if (message.sessionResumptionUpdate?.resumable && message.sessionResumptionUpdate.newHandle) {
      resumptionHandle = message.sessionResumptionUpdate.newHandle
    }
    if (message.goAway) {
      // The server is about to hang up (usually the ~15-minute audio cap).
      // Reconnect on the latest handle rather than letting the call end.
      reconnect()
      return
    }
    if (!content) return
    if (content.interrupted) {
      // The manager started talking over the persona. Everything already
      // scheduled is audio they have decided not to hear.
      stopPlayback()
      on.interrupted?.()
    }
    const audio = content.modelTurn?.parts?.find((p) => p.inlineData?.data)
    if (audio) play(audio.inlineData.data)
    if (content.inputTranscription?.text) on.inputTranscript?.(content.inputTranscription.text)
    if (content.outputTranscription?.text) on.outputTranscript?.(content.outputTranscription.text)
    if (content.turnComplete) on.turnComplete?.()
  }

  const open = async (handle) => {
    const config = { ...(cred.client_config || {}) }
    if (handle) config.sessionResumption = { handle }
    return ai.live.connect({
      model: cred.model,
      config,
      callbacks: {
        onmessage: handleMessage,
        onerror: (e) => on.error?.(e),
        onclose: () => {
          if (!closed) on.close?.()
        },
      },
    })
  }

  const reconnect = async () => {
    if (closed) return
    const handle = resumptionHandle
    try {
      const next = await open(handle)
      const previous = session
      session = next
      previous?.close()
    } catch (e) {
      if (!closed) on.error?.(e)
    }
  }

  session = await open(null)
  on.open?.()

  return {
    /** The persona's voice, as one node for the caller to wire up. */
    outputNode,

    /**
     * Say the first thing.
     *
     * The persona's opening line is sealed in the token as an instruction, but
     * a Live session generates nothing until something arrives. This seeds one
     * synthetic turn — a stage direction, not a manager utterance — purely to
     * start the model talking. It is deliberately never written to the stored
     * transcript; what lands there is what the persona actually says, through
     * the output transcription like every other turn.
     */
    prompt() {
      session?.sendClientContent({
        turns: [
          {
            role: 'user',
            parts: [
              { text: '[The call connects. The interviewer has just joined and is waiting.]' },
            ],
          },
        ],
        turnComplete: true,
      })
    },

    /** Swap in a freshly acquired mic track (device change, NS toggle). */
    setStream(next) {
      micSource.disconnect()
      micSource = captureCtx.createMediaStreamSource(next)
      micSource.connect(worklet)
    },

    close() {
      closed = true
      stopPlayback()
      try {
        session?.close()
      } catch {
        // Already closed by the server.
      }
      worklet.port.onmessage = null
      if (captureCtx.state !== 'closed') captureCtx.close()
    },
  }
}
