"""Normalized injection-mold sourcing analysis with page-level evidence."""

from __future__ import annotations

import json
import os
import re
from difflib import SequenceMatcher

from rapidfuzz import fuzz

from quotes.ingest import IngestedDocument

ANALYST_SYSTEM_PROMPT = """
You are a senior injection molding tooling sourcing engineer.

Your task is NOT to compare filenames, document names, image counts, or document
metadata. Read and extract all technical, commercial, and pricing information
from every quotation document, including tables, notes, appendices, drawings,
and commercial sections.

Before writing any summary, return a normalized matrix-ready JSON structure.
For every part/tool extract configuration, cavities, steel grades, mold base,
hot runner supplier and drops, insulation, demolding, inserts, compression,
sliders/lifters, gating, PUR, PUR sealing, surface finishing/texture, FIM,
tool temperature control, validation scope, included scope, excluded scope,
tool warranty, options, and lead time.

Extract cost by part, optional costs, engineering changes, shipping, spare
parts, and total quoted value. Separately extract tryouts included, T0/T1/T2
costs, additional tryout, sampling, travel, and total tryout cost. Separately
extract lead time, payment terms, warranty, tool ownership, maintenance
responsibility, tool storage, design review, change management, penalties or
liabilities, delivery terms, quote validity, and currency.

Every non-null value MUST include evidence with exact source text and a source page number.
Use null for missing information; never infer a value that is not in
the quote. Return strict JSON only.
""".strip()

TECHNICAL_FIELDS: tuple[tuple[str, str], ...] = (
    ("configuration", "Configuration"),
    ("cavities", "Number of cavities"),
    ("steel_grades", "Steel grades"),
    ("mold_base", "Mold base"),
    ("hot_runner", "Hot runner supplier and drops"),
    ("insulation", "Insulation"),
    ("demolding", "Demolding method"),
    ("inserts", "Inserts"),
    ("compression", "Compression features"),
    ("sliders_lifters", "Sliders / lifters"),
    ("gating", "Gating system"),
    ("pur", "PUR"),
    ("pur_sealing", "PUR sealing"),
    ("surface_finishing", "Surface finishing / texture"),
    ("fim", "FIM requirements"),
    ("temperature_control", "Tool temperature control"),
    ("validation_scope", "Validation scope"),
    ("included_scope", "Included scope"),
    ("excluded_scope", "Excluded scope"),
    ("tool_warranty", "Tool warranty"),
    ("options", "Options"),
    ("lead_time", "Lead time"),
)

PART_COST_FIELDS: tuple[tuple[str, str], ...] = (
    ("tool_cost", "Tool cost"),
    ("optional_costs", "Optional costs"),
    ("engineering_changes", "Engineering changes"),
    ("shipping", "Shipping"),
    ("spare_parts", "Spare parts"),
)

QUOTE_COST_FIELDS: tuple[tuple[str, str], ...] = (
    ("tool_subtotal", "Tool cost subtotal"),
    ("optional_costs", "Optional costs"),
    ("engineering_changes", "Engineering changes"),
    ("shipping", "Shipping"),
    ("spare_parts", "Spare parts"),
    ("total_quoted_value", "Total quoted value"),
)

TRYOUT_FIELDS: tuple[tuple[str, str], ...] = (
    ("included_tryouts", "Number of tryouts included"),
    ("t0_cost", "T0 cost"),
    ("t1_cost", "T1 cost"),
    ("t2_cost", "T2 cost"),
    ("additional_tryout_cost", "Additional tryout cost"),
    ("sampling_cost", "Sampling cost"),
    ("travel_cost", "Travel cost"),
    ("total_tryout_cost", "Total tryout cost"),
)

TERM_FIELDS: tuple[tuple[str, str], ...] = (
    ("lead_time", "Lead time"),
    ("payment_terms", "Payment terms"),
    ("warranty", "Warranty"),
    ("tool_ownership", "Tool ownership"),
    ("maintenance_responsibility", "Maintenance responsibility"),
    ("tool_storage", "Tool storage"),
    ("design_review", "Design review process"),
    ("change_management", "Change management process"),
    ("penalties_liabilities", "Penalties / liabilities"),
    ("delivery_terms", "Delivery terms"),
    ("validity", "Quote validity"),
    ("currency", "Currency"),
)

