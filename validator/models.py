from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


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
    rows: list[dict]


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

    def to_dict(self) -> dict:
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
            "findings": [f.to_dict() for f in self.findings],
        }
