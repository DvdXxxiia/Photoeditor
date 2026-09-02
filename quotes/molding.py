"""Injection-molding tool quote extraction and field-by-field comparison."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher

from rapidfuzz import fuzz

TECHNICAL_FIELDS: tuple[tuple[str, str], ...] = (
    ("configuration", "Configuration"),
    ("insulation", "Insulation"),
    ("demolding", "Demolding"),
    ("inserts", "Inserts"),
    ("compression", "Compression"),
    ("sliders", "Sliders"),
    ("gating", "Gating"),
    ("pur", "PUR"),
    ("pur_sealing", "PUR sealing"),
    ("surface_finishing", "Surface finishing"),
    ("fim", "FIM"),
    ("tool_temperature", "Tool temperature"),
    ("options", "Options"),
    ("lead_time", "Lead time"),
)

FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "configuration": ("configuration", "tool configuration", "cavities", "cavity"),
    "insulation": ("insulation", "thermal insulation"),
    "demolding": ("demolding", "de-molding", "demoulding", "ejection", "ejector"),
    "inserts": ("inserts", "insert"),
    "compression": ("compression", "compression system"),
    "sliders": ("sliders", "slider", "slides"),
    "gating": ("gating", "gate", "runner", "hot runner"),
    "pur": ("pur", "polyurethane"),
    "pur_sealing": ("pur sealing", "pur seal", "polyurethane sealing"),
    "surface_finishing": ("surface finishing", "surface finish", "finish", "texture", "polish"),
    "fim": ("fim", "film insert molding", "film insert moulding"),
    "tool_temperature": ("tool temperature", "mold temperature", "mould temperature", "temperature"),
    "options": ("options", "option", "optional"),
    "lead_time": ("lead time", "delivery time", "tool delivery"),
}

GLOBAL_ALIASES: dict[str, tuple[str, ...]] = {
    "tryout_cost": ("tryout cost", "try-out cost", "tool trial cost", "trial cost", "tryout"),
    "payment_terms": ("payment terms", "payment condition", "payment"),
    "delivery_terms": ("delivery terms", "incoterms", "incoterm"),
    "warranty": ("warranty", "guarantee"),
    "validity": ("quote validity", "quotation validity", "validity"),
    "currency": ("currency",),
}

PART_HEADER = re.compile(
    r"^\s*(?:part|component|tool)(?:\s+name)?\s*[:#-]\s*(.+?)\s*$",
    re.I,
)
VENDOR = re.compile(r"^\s*(?:vendor|toolmaker|supplier)\s*:\s*(.+?)\s*$", re.I)
MONEY = re.compile(r"(?:USD|EUR|GBP|CAD|CNY|RMB|[$€£])?\s*([\d,]+(?:\.\d{1,2})?)", re.I)
PRICE_LINE = re.compile(r"^\s*(?:part\s+|tool\s+)?price\s*:\s*(.+?)\s*$", re.I)


def _clean(value: str) -> str:
    return " ".join((value or "").strip().split())


def _money(value: str | None) -> float:
    if not value:
        return 0.0
    match = MONEY.search(value)
    if not match:
        return 0.0
    try:
        return float(match.group(1).replace(",", ""))
    except ValueError:
        return 0.0


def _field_from_label(label: str, aliases: dict[str, tuple[str, ...]]) -> str | None:
    normalized = re.sub(r"[^a-z0-9]+", " ", label.lower()).strip()
    best = None
    best_len = 0
    for key, names in aliases.items():
        for name in names:
            normalized_name = re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()
            if normalized == normalized_name or normalized.startswith(normalized_name + " "):
                if len(normalized_name) > best_len:
                    best = key
                    best_len = len(normalized_name)
    return best


@dataclass
class MoldPart:
    name: str
    part_number: str | None = None
    configuration: str | None = None
    insulation: str | None = None
    demolding: str | None = None
    inserts: str | None = None
    compression: str | None = None
    sliders: str | None = None
    gating: str | None = None
    pur: str | None = None
    pur_sealing: str | None = None
    surface_finishing: str | None = None
    fim: str | None = None
    tool_temperature: str | None = None
    price: float = 0.0
    options: str | None = None
    lead_time: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class MoldQuote:
    vendor: str | None = None
    parts: list[MoldPart] = field(default_factory=list)
    tryout_cost: float = 0.0
    payment_terms: str | None = None
    delivery_terms: str | None = None
    warranty: str | None = None
    validity: str | None = None
    currency: str | None = None

    @property
    def tooling_total(self) -> float:
        return round(sum(part.price for part in self.parts), 2)

    @property
    def total_with_tryout(self) -> float:
        return round(self.tooling_total + self.tryout_cost, 2)

    def to_dict(self) -> dict:
        return {
            "vendor": self.vendor,
            "parts": [part.to_dict() for part in self.parts],
            "tooling_total": self.tooling_total,
            "tryout_cost": self.tryout_cost,
            "total_with_tryout": self.total_with_tryout,
            "terms": {
                "payment_terms": self.payment_terms,
                "delivery_terms": self.delivery_terms,
                "warranty": self.warranty,
                "validity": self.validity,
                "currency": self.currency,
            },
        }


def _parse_table_parts(tables: list[list[list[str]]]) -> list[MoldPart]:
    parts: list[MoldPart] = []
    for table in tables:
        if len(table) < 2:
            continue
        headers = [_clean(cell).lower() for cell in table[0]]
        part_i = next(
            (i for i, header in enumerate(headers) if header in {"part", "part name", "component", "tool"}),
            None,
        )
        if part_i is None:
            continue
        mappings: dict[int, str] = {}
        for i, header in enumerate(headers):
            field_name = _field_from_label(header, FIELD_ALIASES)
            if field_name:
                mappings[i] = field_name
            elif "price" in header or "cost" in header:
                mappings[i] = "price"
            elif header in {"part no", "part number", "part #"}:
                mappings[i] = "part_number"
        for row in table[1:]:
            if part_i >= len(row):
                continue
            name = _clean(row[part_i])
            if not name:
                continue
            part = MoldPart(name=name)
            for i, field_name in mappings.items():
                if i >= len(row):
                    continue
                value = _clean(row[i])
                if not value:
                    continue
                if field_name == "price":
                    part.price = _money(value)
                else:
                    setattr(part, field_name, value)
            parts.append(part)
    return parts


def parse_mold_quote(text: str, tables: list[list[list[str]]] | None = None) -> MoldQuote:
    """Parse labeled tool-quote sections and table rows into molding parts."""
    quote = MoldQuote(parts=_parse_table_parts(tables or []))
    current: MoldPart | None = None
    last_target: tuple[object, str] | None = None
    for raw in (text or "").splitlines():
        line = _clean(raw)
        if not line:
            last_target = None
            continue
        vendor_match = VENDOR.match(line)
        if vendor_match:
            quote.vendor = _clean(vendor_match.group(1))
            current = None
            last_target = None
            continue
        part_match = PART_HEADER.match(line)
        if part_match:
            current = MoldPart(name=_clean(part_match.group(1)))
            quote.parts.append(current)
            last_target = None
            continue
        if ":" not in line:
            if last_target:
                target, field_name = last_target
                previous = getattr(target, field_name, None)
                setattr(target, field_name, _clean(f"{previous or ''} {line}"))
            continue
        label, value = [_clean(bit) for bit in line.split(":", 1)]
        global_field = _field_from_label(label, GLOBAL_ALIASES)
        if global_field:
            if global_field == "tryout_cost":
                quote.tryout_cost = _money(value)
            else:
                setattr(quote, global_field, value or None)
                last_target = (quote, global_field)
            continue
        if current is None:
            continue
        if label.lower() in {"part no", "part number", "part #"}:
            current.part_number = value or None
            last_target = (current, "part_number")
            continue
        if PRICE_LINE.match(line):
            current.price = _money(value)
            last_target = None
            continue
        technical = _field_from_label(label, FIELD_ALIASES)
        if technical:
            setattr(current, technical, value or None)
            last_target = (current, technical)
    return quote


def _name_similarity(left: MoldPart, right: MoldPart) -> float:
    if left.part_number and right.part_number:
        if re.sub(r"\W+", "", left.part_number).lower() == re.sub(r"\W+", "", right.part_number).lower():
            return 1.0
    token = fuzz.token_set_ratio(left.name, right.name) / 100.0
    sequence = SequenceMatcher(None, left.name.lower(), right.name.lower()).ratio()
    return max(token, sequence)


def match_mold_parts(left: list[MoldPart], right: list[MoldPart]) -> list[tuple[MoldPart | None, MoldPart | None, float]]:
    candidates: list[tuple[float, int, int]] = []
    for i, left_part in enumerate(left):
        for j, right_part in enumerate(right):
            score = _name_similarity(left_part, right_part)
            if score >= 0.58:
                candidates.append((score, i, j))
    candidates.sort(reverse=True)
    used_left: set[int] = set()
    used_right: set[int] = set()
    rows: list[tuple[MoldPart | None, MoldPart | None, float]] = []
    for score, i, j in candidates:
        if i in used_left or j in used_right:
            continue
        used_left.add(i)
        used_right.add(j)
        rows.append((left[i], right[j], score))
    rows.extend((part, None, 0.0) for i, part in enumerate(left) if i not in used_left)
    rows.extend((None, part, 0.0) for j, part in enumerate(right) if j not in used_right)
    return rows


def _norm_value(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()


def _compare_value(left: str | None, right: str | None) -> tuple[str, float]:
    if not left and not right:
        return "not_specified", 1.0
    if left and not right:
        return "missing_in_b", 0.0
    if right and not left:
        return "added_in_b", 0.0
    left_norm = _norm_value(left)
    right_norm = _norm_value(right)
    left_numbers = re.findall(r"\d+(?:\.\d+)?", left_norm)
    right_numbers = re.findall(r"\d+(?:\.\d+)?", right_norm)
    if left_numbers != right_numbers and (left_numbers or right_numbers):
        score = SequenceMatcher(None, left_norm, right_norm).ratio()
        return "different", score
    score = max(
        SequenceMatcher(None, left_norm, right_norm).ratio(),
        fuzz.token_set_ratio(left_norm, right_norm) / 100.0,
    )
    return ("same" if score >= 0.9 else "different"), score


def compare_mold_quotes(left: MoldQuote, right: MoldQuote) -> dict:
    part_rows = []
    difference_count = 0
    for left_part, right_part, confidence in match_mold_parts(left.parts, right.parts):
        fields = []
        for key, label in TECHNICAL_FIELDS:
            left_value = getattr(left_part, key, None) if left_part else None
            right_value = getattr(right_part, key, None) if right_part else None
            status, similarity = _compare_value(left_value, right_value)
            if status in {"different", "missing_in_b", "added_in_b"}:
                difference_count += 1
            fields.append(
                {
                    "key": key,
                    "label": label,
                    "left": left_value,
                    "right": right_value,
                    "status": status,
                    "similarity": round(similarity, 3),
                }
            )
        left_price = left_part.price if left_part else 0.0
        right_price = right_part.price if right_part else 0.0
        delta = round(right_price - left_price, 2)
        pct = round((delta / left_price) * 100, 2) if left_price and right_price else None
        part_rows.append(
            {
                "name": (left_part or right_part).name,
                "left_name": left_part.name if left_part else None,
                "right_name": right_part.name if right_part else None,
                "match_confidence": round(confidence, 3),
                "status": "matched" if left_part and right_part else ("missing_in_b" if left_part else "added_in_b"),
                "fields": fields,
                "price": {
                    "left": left_price,
                    "right": right_price,
                    "difference": delta,
                    "percent": pct,
                },
            }
        )
    term_rows = []
    for key, label in (
        ("payment_terms", "Payment terms"),
        ("delivery_terms", "Delivery terms"),
        ("warranty", "Warranty"),
        ("validity", "Quote validity"),
        ("currency", "Currency"),
    ):
        left_value = getattr(left, key)
        right_value = getattr(right, key)
        status, similarity = _compare_value(left_value, right_value)
        term_rows.append(
            {
                "key": key,
                "label": label,
                "left": left_value,
                "right": right_value,
                "status": status,
                "similarity": round(similarity, 3),
            }
        )
    tryout_delta = round(right.tryout_cost - left.tryout_cost, 2)
    tryout_pct = round((tryout_delta / left.tryout_cost) * 100, 2) if left.tryout_cost else None
    return {
        "detected": bool(left.parts or right.parts),
        "left": left.to_dict(),
        "right": right.to_dict(),
        "parts": part_rows,
        "difference_count": difference_count,
        "tryouts": {
            "left": left.tryout_cost,
            "right": right.tryout_cost,
            "difference": tryout_delta,
            "percent": tryout_pct,
        },
        "terms": term_rows,
    }
