"""
Load SAP S/4HANA Migration Cockpit `Product Master Creation.xls` template.

Layout per data sheet:
  row 0: title
  row 1: version / copyright
  row 2: blank
  row 3: SAP structure (e.g. S_MARA, S_MARC, S_MARM, S_MBEW, S_MVKE)
  row 4: SAP field codes (e.g. PRODUCT, MTART, MEINS, ...)
  row 5: format string ETE;80;0;C;80;0
  row 6: group label
  row 7: long description (field name + help text + Type/Length)
  row 8+: actual data rows

Field List sheet header at row 3, values from row 4 onward.
Sheet Name column (col B = idx 1) holds either:
  - "Basic Data (mandatory)" / "Plant Data (optional)" -> sheet header
  - blank -> field row belonging to last seen sheet header
"""
from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Any

import xlrd

from .models import FieldSpec, SheetData


# A unified Book wrapper so the rest of the code can work on either xlrd or
# openpyxl-loaded workbooks transparently.
class _Book:
    """Duck-typed shim with .sheet_names() and .sheet_by_name() returning Sheet."""

    def __init__(self, raw, kind: str):
        self._raw = raw
        self.kind = kind  # "xlrd" or "openpyxl"

    def sheet_names(self) -> list[str]:
        if self.kind == "xlrd":
            return self._raw.sheet_names()
        return list(self._raw.sheetnames)

    def sheet_by_name(self, name: str) -> "_Sheet":
        if self.kind == "xlrd":
            return _Sheet(self._raw.sheet_by_name(name), "xlrd")
        return _Sheet(self._raw[name], "openpyxl")


class _Sheet:
    def __init__(self, raw, kind: str):
        self._raw = raw
        self.kind = kind
        if kind == "xlrd":
            self.nrows = raw.nrows
            self.ncols = raw.ncols
        else:
            # openpyxl uses 1-based indexing internally
            self.nrows = raw.max_row or 0
            self.ncols = raw.max_column or 0

    def cell_value(self, r: int, c: int) -> Any:
        if self.kind == "xlrd":
            return self._raw.cell_value(r, c)
        # openpyxl: rows/cols are 1-based
        v = self._raw.cell(row=r + 1, column=c + 1).value
        return "" if v is None else v

    def cell_type(self, r: int, c: int) -> int:
        if self.kind == "xlrd":
            return self._raw.cell_type(r, c)
        # rough mapping for openpyxl
        v = self._raw.cell(row=r + 1, column=c + 1).value
        if v is None:
            return xlrd.XL_CELL_EMPTY
        if isinstance(v, bool):
            return xlrd.XL_CELL_BOOLEAN
        if isinstance(v, (int, float)):
            return xlrd.XL_CELL_NUMBER
        import datetime as _dt
        if isinstance(v, (_dt.date, _dt.datetime, _dt.time)):
            return xlrd.XL_CELL_DATE
        return xlrd.XL_CELL_TEXT


HEADER_ROW_SAP_FIELDS = 4
HEADER_ROW_FORMAT = 5
HEADER_ROW_DESC = 7
DATA_START_ROW = 8


def _clean(value) -> str:
    if value is None:
        return ""
    s = str(value).strip()
    return s


def _to_int(value) -> int | None:
    s = _clean(value)
    if not s:
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


def _strip_sheet_suffix(name: str) -> str:
    """ 'Basic Data (mandatory)' -> 'Basic Data' """
    return re.sub(r"\s*\((mandatory|optional)\)\s*$", "", name, flags=re.I).strip()


def load_field_list(book: _Book) -> dict[tuple[str, str], FieldSpec]:
    """Return mapping (sheet_name, sap_field) -> FieldSpec."""
    try:
        sh = book.sheet_by_name("Field List")
    except (KeyError, Exception):
        return {}   # Field List sheet absent — validation continues without it
    specs: dict[tuple[str, str], FieldSpec] = {}
    current_sheet: str | None = None

    for r in range(4, sh.nrows):
        sheet_cell = _clean(sh.cell_value(r, 1))
        if sheet_cell:
            current_sheet = _strip_sheet_suffix(sheet_cell)
            continue
        if not current_sheet:
            continue

        group = _clean(sh.cell_value(r, 2))
        desc = _clean(sh.cell_value(r, 3))
        importance = _clean(sh.cell_value(r, 4))
        ftype = _clean(sh.cell_value(r, 5))
        length = _to_int(sh.cell_value(r, 6))
        decimal = _to_int(sh.cell_value(r, 7))
        sap_struct = _clean(sh.cell_value(r, 8))
        sap_field = _clean(sh.cell_value(r, 9))

        if not desc and not sap_field:
            continue

        specs[(current_sheet, sap_field)] = FieldSpec(
            sheet=current_sheet,
            group=group,
            description=desc,
            importance=importance,
            type=ftype,
            length=length,
            decimal=decimal,
            sap_structure=sap_struct,
            sap_field=sap_field,
        )
    return specs


