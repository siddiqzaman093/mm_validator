import { useCallback, useEffect, useRef, useState } from 'react'
import { fetchJobs, fetchJobResult, downloadJobCsv } from '../api'
import ResultsView from '../components/ResultsView'

const STATUS_STYLES = {
  done:    'bg-emerald-100 text-emerald-700',
  running: 'bg-blue-100 text-blue-700',
  queued:  'bg-slate-100 text-slate-600',
  failed:  'bg-red-100 text-red-700',
}

const fmtDate = (iso) => {
  if (!iso) return '—'
  const d = new Date(iso.endsWith('Z') || iso.includes('+') ? iso : iso + 'Z')
  return d.toLocaleString(undefined, {
    year: 'numeric', month: 'short', day: '2-digit',
    hour: '2-digit', minute: '2-digit',
  })
}

const fmtDuration = (ms) => {
  if (!ms) return '—'
  const s = Math.round(ms / 1000)
  return s >= 60 ? `${Math.floor(s / 60)}m ${s % 60}s` : `${s}s`
}

export default function ValidationsPage() {
  const [jobs, setJobs]       = useState(null)   // null = loading
  const [error, setError]     = useState('')
  const [report, setReport]   = useState(null)
  const [viewing, setViewing] = useState('')     // job id whose result is shown
  const resultsRef = useRef(null)

  const load = useCallback(async () => {
    try {
      setJobs(await fetchJobs())
      setError('')
    } catch (err) {
      setError(err?.response?.data?.detail || 'Failed to load validations.')
    }
  }, [])

  // Refresh the list; poll faster while something is still running.
  useEffect(() => {
    load()
    const id = setInterval(() => {
      load()
    }, 5000)
    return () => clearInterval(id)
  }, [load])

  async function viewResult(job) {
    try {
      const data = await fetchJobResult(job.id)
      setReport(data)
      setViewing(job.id)
      setTimeout(() => resultsRef.current?.scrollIntoView({ behavior: 'smooth' }), 50)
    } catch {
      setError('Result no longer available — validations are kept for 30 days.')
    }
  }

  async function csv(job) {
    try {
      const blob = await downloadJobCsv(job.id)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url; a.download = `${job.file_name}.findings.csv`; a.click()
      URL.revokeObjectURL(url)
    } catch {
      setError('CSV no longer available — validations are kept for 30 days.')
    }
  }

  return (
    <div className="max-w-7xl mx-auto space-y-6">
      <div>
        <h2 className="text-xl font-bold text-slate-800">Past Validations</h2>
        <p className="text-sm text-slate-500 mt-0.5">
          Validations run in the background on the server — results are kept for 30 days,
          even if you closed the browser while they ran.
        </p>
      </div>

      {error && (
        <div className="p-4 rounded-xl bg-red-50 border border-red-200 text-red-700 text-sm">{error}</div>
      )}

      <div className="card p-6">
        {jobs === null ? (
          <p className="text-sm text-slate-400">Loading…</p>
        ) : jobs.length === 0 ? (
          <p className="text-sm text-slate-400">
            No validations yet — run one from the Validator page.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm whitespace-nowrap">
              <thead>
                <tr className="text-left text-xs text-slate-500 uppercase tracking-wider border-b border-slate-200">
                  <th className="py-2 pr-4">Date / Time</th>
                  <th className="py-2 pr-4">File</th>
                  <th className="py-2 pr-4">Status</th>
                  <th className="py-2 pr-4 text-right">Readiness</th>
                  <th className="py-2 pr-4 text-right">Errors</th>
                  <th className="py-2 pr-4 text-right">Warnings</th>
                  <th className="py-2 pr-4 text-right">Duration</th>
                  <th className="py-2">Actions</th>
                </tr>
              </thead>
              <tbody>
                {jobs.map((j) => (
                  <tr key={j.id} className={`border-b border-slate-100 last:border-0 ${viewing === j.id ? 'bg-blue-50/50' : ''}`}>
                    <td className="py-2 pr-4 text-slate-600">{fmtDate(j.created_at)}</td>
                    <td className="py-2 pr-4 text-slate-700 max-w-[240px] truncate" title={j.file_name}>
                      {j.file_name}
                      {j.use_ai && (
                        <span className="ml-2 px-1.5 py-0.5 rounded bg-violet-100 text-violet-700 text-xs font-semibold">AI</span>
                      )}
                    </td>
                    <td className="py-2 pr-4">
                      <span
                        className={`px-2 py-0.5 rounded-full text-xs font-semibold ${STATUS_STYLES[j.status] || STATUS_STYLES.queued}`}
                        title={j.status === 'failed' ? j.error : undefined}
                      >
                        {j.status}
                      </span>
                      {(j.status === 'running' || j.status === 'queued') && (
                        <span className="ml-2 text-xs text-slate-500">
                          {j.progress_pct ?? 0}% · {(j.progress_stage || '').slice(0, 40)}
                        </span>
                      )}
                    </td>
                    <td className="py-2 pr-4 text-right">
                      {j.readiness_score == null ? '—' : `${j.readiness_score}/100`}
                    </td>
                    <td className="py-2 pr-4 text-right">{j.status === 'done' ? j.errors.toLocaleString() : '—'}</td>
                    <td className="py-2 pr-4 text-right">{j.status === 'done' ? j.warnings.toLocaleString() : '—'}</td>
                    <td className="py-2 pr-4 text-right text-slate-500">{fmtDuration(j.duration_ms)}</td>
                    <td className="py-2">
                      {j.status === 'done' && (
                        <div className="flex gap-2">
                          <button onClick={() => viewResult(j)} className="text-blue-600 hover:text-blue-800 text-xs font-semibold">
                            View results
                          </button>
                          <button onClick={() => csv(j)} className="text-slate-500 hover:text-slate-700 text-xs font-semibold">
                            CSV
                          </button>
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Selected result rendered with the standard results view */}
      {report && (
        <div ref={resultsRef}>
          <ResultsView report={report} />
        </div>
      )}
    </div>
  )
}