FIELD_ALIASES = {
    "configuration": ("configuration", "tool configuration"),
    "cavities": ("number of cavities", "cavities", "cavity"),
    "steel_grades": ("steel grades", "steel grade", "tool steel", "steel"),
    "mold_base": ("mold base", "mould base", "tool base"),
    "hot_runner": ("hot runner supplier and drops", "hot runner", "runner supplier"),
    "insulation": ("insulation", "insulation plate"),
    "demolding": ("demolding method", "demolding", "demoulding", "ejection"),
    "inserts": ("inserts", "insert"),
    "compression": ("compression features", "compression"),
    "sliders_lifters": ("sliders lifters", "sliders / lifters", "sliders", "lifters", "slides"),
    "gating": ("gating system", "gating", "gate system", "gates"),
    "pur": ("pur", "polyurethane"),
    "pur_sealing": ("pur sealing", "pur seal", "polyurethane sealing"),
    "surface_finishing": ("surface finishing texture", "surface finishing", "surface finish", "texture", "polish"),
    "fim": ("fim requirements", "fim", "film insert molding", "film insert moulding"),
    "temperature_control": ("tool temperature control", "tool temperature", "mold temperature", "mould temperature", "cooling"),
    "validation_scope": ("validation scope", "validation", "qualification"),
    "included_scope": ("included scope", "scope included", "inclusions"),
    "excluded_scope": ("excluded scope", "scope excluded", "exclusions"),
    "tool_warranty": ("tool warranty",),
    "options": ("options", "option", "optional"),
    "lead_time": ("lead time", "delivery time"),
}

PART_COST_ALIASES = {
    "tool_cost": ("tool cost", "tool price", "part price", "price"),
    "optional_costs": ("optional costs", "option cost"),
    "engineering_changes": ("engineering changes", "engineering change", "design changes"),
    "shipping": ("shipping", "freight"),
    "spare_parts": ("spare parts", "spares"),
}

QUOTE_COST_ALIASES = {
    "tool_subtotal": ("tool cost subtotal", "tool subtotal", "tooling subtotal"),
    "optional_costs": ("total optional costs", "optional costs"),
    "engineering_changes": ("engineering changes", "engineering change allowance"),
    "shipping": ("shipping", "freight"),
    "spare_parts": ("spare parts", "spares"),
    "total_quoted_value": ("total quoted value", "grand total", "total quote", "total"),
}

TRYOUT_ALIASES = {
    "included_tryouts": ("number of tryouts included", "tryouts included", "trials included"),
    "t0_cost": ("t0 cost", "t0 tryout"),
    "t1_cost": ("t1 cost", "t1 tryout"),
    "t2_cost": ("t2 cost", "t2 tryout"),
    "additional_tryout_cost": ("additional tryout cost", "extra tryout", "additional trial"),
    "sampling_cost": ("sampling cost", "sample cost"),
    "travel_cost": ("travel cost", "travel"),
    "total_tryout_cost": ("total tryout cost", "tryout cost", "try-out cost", "total trial cost"),
}

TERM_ALIASES = {
    "lead_time": ("overall lead time", "commercial lead time", "lead time"),
    "payment_terms": ("payment terms", "payment condition"),
    "warranty": ("warranty", "guarantee"),
    "tool_ownership": ("tool ownership", "ownership"),
    "maintenance_responsibility": ("maintenance responsibility", "tool maintenance", "maintenance"),
    "tool_storage": ("tool storage", "storage"),
    "design_review": ("design review process", "design review"),
    "change_management": ("change management process", "change management", "engineering change process"),
    "penalties_liabilities": ("penalties or liabilities", "penalties liabilities", "penalties", "liabilities"),
    "delivery_terms": ("delivery terms", "incoterms", "incoterm"),
    "validity": ("quote validity", "quotation validity", "validity"),
    "currency": ("currency",),
}

