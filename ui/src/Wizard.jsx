import { useState } from 'react'
import { draftRoleFacts } from './api'
import PersonaPicker from './PersonaPicker'

/**
 * New interview, in the spec's two steps.
 *
 * Step 1 collects every field the training-wizard specification asks for.
 * Proctoring is captured and stored but accesses no camera — see the help text,
 * which says so on screen rather than implying a capability that is not there.
 */

const EMPTY = {
  job_title: 'Frontline Sales Executive',
  jd: 'Sell SIM and broadband plans at retail touchpoints. Handle walk-in customers, pitch and close upgrades. Daily targets, rotational shifts.',
  location: 'Jaipur',
  department: 'Sales',
  manager_level: 'Frontline manager',
  language: 'english_indian',
  proctoring: 'identity',
  job_location_type: 'onsite',
  experience_level: 'junior',
  company_type: 'mnc',
  mode: 'training_interviewer',
  duration_minutes: 20,
  candidate_notes: '',
}

const START_SKILLS = ['Customer handling', 'Target orientation', 'Product knowledge', 'Upselling']

const DEPARTMENTS = [
  'Sales',
  'Network',
  'Marketing',
  'Engineering',
  'Finance',
  'Customer service',
  'Operations',
  'Human resources',
  'Retail',
  'Supply chain',
]

const LANGUAGES = [
  ['english_indian', 'English (Indian)'],
  ['hinglish', 'Hinglish'],
  ['hindi', 'Hindi'],
]

const PROCTORING = [
  ['off', 'Off'],
  ['identity', 'Identity check'],
  ['full', 'Full'],
]

// The checklist is fixed in code server-side (evaluation_agent.schema); these
// are its labels. A fact left blank is not on this interview's checklist.
const FACT_KEYS = [
  ['targets', 'Targets'],
  ['shifts', 'Shifts'],
  ['location', 'Location'],
  ['comp_band', 'Compensation'],
  ['growth_path', 'Growth path'],
  ['next_steps', 'Next steps'],
]

function Chips({ options, value, onChange }) {
  return (
    <div className="seg radio">
      {options.map((o) => {
        const [val, label] = Array.isArray(o) ? o : [o, String(o)]
        return (
          <span
            key={val}
            className={`chip ${value === val ? 'on' : ''}`}
            onClick={() => onChange(val)}
          >
            {label}
          </span>
        )
      })}
    </div>
  )
}

