import { useState } from 'react'
import SeverityBadge from './SeverityBadge'

function CategoryGroup({ category, findings }) {
  const [open, setOpen] = useState(false)
  const errorCount   = findings.filter(f => f.severity === 'error').length
  const warningCount = findings.filter(f => f.severity === 'warning').length

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
          <span className="text-xs text-slate-400">({findings.length})</span>
        </div>
        <div className="flex gap-2">
          {errorCount   > 0 && <span className="badge-error">{errorCount} errors</span>}
          {warningCount > 0 && <span className="badge-warning">{warningCount} warnings</span>}
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
              {findings.map((f, i) => (
                <tr key={i} className="hover:bg-slate-50 transition-colors">
                  <td className="px-3 py-2"><SeverityBadge severity={f.severity} /></td>
                  <td className="px-3 py-2 text-xs font-mono text-slate-500">{f.sheet}</td>
                  <td className="px-3 py-2 text-xs font-mono text-slate-700 whitespace-nowrap">{f.material || '—'}</td>
                  <td className="px-3 py-2 text-xs text-slate-500">{f.row ?? '—'}</td>
                  <td className="px-3 py-2 text-xs font-mono text-slate-600">{f.field ?? '—'}</td>
                  <td className="px-3 py-2 text-xs text-slate-700">{f.message}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

export default function FindingsByCategory({ findings }) {
  const groups = {}
  for (const f of findings) {
    if (!groups[f.category]) groups[f.category] = []
    groups[f.category].push(f)
  }
  return (
    <div className="space-y-3">
      {Object.entries(groups).sort().map(([cat, items]) => (
        <CategoryGroup key={cat} category={cat} findings={items} />
      ))}
    </div>
  )
}
