import { useCallback, useEffect, useRef, useState } from 'react'
import {
  appendRecordingChunk,
  appendTranscript,
  endSession,
  finalizeRecording,
  mintRealtimeCredential,
  recordingUrl,
} from './api'

// audio/webm;codecs=opus is what we ask MediaRecorder for below — checked once
// so the connecting/live copy and the finish()/unmount teardown can all agree
// on whether a recording is actually happening.
const RECORDING_SUPPORTED =
  typeof MediaRecorder !== 'undefined' && MediaRecorder.isTypeSupported('audio/webm;codecs=opus')

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

/**
 * A live *spoken* interview.
 *
 * The audio does not pass through our API. The browser holds a WebRTC session
 * with the realtime vendor directly — that is the only way to get a latency
 * that feels like a conversation. Our server's job is the half that must not be
 * client-controlled: it compiled the persona instructions and sealed them into
 * the ephemeral credential, and it stamps every transcript turn that comes back.
 *
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
  const [voice, setVoice] = useState('')
  const [recordingReady, setRecordingReady] = useState(false)

  const pcRef = useRef(null)
  const micRef = useRef(null)
  const audioRef = useRef(null)
  const bottomRef = useRef(null)
  // Transcript POSTs are chained rather than fired in parallel: the server
  // assigns each turn's index on arrival, so two in flight at once could land
  // out of order and mis-sequence the stored conversation.
  const queueRef = useRef(Promise.resolve())
  const startedAtRef = useRef(Date.now())

  // Stereo capture: the manager's mic feeds the left channel, the persona's
  // vendor audio feeds the right, mixed together by a ChannelMerger into a
  // single MediaStream that MediaRecorder chunks and uploads. Same reasoning
  // as queueRef above: chunk POSTs are chained on their own dedicated queue
  // (chunkQueueRef) since the server enforces strict seq ordering.
  const audioCtxRef = useRef(null)
  const mergerRef = useRef(null)
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

    const connect = async () => {
      try {
        const cred = await mintRealtimeCredential(session.id)
        if (cancelled) return
        setVoice(cred.voice)

        const mic = await navigator.mediaDevices.getUserMedia({
          audio: { echoCancellation: true, noiseSuppression: true },
        })
        if (cancelled) {
          mic.getTracks().forEach((t) => t.stop())
          return
        }
        micRef.current = mic

        // Left = manager mic, right = persona — filled in once the vendor's
        // track arrives in pc.ontrack below. A muted mic needs no special
        // handling here: a disabled track renders silence into Web Audio, so
        // the recording honestly captures the muted state.
        let dest
        if (RECORDING_SUPPORTED) {
          const ctx = new AudioContext()
          const merger = ctx.createChannelMerger(2)
          dest = ctx.createMediaStreamDestination()
          ctx.createMediaStreamSource(mic).connect(merger, 0, 0)
          merger.connect(dest)
          audioCtxRef.current = ctx
          mergerRef.current = merger
        }

        pc = new RTCPeerConnection()
        pcRef.current = pc

        pc.ontrack = (e) => {
          if (audioRef.current) audioRef.current.srcObject = e.streams[0]
          // Chrome quirk: a remote WebRTC MediaStream only keeps producing
          // samples for Web Audio while it is *also* attached to a playing
          // media element — the srcObject assignment above already satisfies
          // that, so this tap keeps the persona's audio flowing to channel 1.
          if (mergerRef.current) {
            audioCtxRef.current.createMediaStreamSource(e.streams[0]).connect(mergerRef.current, 0, 1)
          }
        }
        pc.addTrack(mic.getTracks()[0], mic)

        const dc = pc.createDataChannel('oai-events')
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

        const res = await fetch(cred.call_url, {
          method: 'POST',
          body: offer.sdp,
          headers: {
            Authorization: `Bearer ${cred.client_secret}`,
            'Content-Type': 'application/sdp',
          },
        })
        if (!res.ok) throw new Error(`vendor refused the offer (${res.status}): ${await res.text()}`)
        await pc.setRemoteDescription({ type: 'answer', sdp: await res.text() })

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

  const toggleMute = () => {
    const track = micRef.current?.getTracks()[0]
    if (!track) return
    track.enabled = !track.enabled
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
              {voice && ` · voice “${voice}”`}
            </div>
          </div>
        </div>
        <div className="row">
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
          <div className="loading">Say hello — the persona will answer.</div>
        )}
        {bubbles.map((t, i) => (
          <div
            key={`${i}-${t.interim ? 'i' : 'f'}`}
            className={`bubble ${t.speaker} ${t.interim ? 'interim' : ''}`}
          >
            <span className="who">
              {t.speaker === 'manager' ? 'You' : session.candidate_name}
            </span>
            <div>{t.text}</div>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      {/* The persona's voice. autoPlay is safe: reaching this view was a click. */}
      <audio ref={audioRef} autoPlay />
    </div>
  )
}
