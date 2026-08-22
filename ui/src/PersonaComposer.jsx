import { useEffect, useState } from 'react'
import { listTraitDimensions } from './api'

/**
 * Compose a brand-new persona from the BRD §3.2 trait taxonomy instead of
 * picking a fixed archetype. Every dropdown/checkbox option comes from
 * GET /trait-dimensions, never hardcoded here — the taxonomy's vocabulary is
 * validated server-side (candidate_agent/trait_dimensions.py), so a stale
 * client-side copy can never drift into something the server rejects.
 */

const languageRadarAxes = (languagePreset) =>
  languagePreset
    ? [
        { label: 'Fluency', value: languagePreset.fluency * 10 },
        { label: 'Accent strength', value: languagePreset.accent_strength * 100 },
        { label: 'Code-switching', value: languagePreset.code_switch_probability * 100 },
      ]
    : []

const EMPTY_PERSONA = {
  label: '',
  verdict: 'borderline',
  competence: '',
  conscientiousness: '',
  communication: '',
  emotional_stance: '',
  honesty: '',
  bias_trap: '',
  affect: '',
  verbal_style: '',
  language: '',
  comprehension: '',
  motivation: '',
  negotiation_stance: '',
  environment: '',
  seniority: 'junior',
  function: '',
  region: '',
  gender_presentation: '',
  age_band: '',
  notice_period: 'immediate',
  compliance_traps: [],
  protected_info_type: '',
  integrity_red_flags: [],
  offers_in_hand: 0,
}

function RadarChart({ axes, size = 200 }) {
  if (!axes.length) return null
  const cx = size / 2
  const cy = size / 2
  const radius = size / 2 - 44
  const n = axes.length
  const angleFor = (i) => (Math.PI * 2 * i) / n - Math.PI / 2
  const pointFor = (i, valuePct) => {
    const r = (Math.max(0, Math.min(100, valuePct)) / 100) * radius
    const a = angleFor(i)
    return [cx + r * Math.cos(a), cy + r * Math.sin(a)]
  }
  const ringPoints = (frac) => axes.map((_, i) => pointFor(i, frac * 100).join(',')).join(' ')
  const dataPoints = axes.map((ax, i) => pointFor(i, ax.value))

  return (
    <svg width={size} height={size} className="radar-chart">
      {[0.25, 0.5, 0.75, 1].map((f) => (
        <polygon key={f} points={ringPoints(f)} className="radar-grid" />
      ))}
      {axes.map((_, i) => {
        const [x, y] = pointFor(i, 100)
        return <line key={i} x1={cx} y1={cy} x2={x} y2={y} className="radar-spoke" />
      })}
      <polygon points={dataPoints.map((p) => p.join(',')).join(' ')} className="radar-shape" />
      {dataPoints.map(([x, y], i) => (
        <circle key={i} cx={x} cy={y} r={4} className="radar-dot" />
      ))}
      {axes.map((ax, i) => {
        const [lx, ly] = pointFor(i, 130)
        return (
          <text key={`l-${i}`} x={lx} y={ly - 4} textAnchor="middle" className="radar-label">
            {ax.label}
          </text>
        )
      })}
      {axes.map((ax, i) => {
        const [lx, ly] = pointFor(i, 130)
        return (
          <text key={`v-${i}`} x={lx} y={ly + 10} textAnchor="middle" className="radar-value">
            {Math.round(ax.value)}
          </text>
        )
      })}
    </svg>
  )
}

