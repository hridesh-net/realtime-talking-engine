import { useMemo, useState } from 'react'

/**
 * The landing screen: every interview created on this control plane.
 *
 * The mockup's stat tiles (hiring managers, avg readiness, bias flags) are
 * absent by design — no endpoint produces those numbers, and a card showing
 * invented ones would be the most convincing thing on the page.
 */

// The real vocabulary from control_plane/database.py, not the mockup's
// running/draft/archived — a tab that can never match anything is worse than
// no tab.
const STATUS = {
  scheduled: { cls: 'running', text: '▷ Scheduled' },
  in_progress: { cls: 'running', text: '● In progress' },
  completed: { cls: 'draft', text: '✓ Completed' },
  failed: { cls: 'flag', text: '⚠ Failed' },
  cancelled: { cls: 'draft', text: '✕ Cancelled' },
}

export default function InterviewList({ interviews, onOpen, onCreate }) {
  const [tab, setTab] = useState('all')
  const [q, setQ] = useState('')

  const counts = useMemo(() => {
    const c = { all: interviews.length }
    for (const iv of interviews) c[iv.status] = (c[iv.status] || 0) + 1
    return c
  }, [interviews])

  const tabs = [
    ['all', 'All'],
    ['scheduled', 'Scheduled'],
    ['in_progress', 'In progress'],
    ['completed', 'Completed'],
  ]

  const shown = interviews.filter(
    (iv) =>
      (tab === 'all' || iv.status === tab) &&
      (q === '' || iv.job_title.toLowerCase().includes(q.toLowerCase())),
  )

  return (
    <>
      <div className="row" style={{ gap: 16, marginBottom: 8 }}>
        <div
          className="secnum"
          style={{
            width: 48,
            height: 48,
            background: 'var(--blue-50)',
            color: 'var(--blue)',
            fontSize: 20,
          }}
        >
          🎓
        </div>
        <div>
          <h1 className="h1">Interview Training</h1>
          <div className="sub">
            Hiring managers interview an AI candidate. Pick the persona that stresses the
            skill they need to practise.
          </div>
        </div>
      </div>

      <div className="between">
        <div className="tabs" style={{ margin: '18px 0 0' }}>
          {tabs.map(([key, label]) => (
            <button
              type="button"
              key={key}
              className={`tab ${tab === key ? 'active' : ''}`}
              onClick={() => setTab(key)}
            >
              {label} <span className="n">{counts[key] || 0}</span>
            </button>
          ))}
        </div>
        <div className="row">
          <input
            className="search"
            placeholder="Search interviews"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
          <button className="btn primary" onClick={onCreate}>
            + New interview
          </button>
        </div>
      </div>

      <div style={{ height: 16 }} />

      {shown.length === 0 && (
        <div className="card">
          <div className="h2">Nothing here yet</div>
          <div className="sub">
            An interview is a job spec. Create one, then pick a persona to practise
            against.
          </div>
          <div className="actions" style={{ justifyContent: 'flex-start' }}>
            <button className="btn primary" onClick={onCreate}>
              + New interview
            </button>
          </div>
        </div>
      )}

      {shown.map((iv) => (
        <div
          className="card"
          key={iv.id}
          style={{ cursor: 'pointer' }}
          onClick={() => onOpen(iv)}
        >
          <div className="between">
            <div>
              <div className="h2">{iv.job_title}</div>
              <div className="sub">
                {iv.experience_level} · {iv.company_type} · {iv.job_location_type} ·{' '}
                {iv.config.duration_minutes} min · {iv.mode.replace(/_/g, ' ')}
              </div>
              <div className="row" style={{ marginTop: 10, flexWrap: 'wrap' }}>
                {iv.skills_required.map((s) => (
                  <span className="pill" key={s}>
                    {s}
                  </span>
                ))}
              </div>
            </div>
            <span className={`badge ${STATUS[iv.status]?.cls || 'draft'}`}>
              {STATUS[iv.status]?.text || iv.status}
            </span>
          </div>
        </div>
      ))}
    </>
  )
}
