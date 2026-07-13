"""
Lookup-file driven cross-reference validations.

1. Product Type → Material Class + Valuation Type  (Fields Entry sheet)
   1.1  Product type must exist in lookup.
   1.2  Material Class and Valuation Type are retrieved from the lookup.
   1.3  Both are OPTIONAL in the lookup: a blank value means "applies to all"
        for that material type — no finding is raised and no comparison made.
   1.4  When maintained, compare Material Class with Class Data sheet 'Class'.
   1.5  When maintained, compare Valuation Type with Valuation Data 'BWTAR'.

2. Plant → Profit Center  (Plant-ProfitCenter sheet)
   2.1  Get expected Profit Center for each Plant from the lookup.
   2.2  Compare with Profit Center entered in Plant Data.
"""
from __future__ import annotations

from .models import Finding, Severity, SheetData


# ---------------------------------------------------------------------------
# Helpers (mirrors cross_field.py helpers — kept local to avoid import cycle)
# ---------------------------------------------------------------------------
def _v(row: dict, sap: str):
    cell = row.get("_cells", {}).get(sap)
    if cell is None:
        return None
    val = cell.get("value")
    if isinstance(val, str):
        s = val.strip()
        return s or None
    return None if (val is None or val == "") else val


def _s(row: dict, sap: str) -> str:
    v = _v(row, sap)
    return str(v).strip() if v is not None else ""


def _row_no(row: dict) -> int:
    return row.get("_row", 0)


def _norm(s: str) -> str:
    """Normalise a value for comparison: strip, upper, remove leading zeros."""
    s = s.strip().upper()
    # Normalise numeric strings: '001000' == '1000', '1000.0' == '1000'
    try:
        return str(int(float(s)))
    except (ValueError, TypeError):
        return s


# ---------------------------------------------------------------------------
# 1. Product Type → Material Class / Valuation Type
# ---------------------------------------------------------------------------
def check_product_type_vs_lookup(
    basic_data: SheetData | None,
    class_data: SheetData | None,
    valuation_data: SheetData | None,
    fields_entry: dict[str, dict],   # mat_type_upper → {material_class, valuation_type}
) -> list[Finding]:
    """
    Validate every product type (MTART) in Basic Data against the Fields Entry
    lookup and then cross-check Material Class and Valuation Type.
    """
    findings: list[Finding] = []
    if not basic_data or not basic_data.rows or not fields_entry:
        return findings

    # Build product → actual class from Class Data sheet.
    # SAP field for class number may be CLASS, KLASSE, or BKLASSE.
    class_by_product: dict[str, str] = {}
    if class_data and class_data.rows:
        for row in class_data.rows:
            p = _s(row, "PRODUCT")
            cls = _s(row, "CLASS") or _s(row, "KLASSE") or _s(row, "BKLASSE")
            if p and cls:
                class_by_product[p] = cls

    # Build product → actual valuation type from Valuation Data sheet (BWTAR).
    valtype_by_product: dict[str, str] = {}
    if valuation_data and valuation_data.rows:
        for row in valuation_data.rows:
            p  = _s(row, "PRODUCT")
            vt = _s(row, "BWTAR")
            if p and vt:
                valtype_by_product[p] = vt

    for row in basic_data.rows:
        r        = _row_no(row)
        product  = _s(row, "PRODUCT")
        mat_type = _s(row, "MTART").upper()
        if not mat_type:
            continue

        # ── 1.1 Product type not in lookup ────────────────────────────────
        if mat_type not in fields_entry:
            findings.append(Finding(
                severity=Severity.ERROR,
                category="Lookup/ProductType",
                sheet=basic_data.sheet, row=r,
                field="Product Type", sap_field="MTART",
                message=(
                    f"Product type '{mat_type}' is not listed in the lookup file "
                    "(Fields Entry). Verify the product type code."
                ),
                material=product, value=mat_type,
                rule_id="LKP_PRODUCT_TYPE_MISSING",
            ))
            continue

        lkp = fields_entry[mat_type]
        expected_class   = lkp.get("material_class") or ""
        expected_valtype = lkp.get("valuation_type") or ""

        # ── 1.3a/1.4 Material Class: blank in lookup = applies to all ─────
        # (no finding when blank; only compare when a value is maintained)
        if expected_class:
            actual_class = class_by_product.get(product, "")
            if actual_class and _norm(actual_class) != _norm(expected_class):
                findings.append(Finding(
                    severity=Severity.ERROR,
                    category="Lookup/ProductType",
                    sheet=basic_data.sheet, row=r,
                    field="Material Class", sap_field="MTART",
                    message=(
                        f"Material class '{actual_class}' (Class Data sheet) does not "
                        f"match the expected class '{expected_class}' for product type "
                        f"'{mat_type}' as per the lookup file."
                    ),
                    material=product,
                    value=f"actual: {actual_class}  |  expected: {expected_class}",
                    rule_id="LKP_MATERIAL_CLASS_MISMATCH",
                ))

        # ── 1.3b/1.5 Valuation Type: blank in lookup = applies to all ─────
        # (no finding when blank; only compare when a value is maintained)
        if expected_valtype:
            actual_valtype = valtype_by_product.get(product, "")
            if actual_valtype and _norm(actual_valtype) != _norm(expected_valtype):
                findings.append(Finding(
                    severity=Severity.ERROR,
                    category="Lookup/ProductType",
                    sheet=basic_data.sheet, row=r,
                    field="Valuation Type", sap_field="BWTAR",
                    message=(
                        f"Valuation type '{actual_valtype}' (Valuation Data sheet) "
                        f"does not match the expected type '{expected_valtype}' for "
                        f"product type '{mat_type}' as per the lookup file."
                    ),
                    material=product,
                    value=f"actual: {actual_valtype}  |  expected: {expected_valtype}",
                    rule_id="LKP_VALUATION_TYPE_MISMATCH",
                ))

    return findings


