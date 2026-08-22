import { useState } from 'react'
import PersonaComposer from './PersonaComposer'
import PersonaPicker from './PersonaPicker'

/**
 * New interview, in the mockup's two steps.
 *
 * Step 1 renders only the fields the API accepts. The mockup also shows
 * Location, Department, Manager level, opening Language and Proctoring — none
 * of those exist on `InterviewCreateRequest`, and the pivot plan replaces this
 * whole schema with a role card, so they are not stubbed in here.
 */

const EMPTY = {
  job_title: 'Frontline Sales Executive',
  jd: 'Sell SIM and broadband plans at retail touchpoints. Handle walk-in customers, pitch and close upgrades. Daily targets, rotational shifts.',
  job_location_type: 'onsite',
  experience_level: 'junior',
  company_type: 'mnc',
  mode: 'training_interviewer',
  duration_minutes: 20,
}

const START_SKILLS = [
  'Customer handling',
  'Target orientation',
  'Product knowledge',
  'Upselling',
]

const DURATIONS = [15, 20, 30, 45]

function Chips({ options, value, onChange }) {
  return (
    <div className="seg radio">
      {options.map((o) => (
        <span
          key={o}
          className={`chip ${value === o ? 'on' : ''}`}
          onClick={() => onChange(o)}
        >
          {String(o)}
        </span>
      ))}
    </div>
  )
}

