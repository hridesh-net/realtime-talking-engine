import { useEffect, useRef, useState } from 'react'
import { endSession, takeTurn } from './api'

const fmt = (ms) => {
  const total = Math.floor(ms / 1000)
  return `${String(Math.floor(total / 60)).padStart(2, '0')}:${String(total % 60).padStart(2, '0')}`
}

/**
 * One live interview. You are the hiring manager; the persona answers.
 *
 * The transcript on screen is the server's transcript — every turn shown here
 * came back from the API with its own index and elapsed offset. Nothing is
 * rendered optimistically except the "typing" placeholder, so what you read is
 * what the evaluation layer will read.
 */
export default function SessionView({ session, personaLabel, onExit }) {
  const [turns, setTurns] = useState(session.turns)
  const [status, setStatus] = useState(session.status)
  const [draft, setDraft] = useState('')
  const [waiting, setWaiting] = useState(false)
  const [error, setError] = useState(null)
  const [elapsed, setElapsed] = useState(0)
  const bottom = useRef(null)

  const startedAt = new Date(session.started_at).getTime()

  useEffect(() => {
    if (status !== 'live') return undefined
    const t = setInterval(() => setElapsed(Date.now() - startedAt), 1000)
    return () => clearInterval(t)
  }, [status, startedAt])

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: 'smooth' })
  }, [turns.length, waiting])

  const send = async (e) => {
    e.preventDefault()
    const text = draft.trim()
    if (!text || waiting || status !== 'live') return
    setError(null)
    setWaiting(true)
    // The manager's turn is echoed locally the moment it is sent; the server
    // returns only the reply, and both are already persisted by then.
    const optimistic = {
      index: turns.length,
      speaker: 'manager',
      text,
      at: new Date().toISOString(),
      elapsed_ms: Date.now() - startedAt,
    }
    setTurns((t) => [...t, optimistic])
    setDraft('')
    try {
      const reply = await takeTurn(session.id, text)
      setTurns((t) => [...t, reply])
    } catch (err) {
      setError(err.message)
      setTurns((t) => t.filter((x) => x !== optimistic))
      setDraft(text)
    } finally {
      setWaiting(false)
    }
  }

  const finish = async () => {
    setError(null)
    try {
      const done = await endSession(session.id)
      setStatus(done.status)
      setTurns(done.turns)
    } catch (err) {
      setError(err.message)
    }
  }

  const onKeyDown = (e) => {
    // Enter sends, Shift+Enter breaks the line — an interview is a conversation,
    // not an essay, and reaching for a button between every question kills pace.
    if (e.key === 'Enter' && !e.shiftKey) send(e)
  }

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
            ⌨
          </div>
          <div>
            <h2 className="h2">{session.candidate_name}</h2>
            <div className="sub">
              {personaLabel || session.persona_key} · typed interview
            </div>
          </div>
        </div>
        <div className="row">
          <span className={`badge ${status === 'live' ? 'running' : 'draft'}`}>
            {status === 'live'
              ? `● ${fmt(elapsed)} / ${session.planned_minutes}:00`
              : status}
          </span>
          {status === 'live' && (
            <button className="btn" onClick={finish}>
              End interview
            </button>
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

      <div className="chat">
        {turns.map((t) => (
          <div key={`${t.index}-${t.at}`} className={`bubble ${t.speaker}`}>
            <span className="who">
              {t.speaker === 'manager' ? 'You' : session.candidate_name} · {fmt(t.elapsed_ms)}
            </span>
            <div>{t.text}</div>
          </div>
        ))}
        {waiting && (
          <div className="bubble candidate">
            <span className="who">{session.candidate_name}</span>
            <div className="typing">typing…</div>
          </div>
        )}
        <div ref={bottom} />
      </div>

      {status === 'live' ? (
        <form className="composer" onSubmit={send}>
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Ask your question… (Enter to send, Shift+Enter for a new line)"
            rows={2}
            autoFocus
          />
          <button className="btn primary" type="submit" disabled={waiting || !draft.trim()}>
            {waiting ? 'Waiting…' : 'Send'}
          </button>
        </form>
      ) : (
        <div className="tip" style={{ marginTop: 10 }}>
          This interview is {status}. The transcript above is the stored record.
        </div>
      )}
    </div>
  )
}
