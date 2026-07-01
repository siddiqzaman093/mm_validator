"""
Base UoM compatibility check.

All UoM classification is now driven by SAP codes from SAP_UOM_All.xlsx
via uom_data.py.  ISO codes are no longer used for classification.

Strategy:
  1. Look up SAP UoM code -> dimension category (via uom_data).
  2. Classify product description into a "nature" via keyword rules.
  3. High-confidence match/mismatch -> deterministic flag.
  4. Ambiguous -> candidate for AI batch.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .uom_data import classify_sap_uom, describe_sap_uom, is_valid_sap_uom


# ---------------------------------------------------------------------------
# Nature classification: description keywords -> expected UoM dimension(s)
# ---------------------------------------------------------------------------
@dataclass
class NatureRule:
    pattern: re.Pattern
    expected: set[str]
    label: str
    confidence: str   # "high" or "low"


def _r(pat: str) -> re.Pattern:
    return re.compile(rf"\b({pat})\b", re.I)


_RULES: list[NatureRule] = [
    # Liquids -> volume
    NatureRule(_r(r"oil|petrol|diesel|gasoline|kerosene|fuel|lubricant"),
               {"volume"}, "liquid (fuel/oil)", "high"),
    NatureRule(_r(r"milk|juice|water|beverage|drink|soda|wine|beer|liquor|"
                  r"syrup|sauce|ink|paint|solvent|reagent|liquid|fluid|"
                  r"coolant|shampoo|lotion|gel|cream|perfume"),
               {"volume"}, "liquid", "high"),
    # Bulk solids -> mass
    NatureRule(_r(r"flour|sugar|salt|rice|grain|cereal|powder|cement|sand|"
                  r"gravel|coal|ore|fertilizer|metal\s*scrap|granule|pellet"),
               {"mass"}, "bulk solid", "high"),
    NatureRule(_r(r"meat|chicken|fish|beef|pork|cheese|butter|fruit|vegetable|produce"),
               {"mass", "count"}, "food (mass or count)", "high"),
    # Linear materials -> length
    NatureRule(_r(r"cable|wire|rope|string|thread|yarn|tape|hose|pipe|tube|"
                  r"fabric|cloth|textile|chain"),
               {"length"}, "linear material", "high"),
    # Sheet / panel -> area or count
    NatureRule(_r(r"sheet|panel|board|plate|carpet|rug|tile|laminate|"
                  r"wallpaper|film"),
               {"area", "count"}, "sheet/area material", "high"),
    # Discrete hardware -> count
    NatureRule(_r(r"laptop|computer|phone|valve|pump|motor|engine|bearing|"
                  r"screw|bolt|nut|nail|gasket|filter|sensor|chip|battery|"
                  r"bulb|lamp|switch|connector|fuse|relay|kit|set|assembly|"
                  r"module|tool|machine|device|component|widget|gadget"),
               {"count"}, "discrete item", "high"),
    NatureRule(_r(r"furniture|chair|table|desk|bed|sofa|cabinet|shelf|drawer"),
               {"count"}, "furniture", "high"),
    NatureRule(_r(r"book|magazine|booklet|brochure|pamphlet|manual|document"),
               {"count"}, "printed item", "high"),
    # Services -> time or count
    NatureRule(_r(r"service|consultation|labor|labour|maintenance\s*service|"
                  r"warranty|subscription|license"),
               {"time", "count"}, "service", "high"),
    # Packaging items (description is about packaging itself)
    NatureRule(_r(r"\bbox\b|\bcarton\b|\bcase\b|\bpallet\b|\bcrate\b|\bdrum\b|"
                  r"\bbag\b|\bsack\b|\bbottle\b|\bcan\b|\btin\b|\btube\b|\btray\b"),
               {"count", "packaging"}, "packaging", "low"),
]


def classify_uom_dimension(code: str) -> str | None:
    """
    Return dimension category for a SAP UoM code.
    Returns None if the code is not recognised.
    Uses SAP_UOM_All.xlsx data exclusively.
    """
    return classify_sap_uom(code)


def classify_description(description: str) -> tuple[str | None, set[str], str]:
    """Return (label, expected_dims, confidence)."""
    if not description:
        return None, set(), "none"
    for rule in _RULES:
        if rule.pattern.search(description):
            return rule.label, rule.expected, rule.confidence
    return None, set(), "none"


# ---------------------------------------------------------------------------
# Explicit dimensional quantity extraction from description text
# ---------------------------------------------------------------------------
_TEXT_DIM_PATTERNS: list[tuple[re.Pattern, str]] = [
    # Mass: e.g. "500g", "2.5 KG", "100 grams", "50mg"
    (re.compile(
        r"\b\d+[\.,]?\d*\s*(?:kgm|kg|kilograms?|grm|grams?|mg|milligrams?|t\b|tonne|ton|lb|lbs|pounds?)\b",
        re.I), "mass"),
    # Volume: e.g. "500 ML", "1.5L", "250ml", "1 ltr"
    (re.compile(
        r"\b\d+[\.,]?\d*\s*(?:mlt|ml|milliliters?|millilitres?|ltr|liters?|litres?|l\b|cl|centiliters?|fl\.?\s*oz|gallons?|pints?)\b",
        re.I), "volume"),
    # Length: e.g. "10m", "2.5cm", "100mm", "5 mtr"
    (re.compile(
        r"\b\d+[\.,]?\d*\s*(?:kmt|km|kilometers?|kilometres?|mtr|meters?|metres?|cmt|cm|centimeters?|centimetres?|mmt|mm|millimeters?|millimetres?|in\b|inch|inches|ft\b|feet|foot|yd|yards?)\b",
        re.I), "length"),
    # Area: e.g. "2 sqm", "50 m2", "10 sq ft"
    (re.compile(
        r"\b\d+[\.,]?\d*\s*(?:sqm|m2|sq\.?\s*m(?:eters?|etres?)?|cm2|sq\.?\s*cm|ft2|sq\.?\s*ft)\b",
        re.I), "area"),
    # Time: e.g. "24 hours", "30 min", "1 day"
    (re.compile(
        r"\b\d+[\.,]?\d*\s*(?:hur|hours?|min(?:utes?)?|sec(?:onds?)?|days?|weeks?|months?|years?)\b",
        re.I), "time"),
    # Count/pack: e.g. "100 pcs", "50 pieces", "12 pack"
    (re.compile(
        r"\b\d+[\.,]?\d*\s*(?:pce|pcs|pieces?|units?|each|ea)\b"
        r"|\b(?:pack|pcs|pce|pieces?|units?|each|ea)\s*of\s*\d+",
        re.I), "count"),
]


def extract_quantity_dim(description: str) -> str | None:
    """
    Detect explicit dimensional quantity pattern in description text.
    E.g. '500 ML Orange Juice' -> 'volume', '2.5 KG Sugar' -> 'mass'.
    Returns dimension string or None if no match found.
    Checked before nature-keyword rules — explicit quantities are high-confidence.
    """
    if not description:
        return None
    for pattern, dim in _TEXT_DIM_PATTERNS:
        if pattern.search(description):
            return dim
    return None


@dataclass
class UoMCheckResult:
    sheet: str
    row: int
    product: str
    description: str
    uom: str
    uom_dim: str | None
    nature_label: str | None
    expected_dims: set[str]
    confidence: str
    verdict: str   # "ok" | "mismatch" | "invalid_sap" | "unknown_nature" | "needs_ai"

    def as_message(self) -> str:
        dim_label = describe_sap_uom(self.uom) if self.uom else self.uom
        if self.verdict == "mismatch":
            return (
                f"Base UoM '{self.uom}' ({dim_label}) does not match product nature "
                f"'{self.nature_label}' (expected: {', '.join(sorted(self.expected_dims))})."
            )
        if self.verdict == "invalid_sap":
            return (
                f"Base UoM '{self.uom}' is not a recognised SAP UoM code. "
                "Check against the SAP UoM table (T006)."
            )
        return ""


def check_basic_uom(basic_data, max_rows_for_ai: int = 50):
    """
    Returns (deterministic_results, ai_candidates).
    deterministic_results: list[UoMCheckResult] with verdict mismatch/invalid_sap
    ai_candidates:         list[UoMCheckResult] needing AI confirmation
    """
    deterministic: list[UoMCheckResult] = []
    ai_candidates: list[UoMCheckResult] = []

    if basic_data is None or not basic_data.rows:
        return deterministic, ai_candidates

    for row in basic_data.rows:
        cells = row["_cells"]
        product  = str(cells.get("PRODUCT", {}).get("value", "")).strip()
        descr    = str(cells.get("MAKTX",   {}).get("value", "")).strip()
        uom      = str(cells.get("MEINS",   {}).get("value", "")).strip()
        if not descr or not uom:
            continue

        uom_dim = classify_sap_uom(uom)
        label, expected, conf = classify_description(descr)
        text_dim = extract_quantity_dim(descr)

        result = UoMCheckResult(
            sheet=basic_data.sheet, row=row["_row"],
            product=product, description=descr, uom=uom,
            uom_dim=uom_dim, nature_label=label,
            expected_dims=expected, confidence=conf,
            verdict="ok",
        )

        # SAP code not in master list
        if not is_valid_sap_uom(uom):
            result.verdict = "invalid_sap"
            deterministic.append(result)
            continue

        # Explicit dimensional quantity in description text
        if text_dim is not None:
            if uom_dim != text_dim:
                # Explicit quantity clearly contradicts the UoM — definite mismatch
                result.verdict = "mismatch"
                result.nature_label = f"explicit quantity ({text_dim})"
                result.expected_dims = {text_dim}
                deterministic.append(result)
                continue
            # text_dim matches uom_dim — good signal, but check nature keyword
            if expected and uom_dim not in expected:
                # Nature keyword says different dimension; explicit quantity agrees with UoM.
                # Conflicting signals — escalate to AI for resolution.
                result.verdict = "needs_ai"
                result.nature_label = (
                    f"{label}, but explicit {text_dim} quantity in description"
                    if label else f"explicit quantity ({text_dim})"
                )
                ai_candidates.append(result)
            # else: text_dim and nature both agree with uom_dim → ok
            continue

        if not expected:
            result.verdict = "needs_ai"
            ai_candidates.append(result)
            continue

        if conf == "high":
            if uom_dim not in expected:
                result.verdict = "mismatch"
                deterministic.append(result)
            # else: ok — no finding
            continue

        # low-confidence rule: escalate to AI if dim looks wrong
        if uom_dim not in expected:
            result.verdict = "needs_ai"
            ai_candidates.append(result)

    if len(ai_candidates) > max_rows_for_ai:
        ai_candidates = ai_candidates[:max_rows_for_ai]
    return deterministic, ai_candidates
