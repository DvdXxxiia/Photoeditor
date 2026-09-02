"""Procurement-style summary and chat over a stored comparison."""

from __future__ import annotations

import json
import os
import re

from quotes.parse import ParsedQuote


def _money(value: float) -> str:
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,.0f}" if abs(value) >= 100 else f"{sign}${abs(value):,.2f}"


def local_summary(left: ParsedQuote, right: ParsedQuote, payload: dict) -> dict:
    totals = payload.get("totals") or {}
    pct = abs(float(totals.get("percent") or 0))
    cheaper = "B" if (totals.get("difference") or 0) < 0 else "A"
    other = "A" if cheaper == "B" else "B"
    vendor_b = right.vendor or "Vendor B"
    vendor_a = left.vendor or "Vendor A"
    cheaper_name = vendor_b if cheaper == "B" else vendor_a
    headline = f"{cheaper_name} is {pct:.1f}% {'lower' if (totals.get('difference') or 0) < 0 or cheaper == 'B' else 'higher'} cost."
    if (totals.get("difference") or 0) == 0:
        headline = "The two quotes have the same total."
    elif (totals.get("difference") or 0) < 0:
        headline = f"{vendor_b} is {pct:.1f}% lower cost."
    else:
        headline = f"{vendor_a} is {pct:.1f}% lower cost."

    both = []
    for row in payload.get("matches") or []:
        item = row.get("left") or row.get("right") or {}
        label = item.get("sku") or item.get("function") or item.get("description")
        if label:
            both.append(str(label))
    left_includes = [row["left"]["description"] for row in payload.get("missing_in_right") or [] if row.get("left")]
    right_includes = [row["right"]["description"] for row in payload.get("added_in_right") or [] if row.get("right")]
    recommendation = (
        f"{cheaper_name} is lower cost but {vendor_a if cheaper == 'B' else vendor_b} offers higher scope."
        if left_includes or right_includes
        else f"{cheaper_name} is the lower-cost offer on comparable scope."
    )
    return {
        "headline": headline,
        "both_quoted": both[:12],
        "left_includes": left_includes,
        "right_includes": right_includes,
        "right_excludes": left_includes,
        "recommendation": recommendation,
        "backend": "local",
    }


def llm_summary(left: ParsedQuote, right: ParsedQuote, payload: dict) -> dict | None:
    if not os.environ.get("OPENAI_API_KEY", "").strip():
        return None
    if os.environ.get("PHOTOEDITOR_DISABLE_VLM", "").strip() in {"1", "true", "yes"}:
        return None
    body = {
        "model": os.environ.get("PHOTOEDITOR_OPENAI_MODEL", "gpt-4o"),
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": "You are a plastics-processing procurement analyst. Return JSON only.",
            },
            {
                "role": "user",
                "content": (
                    "Write a procurement summary JSON with keys headline, both_quoted (array), "
                    "left_includes, right_includes, right_excludes, recommendation. "
                    "Be factual from this comparison:\n"
                    + json.dumps(
                        {
                            "left": left.to_dict(),
                            "right": right.to_dict(),
                            "totals": payload.get("totals"),
                            "matches": payload.get("matches"),
                            "missing_in_right": payload.get("missing_in_right"),
                            "added_in_right": payload.get("added_in_right"),
                            "functions": payload.get("functions"),
                        }
                    )[:14000]
                ),
            },
        ],
    }
    try:
        import httpx

        response = httpx.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=60.0,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        match = re.search(r"\{.*\}", content, re.S)
        data = json.loads(match.group(0) if match else content)
        data["backend"] = "openai"
        return data
    except Exception:
        return None


def answer_question(question: str, payload: dict) -> str:
    q = (question or "").strip()
    if not q:
        return "Ask why a quote is cheaper, what is missing, or how the equipment functions compare."
    if not os.environ.get("PHOTOEDITOR_DISABLE_VLM", "").strip() in {"1", "true", "yes"} and os.environ.get("OPENAI_API_KEY"):
        llm = _llm_answer(q, payload)
        if llm:
            return llm
    return _local_answer(q, payload)


def _llm_answer(question: str, payload: dict) -> str | None:
    try:
        import httpx

        response = httpx.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}",
                "Content-Type": "application/json",
            },
            json={
                "model": os.environ.get("PHOTOEDITOR_OPENAI_MODEL", "gpt-4o"),
                "temperature": 0,
                "messages": [
                    {
                        "role": "system",
                        "content": "You are a procurement assistant. Answer only from the quote comparison JSON.",
                    },
                    {
                        "role": "user",
                        "content": question + "\n\n" + json.dumps(payload)[:14000],
                    },
                ],
            },
            timeout=45.0,
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        return None


def _local_answer(question: str, payload: dict) -> str:
    q = question.lower()
    totals = payload.get("totals") or {}
    missing = [row["left"]["description"] for row in payload.get("missing_in_right") or [] if row.get("left")]
    added = [row["right"]["description"] for row in payload.get("added_in_right") or [] if row.get("right")]
    missing_value = sum(row.get("left", {}).get("ext_price") or 0 for row in payload.get("missing_in_right") or [])
    if "cheaper" in q or "why" in q:
        bits = []
        if (totals.get("difference") or 0) < 0:
            bits.append(f"Quote B is {_money(totals['difference'])} lower overall ({totals.get('percent')}%).")
        elif (totals.get("difference") or 0) > 0:
            bits.append(f"Quote A is {_money(-totals['difference'])} lower overall.")
        if missing:
            bits.append("Quote B excludes: " + ", ".join(missing) + ".")
            if missing_value:
                bits.append(f"Estimated excluded value: {_money(missing_value)}.")
        if added:
            bits.append("Quote B adds: " + ", ".join(added) + ".")
        for row in payload.get("matches") or []:
            if row.get("match") and row.get("price_delta"):
                left = (row.get("left") or {}).get("description")
                bits.append(f"{left}: {row['price_delta']:+,.0f} on Quote B ({row.get('percent')}%).")
        return " ".join(bits) or "The quotes look commercially similar."
    if "missing" in q or "exclude" in q:
        return "Quote B is missing: " + (", ".join(missing) or "nothing obvious") + "."
    if "function" in q or "scope" in q or "drying" in q:
        fn = payload.get("functions") or {}
        notes = "; ".join(fn.get("notes") or []) or "Scope functions are listed in the dashboard."
        shared = ", ".join(fn.get("shared") or []) or "none"
        return f"Both systems provide: {shared}. {notes}"
    if "save" in q or "increase" in q or "inflation" in q:
        alerts = payload.get("savings") or []
        if not alerts:
            return "No historical price increase was stored for these SKUs yet."
        row = alerts[0]
        return (
            f"{row['sku']} moved from ${row['previous_price']:,.0f} to ${row['current_price']:,.0f} "
            f"({row['increase_pct']}% ). Possible reasons: {', '.join(row.get('reasons') or [])}."
        )
    summary = payload.get("summary") or {}
    return summary.get("recommendation") or summary.get("headline") or "Compare the matched line items in the dashboard."
