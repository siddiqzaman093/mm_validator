"""
Plausibility checks for physical amounts relative to a material's Base UoM.

The Alternative-UoM module (uom_conversion.py) validates *conversion ratios*;
this module validates the *amounts themselves* — weights, volumes and
dimensions entered per 1 Base Unit of Measure (MEINS) in Basic Data, plus the
per-unit weight/volume fields on the Alternative UoM sheet.

Check families (category "Cross/UoM Amounts"):
  1. Negative amounts                                  ERROR
  2. Amount entered without its unit                   ERROR
  3. Net weight greater than gross weight              ERROR
  4. Placeholder/test-looking values (999999, 12345…)  WARNING
  5. Weight per base unit implausibly small/large      WARNING
  6. Volume per base unit implausibly small/large      WARNING
  7. Base UoM is itself a mass/volume unit but the
     entered weight/volume contradicts it              WARNING
  8. Declared volume exceeds the L×W×H bounding box    WARNING
  9. Implied density outside physical bounds           WARNING
"""
from __future__ import annotations

from typing import Any

from .models import Finding, Severity, SheetData

_CATEGORY = "Cross/UoM Amounts"

# --- unit → SI factors (lowercase code → factor) -----------------------------
# Weight units → kilograms (SAP internal codes + ISO codes)
_TO_KG: dict[str, float] = {
    "mg": 1e-6, "mgm": 1e-6,
    "g": 1e-3, "grm": 1e-3,
    "kg": 1.0, "kgm": 1.0,
    "to": 1_000.0, "tne": 1_000.0, "t": 1_000.0,
    "ton": 907.185, "stn": 907.185,
    "lb": 0.453592, "lbr": 0.453592, "lbs": 0.453592,
    "oz": 0.0283495, "onz": 0.0283495,
}
# Volume units → litres
_TO_L: dict[str, float] = {
    "ml": 1e-3, "mlt": 1e-3,
    "cl": 1e-2, "clt": 1e-2,
    "l": 1.0, "ltr": 1.0,
    "hl": 100.0, "hlt": 100.0,
    "m3": 1_000.0, "mtq": 1_000.0,
    "ccm": 1e-3, "cmq": 1e-3, "cm3": 1e-3,
    "cd3": 1.0, "dmq": 1.0,
    "gal": 3.78541, "gll": 3.78541,
    "foz": 0.0295735, "oza": 0.0295735,
    "qt": 0.946353, "pt": 0.473176,
    "bbl": 158.987,
}
# Length units → metres
_TO_M: dict[str, float] = {
    "mm": 1e-3, "mmt": 1e-3,
    "cm": 1e-2, "cmt": 1e-2,
    "dm": 0.1, "dmt": 0.1,
    "m": 1.0, "mtr": 1.0,
    "km": 1_000.0, "kmt": 1_000.0,
    "in": 0.0254, "inh": 0.0254,
    "ft": 0.3048, "fot": 0.3048,
    "yd": 0.9144, "yrd": 0.9144,
}

# Plausibility bounds per 1 base unit
_MIN_KG, _MAX_KG = 0.001, 25_000.0        # 1 g … 25 t per base unit
_MIN_L, _MAX_L = 0.001, 100_000.0         # 1 mL … 100 m³ per base unit
_MIN_DENSITY, _MAX_DENSITY = 0.01, 30_000.0  # kg/m³ (air ~1.2, osmium ~22 590)

# Values that usually mean "someone typed a test value"
_PLACEHOLDERS = {12345.0, 123456.0, 1234567.0, 12345678.0,
                 99999.0, 999999.0, 9999999.0}


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


def _is_placeholder(v: float) -> bool:
    if v in _PLACEHOLDERS:
        return True
    digits = str(int(v)) if float(v).is_integer() else ""
    return len(digits) >= 4 and len(set(digits)) == 1  # 1111, 99999, …


def _fmt(v: float) -> str:
    return f"{v:,.6g}"


