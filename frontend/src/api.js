/**
 * API client for MM Validator backend.
 * Token is held in memory (never localStorage) for security.
 */
import axios from 'axios'

const BASE = import.meta.env.VITE_API_URL || ''

const client = axios.create({ baseURL: BASE })

// Inject Bearer token from in-memory store
let _token = null
export const setToken = (t) => { _token = t }
export const clearToken = () => { _token = null }

client.interceptors.request.use((config) => {
  if (_token) config.headers.Authorization = `Bearer ${_token}`
  return config
})

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
