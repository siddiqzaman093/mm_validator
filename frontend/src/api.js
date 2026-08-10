/**
 * API client for MM Validator backend.
 *
 * The session (token + user info) lives in sessionStorage so a browser
 * refresh doesn't log the user out. sessionStorage is tab-scoped — closing
 * the tab ends the session — and the JWT itself expires after 8 hours, so
 * the exposure window stays small. (Deliberately NOT localStorage: that
 * would persist across browser restarts.)
 */
import axios from 'axios'

const BASE = import.meta.env.VITE_API_URL || ''
const SESSION_KEY = 'mm_validator_session'

const client = axios.create({ baseURL: BASE })

// Token is mirrored in memory; sessionStorage is only read on page load.
let _token = null

export function saveSession({ token, username, name, role }) {
  _token = token
  try { sessionStorage.setItem(SESSION_KEY, JSON.stringify({ token, username, name, role })) } catch { /* private mode */ }
}

export function restoreSession() {
  try {
    const s = JSON.parse(sessionStorage.getItem(SESSION_KEY) || 'null')
    if (s?.token) { _token = s.token; return s }
  } catch { /* corrupt entry — treat as logged out */ }
  return null
}

export function clearSession() {
  _token = null
  try { sessionStorage.removeItem(SESSION_KEY) } catch { /* ignore */ }
}

client.interceptors.request.use((config) => {
  if (_token) config.headers.Authorization = `Bearer ${_token}`
  return config
})

// A 401 on any authenticated call means the token expired (8h) or was
// invalidated server-side: drop the stored session and return to login.
// Login's own 401 (wrong credentials) must NOT trigger this.
client.interceptors.response.use(
  (res) => res,
  (err) => {
    const status = err?.response?.status
    const url = err?.config?.url || ''
    if (status === 401 && !url.includes('/api/auth/login')) {
      clearSession()
      window.location.assign('/login')
    }
    return Promise.reject(err)
  }
)

// ---- Warm-up / keep-alive ----
// Fire-and-forget ping to wake (and keep awake) the free-tier backend so it
// isn't cold-starting when the user actually runs a validation.
export async function pingHealth() {
  try { await client.get('/api/health') } catch { /* server may be waking — ignore */ }
}

// ---- Auth ----
export async function login(username, password) {
  const form = new URLSearchParams({ username, password })
  const res = await client.post('/api/auth/login', form, {
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  })
  return res.data // { access_token, token_type }
}

// ---- Validate ----
export async function validateFile({ file, lookupFile, useAi, apiKey, model, provider }) {
  const form = new FormData()
  form.append('file', file)
  if (lookupFile) form.append('lookup_file', lookupFile)
  form.append('use_ai', String(useAi))
  form.append('api_key', apiKey || '')
  form.append('model', model || 'claude-haiku-4-5')
  form.append('provider', provider || 'anthropic')
  const res = await client.post('/api/validate', form)
  return res.data // ValidationReport JSON + html_report
}

// ---- Background validation jobs ----
// Submit returns immediately with a job id; the validation runs server-side
// and survives dropped connections, closed tabs and server restarts.
export async function submitJob({ file, lookupFile, useAi, model, provider }) {
  const form = new FormData()
  form.append('file', file)
  if (lookupFile) form.append('lookup_file', lookupFile)
  form.append('use_ai', String(useAi))
  form.append('model', model || '')
  form.append('provider', provider || '')
  const res = await client.post('/api/jobs', form)
  return res.data // { job_id }
}

export async function fetchJob(jobId) {
  const res = await client.get(`/api/jobs/${jobId}`)
  return res.data // { status, progress_pct, progress_stage, ai_done, ai_total, … }
}

export async function fetchJobs() {
  const res = await client.get('/api/jobs')
  return res.data.jobs // newest first
}

export async function fetchJobResult(jobId) {
  const res = await client.get(`/api/jobs/${jobId}/result`)
  return res.data // full ValidationReport JSON (+ html_report, job_id)
}

export async function downloadJobCsv(jobId) {
  const res = await client.get(`/api/jobs/${jobId}/csv`, { responseType: 'blob' })
  return res.data // Blob
}

// ---- Full findings CSV (server-side, complete even when the JSON response
// carries only the most severe findings) ----
export async function downloadFindingsCsv(reportId) {
  const res = await client.get(`/api/validate/report/${reportId}`, { responseType: 'blob' })
  return res.data // Blob
}

// ---- Admin: usage log / dashboard ----
export async function fetchUsage(days = 30) {
  const res = await client.get('/api/admin/usage', { params: { days } })
  return res.data // { days, storage, totals, per_user, sessions }
}

export async function fetchActiveRuns() {
  const res = await client.get('/api/admin/active')
  return res.data // { runs: [{username, file_name, ai_enabled, elapsed_s, stage, pct, ai_done, ai_total}] }
}
