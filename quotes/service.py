"""Orchestrate ingest, match, persist, and commercial comparison."""

from __future__ import annotations

import json

from sqlalchemy import select

from quotes.assistant import llm_summary, local_summary
from quotes.catalog import lookup_equipment
from quotes.compare import commercial_rows, function_compare, savings_alerts, totals
from quotes.db import Comparison, Equipment, LineItem, Project, Quote, Vendor, session
from quotes.ingest import ingest_pdf
from quotes.match import match_items
from quotes.molding import compare_mold_quotes, parse_mold_quote
from quotes.parse import ParsedQuote, parse_quote
from quotes.sourcing import build_normalized_comparison, extract_sourcing_quote


def _vendor_id(db, name: str | None) -> int | None:
    if not name:
        return None
    row = db.scalar(select(Vendor).where(Vendor.name == name))
    if row is None:
        row = Vendor(name=name)
        db.add(row)
        db.flush()
    return row.id


def _equipment_id(db, sku: str | None) -> int | None:
    if not sku:
        return None
    row = db.scalar(select(Equipment).where(Equipment.sku == sku))
    return row.id if row else None


def persist_quote(parsed: ParsedQuote, project_id: int | None) -> int:
    db = session()
    try:
        quote = Quote(
            project_id=project_id,
            vendor_id=_vendor_id(db, parsed.vendor),
            quote_number=parsed.quote_number,
            quote_date=parsed.date,
            filename=parsed.filename,
            total=parsed.total,
            raw_json=json.dumps(parsed.to_dict()),
        )
        db.add(quote)
        db.flush()
        for item in parsed.items:
            spec = lookup_equipment(item.description)
            sku = item.sku or (spec.sku if spec else None)
            db.add(
                LineItem(
                    quote_id=quote.id,
                    equipment_id=_equipment_id(db, sku),
                    description=item.description,
                    sku=sku,
                    qty=item.qty,
                    unit=item.unit,
                    unit_price=item.unit_price,
                    ext_price=item.ext_price,
                    function=item.function,
                    category=item.category,
                )
            )
        db.commit()
        return quote.id
    finally:
        db.close()


def compare_quote_pdfs(
    left_data: bytes,
    right_data: bytes,
    left_name: str = "Quote_A.pdf",
    right_name: str = "Quote_B.pdf",
    project_name: str = "Quote comparison",
) -> dict:
    left_doc = ingest_pdf(left_data, left_name)
    right_doc = ingest_pdf(right_data, right_name)
    left = parse_quote(left_doc)
    right = parse_quote(right_doc)
    left_sourcing = extract_sourcing_quote(left_doc)
    right_sourcing = extract_sourcing_quote(right_doc)
    sourcing = build_normalized_comparison(left_sourcing, right_sourcing)
    left_mold = parse_mold_quote(left_doc.text, left_doc.tables)
    right_mold = parse_mold_quote(right_doc.text, right_doc.tables)
    molding = compare_mold_quotes(left_mold, right_mold)
    if molding["detected"]:
        left.vendor = left.vendor or left_mold.vendor
        right.vendor = right.vendor or right_mold.vendor
        left.total = left_mold.tooling_total
        right.total = right_mold.tooling_total
    if sourcing["detected"]:
        left.vendor = sourcing["vendors"]["left"] or left.vendor
        right.vendor = sourcing["vendors"]["right"] or right.vendor
        source_cost_a = next(
            (row["left"] for row in sourcing["costs"] if row["key"] == "total_quoted_value"),
            None,
        )
        source_cost_b = next(
            (row["right"] for row in sourcing["costs"] if row["key"] == "total_quoted_value"),
            None,
        )
        left.total = float(source_cost_a or left.total)
        right.total = float(source_cost_b or right.total)
    matches = match_items(left.items, right.items)
    paired, missing, added = commercial_rows(matches)
    payload = {
        "left": left.to_dict(),
        "right": right.to_dict(),
        "totals": totals(left, right),
        "matches": paired,
        "missing_in_right": missing,
        "added_in_right": added,
        "functions": function_compare(left, right),
        "savings": savings_alerts(right),
        "ingest": {"left": left_doc.backend, "right": right_doc.backend},
        "molding": molding,
        "sourcing": sourcing,
    }
    if sourcing["detected"]:
        sourcing_summary = sourcing["summary"]
        summary = {
            "headline": f"Recommended vendor: {sourcing_summary['recommended_vendor']}.",
            "recommendation": (
                f"Lowest tool cost: {sourcing_summary['lowest_tool_cost']}. "
                f"Lowest tryout cost: {sourcing_summary['lowest_tryout_cost']}. "
                f"Best technical scope: {sourcing_summary['best_technical_scope']}."
            ),
            "both_quoted": [part["part"] for part in sourcing["parts"]],
            "left_includes": [],
            "right_includes": [],
            "right_excludes": sourcing_summary["missing_from_vendor_b"],
            "backend": "normalized-sourcing-matrix",
        }
    else:
        summary = llm_summary(left, right, payload) or local_summary(left, right, payload)
    if molding["detected"] and not sourcing["detected"]:
        costs_a = molding["left"]["total_with_tryout"]
        costs_b = molding["right"]["total_with_tryout"]
        delta = costs_b - costs_a
        vendor_a = left.vendor or "Vendor A"
        vendor_b = right.vendor or "Vendor B"
        if delta < 0:
            headline = f"{vendor_b} is ${abs(delta):,.0f} lower including tryouts."
        elif delta > 0:
            headline = f"{vendor_a} is ${abs(delta):,.0f} lower including tryouts."
        else:
            headline = "Both vendors have the same tooling and tryout total."
        summary.update(
            {
                "headline": headline,
                "recommendation": (
                    f"Review {molding['difference_count']} technical field difference"
                    f"{'s' if molding['difference_count'] != 1 else ''} by part before selecting the lower bid."
                ),
            }
        )
    payload["summary"] = summary

    db = session()
    try:
        project = Project(name=project_name or "Quote comparison")
        db.add(project)
        db.flush()
        project_id = project.id
        db.commit()
    finally:
        db.close()

    left_id = persist_quote(left, project_id)
    right_id = persist_quote(right, project_id)
    db = session()
    try:
        row = Comparison(
            project_id=project_id,
            quote_a_id=left_id,
            quote_b_id=right_id,
            result_json="{}",
        )
        db.add(row)
        db.flush()
        payload["comparison_id"] = row.id
        payload["project_id"] = project_id
        row.result_json = json.dumps(payload)
        db.commit()
    finally:
        db.close()
    return payload


def load_comparison(comparison_id: int) -> dict | None:
    db = session()
    try:
        row = db.get(Comparison, comparison_id)
        if row is None:
            return None
        return json.loads(row.result_json)
    finally:
        db.close()
