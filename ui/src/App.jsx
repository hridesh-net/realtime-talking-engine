import { useEffect, useState } from 'react'
import {
  createInterview,
  deleteCandidate,
  enrollCandidates,
  getVoiceCapability,
  listArchetypes,
  listCandidates,
  listInterviews,
  listSessions,
  startSession,
  startVoiceSession,
} from './api'
import InterviewDetail from './InterviewDetail'
import InterviewList from './InterviewList'
import SessionView from './SessionView'
import Shell from './Shell'
import VoiceSessionView from './VoiceSessionView'
import Wizard from './Wizard'

/**
 * Screen switch for the console. Four screens, one `useState` — a router would
 * be a dependency to express `if`.
 */
export default function App() {
  const [screen, setScreen] = useState('list')
  const [interviews, setInterviews] = useState([])
  const [selected, setSelected] = useState(null)
  const [candidates, setCandidates] = useState([])
  const [sessions, setSessions] = useState([])
  const [catalog, setCatalog] = useState({ archetypes: [], rubric_criteria: [], stress_labels: [] })
  const [session, setSession] = useState(null)
  const [voiceCap, setVoiceCap] = useState(null)
  const [busy, setBusy] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    listInterviews().then(setInterviews).catch((e) => setError(e.message))
    listArchetypes().then(setCatalog).catch((e) => setError(e.message))
    // Voice is a deployment capability, not a feature flag — ask the server
    // rather than guessing from the UI whether a key is configured.
    getVoiceCapability()
      .then(setVoiceCap)
      .catch(() => setVoiceCap({ available: false, detail: 'voice check failed' }))
  }, [])

  const loadInterview = async (iv) => {
    setSelected(iv)
    setCandidates([])
    setSessions([])
    setScreen('detail')
    try {
      const [cs, ss] = await Promise.all([listCandidates(iv.id), listSessions(iv.id)])
      setCandidates(cs)
      setSessions(ss)
    } catch (e) {
      setError(e.message)
    }
  }

  const refreshDetail = async () => {
    if (!selected) return
    try {
      const [cs, ss] = await Promise.all([
        listCandidates(selected.id),
        listSessions(selected.id),
      ])
      setCandidates(cs)
      setSessions(ss)
    } catch {
      /* the screen still holds the last good data */
    }
  }

  const openSession = async (interviewId, archetype, modality) => {
    const open = modality === 'voice' ? startVoiceSession : startSession
    const s = await open(interviewId, archetype, selected?.config?.duration_minutes ?? 20)
    setSession(s)
    setScreen('session')
  }

  const startFromDetail = async (archetype, modality) => {
    setError(null)
    setBusy(`${modality}:${archetype}`)
    try {
      await openSession(selected.id, archetype, modality)
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(null)
    }
  }

  const createFromWizard = async (payload, archetype, action) => {
    setError(null)
    setBusy(action)
    try {
      const created = await createInterview(payload)
      setInterviews(await listInterviews())
      if (action === 'open') {
        await loadInterview(created)
      } else {
        setSelected(created)
        await openSession(created.id, archetype, action)
      }
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(null)
    }
  }

  const enroll = async (keys) => {
    setError(null)
    setBusy(`enroll:${keys[0]}`)
    try {
      await enrollCandidates(selected.id, { archetypes: keys })
      await refreshDetail()
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(null)
    }
  }

  const enrollCustom = async (customPersonas) => {
    setError(null)
    setBusy('enroll:custom')
    try {
      await enrollCandidates(selected.id, { custom_personas: customPersonas })
      await refreshDetail()
    } catch (e) {
      setError(e.message)
      throw e
    } finally {
      setBusy(null)
    }
  }

  const removeCandidate = async (cid) => {
    setError(null)
    try {
      await deleteCandidate(cid)
      await refreshDetail()
    } catch (e) {
      setError(e.message)
    }
  }

  const leaveSession = async () => {
    setSession(null)
    setScreen('detail')
    // A session may have cast a persona on the fly, and it is now a table row.
    await refreshDetail()
  }

  const shared = {
    archetypes: catalog.archetypes,
    criteria: catalog.rubric_criteria,
    stressLabels: catalog.stress_labels,
    voiceCap,
    busy,
  }

  if (screen === 'session' && session) {
    const View = session.modality === 'voice' ? VoiceSessionView : SessionView
    return (
      <Shell
        crumbs={[
          { label: 'Interview Training', onClick: () => setScreen('list') },
          { label: selected?.job_title || 'Interview', onClick: () => setScreen('detail') },
          { label: session.candidate_name },
        ]}
      >
        <View
          session={session}
          personaLabel={
            catalog.archetypes.find((a) => a.key === session.persona_key)?.label
          }
          onExit={leaveSession}
        />
      </Shell>
    )
  }

  return (
    <Shell
      crumbs={
        screen === 'list'
          ? [{ label: 'Dashboard' }, { label: 'Interview Training' }]
          : screen === 'create'
            ? [
                { label: 'Interview Training', onClick: () => setScreen('list') },
                { label: 'New interview' },
              ]
            : [
                { label: 'Interview Training', onClick: () => setScreen('list') },
                { label: selected?.job_title || 'Interview' },
              ]
      }
    >
      {error && <div className="error">{error}</div>}

      {screen === 'list' && (
        <InterviewList
          interviews={interviews}
          onOpen={loadInterview}
          onCreate={() => setScreen('create')}
        />
      )}

      {screen === 'create' && catalog.archetypes.length > 0 && (
        <Wizard
          {...shared}
          onCancel={() => setScreen('list')}
          onSubmit={createFromWizard}
        />
      )}

      {screen === 'detail' && selected && (
        <InterviewDetail
          {...shared}
          interview={selected}
          candidates={candidates}
          sessions={sessions}
          onStart={startFromDetail}
          onEnroll={enroll}
          onEnrollCustom={enrollCustom}
          onDeleteCandidate={removeCandidate}
          onBack={() => setScreen('list')}
        />
      )}
    </Shell>
  )
}
