"""
AI warning flags with deterministic prefilter to minimize LLM tokens.

Flags:
  A. Description vs Material Type mismatch
  B. Missing Shelf Life for food/perishables
  C. Pricing anomaly vs material type
  D. UoM vs Product Nature  (handled in uom.py — AI confirmation here)

Pipeline:
  1. Pre-filter candidates with regex/lookup tables.
  2. Hand only ambiguous cases to ONE batched AI call per flag type.
  3. Cache system prompt for repeated requests (Anthropic prompt caching).
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any

from .models import Finding, Severity, SheetData
from . import uom as uom_mod


# -----------------------------------------------------------------------------
# Material type expectations (high-confidence rules; ambiguous -> AI)
# -----------------------------------------------------------------------------
MTART_EXPECTATIONS = {
    "ROH": {"label": "Raw Material",
            "expected_terms": ["raw", "ingredient", "material", "ore", "mineral", "resin", "compound"],
            "forbidden_terms": ["finished", "assembly", "complete", "kit"],
            "expected_price_range": (0.01, 5_000.0),
            "perishable_ok": True},
    "HALB": {"label": "Semi-Finished",
             "expected_terms": ["component", "subassembly", "semi", "intermediate"],
             "forbidden_terms": ["raw "],
             "expected_price_range": (0.1, 50_000.0),
             "perishable_ok": True},
    "FERT": {"label": "Finished Product",
             "expected_terms": [],
             "forbidden_terms": ["raw material", "ore"],
             "expected_price_range": (0.5, 500_000.0),
             "perishable_ok": True},
    "HAWA": {"label": "Trading Goods",
             "expected_terms": [],
             "forbidden_terms": ["raw material"],
             "expected_price_range": (0.1, 100_000.0),
             "perishable_ok": True},
    "VERP": {"label": "Packaging",
             "expected_terms": ["box", "carton", "pallet", "bag", "drum", "bottle", "can",
                                "wrap", "package", "label", "crate", "tube", "sleeve", "tray"],
             "forbidden_terms": [],
             "expected_price_range": (0.01, 1_000.0),
             "perishable_ok": False},
    "DIEN": {"label": "Service",
             "expected_terms": ["service", "consultation", "maintenance", "license",
                                "subscription", "warranty", "labor", "labour", "fee", "support"],
             "forbidden_terms": [],
             "expected_price_range": (0.1, 1_000_000.0),
             "perishable_ok": False},
    "UNBW": {"label": "Non-Valuated",
             "expected_terms": [],
             "forbidden_terms": [],
             "expected_price_range": (0.0, 0.0),
             "perishable_ok": False},
    "NLAG": {"label": "Non-Stock",
             "expected_terms": [],
             "forbidden_terms": [],
             "expected_price_range": (0.0, 100_000.0),
             "perishable_ok": False},
    "LEIH": {"label": "Returnable Packaging",
             "expected_terms": ["pallet", "container", "crate", "drum", "case"],
             "forbidden_terms": [],
             "expected_price_range": (1.0, 5_000.0),
             "perishable_ok": False},
}


PERISHABLE_PATTERNS = re.compile(
    r"\b(milk|yogurt|yoghurt|cheese|butter|cream|dairy|egg|eggs|"
    r"meat|chicken|beef|pork|lamb|fish|seafood|shrimp|prawn|"
    r"fruit|apple|banana|berry|tomato|vegetable|salad|lettuce|onion|carrot|"
    r"juice|smoothie|"
    r"bread|pastry|cake|biscuit|cookie|sandwich|"
    r"vaccine|insulin|antibiotic|serum|reagent|medicine|drug|pharmaceutic|"
    r"yeast|enzyme|culture|probiotic|"
    r"flower|plant|seedling|"
    r"frozen|fresh|chilled|refrigerated|perishable)\b",
    re.I,
)


def _val(row: dict, sap: str) -> Any:
    cell = row.get("_cells", {}).get(sap)
    if cell is None:
        return None
    val = cell.get("value")
    if isinstance(val, str):
        s = val.strip()
        return s or None
    if val == "":
        return None
    return val


def _str(row: dict, sap: str) -> str:
    v = _val(row, sap)
    return str(v).strip() if v is not None else ""


def _f(row: dict, sap: str) -> float | None:
    v = _val(row, sap)
    if v is None:
        return None
    try:
        return float(str(v).replace(",", ""))
    except ValueError:
        return None


# -----------------------------------------------------------------------------
# A. Description vs Material Type — prefilter
# -----------------------------------------------------------------------------
@dataclass
class AICandidate:
    flag: str
    sheet: str
    row: int
    payload: dict


def prefilter_desc_mtart(basic: SheetData | None) -> tuple[list[Finding], list[AICandidate]]:
    findings: list[Finding] = []
    candidates: list[AICandidate] = []
    if not basic or not basic.rows:
        return findings, candidates

    for row in basic.rows:
        product = _str(row, "PRODUCT")
        descr = _str(row, "MAKTX")
        mtart = _str(row, "MTART").upper()
        if not descr or not mtart:
            continue
        spec = MTART_EXPECTATIONS.get(mtart)
        if spec is None:
            # unknown material type — let AI decide
            candidates.append(AICandidate("desc_mtart", basic.sheet, row["_row"], {
                "product": product,
                "description": descr,
                "material_type": mtart,
            }))
            continue

        d_lower = descr.lower()
        # forbidden term -> deterministic warning
        for bad in spec["forbidden_terms"]:
            if bad in d_lower:
                findings.append(Finding(
                    severity=Severity.WARNING,
                    category="AI/DescVsType",
                    sheet=basic.sheet, row=row["_row"],
                    field="Description vs Product Type",
                    sap_field="MAKTX/MTART",
                    message=(f"Description contains '{bad}' which conflicts with "
                             f"Material Type {mtart} ({spec['label']})."),
                    material=product,
                    value=f"{descr!r} | {mtart}",
                    rule_id="AI_DESC_MTART_FORBIDDEN",
                ))
                break
        else:
            # if expected_terms set and none present -> ambiguous, send to AI
            if spec["expected_terms"]:
                if not any(t in d_lower for t in spec["expected_terms"]):
                    candidates.append(AICandidate("desc_mtart", basic.sheet, row["_row"], {
                        "product": product,
                        "description": descr,
                        "material_type": mtart,
                        "type_label": spec["label"],
                    }))
    return findings, candidates


# -----------------------------------------------------------------------------
# B. Shelf Life on perishables
# -----------------------------------------------------------------------------
def prefilter_shelf_life(basic: SheetData | None) -> tuple[list[Finding], list[AICandidate]]:
    findings: list[Finding] = []
    candidates: list[AICandidate] = []
    if not basic or not basic.rows:
        return findings, candidates

    for row in basic.rows:
        product = _str(row, "PRODUCT")
        descr = _str(row, "MAKTX")
        if not descr:
            continue
        m = PERISHABLE_PATTERNS.search(descr)
        is_perishable_keyword = bool(m)
        total_shelf = _f(row, "MHDHB")
        min_remaining = _f(row, "MHDRZ")
        sled_indicator = _str(row, "SLED_BBD")

        has_shelf_data = (total_shelf and total_shelf > 0) or sled_indicator

        if is_perishable_keyword and not has_shelf_data:
            findings.append(Finding(
                severity=Severity.WARNING,
                category="AI/ShelfLife",
                sheet=basic.sheet, row=row["_row"],
                field="Shelf Life",
                sap_field="MHDHB/MHDRZ/SLED_BBD",
                message=(f"Description mentions '{m.group(0)}' (perishable) but no "
                         "Shelf Life or SLED indicator is set."),
                material=product,
                value=descr,
                rule_id="AI_SHELF_LIFE_MISSING",
            ))
            continue

        # ambiguous: keyword absent but description could still be perishable
        if not is_perishable_keyword and not has_shelf_data and len(descr) < 80:
            if re.search(r"\b(food|edible|consumable|organic|natural)\b", descr, re.I):
                candidates.append(AICandidate("shelf_life", basic.sheet, row["_row"], {
                    "product": product,
                    "description": descr,
                }))
    return findings, candidates


# -----------------------------------------------------------------------------
# C. Pricing anomaly
# -----------------------------------------------------------------------------
def prefilter_pricing(basic: SheetData | None, valuation: SheetData | None) -> tuple[list[Finding], list[AICandidate]]:
    findings: list[Finding] = []
    candidates: list[AICandidate] = []
    if valuation is None or not valuation.rows:
        return findings, candidates

    # build product->material_type lookup from Basic Data
    mtart_by_product: dict[str, str] = {}
    descr_by_product: dict[str, str] = {}
    if basic and basic.rows:
        for row in basic.rows:
            p = _str(row, "PRODUCT")
            if p:
                mtart_by_product[p] = _str(row, "MTART").upper()
                descr_by_product[p] = _str(row, "MAKTX")

    for row in valuation.rows:
        product = _str(row, "PRODUCT")
        mtart = mtart_by_product.get(product, "")
        descr = descr_by_product.get(product, "")
        std_price = _f(row, "STPRS")
        mov_price = _f(row, "VERPR")
        price_ctrl = _str(row, "VPRSV").upper()

        active_price = std_price if price_ctrl == "S" else mov_price
        if active_price is None and std_price is None and mov_price is None:
            continue

        # Negative price -> deterministic ERROR
        for pname, pval in (("Standard", std_price), ("Moving Avg", mov_price)):
            if pval is not None and pval < 0:
                findings.append(Finding(
                    severity=Severity.ERROR,
                    category="AI/Pricing",
                    sheet=valuation.sheet, row=row["_row"],
                    field=f"{pname} Price",
                    sap_field="STPRS" if pname == "Standard" else "VERPR",
                    message=f"{pname} price is negative ({pval}).",
                    material=product,
                    value=pval,
                    rule_id="AI_PRICE_NEGATIVE",
                ))

        spec = MTART_EXPECTATIONS.get(mtart)
        if spec is None:
            continue

        lo, hi = spec["expected_price_range"]
        if active_price is None:
            continue

        if mtart == "DIEN" and active_price <= 0:
            findings.append(Finding(
                severity=Severity.WARNING,
                category="AI/Pricing",
                sheet=valuation.sheet, row=row["_row"],
                field="Price", sap_field="STPRS/VERPR",
                message="Service material (DIEN) usually has a non-zero price.",
                material=product,
                value=active_price,
                rule_id="AI_PRICE_DIEN_ZERO",
            ))
            continue

        if mtart == "UNBW" and active_price not in (None, 0):
            findings.append(Finding(
                severity=Severity.WARNING,
                category="AI/Pricing",
                sheet=valuation.sheet, row=row["_row"],
                field="Price", sap_field="STPRS/VERPR",
                message="Non-valuated material (UNBW) should have zero price.",
                material=product,
                value=active_price,
                rule_id="AI_PRICE_UNBW_NONZERO",
            ))
            continue

        if active_price <= 0 and mtart not in ("UNBW",):
            findings.append(Finding(
                severity=Severity.WARNING,
                category="AI/Pricing",
                sheet=valuation.sheet, row=row["_row"],
                field="Price", sap_field="STPRS/VERPR",
                message=f"Material type {mtart} ({spec['label']}) typically has a positive price.",
                material=product,
                value=active_price,
                rule_id="AI_PRICE_ZERO",
            ))
            continue

        if active_price < lo or active_price > hi:
            # Out of typical band -> ambiguous, ask AI for confirmation
            candidates.append(AICandidate("pricing", valuation.sheet, row["_row"], {
                "product": product,
                "description": descr,
                "material_type": mtart,
                "type_label": spec["label"],
                "price": active_price,
                "expected_low": lo,
                "expected_high": hi,
            }))

    return findings, candidates


# -----------------------------------------------------------------------------
# D. UoM vs Product Nature - re-use uom module's ai_candidates
# -----------------------------------------------------------------------------
def prefilter_uom_nature(basic: SheetData | None) -> tuple[list[Finding], list[AICandidate]]:
    """
    Returns (det_findings, ai_candidates).
    det_findings: direct Finding objects for mismatch cases, used when AI is disabled.
    ai_candidates: all cases (mismatches + ambiguous) routed to AI when enabled.
    """
    det_findings: list[Finding] = []
    candidates: list[AICandidate] = []
    if basic is None:
        return det_findings, candidates

    deterministic, ai_cands = uom_mod.check_basic_uom(basic)

    for d in deterministic:
        if d.verdict == "mismatch":
            # Fallback finding for when AI is disabled
            det_findings.append(Finding(
                severity=Severity.WARNING,
                category="AI/UoMNature",
                sheet=d.sheet, row=d.row,
                field="Base UoM vs Description",
                sap_field="MEINS/MAKTX",
                message=d.as_message(),
                material=d.product,
                value=f"{d.uom} | {d.description[:120]}",
                rule_id="UOM_NATURE_MISMATCH",
                ai_generated=False,
            ))
            # Also queue for AI (gets AI confirmation when enabled)
            candidates.append(AICandidate("uom_nature", d.sheet, d.row, {
                "product": d.product,
                "description": d.description,
                "uom": d.uom,
                "uom_dimension": d.uom_dim,
                "guessed_nature": d.nature_label,
                "pre_filter_verdict": "mismatch",
            }))

    for cand in ai_cands:
        candidates.append(AICandidate("uom_nature", cand.sheet, cand.row, {
            "product": cand.product,
            "description": cand.description,
            "uom": cand.uom,
            "uom_dimension": cand.uom_dim,
            "guessed_nature": cand.nature_label,
        }))

    return det_findings, candidates


# -----------------------------------------------------------------------------
# E. Arabic descriptions vs English descriptions (Additional Descriptions sheet)
# -----------------------------------------------------------------------------
def _is_arabic(text: str) -> bool:
    """Return True if the text contains at least one Arabic Unicode character."""
    return any(
        "\u0600" <= c <= "\u06FF"   # Arabic block
        or "\u0750" <= c <= "\u077F"  # Arabic Supplement
        or "\uFB50" <= c <= "\uFDFF"  # Arabic Presentation Forms-A
        or "\uFE70" <= c <= "\uFEFF"  # Arabic Presentation Forms-B
        for c in text
    )


def prefilter_arabic_descriptions(
    basic: SheetData | None,
    add_desc: SheetData | None,
) -> tuple[list[Finding], list[AICandidate]]:
    """
    Compare Arabic descriptions in 'Additional Descriptions' with the English
    descriptions in 'Basic Data'.

    Deterministic checks (no AI needed):
      1. Arabic field contains no Arabic characters — likely untranslated or wrong text.
      2. Arabic description is identical to the English — copy-paste, not translated.

    AI candidates: valid Arabic text paired with English for semantic comparison.
    The AI checks whether the Arabic plausibly describes the same product as the English.
    """
    findings: list[Finding] = []
    candidates: list[AICandidate] = []

    if not basic or not basic.rows or not add_desc or not add_desc.rows:
        return findings, candidates

    # Build product -> English description lookup from Basic Data
    en_by_product: dict[str, str] = {}
    for row in basic.rows:
        p = _str(row, "PRODUCT")
        d = _str(row, "MAKTX")
        if p and d:
            en_by_product[p] = d

    for row in add_desc.rows:
        r       = row["_row"]
        product = _str(row, "PRODUCT")
        lang    = _str(row, "SPRAS").upper()
        ar_desc = _str(row, "MAKTX")

        if lang != "AR" or not ar_desc or not product:
            continue

        en_desc = en_by_product.get(product, "")

        # Check 1: field contains no Arabic characters at all
        if not _is_arabic(ar_desc):
            findings.append(Finding(
                severity=Severity.WARNING,
                category="AI/ArabicDesc",
                sheet=add_desc.sheet, row=r,
                field="Arabic Description",
                sap_field="MAKTX",
                message=(
                    f"Arabic description field does not contain Arabic text "
                    f"(appears to be '{ar_desc[:80]}') — may be untranslated."
                ),
                material=product,
                value=ar_desc[:120],
                rule_id="AI_AR_NOT_ARABIC",
            ))
            continue

        # Check 2: Arabic text is identical to English (copy-pasted, not translated)
        if en_desc and ar_desc.strip().lower() == en_desc.strip().lower():
            findings.append(Finding(
                severity=Severity.WARNING,
                category="AI/ArabicDesc",
                sheet=add_desc.sheet, row=r,
                field="Arabic Description",
                sap_field="MAKTX",
                message="Arabic description is identical to the English description — likely not translated.",
                material=product,
                value=ar_desc[:120],
                rule_id="AI_AR_SAME_AS_EN",
            ))
            continue

        # AI candidate: real Arabic text, English available for semantic comparison
        if en_desc:
            candidates.append(AICandidate("arabic_desc", add_desc.sheet, r, {
                "product": product,
                "english_description": en_desc,
                "arabic_description": ar_desc,
            }))

    return findings, candidates


# -----------------------------------------------------------------------------
# AI batch caller (Anthropic)
# -----------------------------------------------------------------------------
SYSTEM_PROMPT = """You are an SAP S/4HANA Material Master data quality reviewer.
You will receive a list of items and decide whether each item raises a data-quality concern.
Be conservative — only flag clear issues. Reply with JSON only.

