import { useState, useMemo } from 'react'
import SeverityBadge from './SeverityBadge'

const PAGE_SIZE = 50

export default function FindingsTable({ findings }) {
  const [sevFilter, setSevFilter]   = useState(['error', 'warning', 'info'])
  const [catFilter, setCatFilter]   = useState([])
  const [search, setSearch]         = useState('')
  const [page, setPage]             = useState(1)

  const categories = useMemo(() => {
    return [...new Set(findings.map(f => f.category))].sort()
  }, [findings])

  const filtered = useMemo(() => {
    const activeCats = catFilter.length ? catFilter : categories
    const needle = search.toLowerCase()
    return findings.filter(f =>
      sevFilter.includes(f.severity) &&
      activeCats.includes(f.category) &&
      (!needle || [f.message, f.field, f.sap_field, f.material, String(f.value ?? '')]
        .some(s => (s || '').toLowerCase().includes(needle)))
    )
  }, [findings, sevFilter, catFilter, categories, search])

  const totalPages = Math.ceil(filtered.length / PAGE_SIZE)
  const paged = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)

  function toggleSev(s) {
    setSevFilter(prev => prev.includes(s) ? prev.filter(x => x !== s) : [...prev, s])
    setPage(1)
  }
  function toggleCat(c) {
    setCatFilter(prev => prev.includes(c) ? prev.filter(x => x !== c) : [...prev, c])
    setPage(1)
  }

  return (
    <div className="space-y-4">
      {/* Filters */}
      <div className="flex flex-wrap gap-3 items-center">
        {/* Severity toggles */}
        <div className="flex gap-1">
          {['error', 'warning', 'info'].map(s => (
            <button
              key={s}
              onClick={() => toggleSev(s)}
              className={`px-3 py-1 rounded-full text-xs font-semibold border transition-colors ${
                sevFilter.includes(s)
                  ? s === 'error'   ? 'bg-red-100 border-red-300 text-red-700'
                  : s === 'warning' ? 'bg-amber-100 border-amber-300 text-amber-700'
                  :                   'bg-blue-100 border-blue-300 text-blue-700'
                  : 'bg-white border-slate-200 text-slate-400'
              }`}
            >
              {s}
            </button>
          ))}
        </div>

        {/* Category dropdown */}
        <select
          className="input w-auto text-xs"
          onChange={e => { setCatFilter(e.target.value ? [e.target.value] : []); setPage(1) }}
          value={catFilter[0] ?? ''}
        >
          <option value="">All categories</option>
          {categories.map(c => <option key={c} value={c}>{c}</option>)}
        </select>

        {/* Search */}
        <div className="flex-1 min-w-48 relative">
          <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400"
            fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
              d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <input
            className="input pl-9 text-xs"
            placeholder="Search message, field, value…"
            value={search}
            onChange={e => { setSearch(e.target.value); setPage(1) }}
          />
        </div>

        <span className="text-xs text-slate-500">{filtered.length} findings</span>
      </div>

      {/* Table */}
      <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-slate-50 border-b border-slate-200">
              {['Severity', 'Category', 'Sheet', 'Material', 'Row', 'Field', 'SAP Field', 'Value', 'Message'].map(h => (
                <th key={h} className="px-3 py-2.5 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider whitespace-nowrap">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {paged.length === 0 ? (
              <tr>
                <td colSpan={9} className="px-4 py-8 text-center text-slate-400 text-sm">
                  No findings match your filters.
                </td>
              </tr>
            ) : paged.map((f, i) => (
              <tr key={i} className="hover:bg-slate-50 transition-colors">
                <td className="px-3 py-2"><SeverityBadge severity={f.severity} /></td>
                <td className="px-3 py-2 text-xs text-slate-600 whitespace-nowrap">{f.category}</td>
                <td className="px-3 py-2 text-xs font-mono text-slate-500">{f.sheet}</td>
                <td className="px-3 py-2 text-xs font-mono text-slate-700 whitespace-nowrap">{f.material || '—'}</td>
                <td className="px-3 py-2 text-xs text-slate-500">{f.row ?? '—'}</td>
                <td className="px-3 py-2 text-xs font-mono text-slate-600">{f.field ?? '—'}</td>
                <td className="px-3 py-2 text-xs font-mono text-slate-500">{f.sap_field ?? '—'}</td>
                <td className="px-3 py-2 text-xs text-slate-600 max-w-32 truncate" title={String(f.value ?? '')}>
                  {f.value != null ? String(f.value) : '—'}
                </td>
                <td className="px-3 py-2 text-xs text-slate-700">{f.message}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between text-xs text-slate-500">
          <span>Page {page} of {totalPages}</span>
          <div className="flex gap-2">
            <button
              disabled={page === 1}
              onClick={() => setPage(p => p - 1)}
              className="btn-secondary py-1 px-3 text-xs disabled:opacity-40"
            >← Prev</button>
            <button
              disabled={page === totalPages}
              onClick={() => setPage(p => p + 1)}
              className="btn-secondary py-1 px-3 text-xs disabled:opacity-40"
            >Next →</button>
          </div>
        </div>
      )}
    </div>
  )
}
