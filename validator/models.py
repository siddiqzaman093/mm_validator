import datetime as _dt
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Iterator

import xlrd


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


# ---------------------------------------------------------------------------
# Compact row storage.
#
# A 60k-row workbook stored as one dict per cell needs gigabytes; these
# __slots__ classes keep one value-tuple per row and expose the same dict-like
# API the check modules already use (row["_row"], row["_cells"],
# cells.get(field), cells.items(), cell["value"], cell.get("type")), so the
# checks don't change.
# ---------------------------------------------------------------------------

def _derive_ctype(v: Any) -> int:
    """Map a Python value to the xlrd cell-type constants the checks expect."""
    if v is None:
        return xlrd.XL_CELL_EMPTY
    if isinstance(v, bool):
        return xlrd.XL_CELL_BOOLEAN
    if isinstance(v, (int, float)):
        return xlrd.XL_CELL_NUMBER
    if isinstance(v, (_dt.date, _dt.datetime, _dt.time)):
        return xlrd.XL_CELL_DATE
    return xlrd.XL_CELL_TEXT


class Cell:
    """Per-cell view; API-compatible with the old {"value":…, "type":…} dict."""
    __slots__ = ("value", "type")

    def __init__(self, value: Any, ctype: int):
        self.value = value
        self.type = ctype

    def __getitem__(self, key: str) -> Any:
        if key == "value":
            return self.value
        if key == "type":
            return self.type
        raise KeyError(key)

    def get(self, key: str, default: Any = None) -> Any:
        if key == "value":
            return self.value
        if key == "type":
            return self.type
        return default


class Cells:
    """Mapping view over one row's cells, keyed by SAP field code."""
    __slots__ = ("_row",)

    def __init__(self, row: "Row"):
        self._row = row

    def _cell(self, i: int) -> Cell:
        r = self._row
        v = r.vals[i] if i < len(r.vals) else None
        t = r.types[i] if r.types is not None else _derive_ctype(v)
        # The old loader stored "" (never None) for blank cells; keep that.
        return Cell("" if v is None else v, t)

    def get(self, key: str, default: Any = None) -> Any:
        i = self._row.keymap.get(key)
        return self._cell(i) if i is not None else default

    def __getitem__(self, key: str) -> Cell:
        i = self._row.keymap.get(key)
        if i is None:
            raise KeyError(key)
        return self._cell(i)

    def __contains__(self, key: str) -> bool:
        return key in self._row.keymap

    def __len__(self) -> int:
        return len(self._row.keymap)

    def items(self) -> Iterator[tuple[str, Cell]]:
        for k, i in self._row.keymap.items():
            yield k, self._cell(i)

    def __iter__(self) -> Iterator[str]:
        return iter(self._row.keymap)


class Row:
    """One data row; API-compatible with the old {"_row":…, "_cells":…} dict.

    keymap is SHARED per sheet (sap_field → index into vals); vals holds only
    the values of mapped columns; types is None for .xlsx (derived from the
    value) or a tuple of xlrd cell types for .xls (dates are floats there and
    can't be told apart from numbers without it).
    """
    __slots__ = ("row_num", "vals", "types", "keymap")

    def __init__(self, row_num: int, vals: tuple, types: tuple | None,
                 keymap: dict[str, int]):
        self.row_num = row_num
        self.vals = vals
        self.types = types
        self.keymap = keymap

    def __getitem__(self, key: str) -> Any:
        if key == "_row":
            return self.row_num
        if key == "_cells":
            return Cells(self)
        raise KeyError(key)

    def get(self, key: str, default: Any = None) -> Any:
        if key == "_row":
            return self.row_num
        if key == "_cells":
            return Cells(self)
        return default


@dataclass
class Finding:
    severity: Severity
    category: str
    sheet: str
    row: int | None
    field: str | None
    sap_field: str | None
    message: str
    material: str = ""
    value: Any = None
    rule_id: str = ""
    ai_generated: bool = False

    def to_dict(self) -> dict:
        return {
            "severity": self.severity.value,
            "category": self.category,
            "sheet": self.sheet,
            "row": self.row,
            "field": self.field,
            "sap_field": self.sap_field,
            "message": self.message,
            "material": self.material,
            "value": self.value,
            "rule_id": self.rule_id,
            "ai_generated": self.ai_generated,
        }


@dataclass
class FieldSpec:
    sheet: str
    group: str
    description: str
    importance: str
    type: str
    length: int | None
    decimal: int | None
    sap_structure: str
    sap_field: str

    @property
    def is_mandatory(self) -> bool:
        return "mandatory" in (self.importance or "").lower()


@dataclass
class SheetData:
    sheet: str
    sap_structure: str
    sap_fields: list[str]
    descriptions: list[str]
    rows: list[Row]


