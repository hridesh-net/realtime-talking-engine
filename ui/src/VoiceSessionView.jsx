import { useCallback, useEffect, useRef, useState } from 'react'
import {
  appendRecordingChunk,
  appendTranscript,
  endSession,
  finalizeRecording,
  mintRealtimeCredential,
  recordingUrl,
} from './api'
import { connectGeminiLive } from './geminiLive'

// audio/webm;codecs=opus is what we ask MediaRecorder for below — checked once
// so the connecting/live copy and the finish()/unmount teardown can all agree
// on whether a recording is actually happening.
const RECORDING_SUPPORTED =
  typeof MediaRecorder !== 'undefined' && MediaRecorder.isTypeSupported('audio/webm;codecs=opus')

// Above this the "HEARING YOU" indicator lights on the Gemini path, where we
// compute loudness from the capture worklet rather than being told by the
// vendor. Low enough to catch a quiet talker, high enough to ignore room tone.
const SPEAKING_RMS = 0.02

const fmt = (ms) => {
  const total = Math.max(0, Math.floor(ms / 1000))
  return `${String(Math.floor(total / 60)).padStart(2, '0')}:${String(total % 60).padStart(2, '0')}`
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

// Transient network blips are the common case and are recoverable — retry a
// few times with a short backoff before treating a chunk as truly failed.
const postChunkWithRetry = async (sessionId, seq, blob, attempts = 3) => {
  for (let attempt = 1; attempt <= attempts; attempt++) {
    try {
      return await appendRecordingChunk(sessionId, seq, blob)
    } catch (e) {
      if (attempt === attempts) throw e
      await sleep(300 * attempt)
    }
  }
  return undefined
}

// The one place the microphone is asked for, so every acquisition — the first
// one, a device change, a noise-suppression toggle — gets the same treatment.
//
// noiseSuppression is the operator's switch: it is the browser's own denoiser,
// applied to the live track. Echo cancellation and AGC are not negotiable —
// without them a laptop speaker feeds the persona back into the persona.
const acquireMic = ({ deviceId, noiseSuppression }) =>
  navigator.mediaDevices.getUserMedia({
    audio: {
      echoCancellation: true,
      noiseSuppression,
      autoGainControl: true,
      channelCount: 1,
      ...(deviceId ? { deviceId: { exact: deviceId } } : {}),
    },
  })

/**
 * A live *spoken* interview.
 *
 * The audio does not pass through our API. The browser holds the session with
 * the realtime vendor directly — that is the only way to get a latency that
 * feels like a conversation. Our server's job is the half that must not be
 * client-controlled: it compiled the persona instructions and sealed them into
 * the ephemeral credential, and it stamps every transcript turn that comes back.
 *
 * Two transports, chosen by the credential's `provider`:
 *
 *   gemini — a WebSocket carrying raw PCM, wrapped in `geminiLive.js`. The
 *            persona's opening line is spoken because the session is nudged
 *            with one synthetic "the call connects" turn.
 *   openai — WebRTC: an SDP offer posted against the client secret. The opening
 *            line is spoken because we send `response.create` as turn 0.
 *
 * Both feed the same stereo recording graph and the same transcript endpoint.
 * So: media is peer-to-vendor, truth is server-side.
 */
export default function VoiceSessionView({ session, personaLabel, onExit }) {
  const [phase, setPhase] = useState('connecting') // connecting | live | ended | error
  const [error, setError] = useState(null)
  const [turns, setTurns] = useState([])
  const [interim, setInterim] = useState({ manager: '', candidate: '' })
  const [listening, setListening] = useState(false)
  const [muted, setMuted] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const [cred, setCred] = useState(null)
  const [recordingReady, setRecordingReady] = useState(false)
  const [devices, setDevices] = useState([])
  const [deviceId, setDeviceId] = useState('')
  const [nsEnabled, setNsEnabled] = useState(true)

  const pcRef = useRef(null)
  const senderRef = useRef(null)
  const geminiRef = useRef(null)
  const micRef = useRef(null)
  const audioRef = useRef(null)
  const bottomRef = useRef(null)
  // Transcript POSTs are chained rather than fired in parallel: the server
  // assigns each turn's index on arrival, so two in flight at once could land
  // out of order and mis-sequence the stored conversation.
  const queueRef = useRef(Promise.resolve())
  const startedAtRef = useRef(Date.now())
  // Mic constraints as they stand right now. The connect effect must not
  // re-run when they change — swapping the track is imperative and does not
  // touch the call — so the current values are read from here, not from state.
  const constraintsRef = useRef({ deviceId: '', noiseSuppression: true })
  const mutedRef = useRef(false)

  // Stereo capture: the manager's mic feeds the left channel, the persona's
  // vendor audio feeds the right, mixed together by a ChannelMerger into a
  // single MediaStream that MediaRecorder chunks and uploads. Same reasoning
  // as queueRef above: chunk POSTs are chained on their own dedicated queue
  // (chunkQueueRef) since the server enforces strict seq ordering.
  //
  // NOTE: nothing between the microphone and this merger processes the signal.
  // No RNNoise, no denoise worklet, no gate. The browser's own noise
  // suppression is a getUserMedia constraint on the track and the operator can
  // switch it off; beyond that the recording stays raw on purpose, because it
  // is the evidence the report engine checks its quotes against
  // (`report_engine/validate.py`). A recording we have quietly rewritten is not
  // evidence of anything.
  const audioCtxRef = useRef(null)
  const mergerRef = useRef(null)
  const micSourceRef = useRef(null)
  const recorderRef = useRef(null)
  const chunkQueueRef = useRef(Promise.resolve())
  const chunkSeqRef = useRef(0)
  // Set once a chunk fails all its retries — the client's seq must never
  // drift ahead of the server's, so once this trips we stop posting (and
  // stop the recorder) rather than 409 on every chunk for the rest of the call.
  const recordingGaveUpRef = useRef(false)

  const record = useCallback(
    (speaker, text) => {
      const clean = (text || '').trim()
      if (!clean) return
      setTurns((t) => [...t, { speaker, text: clean, at: Date.now() }])
      queueRef.current = queueRef.current
        .then(() => appendTranscript(session.id, speaker, clean))
        .catch((e) => setError(`transcript not saved: ${e.message}`))
    },
    [session.id],
  )

  useEffect(() => {
    let cancelled = false
    let pc
    let gemini
    // Gemini emits transcription fragments for both sides and no "this turn's
    // transcript is final" event of its own — `turnComplete` is the boundary,
    // so fragments accumulate here and are committed as whole turns there.
    const fragments = { manager: '', candidate: '' }

    const connect = async () => {
      try {
        const credential = await mintRealtimeCredential(session.id)
        if (cancelled) return
        setCred(credential)

        const mic = await acquireMic(constraintsRef.current)
        if (cancelled) {
          mic.getTracks().forEach((t) => t.stop())
          return
        }
        micRef.current = mic

        // Device labels are blank until the permission prompt is answered, so
        // the picker can only be populated after getUserMedia has resolved.
        navigator.mediaDevices
          .enumerateDevices()
          .then((all) => {
            if (!cancelled) setDevices(all.filter((d) => d.kind === 'audioinput'))
          })
          .catch(() => {})

        // Left = manager mic, right = persona. A muted mic needs no special
        // handling here: a disabled track renders silence into Web Audio, so
        // the recording honestly captures the muted state.
        //
        // The Gemini path needs an AudioContext regardless — that is where the
        // persona's PCM is played — so the context is created whenever either
        // job needs one, and the merger only when there is a recording to make.
        let dest
        const needsContext = RECORDING_SUPPORTED || credential.provider === 'gemini'
        if (needsContext) {
          const ctx = new AudioContext()
          audioCtxRef.current = ctx
          if (RECORDING_SUPPORTED) {
            const merger = ctx.createChannelMerger(2)
            dest = ctx.createMediaStreamDestination()
            micSourceRef.current = ctx.createMediaStreamSource(mic)
            micSourceRef.current.connect(merger, 0, 0)
            merger.connect(dest)
            mergerRef.current = merger
          }
        }

        if (credential.provider === 'gemini') {
          gemini = await connectGeminiLive({
            cred: credential,
            stream: mic,
            playbackCtx: audioCtxRef.current,
            on: {
              level: (rms) => setListening(rms > SPEAKING_RMS),
              inputTranscript: (text) => {
                fragments.manager += text
                setInterim((s) => ({ ...s, manager: fragments.manager }))
              },
              outputTranscript: (text) => {
                fragments.candidate += text
                setInterim((s) => ({ ...s, candidate: fragments.candidate }))
              },
              turnComplete: () => {
                // Manager first: they asked, then the persona answered.
                record('manager', fragments.manager)
                record('candidate', fragments.candidate)
                fragments.manager = ''
                fragments.candidate = ''
                setInterim({ manager: '', candidate: '' })
              },
              error: (e) => setError(e?.message || 'live session error'),
            },
          })
          if (cancelled) {
            gemini.close()
            return
          }
          geminiRef.current = gemini
          // Speakers, and — when we are recording — the right channel too.
          gemini.outputNode.connect(audioCtxRef.current.destination)
          if (mergerRef.current) gemini.outputNode.connect(mergerRef.current, 0, 1)
          // Nudge the persona into speaking its sealed opening line. The nudge
          // itself is never stored; what lands in the transcript is what the
          // persona says back, through outputTranscription like any other turn.
          gemini.prompt()
        } else {
          pc = new RTCPeerConnection()
          pcRef.current = pc

          pc.ontrack = (e) => {
            if (audioRef.current) audioRef.current.srcObject = e.streams[0]
            // Chrome quirk: a remote WebRTC MediaStream only keeps producing
            // samples for Web Audio while it is *also* attached to a playing
            // media element — the srcObject assignment above already satisfies
            // that, so this tap keeps the persona's audio flowing to channel 1.
            if (mergerRef.current) {
              audioCtxRef.current
                .createMediaStreamSource(e.streams[0])
                .connect(mergerRef.current, 0, 1)
            }
          }
          senderRef.current = pc.addTrack(mic.getTracks()[0], mic)

          const dc = pc.createDataChannel('oai-events')
          dc.onopen = () => {
            // The opening line is an instruction sealed into the credential,
            // but the vendor generates nothing until asked. This is turn 0.
            dc.send(JSON.stringify({ type: 'response.create' }))
          }
          dc.onmessage = (e) => {
            let ev
            try {
              ev = JSON.parse(e.data)
            } catch {
              return
            }
            switch (ev.type) {
              case 'input_audio_buffer.speech_started':
                setListening(true)
                break
              case 'input_audio_buffer.speech_stopped':
                setListening(false)
                break
              case 'conversation.item.input_audio_transcription.delta':
                setInterim((s) => ({ ...s, manager: s.manager + (ev.delta || '') }))
                break
              case 'conversation.item.input_audio_transcription.completed':
                setInterim((s) => ({ ...s, manager: '' }))
                record('manager', ev.transcript)
                break
              case 'response.output_audio_transcript.delta':
                setInterim((s) => ({ ...s, candidate: s.candidate + (ev.delta || '') }))
                break
              case 'response.output_audio_transcript.done':
                setInterim((s) => ({ ...s, candidate: '' }))
                record('candidate', ev.transcript)
                break
              case 'error':
                setError(ev.error?.message || 'realtime error')
                break
              default:
                break
            }
          }

          const offer = await pc.createOffer()
          await pc.setLocalDescription(offer)

          const res = await fetch(credential.call_url, {
            method: 'POST',
            body: offer.sdp,
            headers: {
              Authorization: `Bearer ${credential.client_secret}`,
              'Content-Type': 'application/sdp',
            },
          })
          if (!res.ok)
            throw new Error(`vendor refused the offer (${res.status}): ${await res.text()}`)
          await pc.setRemoteDescription({ type: 'answer', sdp: await res.text() })
        }

        if (cancelled) return
        startedAtRef.current = Date.now()
        setPhase('live')

        if (RECORDING_SUPPORTED && dest) {
          const recorder = new MediaRecorder(dest.stream, { mimeType: 'audio/webm;codecs=opus' })
          recorder.ondataavailable = (e) => {
            if (!e.data || e.data.size === 0 || recordingGaveUpRef.current) return
            chunkQueueRef.current = chunkQueueRef.current.then(async () => {
              if (recordingGaveUpRef.current) return
              // Read the seq here rather than when the chunk fired: a slow or
              // retrying POST can still be in flight when the next chunk
              // arrives, and both would otherwise claim the same seq. It only
              // advances on confirmed success, so the client's notion of
              // "next seq" can never drift ahead of the server's.
              const seq = chunkSeqRef.current
              try {
                await postChunkWithRetry(session.id, seq, e.data)
                chunkSeqRef.current = seq + 1
              } catch {
                // Give up once, quietly from here on — what already landed is
                // a valid, playable partial recording. Stop the recorder so
                // it stops trying to post into a stream the server will now
                // refuse, and surface a single, non-repeating notice.
                recordingGaveUpRef.current = true
                setError('recording stopped early — the part before the failure was saved')
                if (recorderRef.current && recorderRef.current.state !== 'inactive') {
                  recorderRef.current.stop()
                }
              }
            })
          }
          recorderRef.current = recorder
          recorder.start(10000) // 10s chunks
        }
      } catch (e) {
        if (!cancelled) {
          setError(e.message)
          setPhase('error')
        }
      }
    }

    connect()
    return () => {
      cancelled = true
      pc?.close()
      gemini?.close()
      micRef.current?.getTracks().forEach((t) => t.stop())
      // Same teardown as finish(), but fire-and-forget: the component is
      // unmounting so there is nowhere left to report a failure to.
      if (recorderRef.current && recorderRef.current.state !== 'inactive') {
        recorderRef.current.stop()
      }
      closeAudioCtx()
    }
  }, [session.id, record])

  useEffect(() => {
    if (phase !== 'live') return undefined
    const t = setInterval(() => setElapsed(Date.now() - startedAtRef.current), 1000)
    return () => clearInterval(t)
  }, [phase])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [turns.length, interim.candidate, interim.manager])

  // Acquire a new track under the new constraints and put it everywhere the old
  // one was — the vendor, and the left channel of the recording — then drop the
  // old one. Nothing about the call is renegotiated: on WebRTC the sender swaps
  // its track, on the WebSocket path the capture graph re-points at the new
  // source. A failed swap leaves the working mic in place.
  const swapMic = async (next) => {
    const wanted = { ...constraintsRef.current, ...next }
    let stream
    try {
      stream = await acquireMic(wanted)
    } catch (e) {
      setError(`could not switch microphone: ${e.message}`)
      return
    }
    constraintsRef.current = wanted
    const track = stream.getTracks()[0]
    track.enabled = !mutedRef.current

    try {
      if (senderRef.current) await senderRef.current.replaceTrack(track)
      geminiRef.current?.setStream(stream)
      if (mergerRef.current && audioCtxRef.current) {
        micSourceRef.current?.disconnect()
        micSourceRef.current = audioCtxRef.current.createMediaStreamSource(stream)
        micSourceRef.current.connect(mergerRef.current, 0, 0)
      }
    } catch (e) {
      setError(`could not switch microphone: ${e.message}`)
      stream.getTracks().forEach((t) => t.stop())
      return
    }

    micRef.current?.getTracks().forEach((t) => t.stop())
    micRef.current = stream
  }

  const changeDevice = (id) => {
    setDeviceId(id)
    swapMic({ deviceId: id })
  }

  const toggleNoiseSuppression = () => {
    const next = !nsEnabled
    setNsEnabled(next)
    swapMic({ noiseSuppression: next })
  }

  const toggleMute = () => {
    const track = micRef.current?.getTracks()[0]
    if (!track) return
    track.enabled = !track.enabled
    mutedRef.current = !track.enabled
    setMuted(!track.enabled)
  }

  // Idempotent: finish() and the unmount cleanup can both reach here (e.g.
  // the user hits "Back" right after ending), and closing an already-closed
  // AudioContext throws.
  const closeAudioCtx = () => {
    const ctx = audioCtxRef.current
    audioCtxRef.current = null
    if (ctx && ctx.state !== 'closed') ctx.close()
  }

  // Stop the recorder, wait for its final chunk to land, then finalize. Runs
  // alongside — never gating — the transcript drain below: a lost recording
  // must not cost the transcript.
  const stopRecording = () =>
    new Promise((resolve, reject) => {
      const recorder = recorderRef.current
      if (!recorder || recorder.state === 'inactive') {
        resolve()
        return
      }
      recorder.onerror = (e) => reject(e.error || new Error('recorder error'))
      recorder.onstop = () => {
        // MediaRecorder fires a final `dataavailable` (which queues onto
        // chunkQueueRef) before `stop` — so waiting on the queue here also
        // waits for that last chunk's POST to finish.
        chunkQueueRef.current.then(resolve, reject)
      }
      recorder.stop()
    })

  const finish = async () => {
    pcRef.current?.close()
    geminiRef.current?.close()
    micRef.current?.getTracks().forEach((t) => t.stop())
    setPhase('ended')

    if (recorderRef.current) {
      stopRecording()
        .then(() => finalizeRecording(session.id))
        .then((meta) => meta && setRecordingReady(true))
        .catch((e) => setError(`recording not fully saved: ${e.message}`))
        .finally(closeAudioCtx)
    }

    try {
      // Let any in-flight transcript land before the session closes — a turn
      // posted after `end` would 409 and vanish from the record.
      await queueRef.current
      await endSession(session.id)
    } catch (e) {
      setError(e.message)
    }
  }

  const bubbles = [
    ...turns,
    ...(interim.manager ? [{ speaker: 'manager', text: interim.manager, interim: true }] : []),
    ...(interim.candidate ? [{ speaker: 'candidate', text: interim.candidate, interim: true }] : []),
  ]

  return (
    <div className="card">
      <div className="between">
        <div className="row">
          <div
            className="secnum"
            style={{
              width: 44,
              height: 44,
              background: 'var(--blue-50)',
              color: 'var(--blue)',
              fontSize: 18,
            }}
          >
            🎙
          </div>
          <div>
            <h2 className="h2">{session.candidate_name}</h2>
            <div className="sub">
              {personaLabel || session.persona_key} · spoken interview
            </div>
          </div>
        </div>
        <div className="row">
          {phase === 'live' && devices.length > 1 && (
            <select
              className="btn"
              value={deviceId}
              onChange={(e) => changeDevice(e.target.value)}
              title="Microphone"
            >
              <option value="">Default microphone</option>
              {devices.map((d) => (
                <option key={d.deviceId} value={d.deviceId}>
                  {d.label || 'Microphone'}
                </option>
              ))}
            </select>
          )}
          {phase === 'live' && (
            <button
              className="btn"
              onClick={toggleNoiseSuppression}
              title="Browser noise suppression on the live mic. The saved recording is always raw."
            >
              <span>{nsEnabled ? '🔉' : '🔊'}</span>
              <span>{nsEnabled ? 'Noise suppr. on' : 'Noise suppr. off'}</span>
            </button>
          )}
          <span className={`badge ${phase === 'live' ? 'running' : 'draft'}`}>
            {phase === 'live'
              ? `● ${fmt(elapsed)} / ${session.planned_minutes}:00`
              : phase === 'connecting'
                ? 'connecting…'
                : phase}
          </span>
          {phase === 'live' && (
            <>
              <button className="btn" onClick={toggleMute}>
                <span>{muted ? '🔇' : '🎤'}</span>
                <span>{muted ? 'Unmute' : 'Mute'}</span>
              </button>
              <button className="btn" onClick={finish}>
                End interview
              </button>
            </>
          )}
          <button className="btn" onClick={onExit}>
            ← Back
          </button>
        </div>
      </div>

      {error && (
        <div className="error" style={{ marginTop: 14 }}>
          {error}
        </div>
      )}

      <div
        className={`banner ${phase === 'live' && listening ? 'live' : phase === 'error' ? 'warn' : ''}`}
        style={{ marginTop: 14 }}
      >
        <span className="k">
          {phase === 'connecting' && 'CONNECTING'}
          {phase === 'live' && (muted ? 'MUTED' : listening ? 'HEARING YOU' : 'LISTENING')}
          {phase === 'ended' && 'ENDED'}
          {phase === 'error' && 'FAILED'}
        </span>
        <span>
          {phase === 'connecting' &&
            'Requesting the microphone and opening the call. Chrome will ask for permission.' +
              (RECORDING_SUPPORTED
                ? ' This call is recorded and stored on the control plane.'
                : '')}
          {phase === 'live' &&
            (muted
              ? 'The persona cannot hear you.'
              : 'Just talk — no push-to-talk, and you can interrupt mid-sentence.')}
          {phase === 'ended' && 'Call ended. The transcript below is the stored record.'}
          {phase === 'error' && 'Could not start the call.'}
        </span>
      </div>

      {!RECORDING_SUPPORTED && (phase === 'connecting' || phase === 'live') && (
        <div className="tip" style={{ marginTop: 10 }}>
          This browser can't record this call (no MediaRecorder support for audio/webm;codecs=opus)
          — the interview will proceed without a saved recording.
        </div>
      )}

      {phase === 'ended' && (recordingReady || session.recording) && (
        <div className="row" style={{ marginTop: 10, gap: 12 }}>
          <audio controls src={recordingUrl(session.id)} />
          <a href={recordingUrl(session.id)} download>
            Download recording
          </a>
        </div>
      )}

      <div className="chat">
        {bubbles.length === 0 && phase === 'live' && (
          <div className="loading">The persona opens — listen, then take the interview.</div>
        )}
        {bubbles.map((t, i) => (
          <div
            key={`${i}-${t.interim ? 'i' : 'f'}`}
            className={`bubble ${t.speaker} ${t.interim ? 'interim' : ''}`}
          >
            <span className="who">{t.speaker === 'manager' ? 'You' : session.candidate_name}</span>
            <div>{t.text}</div>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      {/* The persona's voice on the WebRTC path. autoPlay is safe: reaching
          this view was a click. The Gemini path plays through Web Audio. */}
      <audio ref={audioRef} autoPlay />
    </div>
  )
}
