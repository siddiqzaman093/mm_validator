"""HTML report renderer."""
from __future__ import annotations

import html
from collections import defaultdict
from datetime import datetime

from .models import Finding, Severity, ValidationReport


_STYLE = """
<style>
  :root { --bg:#0f172a; --panel:#1e293b; --muted:#94a3b8; --text:#e2e8f0; --accent:#38bdf8;
          --error:#ef4444; --warn:#f59e0b; --info:#0ea5e9; --ok:#10b981; }
  * { box-sizing: border-box; }
  body { font-family: -apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif;
         background:var(--bg); color:var(--text); margin:0; padding:24px; }
  h1 { font-size: 22px; margin: 0 0 12px; }
  h2 { font-size: 16px; margin: 24px 0 8px; color: var(--accent); border-bottom: 1px solid #334155; padding-bottom: 4px; }
  .meta { color: var(--muted); font-size: 13px; margin-bottom: 16px; }
  .cards { display:grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; margin-bottom: 16px; }
  .card { background:var(--panel); border-radius: 8px; padding: 14px; border-left: 4px solid #334155; }
  .card .label { color:var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing:.05em; }
  .card .value { font-size: 24px; font-weight: 600; margin-top: 4px; }
  .card.error { border-color: var(--error); }
  .card.warning { border-color: var(--warn); }
  .card.info { border-color: var(--info); }
  .card.ok { border-color: var(--ok); }
  table { width: 100%; border-collapse: collapse; background: var(--panel); border-radius: 8px; overflow: hidden; }
  thead th { background: #0f172a; padding: 8px 10px; text-align: left; font-size: 11px;
             text-transform: uppercase; letter-spacing: .05em; color: var(--muted); border-bottom: 1px solid #334155;}
  tbody td { padding: 8px 10px; border-bottom: 1px solid #334155; vertical-align: top; font-size: 13px;}
  tbody tr:last-child td { border-bottom: none; }
  .sev { display:inline-block; padding: 2px 6px; border-radius: 4px; font-size: 11px; font-weight: 600; text-transform: uppercase; }
  .sev.error { background: rgba(239,68,68,.18); color: #fca5a5; }
  .sev.warning { background: rgba(245,158,11,.18); color: #fcd34d; }
  .sev.info { background: rgba(14,165,233,.18); color: #7dd3fc; }
  .ai { background: rgba(168,85,247,.15); color:#d8b4fe; padding: 1px 5px; border-radius: 3px; font-size: 10px; margin-left: 4px;}
  .rule { color: var(--muted); font-family: ui-monospace, SFMono-Regular, monospace; font-size: 11px; }
  .empty { background: var(--panel); padding: 14px; border-radius: 8px; color: var(--muted); }
  .health { font-size: 14px; margin-bottom: 12px; }
  .health.green { color: #6ee7b7; }
  .health.amber { color: #fcd34d; }
  .health.red { color: #fca5a5; }
  details { margin-bottom: 12px; }
  summary { cursor: pointer; padding: 8px 12px; background: var(--panel); border-radius: 6px; font-weight: 600; }
  summary::marker { color: var(--accent); }
  details[open] summary { border-bottom-left-radius:0; border-bottom-right-radius:0; }
  details > table { border-top-left-radius: 0; border-top-right-radius: 0; }
</style>
"""


def _readiness_headline(readiness: dict) -> tuple[str, str]:
    cls = {"green": "green", "amber": "amber", "orange": "amber", "red": "red"}
    return (
        f"Readiness Score: {readiness['score']} / 100 — {readiness['label']} "
        f"({readiness['ready_materials']}/{readiness['total_materials']} materials error-free)",
        cls.get(readiness["band"], "amber"),
    )


