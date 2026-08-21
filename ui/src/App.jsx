import { useEffect, useState } from 'react'
import {
  createInterview,
  deleteCandidate,
  enrollCandidates,
  generateExpectation,
  getExpectation,
  listArchetypes,
  listCandidates,
  listInterviews,
} from './api'

const EMPTY_FORM = {
  job_title: 'Senior Backend Engineer',
  jd: 'Looking for a senior backend engineer with strong Go, distributed systems, Redis, and microservices experience. Must design scalable services and mentor junior engineers.',
  skills_required: 'Go, distributed systems, Redis, microservices, system design',
  job_location_type: 'remote',
  experience_level: 'senior',
  company_type: 'startup',
  mode: 'live_interview',
  duration_minutes: 60,
}

export default function App() {
  const [form, setForm] = useState(EMPTY_FORM)
  const [interviews, setInterviews] = useState([])
  const [selected, setSelected] = useState(null)
  const [expectation, setExpectation] = useState(null)
  const [archetypes, setArchetypes] = useState([])
  const [defaults, setDefaults] = useState([])
  const [picked, setPicked] = useState([])
  const [candidates, setCandidates] = useState([])
  const [busy, setBusy] = useState(null)
  const [error, setError] = useState(null)

  const refresh = async () => {
    try {
      setInterviews(await listInterviews())
    } catch (e) {
      setError(e.message)
    }
  }

  useEffect(() => {
    refresh()
    listArchetypes()
      .then((d) => {
        setArchetypes(d.archetypes)
        setDefaults(d.defaults)
        setPicked(d.defaults)
      })
      .catch((e) => setError(e.message))
  }, [])

  // Loading a different interview swaps in its own candidates and expectation.
  useEffect(() => {
    if (!selected) return
    setExpectation(null)
    setCandidates([])
    listCandidates(selected.id).then(setCandidates).catch((e) => setError(e.message))
    getExpectation(selected.id)
      .then(setExpectation)
      .catch(() => setExpectation(null)) // not generated yet — not an error
  }, [selected?.id])

  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value })

  const submit = async (e) => {
    e.preventDefault()
    setError(null)
    setBusy('create')
    try {
      const created = await createInterview({
        job_title: form.job_title,
        jd: form.jd,
        skills_required: form.skills_required
          .split(',')
          .map((s) => s.trim())
          .filter(Boolean),
        job_location_type: form.job_location_type,
        experience_level: form.experience_level,
        company_type: form.company_type,
        mode: form.mode,
        config: { duration_minutes: Number(form.duration_minutes) },
      })
      await refresh()
      setSelected(created)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(null)
    }
  }

  const runExpectation = async () => {
    setError(null)
    setBusy('expectation')
    try {
      setExpectation(await generateExpectation(selected.id))
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(null)
    }
  }

  const enroll = async (keys, regenerate = false) => {
    setError(null)
    setBusy('enroll')
    try {
      await enrollCandidates(selected.id, { archetypes: keys, regenerate })
      setCandidates(await listCandidates(selected.id))
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(null)
    }
  }

  const removeCandidate = async (cid) => {
    setError(null)
    try {
      await deleteCandidate(cid)
      setCandidates(await listCandidates(selected.id))
    } catch (err) {
      setError(err.message)
    }
  }

  const togglePick = (key) =>
    setPicked((p) => (p.includes(key) ? p.filter((k) => k !== key) : [...p, key]))

  return (
    <div className="app">
      <div className="header">
        <h1>Interview Control Plane</h1>
        <p>
          Create an interview, generate the interviewer expectation, then enroll virtual
          candidates to train interviewers against.
        </p>
      </div>

      {error && <div className="error">{error}</div>}

      <div className="layout">
        <div className="panel">
          <h2>New interview</h2>
          <form onSubmit={submit}>
            <div className="form-group">
              <label>Job title</label>
              <input value={form.job_title} onChange={set('job_title')} required />
            </div>
            <div className="form-group">
              <label>Job description</label>
              <textarea value={form.jd} onChange={set('jd')} required />
            </div>
            <div className="form-group">
              <label>Skills required (comma separated)</label>
              <input value={form.skills_required} onChange={set('skills_required')} required />
            </div>
            <div className="form-row">
              <div className="form-group">
                <label>Location type</label>
                <select value={form.job_location_type} onChange={set('job_location_type')}>
                  <option value="remote">remote</option>
                  <option value="onsite">onsite</option>
                  <option value="hybrid">hybrid</option>
                </select>
              </div>
              <div className="form-group">
                <label>Experience level</label>
                <select value={form.experience_level} onChange={set('experience_level')}>
                  <option value="junior">junior</option>
                  <option value="mid">mid</option>
                  <option value="senior">senior</option>
                </select>
              </div>
            </div>
            <div className="form-row">
              <div className="form-group">
                <label>Company type</label>
                <select value={form.company_type} onChange={set('company_type')}>
                  <option value="startup">startup</option>
                  <option value="mnc">mnc</option>
                </select>
              </div>
              <div className="form-group">
                <label>Mode</label>
                <select value={form.mode} onChange={set('mode')}>
                  <option value="live_interview">live_interview</option>
                  <option value="training_interviewer">training_interviewer</option>
                </select>
              </div>
            </div>
            <div className="form-group">
              <label>Duration (minutes)</label>
              <input
                type="number"
                min="15"
                max="180"
                value={form.duration_minutes}
                onChange={set('duration_minutes')}
              />
            </div>
            <button className="btn" type="submit" disabled={busy === 'create'}>
              {busy === 'create' ? 'Creating…' : 'Create interview'}
            </button>
          </form>
        </div>

        <div className="panel">
          <h2>Interviews ({interviews.length})</h2>
          <div className="interview-list">
            {interviews.length === 0 && <div className="loading">No interviews yet.</div>}
            {interviews.map((iv) => (
              <div
                className="interview-item"
                key={iv.id}
                style={
                  selected?.id === iv.id
                    ? { borderColor: '#0070f3', background: '#f0f7ff' }
                    : undefined
                }
              >
                <div className="title">{iv.job_title}</div>
                <div className="meta">
                  {iv.experience_level} · {iv.company_type} · {iv.job_location_type} ·{' '}
                  {iv.config.duration_minutes} min · {iv.status}
                </div>
                <div>
                  {iv.skills_required.map((s) => (
                    <span className="tag" key={s}>
                      {s}
                    </span>
                  ))}
                </div>
                <div className="actions" style={{ marginTop: 8 }}>
                  <button className="btn btn-sm" onClick={() => setSelected(iv)}>
                    {selected?.id === iv.id ? 'Selected' : 'Select'}
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {selected && (
        <div className="panel" style={{ marginTop: 20 }}>
          <h2>
            {selected.job_title} — expectation &amp; candidates
          </h2>

          <div className="section">
            <h4>Interviewer expectation</h4>
            {expectation ? (
              <div>
                <span className="tag">{expectation.interview_type}</span>
                {expectation.structure.map((p) => (
                  <span className="tag" key={p.name}>
                    {p.name} {p.duration_minutes}m
                  </span>
                ))}
                <details className="persona-detail">
                  <summary>Full expectation JSON</summary>
                  <pre>{JSON.stringify(expectation, null, 2)}</pre>
                </details>
              </div>
            ) : (
              <div className="loading">Not generated yet.</div>
            )}
            <button
              className="btn btn-sm"
              style={{ marginTop: 8 }}
              disabled={busy === 'expectation'}
              onClick={runExpectation}
            >
              {busy === 'expectation'
                ? 'Generating…'
                : expectation
                  ? 'Regenerate expectation'
                  : 'Generate expectation'}
            </button>
          </div>

          <div className="section">
            <h4>Enroll virtual candidates</h4>
            <p style={{ fontSize: 12, color: '#666', margin: '0 0 8px 0' }}>
              Personas are cast from this interview's job spec. The two defaults are one
              candidate who <strong>should be selected</strong> and one who{' '}
              <strong>should be rejected</strong>.
            </p>
            <div className="archetype-picker">
              {archetypes.map((a) => (
                <label
                  key={a.key}
                  className={`archetype-option ${picked.includes(a.key) ? 'checked' : ''}`}
                >
                  <input
                    type="checkbox"
                    checked={picked.includes(a.key)}
                    onChange={() => togglePick(a.key)}
                    style={{ marginRight: 6 }}
                  />
                  <span className="aname">
                    {a.label}{' '}
                    <span className={`verdict-badge ${a.verdict}`}>{a.verdict}</span>
                  </span>
                  <span className="achallenge">{a.interviewer_challenge}</span>
                </label>
              ))}
            </div>
            <div className="actions">
              <button
                className="btn"
                disabled={busy === 'enroll'}
                onClick={() => enroll(defaults)}
              >
                {busy === 'enroll' ? 'Casting…' : 'Enroll 2 defaults'}
              </button>
              <button
                className="btn btn-secondary"
                disabled={busy === 'enroll' || picked.length === 0}
                onClick={() => enroll(picked)}
              >
                Enroll selected ({picked.length})
              </button>
              <button
                className="btn btn-secondary"
                disabled={busy === 'enroll' || picked.length === 0}
                onClick={() => enroll(picked, true)}
                title="Re-cast personas that are already enrolled"
              >
                Re-cast selected
              </button>
            </div>

            <div className="candidate-grid">
              {candidates.map((c) => (
                <CandidateCard key={c.candidate_id} c={c} onDelete={removeCandidate} />
              ))}
            </div>
            {candidates.length === 0 && (
              <div className="loading" style={{ marginTop: 10 }}>
                No candidates enrolled yet.
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function Trait({ label, value }) {
  return (
    <div className="trait-row">
      <span className="tlabel">{label}</span>
      <span className="trait-bar">
        <span style={{ width: `${value * 10}%` }} />
      </span>
      <span className="tval">{value}</span>
    </div>
  )
}

function CandidateCard({ c, onDelete }) {
  const a = c.aptitude
  const smartPct = Math.round(a.smartness_ratio * 100)

  return (
    <div className={`candidate-card ${c.verdict}`}>
      <div className="cname">
        {c.name} <span className={`verdict-badge ${c.verdict}`}>{c.verdict}</span>
      </div>
      <div className="chead">
        {c.archetype_label} · {c.years_experience}y — {c.headline}
      </div>

      <div className="ratio-bar" title="smartness vs dumbness">
        <span className="smart" style={{ width: `${smartPct}%` }}>
          {smartPct >= 25 ? `smart ${a.smartness}` : ''}
        </span>
        <span className="dumb" style={{ width: `${100 - smartPct}%` }}>
          {100 - smartPct >= 25 ? `dumb ${a.dumbness}` : ''}
        </span>
      </div>

      <Trait label="seriousness" value={a.seriousness} />
      <Trait label="effort" value={a.effort} />
      <Trait label="interest" value={a.interest} />
      <Trait label="honesty" value={a.honesty} />
      <Trait label="nervousness" value={a.nervousness} />

      <div style={{ fontSize: 12, marginTop: 8 }}>
        <strong>Talks:</strong> {c.speech_profile.pace}, {c.speech_profile.verbosity} —{' '}
        {c.speech_profile.tone}
      </div>
      <div style={{ fontSize: 12, marginTop: 4 }}>
        <strong>Knowledge:</strong>{' '}
        {c.knowledge_map.map((k) => (
          <span className="tag" key={k.skill}>
            {k.skill} {k.level}/10
          </span>
        ))}
      </div>
      <div style={{ fontSize: 12, marginTop: 6, color: '#444' }}>
        <strong>Unlocks when:</strong> {c.answer_policy.reveals_depth_when}
      </div>

      <details className="persona-detail">
        <summary>Interviewer scorecard</summary>
        <div style={{ marginTop: 6 }}>
          <div style={{ marginBottom: 6 }}>
            <em>{c.interviewer_scorecard.interviewer_challenge}</em>
          </div>
          <ul style={{ paddingLeft: 18, margin: 0 }}>
            {c.interviewer_scorecard.must_discover.map((i) => (
              <li key={i.id} style={{ marginBottom: 4 }}>
                <strong>{i.weight}</strong> — {i.signal}
                <br />
                <span style={{ color: '#666' }}>How: {i.how_to_surface}</span>
              </li>
            ))}
          </ul>
          <div style={{ marginTop: 6, color: '#666' }}>
            Fails if: {c.interviewer_scorecard.interviewer_failure_modes.join('; ')}
          </div>
        </div>
      </details>

      <details className="persona-detail">
        <summary>Engine system prompt</summary>
        <pre>{c.engine_contract.system_prompt}</pre>
      </details>

      <details className="persona-detail">
        <summary>Full persona JSON</summary>
        <pre>{JSON.stringify(c, null, 2)}</pre>
      </details>

      <div className="actions" style={{ marginTop: 8 }}>
        <button className="btn btn-sm btn-secondary" onClick={() => onDelete(c.candidate_id)}>
          Remove
        </button>
      </div>
    </div>
  )
}
