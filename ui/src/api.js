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

export const listTraitDimensions = () => request('/trait-dimensions')

// Drafts the role-fact checklist from a JD. Nothing is stored — the operator
// edits the drafts before the interview is created.
export const draftRoleFacts = (body) =>
  request('/role-facts', { method: 'POST', body: JSON.stringify(body) })

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

// --- Session recording -------------------------------------------------------

// Raw bytes, not JSON — bypasses request()'s JSON header.
export const appendRecordingChunk = async (sessionId, seq, blob) => {
  const res = await fetch(`/api/v1/sessions/${sessionId}/recording/chunks?seq=${seq}`, {
    method: 'POST',
    body: blob,
    headers: { 'Content-Type': blob.type || 'audio/webm' },
  })
  if (!res.ok) throw new Error(`recording chunk ${seq} rejected (${res.status})`)
  return res.json()
}

export const finalizeRecording = (sessionId) =>
  request(`/sessions/${sessionId}/recording/finalize`, { method: 'POST' })

export const recordingUrl = (sessionId) => `/api/v1/sessions/${sessionId}/recording`

export const recordingDownloadUrl = (sessionId) =>
  `/api/v1/sessions/${sessionId}/recording`

// The report is generated once and stored, so a score a trainer has already
// discussed cannot move under them. Regenerating is this explicit POST.
export const generateReport = (sessionId, { englishWeight = null, languageGate = false } = {}) => {
  const params = new URLSearchParams()
  if (englishWeight !== null) params.set('english_weight', String(englishWeight))
  if (languageGate) params.set('language_gate', 'true')
  const query = params.toString()
  return request(`/sessions/${sessionId}/report${query ? `?${query}` : ''}`, { method: 'POST' })
}

export const getReport = (sessionId) => request(`/sessions/${sessionId}/report`)

// The console embeds this rather than re-drawing the report, so the page on
// screen and the page that prints are the same document.
export const reportHtmlUrl = (sessionId, detail = false) =>
  `/api/v1/sessions/${sessionId}/report.html${detail ? '?detail=1' : ''}`

// Analysis reads the audio and takes about a minute, so it starts a background
// job and returns immediately. The caller polls until the status settles.
export const startAnalysis = (sessionId) =>
  request(`/sessions/${sessionId}/analyze`, { method: 'POST' })

export const getAnalysisStatus = (sessionId) => request(`/sessions/${sessionId}/analysis`)

export const getAnalysisBody = (sessionId) => request(`/sessions/${sessionId}/analysis/full`)
