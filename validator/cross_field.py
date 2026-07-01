"""
Cross-field / cross-extension consistency checks for SAP S/4HANA Material Master.

Coverage:
  - Duplicate product numbers within Basic Data
  - Very-similar descriptions within Basic Data (potential duplicate entries)
  - Plants (S_MARC) MRP, procurement, status validity
  - Sales (S_MVKE) status validity, item categories — derived from Distribution Chains sheet
  - Purchasing (within Plant Data S_MARC: EKGRP, EKWSL etc.)
  - Accounting & Costing (S_MBEW Valuation Data)
  - Production (work scheduling fields S_MARC: FEVOR, AUSME, BSTRF, FHORI)
  - Alternative UoM (S_MARM) sanity
  - Master existence cross-references between sheets
"""
from __future__ import annotations

import difflib
import re
from collections import defaultdict
from typing import Any


# Tokens that represent pack sizes / quantities — e.g. "500G", "1.5KG", "750ML", "10M"
# Longer unit suffixes listed before shorter ones to avoid prefix mis-matches.
_PACK_SIZE_RE = re.compile(
    r"^\d+[\.,]?\d*"
    r"(?:kgm|grm|mlt|cmt|mmt|kmt|ltr|mtr"
    r"|kg|mg|ml|cl|km|mm|cm|oz|lb|lbs"
    r"|pcs|pce|pack|pk|ct|pc|ea"
    r"|g|l|m)$",
    re.I,
)


def _strip_quantities(tokens: frozenset) -> frozenset:
    """Remove pack-size/quantity tokens (e.g. '500G', '2KG', '750ML') from a token set."""
    return frozenset(t for t in tokens if not _PACK_SIZE_RE.match(t))

from .models import Finding, Severity, SheetData
from .uom_conversion import check_conversion
from .uom_data import is_valid_sap_uom, describe_sap_uom


def _v(row: dict, sap: str) -> Any:
    cell = row.get("_cells", {}).get(sap)
    if cell is None:
        return None
    val = cell.get("value")
    if isinstance(val, str):
        s = val.strip()
        return s or None
    if val == "" or val is None:
        return None
    return val


def _s(row: dict, sap: str) -> str:
    v = _v(row, sap)
    return str(v).strip() if v is not None else ""


def _f(row: dict, sap: str) -> float | None:
    v = _v(row, sap)
    if v is None:
        return None
    try:
        return float(str(v).replace(",", ""))
    except ValueError:
        return None


def _row_no(row: dict) -> int:
    return row.get("_row", 0)


