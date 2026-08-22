// Thin fetch wrapper over the control-plane API. Vite proxies /api -> :8081.

async function request(path, options = {}) {
  const res = await fetch(`/api/v1${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  const body = await res.text()
  const parsed = body ? JSON.parse(body) : null
  if (!res.ok) {
    const detail = parsed?.detail
    throw new Error(
      typeof detail === 'string' ? detail : JSON.stringify(detail ?? parsed ?? res.statusText),
    )
  }
  return parsed
}

export const listInterviews = () => request('/interviews')

export const createInterview = (payload) =>
  request('/interviews', { method: 'POST', body: JSON.stringify(payload) })

export const generateExpectation = (id) =>
  request(`/interviews/${id}/expectation`, { method: 'POST' })

export const getExpectation = (id) => request(`/interviews/${id}/expectation`)

export const listArchetypes = () => request('/candidate-archetypes')

export const listCandidates = (id) => request(`/interviews/${id}/candidates`)

export const enrollCandidates = (id, body) =>
  request(`/interviews/${id}/candidates`, {
    method: 'POST',
    body: JSON.stringify(body ?? {}),
  })

export const deleteCandidate = (cid) =>
  request(`/candidates/${cid}`, { method: 'DELETE' })

// --- Live text sessions -----------------------------------------------------

export const startSession = (interviewId, archetype, plannedMinutes = 20) =>
  request('/sessions', {
    method: 'POST',
    body: JSON.stringify({
      interview_id: interviewId,
      archetype,
      planned_minutes: plannedMinutes,
    }),
  })

export const takeTurn = (sessionId, text) =>
  request(`/sessions/${sessionId}/turns`, {
    method: 'POST',
    body: JSON.stringify({ text }),
  })

export const endSession = (sessionId) =>
  request(`/sessions/${sessionId}/end`, { method: 'POST' })

export const getSession = (sessionId) => request(`/sessions/${sessionId}`)

// Summaries, not transcripts — the detail screen's table.
export const listSessions = (interviewId) => request(`/interviews/${interviewId}/sessions`)

// --- Voice sessions ---------------------------------------------------------

export const getVoiceCapability = () => request('/voice-capability')

export const startVoiceSession = (interviewId, archetype, plannedMinutes = 20) =>
  request('/sessions', {
    method: 'POST',
    body: JSON.stringify({
      interview_id: interviewId,
      archetype,
      planned_minutes: plannedMinutes,
      modality: 'voice',
    }),
  })

export const mintRealtimeCredential = (sessionId) =>
  request(`/sessions/${sessionId}/realtime`, { method: 'POST' })

export const appendTranscript = (sessionId, speaker, text) =>
  request(`/sessions/${sessionId}/transcript`, {
    method: 'POST',
    body: JSON.stringify({ speaker, text }),
  })
