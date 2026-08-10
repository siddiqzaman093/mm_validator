import { useEffect, useState } from 'react'

/** Live progress card for a background validation job.
 *
 * `job` is the polled job status ({ status, progress_pct, progress_stage,
 * ai_done, ai_total, created_at }). Elapsed time is computed from the job's
 * created_at so it stays correct across page refreshes.
 */
export default function ValidationProgress({ job }) {
  const [, force] = useState(0)

  useEffect(() => {
    const id = setInterval(() => force(n => n + 1), 1000)   // tick elapsed
    return () => clearInterval(id)
  }, [])

  const queued = !job || job.status === 'queued'
  const pct = queued ? 0 : Math.min(100, job.progress_pct ?? 0)
  const stage = queued
    ? 'Waiting in queue…'
    : (job.progress_stage || 'Working…')
  const aiSuffix = job?.ai_total > 0 ? ` — AI items ${job.ai_done}/${job.ai_total}` : ''

  let elapsed = 0
  if (job?.created_at) {
    const iso = job.created_at.endsWith('Z') || job.created_at.includes('+')
      ? job.created_at : job.created_at + 'Z'
    elapsed = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000)
  }

  return (
    <div className="card p-6">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-3">
          <svg className="animate-spin w-5 h-5 text-blue-600 shrink-0" fill="none" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
          </svg>
          <div>
            <p className="text-sm font-semibold text-slate-800">Validating…</p>
            <p className="text-xs text-slate-500">{stage}{aiSuffix}</p>
          </div>
        </div>
        <div className="text-right">
          <span className="text-xs font-mono text-slate-400 tabular-nums">{elapsed.toFixed(0)}s</span>
          <p className="text-xs text-slate-400">{pct}%</p>
        </div>
      </div>

      <div className="h-2 w-full rounded-full bg-slate-100 overflow-hidden">
        <div
          className="h-full bg-blue-600 rounded-full transition-all duration-300 ease-out"
          style={{ width: `${pct}%` }}
        />
      </div>

      <p className="mt-3 text-xs text-slate-400">
        This validation runs on the server — you can close this page and pick the
        result up later under <span className="font-medium">Past Validations</span>.
      </p>
    </div>
  )
}