# -----------------------------------------------------------------------------
# Plant Data (S_MARC) - covers MRP, Forecasting hooks, Production scheduling,
# Purchasing on plant level.
# -----------------------------------------------------------------------------
def check_plant_data(sheet: SheetData) -> list[Finding]:
    findings: list[Finding] = []
    if sheet is None or not sheet.rows:
        return findings

    for row in sheet.rows:
        r = _row_no(row)
        product = _s(row, "PRODUCT")
        plant = _s(row, "WERKS")
        mrp_type = _s(row, "DISMM")
        mrp_controller = _s(row, "DISPO")
        lot_size = _s(row, "DISLS")
        reorder = _f(row, "MINBE")
        max_stock = _f(row, "MABST")
        round_value = _f(row, "BSTRF")
        proc_type = _s(row, "BESKZ")  # E=in-house, F=external, X=both
        special_proc = _s(row, "SOBSL")
        purchasing_grp = _s(row, "EKGRP")
        plant_status = _s(row, "MMSTA")
        status_valid_from = _v(row, "MMSTD")
        sloc = _s(row, "LGPRO")  # production storage location
        prod_scheduler = _s(row, "FEVOR")
        avail_check = _s(row, "MTVFP")
        ctrl_area = _s(row, "KOKRS")
        profit_center = _s(row, "PRCTR")

        # ---------- MRP block ----------
        is_nd = mrp_type.upper() == "ND" if mrp_type else False

        if mrp_type:
            if is_nd:
                # MRP type 'ND' = no planning. Only check that MRP fields are not populated.
                if reorder is not None or lot_size or max_stock is not None:
                    findings.append(Finding(Severity.WARNING, "Cross/MRP", sheet.sheet, r,
                        "MRP Type", "DISMM",
                        "MRP type 'ND' (no planning) but other MRP fields are populated.",
                        material=product, rule_id="X_MRP_ND_INCONSISTENT"))
            else:
                # Active MRP type — run full MRP checks
                if not mrp_controller:
                    findings.append(Finding(Severity.ERROR, "Cross/MRP", sheet.sheet, r,
                        "MRP Controller", "DISPO",
                        f"MRP type '{mrp_type}' set but MRP Controller is empty.",
                        material=product, rule_id="X_MRP_CONTROLLER_REQUIRED"))
                if mrp_type.upper() in {"VB", "VM", "V1", "V2"} and reorder is None:
                    findings.append(Finding(Severity.ERROR, "Cross/MRP", sheet.sheet, r,
                        "Reorder Point", "MINBE",
                        f"Reorder-point MRP type '{mrp_type}' requires Reorder Point.",
                        material=product, rule_id="X_MRP_REORDER_POINT"))
                if not lot_size:
                    findings.append(Finding(Severity.WARNING, "Cross/MRP", sheet.sheet, r,
                        "Lot Sizing Procedure", "DISLS",
                        f"MRP type '{mrp_type}' typically requires a Lot Sizing Procedure.",
                        material=product, rule_id="X_MRP_LOT_SIZE"))

        # Max stock vs reorder point — only meaningful when MRP is active
        if not is_nd and reorder is not None and max_stock is not None and max_stock < reorder:
            findings.append(Finding(Severity.ERROR, "Cross/MRP", sheet.sheet, r,
                "Maximum Stock Level", "MABST",
                f"Maximum Stock ({max_stock}) is less than Reorder Point ({reorder}).",
                material=product, rule_id="X_MRP_MAX_LT_REORDER"))

        # ---------- Procurement ----------
        if proc_type:
            pt = proc_type.upper()
            if pt == "F" and not purchasing_grp:
                findings.append(Finding(Severity.WARNING, "Cross/Purchasing", sheet.sheet, r,
                    "Purchasing Group", "EKGRP",
                    "External procurement (F) usually requires a Purchasing Group.",
                    material=product, rule_id="X_PUR_GROUP_REQUIRED"))
            # Production Scheduler (FEVOR) is only flagged via the mandatory-field
            # check (Fields Entry / Field List importance flag) — not as a
            # cross-field warning, because it is not universally required.

        # ---------- Plant status validity ----------
        if plant_status and not status_valid_from:
            findings.append(Finding(Severity.ERROR, "Cross/Status", sheet.sheet, r,
                "Valid From Date for Status", "MMSTD",
                "Plant-Specific Status set but Valid-From Date is missing.",
                material=product, rule_id="X_STATUS_VALID_FROM"))

        # ---------- Production scheduling sanity ----------
        if round_value is not None and round_value < 0:
            findings.append(Finding(Severity.ERROR, "Cross/Production", sheet.sheet, r,
                "Rounding Value", "BSTRF",
                f"Rounding Value cannot be negative ({round_value}).",
                material=product, rule_id="X_PROD_ROUNDING_NEG"))

        # ---------- Controlling / costing alignment ----------
        if profit_center and not ctrl_area:
            findings.append(Finding(Severity.WARNING, "Cross/Costing", sheet.sheet, r,
                "Controlling Area", "KOKRS",
                "Profit Center set but Controlling Area is missing.",
                material=product, rule_id="X_CO_AREA_REQUIRED"))

        # ---------- Availability check vs MRP type ----------
        if avail_check == "" and mrp_type and not is_nd:
            findings.append(Finding(Severity.INFO, "Cross/MRP", sheet.sheet, r,
                "Availability Check", "MTVFP",
                "Availability Check group is recommended when MRP is active.",
                material=product, rule_id="X_AVAIL_CHECK_RECOMMENDED"))

        if not product or not plant:
            findings.append(Finding(Severity.ERROR, "Cross/Key", sheet.sheet, r,
                "Product/Plant", "PRODUCT/WERKS",
                "Plant Data row missing Product or Plant key.",
                material=product, rule_id="X_KEY_PLANT"))

    return findings


