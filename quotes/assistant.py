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
                        "content": (
                            "You are a senior injection molding tooling sourcing engineer. "
                            "Answer only from the normalized per-part matrix. Do not discuss "
                            "filenames, image counts, or document metadata. Cite page-numbered "
                            "source evidence when it is available and state Not specified for gaps."
                        ),
                    },
                    {
                        "role": "user",
                        "content": question + "\n\n" + json.dumps(payload.get("sourcing") or payload)[:18000],
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
    sourcing = payload.get("sourcing") or {}
    if sourcing.get("detected"):
        if "tryout" in q or "trial" in q:
            rows = [
                row for row in sourcing.get("tryouts") or []
                if row.get("left") is not None or row.get("right") is not None
            ]
            return "Tryout comparison: " + "; ".join(_sourcing_row_text(row) for row in rows) + "."
        if any(word in q for word in ("term", "payment", "warranty", "ownership", "maintenance", "storage", "penalt", "delivery")):
            rows = [
                row for row in sourcing.get("terms") or []
                if row.get("status") not in {"same", "not_specified"}
            ]
            return "Commercial terms: " + ("; ".join(_sourcing_row_text(row) for row in rows) or "no differences detected") + "."
        if any(word in q for word in ("scope", "cavit", "steel", "runner", "insulation", "demold", "insert", "compression", "slider", "gating", "pur", "surface", "fim", "temperature", "validation", "part")):
            rows = []
            for part in sourcing.get("parts") or []:
                for row in part.get("technical") or []:
                    if row.get("status") not in {"same", "not_specified"}:
                        rows.append(f"{part.get('part')}: {_sourcing_row_text(row)}")
            return "Technical differences: " + ("; ".join(rows[:12]) or "none detected") + "."
        summary = sourcing.get("summary") or {}
        return (
            f"Recommended vendor: {summary.get('recommended_vendor', 'Not specified')}. "
            f"Potential risks: {', '.join(summary.get('potential_risks') or []) or 'none identified'}."
        )
    molding = payload.get("molding") or {}
    if molding.get("detected"):
        if "tryout" in q or "trial" in q:
            tryouts = molding.get("tryouts") or {}
            return (
                f"Tryout cost is {_money(tryouts.get('left') or 0)} for Vendor A and "
                f"{_money(tryouts.get('right') or 0)} for Vendor B. "
                f"Vendor B's difference is {_money(tryouts.get('difference') or 0)}."
            )
        if "term" in q or "payment" in q or "warranty" in q or "delivery" in q:
            differences = []
            for row in molding.get("terms") or []:
                if row.get("status") not in {"same", "not_specified"}:
                    differences.append(
                        f"{row.get('label')}: A = {row.get('left') or 'not specified'}; "
                        f"B = {row.get('right') or 'not specified'}"
                    )
            return "Vendor term differences: " + ("; ".join(differences) if differences else "none detected") + "."
        field_names = {
            "configuration",
            "insulation",
            "demolding",
            "inserts",
            "compression",
            "sliders",
            "gating",
            "pur",
            "sealing",
            "surface",
            "finishing",
            "fim",
            "temperature",
            "option",
            "lead time",
        }
        if any(name in q for name in field_names) or "part" in q or "technical" in q:
            differences = []
            for part in molding.get("parts") or []:
                for row in part.get("fields") or []:
                    if row.get("status") in {"different", "missing_in_b", "added_in_b"}:
                        differences.append(
                            f"{part.get('name')} — {row.get('label')}: "
                            f"A = {row.get('left') or 'not specified'}; B = {row.get('right') or 'not specified'}"
                        )
            return "Technical differences: " + ("; ".join(differences[:12]) if differences else "none detected") + "."
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


def _sourcing_row_text(row: dict) -> str:
    def value(side: str) -> str:
        raw = row.get(side)
        text = "Not specified" if raw in {None, ""} else str(raw)
        evidence = row.get(f"{side}_evidence") or {}
        if evidence.get("text"):
            text += f' (page {evidence.get("page", 1)}: “{evidence["text"]}”)'
        return text

    return f"{row.get('label')}: A = {value('left')}; B = {value('right')}"
