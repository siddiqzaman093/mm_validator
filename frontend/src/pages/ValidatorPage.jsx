import { useState, useRef, useEffect } from 'react'
import { validateFile, pingHealth } from '../api'
import { AI_PROVIDER, AI_MODEL, AI_MODEL_LABEL } from '../aiConfig'
import ValidationProgress from '../components/ValidationProgress'
import KPICards from '../components/KPICards'
import FindingsTable from '../components/FindingsTable'
import FindingsByCategory from '../components/FindingsByCategory'
import FindingsBySheet from '../components/FindingsBySheet'

const TABS = ['By Category', 'By Sheet', 'All Findings', 'Downloads']

function downloadBlob(content, filename, mime) {
  const blob = new Blob([content], { type: mime })
  const url  = URL.createObjectURL(blob)
  const a    = document.createElement('a')
  a.href = url; a.download = filename; a.click()
  URL.revokeObjectURL(url)
}

/** Reusable drag-and-drop file picker. */
function DropZone({ file, onFile, accept, title, hint, required }) {
  const [dragging, setDrag] = useState(false)
  const inputRef = useRef(null)

  function handleDrop(e) {
    e.preventDefault(); setDrag(false)
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
        onDragOver={e => { e.preventDefault(); setDrag(true) }}
        onDragLeave={() => setDrag(false)}
        onDrop={handleDrop}
        onClick={() => inputRef.current?.click()}
        className={`relative flex flex-col items-center justify-center h-32 rounded-xl border-2 border-dashed cursor-pointer transition-colors
          ${dragging ? 'border-blue-400 bg-blue-50' : 'border-slate-300 hover:border-blue-400 hover:bg-slate-50'}`}
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

  // Results
  const [loading, setLoading] = useState(false)
  const [error, setError]     = useState('')
  const [report, setReport]   = useState(null)
  const [activeTab, setTab]   = useState(0)

  // Warm up the backend when the page opens, and keep it awake during the
  // session, so the free-tier server isn't cold when Run Validation is clicked.
  useEffect(() => {
    pingHealth()
    const id = setInterval(pingHealth, 10 * 60 * 1000)  // every 10 min
    return () => clearInterval(id)
  }, [])

  async function handleValidate() {
    if (!file || !lookupFile) return
    setLoading(true); setError(''); setReport(null)
    try {
      const data = await validateFile({
        file, lookupFile, useAi,
        provider: AI_PROVIDER,
        model:    AI_MODEL,
        // no apiKey — the backend supplies it from its OPENAI_API_KEY env var
      })
      setReport(data)
      setTab(0)
    } catch (err) {
      setError(err?.response?.data?.detail || 'Validation failed. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  const counts = report?.counts ?? {}
  const statusColor = !report ? '' :
    counts.error   > 0 ? 'border-red-300   bg-red-50   text-red-800' :
    counts.warning > 0 ? 'border-amber-300 bg-amber-50 text-amber-800' :
                         'border-green-300 bg-green-50 text-green-800'
  const statusText = !report ? '' :
    counts.error   > 0 ? `🔴 RED — ${counts.error} error(s) require attention before upload.` :
    counts.warning > 0 ? `🟡 AMBER — ${counts.warning} warning(s), 0 errors.` :
                         `🟢 GREEN — No issues found.`

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
              hint="Drop Product Master Lookup File .xlsx here, or click to browse"
            />
            <DropZone
              file={file}
              onFile={setFile}
              accept=".xls,.xlsx"
              title="Step 2 — Material Master Data"
              required
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
              <label className="block text-sm font-medium text-slate-700 mb-1">AI Warning Flags</label>
              <div className="flex items-center gap-3">
                <button
                  onClick={() => setUseAi(v => !v)}
                  className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none
                    ${useAi ? 'bg-blue-600' : 'bg-slate-200'}`}
                >
                  <span className={`inline-block h-4 w-4 rounded-full bg-white shadow transition-transform
                    ${useAi ? 'translate-x-6' : 'translate-x-1'}`} />
                </button>
                <span className="text-sm text-slate-600">{useAi ? 'Enabled' : 'Disabled'}</span>
              </div>
            </div>

            <button
              onClick={handleValidate}
              disabled={!file || !lookupFile || loading}
              className="btn-primary w-full justify-center mt-auto"
            >
              {loading ? (
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

      {/* Progress indicator while validating */}
      {loading && <ValidationProgress useAi={useAi} />}

      {/* Error banner */}
      {error && (
        <div className="p-4 rounded-xl bg-red-50 border border-red-200 text-red-700 text-sm">
          {error}
        </div>
      )}

      {/* Results */}
      {report && (
        <div className="space-y-4">
          {/* Status banner */}
          <div className={`p-4 rounded-xl border font-medium text-sm ${statusColor}`}>
            {statusText}
            {report.ai_calls > 0 && (
              <span className="ml-3 text-xs opacity-70">
                AI — input: {report.ai_input_tokens} tokens · output: {report.ai_output_tokens} tokens · model: {AI_MODEL_LABEL}
              </span>
            )}
          </div>

          {/* KPI cards */}
          <KPICards counts={counts} report={report} />

          {/* Tabs */}
          {report.findings?.length > 0 ? (
            <div className="card overflow-hidden">
              {/* Tab bar */}
              <div className="flex border-b border-slate-200 bg-slate-50">
                {TABS.map((tab, i) => (
                  <button
                    key={tab}
                    onClick={() => setTab(i)}
                    className={`px-5 py-3 text-sm font-medium transition-colors border-b-2 -mb-px
                      ${activeTab === i
                        ? 'border-blue-600 text-blue-700 bg-white'
                        : 'border-transparent text-slate-500 hover:text-slate-700'}`}
                  >
                    {tab}
                  </button>
                ))}
              </div>

              <div className="p-5">
                {activeTab === 0 && <FindingsByCategory findings={report.findings} />}
                {activeTab === 1 && <FindingsBySheet    findings={report.findings} />}
                {activeTab === 2 && <FindingsTable      findings={report.findings} />}
                {activeTab === 3 && (
                  <div className="space-y-4">
                    <p className="text-sm text-slate-600">Download the full validation results in your preferred format.</p>
                    <div className="flex flex-wrap gap-3">
                      <button
                        onClick={() => downloadBlob(report.html_report, `${report.file_name}.validation-report.html`, 'text/html')}
                        className="btn-primary"
                      >
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                            d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                        </svg>
                        HTML Report
                      </button>
                      <button
                        onClick={() => downloadBlob(
                          JSON.stringify({ ...report, html_report: undefined }, null, 2),
                          `${report.file_name}.validation-report.json`,
                          'application/json'
                        )}
                        className="btn-secondary"
                      >
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                            d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                        </svg>
                        JSON Findings
                      </button>
                      <button
                        onClick={() => {
                          const cols = ['severity','ai_generated','category','sheet','material','row','field','sap_field','value','message','rule_id']
                          const rows = report.findings.map(f => cols.map(c => JSON.stringify(f[c] ?? '')).join(','))
                          const csv  = [cols.join(','), ...rows].join('\n')
                          downloadBlob(csv, `${report.file_name}.findings.csv`, 'text/csv')
                        }}
                        className="btn-secondary"
                      >
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                            d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                        </svg>
                        CSV Findings
                      </button>
                    </div>

                    {/* Inline HTML preview */}
                    <div className="mt-4">
                      <p className="text-sm font-medium text-slate-700 mb-2">HTML Report Preview</p>
                      <iframe
                        srcDoc={report.html_report}
                        className="w-full h-96 rounded-xl border border-slate-200"
                        title="HTML Report Preview"
                        sandbox="allow-same-origin"
                      />
                    </div>
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div className="card p-8 text-center">
              <svg className="w-12 h-12 text-green-400 mx-auto mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                  d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              <p className="text-slate-600 font-medium">No findings — the file looks clean!</p>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