def check_uom_amounts(basic: SheetData | None,
                      alt_uom: SheetData | None = None) -> list[Finding]:
    findings: list[Finding] = []

    if basic and basic.rows:
        for row in basic.rows:
            findings += _check_basic_row(basic.sheet, row)

    if alt_uom and alt_uom.rows:
        for row in alt_uom.rows:
            findings += _check_alt_row(alt_uom.sheet, row)

    return findings


def _check_basic_row(sheet: str, row: dict) -> list[Finding]:
    out: list[Finding] = []
    r = _row_no(row)
    product = _s(row, "PRODUCT")
    base_uom = _s(row, "MEINS").lower()

    gross = _f(row, "BRGEW")
    net = _f(row, "NTGEW")
    weight_unit = _s(row, "GEWEI").lower()
    volume = _f(row, "VOLUM")
    volume_unit = _s(row, "VOLEH").lower()
    length = _f(row, "LAENG")
    width = _f(row, "BREIT")
    height = _f(row, "HOEHE")
    dim_unit = _s(row, "MEABM").lower()

    def add(sev: Severity, field: str, sap: str, msg: str, rule: str, value=None):
        out.append(Finding(sev, _CATEGORY, sheet, r, field, sap, msg,
                           material=product, value=value, rule_id=rule))

    # 1. Negative amounts are always wrong
    for label, sap, val in (("Gross Weight", "BRGEW", gross),
                            ("Net Weight", "NTGEW", net),
                            ("Volume", "VOLUM", volume),
                            ("Length", "LAENG", length),
                            ("Width", "BREIT", width),
                            ("Height", "HOEHE", height)):
        if val is not None and val < 0:
            add(Severity.ERROR, label, sap,
                f"{label} cannot be negative ({_fmt(val)}).",
                "X_QTY_NEGATIVE", val)

    # 2. Amount without its unit
    if any(v is not None and v > 0 for v in (gross, net)) and not weight_unit:
        add(Severity.ERROR, "Weight Unit", "GEWEI",
            "Gross/Net Weight entered but Weight Unit (GEWEI) is missing.",
            "X_QTY_WEIGHT_UNIT_MISSING")
    if volume is not None and volume > 0 and not volume_unit:
        add(Severity.ERROR, "Volume Unit", "VOLEH",
            "Volume entered but Volume Unit (VOLEH) is missing.",
            "X_QTY_VOL_UNIT_MISSING")
    if any(v is not None and v > 0 for v in (length, width, height)) and not dim_unit:
        add(Severity.ERROR, "Unit of Dimension", "MEABM",
            "Length/Width/Height entered but Unit of Dimension (MEABM) is missing.",
            "X_QTY_DIM_UNIT_MISSING")

    # 3. Net > gross
    if net is not None and gross is not None and net > gross > 0:
        add(Severity.ERROR, "Net vs Gross Weight", "NTGEW/BRGEW",
            f"Net Weight ({_fmt(net)}) exceeds Gross Weight ({_fmt(gross)}).",
            "X_QTY_NET_GT_GROSS", f"net={net}, gross={gross}")

    # 4. Placeholder-looking values
    for label, sap, val in (("Gross Weight", "BRGEW", gross),
                            ("Net Weight", "NTGEW", net),
                            ("Volume", "VOLUM", volume)):
        if val is not None and val > 0 and _is_placeholder(val):
            add(Severity.WARNING, label, sap,
                f"{label} {_fmt(val)} looks like a test/placeholder value — verify.",
                "X_QTY_PLACEHOLDER", val)

    # 5. Weight per base unit plausibility (needs a recognised weight unit)
    kg_factor = _TO_KG.get(weight_unit)
    gross_kg = gross * kg_factor if (gross and kg_factor) else None
    if gross_kg is not None and gross_kg > 0:
        if gross_kg < _MIN_KG:
            add(Severity.WARNING, "Gross Weight", "BRGEW/GEWEI",
                f"Suspiciously small: {_fmt(gross)} {weight_unit.upper()} "
                f"(≈{_fmt(gross_kg * 1000)} g) per 1 {base_uom.upper() or 'base unit'}.",
                "X_QTY_WEIGHT_TINY", f"{gross} {weight_unit}")
        elif gross_kg > _MAX_KG:
            add(Severity.WARNING, "Gross Weight", "BRGEW/GEWEI",
                f"Suspiciously large: {_fmt(gross)} {weight_unit.upper()} "
                f"(≈{_fmt(gross_kg / 1000)} t) per 1 {base_uom.upper() or 'base unit'}.",
                "X_QTY_WEIGHT_HUGE", f"{gross} {weight_unit}")

    # 6. Volume per base unit plausibility
    l_factor = _TO_L.get(volume_unit)
    volume_l = volume * l_factor if (volume and l_factor) else None
    if volume_l is not None and volume_l > 0:
        if volume_l < _MIN_L:
            add(Severity.WARNING, "Volume", "VOLUM/VOLEH",
                f"Suspiciously small: {_fmt(volume)} {volume_unit.upper()} "
                f"(≈{_fmt(volume_l * 1000)} mL) per 1 {base_uom.upper() or 'base unit'}.",
                "X_QTY_VOLUME_TINY", f"{volume} {volume_unit}")
        elif volume_l > _MAX_L:
            add(Severity.WARNING, "Volume", "VOLUM/VOLEH",
                f"Suspiciously large: {_fmt(volume)} {volume_unit.upper()} "
                f"(≈{_fmt(volume_l / 1000)} m³) per 1 {base_uom.upper() or 'base unit'}.",
                "X_QTY_VOLUME_HUGE", f"{volume} {volume_unit}")

    # 7. Base UoM itself is a mass/volume unit — the per-unit amount must agree.
    #    E.g. Base UoM = KG ⇒ the weight of 1 base unit IS 1 kg by definition.
    base_kg = _TO_KG.get(base_uom)
    if base_kg is not None and net is not None and net > 0 and kg_factor:
        net_kg = net * kg_factor
        if abs(net_kg - base_kg) / base_kg > 0.05:
            add(Severity.WARNING, "Net Weight vs Base UoM", "MEINS/NTGEW",
                f"Base UoM is {base_uom.upper()} (= {_fmt(base_kg)} kg), but Net "
                f"Weight per base unit is {_fmt(net)} {weight_unit.upper()} "
                f"(≈{_fmt(net_kg)} kg). These should match — check the amount.",
                "X_QTY_BASE_MASS_MISMATCH", f"{net} {weight_unit}")
    base_l = _TO_L.get(base_uom)
    if base_l is not None and volume is not None and volume > 0 and l_factor:
        vol_l = volume * l_factor
        if abs(vol_l - base_l) / base_l > 0.05:
            add(Severity.WARNING, "Volume vs Base UoM", "MEINS/VOLUM",
                f"Base UoM is {base_uom.upper()} (= {_fmt(base_l)} L), but Volume "
                f"per base unit is {_fmt(volume)} {volume_unit.upper()} "
                f"(≈{_fmt(vol_l)} L). These should match — check the amount.",
                "X_QTY_BASE_VOL_MISMATCH", f"{volume} {volume_unit}")

    # 8. Declared volume vs L×W×H bounding box (volume can never exceed the box)
    m_factor = _TO_M.get(dim_unit)
    if (m_factor and volume_l is not None and volume_l > 0
            and all(v is not None and v > 0 for v in (length, width, height))):
        box_l = (length * m_factor) * (width * m_factor) * (height * m_factor) * 1000.0
        if box_l > 0 and volume_l > box_l * 1.15:
            add(Severity.WARNING, "Volume vs Dimensions",
                "VOLUM/LAENG/BREIT/HOEHE",
                f"Declared volume ≈{_fmt(volume_l)} L exceeds the L×W×H bounding "
                f"box ≈{_fmt(box_l)} L — one of the amounts is wrong.",
                "X_QTY_VOL_GT_BOX", f"vol={volume} {volume_unit}, "
                f"box={length}×{width}×{height} {dim_unit}")

    # 9. Implied density (gross weight / volume) within physical bounds
    if gross_kg is not None and volume_l is not None and gross_kg > 0 and volume_l > 0:
        density = gross_kg / (volume_l / 1000.0)  # kg per m³
        if density > _MAX_DENSITY:
            add(Severity.WARNING, "Weight vs Volume", "BRGEW/VOLUM",
                f"Implied density ≈{_fmt(density)} kg/m³ is denser than any common "
                "material — weight or volume amount looks wrong.",
                "X_QTY_DENSITY_HIGH", f"{gross} {weight_unit} / {volume} {volume_unit}")
        elif density < _MIN_DENSITY:
            add(Severity.WARNING, "Weight vs Volume", "BRGEW/VOLUM",
                f"Implied density ≈{_fmt(density)} kg/m³ is lighter than air — "
                "weight or volume amount looks wrong.",
                "X_QTY_DENSITY_LOW", f"{gross} {weight_unit} / {volume} {volume_unit}")

    return out


