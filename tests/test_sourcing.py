from __future__ import annotations

import json

from office.pdf import write_text_pdf
from quotes.ingest import IngestedDocument
from quotes.samples import MOLD_QUOTE_A, MOLD_QUOTE_B, TITLE_QUOTE_A, TITLE_QUOTE_B
from quotes.service import compare_quote_pdfs
from quotes.sourcing import (
    ANALYST_SYSTEM_PROMPT,
    TECHNICAL_FIELDS,
    build_normalized_comparison,
    local_extract,
)


def _doc(text: str, page: int) -> IngestedDocument:
    return IngestedDocument(
        filename="ignored.pdf",
        page_count=page,
        text=text,
        images=[{"page": 1}],
        blocks=[{"type": "page_text", "page": page, "text": text}],
    )


def test_analyst_prompt_forbids_metadata_comparison():
    prompt = ANALYST_SYSTEM_PROMPT.lower()
    assert "senior injection molding tooling sourcing engineer" in prompt
    assert "not to compare filenames" in prompt
    assert "normalized matrix" in prompt
    assert "exact source text" in prompt
    assert "page number" in prompt


def test_extracts_full_part_scope_with_page_evidence():
    quote = local_extract(_doc(MOLD_QUOTE_A, 3))
    assert quote["vendor"] == "Alpha Tooling"
    assert len(quote["parts"]) == 2
    door = next(part for part in quote["parts"] if part["name"] == "Door Panel")
    expected = {key for key, _ in TECHNICAL_FIELDS}
    assert set(door["technical"]) == expected
    assert door["technical"]["cavities"]["value"] == "2"
    assert door["technical"]["steel_grades"]["value"] == "P20 mold plates / H13 inserts"
    assert door["technical"]["hot_runner"]["value"] == "Mold-Masters, 4 drops"
    evidence = door["technical"]["hot_runner"]["evidence"]
    assert evidence["page"] == 3
    assert evidence["text"] == "Hot Runner: Mold-Masters, 4 drops"
    assert door["technical"]["validation_scope"]["value"].startswith("Moldflow")
    assert door["technical"]["tool_warranty"]["value"] == "1,000,000 shots"


def test_normalized_part_matrix_explains_difference_scope_and_impact():
    matrix = build_normalized_comparison(
        local_extract(_doc(MOLD_QUOTE_A, 2)),
        local_extract(_doc(MOLD_QUOTE_B, 5)),
    )
    assert matrix["detected"] is True
    assert len(matrix["parts"]) == 2
    door = next(part for part in matrix["parts"] if part["part"] == "Door Panel")
    rows = {row["key"]: row for row in door["technical"]}
    cavities = rows["cavities"]
    assert cavities["left"] == "2"
    assert cavities["right"] == "4"
    assert cavities["higher_scope"] == "Vendor B (higher output)"
    assert cavities["commercial_impact"] == "Medium"
    assert "Vendor A specifies" in cavities["difference"]
    assert cavities["left_evidence"]["page"] == 2
    assert cavities["right_evidence"]["page"] == 5
    assert rows["steel_grades"]["status"] == "different"
    assert rows["mold_base"]["status"] == "different"
    assert rows["hot_runner"]["status"] == "different"
    assert rows["validation_scope"]["higher_scope"] == "Vendor A"


def test_cost_tryout_and_terms_matrices_are_separate():
    matrix = build_normalized_comparison(
        local_extract(_doc(MOLD_QUOTE_A, 1)),
        local_extract(_doc(MOLD_QUOTE_B, 1)),
    )
    costs = {row["key"]: row for row in matrix["costs"]}
    assert costs["tool_subtotal"]["left"] == 202500
    assert costs["tool_subtotal"]["right"] == 195000
    assert costs["total_quoted_value"]["difference_amount"] == 5000

    tryouts = {row["key"]: row for row in matrix["tryouts"]}
    assert tryouts["included_tryouts"]["left"] == "3"
    assert tryouts["included_tryouts"]["right"] == "2"
    assert tryouts["included_tryouts"]["higher_scope"] == "Vendor A"
    assert tryouts["t2_cost"]["higher_scope"] == "Vendor A"
    assert tryouts["total_tryout_cost"]["left"] == 14000
    assert tryouts["total_tryout_cost"]["right"] == 18500

    terms = {row["key"]: row for row in matrix["terms"]}
    assert terms["payment_terms"]["status"] == "different"
    assert terms["tool_ownership"]["status"] == "different"
    assert terms["maintenance_responsibility"]["higher_scope"] == "Vendor A"
    assert terms["tool_storage"]["higher_scope"] == "Vendor A"
    assert terms["change_management"]["status"] == "different"
    assert terms["penalties_liabilities"]["higher_scope"] == "Vendor A"


