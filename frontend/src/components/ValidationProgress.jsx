import { useEffect, useRef, useState } from 'react'

// Indicative pipeline stages (the backend returns the result in one response,
// so the bar advances optimistically and completes when the result arrives).
const STAGES_BASE = [
  { until: 12, label: 'Uploading & reading the workbook…' },
  { until: 32, label: 'Checking schema, field types & lengths…' },
  { until: 52, label: 'Running cross-field consistency checks…' },
  { until: 70, label: 'Validating against the lookup file…' },
]
const STAGE_AI    = { until: 92, label: 'Running AI warning-flag checks…' }
const STAGE_FINAL = { until: 101, label: 'Finalizing the report…' }

export default function ValidationProgress({ useAi }) {
  const [pct, setPct] = useState(5)
  const [elapsed, setElapsed] = useState(0)
  const startRef = useRef(null)

  useEffect(() => {
    startRef.current = Date.now()
    const id = setInterval(() => {
      setElapsed((Date.now() - startRef.current) / 1000)
      // Ease toward 95% and hold — never reach 100% until the response lands
      // (this component unmounts) so the bar can't "finish" before the work does.
      setPct(p => (p >= 95 ? 95 : p + (95 - p) * 0.05))
    }, 200)
    return () => clearInterval(id)
  }, [])

  const stages = useAi ? [...STAGES_BASE, STAGE_AI, STAGE_FINAL] : [...STAGES_BASE, STAGE_FINAL]
  const stage = stages.find(s => pct < s.until) ?? stages[stages.length - 1]

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
            <p className="text-xs text-slate-500">{stage.label}</p>
          </div>
        </div>
        <span className="text-xs font-mono text-slate-400 tabular-nums">{elapsed.toFixed(1)}s</span>
      </div>

      <div className="h-2 w-full rounded-full bg-slate-100 overflow-hidden">
        <div
          className="h-full bg-blue-600 rounded-full transition-all duration-200 ease-out"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  )
}
