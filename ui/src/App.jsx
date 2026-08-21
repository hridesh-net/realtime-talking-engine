import { useEffect, useState } from 'react'
import {
  createInterview,
  generateExpectation,
  getExpectation,
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
  const [expectation, setExpectation] = useState(null)
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
  }, [])

  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value })

  const submit = async (e) => {
    e.preventDefault()
    setError(null)
    setBusy('create')
    try {
      await createInterview({
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
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(null)
    }
  }

  const runExpectation = async (id, fetchOnly) => {
    setError(null)
    setExpectation(null)
    setBusy(id)
    try {
      setExpectation(fetchOnly ? await getExpectation(id) : await generateExpectation(id))
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="app">
      <div className="header">
        <h1>Interview Control Plane</h1>
        <p>Create an interview from a job spec, then generate the interviewer expectation.</p>
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
              <div className="interview-item" key={iv.id}>
                <div className="title">{iv.job_title}</div>
                <div className="meta">
                  {iv.experience_level} · {iv.company_type} · {iv.job_location_type} ·{' '}
                  {iv.config.duration_minutes} min · {iv.mode} · {iv.status}
                  <br />
                  {iv.id}
                </div>
                <div>
                  {iv.skills_required.map((s) => (
                    <span className="tag" key={s}>
                      {s}
                    </span>
                  ))}
                </div>
                <div className="actions" style={{ marginTop: 8 }}>
                  <button
                    className="btn btn-sm"
                    disabled={busy === iv.id}
                    onClick={() => runExpectation(iv.id, false)}
                  >
                    {busy === iv.id ? 'Generating…' : 'Generate expectation'}
                  </button>
                  <button
                    className="btn btn-sm btn-secondary"
                    disabled={busy === iv.id}
                    onClick={() => runExpectation(iv.id, true)}
                  >
                    View saved
                  </button>
                </div>
              </div>
            ))}
          </div>

          {expectation && <ExpectationView expectation={expectation} />}
        </div>
      </div>
    </div>
  )
}

function ExpectationView({ expectation }) {
  const {
    interview_type,
    structure,
    mandatory_skills,
    optional_skills,
    resume_probing,
    behavioral_assessment,
    red_flags,
    green_flags,
    evaluation_criteria,
    interviewer_guidance,
  } = expectation

  return (
    <div className="expectation-view">
      <h3>Expectation — {interview_type}</h3>

      <div className="section">
        <h4>Structure</h4>
        {structure.map((p) => (
          <div key={p.name} style={{ marginBottom: 6 }}>
            <span className="tag">
              {p.name} · {p.duration_minutes} min{p.mandatory ? ' · mandatory' : ''}
            </span>
            <div style={{ fontSize: 12, color: '#444' }}>{p.guidance}</div>
          </div>
        ))}
      </div>

      <div className="section">
        <h4>Mandatory skills</h4>
        {mandatory_skills.map((s) => (
          <div key={s.skill} style={{ marginBottom: 6 }}>
            <span className="tag">
              {s.skill} · {s.priority} · {s.assessment_method} · {s.min_duration_minutes} min
            </span>
            <div style={{ fontSize: 12, color: '#444' }}>{s.evidence_to_look_for}</div>
          </div>
        ))}
      </div>

      {optional_skills?.length > 0 && (
        <div className="section">
          <h4>Optional skills</h4>
          {optional_skills.map((s) => (
            <span className="tag" key={s.skill}>
              {s.skill}
            </span>
          ))}
        </div>
      )}

      <div className="section">
        <h4>Resume probing — {resume_probing.required ? 'required' : 'not required'}</h4>
        <ul style={{ fontSize: 13, marginTop: 4 }}>
          {resume_probing.sample_questions.map((q) => (
            <li key={q}>{q}</li>
          ))}
        </ul>
      </div>

      <div className="section">
        <h4>
          Behavioral — {behavioral_assessment.required ? 'required' : 'not required'}
        </h4>
        <ul style={{ fontSize: 13, marginTop: 4 }}>
          {behavioral_assessment.sample_questions.map((q) => (
            <li key={q}>{q}</li>
          ))}
        </ul>
      </div>

      <div className="section">
        <h4>Evaluation criteria</h4>
        {evaluation_criteria.map((c) => (
          <span className="tag" key={c.name}>
            {c.name} · {c.weight}
          </span>
        ))}
      </div>

      <div className="section">
        <h4>Red flags</h4>
        <ul style={{ fontSize: 13, marginTop: 4 }}>
          {red_flags.map((f) => (
            <li key={f}>{f}</li>
          ))}
        </ul>
      </div>

      <div className="section">
        <h4>Green flags</h4>
        <ul style={{ fontSize: 13, marginTop: 4 }}>
          {green_flags.map((f) => (
            <li key={f}>{f}</li>
          ))}
        </ul>
      </div>

      <div className="section">
        <h4>Interviewer guidance</h4>
        <ul style={{ fontSize: 13, marginTop: 4 }}>
          {interviewer_guidance.dos.map((d) => (
            <li key={d}>DO — {d}</li>
          ))}
          {interviewer_guidance.donts.map((d) => (
            <li key={d}>DON'T — {d}</li>
          ))}
        </ul>
      </div>

      <details>
        <summary style={{ cursor: 'pointer', fontSize: 13 }}>Raw JSON</summary>
        <pre>{JSON.stringify(expectation, null, 2)}</pre>
      </details>
    </div>
  )
}