def test_summary_is_generated_after_matrix_and_has_required_decisions():
    matrix = build_normalized_comparison(
        local_extract(_doc(MOLD_QUOTE_A, 1)),
        local_extract(_doc(MOLD_QUOTE_B, 1)),
    )
    summary = matrix["summary"]
    assert summary["lowest_tool_cost"] == "Vendor B"
    assert summary["lowest_tryout_cost"] == "Vendor A"
    assert summary["best_technical_scope"] == "Vendor A"
    assert summary["best_commercial_terms"] == "Vendor A"
    assert isinstance(summary["missing_from_vendor_a"], list)
    assert isinstance(summary["missing_from_vendor_b"], list)
    assert summary["potential_risks"]
    assert summary["recommended_vendor"].startswith("Vendor A")


def test_service_does_not_compare_filename_or_image_count():
    payload = compare_quote_pdfs(
        write_text_pdf(MOLD_QUOTE_A),
        write_text_pdf(MOLD_QUOTE_B),
        "arbitrary-one.pdf",
        "unrelated-name.pdf",
        "VU_A5_26 tooling",
    )
    sourcing = payload["sourcing"]
    serialized = json.dumps(sourcing).lower()
    assert "arbitrary-one.pdf" not in serialized
    assert "unrelated-name.pdf" not in serialized
    assert "image count" not in serialized
    assert "images" not in sourcing
    assert sourcing["parts"][0]["technical"]


def test_title_dates_are_not_treated_as_prices_or_star_skus():
    payload = compare_quote_pdfs(
        write_text_pdf(TITLE_QUOTE_A),
        write_text_pdf(TITLE_QUOTE_B),
        "FSU VU_A6_26 August 25th, 2026.pdf",
        "FSU VU_A6_26 September 1st, 2026.pdf",
        "FSU VU_A6_26",
    )
    assert payload["sourcing"]["detected"] is True
    assert payload["totals"]["left"] == 198500
    assert payload["totals"]["right"] == 190000
    assert payload["left"]["vendor"] == "Northwind Molds"
    assert payload["right"]["vendor"] == "Southshore Tools"
    assert payload["left"]["vendor"] != "Star"
    descriptions = " ".join(
        str((row.get("left") or {}).get("description") or "")
        + " "
        + str((row.get("right") or {}).get("description") or "")
        for row in payload.get("matches") or []
    ).lower()
    assert "august 25th" not in descriptions
    assert "september 1st" not in descriptions
    assert "star is the lower-cost" not in payload["summary"]["recommendation"].lower()
    assert payload["summary"]["backend"] == "normalized-sourcing-matrix"
    part = payload["sourcing"]["parts"][0]
    assert part["part"] == "Console Bezel"
    rows = {row["key"]: row for row in part["technical"]}
    assert rows["cavities"]["left"] == "1"
    assert rows["cavities"]["right"] == "2"
    assert rows["hot_runner"]["left"] == "Mold-Masters 8 drops"
    assert rows["hot_runner"]["right"] == "Yudo 4 drops"


def test_extracts_unlabeled_and_table_fields_instead_of_filename():
    quote = local_extract(
        IngestedDocument(
            filename="FSU VU_A6_26 August 25th, 2026.pdf",
            page_count=1,
            text=TITLE_QUOTE_A,
            tables=[
                [
                    ["Item", "Specification"],
                    ["Cavities", "1"],
                    ["Steel grades", "1.2343"],
                    ["Hot runner", "Mold-Masters 8 drops"],
                ]
            ],
            blocks=[
                {"type": "page_text", "page": 1, "text": TITLE_QUOTE_A},
                {
                    "type": "table",
                    "page": 1,
                    "rows": [
                        ["Item", "Specification"],
                        ["Insulation", "12 mm plates"],
                    ],
                    "text": "Item | Specification\nInsulation | 12 mm plates",
                },
            ],
        )
    )
    assert quote["vendor"] == "Northwind Molds"
    assert quote["parts"][0]["name"] == "Console Bezel"
    assert quote["parts"][0]["technical"]["cavities"]["value"] == "1"
    assert quote["parts"][0]["technical"]["insulation"]["value"] == "12 mm plates"
    assert quote["costs"]["total_quoted_value"]["value"] == 198500
    serialized = json.dumps(quote).lower()
    assert "august 25th, 2026.pdf" not in serialized
    assert quote["costs"]["total_quoted_value"]["value"] != 2026


def test_date_only_cover_sheets_do_not_invent_a_2026_dollar_total():
    payload = compare_quote_pdfs(
        write_text_pdf("FSU VU_A6_26 August 25th, 2026\nStart-up included\n"),
        write_text_pdf("FSU VU_A6_26 September 1st, 2026\nStart-up included\n"),
        "FSU VU_A6_26 August 25th, 2026.pdf",
        "FSU VU_A6_26 September 1st, 2026.pdf",
    )
    assert payload["totals"]["left"] != 2026
    assert payload["totals"]["right"] != 2026
    assert payload["left"].get("vendor") != "Star"
    assert payload["summary"]["backend"] == "normalized-sourcing-matrix"
    assert payload["sourcing"]["detected"] is True
    assert payload["sourcing"]["parts"]
