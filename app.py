"""
SAP S/4HANA Material Master — Validation App.

Streamlit UI: upload `Product Master Creation.xls(x)`, run all validations,
display a health report, download HTML/JSON.
"""
from __future__ import annotations

import io
import json
import os
import sys
import shutil
from collections import Counter
from pathlib import Path

# Purge stale bytecode and any cached validator modules so every restart
# loads fresh source regardless of Streamlit's module cache.
for _p in Path(__file__).parent.rglob("__pycache__"):
    shutil.rmtree(_p, ignore_errors=True)
for _k in [k for k in sys.modules if k.startswith("validator")]:
    del sys.modules[_k]

import pandas as pd
import streamlit as st

from validator import run_validation
from validator.report import render_html


st.set_page_config(
    page_title="SAP MM Validator",
    page_icon=":material/inventory_2:",
    layout="wide",
)

st.title("SAP S/4HANA Material Master — Validation Tool")
st.caption("Upload the Migration Cockpit Product Master template and get a data-quality check report.")


_OPENAI_KEY_DEFAULT = ""  # No hardcoded key — set OPENAI_API_KEY in the environment.

with st.sidebar:
    st.header("Settings")

    use_ai = st.toggle("Enable online AI checks", value=False)

    if use_ai:
        # When AI is enabled, default to OpenAI / gpt-5.4
        provider = st.selectbox(
            "AI Provider",
            options=["Anthropic", "OpenAI"],
            index=1,                          # OpenAI pre-selected
        )
    else:
        provider = st.selectbox(
            "AI Provider",
            options=["Anthropic", "OpenAI"],
            index=1,
        )

    if provider == "Anthropic":
        api_key_default = os.environ.get("ANTHROPIC_API_KEY", "")
        api_key = st.text_input(
            "Anthropic API key",
            value=api_key_default,
            type="password",
            help="Used only for the AI warning flags. Leave blank to disable AI.",
        )
        model = st.selectbox(
            "Model",
            options=["claude-haiku-4-5", "claude-sonnet-4-6", "claude-opus-4-7"],
            index=0,
            help="Haiku is fastest/cheapest; Opus is most accurate.",
        )
    else:
        api_key_default = os.environ.get("OPENAI_API_KEY", _OPENAI_KEY_DEFAULT)
        api_key = st.text_input(
            "OpenAI API key",
            value=api_key_default,
            type="password",
            help="Used only for the AI warning flags. Leave blank to disable AI.",
        )
        _openai_models = ["gpt-4o-mini", "gpt-4o", "gpt-5.4", "gpt-4-turbo", "gpt-3.5-turbo"]
        _default_model_idx = _openai_models.index("gpt-5.4") if use_ai else 0
        model = st.selectbox(
            "Model",
            options=_openai_models,
            index=_default_model_idx,
            help="gpt-4o-mini is fastest/cheapest; gpt-5.4 / gpt-4o are most accurate.",
        )
    st.divider()
    st.markdown(
        "**Token-saving strategy:**\n"
        "1. All schema, length, decimal & cross-field checks run in pure Python.\n"
        "2. Each AI flag has a deterministic pre-filter.\n"
        "3. Only ambiguous cases are batched into a single AI call.\n"
        "4. The system prompt is cached across calls (Anthropic only)."
    )


# ── Step 1: Lookup file (mandatory) ──────────────────────────────────────────
st.subheader("Step 1 — Upload Master Lookup File")
lookup_uploaded = st.file_uploader(
    "Upload `Product Master Lookup File.xlsx`",
    type=["xlsx"],
    accept_multiple_files=False,
    key="lookup_file",
)

if lookup_uploaded is None:
    st.error(
        "⛔ **Lookup file is required.** "
        "Please upload `Product Master Lookup File.xlsx` to proceed. "
        "This file defines the authoritative SAP field types and lengths used for validation."
    )
    st.stop()

st.success(f"✅ Lookup file loaded: `{lookup_uploaded.name}`")

# ── Step 2: Material Master file ─────────────────────────────────────────────
st.subheader("Step 2 — Upload Material Master Data")
uploaded = st.file_uploader(
    "Upload `Product Master Creation.xls` or `.xlsx`",
    type=["xls", "xlsx"],
    accept_multiple_files=False,
    key="mm_file",
)

if uploaded is None:
    st.info("Drop your SAP migration template above to begin.")
    st.stop()

# Run validation
file_bytes   = uploaded.getvalue()
lookup_bytes = lookup_uploaded.getvalue()

_progress_bar   = st.progress(0, text="Starting validation…")
_status_text    = st.empty()
_ai_sub_bar     = st.empty()   # sub-progress bar for AI stage
_ai_sub_caption = st.empty()   # companion text for sub-bar

def _on_progress(pct: int, msg: str):
    _progress_bar.progress(pct, text=f"{pct}% — {msg}")
    _status_text.caption(msg)
    # Clear AI sub-bar when we move past the AI stage
    if pct >= 100:
        _ai_sub_bar.empty()
        _ai_sub_caption.empty()

def _on_ai_progress(processed: int, total: int):
    if total <= 0:
        return
    ai_pct = int((processed / total) * 100)
    _ai_sub_caption.caption(
        f"↳ AI check: {processed} of {total} material(s) — {ai_pct}%"
    )
    _ai_sub_bar.progress(ai_pct)