PART_HEADER = re.compile(r"^(?:part|component|tool)(?:\s+name)?\s*[:#-]\s*(.+)$", re.I)
PART_NUMBER = re.compile(r"^(?:part|component)\s*(?:number|no\.?|#)\s*:\s*(.+)$", re.I)
VENDOR = re.compile(r"^(?:vendor|toolmaker|supplier)\s*:\s*(.+)$", re.I)
SECTION_HEADER = re.compile(
    r"^(?:cost comparison|tryout costs?|try-out costs?|commercial terms?|terms and conditions)\s*:?\s*$",
    re.I,
)
MONEY = re.compile(r"(?:USD|EUR|GBP|CAD|CNY|RMB|[$€£])?\s*([\d,]+(?:\.\d{1,2})?)", re.I)


def _empty_values(fields: tuple[tuple[str, str], ...]) -> dict:
    return {key: {"value": None, "evidence": None} for key, _ in fields}


def _normalized_label(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", label.lower()).strip()


def _match_alias(label: str, aliases: dict[str, tuple[str, ...]]) -> str | None:
    normalized = _normalized_label(label)
    best = None
    best_length = 0
    for key, names in aliases.items():
        for name in names:
            alias = _normalized_label(name)
            if normalized == alias and len(alias) > best_length:
                best = key
                best_length = len(alias)
    return best


def _money(value: str | None) -> float:
    match = MONEY.search(value or "")
    if not match:
        return 0.0
    try:
        return float(match.group(1).replace(",", ""))
    except ValueError:
        return 0.0


def _cost_value(value: str) -> float | str:
    amount = _money(value)
    if amount or re.search(r"(?:^|\s)0(?:\.00)?(?:\s|$)", value):
        return amount
    return value.strip()


def _evidence(line: str, page: int | None) -> dict:
    return {"text": line.strip(), "page": int(page or 1)}


def _set_value(container: dict, key: str, value, line: str, page: int) -> None:
    container[key] = {"value": value if value not in {"", None} else None, "evidence": _evidence(line, page)}


def _page_lines(doc: IngestedDocument) -> list[tuple[int, str]]:
    page_blocks = [
        block for block in doc.blocks
        if block.get("text") and block.get("type") in {"page_text", "paragraph"}
    ]
    if not page_blocks:
        return [(1, line) for line in doc.text.splitlines()]
    lines = []
    for block in page_blocks:
        page = int(block.get("page") or 1)
        lines.extend((page, line) for line in str(block["text"]).splitlines())
    return lines


def _new_part(name: str, page: int, line: str) -> dict:
    return {
        "name": name.strip(),
        "part_number": None,
        "part_evidence": _evidence(line, page),
        "technical": _empty_values(TECHNICAL_FIELDS),
        "costs": _empty_values(PART_COST_FIELDS),
    }


def local_extract(doc: IngestedDocument) -> dict:
    result = {
        "vendor": None,
        "vendor_evidence": None,
        "parts": [],
        "costs": _empty_values(QUOTE_COST_FIELDS),
        "tryouts": _empty_values(TRYOUT_FIELDS),
        "terms": _empty_values(TERM_FIELDS),
        "backend": "normalized-local",
    }
    current = None
    for page, raw in _page_lines(doc):
        line = " ".join(raw.strip().split())
        if not line:
            continue
        vendor_match = VENDOR.match(line)
        if vendor_match:
            result["vendor"] = vendor_match.group(1).strip()
            result["vendor_evidence"] = _evidence(line, page)
            continue
        number_match = PART_NUMBER.match(line)
        if number_match and current is not None:
            current["part_number"] = number_match.group(1).strip()
            continue
        part_match = PART_HEADER.match(line)
        if part_match:
            current = _new_part(part_match.group(1), page, line)
            result["parts"].append(current)
            continue
        if SECTION_HEADER.match(line):
            current = None
            continue
        if ":" not in line:
            continue
        label, value = [piece.strip() for piece in line.split(":", 1)]

        tryout_key = _match_alias(label, TRYOUT_ALIASES)
        if tryout_key:
            parsed = _cost_value(value) if tryout_key != "included_tryouts" else value
            _set_value(result["tryouts"], tryout_key, parsed, line, page)
            continue
        term_key = _match_alias(label, TERM_ALIASES)
        technical_key = _match_alias(label, FIELD_ALIASES)
        part_cost_key = _match_alias(label, PART_COST_ALIASES)
        quote_cost_key = _match_alias(label, QUOTE_COST_ALIASES)

        if current is not None and technical_key:
            _set_value(current["technical"], technical_key, value, line, page)
            continue
        if current is not None and part_cost_key:
            _set_value(current["costs"], part_cost_key, _cost_value(value), line, page)
            continue
        if quote_cost_key:
            _set_value(result["costs"], quote_cost_key, _cost_value(value), line, page)
            continue
        if term_key:
            _set_value(result["terms"], term_key, value, line, page)
            continue

    tool_costs = [
        part["costs"]["tool_cost"]["value"] or 0
        for part in result["parts"]
    ]
    if not result["costs"]["tool_subtotal"]["value"] and any(tool_costs):
        result["costs"]["tool_subtotal"]["value"] = round(sum(tool_costs), 2)
    if not result["costs"]["total_quoted_value"]["value"]:
        components = [
            result["costs"][key]["value"] or 0
            for key, _ in QUOTE_COST_FIELDS
            if key != "total_quoted_value"
        ]
        if any(components):
            result["costs"]["total_quoted_value"]["value"] = round(sum(components), 2)
    return result


def _document_for_prompt(doc: IngestedDocument) -> str:
    blocks = _page_lines(doc)
    chunks: list[str] = []
    current_page = None
    for page, line in blocks:
        if page != current_page:
            chunks.append(f"\n--- PAGE {page} ---")
            current_page = page
        chunks.append(line)
    for block in doc.blocks:
        if block.get("type") == "table" and block.get("text"):
            chunks.append(
                f"\n--- TABLE ON PAGE {int(block.get('page') or 1)} ---\n{block['text']}"
            )
    return "\n".join(chunks)[:45_000]


def _llm_extract(doc: IngestedDocument) -> dict | None:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key or os.environ.get("PHOTOEDITOR_DISABLE_VLM", "").strip().lower() in {"1", "true", "yes"}:
        return None
    schema_hint = {
        "vendor": None,
        "vendor_evidence": {"text": None, "page": None},
        "parts": [
            {
                "name": None,
                "part_number": None,
                "part_evidence": {"text": None, "page": None},
                "technical": _empty_values(TECHNICAL_FIELDS),
                "costs": _empty_values(PART_COST_FIELDS),
            }
        ],
        "costs": _empty_values(QUOTE_COST_FIELDS),
        "tryouts": _empty_values(TRYOUT_FIELDS),
        "terms": _empty_values(TERM_FIELDS),
    }
    try:
        import httpx

        response = httpx.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={
                "model": os.environ.get("PHOTOEDITOR_OPENAI_MODEL", "gpt-4o"),
                "temperature": 0,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": ANALYST_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": (
                            "Extract this quotation into exactly this JSON shape. "
                            "All missing values must be null.\n\n"
                            f"JSON shape:\n{json.dumps(schema_hint)}\n\n"
                            f"Quotation:\n{_document_for_prompt(doc)}"
                        ),
                    },
                ],
            },
            timeout=120.0,
        )
        response.raise_for_status()
        data = json.loads(response.json()["choices"][0]["message"]["content"])
        if not isinstance(data.get("parts"), list):
            return None
        data["backend"] = "openai-sourcing-analyst"
        return data
    except Exception:
        return None


