"""Commercial comparison, function-scope compare, and savings detection."""

from __future__ import annotations

from quotes.catalog import FUNCTION_LABELS, lookup_equipment
from quotes.db import Equipment, LineItem, session
from quotes.match import ItemMatch
from quotes.parse import ParsedQuote, QuoteItem
from sqlalchemy import select


def _price(item: QuoteItem | None) -> float:
    if item is None:
        return 0.0
    return float(item.ext_price or (item.unit_price * (item.qty or 1)))


def _delta_payload(left: QuoteItem | None, right: QuoteItem | None, confidence: float, matched: bool, kind: str = "unmatched") -> dict:
    lp = _price(left)
    rp = _price(right)
    delta = round(rp - lp, 2) if left and right else round(rp - lp, 2)
    pct = None
    if left and right and lp:
        pct = round((delta / lp) * 100, 2)
    cheaper = None
    if left and right:
        if rp < lp:
            cheaper = "B"
        elif rp > lp:
            cheaper = "A"
        else:
            cheaper = "tie"
    return {
        "match": matched,
        "confidence": round(float(confidence), 3),
        "kind": kind,
        "left": left.to_dict() if left else None,
        "right": right.to_dict() if right else None,
        "price_delta": delta,
        "percent": pct,
        "cheaper": cheaper,
    }


def commercial_rows(matches: list[ItemMatch]) -> tuple[list[dict], list[dict], list[dict]]:
    paired = []
    missing = []
    added = []
    for row in matches:
        if row.match and row.left and row.right:
            paired.append(_delta_payload(row.left, row.right, row.confidence, True, row.kind))
        elif row.left and not row.right:
            missing.append(_delta_payload(row.left, None, 0, False, "unmatched"))
        elif row.right and not row.left:
            added.append(_delta_payload(None, row.right, 0, False, "unmatched"))
    return paired, missing, added


def totals(left: ParsedQuote, right: ParsedQuote) -> dict:
    a = round(left.total or sum(_price(i) for i in left.items), 2)
    b = round(right.total or sum(_price(i) for i in right.items), 2)
    delta = round(b - a, 2)
    pct = round((delta / a) * 100, 2) if a else 0.0
    return {"left": a, "right": b, "difference": delta, "percent": pct}


def function_compare(left: ParsedQuote, right: ParsedQuote) -> dict:
    def by_function(quote: ParsedQuote) -> dict[str, list[QuoteItem]]:
        grouped: dict[str, list[QuoteItem]] = {}
        for item in quote.items:
            spec = lookup_equipment(item.description)
            fn = (item.function or (spec.function if spec else None) or "unclassified").lower()
            grouped.setdefault(fn, []).append(item)
        return grouped

    left_fn = by_function(left)
    right_fn = by_function(right)
    shared = sorted(set(left_fn) & set(right_fn))
    only_left = sorted(set(left_fn) - set(right_fn))
    only_right = sorted(set(right_fn) - set(left_fn))
    notes = []
    for fn in shared:
        left_sizes = [i.size for i in left_fn[fn] if i.size]
        right_sizes = [i.size for i in right_fn[fn] if i.size]
        if left_sizes and right_sizes and max(left_sizes) != max(right_sizes):
            label = FUNCTION_LABELS.get(fn, fn)
            if max(right_sizes) > max(left_sizes):
                notes.append(f"larger {label} in Quote B")
            else:
                notes.append(f"larger {label} in Quote A")
    return {
        "shared": [FUNCTION_LABELS.get(fn, fn) for fn in shared],
        "only_left": [FUNCTION_LABELS.get(fn, fn) for fn in only_left],
        "only_right": [FUNCTION_LABELS.get(fn, fn) for fn in only_right],
        "notes": notes,
        "mode": "function",
    }


def savings_alerts(right: ParsedQuote) -> list[dict]:
    alerts = []
    db = session()
    try:
        for item in right.items:
            sku = item.sku or (lookup_equipment(item.description).sku if lookup_equipment(item.description) else None)
            if not sku:
                continue
            eq = db.scalar(select(Equipment).where(Equipment.sku == sku))
            if eq is None:
                continue
            previous = db.scalars(
                select(LineItem)
                .where(LineItem.equipment_id == eq.id)
                .where(LineItem.ext_price > 0)
                .order_by(LineItem.id.desc())
            ).first()
            current = _price(item)
            if previous is None or not previous.ext_price or not current:
                continue
            if abs(current - previous.ext_price) < 1:
                continue
            delta = round(current - previous.ext_price, 2)
            pct = round((delta / previous.ext_price) * 100, 2)
            reasons = ["inflation"]
            if item.function in {"controls", "options"}:
                reasons.append("upgraded controls")
            reasons.append("added options")
            alerts.append(
                {
                    "sku": sku,
                    "description": item.description,
                    "previous_price": previous.ext_price,
                    "current_price": current,
                    "increase": delta,
                    "increase_pct": pct,
                    "reasons": reasons,
                }
            )
    finally:
        db.close()
    return alerts