Output format (strict JSON):
{
  "results": [
    {"id": <int>, "issue": true|false, "severity": "warning"|"info", "reason": "<short, <=140 chars>"},
    ...
  ]
}
"""

FLAG_INSTRUCTIONS = {
    "desc_mtart": (
        "For each item, decide if the product description is consistent with the SAP Material Type. "
        "Mark issue=true only if the description clearly contradicts the type."
    ),
    "shelf_life": (
        "For each item, decide if the description suggests a perishable/food/pharma product that "
        "should have a Shelf Life maintained. Mark issue=true only if perishable nature is clear."
    ),
    "pricing": (
        "For each item, decide if the given price is plausible for the described product and material type. "
        "Mark issue=true only if the price seems clearly wrong (too high or too low for that kind of product)."
    ),
    "uom_nature": (
        "For each item, decide if the Base Unit of Measure dimension matches the physical nature of the "
        "product implied by its description (e.g. liquids -> volume, bulk solids -> mass, discrete items -> count). "
        "Mark issue=true only if there is a clear dimensional mismatch."
    ),
    "arabic_desc": (
        "For each item you are given an English product description and an Arabic product description "
        "for the same SAP material. Decide if the Arabic is a reasonable translation or equivalent of "
        "the English. Mark issue=true only if: (a) the Arabic clearly describes a completely different "
        "product, or (b) the Arabic text is gibberish, meaningless symbols, or an untranslated "
        "transliteration of the English words rather than a real Arabic translation."
    ),
}


@dataclass
class AIBatchResult:
    findings: list[Finding] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0


def _truncate(s: str, n: int = 200) -> str:
    s = s or ""
    return s if len(s) <= n else s[: n - 1] + "..."


def call_ai_for_candidates(candidates: list[AICandidate], api_key: str | None = None,
                           model: str = "claude-haiku-4-5",
                           provider: str = "anthropic",
                           max_per_call: int = 25,
                           ai_progress_callback=None) -> AIBatchResult:
    """Group candidates by flag type, send minimal payloads, parse JSON.

    ai_progress_callback(processed: int, total: int) — called after each chunk.
    """
    out = AIBatchResult()
    if not candidates:
        return out

    total_candidates = len(candidates)
    processed_candidates = 0

    env_key = "OPENAI_API_KEY" if provider == "openai" else "ANTHROPIC_API_KEY"
    api_key = api_key or os.environ.get(env_key)
    if not api_key:
        for c in candidates:
            out.findings.append(Finding(
                severity=Severity.INFO,
                category=f"AI/{c.flag}",
                sheet=c.sheet, row=c.row,
                field="AI check skipped", sap_field=None,
                message=f"Ambiguous; AI confirmation skipped (no {env_key}). Payload: {json.dumps(c.payload)[:160]}",
                material=c.payload.get("product", ""),
                rule_id="AI_SKIPPED_NO_KEY",
                ai_generated=False,
            ))
        return out

    by_flag: dict[str, list[AICandidate]] = {}
    for c in candidates:
        by_flag.setdefault(c.flag, []).append(c)

    for flag, group in by_flag.items():
        for chunk_start in range(0, len(group), max_per_call):
            chunk = group[chunk_start:chunk_start + max_per_call]
            items_payload = []
            for i, c in enumerate(chunk):
                payload = {k: (_truncate(v, 160) if isinstance(v, str) else v) for k, v in c.payload.items()}
                items_payload.append({"id": i, **payload})

            user_msg = (
                FLAG_INSTRUCTIONS[flag]
                + "\n\nItems:\n"
                + json.dumps(items_payload, ensure_ascii=False)
                + "\n\nRespond with JSON only."
            )

            if provider == "openai":
                text, in_tok, out_tok, err = _call_openai(api_key, model, user_msg)
            else:
                text, in_tok, out_tok, err = _call_anthropic(api_key, model, user_msg)

            if err:
                for c in chunk:
                    out.findings.append(Finding(
                        severity=Severity.INFO,
                        category=f"AI/{flag}",
                        sheet=c.sheet, row=c.row,
                        field="AI check failed", sap_field=None,
                        message=f"AI call failed: {err}",
                        material=c.payload.get("product", ""),
                        rule_id="AI_CALL_FAILED",
                    ))
                continue

            out.calls += 1
            out.input_tokens += in_tok
            out.output_tokens += out_tok

            parsed = _safe_json(text)
            if not parsed:
                for c in chunk:
                    out.findings.append(Finding(
                        severity=Severity.INFO,
                        category=f"AI/{flag}",
                        sheet=c.sheet, row=c.row,
                        field="AI parse error", sap_field=None,
                        message=f"AI replied with non-JSON text (truncated): {text[:160]}",
                        material=c.payload.get("product", ""),
                        rule_id="AI_PARSE_ERROR",
                    ))
                continue

            results = parsed.get("results") if isinstance(parsed, dict) else None
            if not isinstance(results, list):
                continue

            for res in results:
                if not isinstance(res, dict):
                    continue
                idx = res.get("id")
                if not isinstance(idx, int) or idx < 0 or idx >= len(chunk):
                    continue
                if not res.get("issue"):
                    continue
                cand = chunk[idx]
                sev_str = (res.get("severity") or "warning").lower()
                severity = Severity.WARNING if sev_str == "warning" else Severity.INFO
                reason = str(res.get("reason") or "")[:300]
                out.findings.append(Finding(
                    severity=severity,
                    category=f"AI/{_friendly_flag(flag)}",
                    sheet=cand.sheet, row=cand.row,
                    field=_field_for_flag(flag), sap_field=_sap_for_flag(flag),
                    message=reason,
                    material=cand.payload.get("product", ""),
                    value=_value_for_flag(flag, cand.payload),
                    rule_id=f"AI_{flag.upper()}",
                    ai_generated=True,
                ))

            # Report sub-progress after each chunk
            processed_candidates += len(chunk)
            if ai_progress_callback:
                ai_progress_callback(processed_candidates, total_candidates)

    return out


def _call_anthropic(api_key: str, model: str, user_msg: str) -> tuple[str, int, int, str]:
    """Returns (text, input_tokens, output_tokens, error_message)."""
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=model,
            max_tokens=1500,
            system=[{"type": "text", "text": SYSTEM_PROMPT,
                     "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user_msg}],
        )
        text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
        usage = getattr(resp, "usage", None)
        in_tok = getattr(usage, "input_tokens", 0) or 0
        out_tok = getattr(usage, "output_tokens", 0) or 0
        return text, in_tok, out_tok, ""
    except Exception as e:
        return "", 0, 0, str(e)


def _call_openai(api_key: str, model: str, user_msg: str) -> tuple[str, int, int, str]:
    """Returns (text, input_tokens, output_tokens, error_message)."""
    try:
        import openai
        client = openai.OpenAI(api_key=api_key)
        kwargs = dict(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": user_msg},
            ],
        )
        # Newer models (gpt-5.x, o1, o3 …) require max_completion_tokens;
        # older models accept max_tokens. Try the new param first.
        try:
            resp = client.chat.completions.create(max_completion_tokens=1500, **kwargs)
        except openai.BadRequestError:
            resp = client.chat.completions.create(max_tokens=1500, **kwargs)
        text = resp.choices[0].message.content or ""
        usage = getattr(resp, "usage", None)
        in_tok = getattr(usage, "prompt_tokens", 0) or 0
        out_tok = getattr(usage, "completion_tokens", 0) or 0
        return text, in_tok, out_tok, ""
    except Exception as e:
        return "", 0, 0, str(e)


def _safe_json(text: str) -> Any:
    text = text.strip()
    # strip markdown fences
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        if text.endswith("```"):
            text = text[:-3].strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}\s*$", text, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                return None
        return None


def _friendly_flag(flag: str) -> str:
    return {
        "desc_mtart":  "DescVsType",
        "shelf_life":  "ShelfLife",
        "pricing":     "Pricing",
        "uom_nature":  "UoMNature",
        "arabic_desc": "ArabicDesc",
    }.get(flag, flag)


def _field_for_flag(flag: str) -> str:
    return {
        "desc_mtart":  "Description vs Material Type",
        "shelf_life":  "Shelf Life",
        "pricing":     "Price",
        "uom_nature":  "Base UoM vs Description",
        "arabic_desc": "Arabic Description vs English",
    }.get(flag, flag)


def _sap_for_flag(flag: str) -> str:
    return {
        "desc_mtart":  "MAKTX/MTART",
        "shelf_life":  "MHDHB/MHDRZ",
        "pricing":     "STPRS/VERPR",
        "uom_nature":  "MEINS/MAKTX",
        "arabic_desc": "MAKTX/SPRAS",
    }.get(flag, "")


def _value_for_flag(flag: str, payload: dict) -> str:
    if flag == "pricing":
        return f"{payload.get('price')} ({payload.get('material_type')})"
    if flag == "uom_nature":
        return f"{payload.get('uom')} | {payload.get('description')}"
    if flag == "arabic_desc":
        return f"AR: {payload.get('arabic_description', '')} | EN: {payload.get('english_description', '')}"
    return payload.get("description", "")


# -----------------------------------------------------------------------------
# Entry point
# -----------------------------------------------------------------------------
def run_ai_flags(data: dict[str, SheetData], use_ai: bool = True,
                 api_key: str | None = None, model: str = "claude-haiku-4-5",
                 provider: str = "anthropic",
                 ai_progress_callback=None):
    """
    ai_progress_callback(processed: int, total: int) — called after each AI chunk.
    """
    findings: list[Finding] = []
    candidates: list[AICandidate] = []

    f, c = prefilter_desc_mtart(data.get("Basic Data"))
    findings += f; candidates += c
    f, c = prefilter_shelf_life(data.get("Basic Data"))
    findings += f; candidates += c
    f, c = prefilter_pricing(data.get("Basic Data"), data.get("Valuation Data"))
    findings += f; candidates += c

    # UoM nature: AI path vs deterministic fallback
    uom_det_findings, uom_candidates = prefilter_uom_nature(data.get("Basic Data"))
    if use_ai:
        candidates += uom_candidates          # AI will confirm/reject
    else:
        findings += uom_det_findings          # direct deterministic warnings

    # Arabic descriptions vs English (Additional Descriptions sheet)
    f, c = prefilter_arabic_descriptions(
        data.get("Basic Data"), data.get("Additional Descriptions")
    )
    findings += f
    if use_ai:
        candidates += c

    ai_result = AIBatchResult()
    if use_ai and candidates:
        ai_result = call_ai_for_candidates(
            candidates, api_key=api_key, model=model, provider=provider,
            ai_progress_callback=ai_progress_callback,
        )
        findings += ai_result.findings

    return findings, ai_result, len(candidates)