def extract_sourcing_quote(doc: IngestedDocument) -> dict:
    return _llm_extract(doc) or local_extract(doc)


def _part_similarity(left: dict, right: dict) -> float:
    left_no = re.sub(r"\W+", "", str(left.get("part_number") or "")).lower()
    right_no = re.sub(r"\W+", "", str(right.get("part_number") or "")).lower()
    if left_no and right_no and left_no == right_no:
        return 1.0
    a = str(left.get("name") or "")
    b = str(right.get("name") or "")
    return max(fuzz.token_set_ratio(a, b) / 100.0, SequenceMatcher(None, a.lower(), b.lower()).ratio())


def _match_parts(left: list[dict], right: list[dict]) -> list[tuple[dict | None, dict | None, float]]:
    candidates = []
    for i, a in enumerate(left):
        for j, b in enumerate(right):
            score = _part_similarity(a, b)
            if score >= 0.58:
                candidates.append((score, i, j))
    candidates.sort(reverse=True)
    used_a: set[int] = set()
    used_b: set[int] = set()
    rows = []
    for score, i, j in candidates:
        if i in used_a or j in used_b:
            continue
        used_a.add(i)
        used_b.add(j)
        rows.append((left[i], right[j], score))
    rows.extend((part, None, 0.0) for i, part in enumerate(left) if i not in used_a)
    rows.extend((None, part, 0.0) for j, part in enumerate(right) if j not in used_b)
    return rows


