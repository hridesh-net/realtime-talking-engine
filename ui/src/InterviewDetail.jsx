import { useEffect, useState } from 'react'
import { getSession } from './api'
import PersonaComposer from './PersonaComposer'
import PersonaPicker from './PersonaPicker'

/**
 * One interview: what has been run against it, and who can be run next.
 *
 * The mockup's version of this screen is a manager cohort with readiness scores
 * and bias flags. There is no manager roster and no evaluation layer, so this
 * lists the thing that does exist — the sessions held — and the side panel shows
 * a transcript rather than a report.
 */

const initials = (name) =>
  name
    .split(/\s+/)
    .slice(0, 2)
    .map((w) => w[0])
    .join('')
    .toUpperCase()

const fmtWhen = (iso) => new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })

const STATUS = {
  live: { cls: 'running', text: '● Live' },
  completed: { cls: 'draft', text: '✓ Completed' },
  abandoned: { cls: 'flag', text: '⚠ Abandoned' },
}

export default function InterviewDetail({
  interview,
  candidates,
  sessions,
  archetypes,
  criteria,
  stressLabels,
  voiceCap,
  busy,
  onStart,
  onEnroll,
  onEnrollCustom,
  onDeleteCandidate,
  onBack,
}) {
  const [tab, setTab] = useState('sessions')
  const [persona, setPersona] = useState(archetypes[0]?.key)
  const [openSession, setOpenSession] = useState(null)
  const [transcript, setTranscript] = useState(null)

  useEffect(() => {
    if (!openSession) return
    setTranscript(null)
    getSession(openSession).then(setTranscript).catch(() => setTranscript(null))
  }, [openSession])

  const completed = sessions.filter((s) => s.status === 'completed').length
  const enrolled = new Set(candidates.map((c) => c.archetype))

  return (
    <>
      <div className="card">
        <div className="between">
          <div>
            <div className="row">
              <h1 className="h1">{interview.job_title}</h1>
              <span className="badge running">▷ {interview.status.replace(/_/g, ' ')}</span>
            </div>
            <div className="sub">
              {interview.experience_level} · {interview.company_type} ·{' '}
              {interview.job_location_type} · {interview.config.duration_minutes} min ·{' '}
              {candidates.length} persona{candidates.length === 1 ? '' : 's'} cast
            </div>
          </div>
          <div className="row">
            <button className="btn" onClick={onBack}>
              ← All interviews
            </button>
          </div>
        </div>
      </div>

      <div className="tabs">
        <button
          type="button"
          className={`tab ${tab === 'sessions' ? 'active' : ''}`}
          onClick={() => setTab('sessions')}
        >
          <span>👥</span> Sessions <span className="n">{sessions.length}</span>
        </button>
        <button
          type="button"
          className={`tab ${tab === 'practise' ? 'active' : ''}`}
          onClick={() => setTab('practise')}
        >
          <span>🎓</span> Practise
        </button>
        <button
          type="button"
          className={`tab ${tab === 'personas' ? 'active' : ''}`}
          onClick={() => setTab('personas')}
        >
          <span>🎭</span> Cast <span className="n">{candidates.length}</span>
        </button>
        <button
          type="button"
          className={`tab ${tab === 'compose' ? 'active' : ''}`}
          onClick={() => setTab('compose')}
        >
          <span>🧬</span> Compose
        </button>
      </div>

      {tab === 'sessions' && (
        <>
          <div className="grid4">
            <div className="card">
              <div className="muted">Sessions held</div>
              <div className="h1" style={{ marginTop: 6 }}>
                {sessions.length}
              </div>
              <div className="muted">
                {sessions.filter((s) => s.modality === 'voice').length} spoken
              </div>
            </div>
            <div className="card">
              <div className="muted">Completed</div>
              <div className="h1" style={{ marginTop: 6 }}>
                {completed}{' '}
                <span className="muted" style={{ fontSize: 14, fontWeight: 400 }}>
                  / {sessions.length}
                </span>
              </div>
              <div className="bar">
                <i
                  style={{
                    width: `${sessions.length ? (completed / sessions.length) * 100 : 0}%`,
                  }}
                />
              </div>
            </div>
            <div className="card">
              <div className="muted">Personas cast</div>
              <div className="h1" style={{ marginTop: 6 }}>
                {candidates.length}
              </div>
              <div className="muted">of {archetypes.length} types</div>
            </div>
            <div className="card">
              <div className="muted">Readiness</div>
              <div className="h1" style={{ marginTop: 6, color: 'var(--ink-4)' }}>
                —
              </div>
              <div className="muted">no evaluation layer yet</div>
            </div>
          </div>

          <div className="between" style={{ margin: '22px 0 12px' }}>
            <h2 className="h2">Sessions</h2>
            <button className="btn primary" onClick={() => setTab('practise')}>
              <span>🎓</span> Start a session
            </button>
          </div>

          <div className="layout-rail" style={{ gridTemplateColumns: '1fr 380px' }}>
            <div className="card" style={{ padding: 0 }}>
              {sessions.length === 0 ? (
                <div style={{ padding: 20 }}>
                  <div className="h2">No sessions yet</div>
                  <div className="sub">
                    Open the Practise tab, pick a persona and start talking.
                  </div>
                </div>
              ) : (
                <table className="tbl">
                  <thead>
                    <tr>
                      <th>Candidate</th>
                      <th>Mode</th>
                      <th>Turns</th>
                      <th>Started</th>
                      <th>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sessions.map((s) => (
                      <tr
                        key={s.id}
                        className={openSession === s.id ? 'sel' : ''}
                        onClick={() => setOpenSession(s.id)}
                      >
                        <td>
                          <div className="who">
                            <div className="av">{initials(s.candidate_name)}</div>
                            <div>
                              <div className="nm">{s.candidate_name}</div>
                              <div className="mt">
                                {archetypes.find((a) => a.key === s.persona_key)?.label ||
                                  s.persona_key}
                              </div>
                            </div>
                          </div>
                        </td>
                        <td>
                          <span className="pill">
                            {s.modality === 'voice' ? '🎙 voice' : '⌨ chat'}
                          </span>
                        </td>
                        <td>{s.turn_count}</td>
                        <td className="small muted">{fmtWhen(s.started_at)}</td>
                        <td>
                          <span className={`badge ${STATUS[s.status]?.cls || 'draft'}`}>
                            {STATUS[s.status]?.text || s.status}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>

            <aside className="card">
              {!openSession && (
                <>
                  <div className="eyebrow">Transcript</div>
                  <div className="loading">Select a session to read its transcript.</div>
                  <div className="tip" style={{ marginTop: 12 }}>
                    The transcript is the record the evaluation layer will read when it
                    lands. Every turn was stamped by the server, not the browser.
                  </div>
                </>
              )}
              {openSession && !transcript && <div className="loading">Loading…</div>}
              {transcript && (
                <>
                  <div className="between">
                    <div className="who">
                      <div className="av">{initials(transcript.candidate_name)}</div>
                      <div>
                        <div className="nm" style={{ fontSize: 17 }}>
                          {transcript.candidate_name}
                        </div>
                        <div className="mt">
                          {transcript.modality} · {transcript.turns.length} turns
                        </div>
                      </div>
                    </div>
                    <span className="iconbtn" onClick={() => setOpenSession(null)}>
                      ✕
                    </span>
                  </div>
                  <div className="transcript" style={{ marginTop: 14 }}>
                    {transcript.turns.length === 0 && (
                      <div className="loading">Nothing was said.</div>
                    )}
                    {transcript.turns.map((t) => (
                      <div className="line" key={t.index}>
                        <span className="sp">
                          {t.speaker === 'manager' ? 'Manager' : 'Candidate'}
                        </span>
                        <div>{t.text}</div>
                      </div>
                    ))}
                  </div>
                </>
              )}
            </aside>
          </div>
        </>
      )}

      {tab === 'practise' && (
        <div className="card">
          <div className="sechead">
            <span className="secnum">▶</span>
            <span className="h2">Start a session</span>
            <span className="note">
              A different person of the chosen type is cast each time.
            </span>
          </div>
          {voiceCap && !voiceCap.available && (
            <div className="banner warn" style={{ marginBottom: 16 }}>
              <span className="k">VOICE OFF</span>
              <span>{voiceCap.detail}</span>
            </div>
          )}
          <PersonaPicker
            archetypes={archetypes}
            criteria={criteria}
            stressLabels={stressLabels}
            selected={persona}
            onSelect={setPersona}
            actions={(p) => (
              <>
                {!enrolled.has(p.key) && (
                  <button
                    className="btn"
                    disabled={Boolean(busy)}
                    onClick={() => onEnroll([p.key])}
                    title="Cast this persona without starting a session"
                  >
                    {busy === `enroll:${p.key}` ? 'Casting…' : 'Cast only'}
                  </button>
                )}
                <button
                  className="btn"
                  disabled={Boolean(busy)}
                  onClick={() => onStart(p.key, 'text')}
                >
                  {busy === `text:${p.key}` ? 'Casting…' : '⌨ Chat'}
                </button>
                <button
                  className="btn primary"
                  disabled={Boolean(busy) || !voiceCap?.available}
                  title={voiceCap?.available ? 'Spoken interview' : voiceCap?.detail}
                  onClick={() => onStart(p.key, 'voice')}
                >
                  {busy === `voice:${p.key}` ? 'Casting…' : '🎙 Voice'}
                </button>
              </>
            )}
          />
        </div>
      )}

      {tab === 'personas' && (
        <div className="card">
          <div className="sechead">
            <span className="secnum">🎭</span>
            <span className="h2">Personas cast for this interview</span>
            <span className="note">
              Each is one specific person, grounded in this job spec.
            </span>
          </div>
          {candidates.length === 0 && (
            <div className="loading">
              Nothing cast yet. Starting a session casts the persona it needs.
            </div>
          )}
          {candidates.map((c) => (
            <CandidateCard
              key={c.candidate_id}
              c={c}
              onDelete={onDeleteCandidate}
              onStart={onStart}
              busy={busy}
              voiceReady={Boolean(voiceCap?.available)}
            />
          ))}
        </div>
      )}

      {tab === 'compose' && (
        <div className="card">
          <div className="sechead">
            <span className="secnum">🧬</span>
            <span className="h2">Compose a custom persona</span>
            <span className="note">
              Pick a value for each dimension below — any combination is valid. The radar
              plots this exact persona's selected competence, effort, composure, honesty,
              comprehension, and fluency.
            </span>
          </div>
          <PersonaComposer busy={busy} onCast={onEnrollCustom} />
        </div>
      )}
    </>
  )
}

function Trait({ label, value }) {
  return (
    <div className="t">
      <span>{label}</span>
      <b>{value}</b>
    </div>
  )
}

function HumanTraits({ traits }) {
  const env = traits.environment
  const watch = [
    ...traits.compliance_traps.map((t) =>
      t === 'volunteers_protected_info' && traits.protected_info_type
        ? `${t} (${traits.protected_info_type})`
        : t,
    ),
    ...traits.integrity_red_flags,
  ]
  return (
    <details className="human-traits" open>
      <summary>Human traits (§3.2 taxonomy)</summary>
      <div className="row">
        <span className="pill">{traits.affect}</span> <span className="pill">{traits.verbal_style}</span>{' '}
        <span className="pill">{traits.motivation}</span> <span className="pill">{traits.negotiation_stance}</span>
      </div>
      <div className="row">
        <b>Language:</b> fluency {traits.fluency}/10, {traits.literacy_level},{' '}
        {traits.native_speaker ? 'native' : 'non-native'} speaker, accent {traits.accent_strength}, code-switch{' '}
        {traits.code_switch_probability}, {traits.vocabulary_ceiling} vocabulary
      </div>
      <div className="row">
        <b>Comprehension:</b> clarification rate {traits.clarification_rate}, misinterprets{' '}
        {traits.misinterprets_question_rate}
        {traits.needs_rephrasing ? ', often needs rephrasing' : ''}
      </div>
      {watch.length > 0 && (
        <div className="row watch">
          <b>Watch for:</b> {watch.join(', ')}
        </div>
      )}
      <div className="row">
        <b>Environment:</b> camera {env.camera_behavior}, {env.background_noise}
        {env.joins_late_minutes ? `, joins ${env.joins_late_minutes}m late` : ', on time'}
        {env.network_drops_at_minute ? `, network drops ~min ${env.network_drops_at_minute}` : ''}
        {env.mobile_or_driving ? ', mobile/driving' : ''}
        {env.hard_stop_minute ? `, hard stop at min ${env.hard_stop_minute}` : ''}
      </div>
      <div className="row">
        <b>Profile:</b> {traits.seniority} · {traits.function} · {traits.region} · {traits.gender_presentation} ·{' '}
        {traits.age_band} · notice {traits.notice_period} · {traits.offers_in_hand} offer(s) in hand
      </div>
    </details>
  )
}

function CandidateCard({ c, onDelete, onStart, busy, voiceReady }) {
  const a = c.aptitude
  return (
    <div className="card" style={{ marginTop: 14 }}>
      <div className="between">
        <div className="who">
          <div className="av">{initials(c.name)}</div>
          <div>
            <div className="nm" style={{ fontSize: 16 }}>
              {c.name}
            </div>
            <div className="mt">
              {c.archetype_label} · {c.years_experience}y · {c.headline}
            </div>
          </div>
        </div>
        <div className="row">
          <button
            className="btn sm"
            disabled={Boolean(busy)}
            onClick={() => onStart(c.archetype, 'text')}
          >
            ⌨ Chat
          </button>
          <button
            className="btn sm primary"
            disabled={Boolean(busy) || !voiceReady}
            onClick={() => onStart(c.archetype, 'voice')}
          >
            🎙 Voice
          </button>
          <button className="btn sm danger" onClick={() => onDelete(c.candidate_id)}>
            Remove
          </button>
        </div>
      </div>

      <div className="traits" style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8, marginTop: 14 }}>
        <Trait label="Smartness" value={a.smartness} />
        <Trait label="Honesty" value={a.honesty} />
        <Trait label="Effort" value={a.effort} />
        <Trait label="Nerves" value={a.nervousness} />
      </div>

      <div className="row" style={{ marginTop: 12, flexWrap: 'wrap' }}>
        <span className="pill blue">
          {c.speech_profile.pace} · {c.speech_profile.verbosity}
        </span>
        {c.knowledge_map.map((k) => (
          <span className="pill" key={k.skill}>
            {k.skill} {k.level}/10
          </span>
        ))}
      </div>

      <div className="small muted" style={{ marginTop: 10 }}>
        <b>Opens up when:</b> {c.answer_policy.reveals_depth_when}
      </div>

      {c.human_traits && <HumanTraits traits={c.human_traits} />}

      <details className="raw">
        <summary>Compiled persona prompt — do not show the manager</summary>
        <pre>{c.engine_contract.system_prompt}</pre>
      </details>
      <details className="raw">
        <summary>Interviewer scorecard (ground truth)</summary>
        <pre>{JSON.stringify(c.interviewer_scorecard, null, 2)}</pre>
      </details>
    </div>
  )
}
