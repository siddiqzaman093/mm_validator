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

// Readiness is the headline number — rendered larger and stronger than the
// ordinary KPI tiles to carry the weight of the go/no-go decision.
const READINESS_STYLES = {
  green:  { card: 'bg-green-50 border-green-400 text-green-800', bar: 'bg-green-500' },
  amber:  { card: 'bg-amber-50 border-amber-400 text-amber-800', bar: 'bg-amber-500' },
  orange: { card: 'bg-amber-50 border-amber-400 text-amber-800', bar: 'bg-amber-500' },
  red:    { card: 'bg-red-50   border-red-400   text-red-800',   bar: 'bg-red-500' },
}

function ReadinessCard({ readiness }) {
  const style = READINESS_STYLES[readiness.band] ?? READINESS_STYLES.amber
  return (
    <div className={`col-span-2 sm:col-span-3 lg:col-span-3 rounded-xl border-2 p-4 flex flex-col gap-1 shadow-md ${style.card}`}>
      <span className="text-xs font-bold uppercase tracking-wider opacity-80">Readiness Score</span>
      <div className="flex items-baseline gap-2">
        <span className="text-5xl font-extrabold leading-none">{readiness.score}</span>
        <span className="text-lg font-semibold opacity-60">/100</span>
        <span className="ml-auto text-sm font-bold uppercase tracking-wide">{readiness.label}</span>
      </div>
      <div className="h-2 rounded-full bg-black/10 overflow-hidden mt-1.5">
        <div
          className={`h-full rounded-full ${style.bar} transition-all`}
          style={{ width: `${Math.max(2, readiness.score)}%` }}
        />
      </div>
      <span className="text-xs opacity-75 mt-0.5">
        {readiness.ready_materials}/{readiness.total_materials} materials error-free
      </span>
    </div>
  )
}

export default function KPICards({ counts, report }) {
  const readiness = report.readiness
  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-8 gap-3">
      {readiness && <ReadinessCard readiness={readiness} />}
      <KPI label="Errors"    value={counts.error}                    color="red"   />
      <KPI label="Warnings"  value={counts.warning}                  color="amber" />
      <KPI label="Info"      value={counts.info}                     color="blue"  />
      <KPI label="Data Rows" value={report.rows_total}               color="slate" />
      <KPI label="Sheets"    value={report.sheets_seen?.length ?? 0} color="slate" />
    </div>
  )
}
