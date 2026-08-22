import { useCallback, useEffect, useRef, useState } from 'react'
import { appendTranscript, endSession, mintRealtimeCredential } from './api'

const fmt = (ms) => {
  const total = Math.max(0, Math.floor(ms / 1000))
  return `${String(Math.floor(total / 60)).padStart(2, '0')}:${String(total % 60).padStart(2, '0')}`
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

  const pcRef = useRef(null)
  const micRef = useRef(null)
  const audioRef = useRef(null)
  const bottomRef = useRef(null)
  // Transcript POSTs are chained rather than fired in parallel: the server
  // assigns each turn's index on arrival, so two in flight at once could land
  // out of order and mis-sequence the stored conversation.
  const queueRef = useRef(Promise.resolve())
  const startedAtRef = useRef(Date.now())

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

        pc = new RTCPeerConnection()
        pcRef.current = pc

        pc.ontrack = (e) => {
          if (audioRef.current) audioRef.current.srcObject = e.streams[0]
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

  const finish = async () => {
    pcRef.current?.close()
    micRef.current?.getTracks().forEach((t) => t.stop())
    setPhase('ended')
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
            'Requesting the microphone and opening the call. Chrome will ask for permission.'}
          {phase === 'live' &&
            (muted
              ? 'The persona cannot hear you.'
              : 'Just talk — no push-to-talk, and you can interrupt mid-sentence.')}
          {phase === 'ended' && 'Call ended. The transcript below is the stored record.'}
          {phase === 'error' && 'Could not start the call.'}
        </span>
      </div>

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
