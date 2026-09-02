from __future__ import annotations

from quotes.assistant import answer_question, local_summary
from quotes.compare import commercial_rows, function_compare, totals
from quotes.ingest import IngestedDocument
from quotes.match import match_items
from quotes.parse import parse_quote
from quotes.samples import QUOTE_A, QUOTE_B, QUOTE_B_LARGER_DRYER
from quotes.service import compare_quote_pdfs
from office.pdf import write_text_pdf


def test_parse_quote_json_shape():
    parsed = parse_quote(IngestedDocument("Quote_A.pdf", 1, QUOTE_A))
    data = parsed.to_dict()
    assert data["vendor"] == "Piovan"
    assert data["quote_number"] == "Q12345"
    assert data["date"] == "2026-09-01"
    skus = {item["sku"] for item in data["items"]}
    assert "GMP180" in skus
    assert "PTUN2500" in skus
    dryer = next(item for item in data["items"] if item["sku"] == "GMP180")
    assert dryer["unit_price"] == 73061


def test_semantic_match_gmp180_despite_wording():
    left = parse_quote(IngestedDocument("a.pdf", 1, QUOTE_A)).items
    right = parse_quote(IngestedDocument("b.pdf", 1, QUOTE_B)).items
    matches = match_items(left, right)
    dryer = next(
        row
        for row in matches
        if row.match and row.left and row.left.sku == "GMP180"
    )
    assert dryer.right is not None
    assert dryer.confidence >= 0.9
    assert dryer.kind == "same_item"
    assert dryer.to_dict()["match"] is True


def test_function_compare_understands_capacity_shift():
    left = parse_quote(IngestedDocument("a.pdf", 1, QUOTE_A))
    right = parse_quote(IngestedDocument("b.pdf", 1, QUOTE_B_LARGER_DRYER))
    result = function_compare(left, right)
    assert "drying" in result["shared"]
    assert "storage" in result["shared"]
    assert any("drying" in note for note in result["notes"])


def test_compare_quote_pdfs_dashboard():
    payload = compare_quote_pdfs(
        write_text_pdf(QUOTE_A),
        write_text_pdf(QUOTE_B),
        "Quote_A.pdf",
        "Quote_B.pdf",
        "Dryer package",
    )
    assert payload["left"]["vendor"] == "Piovan"
    assert payload["comparison_id"]
    totals_row = payload["totals"]
    assert totals_row["right"] < totals_row["left"]
    matched_skus = [row["left"]["sku"] for row in payload["matches"] if row.get("left")]
    assert "GMP180" in matched_skus
    missing = " ".join(row["left"]["description"] for row in payload["missing_in_right"]).lower()
    assert "vacuum receiver" in missing or "installation" in missing
    added = " ".join(row["right"]["description"] for row in payload["added_in_right"]).lower()
    assert "dew point" in added
    assert payload["drawings"]["highlights"]
    assert "lower cost" in payload["summary"]["headline"].lower() or "lower" in payload["summary"]["headline"].lower()


def test_assistant_explains_why_cheaper():
    left = parse_quote(IngestedDocument("a.pdf", 1, QUOTE_A))
    right = parse_quote(IngestedDocument("b.pdf", 1, QUOTE_B))
    matches = match_items(left.items, right.items)
    paired, missing, added = commercial_rows(matches)
    payload = {
        "totals": totals(left, right),
        "matches": paired,
        "missing_in_right": missing,
        "added_in_right": added,
        "functions": function_compare(left, right),
        "summary": local_summary(left, right, {"totals": totals(left, right), "matches": paired, "missing_in_right": missing, "added_in_right": added}),
        "savings": [],
    }
    answer = answer_question("Why is Quote B cheaper?", payload)
    assert "exclude" in answer.lower() or "installation" in answer.lower() or "lower" in answer.lower()