# ---------------------------------------------------------------------------
# 2. Plant → Profit Center
# ---------------------------------------------------------------------------
def check_plant_profit_center(
    plant_data: SheetData | None,
    plant_pc_map: dict[str, str],    # normalised_plant → normalised_profit_center
) -> list[Finding]:
    """
    Validate Profit Center (PRCTR) in Plant Data against the
    Plant-ProfitCenter lookup sheet.
    """
    findings: list[Finding] = []
    if not plant_data or not plant_data.rows or not plant_pc_map:
        return findings

    for row in plant_data.rows:
        r             = _row_no(row)
        product       = _s(row, "PRODUCT")
        plant_raw     = _s(row, "WERKS")
        pc_raw        = _s(row, "PRCTR")

        if not plant_raw:
            continue

        plant_key = _norm(plant_raw)
        expected_pc = plant_pc_map.get(plant_key)

        if expected_pc is None:
            findings.append(Finding(
                severity=Severity.ERROR,
                category="Lookup/ProfitCenter",
                sheet=plant_data.sheet, row=r,
                field="Plant", sap_field="WERKS",
                message=(
                    f"Plant '{plant_raw}' is not found in the lookup file "
                    "(Plant-ProfitCenter sheet). Verify the plant code."
                ),
                material=product,
                value=plant_raw,
                rule_id="LKP_PLANT_NOT_IN_LOOKUP",
            ))
            continue

        if not pc_raw:
            # ── Profit Center missing but lookup has an expected value ────
            findings.append(Finding(
                severity=Severity.WARNING,
                category="Lookup/ProfitCenter",
                sheet=plant_data.sheet, row=r,
                field="Profit Center", sap_field="PRCTR",
                message=(
                    f"Profit Center is empty for plant '{plant_raw}'. "
                    f"Expected value from lookup: '{expected_pc}'."
                ),
                material=product,
                value=f"plant: {plant_raw}  |  expected PC: {expected_pc}",
                rule_id="LKP_PROFIT_CENTER_EMPTY",
            ))
        elif _norm(pc_raw) != expected_pc:
            # ── Profit Center mismatch ────────────────────────────────────
            findings.append(Finding(
                severity=Severity.ERROR,
                category="Lookup/ProfitCenter",
                sheet=plant_data.sheet, row=r,
                field="Profit Center", sap_field="PRCTR",
                message=(
                    f"Profit Center '{pc_raw}' for plant '{plant_raw}' does not "
                    f"match the expected value '{expected_pc}' from the lookup file."
                ),
                material=product,
                value=f"actual: {pc_raw}  |  expected: {expected_pc}",
                rule_id="LKP_PROFIT_CENTER_MISMATCH",
            ))

    return findings