# -----------------------------------------------------------------------------
# Valuation Data (S_MBEW) - Accounting & Costing
# -----------------------------------------------------------------------------
def check_valuation(sheet: SheetData) -> list[Finding]:
    findings: list[Finding] = []
    if sheet is None or not sheet.rows:
        return findings

    for row in sheet.rows:
        r = _row_no(row)
        product = _s(row, "PRODUCT")
        plant = _s(row, "BWKEY")  # valuation area
        val_class = _s(row, "BKLAS")
        price_ctrl = _s(row, "VPRSV").upper()  # S=standard, V=moving
        std_price = _f(row, "STPRS")
        mov_price = _f(row, "VERPR")
        price_unit = _f(row, "PEINH")
        currency = _s(row, "STPRS_CURR") or _s(row, "WAERS")
        total_stock = _f(row, "LBKUM")
        total_value = _f(row, "SALK3")

        if not val_class:
            findings.append(Finding(Severity.ERROR, "Cross/Costing", sheet.sheet, r,
                "Valuation Class", "BKLAS",
                "Valuation Class is required to create the Accounting view.",
                material=product, rule_id="X_VAL_CLASS_REQUIRED"))

        if price_ctrl and price_ctrl not in {"S", "V"}:
            findings.append(Finding(Severity.ERROR, "Cross/Costing", sheet.sheet, r,
                "Price Control", "VPRSV",
                f"Price Control must be 'S' (standard) or 'V' (moving avg); got '{price_ctrl}'.",
                material=product, rule_id="X_PRICE_CTRL_VALUE"))

        if price_ctrl == "S":
            if std_price is None or std_price <= 0:
                findings.append(Finding(Severity.ERROR, "Cross/Costing", sheet.sheet, r,
                    "Standard Price", "STPRS",
                    "Standard Price (>0) required when Price Control = 'S'.",
                    material=product, rule_id="X_STD_PRICE_REQUIRED"))
            if mov_price is not None and mov_price > 0 and std_price is not None:
                findings.append(Finding(Severity.INFO, "Cross/Costing", sheet.sheet, r,
                    "Moving Avg Price", "VERPR",
                    "Moving Avg Price provided though Price Control is 'S' (standard). Will be ignored.",
                    material=product, rule_id="X_MOV_PRICE_IGNORED"))

        if price_ctrl == "V":
            if mov_price is None or mov_price <= 0:
                findings.append(Finding(Severity.ERROR, "Cross/Costing", sheet.sheet, r,
                    "Moving Avg Price", "VERPR",
                    "Moving Avg Price (>0) required when Price Control = 'V'.",
                    material=product, rule_id="X_MOV_PRICE_REQUIRED"))
            if total_stock is not None and total_stock != 0 and total_value is not None:
                expected = (mov_price or 0) * total_stock / (price_unit or 1)
                if abs(expected - total_value) > max(1.0, 0.01 * abs(expected)):
                    findings.append(Finding(Severity.WARNING, "Cross/Costing", sheet.sheet, r,
                        "Total Value", "SALK3",
                        f"Total Value {total_value} != stock x price/unit ({expected:.2f}).",
                        material=product, rule_id="X_VAL_INCONSISTENT"))

        if (std_price is not None or mov_price is not None) and not currency:
            findings.append(Finding(Severity.WARNING, "Cross/Costing", sheet.sheet, r,
                "Currency", "WAERS",
                "Price entered without a currency indicator.",
                material=product, rule_id="X_CURRENCY_MISSING"))

        if price_unit is not None and price_unit <= 0:
            findings.append(Finding(Severity.ERROR, "Cross/Costing", sheet.sheet, r,
                "Price Unit", "PEINH",
                f"Price Unit must be > 0 (got {price_unit}).",
                material=product, rule_id="X_PRICE_UNIT_POSITIVE"))

        if not product or not plant:
            findings.append(Finding(Severity.ERROR, "Cross/Key", sheet.sheet, r,
                "Product/Valuation Area", "PRODUCT/BWKEY",
                "Valuation row missing Product or Valuation Area.",
                material=product, rule_id="X_KEY_VAL"))

    return findings