def _check_alt_row(sheet: str, row: dict) -> list[Finding]:
    """Weight/volume sanity for Alternative-UoM rows (per 1 alternative unit)."""
    out: list[Finding] = []
    r = _row_no(row)
    product = _s(row, "PRODUCT")
    alt = _s(row, "MEINH").upper()

    gross = _f(row, "BRGEW")
    weight_unit = _s(row, "GEWEI").lower()
    volume = _f(row, "VOLUM")
    volume_unit = _s(row, "VOLEH").lower()

    def add(sev: Severity, field: str, sap: str, msg: str, rule: str, value=None):
        out.append(Finding(sev, _CATEGORY, sheet, r, field, sap, msg,
                           material=product, value=value, rule_id=rule))

    for label, sap, val in (("Gross Weight", "BRGEW", gross), ("Volume", "VOLUM", volume)):
        if val is not None and val < 0:
            add(Severity.ERROR, label, sap,
                f"{label} cannot be negative ({_fmt(val)}) for alt UoM {alt}.",
                "X_QTY_NEGATIVE", val)
        if val is not None and val > 0 and _is_placeholder(val):
            add(Severity.WARNING, label, sap,
                f"{label} {_fmt(val)} for alt UoM {alt} looks like a "
                "test/placeholder value — verify.",
                "X_QTY_PLACEHOLDER", val)

    if gross is not None and gross > 0 and not weight_unit:
        add(Severity.ERROR, "Weight Unit", "GEWEI",
            f"Gross Weight entered for alt UoM {alt} but Weight Unit is missing.",
            "X_QTY_WEIGHT_UNIT_MISSING")
    if volume is not None and volume > 0 and not volume_unit:
        add(Severity.ERROR, "Volume Unit", "VOLEH",
            f"Volume entered for alt UoM {alt} but Volume Unit is missing.",
            "X_QTY_VOL_UNIT_MISSING")

    kg = _TO_KG.get(weight_unit)
    if gross and kg:
        gross_kg = gross * kg
        if 0 < gross_kg < _MIN_KG:
            add(Severity.WARNING, "Gross Weight", "BRGEW/GEWEI",
                f"Suspiciously small: {_fmt(gross)} {weight_unit.upper()} per 1 {alt}.",
                "X_QTY_WEIGHT_TINY", f"{gross} {weight_unit}")
        elif gross_kg > _MAX_KG:
            add(Severity.WARNING, "Gross Weight", "BRGEW/GEWEI",
                f"Suspiciously large: {_fmt(gross)} {weight_unit.upper()} per 1 {alt}.",
                "X_QTY_WEIGHT_HUGE", f"{gross} {weight_unit}")

    return out
