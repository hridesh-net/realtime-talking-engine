import { useEffect, useRef, useState } from 'react'
import AnalysisPanel from './AnalysisPanel'
import { generateReport, getReport, reportHtmlUrl } from './api'

/**
 * One session's development report, as its own screen.
 *
 * The body is an iframe of the engine's own HTML rather than a second React
 * rendering of the same data. That is deliberate: "download as PDF" is the
 * browser printing this very document, so a separate console layout would mean
 * the report a trainer reads on screen and the one they file could drift apart.
 * One renderer, two outputs.
 */
export default function ReportView({ session, onClose, onGenerated }) {
  const [report, setReport] = useState(null)
  const [busy, setBusy] = useState(false)
  // The working — signal tables, question acts, the basis panel — is off by
  // default. It is what a trainer opens to check a number, and what made the
  // old report unreadable for the manager acting on one.
  const [detail, setDetail] = useState(false)
  // Bumped when an analysis finishes, so the report offers to pick it up.
  const [analysed, setAnalysed] = useState(0)
  const [error, setError] = useState(null)
  const frame = useRef(null)

  useEffect(() => {
    let live = true
    setReport(null)
    setError(null)
    if (!session?.has_report) return undefined
    getReport(session.id)
      .then((r) => live && setReport(r))
      .catch((e) => live && setError(e.message))
    return () => {
      live = false
    }
  }, [session])

  async function onGenerate() {
    setBusy(true)
    setError(null)
    try {
      setReport(await generateReport(session.id))
      onGenerated?.(session.id)
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  // Printing the iframe, not the console, is what makes the PDF match the page.
  function onPrint() {
    const win = frame.current?.contentWindow
    if (!win) return
    win.focus()
    win.print()
  }

  const tone = (n) => (n >= 65 ? 'g' : n >= 45 ? 'o' : 'r')

  return (
    <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
      <div className="between" style={{ padding: '14px 18px', borderBottom: '1px solid var(--line)' }}>
        <div>
          <div className="eyebrow">Development report</div>
          <div className="nm" style={{ fontSize: 16 }}>{session.candidate_name}</div>
        </div>
        <div className="row" style={{ gap: 10 }}>
          {report && !report.unscoreable && (
            <span className={`score ${tone(report.readiness_index)}`} style={{ fontSize: 20 }}>
              {report.readiness_index}
              <span className="muted small" style={{ fontWeight: 400 }}> · {report.band}</span>
            </span>
          )}
          {report && (
            <>
              <button
                className={`btn sm ${detail ? 'primary' : ''}`}
                onClick={() => setDetail((d) => !d)}
                title="Every signal with its measurement, the question acts and the basis panel"
              >
                {detail ? '▾ Hide working' : '▸ Show working'}
              </button>
              <button className="btn sm" onClick={onPrint}>📄 Download PDF</button>
              <button
                className={`btn sm ${analysed ? 'primary' : ''}`}
                disabled={busy}
                onClick={onGenerate}
                title={analysed ? 'A newer analysis is available — rebuild to include it' : ''}
              >
                {busy ? 'Regenerating…' : analysed ? '↻ Rebuild with analysis' : '↻ Regenerate'}
              </button>
            </>
          )}
          <button className="btn sm" onClick={onClose}>← Back to sessions</button>
        </div>
      </div>

      <div style={{ padding: '14px 18px 0' }}>
        <AnalysisPanel session={session} onComplete={() => setAnalysed((n) => n + 1)} />
      </div>

      {error && <div className="banner warn" style={{ margin: 16 }}><span>{error}</span></div>}

      {!report && !error && (
        <div style={{ padding: 28, textAlign: 'center' }}>
          <div className="h2">No report yet</div>
          <div className="sub" style={{ marginBottom: 16 }}>
            Built from the stored transcript, and from the audio analysis when one
            has been run. Every claim cites the moment it came from.
          </div>
          <button className="btn primary" disabled={busy} onClick={onGenerate}>
            {busy ? 'Scoring…' : '⚡ Generate report'}
          </button>
        </div>
      )}

      {report && (
        <>
          {report.unscoreable && (
            <div className="banner warn" style={{ margin: 16 }}>
              <span className="k">NOT SCORED</span>
              <span>
                The manager's speech was not detected as English, so the English
                rule set does not hold. Nothing was scored rather than scored wrongly.
              </span>
            </div>
          )}
          <iframe
            ref={frame}
            title="Session report"
            src={reportHtmlUrl(session.id, detail)}
            style={{ width: '100%', height: 'calc(100vh - 210px)', minHeight: 520, border: 0, display: 'block' }}
          />
        </>
      )}
    </div>
  )
}
