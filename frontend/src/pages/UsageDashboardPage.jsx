import { useCallback, useEffect, useState } from 'react'
import { fetchUsage } from '../api'

const RANGES = [
  { label: 'Last 7 days', value: 7 },
  { label: 'Last 30 days', value: 30 },
  { label: 'Last 90 days', value: 90 },
  { label: 'All time', value: 0 },
]

const nf = new Intl.NumberFormat('en-US')
const fmtInt = (v) => nf.format(v ?? 0)
const fmtCost = (v) => `$${(v ?? 0).toFixed(4)}`
const fmtDate = (iso) => {
  if (!iso) return '—'
  const d = new Date(iso.endsWith('Z') || iso.includes('+') ? iso : iso + 'Z')
  return d.toLocaleString(undefined, {
    year: 'numeric', month: 'short', day: '2-digit',
    hour: '2-digit', minute: '2-digit',
  })
}

function KpiCard({ label, value, sub }) {
  return (
    <div className="card p-4">
      <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider">{label}</p>
      <p className="text-2xl font-bold text-slate-800 mt-1">{value}</p>
      {sub && <p className="text-xs text-slate-400 mt-0.5">{sub}</p>}
    </div>
  )
}

function exportCsv(sessions) {
  const cols = [
    'started_at', 'username', 'file_name', 'materials', 'errors', 'warnings',
    'infos', 'ai_used', 'provider', 'model', 'ai_calls', 'input_tokens',
    'output_tokens', 'cost_usd', 'duration_ms', 'status',
  ]
  const esc = (v) => {
    const s = String(v ?? '')
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
  }
  const lines = [cols.join(',')]
  for (const s of sessions) lines.push(cols.map((c) => esc(s[c])).join(','))
  const blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `mm-validator-usage-${new Date().toISOString().slice(0, 10)}.csv`
  a.click()
  URL.revokeObjectURL(url)
}