def load_sheet_data(book: _Book, sheet_name: str) -> SheetData | None:
    if sheet_name not in book.sheet_names():
        return None
    sh = book.sheet_by_name(sheet_name)
    if sh.nrows <= DATA_START_ROW:
        sap_structure = _clean(sh.cell_value(3, 0)) if sh.nrows > 3 else ""
        sap_fields = [_clean(sh.cell_value(HEADER_ROW_SAP_FIELDS, c)) for c in range(sh.ncols)] if sh.nrows > HEADER_ROW_SAP_FIELDS else []
        return SheetData(sheet=sheet_name, sap_structure=sap_structure, sap_fields=sap_fields, descriptions=[], rows=[])

    sap_structure = _clean(sh.cell_value(3, 0))
    sap_fields = [_clean(sh.cell_value(HEADER_ROW_SAP_FIELDS, c)) for c in range(sh.ncols)]
    descriptions = []
    for c in range(sh.ncols):
        long = _clean(sh.cell_value(HEADER_ROW_DESC, c))
        head_name = long.split("\n", 1)[0].rstrip("*").strip() if long else ""
        descriptions.append(head_name)

    rows: list[dict] = []
    for r in range(DATA_START_ROW, sh.nrows):
        raw = [sh.cell_value(r, c) for c in range(sh.ncols)]
        if not any(_clean(v) for v in raw):
            continue
        row = {
            "_row": r + 1,  # 1-based excel row number
            "_cells": {},
        }
        for c, sap_field in enumerate(sap_fields):
            if not sap_field:
                continue
            ctype = sh.cell_type(r, c)
            value = sh.cell_value(r, c)
            # xlrd reads every numeric cell as a float, so an integer-valued
            # material number / plant / code (e.g. 1054) becomes 1054.0 and
            # renders with a trailing ".0". Normalise whole numbers to int.
            # Guard on XL_CELL_NUMBER only — dates are floats too and must not
            # be truncated; genuine decimals (12.5) are left untouched.
            if (ctype == xlrd.XL_CELL_NUMBER
                    and isinstance(value, float) and value.is_integer()):
                value = int(value)
            row["_cells"][sap_field] = {
                "value": value,
                "type": ctype,
                "col": c,
                "description": descriptions[c],
            }
        rows.append(row)

    return SheetData(
        sheet=sheet_name,
        sap_structure=sap_structure,
        sap_fields=sap_fields,
        descriptions=descriptions,
        rows=rows,
    )


def open_workbook(file_path_or_bytes, file_name: str | None = None) -> _Book:
    """Open .xls or .xlsx — returns _Book wrapper."""
    if isinstance(file_path_or_bytes, (bytes, bytearray)):
        data = bytes(file_path_or_bytes)
        if data[:4] == b"PK\x03\x04":  # xlsx is a zip
            from openpyxl import load_workbook
            wb = load_workbook(io.BytesIO(data), data_only=True, read_only=False)
            return _Book(wb, "openpyxl")
        return _Book(xlrd.open_workbook(file_contents=data), "xlrd")
    if isinstance(file_path_or_bytes, io.IOBase):
        data = file_path_or_bytes.read()
        return open_workbook(data, file_name)
    path = str(file_path_or_bytes)
    if path.lower().endswith(".xlsx"):
        from openpyxl import load_workbook
        wb = load_workbook(path, data_only=True, read_only=False)
        return _Book(wb, "openpyxl")
    return _Book(xlrd.open_workbook(path), "xlrd")


def load_all(book: _Book) -> tuple[dict[tuple[str, str], FieldSpec], dict[str, SheetData]]:
    specs = load_field_list(book)
    sheets_in_specs = sorted({s for s, _ in specs.keys()})

    # If Field List is absent/empty, fall back to loading every sheet in the workbook
    if not sheets_in_specs:
        sheets_in_specs = book.sheet_names()

    data: dict[str, SheetData] = {}
    for s in sheets_in_specs:
        sd = load_sheet_data(book, s)
        if sd is not None:
            data[s] = sd
    return specs, data