# -----------------------------------------------------------------------------
# Distribution Chains (S_MVKE) - Sales view
# -----------------------------------------------------------------------------
def check_sales(sheet: SheetData) -> list[Finding]:
    findings: list[Finding] = []
    if sheet is None or not sheet.rows:
        return findings

    for row in sheet.rows:
        r = _row_no(row)
        product = _s(row, "PRODUCT")
        sales_org = _s(row, "VKORG")
        dist_chan = _s(row, "VTWEG")
        sales_status = _s(row, "VMSTA")
        status_from = _v(row, "VMSTD")
        item_cat_grp = _s(row, "MTPOS")
        acct_assign = _s(row, "KTGRM")
        tax_class = _s(row, "TAXM1")
        min_order = _f(row, "AUMNG")
        sales_unit = _s(row, "VRKME")

        if not sales_org or not dist_chan:
            findings.append(Finding(Severity.ERROR, "Cross/Sales", sheet.sheet, r,
                "Sales Org / Distribution Channel", "VKORG/VTWEG",
                "Sales Organisation and Distribution Channel are required.",
                material=product, rule_id="X_SALES_ORG"))

        if sales_status and not status_from:
            findings.append(Finding(Severity.ERROR, "Cross/Sales", sheet.sheet, r,
                "Sales Status Valid From", "VMSTD",
                "Sales status set but Valid-From Date is missing.",
                material=product, rule_id="X_SALES_STATUS_VALID"))

        # Account Assignment Group (KTGRM) is only flagged via the mandatory-field
        # check (Fields Entry / Field List importance flag) — not as a cross-field
        # warning, because it is not universally required.

        if min_order is not None and min_order < 0:
            findings.append(Finding(Severity.ERROR, "Cross/Sales", sheet.sheet, r,
                "Minimum Order Quantity", "AUMNG",
                f"Minimum Order Quantity cannot be negative ({min_order}).",
                material=product, rule_id="X_SALES_MIN_ORDER_NEG"))

        if not product:
            findings.append(Finding(Severity.ERROR, "Cross/Key", sheet.sheet, r,
                "Product", "PRODUCT",
                "Distribution Chains row missing Product key.",
                material=product, rule_id="X_KEY_SALES"))

    return findings