def _entry(container: dict | None, key: str) -> dict:
    if not container:
        return {"value": None, "evidence": None}
    value = container.get(key)
    if isinstance(value, dict) and "value" in value:
        return {"value": value.get("value"), "evidence": value.get("evidence")}
    return {"value": value, "evidence": None}


def _compare_entries(left: dict, right: dict, key: str, label: str, impact: str = "Medium") -> dict:
    a = left.get("value")
    b = right.get("value")
    if a in {"", None} and b in {"", None}:
        status, difference, higher = "not_specified", "Not specified by either vendor.", "Neither"
    elif b in {"", None}:
        status, difference, higher = "missing_in_b", "Vendor B does not specify this scope.", "Vendor A"
    elif a in {"", None}:
        status, difference, higher = "added_in_b", "Vendor A does not specify this scope.", "Vendor B"
    else:
        a_norm = _normalized_label(str(a))
        b_norm = _normalized_label(str(b))
        a_numbers = re.findall(r"\d+(?:\.\d+)?", a_norm)
        b_numbers = re.findall(r"\d+(?:\.\d+)?", b_norm)
        numeric_difference = (a_numbers or b_numbers) and a_numbers != b_numbers
        same = not numeric_difference and (
            a_norm == b_norm
            or max(
                fuzz.token_sort_ratio(a_norm, b_norm) / 100.0,
                SequenceMatcher(None, a_norm, b_norm).ratio(),
            ) >= 0.9
        )
        if same:
            status, difference, higher = "same", "Equivalent stated scope.", "Equivalent"
        else:
            status = "different"
            difference = f"Vendor A specifies “{a}”; Vendor B specifies “{b}”."
            higher = _higher_scope(a, b, key)
    return {
        "key": key,
        "label": label,
        "left": a if a not in {"", None} else None,
        "right": b if b not in {"", None} else None,
        "status": status,
        "difference": difference,
        "higher_scope": higher,
        "commercial_impact": "None" if status in {"same", "not_specified"} else impact,
        "left_evidence": left.get("evidence"),
        "right_evidence": right.get("evidence"),
    }


def _higher_scope(a, b, key: str) -> str:
    a_text = _normalized_label(str(a))
    b_text = _normalized_label(str(b))
    negative = ("not included", "excluded", "none", "not required", "by customer")
    a_negative = any(term in a_text for term in negative)
    b_negative = any(term in b_text for term in negative)
    if a_negative != b_negative:
        return "Vendor B" if a_negative else "Vendor A"
    if key == "cavities":
        a_num = re.search(r"\d+", a_text)
        b_num = re.search(r"\d+", b_text)
        if a_num and b_num and a_num.group() != b_num.group():
            return "Vendor B (higher output)" if int(b_num.group()) > int(a_num.group()) else "Vendor A (higher output)"
    if key in {"tool_warranty", "warranty", "tool_storage"}:
        a_num = re.search(r"[\d,]+", a_text)
        b_num = re.search(r"[\d,]+", b_text)
        if a_num and b_num:
            a_value = int(a_num.group().replace(",", ""))
            b_value = int(b_num.group().replace(",", ""))
            if a_value != b_value:
                return "Vendor A" if a_value > b_value else "Vendor B"
    if key in {"lead_time"}:
        a_num = re.search(r"\d+", a_text)
        b_num = re.search(r"\d+", b_text)
        if a_num and b_num and a_num.group() != b_num.group():
            return "Vendor A (shorter)" if int(a_num.group()) < int(b_num.group()) else "Vendor B (shorter)"
    if key in {"validation_scope", "included_scope"}:
        if ("only" in a_text) != ("only" in b_text):
            return "Vendor B" if "only" in a_text else "Vendor A"
        a_items = len(re.split(r",| and ", a_text))
        b_items = len(re.split(r",| and ", b_text))
        if a_items != b_items:
            return "Vendor A" if a_items > b_items else "Vendor B"
    if key == "excluded_scope":
        a_items = len(re.split(r",| and ", a_text))
        b_items = len(re.split(r",| and ", b_text))
        if a_items != b_items:
            return "Vendor A (fewer exclusions)" if a_items < b_items else "Vendor B (fewer exclusions)"
    if key == "maintenance_responsibility":
        if "vendor" in a_text and "customer" in b_text:
            return "Vendor A"
        if "vendor" in b_text and "customer" in a_text:
            return "Vendor B"
    if key == "penalties_liabilities":
        if ("none" in a_text) != ("none" in b_text):
            return "Vendor B" if "none" in a_text else "Vendor A"
    return "Engineering review required"


