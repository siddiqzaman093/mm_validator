import { useState } from 'react'
import SeverityBadge from './SeverityBadge'

// Rows rendered inside one expanded group. ResultsView owns the number — it
// is the server's own samples_per_group on a sampled report, and a plain
// render guard otherwise (thousands of rows in one expand freeze the tab).
// The default here only applies if a caller omits the prop.
const DEFAULT_MAX_ROWS = 300

function CategoryGroup({ category, findings, summary, maxRows }) {
  const [open, setOpen] = useState(false)
  const cap = maxRows ?? DEFAULT_MAX_ROWS
  // True totals come from the server summary (covers ALL findings); fall back
  // to counting the shipped rows for small files / older responses.
  const errorCount   = summary?.error   ?? findings.filter(f => f.severity === 'error').length
  const warningCount = summary?.warning ?? findings.filter(f => f.severity === 'warning').length
  const total        = summary?.total   ?? findings.length
  const shown        = Math.min(findings.length, cap)

  return (
    <div className="border border-slate-200 rounded-xl overflow-hidden">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-4 py-3 bg-slate-50 hover:bg-slate-100 transition-colors"
      >
        <div className="flex items-center gap-3">
          <svg className={`w-4 h-4 text-slate-400 transition-transform ${open ? 'rotate-90' : ''}`}
            fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
          </svg>
          <span className="text-sm font-semibold text-slate-700">{category}</span>
          <span className="text-xs text-slate-400">({total.toLocaleString()})</span>
        </div>
        <div className="flex gap-2">
          {errorCount   > 0 && <span className="badge-error">{errorCount.toLocaleString()} errors</span>}
          {warningCount > 0 && <span className="badge-warning">{warningCount.toLocaleString()} warnings</span>}
        </div>
      </button>

      {open && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-white border-b border-slate-100">
                {['Sev', 'Sheet', 'Material', 'Row', 'Field', 'Message'].map(h => (
                  <th key={h} className="px-3 py-2 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-50">
              {findings.slice(0, cap).map((f, i) => (
                <tr key={i} className="hover:bg-slate-50 transition-colors">
                  <td className="px-3 py-2"><SeverityBadge severity={f.severity} /></td>
                  <td className="px-3 py-2 text-xs font-mono text-slate-500">{f.sheet}</td>
                  <td className="px-3 py-2 text-xs font-mono text-slate-700 whitespace-nowrap">{f.material || '—'}</td>
                  <td className="px-3 py-2 text-xs text-slate-500">{f.row ?? '—'}</td>
                  <td className="px-3 py-2 text-xs font-mono text-slate-600">{f.field ?? '—'}</td>
                  <td className="px-3 py-2 text-xs text-slate-700">{f.message}</td>
                </tr>
              ))}
              {total > shown && (
                <tr>
                  <td colSpan={6} className="px-3 py-2 text-xs text-slate-400">
                    Showing {shown.toLocaleString()} of {total.toLocaleString()} —
                    download the complete CSV from the Downloads tab.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

export default function FindingsByCategory({ findings, summaries, maxRows }) {
  const groups = {}
  for (const f of findings) {
    if (!groups[f.category]) groups[f.category] = []
    groups[f.category].push(f)
  }
  // The server summary lists EVERY category with true totals — the shipped
  // findings are only samples. Fall back to the shipped rows when absent.
  const cats = summaries?.length
    ? summaries.map(s => s.name)
    : Object.keys(groups).sort()
  const byName = Object.fromEntries((summaries ?? []).map(s => [s.name, s]))

  return (
    <div className="space-y-3">
      {cats.map((cat) => (
        <CategoryGroup
          key={cat}
          category={cat}
          findings={groups[cat] ?? []}
          maxRows={maxRows}
          summary={byName[cat]}
        />
      ))}
    </div>
  )
}