# -----------------------------------------------------------------------------
# Alternative Units of Measure (S_MARM)
# -----------------------------------------------------------------------------
def check_alt_uom(sheet: SheetData, basic_data: SheetData | None) -> list[Finding]:
    findings: list[Finding] = []
    if sheet is None or not sheet.rows:
        return findings

    base_uom_by_product: dict[str, str] = {}
    mtart_by_product: dict[str, str] = {}
    if basic_data and basic_data.rows:
        for row in basic_data.rows:
            p = _s(row, "PRODUCT")
            if p:
                base_uom_by_product[p] = _s(row, "MEINS")
                mtart_by_product[p] = _s(row, "MTART")

    seen: dict[tuple[str, str], int] = {}
    gtin_seen: dict[str, int] = {}

    for row in sheet.rows:
        r = _row_no(row)
        product = _s(row, "PRODUCT")
        alt_uom = _s(row, "MEINH")
        denom = _f(row, "UMREN")
        numer = _f(row, "UMREZ")
        gtin = _s(row, "EAN11")
        length = _f(row, "LAENG")
        width = _f(row, "BREIT")
        height = _f(row, "HOEHE")
        dim_unit = _s(row, "MEABM")

        if not product or not alt_uom:
            findings.append(Finding(Severity.ERROR, "Cross/Key", sheet.sheet, r,
                "Product/Alt UoM", "PRODUCT/MEINH",
                "Alternative UoM row missing Product or Alternative UoM.",
                material=product, rule_id="X_KEY_ALTUOM"))
            continue

        # Cannot equal base UoM
        base = base_uom_by_product.get(product)
        if base and alt_uom.lower() == base.lower():
            findings.append(Finding(Severity.ERROR, "Cross/AltUoM", sheet.sheet, r,
                "Alt UoM = Base UoM", "MEINH",
                f"Alternative UoM '{alt_uom}' equals the Base UoM in Basic Data.",
                material=product, rule_id="X_ALT_EQ_BASE"))

        # Numerator/Denominator
        if numer is None or numer <= 0 or denom is None or denom <= 0:
            findings.append(Finding(Severity.ERROR, "Cross/AltUoM", sheet.sheet, r,
                "Conversion factors", "UMREN/UMREZ",
                "Both Numerator (UMREZ) and Denominator (UMREN) must be > 0.",
                material=product, rule_id="X_ALT_CONV_INVALID"))

        # Duplicate alt UoM
        key = (product, alt_uom.lower())
        if key in seen:
            findings.append(Finding(Severity.ERROR, "Cross/AltUoM", sheet.sheet, r,
                "Duplicate Alt UoM", "MEINH",
                f"Alternative UoM '{alt_uom}' duplicated for product (also row {seen[key]}).",
                material=product, rule_id="X_ALT_DUPLICATE"))
        else:
            seen[key] = r

        # Duplicate GTIN across rows
        if gtin:
            if gtin in gtin_seen:
                findings.append(Finding(Severity.ERROR, "Cross/AltUoM", sheet.sheet, r,
                    "GTIN", "EAN11",
                    f"GTIN '{gtin}' already used in row {gtin_seen[gtin]}.",
                    material=product, rule_id="X_ALT_GTIN_DUP"))
            else:
                gtin_seen[gtin] = r
            # GTIN length sanity
            digits = "".join(c for c in gtin if c.isdigit())
            if len(digits) not in {8, 12, 13, 14}:
                findings.append(Finding(Severity.WARNING, "Cross/AltUoM", sheet.sheet, r,
                    "GTIN length", "EAN11",
                    f"GTIN '{gtin}' has {len(digits)} digits; expected 8/12/13/14.",
                    material=product, rule_id="X_ALT_GTIN_LEN"))

        # Dimensions need a unit
        if any(v is not None and v > 0 for v in (length, width, height)) and not dim_unit:
            findings.append(Finding(Severity.ERROR, "Cross/AltUoM", sheet.sheet, r,
                "Unit of Dimension", "MEABM",
                "Length/Width/Height entered but Unit of Dimension is missing.",
                material=product, rule_id="X_ALT_DIM_UNIT"))

        # --- Advanced conversion checks ---
        if base and alt_uom and alt_uom.lower() != (base or "").lower():
            mtart = mtart_by_product.get(product, "")
            for issue in check_conversion(base, alt_uom, denom, numer, mtart, product):
                findings.append(Finding(
                    severity=issue.severity,
                    category="Cross/AltUoM",
                    sheet=sheet.sheet,
                    row=r,
                    field="UoM Conversion",
                    sap_field="MEINS/MEINH/UMREN/UMREZ",
                    message=issue.message,
                    material=product,
                    value=f"{base} -> {alt_uom} (ratio={denom}/{numer})",
                    rule_id=issue.rule_id,
                ))

    return findings


