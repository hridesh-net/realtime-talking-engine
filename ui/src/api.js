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