export default function PersonaComposer({ busy, onCast }) {
  const [dims, setDims] = useState(null)
  const [form, setForm] = useState(EMPTY_PERSONA)
  const [batch, setBatch] = useState([])
  const [error, setError] = useState(null)

  useEffect(() => {
    listTraitDimensions()
      .then((d) => {
        setDims(d)
        setForm((f) => ({
          ...f,
          competence: Object.keys(d.competence)[0],
          conscientiousness: Object.keys(d.conscientiousness)[0],
          communication: Object.keys(d.communication)[0],
          emotional_stance: Object.keys(d.emotional_stance)[0],
          honesty: Object.keys(d.honesty)[0],
          affect: d.affect[0],
          verbal_style: d.verbal_style[0],
          language: Object.keys(d.language)[0],
          comprehension: Object.keys(d.comprehension)[0],
          motivation: d.motivation[0],
          negotiation_stance: d.negotiation_stance[0],
          environment: Object.keys(d.environment)[0],
        }))
      })
      .catch((e) => setError(e.message))
  }, [])

  if (!dims) return <div className="loading">Loading trait taxonomy…</div>

  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value })
  const toggle = (key, value) =>
    setForm((f) => ({
      ...f,
      [key]: f[key].includes(value) ? f[key].filter((v) => v !== value) : [...f[key], value],
    }))

  const addToBatch = () => {
    if (!form.label.trim()) {
      setError('Give the persona a label before adding it to the batch.')
      return
    }
    setError(null)
    setBatch((b) => [...b, form])
    setForm((f) => ({ ...EMPTY_PERSONA, ...f, label: '' }))
  }

  const removeFromBatch = (i) => setBatch((b) => b.filter((_, idx) => idx !== i))

  const cast = async () => {
    setError(null)
    try {
      await onCast(batch)
      setBatch([])
    } catch (e) {
      setError(e.message)
    }
  }

  const selectField = (label, key, options, withHint = false) => (
    <div className="field">
      <label>{label}</label>
      <select value={form[key]} onChange={set(key)}>
        {Array.isArray(options)
          ? options.map((v) => (
              <option key={v} value={v}>
                {v}
              </option>
            ))
          : Object.entries(options).map(([k, v]) => (
              <option key={k} value={k} title={withHint ? v : undefined}>
                {k}
              </option>
            ))}
      </select>
    </div>
  )

  return (
    <div>
      {error && <div className="error">{error}</div>}
      <div className="composer-layout">
        <div className="composer-fields">
          <div className="field">
            <label>Label</label>
            <input
              value={form.label}
              onChange={set('label')}
              placeholder="e.g. Guarded network technician, career gap"
            />
          </div>

          <div className="field-row">
            <div className="field">
              <label>Verdict</label>
              <select value={form.verdict} onChange={set('verdict')}>
                <option value="select">select</option>
                <option value="reject">reject</option>
                <option value="borderline">borderline</option>
              </select>
            </div>
            {selectField('Competence', 'competence', dims.competence, true)}
          </div>

          <div className="field-row">
            {selectField('Conscientiousness', 'conscientiousness', dims.conscientiousness, true)}
            {selectField('Communication', 'communication', dims.communication, true)}
          </div>

          <div className="field-row">
            {selectField('Emotional stance', 'emotional_stance', dims.emotional_stance, true)}
            {selectField('Honesty', 'honesty', dims.honesty, true)}
          </div>

          <div className="field">
            <label>Bias trap (optional)</label>
            <select value={form.bias_trap} onChange={set('bias_trap')}>
              <option value="">(none — generic structured-probing signal)</option>
              {Object.entries(dims.bias_trap).map(([k, v]) => (
                <option key={k} value={k} title={v}>
                  {k}
                </option>
              ))}
            </select>
          </div>

          <div className="field-row">
            {selectField('Affect / disposition', 'affect', dims.affect)}
            {selectField('Verbal style', 'verbal_style', dims.verbal_style)}
          </div>

          <div className="field-row">
            {selectField('Language & literacy', 'language', Object.keys(dims.language))}
            {selectField('Comprehension', 'comprehension', Object.keys(dims.comprehension))}
          </div>

          <div className="field-row">
            {selectField('Motivation', 'motivation', dims.motivation)}
            {selectField('Negotiation stance', 'negotiation_stance', dims.negotiation_stance)}
          </div>

          <div className="field">
            <label>Compliance traps</label>
            <div className="chip-row">
              {dims.compliance_traps.map((v) => (
                <label key={v} className="chip-checkbox">
                  <input
                    type="checkbox"
                    checked={form.compliance_traps.includes(v)}
                    onChange={() => toggle('compliance_traps', v)}
                  />
                  {v}
                </label>
              ))}
            </div>
          </div>

          {form.compliance_traps.includes('volunteers_protected_info') && (
            <div className="field">
              <label>Protected info type</label>
              <select value={form.protected_info_type} onChange={set('protected_info_type')}>
                <option value="">(choose one)</option>
                {dims.protected_info_types.map((v) => (
                  <option key={v} value={v}>
                    {v}
                  </option>
                ))}
              </select>
            </div>
          )}

          <div className="field">
            <label>Integrity red flags</label>
            <div className="chip-row">
              {dims.integrity_red_flags.map((v) => (
                <label key={v} className="chip-checkbox">
                  <input
                    type="checkbox"
                    checked={form.integrity_red_flags.includes(v)}
                    onChange={() => toggle('integrity_red_flags', v)}
                  />
                  {v}
                </label>
              ))}
            </div>
          </div>

          {selectField('Environment', 'environment', Object.keys(dims.environment))}

          <div className="field-row">
            <div className="field">
              <label>Seniority</label>
              <input value={form.seniority} onChange={set('seniority')} />
            </div>
            <div className="field">
              <label>Function</label>
              <input value={form.function} onChange={set('function')} placeholder="network, sales, ..." />
            </div>
          </div>
          <div className="field-row">
            <div className="field">
              <label>Region</label>
              <input value={form.region} onChange={set('region')} />
            </div>
            <div className="field">
              <label>Gender presentation</label>
              <input value={form.gender_presentation} onChange={set('gender_presentation')} />
            </div>
          </div>
          <div className="field-row">
            <div className="field">
              <label>Age band</label>
              <input value={form.age_band} onChange={set('age_band')} placeholder="25-34" />
            </div>
            <div className="field">
              <label>Notice period</label>
              <input value={form.notice_period} onChange={set('notice_period')} />
            </div>
          </div>
          <div className="field">
            <label>Offers in hand</label>
            <input type="number" min="0" value={form.offers_in_hand} onChange={set('offers_in_hand')} />
          </div>

          <button className="btn" onClick={addToBatch}>
            Add to batch
          </button>
        </div>

        <div className="composer-preview">
          <div className="radar-card">
            <RadarChart axes={languageRadarAxes(dims.language[form.language])} />
          </div>
          <div className="small muted" style={{ textAlign: 'center', marginTop: 4 }}>
            numeric axes for &quot;{form.language || '—'}&quot;
          </div>

          <div className="batch-list">
            {batch.length === 0 && <div className="loading">No custom personas queued yet.</div>}
            {batch.map((spec, i) => (
              <div key={i} className="batch-item">
                <span>
                  {spec.label} <span className={`badge ${spec.verdict === 'reject' ? 'flag' : spec.verdict === 'select' ? 'draft' : 'running'}`}>{spec.verdict}</span>
                </span>
                <button className="btn sm" onClick={() => removeFromBatch(i)}>
                  Remove
                </button>
              </div>
            ))}
          </div>

          <button
            className="btn primary"
            style={{ marginTop: 8, width: '100%' }}
            disabled={Boolean(busy) || batch.length === 0}
            onClick={cast}
          >
            {busy === 'enroll:custom' ? 'Casting…' : `Cast ${batch.length} custom persona(s)`}
          </button>
        </div>
      </div>
    </div>
  )
}