# -----------------------------------------------------------------------------
# Storage Locations - must exist on a Plant in Plant Data
# -----------------------------------------------------------------------------
def check_storage_locations(sheet: SheetData, plant_data: SheetData | None) -> list[Finding]:
    findings: list[Finding] = []
    if sheet is None or not sheet.rows:
        return findings

    plants = set()
    if plant_data and plant_data.rows:
        for row in plant_data.rows:
            p = _s(row, "PRODUCT")
            w = _s(row, "WERKS")
            if p and w:
                plants.add((p, w))

    for row in sheet.rows:
        r = _row_no(row)
        product = _s(row, "PRODUCT")
        plant = _s(row, "WERKS")
        sloc = _s(row, "LGORT")

        if not (product and plant and sloc):
            findings.append(Finding(Severity.ERROR, "Cross/Key", sheet.sheet, r,
                "Storage Loc keys", "PRODUCT/WERKS/LGORT",
                "Storage Location row missing one of Product/Plant/Storage Location.",
                material=product, rule_id="X_KEY_SLOC"))
            continue
        if (product, plant) not in plants:
            findings.append(Finding(Severity.WARNING, "Cross/Reference", sheet.sheet, r,
                "Plant not maintained", "WERKS",
                f"Plant '{plant}' for product '{product}' not found in Plant Data sheet.",
                material=product, rule_id="X_SLOC_PLANT_MISSING"))

    return findings


# -----------------------------------------------------------------------------
# Forecasting Data <-> Plant Data MRP type
# -----------------------------------------------------------------------------
def check_forecasting(sheet: SheetData, plant_data: SheetData | None) -> list[Finding]:
    findings: list[Finding] = []
    if sheet is None or not sheet.rows:
        return findings

    plant_keys = set()
    if plant_data and plant_data.rows:
        for row in plant_data.rows:
            plant_keys.add((_s(row, "PRODUCT"), _s(row, "WERKS")))

    for row in sheet.rows:
        r = _row_no(row)
        product = _s(row, "PRODUCT")
        plant = _s(row, "WERKS")
        model = _s(row, "PRMOD")
        periods = _f(row, "PERAN")

        if product and plant and (product, plant) not in plant_keys:
            findings.append(Finding(Severity.WARNING, "Cross/Reference", sheet.sheet, r,
                "Plant", "WERKS",
                f"Forecasting maintained for plant '{plant}' but no matching Plant Data row.",
                material=product, rule_id="X_FCST_PLANT_MISSING"))

        if model and periods is None:
            findings.append(Finding(Severity.WARNING, "Cross/Forecast", sheet.sheet, r,
                "Periods per Season", "PERAN",
                f"Forecast model '{model}' set but Periods per Season missing.",
                material=product, rule_id="X_FCST_PERIODS"))

    return findings


# -----------------------------------------------------------------------------
# MRP Area
# -----------------------------------------------------------------------------
def check_mrp_area(sheet: SheetData) -> list[Finding]:
    findings: list[Finding] = []
    if sheet is None or not sheet.rows:
        return findings

    for row in sheet.rows:
        r = _row_no(row)
        product = _s(row, "PRODUCT")
        mrp_area = _s(row, "BERID")
        mrp_type = _s(row, "DISMM")
        controller = _s(row, "DISPO")
        if mrp_area and mrp_type and mrp_type.upper() != "ND" and not controller:
            findings.append(Finding(Severity.ERROR, "Cross/MRP", sheet.sheet, r,
                "MRP Controller", "DISPO",
                f"MRP Area '{mrp_area}' with MRP type '{mrp_type}' requires MRP Controller.",
                material=product, rule_id="X_MRPA_CONTROLLER"))
        if not product or not mrp_area:
            findings.append(Finding(Severity.ERROR, "Cross/Key", sheet.sheet, r,
                "MRP Area Key", "PRODUCT/BERID",
                "MRP Area row missing Product or MRP Area.",
                material=product, rule_id="X_KEY_MRPA"))
    return findings


# -----------------------------------------------------------------------------
# Inspection Setup - if used, must have inspection type
# -----------------------------------------------------------------------------
def check_inspection(sheet: SheetData) -> list[Finding]:
    findings: list[Finding] = []
    if sheet is None or not sheet.rows:
        return findings
    for row in sheet.rows:
        r = _row_no(row)
        product = _s(row, "PRODUCT")
        plant = _s(row, "WERKS")
        ins_type = _s(row, "ART")
        active = _s(row, "AKTIV")
        if active and active.lower() in {"x", "true", "1"} and not ins_type:
            findings.append(Finding(Severity.ERROR, "Cross/QM", sheet.sheet, r,
                "Inspection Type", "ART",
                "Active inspection but Inspection Type is missing.",
                material=product, rule_id="X_QM_TYPE"))
        if not product or not plant:
            findings.append(Finding(Severity.ERROR, "Cross/Key", sheet.sheet, r,
                "Inspection Key", "PRODUCT/WERKS",
                "Inspection row missing Product or Plant.",
                material=product, rule_id="X_KEY_QM"))
    return findings


