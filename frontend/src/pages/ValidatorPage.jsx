import { useState, useRef, useEffect, useCallback } from 'react'
import { submitJob, fetchJob, fetchJobResult, pingHealth } from '../api'
import { AI_PROVIDER, AI_MODEL } from '../aiConfig'
import ValidationProgress from '../components/ValidationProgress'
import ResultsView from '../components/ResultsView'

// Survives page refreshes: a running job is picked back up on load.
const ACTIVE_JOB_KEY = 'mm_validator_active_job'

/** Reusable drag-and-drop file picker. */
function DropZone({ file, onFile, accept, title, hint, required, disabled }) {
  const [dragging, setDrag] = useState(false)
  const inputRef = useRef(null)

  function handleDrop(e) {
    e.preventDefault(); setDrag(false)
    if (disabled) return
    const f = e.dataTransfer.files[0]
    if (f) onFile(f)
  }

  return (
    <div>
      <label className="block text-sm font-medium text-slate-700 mb-2">
        {title}
        {required && <span className="text-red-500 ml-1">*</span>}
      </label>
      <div
        onDragOver={e => { e.preventDefault(); if (!disabled) setDrag(true) }}
        onDragLeave={() => setDrag(false)}
        onDrop={handleDrop}
        onClick={() => { if (!disabled) inputRef.current?.click() }}
        className={`relative flex flex-col items-center justify-center h-32 rounded-xl border-2 border-dashed transition-colors
          ${disabled
            ? 'border-slate-200 bg-slate-50 opacity-60 cursor-not-allowed'
            : dragging ? 'border-blue-400 bg-blue-50 cursor-pointer'
            : 'border-slate-300 hover:border-blue-400 hover:bg-slate-50 cursor-pointer'}`}
      >
        <input
          ref={inputRef}
          type="file"
          accept={accept}
          className="hidden"
          onChange={e => onFile(e.target.files[0] ?? null)}
        />
        {file ? (
          <div className="flex items-center gap-3 text-blue-700 px-4">
            <svg className="w-7 h-7 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
            <div className="min-w-0">
              <p className="font-semibold text-sm truncate">{file.name}</p>
              <p className="text-xs text-blue-500">{(file.size / 1024).toFixed(1)} KB — click to change</p>
            </div>
          </div>
        ) : (
          <>
            <svg className="w-8 h-8 text-slate-300 mb-1.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
            </svg>
            <p className="text-xs text-slate-500 px-4 text-center">{hint}</p>
          </>
        )}
      </div>
    </div>
  )
}