report = run_validation(
    file_bytes,
    file_name=uploaded.name,
    lookup_bytes=lookup_bytes,
    use_ai=use_ai and bool(api_key),
    api_key=api_key or None,
    model=model,
    provider=provider.lower(),
    progress_callback=_on_progress,
    ai_progress_callback=_on_ai_progress,
)

_progress_bar.empty()
_status_text.empty()
_ai_sub_bar.empty()
_ai_sub_caption.empty()

counts = report.counts()
total = sum(counts.values())

# --- Health summary banner ---
if counts["error"] == 0 and counts["warning"] == 0:
    st.success(f"GREEN — no issues across {report.rows_total} data rows in {len(report.sheets_seen)} sheets.")
elif counts["error"] == 0:
    st.warning(f"AMBER — {counts['warning']} warning(s), 0 errors.")
else:
    st.error(f"RED — {counts['error']} error(s) require attention before upload.")

# --- KPI cards ---
c1, c2, c3, c4, c5, c6, c7 = st.columns(7)
c1.metric("Errors", counts["error"])
c2.metric("Warnings", counts["warning"])
c3.metric("Info", counts["info"])
c4.metric("Data Rows", report.rows_total)
c5.metric("Sheets", len(report.sheets_seen))
c6.metric("AI Calls", report.ai_calls)
c7.metric("Elapsed", f"{report.elapsed_ms} ms")

if report.ai_calls:
    st.caption(
        f"AI tokens — input: {report.ai_input_tokens} · output: {report.ai_output_tokens} "
        f"· model: `{model}`"
    )

st.divider()

if not report.findings:
    st.success("No findings. The file looks clean.")
    st.stop()

# --- Findings dataframe + filters ---
df = pd.DataFrame([f.to_dict() for f in report.findings])
# move ai_generated next to severity column for readability
cols_order = ["severity", "ai_generated", "category", "sheet", "material", "row", "field",
              "sap_field", "value", "message", "rule_id"]
df = df[cols_order]

with st.expander("Messages Filter", expanded=False):
    f1, f2, f3 = st.columns([1, 1, 2])
    sev_filter = f1.multiselect("Severity", ["error", "warning", "info"],
                                default=["error", "warning", "info"])
    cat_options = sorted(df["category"].unique().tolist())
    cat_filter = f2.multiselect("Category", cat_options, default=cat_options)
    text_filter = f3.text_input("Search message / field", placeholder="e.g. shelf life, MEINS, MAT-1001")

filtered = df[df["severity"].isin(sev_filter) & df["category"].isin(cat_filter)]
if text_filter:
    needle = text_filter.lower()
    filtered = filtered[
        filtered["message"].str.lower().str.contains(needle, na=False)
        | filtered["field"].fillna("").str.lower().str.contains(needle)
        | filtered["sap_field"].fillna("").str.lower().str.contains(needle)
        | filtered["value"].astype(str).str.lower().str.contains(needle, na=False)
    ]

st.subheader("Data Validation Result")
tab1, tab2, tab3, tab4 = st.tabs(["By Category", "By Sheet", "All Findings", "Downloads"])

with tab1:
    cat_counts = Counter(f.category for f in report.findings)
    for cat in sorted(cat_counts.keys()):
        cat_findings = [f for f in report.findings if f.category == cat]
        cat_df = pd.DataFrame([f.to_dict() for f in cat_findings])[cols_order]
        with st.expander(f"{cat} — {len(cat_findings)}", expanded=False):
            st.dataframe(cat_df.rename(columns=str.upper), use_container_width=True, hide_index=True)

with tab2:
    sheet_counts = Counter(f.sheet for f in report.findings)
    for sheet in sorted(sheet_counts.keys()):
        sheet_findings = [f for f in report.findings if f.sheet == sheet]
        sheet_df = pd.DataFrame([f.to_dict() for f in sheet_findings])[cols_order]
        with st.expander(f"{sheet} — {len(sheet_findings)}"):
            st.dataframe(sheet_df.rename(columns=str.upper), use_container_width=True, hide_index=True)

with tab3:
    st.dataframe(filtered.rename(columns=str.upper), use_container_width=True, hide_index=True, height=560)

with tab4:
    html_blob = render_html(report)
    json_blob = json.dumps(report.to_dict(), indent=2, default=str)

    st.download_button(
        "Download HTML report",
        data=html_blob,
        file_name=f"{uploaded.name}.validation-report.html",
        mime="text/html",
    )
    st.download_button(
        "Download JSON",
        data=json_blob,
        file_name=f"{uploaded.name}.validation-report.json",
        mime="application/json",
    )
    _excel_buf = io.BytesIO()
    _excel_df = df.rename(columns=str.upper)
    _excel_df.to_excel(_excel_buf, index=False, engine="openpyxl")

    # Style the header row: bold + centre-aligned
    from openpyxl import load_workbook as _lw
    from openpyxl.styles import Font as _Font, Alignment as _Align
    _excel_buf.seek(0)
    _wb = _lw(_excel_buf)
    _ws = _wb.active
    for cell in _ws[1]:
        cell.font      = _Font(bold=True)
        cell.alignment = _Align(horizontal="center")
    _excel_buf = io.BytesIO()
    _wb.save(_excel_buf)
    _excel_buf.seek(0)

    st.download_button(
        "Download Result in Excel",
        data=_excel_buf.getvalue(),
        file_name=f"{uploaded.name}.findings.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    with st.expander("Preview HTML report"):
        st.components.v1.html(html_blob, height=800, scrolling=True)