function Combo({ value, options, onChange }) {
  const [open, setOpen] = useState(false)
  const hits = options.filter(
    (d) => d.toLowerCase().includes(value.toLowerCase()) && d.toLowerCase() !== value.toLowerCase(),
  )
  return (
    <div className="combo">
      <input
        className="input"
        value={value}
        placeholder="Start typing…"
        autoComplete="off"
        onChange={(e) => {
          onChange(e.target.value)
          setOpen(true)
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 120)}
      />
      {open && hits.length > 0 && (
        <div className="menu">
          {hits.map((d) => (
            <div
              key={d}
              onMouseDown={() => {
                onChange(d)
                setOpen(false)
              }}
            >
              {d}
            </div>
          ))}
        </div>
      )}
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
}) {
  const [step, setStep] = useState(1)
  const [form, setForm] = useState(EMPTY)
  const [skills, setSkills] = useState(START_SKILLS)
  const [skillDraft, setSkillDraft] = useState('')
  const [facts, setFacts] = useState(() => Object.fromEntries(FACT_KEYS.map(([k]) => [k, ''])))
  const [drafting, setDrafting] = useState(false)
  const [draftError, setDraftError] = useState(null)
  const [persona, setPersona] = useState(archetypes[0]?.key)

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value })
  const pick = (k) => (v) => setForm({ ...form, [k]: v })

  const addSkill = (e) => {
    if (e.key !== 'Enter') return
    e.preventDefault()
    const s = skillDraft.trim()
    if (s && !skills.includes(s)) setSkills([...skills, s])
    setSkillDraft('')
  }

  const autofill = async () => {
    setDraftError(null)
    setDrafting(true)
    try {
      const drafted = await draftRoleFacts({
        job_title: form.job_title,
        jd: form.jd,
        location: form.location,
      })
      setFacts(Object.fromEntries(drafted.map((f) => [f.key, f.statement])))
    } catch (err) {
      setDraftError(err.message)
    } finally {
      setDrafting(false)
    }
  }

  const payload = () => ({
    job_title: form.job_title,
    jd: form.jd,
    skills_required: skills,
    job_location_type: form.job_location_type,
    experience_level: form.experience_level,
    company_type: form.company_type,
    mode: form.mode,
    location: form.location,
    department: form.department,
    manager_level: form.manager_level,
    language: form.language,
    proctoring: form.proctoring,
    candidate_notes: form.candidate_notes,
    // A blank statement means "not on this interview's checklist" and is
    // dropped rather than sent as an unmeetable expectation.
    clarity_facts: FACT_KEYS.filter(([k]) => facts[k]?.trim()).map(([k]) => ({
      key: k,
      statement: facts[k].trim(),
    })),
    config: { duration_minutes: Number(form.duration_minutes) },
  })

  const canAdvance = form.job_title.trim() && form.jd.trim() && skills.length > 0
  const factCount = FACT_KEYS.filter(([k]) => facts[k]?.trim()).length

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

            <div className="grid2">
              <div className="field">
                <label>
                  Job title <span className="req">*</span>
                </label>
                <input className="input" value={form.job_title} onChange={set('job_title')} />
              </div>
              <div className="field">
                <label>Location</label>
                <input
                  className="input"
                  value={form.location}
                  onChange={set('location')}
                  placeholder="e.g. Jaipur"
                />
              </div>
            </div>

            <div className="field">
              <label>
                Job description <span className="req">*</span>
              </label>
              <textarea className="textarea" value={form.jd} onChange={set('jd')} />
              <div className="help">
                The persona's background and knowledge are grounded in this. Keep it concrete.
              </div>
            </div>

            <div className="grid3">
              <div className="field">
                <label>Department</label>
                <Combo
                  value={form.department}
                  options={DEPARTMENTS}
                  onChange={pick('department')}
                />
                <div className="help">Type freely or pick a suggestion.</div>
              </div>
              <div className="field">
                <label>Manager level</label>
                <input
                  className="input"
                  value={form.manager_level}
                  onChange={set('manager_level')}
                  placeholder="e.g. Frontline manager"
                />
              </div>
              <div className="field">
                <label>Duration</label>
                <Chips
                  options={[15, 20, 30]}
                  value={Number(form.duration_minutes)}
                  onChange={pick('duration_minutes')}
                />
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

            <div className="grid2">
              <div className="field">
                <label>Language the candidate opens in</label>
                <Chips options={LANGUAGES} value={form.language} onChange={pick('language')} />
                <div className="help">
                  Reaches the persona's prompt and the speech-to-text hint, not just this label.
                </div>
              </div>
              <div className="field">
                <label>Proctoring</label>
                <Chips options={PROCTORING} value={form.proctoring} onChange={pick('proctoring')} />
                <div className="help">
                  Recorded on the interview. <strong>No camera is accessed yet</strong> at any
                  setting — enforcement needs a data-retention decision first.
                </div>
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
          </div>

          <div className="card">
            <div className="sechead">
              <span className="secnum">2</span>
              <span className="h2">Role facts the manager must convey</span>
              <span className="note">
                {factCount} of {FACT_KEYS.length} on this interview's checklist.
              </span>
            </div>
            <div className="banner" style={{ marginBottom: 16 }}>
              <span className="k">WHY FIXED</span>
              <span>
                The same six facts are checked for every manager, so their scores stay
                comparable. Leave one blank and it drops off this interview's checklist.
              </span>
            </div>

            {draftError && <div className="error">{draftError}</div>}

            <div className="grid2">
              {FACT_KEYS.map(([key, label]) => (
                <div className="field" key={key}>
                  <label>{label}</label>
                  <input
                    className="input"
                    value={facts[key]}
                    placeholder="Leave blank to drop this fact"
                    onChange={(e) => setFacts({ ...facts, [key]: e.target.value })}
                  />
                </div>
              ))}
            </div>

            <button className="btn" onClick={autofill} disabled={drafting || !form.jd.trim()}>
              {drafting ? 'Reading the JD…' : '✨ Auto-fill from the job description'}
            </button>
            <div className="help" style={{ marginTop: 8 }}>
              Drafts each fact from the description above. Anything the description does not
              actually say comes back blank rather than invented — check them before creating.
            </div>
          </div>

          <div className="actions">
            <button className="btn" onClick={onCancel}>
              Cancel
            </button>
            <button className="btn primary" disabled={!canAdvance} onClick={() => setStep(2)}>
              Next: pick a candidate →
            </button>
          </div>
        </>
      )}

      {step === 2 && (
        <>
          <div className="card">
            <div className="sechead">
              <span className="secnum">3</span>
              <span className="h2">Who will they interview?</span>
              <span className="note">
                Pick one candidate type. A different person of that type is cast each session.
              </span>
            </div>

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

            <div className="field" style={{ marginTop: 18 }}>
              <label>
                Additional notes for the candidate{' '}
                <span className="muted" style={{ fontWeight: 400 }}>
                  (optional)
                </span>
              </label>
              <textarea
                className="textarea"
                value={form.candidate_notes}
                onChange={set('candidate_notes')}
                placeholder="Anything the type above doesn't cover. e.g. Candidate has worked at a competitor store in the same mall and mentions it if asked about local market knowledge."
              />
              <div className="help">
                Layered on top of the selected type, within the same safety rails. It adds
                detail — it cannot make the persona more capable than its band, change its
                type, or unlock anything the persona is forbidden to do.
              </div>
            </div>
          </div>

          <div className="actions" style={{ justifyContent: 'space-between' }}>
            <button className="btn" onClick={() => setStep(1)}>
              ← Back
            </button>
            <span className="muted small">
              Creating the interview casts this persona; the others are cast when you first
              use them.
            </span>
          </div>
        </>
      )}
    </>
  )
}