export default function UsageDashboardPage() {
  const [days, setDays] = useState(30)
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(async (d) => {
    setLoading(true)
    setError('')
    try {
      setData(await fetchUsage(d))
    } catch (err) {
      setError(err?.response?.data?.detail || 'Failed to load usage data.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load(days) }, [days, load])

  const totals = data?.totals || {}
  const sessions = data?.sessions || []
  const perUser = data?.per_user || []

  return (
    <div className="max-w-7xl mx-auto space-y-6">
      {/* Page header */}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-xl font-bold text-slate-800">Usage Dashboard</h2>
          <p className="text-sm text-slate-500 mt-0.5">
            Admin Activities — validation sessions, materials, AI tokens and cost per user.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <select
            className="input text-sm w-40"
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
          >
            {RANGES.map((r) => (
              <option key={r.value} value={r.value}>{r.label}</option>
            ))}
          </select>
          <button
            onClick={() => exportCsv(sessions)}
            disabled={!sessions.length}
            className="px-3 py-2 rounded-lg text-sm font-medium bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            Export CSV
          </button>
        </div>
      </div>

      {error && (
        <div className="card p-4 border border-red-200 bg-red-50 text-sm text-red-700">{error}</div>
      )}

      {loading ? (
        <div className="card p-8 text-center text-sm text-slate-400">Loading usage data…</div>
      ) : (
        <>
          {/* KPI cards */}
          <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
            <KpiCard label="Sessions" value={fmtInt(totals.sessions)} />
            <KpiCard label="Materials Validated" value={fmtInt(totals.materials)} />
            <KpiCard label="AI Calls" value={fmtInt(totals.ai_calls)} />
            <KpiCard
              label="Tokens (in / out)"
              value={`${fmtInt(totals.input_tokens)} / ${fmtInt(totals.output_tokens)}`}
            />
            <KpiCard label="Estimated Cost" value={fmtCost(totals.cost_usd)} sub="USD" />
          </div>

          {/* Storage warning */}
          {data?.storage && !data.storage.durable && (
            <div className="card p-4 border border-amber-200 bg-amber-50 text-xs text-amber-800">
              <strong>Note:</strong> {data.storage.note}
            </div>
          )}

          {/* Per-user summary */}
          <div className="card p-6">
            <h3 className="text-base font-bold text-slate-800 mb-3">By User</h3>
            {perUser.length === 0 ? (
              <p className="text-sm text-slate-400">No activity in this period.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-xs text-slate-500 uppercase tracking-wider border-b border-slate-200">
                      <th className="py-2 pr-4">User</th>
                      <th className="py-2 pr-4 text-right">Sessions</th>
                      <th className="py-2 pr-4 text-right">Materials</th>
                      <th className="py-2 pr-4 text-right">Tokens In</th>
                      <th className="py-2 pr-4 text-right">Tokens Out</th>
                      <th className="py-2 pr-4 text-right">Cost (USD)</th>
                      <th className="py-2">Last Active</th>
                    </tr>
                  </thead>
                  <tbody>
                    {perUser.map((u) => (
                      <tr key={u.username} className="border-b border-slate-100 last:border-0">
                        <td className="py-2 pr-4 font-medium text-slate-700">{u.username}</td>
                        <td className="py-2 pr-4 text-right">{fmtInt(u.sessions)}</td>
                        <td className="py-2 pr-4 text-right">{fmtInt(u.materials)}</td>
                        <td className="py-2 pr-4 text-right">{fmtInt(u.input_tokens)}</td>
                        <td className="py-2 pr-4 text-right">{fmtInt(u.output_tokens)}</td>
                        <td className="py-2 pr-4 text-right">{fmtCost(u.cost_usd)}</td>
                        <td className="py-2 text-slate-500">{fmtDate(u.last_active)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Session log */}
          <div className="card p-6">
            <h3 className="text-base font-bold text-slate-800 mb-3">
              Sessions <span className="text-xs font-normal text-slate-400">(most recent first)</span>
            </h3>
            {sessions.length === 0 ? (
              <p className="text-sm text-slate-400">No validation sessions recorded in this period.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm whitespace-nowrap">
                  <thead>
                    <tr className="text-left text-xs text-slate-500 uppercase tracking-wider border-b border-slate-200">
                      <th className="py-2 pr-4">Date / Time</th>
                      <th className="py-2 pr-4">User</th>
                      <th className="py-2 pr-4">File</th>
                      <th className="py-2 pr-4 text-right">Materials</th>
                      <th className="py-2 pr-4 text-right">AI Calls</th>
                      <th className="py-2 pr-4 text-right">Tokens In</th>
                      <th className="py-2 pr-4 text-right">Tokens Out</th>
                      <th className="py-2 pr-4 text-right">Cost (USD)</th>
                      <th className="py-2">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sessions.map((s) => (
                      <tr key={s.id} className="border-b border-slate-100 last:border-0">
                        <td className="py-2 pr-4 text-slate-600">{fmtDate(s.started_at)}</td>
                        <td className="py-2 pr-4 font-medium text-slate-700">{s.username}</td>
                        <td className="py-2 pr-4 text-slate-600 max-w-[220px] truncate" title={s.file_name}>
                          {s.file_name}
                        </td>
                        <td className="py-2 pr-4 text-right">{fmtInt(s.materials)}</td>
                        <td className="py-2 pr-4 text-right">{fmtInt(s.ai_calls)}</td>
                        <td className="py-2 pr-4 text-right">{fmtInt(s.input_tokens)}</td>
                        <td className="py-2 pr-4 text-right">{fmtInt(s.output_tokens)}</td>
                        <td className="py-2 pr-4 text-right">{fmtCost(s.cost_usd)}</td>
                        <td className="py-2">
                          <span
                            className={`px-2 py-0.5 rounded-full text-xs font-semibold ${
                              s.status === 'success'
                                ? 'bg-emerald-100 text-emerald-700'
                                : 'bg-red-100 text-red-700'
                            }`}
                            title={s.error || undefined}
                          >
                            {s.status}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}
