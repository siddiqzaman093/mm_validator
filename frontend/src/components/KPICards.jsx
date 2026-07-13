const KPI = ({ label, value, color = 'slate' }) => {
  const colors = {
    red:    'bg-red-50    border-red-200    text-red-700',
    amber:  'bg-amber-50  border-amber-200  text-amber-700',
    blue:   'bg-blue-50   border-blue-200   text-blue-700',
    green:  'bg-green-50  border-green-200  text-green-700',
    slate:  'bg-slate-50  border-slate-200  text-slate-700',
    purple: 'bg-purple-50 border-purple-200 text-purple-700',
    teal:   'bg-teal-50   border-teal-200   text-teal-700',
  }
  return (
    <div className={`rounded-xl border p-4 flex flex-col gap-1 ${colors[color]}`}>
      <span className="text-xs font-semibold uppercase tracking-wider opacity-70">{label}</span>
      <span className="text-3xl font-bold">{value}</span>
    </div>
  )
}

const READINESS_COLORS = { green: 'green', amber: 'amber', orange: 'amber', red: 'red' }

export default function KPICards({ counts, report }) {
  const readiness = report.readiness
  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
      {readiness && (
        <div className={`rounded-xl border p-4 flex flex-col gap-1 ${{
          green: 'bg-green-50 border-green-200 text-green-700',
          amber: 'bg-amber-50 border-amber-200 text-amber-700',
          red:   'bg-red-50   border-red-200   text-red-700',
        }[READINESS_COLORS[readiness.band] ?? 'amber']}`}>
          <span className="text-xs font-semibold uppercase tracking-wider opacity-70">Readiness Score</span>
          <span className="text-3xl font-bold">{readiness.score}<span className="text-base font-semibold opacity-60">/100</span></span>
          <span className="text-xs opacity-70">
            {readiness.label} · {readiness.ready_materials}/{readiness.total_materials} materials error-free
          </span>
        </div>
      )}
      <KPI label="Errors"    value={counts.error}                         color="red"    />
      <KPI label="Warnings"  value={counts.warning}                       color="amber"  />
      <KPI label="Info"      value={counts.info}                          color="blue"   />
      <KPI label="Data Rows" value={report.rows_total}                    color="slate"  />
      <KPI label="Sheets"    value={report.sheets_seen?.length ?? 0}      color="slate"  />
    </div>
  )
}
