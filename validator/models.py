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

    def to_dict(self) -> dict:
        return {
            "file_name": self.file_name,
            "rows_total": self.rows_total,
            "materials_total": self.materials_total,
            "sheets_seen": self.sheets_seen,
            "counts": self.counts(),
            "ai_calls": self.ai_calls,
            "ai_input_tokens": self.ai_input_tokens,
            "ai_output_tokens": self.ai_output_tokens,
            "elapsed_ms": self.elapsed_ms,
            "findings": [f.to_dict() for f in self.findings],
        }