HIGH_IMPACT = {
    "steel_grades", "mold_base", "demolding", "compression", "sliders_lifters",
    "gating", "pur_sealing", "validation_scope", "included_scope", "excluded_scope",
    "tool_warranty",
}


def _matrix(left: dict, right: dict, fields: tuple[tuple[str, str], ...], *, costs: bool = False) -> list[dict]:
    rows = []
    for key, label in fields:
        impact = "High" if key in HIGH_IMPACT else "Medium"
        row = _compare_entries(_entry(left, key), _entry(right, key), key, label, impact)
        if costs:
            try:
                a = float(row["left"] or 0)
                b = float(row["right"] or 0)
                row["difference_amount"] = round(b - a, 2)
                row["commercial_impact"] = "High" if a or b else row["commercial_impact"]
                if key == "included_tryouts":
                    row["unit"] = "count"
                    if a != b:
                        row["higher_scope"] = "Vendor A" if a > b else "Vendor B"
                a_source = _normalized_label(str((row.get("left_evidence") or {}).get("text") or ""))
                b_source = _normalized_label(str((row.get("right_evidence") or {}).get("text") or ""))
                a_excluded = any(word in a_source for word in ("not included", "excluded", "none"))
                b_excluded = any(word in b_source for word in ("not included", "excluded", "none"))
                if a_excluded != b_excluded:
                    row["higher_scope"] = "Vendor B" if a_excluded else "Vendor A"
                elif key != "included_tryouts" and a and b and a != b:
                    row["higher_scope"] = "Vendor A lower cost" if a < b else "Vendor B lower cost"
            except (TypeError, ValueError):
                row["difference_amount"] = None
        rows.append(row)
    return rows


def build_normalized_comparison(left: dict, right: dict) -> dict:
    parts = []
    for a, b, confidence in _match_parts(left.get("parts") or [], right.get("parts") or []):
        technical_a = (a or {}).get("technical") or {}
        technical_b = (b or {}).get("technical") or {}
        costs_a = (a or {}).get("costs") or {}
        costs_b = (b or {}).get("costs") or {}
        parts.append(
            {
                "part": (a or b or {}).get("name"),
                "left_name": (a or {}).get("name"),
                "right_name": (b or {}).get("name"),
                "part_number": (a or b or {}).get("part_number"),
                "match_confidence": round(confidence, 3),
                "technical": _matrix(technical_a, technical_b, TECHNICAL_FIELDS),
                "costs": _matrix(costs_a, costs_b, PART_COST_FIELDS, costs=True),
            }
        )
    cost_matrix = _matrix(left.get("costs") or {}, right.get("costs") or {}, QUOTE_COST_FIELDS, costs=True)
    tryout_matrix = _matrix(left.get("tryouts") or {}, right.get("tryouts") or {}, TRYOUT_FIELDS, costs=True)
    term_matrix = _matrix(left.get("terms") or {}, right.get("terms") or {}, TERM_FIELDS)
    result = {
        "detected": bool(parts),
        "vendors": {"left": left.get("vendor"), "right": right.get("vendor")},
        "parts": parts,
        "costs": cost_matrix,
        "tryouts": tryout_matrix,
        "terms": term_matrix,
    }
    result["summary"] = _summary(result)
    return result


def _missing(matrix: dict, side: str) -> list[str]:
    missing = []
    target_status = "added_in_b" if side == "Vendor A" else "missing_in_b"
    for part in matrix["parts"]:
        for row in part["technical"]:
            if row["status"] in {target_status, "not_specified"}:
                missing.append(f"{part['part']}: {row['label']}")
    for section in ("tryouts", "terms"):
        for row in matrix[section]:
            if row["status"] in {target_status, "not_specified"}:
                missing.append(row["label"])
    return missing