export default function Wizard({
  archetypes,
  criteria,
  stressLabels,
  voiceCap,
  busy,
  onCancel,
  onSubmit,
  onSubmitCustom,
}) {
  const [step, setStep] = useState(1)
  const [form, setForm] = useState(EMPTY)
  const [skills, setSkills] = useState(START_SKILLS)
  const [skillDraft, setSkillDraft] = useState('')
  const [persona, setPersona] = useState(archetypes[0]?.key)
  const [pickMode, setPickMode] = useState('catalog')
  const [customSpec, setCustomSpec] = useState(null)

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value })
  const pick = (k) => (v) => setForm({ ...form, [k]: v })

  const addSkill = (e) => {
    if (e.key !== 'Enter') return
    e.preventDefault()
    const s = skillDraft.trim()
    if (s && !skills.includes(s)) setSkills([...skills, s])
    setSkillDraft('')
  }

  const payload = () => ({
    job_title: form.job_title,
    jd: form.jd,
    skills_required: skills,
    job_location_type: form.job_location_type,
    experience_level: form.experience_level,
    company_type: form.company_type,
    mode: form.mode,
    config: { duration_minutes: Number(form.duration_minutes) },
  })

  const canAdvance = form.job_title.trim() && form.jd.trim() && skills.length > 0

  return (
    <>
      <h1 className="h1">New interview</h1>
      <div className="sub" style={{ marginBottom: 18 }}>
        Set the role, then pick who your managers practise against.
      </div>

      <div className="stepper">
        <div className={`step ${step === 1 ? 'active' : 'done'}`}>
          <span className="dot">1</span>Basics
        </div>
        <div className={`step-line ${step > 1 ? 'done' : ''}`} />
        <div className={`step ${step === 2 ? 'active' : ''}`}>
          <span className="dot">2</span>Candidate
        </div>
      </div>

      {step === 1 && (
        <>
          <div className="card">
            <div className="sechead">
              <span className="secnum">1</span>
              <span className="h2">Basics</span>
              <span className="note">
                Only the essentials. Everything else has a sensible default.
              </span>
            </div>

            <div className="field">
              <label>
                Job title <span className="req">*</span>
              </label>
              <input className="input" value={form.job_title} onChange={set('job_title')} />
            </div>

            <div className="field">
              <label>
                Job description <span className="req">*</span>
              </label>
              <textarea className="textarea" value={form.jd} onChange={set('jd')} />
              <div className="help">
                The persona's background and knowledge are grounded in this. Keep it
                concrete.
              </div>
            </div>

            <div className="field">
              <label>
                Skills to check <span className="req">*</span>
              </label>
              <div className="seg">
                {skills.map((s) => (
                  <span key={s} className="chip on">
                    {s}
                    <span
                      className="x"
                      title="Remove"
                      onClick={() => setSkills(skills.filter((x) => x !== s))}
                    >
                      ×
                    </span>
                  </span>
                ))}
              </div>
              <input
                className="input"
                style={{ marginTop: 8 }}
                placeholder="Add a skill and press Enter"
                value={skillDraft}
                onChange={(e) => setSkillDraft(e.target.value)}
                onKeyDown={addSkill}
              />
              <div className="help">
                Every persona gets a knowledge level for each of these, clamped to their
                archetype's band.
              </div>
            </div>

            <div className="grid3">
              <div className="field">
                <label>Experience level</label>
                <Chips
                  options={['junior', 'mid', 'senior']}
                  value={form.experience_level}
                  onChange={pick('experience_level')}
                />
              </div>
              <div className="field">
                <label>Location type</label>
                <Chips
                  options={['onsite', 'hybrid', 'remote']}
                  value={form.job_location_type}
                  onChange={pick('job_location_type')}
                />
              </div>
              <div className="field">
                <label>Company type</label>
                <Chips
                  options={['startup', 'mnc']}
                  value={form.company_type}
                  onChange={pick('company_type')}
                />
              </div>
            </div>

            <div className="grid2">
              <div className="field">
                <label>Duration</label>
                <Chips
                  options={DURATIONS}
                  value={Number(form.duration_minutes)}
                  onChange={pick('duration_minutes')}
                />
              </div>
              <div className="field">
                <label>Mode</label>
                <Chips
                  options={['training_interviewer', 'live_interview']}
                  value={form.mode}
                  onChange={pick('mode')}
                />
                <div className="help">
                  Training mode is the manager-upskilling flow this console is built for.
                </div>
              </div>
            </div>
          </div>

          <div className="actions">
            <button className="btn" onClick={onCancel}>
              Cancel
            </button>
            <button
              className="btn primary"
              disabled={!canAdvance}
              onClick={() => setStep(2)}
            >
              Next: pick a candidate →
            </button>
          </div>
        </>
      )}

      {step === 2 && (
        <>
          <div className="card">
            <div className="sechead">
              <span className="secnum">2</span>
              <span className="h2">Who will they interview?</span>
              <span className="note">
                Pick one candidate type. A different person of that type is cast each
                session.
              </span>
            </div>

            <div className="seg radio" style={{ marginBottom: 16 }}>
              <span
                className={`chip ${pickMode === 'catalog' ? 'on' : ''}`}
                onClick={() => setPickMode('catalog')}
              >
                Pick from catalog
              </span>
              <span
                className={`chip ${pickMode === 'custom' ? 'on' : ''}`}
                onClick={() => setPickMode('custom')}
              >
                Compose custom
              </span>
            </div>

            {pickMode === 'catalog' && (
              <PersonaPicker
                archetypes={archetypes}
                criteria={criteria}
                stressLabels={stressLabels}
                selected={persona}
                onSelect={setPersona}
                actions={(p) => (
                  <>
                    <button
                      className="btn"
                      disabled={Boolean(busy)}
                      onClick={() => onSubmit(payload(), p.key, 'open')}
                    >
                      {busy === 'open' ? 'Creating…' : 'Create interview'}
                    </button>
                    <button
                      className="btn"
                      disabled={Boolean(busy)}
                      onClick={() => onSubmit(payload(), p.key, 'text')}
                    >
                      {busy === 'text' ? 'Casting…' : 'Create & chat'}
                    </button>
                    <button
                      className="btn primary"
                      disabled={Boolean(busy) || !voiceCap?.available}
                      title={voiceCap?.available ? 'Spoken interview' : voiceCap?.detail}
                      onClick={() => onSubmit(payload(), p.key, 'voice')}
                    >
                      {busy === 'voice' ? 'Casting…' : '🎙 Create & talk'}
                    </button>
                  </>
                )}
              />
            )}

            {pickMode === 'custom' && (
              <>
                <PersonaComposer singleMode busy={busy} onChange={setCustomSpec} />
                <div className="actions" style={{ marginTop: 16 }}>
                  <button
                    className="btn"
                    disabled={Boolean(busy) || !customSpec?.label.trim()}
                    onClick={() => onSubmitCustom(payload(), customSpec, 'open')}
                  >
                    {busy === 'open' ? 'Creating…' : 'Create interview'}
                  </button>
                  <button
                    className="btn"
                    disabled={Boolean(busy) || !customSpec?.label.trim()}
                    onClick={() => onSubmitCustom(payload(), customSpec, 'text')}
                  >
                    {busy === 'text' ? 'Casting…' : 'Create & chat'}
                  </button>
                  <button
                    className="btn primary"
                    disabled={Boolean(busy) || !customSpec?.label.trim() || !voiceCap?.available}
                    title={voiceCap?.available ? 'Spoken interview' : voiceCap?.detail}
                    onClick={() => onSubmitCustom(payload(), customSpec, 'voice')}
                  >
                    {busy === 'voice' ? 'Casting…' : '🎙 Create & talk'}
                  </button>
                </div>
                {!customSpec?.label.trim() && (
                  <div className="help" style={{ marginTop: 8 }}>
                    Give the persona a label above to enable these.
                  </div>
                )}
              </>
            )}
          </div>

          <div className="actions" style={{ justifyContent: 'space-between' }}>
            <button className="btn" onClick={() => setStep(1)}>
              ← Back
            </button>
            <span className="muted small">
              Creating the interview casts this persona; the others are cast when you
              first use them.
            </span>
          </div>
        </>
      )}
    </>
  )
}
