import { useEffect, useRef, useState } from 'react'
import { getAnalysisStatus, startAnalysis } from './api'

/**
 * Running, and waiting on, one session's audio analysis.
 *
 * The analysis takes about a minute, so this is a background job with a polled
 * status rather than a request that hangs. The row exists from the moment the
 * job starts, which is what lets this tell "running" from "never asked".
 */
const POLL_MS = 4000

export default function AnalysisPanel({ session, onComplete }) {
  const [meta, setMeta] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const timer = useRef(null)

  const stop = () => {
    if (timer.current) clearTimeout(timer.current)
    timer.current = null
  }

  const poll = async (id) => {
    try {
      const next = await getAnalysisStatus(id)
      setMeta(next)
      if (next.status === 'running') {
        timer.current = setTimeout(() => poll(id), POLL_MS)
        return
      }
      if (next.status === 'complete') onComplete?.()
    } catch {
      // A 404 means nothing has been asked for yet, which is not an error.
      setMeta(null)
    }
  }

  useEffect(() => {
    stop()
    setMeta(null)
    setError(null)
    if (session?.id) poll(session.id)
    return stop
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session?.id])

  async function onAnalyse() {
    setBusy(true)
    setError(null)
    try {
      setMeta(await startAnalysis(session.id))
      timer.current = setTimeout(() => poll(session.id), POLL_MS)
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  const status = meta?.status
  const running = status === 'running'

  return (
    <div className="card" style={{ marginBottom: 14 }}>
      <div className="between">
        <div>
          <div className="eyebrow">Audio analysis</div>
          <div className="muted small">
            {running && 'Listening to the recording — about a minute.'}
            {status === 'complete' && (
              <>
                Analysed with <b>{meta.model_used}</b> under instructions{' '}
                <b>{meta.instructions_version}</b>, in {meta.windows} window
                {meta.windows === 1 ? '' : 's'}.
                {meta.dropped_anchors > 0 && (
                  <> {meta.dropped_anchors} timestamps fell outside the recording and were discarded.</>
                )}
              </>
            )}
            {status === 'failed' && <span style={{ color: 'var(--red)' }}>{meta.error}</span>}
            {!status && (
              <>
                The report is far stronger with this. It hears tone, silences, and
                anything said in a language other than English — which the counted
                signals cannot read.
              </>
            )}
          </div>
        </div>
        <div className="row" style={{ gap: 10 }}>
          {status === 'complete' && <span className="badge ok">✓ Analysed</span>}
          {running && <span className="badge running">● Running</span>}
          {!session.has_recording ? (
            <span className="muted small">No recording — nothing to analyse</span>
          ) : (
            <button className="btn sm primary" disabled={busy || running} onClick={onAnalyse}>
              {running ? 'Analysing…' : status ? '↻ Re-analyse' : '🎧 Analyse audio'}
            </button>
          )}
        </div>
      </div>
      {error && <div className="banner warn" style={{ marginTop: 12 }}><span>{error}</span></div>}
    </div>
  )
}