def _summary(matrix: dict) -> dict:
    def numeric(field: str, rows: list[dict]) -> tuple[float, float]:
        row = next((item for item in rows if item["key"] == field), None)
        try:
            left_value = float((row or {}).get("left") or 0)
        except (TypeError, ValueError):
            left_value = 0.0
        try:
            right_value = float((row or {}).get("right") or 0)
        except (TypeError, ValueError):
            right_value = 0.0
        return left_value, right_value

    tool_a, tool_b = numeric("tool_subtotal", matrix["costs"])
    total_a, total_b = numeric("total_quoted_value", matrix["costs"])
    tryout_a, tryout_b = numeric("total_tryout_cost", matrix["tryouts"])
    scope_a = scope_b = 0
    high_risks = []
    for part in matrix["parts"]:
        for row in part["technical"]:
            if row["higher_scope"].startswith("Vendor A"):
                scope_a += 1
            elif row["higher_scope"].startswith("Vendor B"):
                scope_b += 1
            if row["commercial_impact"] == "High" and row["status"] not in {"same", "not_specified"}:
                high_risks.append(f"{part['part']}: {row['label']} differs")
    missing_a = _missing(matrix, "Vendor A")
    missing_b = _missing(matrix, "Vendor B")
    terms_a = sum(1 for row in matrix["terms"] if row["higher_scope"].startswith("Vendor A"))
    terms_b = sum(1 for row in matrix["terms"] if row["higher_scope"].startswith("Vendor B"))
    if total_a and total_b:
        recommended = "Vendor A" if total_a + tryout_a < total_b + tryout_b else "Vendor B"
        recommended += ", subject to closing high-impact scope gaps"
    else:
        recommended = "No recommendation until both vendors provide total quoted value"
    local = {
        "lowest_tool_cost": (
            "Vendor A" if tool_a and (not tool_b or tool_a < tool_b)
            else "Vendor B" if tool_b and (not tool_a or tool_b < tool_a)
            else "Equal / not specified"
        ),
        "lowest_tryout_cost": (
            "Vendor A" if tryout_a and (not tryout_b or tryout_a < tryout_b)
            else "Vendor B" if tryout_b and (not tryout_a or tryout_b < tryout_a)
            else "Equal / not specified"
        ),
        "best_technical_scope": (
            "Vendor A" if scope_a > scope_b else "Vendor B" if scope_b > scope_a else "Engineering review required"
        ),
        "best_commercial_terms": (
            "Vendor A" if terms_a > terms_b else "Vendor B" if terms_b > terms_a else "Commercial review required"
        ),
        "missing_from_vendor_a": missing_a,
        "missing_from_vendor_b": missing_b,
        "potential_risks": high_risks + [
            item for item in missing_a[:5] + missing_b[:5]
            if item not in high_risks
        ],
        "recommended_vendor": recommended,
    }
    return _llm_summary(matrix, local) or local


def _llm_summary(matrix: dict, fallback: dict) -> dict | None:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key or os.environ.get("PHOTOEDITOR_DISABLE_VLM", "").strip().lower() in {"1", "true", "yes"}:
        return None
    try:
        import httpx

        response = httpx.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={
                "model": os.environ.get("PHOTOEDITOR_OPENAI_MODEL", "gpt-4o"),
                "temperature": 0,
                "response_format": {"type": "json_object"},
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            ANALYST_SYSTEM_PROMPT
                            + "\nThe normalized matrix has already been created. Analyze only that matrix."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            "Return JSON with exactly these keys: lowest_tool_cost, "
                            "lowest_tryout_cost, best_technical_scope, best_commercial_terms, "
                            "missing_from_vendor_a (array), missing_from_vendor_b (array), "
                            "potential_risks (array), recommended_vendor. Explain the vendor "
                            "recommendation briefly in recommended_vendor. Do not use filenames "
                            "or metadata.\n\nNormalized matrix:\n"
                            + json.dumps(matrix)[:30_000]
                        ),
                    },
                ],
            },
            timeout=90.0,
        )
        response.raise_for_status()
        data = json.loads(response.json()["choices"][0]["message"]["content"])
        if not isinstance(data, dict):
            return None
        return {key: data.get(key, value) for key, value in fallback.items()}
    except Exception:
        return None