export default function ValidatorPage() {
  // Upload state
  const [lookupFile, setLookupFile] = useState(null)
  const [file, setFile]             = useState(null)

  // Settings — only the AI toggle is user-facing; provider/key/model are hardcoded.
  const [useAi, setUseAi] = useState(false)

  // Job / results state
  const [jobId, setJobId]   = useState(() => sessionStorage.getItem(ACTIVE_JOB_KEY) || null)
  const [job, setJob]       = useState(null)
  const [error, setError]   = useState('')
  const [report, setReport] = useState(null)

  const running = Boolean(jobId)

  // Warm up the backend when the page opens, and keep it awake during the
  // session, so the free-tier server isn't cold when Run Validation is clicked.
  useEffect(() => {
    pingHealth()
    const id = setInterval(pingHealth, 10 * 60 * 1000)  // every 10 min
    return () => clearInterval(id)
  }, [])

  const clearActiveJob = useCallback(() => {
    setJobId(null)
    setJob(null)
    sessionStorage.removeItem(ACTIVE_JOB_KEY)
  }, [])

  // Poll the active job until it finishes; also resumes after a page refresh.
  useEffect(() => {
    if (!jobId) return
    let alive = true

    async function poll() {
      try {
        const j = await fetchJob(jobId)
        if (!alive) return
        setJob(j)
        if (j.status === 'done') {
          const data = await fetchJobResult(jobId)
          if (!alive) return
          setReport(data)
          clearActiveJob()
        } else if (j.status === 'failed') {
          setError(j.error || 'Validation failed. Please try again.')
          clearActiveJob()
        }
      } catch (err) {
        if (!alive) return
        if (err?.response?.status === 404) {   // expired/unknown job
          setError('This validation is no longer available — please run it again.')
          clearActiveJob()
        }
        // other errors (network blip, waking server): keep polling
      }
    }

    poll()
    const id = setInterval(poll, 2500)
    return () => { alive = false; clearInterval(id) }
  }, [jobId, clearActiveJob])

  async function handleValidate() {
    if (!file || !lookupFile || running) return
    setError(''); setReport(null); setJob(null)
    try {
      const { job_id } = await submitJob({
        file, lookupFile, useAi,
        provider: AI_PROVIDER,
        model:    AI_MODEL,
        // no apiKey — the backend supplies it from its env var
      })
      sessionStorage.setItem(ACTIVE_JOB_KEY, job_id)
      setJobId(job_id)
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not start the validation. Please try again.')
    }
  }

  return (
    <div className="max-w-7xl mx-auto space-y-6">
      {/* Page header */}
      <div>
        <h2 className="text-xl font-bold text-slate-800">Material Master Validator</h2>
        <p className="text-sm text-slate-500 mt-0.5">
          Upload the Master Lookup File and a SAP Migration Cockpit <em>Product Master Creation</em> template to run data-quality checks.
        </p>
      </div>

      {/* Upload + settings card */}
      <div className="card p-6">
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">

          {/* Drop zones */}
          <div className="lg:col-span-2 space-y-4">
            <DropZone
              file={lookupFile}
              onFile={setLookupFile}
              accept=".xlsx"
              title="Step 1 — Master Lookup File"
              required
              disabled={running}
              hint="Drop Product Master Lookup File .xlsx here, or click to browse"
            />
            <DropZone
              file={file}
              onFile={setFile}
              accept=".xls,.xlsx"
              title="Step 2 — Material Master Data"
              required
              disabled={running}
              hint="Drop Product Master Creation .xls or .xlsx here, or click to browse"
            />
            {!lookupFile && (
              <p className="text-xs text-amber-600 flex items-center gap-1.5">
                <svg className="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M12 9v2m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                The lookup file is required — it defines authoritative SAP field types,
                per-material-type mandatory fields, and plant→profit-center mappings.
              </p>
            )}
          </div>

          {/* Settings panel — Validator section (AI toggle only) */}
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">AI-Enabled Validations</label>
              <div className="flex items-center gap-3">
                <button
                  onClick={() => { if (!running) setUseAi(v => !v) }}
                  disabled={running}
                  className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none
                    ${useAi ? 'bg-blue-600' : 'bg-slate-200'} ${running ? 'opacity-60 cursor-not-allowed' : ''}`}
                >
                  <span className={`inline-block h-4 w-4 rounded-full bg-white shadow transition-transform
                    ${useAi ? 'translate-x-6' : 'translate-x-1'}`} />
                </button>
                <span className="text-sm text-slate-600">{useAi ? 'Enabled' : 'Disabled'}</span>
              </div>
            </div>

            <button
              onClick={handleValidate}
              disabled={!file || !lookupFile || running}
              className="btn-primary w-full justify-center mt-auto"
            >
              {running ? (
                <>
                  <svg className="animate-spin w-4 h-4" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                  </svg>
                  Validating…
                </>
              ) : (
                <>
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                      d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  Run Validation
                </>
              )}
            </button>
          </div>
        </div>
      </div>

      {/* Live progress from the server while the job runs */}
      {running && <ValidationProgress job={job} />}

      {/* Error banner */}
      {error && (
        <div className="p-4 rounded-xl bg-red-50 border border-red-200 text-red-700 text-sm">
          {error}
        </div>
      )}

      {/* Results */}
      {report && <ResultsView report={report} />}
    </div>
  )
}
