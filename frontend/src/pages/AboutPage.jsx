const CHECK_GROUPS = [
  { title: 'Schema', desc: 'Mandatory presence, Type (Text/Number/Date/Time), Length and Decimal places — driven by the lookup file and the template Field List.' },
  { title: 'Cross-extension consistency', desc: 'MRP type ↔ Controller / Reorder / Lot Size · Procurement ↔ Purchasing Group · Plant status validity · Reorder ≤ Maximum stock.' },
  { title: 'Costing & Accounting', desc: 'Valuation Class, Price Control S/V coherence, Standard/Moving price > 0, Currency presence, Stock × Price ≈ Total Value.' },
  { title: 'Sales', desc: 'Sales Org + Distribution Channel, status valid-from, Item Category ↔ Account Assignment, Min Order ≥ 0.' },
  { title: 'Alternative UoM', desc: 'Alt UoM ≠ Base UoM, Numerator/Denominator > 0, no duplicates, GTIN length 8/12/13/14, conversion sanity vs SAP UoM master.' },
  { title: 'References', desc: 'Every product in extension sheets exists in Basic Data; Storage Loc / Forecasting refer to a maintained Plant.' },
  { title: 'Lookup-driven', desc: 'Product type → Material Class / Valuation Type and Plant → Profit Center, validated against the Master Lookup File.' },
  { title: 'AI warning flags', desc: 'Description vs Material Type, missing Shelf Life on perishables, pricing anomalies, Base UoM vs product nature — each with a deterministic pre-filter.' },
]

function InfoCard({ children }) {
  return <div className="card p-6">{children}</div>
}

export default function AboutPage() {
  return (
    <div className="max-w-7xl mx-auto space-y-6">
      {/* Page header */}
      <div>
        <h2 className="text-xl font-bold text-slate-800">About</h2>
        <p className="text-sm text-slate-500 mt-0.5">
          SAP S/4HANA Material Master Validator Tool — data-quality checks for the Migration Cockpit.
        </p>
      </div>

      {/* What it does */}
      <InfoCard>
        <h3 className="text-base font-bold text-slate-800 mb-2">What it does</h3>
        <p className="text-sm text-slate-600 leading-relaxed">
          This tool validates the SAP Migration Cockpit <em>“Product Master Creation”</em> template
          (<code className="text-xs bg-slate-100 px-1 py-0.5 rounded">.xls</code> / <code className="text-xs bg-slate-100 px-1 py-0.5 rounded">.xlsx</code>)
          before load, and produces a health report (RED / AMBER / GREEN) with every finding grouped by
          category and by sheet. Upload the <strong>Master Lookup File</strong> and your <strong>Material
          Master</strong> workbook, and it runs the full rule set below. Findings download as HTML, JSON or CSV.
        </p>
      </InfoCard>

      {/* Validation coverage */}
      <InfoCard>
        <h3 className="text-base font-bold text-slate-800 mb-4">Validation coverage</h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {CHECK_GROUPS.map(g => (
            <div key={g.title} className="flex gap-3">
              <svg className="w-5 h-5 text-blue-500 shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              <div>
                <p className="text-sm font-semibold text-slate-700">{g.title}</p>
                <p className="text-xs text-slate-500 leading-relaxed">{g.desc}</p>
              </div>
            </div>
          ))}
        </div>
      </InfoCard>

      {/* How to use */}
      <InfoCard>
        <h3 className="text-base font-bold text-slate-800 mb-4">How to use</h3>
        <ol className="space-y-3">
          {[
            ['1', 'Upload the Master Lookup File', 'Defines the authoritative SAP field types, per-material-type mandatory fields, and plant → profit-center mappings.'],
            ['2', 'Upload the Material Master data', 'The Migration Cockpit “Product Master Creation” .xls / .xlsx workbook to validate.'],
            ['3', 'Run Validation', 'Optionally enable AI-Enabled Validations first. Review the findings and download the report.'],
          ].map(([n, title, desc]) => (
            <li key={n} className="flex gap-3">
              <span className="flex items-center justify-center w-6 h-6 rounded-full bg-blue-600 text-white text-xs font-bold shrink-0">{n}</span>
              <div>
                <p className="text-sm font-semibold text-slate-700">{title}</p>
                <p className="text-xs text-slate-500">{desc}</p>
              </div>
            </li>
          ))}
        </ol>
      </InfoCard>

      {/* Meta */}
      <p className="text-center text-xs text-slate-400">
        SAP MM Validator Tool · React + FastAPI · shared validation engine with the Streamlit app
      </p>
    </div>
  )
}
