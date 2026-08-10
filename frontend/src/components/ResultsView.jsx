import { useState } from 'react'
import { downloadJobCsv } from '../api'
import KPICards from './KPICards'
import FindingsTable from './FindingsTable'
import FindingsByCategory from './FindingsByCategory'
import FindingsBySheet from './FindingsBySheet'

const TABS = ['By Category', 'By Sheet', 'All Findings', 'Downloads']

function downloadBlob(content, filename, mime) {
  const blob = content instanceof Blob ? content : new Blob([content], { type: mime })
  const url  = URL.createObjectURL(blob)
  const a    = document.createElement('a')
  a.href = url; a.download = filename; a.click()
  URL.revokeObjectURL(url)
}

/** Full results block (KPIs, truncation banner, findings tabs, downloads) for
 * a ValidationReport JSON — used by the Validator page and Past Validations. */
export default function ResultsView({ report }) {
  const [activeTab, setTab] = useState(0)
  const counts = report?.counts ?? {}

  // The complete CSV comes from the job store on the server: with very large
  // files the JSON response only carries the most severe findings. Fall back
  // to a client-side build from the (possibly capped) list if it's gone.
  async function handleCsvDownload() {
    try {
      if (report.job_id) {
        const blob = await downloadJobCsv(report.job_id)
        downloadBlob(blob, `${report.file_name}.findings.csv`, 'text/csv')
        return
      }
    } catch { /* expired/unreachable — fall through to client-side build */ }
    // Prefix a quote onto values starting with =, +, -, @ so Excel treats
    // workbook-controlled text as text, never as a formula.
    const safe = (v) => typeof v === 'string' && /^[=+\-@\t\r]/.test(v) ? `'${v}` : v
    const cols = ['severity','ai_generated','category','sheet','material','row','field','sap_field','value','message','rule_id']
    const rows = report.findings.map(f => cols.map(c => JSON.stringify(safe(f[c]) ?? '')).join(','))
    downloadBlob([cols.join(','), ...rows].join('\n'), `${report.file_name}.findings.csv`, 'text/csv')
  }

  if (!report) return null

  return (
    <div className="space-y-4">
      {/* KPI cards (Readiness Score is the headline) */}
      <KPICards counts={counts} report={report} />

      {/* Large files: the tables below show only the most severe findings */}
      {report.findings_truncated && (
        <div className="p-4 rounded-xl bg-amber-50 border border-amber-200 text-amber-800 text-sm">
          This file produced <strong>{(report.findings_total ?? 0).toLocaleString()}</strong> findings.
          The tables below show the <strong>{report.findings.length.toLocaleString()}</strong> most
          severe (all errors first) — score and counts above cover everything. Use{' '}
          <button className="underline font-semibold" onClick={() => setTab(3)}>Downloads</button>{' '}
          to get the complete findings CSV.
        </div>
      )}

      {report.findings?.length > 0 ? (
        <div className="card overflow-hidden">
          {/* Tab bar */}
          <div className="flex border-b border-slate-200 bg-slate-50">
            {TABS.map((tab, i) => (
              <button
                key={tab}
                onClick={() => setTab(i)}
                className={`px-5 py-3 text-sm font-medium transition-colors border-b-2 -mb-px
                  ${activeTab === i
                    ? 'border-blue-600 text-blue-700 bg-white'
                    : 'border-transparent text-slate-500 hover:text-slate-700'}`}
              >
                {tab}
              </button>
            ))}
          </div>

          <div className="p-5">
            {activeTab === 0 && <FindingsByCategory findings={report.findings} />}
            {activeTab === 1 && <FindingsBySheet    findings={report.findings} />}
            {activeTab === 2 && <FindingsTable      findings={report.findings} />}
            {activeTab === 3 && (
              <div className="space-y-4">
                <p className="text-sm text-slate-600">Download the full validation results in your preferred format.</p>
                <div className="flex flex-wrap gap-3">
                  <button
                    onClick={() => downloadBlob(report.html_report, `${report.file_name}.validation-report.html`, 'text/html')}
                    className="btn-primary"
                  >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                        d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                    </svg>
                    HTML Report
                  </button>
                  <button
                    onClick={() => downloadBlob(
                      JSON.stringify({ ...report, html_report: undefined }, null, 2),
                      `${report.file_name}.validation-report.json`,
                      'application/json'
                    )}
                    className="btn-secondary"
                  >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                        d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                    </svg>
                    JSON Findings
                  </button>
                  <button
                    onClick={handleCsvDownload}
                    className="btn-secondary"
                  >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                        d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                    </svg>
                    CSV Findings (complete)
                  </button>
                  {report.findings_truncated && (
                    <p className="w-full text-xs text-slate-500">
                      The HTML and JSON downloads show the most severe findings only; the CSV always
                      contains all {(report.findings_total ?? 0).toLocaleString()} findings.
                    </p>
                  )}
                </div>

                {/* Inline HTML preview */}
                <div className="mt-4">
                  <p className="text-sm font-medium text-slate-700 mb-2">HTML Report Preview</p>
                  <iframe
                    srcDoc={report.html_report}
                    className="w-full h-96 rounded-xl border border-slate-200"
                    title="HTML Report Preview"
                    sandbox="allow-same-origin"
                  />
                </div>
              </div>
            )}
          </div>
        </div>
      ) : (
        <div className="card p-8 text-center">
          <svg className="w-12 h-12 text-green-400 mx-auto mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
              d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <p className="text-slate-600 font-medium">No findings — the file looks clean!</p>
        </div>
      )}
    </div>
  )
}