# -----------------------------------------------------------------------------
# Cross-extension references: every product in extension sheets must exist in Basic Data.
# -----------------------------------------------------------------------------
def check_product_existence(data: dict[str, SheetData]) -> list[Finding]:
    findings: list[Finding] = []
    basic = data.get("Basic Data")
    if not basic or not basic.rows:
        return findings
    basic_products = {_s(row, "PRODUCT") for row in basic.rows if _s(row, "PRODUCT")}

    for sheet_name, sd in data.items():
        if sheet_name == "Basic Data" or not sd.rows:
            continue
        for row in sd.rows:
            p = _s(row, "PRODUCT")
            if p and p not in basic_products:
                findings.append(Finding(Severity.ERROR, "Cross/Reference", sheet_name, _row_no(row),
                    "Product", "PRODUCT",
                    f"Product '{p}' is referenced but not defined in 'Basic Data'.",
                    material=p, rule_id="X_PRODUCT_NOT_IN_BASIC"))
    return findings


# -----------------------------------------------------------------------------
# Duplicate product numbers within Basic Data
# -----------------------------------------------------------------------------
def check_duplicate_products(basic: SheetData | None) -> list[Finding]:
    """Error if the same product/material number appears more than once in Basic Data."""
    findings: list[Finding] = []
    if not basic or not basic.rows:
        return findings

    seen: dict[str, int] = {}          # normalised key -> first row number
    for row in basic.rows:
        r = _row_no(row)
        product = _s(row, "PRODUCT")
        if not product:
            continue
        key = product.strip().upper()
        if key in seen:
            findings.append(Finding(
                Severity.ERROR, "Duplicate/ProductNumber", basic.sheet, r,
                "Product Number", "PRODUCT",
                f"Duplicate product number '{product}' — already defined in row {seen[key]}.",
                material=product,
                value=product,
                rule_id="X_DUP_PRODUCT_NUMBER",
            ))
        else:
            seen[key] = r
    return findings


# -----------------------------------------------------------------------------
# Very-similar descriptions within Basic Data (potential duplicate entries)
# -----------------------------------------------------------------------------
def _token_overlap(tokens_a: frozenset, tokens_b: frozenset) -> float:
    """
    Overlap coefficient = |A ∩ B| / min(|A|, |B|).
    Returns 1.0 when the smaller token set is fully contained in the larger.
    e.g. {"TOMATO"} vs {"FRESH","TOMATO"} → 1/1 = 1.0
    """
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / min(len(tokens_a), len(tokens_b))


