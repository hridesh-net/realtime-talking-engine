/**
 * The persona picker: a list of archetypes and a sticky detail panel.
 *
 * Everything on screen comes from GET /api/v1/candidate-archetypes. The icons
 * are the one exception — they are presentation, so they live here rather than
 * putting emoji in the domain catalog. An unmapped key still renders.
 */

const ICONS = {
  cooperative_trap: '🤝',
  evasive: '🤐',
  nervous_fresher: '🙂',
  inflated_resume: '😎',
  comp_first: '💰',
  defensive: '😤',
  rambler: '🗣️',
}

const TRAIT_ORDER = [
  ['smartness', 'Smartness'],
  ['nervousness', 'Nervousness'],
  ['honesty', 'Honesty'],
  ['effort', 'Effort'],
  ['interest', 'Interest'],
  ['preparedness', 'Preparedness'],
]

const band = ([lo, hi]) => (lo === hi ? `${lo}` : `${lo}–${hi}`)

/**
 * @param archetypes  catalog rows
 * @param criteria    [{id, label}] — the fixed rubric, from the API
 * @param stressLabels ["light", ...] — index 0 means a stress of 1
 * @param actions     rendered inside the detail panel's footer
 */
export default function PersonaPicker({
  archetypes,
  criteria = [],
  stressLabels = [],
  selected,
  onSelect,
  actions,
}) {
  const p = archetypes.find((a) => a.key === selected) || archetypes[0]
  if (!p) return <div className="loading">Loading personas…</div>

  return (
    <div className="picklayout">
      <div className="plist">
        {archetypes.map((a) => (
          <button
            type="button"
            key={a.key}
            className={`pcard ${a.key === p.key ? 'on' : ''}`}
            onClick={() => onSelect(a.key)}
          >
            <div className="pi">{ICONS[a.key] || '👤'}</div>
            <div style={{ flex: 1 }}>
              <div className="pt">{a.label}</div>
              <div className="pd">{a.interviewer_challenge}</div>
              <div className="hard">
                {a.tags.map((t) => (
                  <span className="pill amber" key={t}>
                    {t}
                  </span>
                ))}
                {a.is_default && <span className="pill blue">default</span>}
              </div>
            </div>
          </button>
        ))}
      </div>

      <div className="detail card">
        <div className="row" style={{ gap: 16, alignItems: 'flex-start' }}>
          <div className="dv">{ICONS[p.key] || '👤'}</div>
          <div>
            <div className="h2">{p.label}</div>
            <div className="muted small" style={{ marginTop: 4 }}>
              {p.description}
            </div>
          </div>
        </div>

        <div style={{ marginTop: 16 }}>
          <div className="eyebrow">Trait bounds</div>
          <div className="traits">
            {TRAIT_ORDER.filter(([k]) => p.trait_bounds[k]).map(([k, label]) => (
              <div className="t" key={k}>
                <span>{label}</span>
                <b>{band(p.trait_bounds[k])}</b>
              </div>
            ))}
          </div>
          <div className="muted small" style={{ marginTop: 8 }}>
            A different person is cast each time — name, background and exact scores move
            inside these bounds. The type does not.
          </div>
        </div>

        <div style={{ marginTop: 16 }}>
          <div className="eyebrow">What they tend to do</div>
          <ul className="runlist">
            {p.session_beats.map((b) => (
              <li key={b}>{b}</li>
            ))}
          </ul>
          <div className="muted small" style={{ marginTop: 8 }}>
            These shape how the persona is cast, so they usually show up. Nothing forces
            them at a fixed moment.
          </div>
        </div>

        <div style={{ marginTop: 16 }}>
          <div className="eyebrow">Stresses these skills most</div>
          {criteria.map((c) => {
            const level = p.stresses[c.id] || 0
            return (
              <div style={{ marginTop: 8 }} key={c.id}>
                <div className="between small">
                  <span>{c.label}</span>
                  <span className="muted">{level ? stressLabels[level - 1] : '—'}</span>
                </div>
                <div className="stressbar">
                  {[1, 2, 3, 4].map((i) => (
                    <i key={i} className={i <= level ? 'on' : ''} />
                  ))}
                </div>
              </div>
            )
          })}
          <div className="muted small" style={{ marginTop: 10 }}>
            Which manager competencies this persona puts under pressure. Nothing is scored
            yet — the report arrives with the evaluation layer.
          </div>
        </div>

        {actions && <div className="actions">{actions(p)}</div>}
      </div>
    </div>
  )
}
