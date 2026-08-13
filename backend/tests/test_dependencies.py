"""Unit tests for the dynamic Dependencies rule engine."""
import pytest

from validator.dependencies import (
    Condition, check_dependencies, parse_condition, resolve_field,
)
from validator.models import FieldSpec, Row, SheetData


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text,op,negate,operands", [
    ('"Product group" should start with "ZDEV"', "startswith", False, ["ZDEV"]),
    ("Product group should start with ZDEV",      "startswith", False, ["ZDEV"]),
    ("Plant should end with 01",                  "endswith",   False, ["01"]),
    ("Description should contain STERILE",        "contains",   False, ["STERILE"]),
    ("Valuation class should be one of the following: Z002 - Z015 - Z017",
                                                  "one_of",     False, ["Z002", "Z015", "Z017"]),
    ("Valuation class should be one of: Z002, Z015",
                                                  "one_of",     False, ["Z002", "Z015"]),
    ("Shelf life should not be empty",            "empty",      True,  []),
    ("Shelf life should be maintained",           "empty",      True,  []),
    ("Base Unit should be empty",                 "empty",      False, []),
    ("Product type should be equal to FERT",      "equals",     False, ["FERT"]),
    ("Product type should be FERT",               "equals",     False, ["FERT"]),
    ("Product type should not be DIEN",           "equals",     True,  ["DIEN"]),
])
def test_parse_condition(text, op, negate, operands):
    cond = parse_condition(text)
    assert cond is not None, text
    assert (cond.op, cond.negate, cond.operands) == (op, negate, operands)


@pytest.mark.parametrize("text", [
    "",
    "just some words",
    "Product group must start with ZDEV",           # unsupported verb
    "Base UoM should be gibberish nonsense text weird",  # too long for equals
    "X should be consistent with the master data list definition",
])
def test_parse_condition_rejects(text):
    assert parse_condition(text) is None


# ---------------------------------------------------------------------------
# Execution on synthetic data
# ---------------------------------------------------------------------------

def _sheet(name, fields, rows):
    """Build a SheetData from field names and row value-lists."""
    keymap = {f: i for i, f in enumerate(fields)}
    return SheetData(
        sheet=name, sap_structure="S_TEST", sap_fields=list(fields),
        descriptions=[""] * len(fields),
        rows=[Row(row_num=9 + i, vals=tuple(vals), types=None, keymap=keymap)
              for i, vals in enumerate(rows)],
    )


@pytest.fixture()
def world():
    specs = {
        ("Basic Data", "MTART"):  FieldSpec("Basic Data", "", "Product Type",  "", "Text", 4, None, "S", "MTART"),
        ("Basic Data", "MATKL"):  FieldSpec("Basic Data", "", "Product Group", "", "Text", 9, None, "S", "MATKL"),
        ("Basic Data", "WBKLA"):  FieldSpec("Basic Data", "", "Valuation Class", "", "Text", 4, None, "S", "WBKLA"),
        ("Valuation Data", "BKLAS"): FieldSpec("Valuation Data", "", "Valuation Class", "", "Text", 4, None, "S", "BKLAS"),
    }
    data = {
        "Basic Data": _sheet("Basic Data", ["PRODUCT", "MTART", "MATKL", "WBKLA"], [
            ("M1", "ZDEV", "ZDEV_01", None),
            ("M2", "ZDEV", "OTHER_9", None),
            ("M3", "FERT", "OTHER_9", None),
        ]),
        "Valuation Data": _sheet("Valuation Data", ["PRODUCT", "BKLAS"], [
            ("M1", "Z002"),
            ("M2", "Z999"),
            # M3 intentionally has no valuation row
        ]),
    }
    return specs, data


def test_resolve_prefers_populated_column(world):
    specs, data = world
    # 'Valuation Class' matches WBKLA (empty) and BKLAS (populated) → BKLAS wins
    assert resolve_field("Valuation class", specs, data)[:2] == ("Valuation Data", "BKLAS")


def test_same_sheet_rule(world):
    specs, data = world
    rules = [{"row": 2, "trigger_field": "Product type", "trigger_value": "ZDEV",
              "condition": 'Product group should start with "ZDEV"'}]
    fs = check_dependencies(rules, specs, data)
    errors = [f for f in fs if f.severity.value == "error"]
    assert len(errors) == 1 and errors[0].material == "M2"
    info = [f for f in fs if f.rule_id == "LKP_DEPENDENCY_INFO"]
    assert "matched 2 material(s); 1 violation(s)" in info[0].message


def test_cross_sheet_rule_and_missing_row(world):
    specs, data = world
    rules = [{"row": 3, "trigger_field": "Product type", "trigger_value": "ZDEV",
              "condition": "Valuation class should be one of: Z002 - Z015"},
             {"row": 4, "trigger_field": "Product type", "trigger_value": "FERT",
              "condition": "Valuation class should be one of: Z002"}]
    fs = check_dependencies(rules, specs, data)
    errors = [f for f in fs if f.severity.value == "error"]
    # M2's BKLAS Z999 not allowed; M3 (FERT) has no Valuation Data row at all
    assert {e.material for e in errors} == {"M2", "M3"}
    assert any("no 'Valuation Data' row" in e.message for e in errors)


def test_unparseable_and_unknown_field_are_reported(world):
    specs, data = world
    rules = [{"row": 5, "trigger_field": "Product type", "trigger_value": "ZDEV",
              "condition": "something entirely unstructured"},
             {"row": 6, "trigger_field": "No Such Field", "trigger_value": "X",
              "condition": "Product group should start with A"}]
    fs = check_dependencies(rules, specs, data)
    assert all(f.rule_id == "LKP_DEPENDENCY_UNPARSED" for f in fs)
    assert len(fs) == 2
    assert all(f.severity.value == "warning" for f in fs)
