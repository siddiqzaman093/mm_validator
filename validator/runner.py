"""Top-level orchestration: load workbook, run all checks, return ValidationReport."""
from __future__ import annotations

import time

from .loader import open_workbook, load_all
from .lookup_loader import (
    load_lookup_field_types,
    load_lookup_fields_entry,
    load_lookup_mandatory_fields,
    load_lookup_plant_profit_center,
)
from .schema_check import validate_schema
from .cross_field import run_cross_checks
from .lookup_checks import check_product_type_vs_lookup, check_plant_profit_center
from .ai_flags import run_ai_flags
from .models import Finding, Severity, ValidationReport


def run_validation(file_path_or_bytes, file_name: str = "uploaded.xls",
                   lookup_bytes: bytes | None = None,
                   use_ai: bool = True, api_key: str | None = None,
                   model: str = "claude-haiku-4-5",
                   provider: str = "anthropic",
                   progress_callback=None,
                   ai_progress_callback=None) -> ValidationReport:
    """
    progress_callback(pct: int, message: str) — called at each major stage.
    pct is 0-100. If None, no progress reporting.
    """
    def _progress(pct: int, msg: str):
        if progress_callback:
            progress_callback(pct, msg)

    started = time.perf_counter()

    # -- Stage 1: Load lookup file --
    _progress(5, "Loading Master Lookup File…")
    lookup_specs       = load_lookup_field_types(lookup_bytes)         if lookup_bytes else None
    fields_entry       = load_lookup_fields_entry(lookup_bytes)        if lookup_bytes else {}
    mandatory_by_mtart = load_lookup_mandatory_fields(lookup_bytes)    if lookup_bytes else {}
    plant_pc_map       = load_lookup_plant_profit_center(lookup_bytes) if lookup_bytes else {}

    # -- Stage 2: Read workbook --
    _progress(15, "Reading Material Master workbook…")
    book = open_workbook(file_path_or_bytes)
    specs, data = load_all(book)
    report = ValidationReport(file_name=file_name)
    report.sheets_seen = sorted(data.keys())

    # Build product → MTART map from Basic Data (used for non-Basic-Data sheets)
    _progress(25, "Preparing field specifications…")
    product_mtart_map: dict[str, str] = {}
    basic_sd = data.get("Basic Data")
    if basic_sd and basic_sd.rows:
        for _row in basic_sd.rows:
            _cells = _row.get("_cells", {})
            _pc = _cells.get("PRODUCT")
            _mc = _cells.get("MTART")
            if _pc and _mc:
                _prod = str(_pc.get("value", "")).strip()
                _mtype = str(_mc.get("value", "")).strip().upper()
                if _prod and _mtype:
                    product_mtart_map[_prod] = _mtype

    # -- Stage 3: Schema validations (per sheet) --
    sheets_list = [(sn, sd) for sn, sd in data.items() if sd.rows]
    n_sheets = len(sheets_list) or 1
    _distinct_products: set[str] = set()
    for idx, (sheet_name, sd) in enumerate(sheets_list):
        pct = 30 + int((idx / n_sheets) * 25)   # 30 → 55
        _progress(pct, f"Schema check: {sheet_name} ({idx + 1}/{n_sheets})…")
        report.rows_total += len(sd.rows)
        for _row in sd.rows:
            _pc = _row.get("_cells", {}).get("PRODUCT")
            if _pc and _pc.get("value") is not None:
                _p = str(_pc["value"]).strip()
                if _p:
                    _distinct_products.add(_p)
        for f in validate_schema(
            specs, sd,
            lookup_specs=lookup_specs,
            mandatory_by_mtart=mandatory_by_mtart or None,
            product_mtart_map=product_mtart_map or None,
        ):
            report.add(f)

    # Distinct material numbers seen across all sheets; fall back to the
    # Basic Data row count when the PRODUCT column is absent entirely.
    report.materials_total = len(_distinct_products) or (
        len(basic_sd.rows) if basic_sd and basic_sd.rows else 0
    )

    # -- Stage 4: Cross-field consistency --
    _progress(60, "Running cross-field consistency checks…")
    for f in run_cross_checks(data):
        report.add(f)

    # -- Stage 5: Lookup-file driven checks --
    _progress(75, "Running lookup-file validations…")
    for f in check_product_type_vs_lookup(
        data.get("Basic Data"),
        data.get("Class Data"),
        data.get("Valuation Data"),
        fields_entry,
    ):
        report.add(f)

    for f in check_plant_profit_center(data.get("Plant Data"), plant_pc_map):
        report.add(f)

    # -- Stage 6: AI checks --
    _progress(85, "Running online AI checks…" if use_ai else "Skipping AI checks…")
    ai_findings, ai_result, candidate_count = run_ai_flags(
        data, use_ai=use_ai, api_key=api_key, model=model, provider=provider,
        ai_progress_callback=ai_progress_callback,
    )
    for f in ai_findings:
        report.add(f)
    report.ai_calls = ai_result.calls
    report.ai_input_tokens = ai_result.input_tokens
    report.ai_output_tokens = ai_result.output_tokens

    _progress(100, "Validation complete.")
    report.elapsed_ms = int((time.perf_counter() - started) * 1000)
    return report
