"""
Dynamic dependency rules from the lookup file's 'Dependencies' sheet.

Users maintain conditional business rules as rows of
    trigger field | trigger value | up to five plain-English conditions
e.g.  Product type | ZDEV | Valuation class should be one of: Z002 - Z015

The rules are re-read from the uploaded lookup on EVERY run, so users can add
or change them without any deployment. Condition texts are interpreted by a
deterministic template parser (business rules must not depend on model
guesswork); anything the parser cannot understand produces a visible warning
listing the supported phrasings — a rule is never silently ignored.

Supported condition templates (case-insensitive, quotes optional):
    <field> should [not] start with <value>
    <field> should [not] end with <value>
    <field> should [not] contain <value>
    <field> should [not] be one of [the following][:] v1 - v2 - v3   (also , ;)
    <field> should [not] be empty     |  <field> should be maintained/filled
    <field> should [not] be [equal to] <value>

Field names are resolved against the template's Field List descriptions
(exact match after normalisation). If a name matches several columns
(e.g. 'Valuation Class' exists on Basic Data and Valuation Data), the column
that actually contains data wins; a remaining tie prefers Basic Data.
Conditions on other sheets are joined per material via the Product number.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .models import FieldSpec, Finding, Severity, SheetData

RULE_ERROR    = "LKP_DEPENDENCY"
RULE_SUMMARY  = "LKP_DEPENDENCY_INFO"
RULE_UNPARSED = "LKP_DEPENDENCY_UNPARSED"

_SUPPORTED_HINT = (
    "Supported phrasings: \"<field> should [not] start/end with <value>\", "
    "\"<field> should [not] contain <value>\", "
    "\"<field> should [not] be one of: A - B - C\", "
    "\"<field> should [not] be empty\", "
    "\"<field> should [not] be <value>\"."
)


@dataclass
class Condition:
    field_name: str          # as written by the user
    op: str                  # startswith | endswith | contains | one_of | empty | equals
    negate: bool
    operands: list[str]      # normalised (upper-case) comparison values

    def describe(self) -> str:
        neg = "not " if self.negate else ""
        if self.op == "one_of":
            return f"should {neg}be one of {', '.join(self.operands)}"
        if self.op == "empty":
            return f"should {neg}be empty"
        if self.op == "equals":
            return f"should {neg}be '{self.operands[0]}'"
        verb = {"startswith": "start with", "endswith": "end with",
                "contains": "contain"}[self.op]
        return f"should {neg}{verb} '{self.operands[0]}'"


def _unquote(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'“”":
        return s[1:-1].strip()
    return s.strip("\"'“” ").strip()


def _split_list(s: str) -> list[str]:
    parts = re.split(r"\s*[,;]\s*|\s+-\s+|\s*-\s*", s)
    return [_unquote(p).upper() for p in parts if _unquote(p)]


def parse_condition(text: str) -> Condition | None:
    """Parse one plain-English condition into a Condition, or None."""
    t = re.sub(r"\s+", " ", (text or "").strip())
    m = re.match(r'^(?P<field>.+?)\s+should\s+(?P<rest>.+)$', t, re.I)
    if not m:
        return None
    field = _unquote(m.group("field"))
    rest = m.group("rest").strip()

    neg = False
    nm = re.match(r"^not\s+(.*)$", rest, re.I)
    if nm:
        neg = True
        rest = nm.group(1).strip()

    patterns: list[tuple[str, str]] = [
        (r"^starts?\s+with\s+(?P<v>.+)$",                       "startswith"),
        (r"^ends?\s+with\s+(?P<v>.+)$",                         "endswith"),
        (r"^contains?\s+(?P<v>.+)$",                            "contains"),
        (r"^be\s+one\s+of(?:\s+the\s+following)?\s*:?\s*(?P<v>.+)$", "one_of"),
        (r"^be\s+empty$",                                       "empty"),
        (r"^be\s+(?:maintained|filled)$",                       "not_empty"),
        (r"^be\s+(?:equal\s+to\s+)?(?P<v>.+)$",                 "equals"),
    ]
    for pat, op in patterns:
        pm = re.match(pat, rest, re.I)
        if not pm:
            continue
        if op == "empty":
            return Condition(field, "empty", neg, [])
        if op == "not_empty":   # "should be maintained" == "should not be empty"
            return Condition(field, "empty", not neg, [])
        raw = pm.group("v").strip()
        if op == "one_of":
            values = _split_list(raw)
            return Condition(field, op, neg, values) if values else None
        value = _unquote(raw)
        if not value:
            return None
        # The bare-equality fallback ("should be X") must only accept short,
        # code-like values — otherwise a rule the author phrased in some
        # unsupported way ("should be consistent with ...") would silently
        # become an equality check and flood the report with false errors.
        # Better to reject it and surface a "not understood" warning.
        if op == "equals" and (len(value) > 40 or len(value.split()) > 3):
            return None
        return Condition(field, op, neg, [value.upper()])
    return None


# ---------------------------------------------------------------------------
# Field resolution & row access
# ---------------------------------------------------------------------------

def _norm_desc(s: str) -> str:
    """Same normalisation the Fields Entry matching uses (schema_check)."""
    s = re.sub(r"\([^)]*\)", " ", (s or "").lower())
    s = re.sub(r"\s+", " ", s).strip()
    if s.startswith("material "):
        s = s[len("material "):]
    return s


def _cell_str(row, sap_field: str) -> str:
    c = row["_cells"].get(sap_field)
    if c is None:
        return ""
    v = c.get("value")
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip()


def resolve_field(name: str, specs: dict[tuple[str, str], FieldSpec],
                  data: dict[str, SheetData]) -> tuple[str, str, str] | None:
    """Resolve a user-written field name → (sheet, sap_field, description).

    Exact description match after normalisation. Ambiguity: prefer the column
    that actually contains data; remaining ties prefer Basic Data.
    """
    wanted = _norm_desc(name)
    if not wanted:
        return None
    candidates = [
        (sheet, fld, sp.description)
        for (sheet, fld), sp in specs.items()
        if _norm_desc(sp.description) == wanted
    ]
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    def has_data(sheet: str, fld: str) -> bool:
        sd = data.get(sheet)
        if not sd:
            return False
        return any(_cell_str(r, fld) for r in sd.rows)

    candidates.sort(key=lambda c: (
        not has_data(c[0], c[1]),       # populated columns first
        c[0] != "Basic Data",           # then Basic Data
        c[0],                           # then stable by sheet name
    ))
    return candidates[0]


def _evaluate(cond: Condition, value: str) -> bool:
    v = value.upper()
    if cond.op == "empty":
        result = (v == "")
    elif cond.op == "startswith":
        result = v.startswith(cond.operands[0])
    elif cond.op == "endswith":
        result = v.endswith(cond.operands[0])
    elif cond.op == "contains":
        result = cond.operands[0] in v
    elif cond.op == "one_of":
        result = v in cond.operands
    elif cond.op == "equals":
        result = v == cond.operands[0]
    else:
        return True
    return not result if cond.negate else result


# ---------------------------------------------------------------------------
# Main check
# ---------------------------------------------------------------------------

def check_dependencies(raw_rules: list[dict],
                       specs: dict[tuple[str, str], FieldSpec],
                       data: dict[str, SheetData]) -> list[Finding]:
    findings: list[Finding] = []
    if not raw_rules:
        return findings

    dep_sheet_label = "Dependencies"

    for rule in raw_rules:
        where = f"'{dep_sheet_label}' sheet row {rule['row']}"

        cond = parse_condition(rule["condition"])
        if cond is None:
            findings.append(Finding(
                Severity.WARNING, "Lookup/Dependency", dep_sheet_label, rule["row"],
                "Dependency rule", None,
                (f"Rule in {where} was NOT checked — condition not understood: "
                 f"\"{rule['condition']}\". {_SUPPORTED_HINT}"),
                rule_id=RULE_UNPARSED,
            ))
            continue

        trigger = resolve_field(rule["trigger_field"], specs, data)
        target = resolve_field(cond.field_name, specs, data)
        unresolved = ([f"'{rule['trigger_field']}'"] if trigger is None else []) \
                   + ([f"'{cond.field_name}'"] if target is None else [])
        if unresolved:
            findings.append(Finding(
                Severity.WARNING, "Lookup/Dependency", dep_sheet_label, rule["row"],
                "Dependency rule", None,
                (f"Rule in {where} was NOT checked — field name(s) {', '.join(unresolved)} "
                 f"not found in the template's Field List."),
                rule_id=RULE_UNPARSED,
            ))
            continue

        trig_sheet, trig_fld, trig_desc = trigger
        tgt_sheet, tgt_fld, tgt_desc = target
        trig_value = rule["trigger_value"].upper()

        trig_sd = data.get(trig_sheet)
        rule_label = (f"when '{trig_desc}' = '{rule['trigger_value']}' -> "
                      f"'{tgt_desc}' {cond.describe()}")

        # Index the target sheet's rows per material for cross-sheet rules.
        tgt_rows_by_product: dict[str, list] = {}
        if tgt_sheet != trig_sheet:
            tgt_sd = data.get(tgt_sheet)
            for r in (tgt_sd.rows if tgt_sd else []):
                p = _cell_str(r, "PRODUCT")
                if p:
                    tgt_rows_by_product.setdefault(p.upper(), []).append(r)

        matched = 0
        violations = 0
        for row in (trig_sd.rows if trig_sd else []):
            if _cell_str(row, trig_fld).upper() != trig_value:
                continue
            matched += 1
            product = _cell_str(row, "PRODUCT")

            if tgt_sheet == trig_sheet:
                target_rows = [row]
            else:
                target_rows = tgt_rows_by_product.get(product.upper(), [])
                if not target_rows:
                    violations += 1
                    findings.append(Finding(
                        Severity.ERROR, "Lookup/Dependency", trig_sheet, row["_row"],
                        tgt_desc, tgt_fld,
                        (f"When '{trig_desc}' = '{rule['trigger_value']}', '{tgt_desc}' "
                         f"{cond.describe()} — but this material has no '{tgt_sheet}' "
                         f"row to satisfy the rule ({where})."),
                        material=product, rule_id=RULE_ERROR,
                    ))
                    continue

            for trow in target_rows:
                value = _cell_str(trow, tgt_fld)
                if not _evaluate(cond, value):
                    violations += 1
                    findings.append(Finding(
                        Severity.ERROR, "Lookup/Dependency", tgt_sheet, trow["_row"],
                        tgt_desc, tgt_fld,
                        (f"When '{trig_desc}' = '{rule['trigger_value']}', '{tgt_desc}' "
                         f"{cond.describe()} — found "
                         f"{'nothing (empty)' if value == '' else repr(value)} ({where})."),
                        material=product, value=value, rule_id=RULE_ERROR,
                    ))

        # One transparency line per rule: how it was interpreted and what it did.
        findings.append(Finding(
            Severity.INFO, "Lookup/Dependency", dep_sheet_label, rule["row"],
            "Dependency rule", None,
            (f"Rule in {where} interpreted as: {rule_label}. "
             f"Trigger matched {matched} material(s); {violations} violation(s)."),
            rule_id=RULE_SUMMARY,
        ))

    return findings
