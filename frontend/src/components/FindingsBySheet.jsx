import { useState } from 'react'
import SeverityBadge from './SeverityBadge'

function SheetGroup({ sheet, findings }) {
  const [open, setOpen] = useState(false)

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
          <span className="text-sm font-semibold text-slate-700 font-mono">{sheet}</span>
          <span className="text-xs text-slate-400">({findings.length} findings)</span>
        </div>
      </button>

      {open && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-white border-b border-slate-100">
                {['Sev', 'Category', 'Material', 'Row', 'Field', 'Message'].map(h => (
                  <th key={h} className="px-3 py-2 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-50">
              {findings.map((f, i) => (
                <tr key={i} className="hover:bg-slate-50">
                  <td className="px-3 py-2"><SeverityBadge severity={f.severity} /></td>
                  <td className="px-3 py-2 text-xs text-slate-600">{f.category}</td>
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

export default function FindingsBySheet({ findings }) {
  const groups = {}
  for (const f of findings) {
    if (!groups[f.sheet]) groups[f.sheet] = []
    groups[f.sheet].push(f)
  }
  return (
    <div className="space-y-3">
      {Object.entries(groups).sort().map(([sheet, items]) => (
        <SheetGroup key={sheet} sheet={sheet} findings={items} />
      ))}
    </div>
  )
}
