"""
Schema validation: Importance, Type, Length, Decimal.

Priority 1 — Lookup file 'Field Types' sheet (SAP Type / SAP Length / SAP Decimal).
Priority 2 — 'Field List' sheet in the migration template (fallback for fields not
             present in the lookup file).
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Any

import xlrd

from .models import FieldSpec, Finding, Severity, SheetData


def _is_blank(value: Any, ctype: int | None = None) -> bool:
    if value is None:
        return True
    if ctype == xlrd.XL_CELL_EMPTY or ctype == xlrd.XL_CELL_BLANK:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return False


def _length_of(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, float):
        # if integer-valued, count digits without trailing .0
        if value.is_integer():
            return len(str(int(value)))
        return len(repr(value))
    return len(str(value).strip())


def _decimal_places(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, (int,)):
        return 0
    if isinstance(value, float):
        if value.is_integer():
            return 0
        s = repr(value)
        if "e" in s.lower():
            # scientific notation; estimate
            return 16
        if "." in s:
            return len(s.split(".", 1)[1])
        return 0
    s = str(value).strip()
    if "." in s:
        try:
            float(s)
        except ValueError:
            return 0
        return len(s.split(".", 1)[1])
    return 0


def _looks_like_number(value: Any) -> bool:
    if isinstance(value, (int, float)):
        return True
    s = str(value).strip()
    if not s:
        return False
    try:
        float(s.replace(",", ""))
        return True
    except ValueError:
        return False


def _looks_like_date(value: Any, ctype: int | None) -> bool:
    if ctype == xlrd.XL_CELL_DATE:
        return True
    if isinstance(value, (dt.date, dt.datetime)):
        return True
    s = str(value).strip()
    if not s:
        return False
    # tolerate common SAP date formats
    return bool(re.match(r"^\d{4}[-/]\d{2}[-/]\d{2}$", s) or re.match(r"^\d{8}$", s) or re.match(r"^\d{2}[./-]\d{2}[./-]\d{4}$", s))


def _looks_like_time(value: Any) -> bool:
    if isinstance(value, dt.time):
        return True
    s = str(value).strip()
    return bool(re.match(r"^\d{1,2}:\d{2}(:\d{2})?$", s) or re.match(r"^\d{6}$", s))


def _resolve(spec: FieldSpec, sheet_name: str,
             lookup_specs: dict | None) -> tuple[str, int | None, int | None, str]:
    """
    Return (effective_type, effective_length, effective_decimal, source_label).
    Lookup file (SAP columns) is Priority 1; Field List is Priority 2 fallback.
    """
    if lookup_specs:
        key = (sheet_name.lower(), spec.description.lower())
        lspec = lookup_specs.get(key)
        if lspec:
            eff_type    = (lspec.sap_type or lspec.type or spec.type or "").strip().lower()
            eff_length  = lspec.sap_length  if lspec.sap_length  is not None else spec.length
            eff_decimal = lspec.sap_decimal if lspec.sap_decimal is not None else spec.decimal
            return eff_type, eff_length, eff_decimal, "lookup"
    return (spec.type or "").strip().lower(), spec.length, spec.decimal, "field_list"


def validate_schema(specs: dict[tuple[str, str], FieldSpec], sheet: SheetData,
                    lookup_specs: dict | None = None,
                    mandatory_by_mtart: dict | None = None,
                    product_mtart_map: dict | None = None) -> list[Finding]:
    """
    Validate every data row against field-type / length / decimal rules.

    lookup_specs      — SAP Type/Length/Decimal from the lookup 'Field Types' sheet
                        (Priority 1). Falls back to Field List when absent.

    mandatory_by_mtart — dict[material_type_upper, set[(sheet_lower, field_desc_lower)]]
                         built from the lookup 'Fields Entry' X-marks.
                         When a material type IS present here, Fields Entry X-marks
                         determine mandatory fields.
                         When ABSENT (req 6 & 7), Field List importance flag is used.

    product_mtart_map  — dict[product, material_type_upper] built from Basic Data.
                         Used to resolve MTART for rows in non-Basic-Data sheets.
    """
    findings: list[Finding] = []
    if not sheet.rows:
        return findings

    # Build per-sheet spec lookup (keyed by SAP field code)
    sheet_specs = {fld: spec for (sh, fld), spec in specs.items() if sh == sheet.sheet}

    for row in sheet.rows:
        excel_row = row["_row"]
        cells = row["_cells"]
        _pc = cells.get("PRODUCT")
        product = str(_pc["value"]).strip() if _pc and _pc.get("value") is not None else ""

        # Resolve MTART for this row (direct cell → fallback to product map)
        mtart = ""
        _mc = cells.get("MTART")
        if _mc and _mc.get("value") is not None:
            mtart = str(_mc["value"]).strip().upper()
        if not mtart and product and product_mtart_map:
            mtart = product_mtart_map.get(product, "").upper()

        # Decide which mandatory-field source to use for this row
        # Priority 1: Fields Entry X-marks (if MTART found in lookup)
        # Priority 2: Field List importance flag (req 6 & 7 fallback)
        use_fields_entry = (
            mandatory_by_mtart is not None
            and mtart
            and mtart in mandatory_by_mtart
        )
        fields_entry_mandatory: set = mandatory_by_mtart[mtart] if use_fields_entry else set()

        # --- Mandatory check ---
        for sap_field, spec in sheet_specs.items():
            if use_fields_entry:
                # Use Fields Entry: field is mandatory iff it has 'X' for this MTART
                key = (sheet.sheet.lower(), spec.description.lower())
                is_mandatory = key in fields_entry_mandatory
            else:
                # Fallback: Field List importance flag (req 6 & 7)
                is_mandatory = spec.is_mandatory

            if not is_mandatory:
                continue
            cell = cells.get(sap_field)
            if cell is None or _is_blank(cell["value"], cell.get("type")):
                source_note = "" if use_fields_entry else " (Field List)"
                findings.append(Finding(
                    severity=Severity.ERROR,
                    category="Schema/Mandatory",
                    sheet=sheet.sheet,
                    row=excel_row,
                    field=spec.description,
                    sap_field=sap_field,
                    message=f"Mandatory field '{spec.description}' is empty{source_note}.",
                    material=product,
                    rule_id="SCHEMA_MANDATORY",
                ))

        # --- Per-cell type / length / decimal checks ---
        for sap_field, cell in cells.items():
            if _is_blank(cell["value"], cell.get("type")):
                continue
            spec = sheet_specs.get(sap_field)
            if spec is None:
                continue   # field not in Field List — skip silently

            value = cell["value"]
            ctype = cell.get("type")

            # Resolve effective constraints (lookup = P1, field_list = P2)
            t, eff_length, eff_decimal, _src = _resolve(spec, sheet.sheet, lookup_specs)

            if t == "number":
                if not _looks_like_number(value):
                    findings.append(Finding(
                        severity=Severity.ERROR,
                        category="Schema/Type",
                        sheet=sheet.sheet,
                        row=excel_row,
                        field=spec.description,
                        sap_field=sap_field,
                        message=f"Expected Number; got '{value}'.",
                        material=product,
                        value=value,
                        rule_id="SCHEMA_TYPE_NUMBER",
                    ))
                else:
                    if eff_decimal is not None:
                        dp = _decimal_places(value)
                        if dp > eff_decimal:
                            findings.append(Finding(
                                severity=Severity.WARNING,
                                category="Schema/Decimal",
                                sheet=sheet.sheet,
                                row=excel_row,
                                field=spec.description,
                                sap_field=sap_field,
                                message=(f"Has {dp} decimal places; "
                                         f"max allowed is {eff_decimal}."),
                                material=product,
                                value=value,
                                rule_id="SCHEMA_DECIMAL",
                            ))
                    if eff_length is not None:
                        s = str(value)
                        digit_count = sum(1 for c in s if c.isdigit())
                        if digit_count > eff_length:
                            findings.append(Finding(
                                severity=Severity.ERROR,
                                category="Schema/Length",
                                sheet=sheet.sheet,
                                row=excel_row,
                                field=spec.description,
                                sap_field=sap_field,
                                message=(f"Number has {digit_count} digits; "
                                         f"max allowed is {eff_length}."),
                                material=product,
                                value=value,
                                rule_id="SCHEMA_LENGTH_NUM",
                            ))
            elif t == "date":
                if not _looks_like_date(value, ctype):
                    findings.append(Finding(
                        severity=Severity.ERROR,
                        category="Schema/Type",
                        sheet=sheet.sheet,
                        row=excel_row,
                        field=spec.description,
                        sap_field=sap_field,
                        message=f"Expected Date (YYYY-MM-DD or YYYYMMDD); got '{value}'.",
                        material=product,
                        value=value,
                        rule_id="SCHEMA_TYPE_DATE",
                    ))
            elif t == "time":
                if not _looks_like_time(value):
                    findings.append(Finding(
                        severity=Severity.ERROR,
                        category="Schema/Type",
                        sheet=sheet.sheet,
                        row=excel_row,
                        field=spec.description,
                        sap_field=sap_field,
                        message=f"Expected Time (HH:MM:SS); got '{value}'.",
                        material=product,
                        value=value,
                        rule_id="SCHEMA_TYPE_TIME",
                    ))
            elif t == "text":
                if eff_length is not None:
                    s = (str(value).strip() if not isinstance(value, float)
                         else (str(int(value)) if value.is_integer() else repr(value)))
                    if len(s) > eff_length:
                        findings.append(Finding(
                            severity=Severity.ERROR,
                            category="Schema/Length",
                            sheet=sheet.sheet,
                            row=excel_row,
                            field=spec.description,
                            sap_field=sap_field,
                            message=f"Text length {len(s)} exceeds max {eff_length}.",
                            material=product,
                            value=value,
                            rule_id="SCHEMA_LENGTH_TEXT",
                        ))

    return findings