def _findings_table(findings: list[Finding]) -> str:
    if not findings:
        return '<div class="empty">No issues in this group.</div>'
    rows = []
    for f in findings:
        ai_badge = '<span class="ai">AI</span>' if f.ai_generated else ""
        rows.append(
            f"<tr>"
            f'<td><span class="sev {f.severity.value}">{f.severity.value}</span>{ai_badge}</td>'
            f'<td>{html.escape(f.sheet)}</td>'
            f'<td>{html.escape(f.material or "")}</td>'
            f'<td>{f.row if f.row else ""}</td>'
            f'<td>{html.escape(f.field or "")}'
            + (f'<div class="rule">{html.escape(f.sap_field or "")}</div>' if f.sap_field else "")
            + f'</td>'
            f'<td>{html.escape(f.message)}'
            + (f'<div class="rule">{html.escape(str(f.value))}</div>' if f.value not in (None, "") else "")
            + f'</td>'
            f'<td><span class="rule">{html.escape(f.rule_id)}</span></td>'
            f"</tr>"
        )
    return (
        '<table><thead><tr>'
        '<th>Severity</th><th>Sheet</th><th>Material</th><th>Row</th><th>Field</th><th>Message</th><th>Rule</th>'
        '</tr></thead><tbody>'
        + "".join(rows)
        + '</tbody></table>'
    )


def render_html(report: ValidationReport) -> str:
    counts = report.counts()
    readiness = report.readiness()
    health_text, health_cls = _readiness_headline(readiness)

    grouped: dict[str, list[Finding]] = defaultdict(list)
    for f in report.findings:
        grouped[f.category].append(f)

    severity_order = {"error": 0, "warning": 1, "info": 2}
    for cat in grouped:
        grouped[cat].sort(key=lambda f: (severity_order.get(f.severity.value, 99), f.sheet, f.row or 0))
    sorted_cats = sorted(grouped.keys())

    by_sheet: dict[str, list[Finding]] = defaultdict(list)
    for f in report.findings:
        by_sheet[f.sheet].append(f)

    readiness_cls = {"green": "ok", "amber": "warning",
                     "orange": "warning", "red": "error"}.get(readiness["band"], "info")
    cards = (
        # The Readiness card is the headline — deliberately larger and heavier
        # than the plain Errors/Warnings tiles.
        f'<div class="card {readiness_cls}" style="grid-column: span 2; border-left-width: 8px;">'
        f'<div class="label" style="font-weight:700;">Readiness Score</div>'
        f'<div class="value" style="font-size:40px;">{readiness["score"]} <span style="font-size:18px;opacity:.6;">/ 100</span></div>'
        f'<div class="label" style="margin-top:4px;text-transform:none;font-size:13px;">{html.escape(readiness["label"])} · '
        f'{readiness["ready_materials"]}/{readiness["total_materials"]} materials error-free</div></div>'
        f'<div class="card error"><div class="label">Errors</div><div class="value">{counts["error"]}</div></div>'
        f'<div class="card warning"><div class="label">Warnings</div><div class="value">{counts["warning"]}</div></div>'
        f'<div class="card info"><div class="label">Info</div><div class="value">{counts["info"]}</div></div>'
        f'<div class="card ok"><div class="label">Sheets w/ Data</div><div class="value">{len(report.sheets_seen)}</div></div>'
        f'<div class="card ok"><div class="label">Data Rows</div><div class="value">{report.rows_total}</div></div>'
    )

    cat_blocks = "".join(
        f'<details><summary>{html.escape(cat)} — {len(items)} issue(s)</summary>{_findings_table(items)}</details>'
        for cat, items in ((c, grouped[c]) for c in sorted_cats)
    )

    sheet_blocks = "".join(
        f'<details><summary>{html.escape(sheet)} — {len(items)} issue(s)</summary>{_findings_table(items)}</details>'
        for sheet, items in sorted(by_sheet.items())
    )

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>MM Validation Report — {html.escape(report.file_name)}</title>{_STYLE}</head>
<body>
  <h1>SAP S/4HANA Material Master — Validation Report</h1>
  <div class="meta">
    File: <strong>{html.escape(report.file_name)}</strong> · Generated: {now}
  </div>
  <div class="health {health_cls}">{html.escape(health_text)}</div>
  <div class="cards">{cards}</div>

  <h2>Findings by Category</h2>
  {cat_blocks or '<div class="empty">No findings.</div>'}

  <h2>Findings by Sheet</h2>
  {sheet_blocks or '<div class="empty">No findings.</div>'}

</body></html>
"""