@dataclass
class ValidationReport:
    file_name: str
    findings: list[Finding] = field(default_factory=list)
    sheets_seen: list[str] = field(default_factory=list)
    rows_total: int = 0
    materials_total: int = 0
    ai_calls: int = 0
    ai_input_tokens: int = 0
    ai_output_tokens: int = 0
    elapsed_ms: int = 0

    def add(self, f: Finding) -> None:
        self.findings.append(f)

    def counts(self) -> dict[str, int]:
        out = {s.value: 0 for s in Severity}
        for f in self.findings:
            out[f.severity.value] += 1
        return out

    def readiness(self) -> dict:
        """
        Overall migration-readiness score for the uploaded data, 0–100.

        Per-material: a material with ≥1 error is blocked (full penalty);
        a material with warnings only costs 30% of a material. File-level
        findings (no material key, e.g. missing sheets/columns) subtract
        flat points: 5 per error (max 25), 1 per warning (max 10).
        """
        mats_err: set[str] = set()
        mats_warn: set[str] = set()
        global_err = global_warn = 0
        for f in self.findings:
            m = (f.material or "").strip()
            if f.severity == Severity.ERROR:
                if m:
                    mats_err.add(m)
                else:
                    global_err += 1
            elif f.severity == Severity.WARNING:
                if m:
                    mats_warn.add(m)
                else:
                    global_warn += 1

        total = self.materials_total
        if total <= 0:
            return {"score": 0, "label": "No data", "band": "red",
                    "ready_materials": 0, "warning_materials": 0,
                    "blocked_materials": 0, "total_materials": 0}

        blocked = len(mats_err)
        warn_only = len(mats_warn - mats_err)
        score = 100.0 * (total - blocked - 0.3 * warn_only) / total
        score -= min(25.0, 5.0 * global_err)
        score -= min(10.0, 1.0 * global_warn)
        score = int(max(0.0, min(100.0, round(score))))

        if score >= 90:
            label, band = "Ready to load", "green"
        elif score >= 70:
            label, band = "Nearly ready", "amber"
        elif score >= 40:
            label, band = "Needs attention", "orange"
        else:
            label, band = "Not ready", "red"

        return {
            "score": score,
            "label": label,
            "band": band,
            "ready_materials": total - blocked,
            "warning_materials": warn_only,
            "blocked_materials": blocked,
            "total_materials": total,
        }

    # Huge files can yield tens of thousands of findings; shipping them all as
    # JSON stalls the browser. The response instead carries a SAMPLE PER
    # CATEGORY (most severe first) so every category appears in the UI with
    # its true totals — a purely global most-severe cut would fill the whole
    # budget with the single biggest error category. Counts/readiness are
    # always computed from the FULL list, and the complete detail is available
    # as a server-side CSV download.
    MAX_FINDINGS_JSON = 5000
    SAMPLES_PER_GROUP = 200

    _SEV_ORDER = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}

    def top_findings(self, cap: int | None) -> list[Finding]:
        """Representative findings: up to SAMPLES_PER_GROUP per category
        (errors first, original order within each severity), globally bounded
        by `cap`. Returns the full list when it fits."""
        if cap is None or len(self.findings) <= cap:
            return self.findings
        by_cat: dict[str, list[Finding]] = {}
        for f in self.findings:
            by_cat.setdefault(f.category, []).append(f)
        shipped: list[Finding] = []
        for cat in sorted(by_cat):
            group = sorted(by_cat[cat], key=lambda f: self._SEV_ORDER.get(f.severity, 9))
            shipped.extend(group[:self.SAMPLES_PER_GROUP])
        if len(shipped) > cap:   # very many categories — trim globally
            shipped = sorted(shipped, key=lambda f: self._SEV_ORDER.get(f.severity, 9))[:cap]
        return shipped

    def _group_counts(self, key) -> list[dict]:
        """True severity totals per group (computed from ALL findings)."""
        out: dict[str, dict] = {}
        for f in self.findings:
            g = out.setdefault(key(f), {"error": 0, "warning": 0, "info": 0})
            g[f.severity.value] += 1
        return [
            {"name": name, **c, "total": c["error"] + c["warning"] + c["info"]}
            for name, c in sorted(out.items())
        ]

    def to_dict(self, max_findings: int | None = MAX_FINDINGS_JSON) -> dict:
        shipped = self.top_findings(max_findings)
        return {
            "file_name": self.file_name,
            "rows_total": self.rows_total,
            "materials_total": self.materials_total,
            "sheets_seen": self.sheets_seen,
            "counts": self.counts(),
            "readiness": self.readiness(),
            "ai_calls": self.ai_calls,
            "ai_input_tokens": self.ai_input_tokens,
            "ai_output_tokens": self.ai_output_tokens,
            "elapsed_ms": self.elapsed_ms,
            "findings_total": len(self.findings),
            "findings_truncated": len(shipped) < len(self.findings),
            # True totals for every category/sheet so the UI can list ALL
            # groups even when only samples of their rows are shipped.
            "category_counts": self._group_counts(lambda f: f.category),
            "sheet_counts": self._group_counts(lambda f: f.sheet),
            "findings": [f.to_dict() for f in shipped],
        }