def check_similar_descriptions(basic: SheetData | None,
                                seq_threshold: float = 0.50,
                                overlap_threshold: float = 0.85,
                                max_findings: int = 50) -> list[Finding]:
    """
    Warning when two materials have descriptions that are similar enough to be
    potential duplicate entries.  Two independent signals are combined:

      1. SequenceMatcher ratio >= seq_threshold (0.90)
         Catches near-identical strings and word-order variants after token sorting.
         e.g. 'CHOCOLATE MILK 500G' vs 'MILK CHOCOLATE 500G'

      2. Token overlap coefficient >= overlap_threshold (0.85)
         Catches subset/containment cases.
         e.g. 'TOMATO' fully inside 'FRESH TOMATO' → overlap = 1.0

    A pair is flagged if EITHER signal exceeds its threshold.
    Normalisation: upper-case, collapse whitespace.
    O(n²) — fast enough for typical SAP migration file sizes (<2 000 rows).
    """
    findings: list[Finding] = []
    if not basic or not basic.rows:
        return findings

    # Build per-row data: (row_no, product, original_descr, sorted-norm, token frozenset)
    items: list[tuple[int, str, str, str, frozenset]] = []
    for row in basic.rows:
        r       = _row_no(row)
        product = _s(row, "PRODUCT")
        descr   = _s(row, "MAKTX")
        if not descr:
            continue
        tokens  = frozenset(descr.upper().split())
        norm    = " ".join(sorted(tokens))        # sorted for SequenceMatcher
        items.append((r, product, descr, norm, tokens))

    reported: set[tuple[int, int]] = set()
    for i in range(len(items)):
        if len(findings) >= max_findings:
            break
        r1, p1, d1, n1, t1 = items[i]
        for j in range(i + 1, len(items)):
            if len(findings) >= max_findings:
                break
            r2, p2, d2, n2, t2 = items[j]
            # same product number already caught by duplicate-product check
            if p1 and p2 and p1.upper() == p2.upper():
                continue
            pair = (r1, r2)
            if pair in reported:
                continue

            # Skip pairs that are the same product in different pack sizes
            # (descriptions identical once quantity/unit tokens are removed)
            s1, s2 = _strip_quantities(t1), _strip_quantities(t2)
            if s1 and s1 == s2:
                continue

            # Signal 1: token-overlap (cheap — check first)
            overlap = _token_overlap(t1, t2)
            if overlap >= overlap_threshold:
                reported.add(pair)
                reason = f"token overlap {overlap:.0%}"
            else:
                # Signal 2: character-level sequence match on sorted tokens
                ratio = difflib.SequenceMatcher(None, n1, n2).ratio()
                if ratio >= seq_threshold:
                    reported.add(pair)
                    reason = f"{ratio:.0%} character similarity"
                else:
                    continue

            snippet = d1[:60] + ("…" if len(d1) > 60 else "")
            findings.append(Finding(
                Severity.WARNING, "Duplicate/Description", basic.sheet, r2,
                "Material Description", "MAKTX",
                (f"Description may be a duplicate of product '{p1}' "
                 f"(row {r1}, {reason}): '{snippet}'."),
                material=p2,
                value=d2[:120],
                rule_id="X_DUP_DESCRIPTION",
            ))
    return findings


# -----------------------------------------------------------------------------
# Run all
# -----------------------------------------------------------------------------
def check_basic_uom_codes(sheet: SheetData | None) -> list[Finding]:
    """Validate that every Base UoM (MEINS) in Basic Data is a valid SAP code."""
    findings: list[Finding] = []
    if sheet is None or not sheet.rows:
        return findings
    for row in sheet.rows:
        r = _row_no(row)
        product = _s(row, "PRODUCT")
        uom = _s(row, "MEINS")
        if uom and not is_valid_sap_uom(uom):
            findings.append(Finding(
                Severity.ERROR, "Cross/UoM", sheet.sheet, r,
                "Base UoM (MEINS)", "MEINS",
                f"Base UoM '{uom}' is not a recognised ISO or SAP UoM code "
                "(not in SAP_UOM_All.xlsx). Check for typos.",
                material=product, value=uom, rule_id="X_BASE_UOM_INVALID_SAP",
            ))
    return findings


def run_cross_checks(data: dict[str, SheetData]) -> list[Finding]:
    findings: list[Finding] = []
    findings += check_duplicate_products(data.get("Basic Data"))
    findings += check_similar_descriptions(data.get("Basic Data"))
    findings += check_product_existence(data)
    findings += check_basic_uom_codes(data.get("Basic Data"))
    findings += check_plant_data(data.get("Plant Data"))
    findings += check_valuation(data.get("Valuation Data"))
    findings += check_sales(data.get("Distribution Chains"))
    findings += check_alt_uom(data.get("Alternative Units of Measure"), data.get("Basic Data"))
    findings += check_storage_locations(data.get("Storage Locations"), data.get("Plant Data"))
    findings += check_forecasting(data.get("Forecasting Data"), data.get("Plant Data"))
    findings += check_mrp_area(data.get("MRP Area"))
    findings += check_inspection(data.get("Inspection Setup Data"))
    return findings
