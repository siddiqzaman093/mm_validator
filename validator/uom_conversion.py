"""
Advanced Alternative Unit of Measure conversion validation.
UoM codes may be ISO codes (primary) or SAP internal codes (fallback).
Reference: SAP_UOM_All.xlsx loaded via uom_data.py.

SAP formula:  UMREN alt_units = UMREZ base_units
              alt_per_base = UMREN / UMREZ

Check families
 1. UoM code validity              ERROR
 2. Impossible dimension pairs     ERROR
 3. Cross-dim industry warning     WARNING
 4. Known conversion magnitude     ERROR
 5. Same-dim implausible ratio     WARNING
 6. Trivial 1:1 same-dim           WARNING
 7. Material-type context          WARNING/INFO
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import NamedTuple
from .models import Severity
from .uom_data import classify_sap_uom, is_valid_sap_uom

IMPOSSIBLE_PAIRS: dict[frozenset, str] = {
    frozenset({"mass",   "length"}): "Mass and length are incompatible dimensions.",
    frozenset({"mass",   "area"}):   "Mass and area are incompatible dimensions.",
    frozenset({"mass",   "time"}):   "Mass and time are incompatible dimensions.",
    frozenset({"volume", "length"}): "Volume and length are incompatible dimensions.",
    frozenset({"volume", "area"}):   "Volume and area are incompatible dimensions.",
    frozenset({"volume", "time"}):   "Volume and time are incompatible dimensions.",
    frozenset({"length", "area"}):   "Length and area are incompatible dimensions.",
    frozenset({"length", "time"}):   "Length and time are incompatible dimensions.",
    frozenset({"area",   "time"}):   "Area and time are incompatible dimensions.",
}
CROSS_DIM_WARNINGS: dict[frozenset, str] = {
    frozenset({"mass", "volume"}):
        "Mass<->Volume implies a density factor. Valid for liquids/bulk chemicals -- verify ratio matches material density.",
    frozenset({"mass", "count"}):
        "Mass<->Count (e.g. 1 carton = 5 KG catch-weight). Valid for variable-weight items.",
    frozenset({"volume", "count"}):
        "Volume<->Count (e.g. 1 BT = 500 ML). Valid for pre-packaged liquids.",
    frozenset({"length", "count"}):
        "Length<->Count (e.g. 1 ROL = 100 M). Valid for reels/spools/cable.",
    frozenset({"area", "count"}):
        "Area<->Count (e.g. 1 PC = 2 M2). Valid for panels/tiles/fabric.",
    frozenset({"mass", "packaging"}):
        "Mass<->Packaging. Verify the mass per packaging unit.",
    frozenset({"volume", "packaging"}):
        "Volume<->Packaging. Verify the volume per packaging unit.",
    frozenset({"length", "packaging"}):
        "Length<->Packaging (e.g. 1 ROL = 100 M). Verify the length per packaging unit.",
}
ACCEPTABLE_CROSS_DIM: set[frozenset] = {
    frozenset({"packaging", "count"}),
    frozenset({"count",     "count"}),
    frozenset({"packaging", "packaging"}),
}


class ConvSpec(NamedTuple):
    expected: float
    tol_pct:  float
    label:    str


# _KNOWN: (base_lower, alt_lower) -> ConvSpec(alt_per_base, tolerance_pct, description)
# Entries cover both ISO codes (primary) and SAP internal codes (fallback).
_KNOWN: dict[tuple[str, str], ConvSpec] = {
    # ------------------------------------------------------------------ MASS
    # ISO codes
    ("kgm", "grm"):  ConvSpec(1_000,       0.005, "1 KGM = 1,000 GRM"),
    ("kgm", "mgm"):  ConvSpec(1_000_000,   0.005, "1 KGM = 1,000,000 MGM"),
    ("kgm", "tne"):  ConvSpec(0.001,       0.005, "1 KGM = 0.001 TNE"),
    ("kgm", "lbr"):  ConvSpec(2.20462,     0.02,  "1 KGM = 2.205 LBR"),
    ("kgm", "onz"):  ConvSpec(35.2740,     0.02,  "1 KGM = 35.274 ONZ"),
    ("grm", "kgm"):  ConvSpec(0.001,       0.005, "1 GRM = 0.001 KGM"),
    ("grm", "mgm"):  ConvSpec(1_000,       0.005, "1 GRM = 1,000 MGM"),
    ("lbr", "onz"):  ConvSpec(16.0,        0.005, "1 LBR = 16 ONZ"),
    ("lbr", "kgm"):  ConvSpec(0.453592,    0.02,  "1 LBR = 0.4536 KGM"),
    ("tne", "kgm"):  ConvSpec(1_000,       0.005, "1 TNE = 1,000 KGM"),
    ("tne", "grm"):  ConvSpec(1_000_000,   0.005, "1 TNE = 1,000,000 GRM"),
    ("stn", "lbr"):  ConvSpec(2_000,       0.005, "1 STN (US ton) = 2,000 LBR"),
    ("stn", "kgm"):  ConvSpec(907.185,     0.02,  "1 STN = 907.185 KGM"),
    # SAP internal codes (fallback)
    ("kg",  "g"):    ConvSpec(1_000,       0.005, "1 KG = 1,000 G"),
    ("kg",  "mg"):   ConvSpec(1_000_000,   0.005, "1 KG = 1,000,000 MG"),
    ("kg",  "to"):   ConvSpec(0.001,       0.005, "1 KG = 0.001 TO"),
    ("kg",  "lb"):   ConvSpec(2.20462,     0.02,  "1 KG = 2.205 LB"),
    ("kg",  "oz"):   ConvSpec(35.2740,     0.02,  "1 KG = 35.274 OZ"),
    ("kg",  "kt"):   ConvSpec(1e-6,        0.005, "1 KG = 0.000001 KT"),
    ("g",   "kg"):   ConvSpec(0.001,       0.005, "1 G = 0.001 KG"),
    ("g",   "mg"):   ConvSpec(1_000,       0.005, "1 G = 1,000 MG"),
    ("lb",  "oz"):   ConvSpec(16.0,        0.005, "1 LB = 16 OZ"),
    ("lb",  "kg"):   ConvSpec(0.453592,    0.02,  "1 LB = 0.4536 KG"),
    ("to",  "kg"):   ConvSpec(1_000,       0.005, "1 TO = 1,000 KG"),
    ("to",  "g"):    ConvSpec(1_000_000,   0.005, "1 TO = 1,000,000 G"),
    ("ton", "lb"):   ConvSpec(2_000,       0.005, "1 TON (US) = 2,000 LB"),
    ("ton", "kg"):   ConvSpec(907.185,     0.02,  "1 TON (US) = 907.185 KG"),
    # ---------------------------------------------------------------- VOLUME
    # ISO codes
    ("ltr", "mlt"):  ConvSpec(1_000,       0.005, "1 LTR = 1,000 MLT"),
    ("ltr", "clt"):  ConvSpec(100,         0.005, "1 LTR = 100 CLT"),
    ("ltr", "hlt"):  ConvSpec(0.01,        0.005, "1 LTR = 0.01 HLT"),
    ("ltr", "mtq"):  ConvSpec(0.001,       0.005, "1 LTR = 0.001 MTQ"),
    ("ltr", "gll"):  ConvSpec(0.264172,    0.02,  "1 LTR = 0.264 GLL (US)"),
    ("ltr", "oza"):  ConvSpec(33.8140,     0.02,  "1 LTR = 33.814 OZA"),
    ("ltr", "cmq"):  ConvSpec(1_000,       0.005, "1 LTR = 1,000 CMQ"),
    ("ltr", "dmq"):  ConvSpec(1.0,         0.005, "1 LTR = 1 DMQ"),
    ("mlt", "ltr"):  ConvSpec(0.001,       0.005, "1 MLT = 0.001 LTR"),
    ("mlt", "cmq"):  ConvSpec(1.0,         0.005, "1 MLT = 1 CMQ"),
    ("mtq", "ltr"):  ConvSpec(1_000,       0.005, "1 MTQ = 1,000 LTR"),
    ("mtq", "hlt"):  ConvSpec(10,          0.005, "1 MTQ = 10 HLT"),
    ("mtq", "mlt"):  ConvSpec(1_000_000,   0.005, "1 MTQ = 1,000,000 MLT"),
    ("hlt", "ltr"):  ConvSpec(100,         0.005, "1 HLT = 100 LTR"),
    ("gll", "ltr"):  ConvSpec(3.78541,     0.02,  "1 GLL = 3.785 LTR (US)"),
    ("gll", "qt"):   ConvSpec(4.0,         0.005, "1 GLL = 4 QT"),
    ("qt",  "pt"):   ConvSpec(2.0,         0.005, "1 QT = 2 PT"),
    # SAP internal codes (fallback)
    ("l",   "ml"):   ConvSpec(1_000,       0.005, "1 L = 1,000 ML"),
    ("l",   "cl"):   ConvSpec(100,         0.005, "1 L = 100 CL"),
    ("l",   "hl"):   ConvSpec(0.01,        0.005, "1 L = 0.01 HL"),
    ("l",   "m3"):   ConvSpec(0.001,       0.005, "1 L = 0.001 M3"),
    ("l",   "gal"):  ConvSpec(0.264172,    0.02,  "1 L = 0.264 GAL (US)"),
    ("l",   "foz"):  ConvSpec(33.8140,     0.02,  "1 L = 33.814 FOZ"),
    ("l",   "ccm"):  ConvSpec(1_000,       0.005, "1 L = 1,000 CCM"),
    ("l",   "cd3"):  ConvSpec(1.0,         0.005, "1 L = 1 CD3"),
    ("ml",  "l"):    ConvSpec(0.001,       0.005, "1 ML = 0.001 L"),
    ("ml",  "ccm"):  ConvSpec(1.0,         0.005, "1 ML = 1 CCM"),
    ("m3",  "l"):    ConvSpec(1_000,       0.005, "1 M3 = 1,000 L"),
    ("m3",  "hl"):   ConvSpec(10,          0.005, "1 M3 = 10 HL"),
    ("m3",  "ml"):   ConvSpec(1_000_000,   0.005, "1 M3 = 1,000,000 ML"),
    ("hl",  "l"):    ConvSpec(100,         0.005, "1 HL = 100 L"),
    ("gal", "l"):    ConvSpec(3.78541,     0.02,  "1 GAL = 3.785 L (US)"),
    ("gal", "qt"):   ConvSpec(4.0,         0.005, "1 GAL = 4 QT"),
    ("qt",  "pt"):   ConvSpec(2.0,         0.005, "1 QT = 2 PT"),
    ("bbl", "l"):    ConvSpec(158.987,     0.02,  "1 BBL = 158.987 L"),
    ("bbl", "gal"):  ConvSpec(42.0,        0.005, "1 BBL = 42 GAL"),
    # ---------------------------------------------------------------- LENGTH
    # ISO codes
    ("mtr", "cmt"):  ConvSpec(100,         0.005, "1 MTR = 100 CMT"),
    ("mtr", "mmt"):  ConvSpec(1_000,       0.005, "1 MTR = 1,000 MMT"),
    ("mtr", "kmt"):  ConvSpec(0.001,       0.005, "1 MTR = 0.001 KMT"),
    ("mtr", "dmt"):  ConvSpec(10,          0.005, "1 MTR = 10 DMT"),
    ("mtr", "fot"):  ConvSpec(3.28084,     0.02,  "1 MTR = 3.281 FOT"),
    ("mtr", "yrd"):  ConvSpec(1.09361,     0.02,  "1 MTR = 1.094 YRD"),
    ("cmt", "mmt"):  ConvSpec(10,          0.005, "1 CMT = 10 MMT"),
    ("cmt", "mtr"):  ConvSpec(0.01,        0.005, "1 CMT = 0.01 MTR"),
    ("kmt", "mtr"):  ConvSpec(1_000,       0.005, "1 KMT = 1,000 MTR"),
    ("fot", "mtr"):  ConvSpec(0.3048,      0.02,  "1 FOT = 0.3048 MTR"),
    ("yrd", "mtr"):  ConvSpec(0.9144,      0.02,  "1 YRD = 0.9144 MTR"),
    ("yrd", "fot"):  ConvSpec(3.0,         0.005, "1 YRD = 3 FOT"),
    # SAP internal codes (fallback)
    ("m",   "cm"):   ConvSpec(100,         0.005, "1 M = 100 CM"),
    ("m",   "mm"):   ConvSpec(1_000,       0.005, "1 M = 1,000 MM"),
    ("m",   "km"):   ConvSpec(0.001,       0.005, "1 M = 0.001 KM"),
    ("m",   "dm"):   ConvSpec(10,          0.005, "1 M = 10 DM"),
    ("m",   "ft"):   ConvSpec(3.28084,     0.02,  "1 M = 3.281 FT"),
    ("m",   "yd"):   ConvSpec(1.09361,     0.02,  "1 M = 1.094 YD"),
    ("cm",  "mm"):   ConvSpec(10,          0.005, "1 CM = 10 MM"),
    ("cm",  "m"):    ConvSpec(0.01,        0.005, "1 CM = 0.01 M"),
    ("km",  "m"):    ConvSpec(1_000,       0.005, "1 KM = 1,000 M"),
    ("ft",  "m"):    ConvSpec(0.3048,      0.02,  "1 FT = 0.3048 M"),
    ("yd",  "m"):    ConvSpec(0.9144,      0.02,  "1 YD = 0.9144 M"),
    ("yd",  "ft"):   ConvSpec(3.0,         0.005, "1 YD = 3 FT"),
    # ------------------------------------------------------------------ AREA
    # ISO codes
    ("mtk", "cmk"):  ConvSpec(10_000,      0.005, "1 MTK = 10,000 CMK"),
    ("mtk", "mmk"):  ConvSpec(1_000_000,   0.005, "1 MTK = 1,000,000 MMK"),
    ("mtk", "ftk"):  ConvSpec(10.7639,     0.02,  "1 MTK = 10.764 FTK"),
    ("har", "mtk"):  ConvSpec(10_000,      0.005, "1 HAR = 10,000 MTK"),
    ("kmk", "mtk"):  ConvSpec(1_000_000,   0.005, "1 KMK = 1,000,000 MTK"),
    ("acr", "mtk"):  ConvSpec(4_046.86,    0.02,  "1 ACR = 4,046.86 MTK"),
    # SAP internal codes (fallback)
    ("m2",  "cm2"):  ConvSpec(10_000,      0.005, "1 M2 = 10,000 CM2"),
    ("m2",  "mm2"):  ConvSpec(1_000_000,   0.005, "1 M2 = 1,000,000 MM2"),
    ("m2",  "ft2"):  ConvSpec(10.7639,     0.02,  "1 M2 = 10.764 FT2"),
    ("ha",  "m2"):   ConvSpec(10_000,      0.005, "1 HA = 10,000 M2"),
    ("km2", "m2"):   ConvSpec(1_000_000,   0.005, "1 KM2 = 1,000,000 M2"),
    # ------------------------------------------------------------------ TIME
    # ISO codes
    ("min", "sec"):  ConvSpec(60,          0.005, "1 MIN = 60 SEC"),
    ("hur", "min"):  ConvSpec(60,          0.005, "1 HUR = 60 MIN"),
    ("hur", "sec"):  ConvSpec(3_600,       0.005, "1 HUR = 3,600 SEC"),
    ("day", "hur"):  ConvSpec(24,          0.005, "1 DAY = 24 HUR"),
    ("wee", "day"):  ConvSpec(7,           0.005, "1 WEE = 7 DAY"),
    ("mon", "day"):  ConvSpec(30.4375,     0.05,  "1 MON ~= 30.44 DAY"),
    ("ann", "day"):  ConvSpec(365.25,      0.01,  "1 ANN = 365.25 DAY"),
    ("ann", "mon"):  ConvSpec(12,          0.005, "1 ANN = 12 MON"),
    # SAP internal codes (fallback)
    ("min", "s"):    ConvSpec(60,          0.005, "1 MIN = 60 S"),
    ("h",   "min"):  ConvSpec(60,          0.005, "1 H = 60 MIN"),
    ("hr",  "min"):  ConvSpec(60,          0.005, "1 HR = 60 MIN"),
    ("h",   "s"):    ConvSpec(3_600,       0.005, "1 H = 3,600 S"),
    ("hr",  "s"):    ConvSpec(3_600,       0.005, "1 HR = 3,600 S"),
    ("d",   "h"):    ConvSpec(24,          0.005, "1 D = 24 H"),
    ("d",   "hr"):   ConvSpec(24,          0.005, "1 D = 24 HR"),
    ("day", "h"):    ConvSpec(24,          0.005, "1 DAY = 24 H"),
    ("day", "hr"):   ConvSpec(24,          0.005, "1 DAY = 24 HR"),
    ("wk",  "d"):    ConvSpec(7,           0.005, "1 WK = 7 D"),
    ("wk",  "day"):  ConvSpec(7,           0.005, "1 WK = 7 DAY"),
    ("mon", "d"):    ConvSpec(30.4375,     0.05,  "1 MON ~= 30.44 D"),
    ("025", "d"):    ConvSpec(30.4375,     0.05,  "1 MON (025) ~= 30.44 D"),
    ("yr",  "d"):    ConvSpec(365.25,      0.01,  "1 YR = 365.25 D"),
    ("024", "d"):    ConvSpec(365.25,      0.01,  "1 YR (024) = 365.25 D"),
    # -------------------------------------------------------- COUNT/PACKAGING
    # ISO codes
    ("ea",  "dzn"):  ConvSpec(1/12,        0.005, "12 EA = 1 DZN"),
    ("dzn", "ea"):   ConvSpec(12.0,        0.005, "1 DZN = 12 EA"),
    ("dzn", "gro"):  ConvSpec(1/12,        0.005, "12 DZN = 1 GRO"),
    ("gro", "dzn"):  ConvSpec(12.0,        0.005, "1 GRO = 12 DZN"),
    # SAP internal codes (fallback)
    ("pc",  "dz"):   ConvSpec(1/12,        0.005, "12 PC = 1 DZ"),
    ("dz",  "pc"):   ConvSpec(12.0,        0.005, "1 DZ = 12 PC"),
    ("pc",  "gro"):  ConvSpec(1/144,       0.005, "144 PC = 1 GRO"),
    ("ea",  "dz"):   ConvSpec(1/12,        0.005, "12 EA = 1 DZ"),
    ("dz",  "ea"):   ConvSpec(12.0,        0.005, "1 DZ = 12 EA"),
    ("ea",  "ts"):   ConvSpec(0.001,       0.005, "1 EA = 0.001 TS (thousands)"),
    ("pc",  "ts"):   ConvSpec(0.001,       0.005, "1 PC = 0.001 TS (thousands)"),
}

_SAME_DIM_BOUNDS: dict[str, tuple[float, float]] = {
    "mass": (1e-9, 1e9), "volume": (1e-9, 1e9), "length": (1e-9, 1e9),
    "area": (1e-9, 1e9), "count":  (1e-6, 1e6),  "time":  (1e-6, 1e6),
    "packaging": (1e-4, 1e5),
}
_CROSS_DIM_BOUNDS = (1e-9, 1e9)
_MTART_FORBIDDEN = {"DIEN": {"mass", "volume", "area"}}
_MTART_PREFERRED = {"DIEN": {"time", "count"}}


@dataclass
class ConversionIssue:
    severity: Severity
    rule_id:  str
    message:  str


def _pct(a: float, e: float) -> float:
    return abs(a - e) / abs(e) if e else float("inf")


def check_conversion(
    base_uom: str,
    alt_uom:  str,
    denom:    float | None,
    numer:    float | None,
    mtart:    str = "",
    product:  str = "",
) -> list[ConversionIssue]:
    issues: list[ConversionIssue] = []
    bn = base_uom.strip().lower() if base_uom else ""
    an = alt_uom.strip().lower()  if alt_uom  else ""

    # 1. UoM code validity (ISO or SAP)
    if alt_uom and not is_valid_sap_uom(alt_uom):
        issues.append(ConversionIssue(Severity.ERROR, "X_ALT_INVALID_UOM_CODE",
            f"Alt UoM '{alt_uom}' is not a recognised ISO or SAP UoM code. "
            "Check against SAP_UOM_All.xlsx."))

    bd = classify_sap_uom(base_uom)
    ad = classify_sap_uom(alt_uom)

    # 2 & 3. Dimension compatibility
    if bd and ad and bd != ad:
        pair = frozenset({bd, ad})
        if pair in IMPOSSIBLE_PAIRS:
            issues.append(ConversionIssue(Severity.ERROR, "X_ALT_IMPOSSIBLE_DIM",
                f"Physically impossible: {base_uom} ({bd}) -> {alt_uom} ({ad}). "
                f"{IMPOSSIBLE_PAIRS[pair]}"))
            return issues
        if pair not in ACCEPTABLE_CROSS_DIM and pair in CROSS_DIM_WARNINGS:
            issues.append(ConversionIssue(Severity.WARNING, "X_ALT_CROSS_DIM",
                f"Cross-dimension: {base_uom} ({bd}) -> {alt_uom} ({ad}). "
                f"{CROSS_DIM_WARNINGS[pair]}"))

    # Ratio checks require valid factors
    if denom is None or numer is None or numer <= 0 or denom <= 0:
        return issues
    apb = denom / numer

    # 4. Known conversion magnitude
    spec = _KNOWN.get((bn, an))
    if spec:
        d = _pct(apb, spec.expected)
        if d > spec.tol_pct:
            f = apb / spec.expected
            hint = f"~{f:.1f}x too large" if f > 1 else f"~{1/f:.1f}x too small"
            issues.append(ConversionIssue(Severity.ERROR, "X_ALT_MAGNITUDE_ERROR",
                f"Magnitude error: {base_uom} -> {alt_uom} ratio is {apb:.6g}, "
                f"expected {spec.expected:.6g} ({spec.label}). {hint.capitalize()}."))
    else:
        # 5. Same-dim implausible magnitude
        if bd and ad and bd == ad:
            lo, hi = _SAME_DIM_BOUNDS.get(bd, (1e-12, 1e12))
            if not (lo <= apb <= hi):
                issues.append(ConversionIssue(Severity.WARNING, "X_ALT_IMPLAUSIBLE_RATIO",
                    f"Implausible {bd} conversion: {base_uom} -> {alt_uom} ratio "
                    f"{apb:.4g} outside plausible range [{lo:.0e},{hi:.0e}]."))
        elif bd and ad and bd != ad:
            lo, hi = _CROSS_DIM_BOUNDS
            if not (lo <= apb <= hi):
                issues.append(ConversionIssue(Severity.WARNING, "X_ALT_IMPLAUSIBLE_CROSS_RATIO",
                    f"Cross-dim ratio {base_uom} -> {alt_uom} = {apb:.4g} "
                    "outside any plausible range. Likely a data-entry error."))

    # 6. Trivial 1:1 between different same-dim units
    if bd and ad and bd == ad and bn != an and abs(apb - 1.0) < 0.001:
        issues.append(ConversionIssue(Severity.WARNING, "X_ALT_RATIO_ONE",
            f"Ratio {base_uom} -> {alt_uom} is 1:1 but they are different {bd} units. "
            "Conversion factor likely missing."))

    # 7. Material-type context
    mt = (mtart or "").upper()
    if mt in _MTART_FORBIDDEN and ad in _MTART_FORBIDDEN[mt]:
        issues.append(ConversionIssue(Severity.WARNING, "X_ALT_MTART_DIM",
            f"Material type '{mt}' should not normally have a {ad}-based "
            f"alt UoM (found: {alt_uom})."))
    elif mt in _MTART_PREFERRED and ad:
        pref = _MTART_PREFERRED[mt]
        if ad not in pref | {"count", "packaging"}:
            issues.append(ConversionIssue(Severity.INFO, "X_ALT_MTART_PREFERRED",
                f"Material type '{mt}' usually uses {pref} units; "
                f"alt UoM '{alt_uom}' ({ad}) may be unusual."))
    return issues
