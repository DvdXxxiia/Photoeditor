from __future__ import annotations

from office.pdf import write_text_pdf
from quotes.ingest import IngestedDocument
from quotes.molding import compare_mold_quotes, parse_mold_quote
from quotes.samples import MOLD_QUOTE_A, MOLD_QUOTE_B
from quotes.service import compare_quote_pdfs


def test_parse_injection_molding_parts_and_terms():
    quote = parse_mold_quote(MOLD_QUOTE_A)
    assert quote.vendor == "Alpha Tooling"
    assert len(quote.parts) == 2
    door = quote.parts[0]
    assert door.name == "Door Panel"
    assert door.part_number == "DP-100"
    assert door.configuration == "1+1 cavity, P20 steel"
    assert door.insulation == "12 mm insulation plate"
    assert door.demolding == "16 ejector pins"
    assert door.inserts == "2 interchangeable inserts"
    assert door.compression == "Hydraulic compression"
    assert door.sliders == "2 hydraulic sliders"
    assert door.gating == "4-drop hot runner"
    assert door.pur == "PUR foaming provision included"
    assert door.pur_sealing == "Silicone sealing groove"
    assert door.surface_finishing == "VDI 27 texture"
    assert door.fim == "Film insert molding ready"
    assert door.tool_temperature == "80 C"
    assert door.price == 120000
    assert door.options == "Spare insert set included"
    assert door.lead_time == "18 weeks"
    assert quote.tryout_cost == 14000
    assert "30% order" in (quote.payment_terms or "")
    assert quote.delivery_terms == "DDP plant"
    assert quote.warranty == "2 years or 1 million shots"
    assert quote.validity == "60 days"


def test_parts_match_by_part_number_and_compare_every_field():
    left = parse_mold_quote(MOLD_QUOTE_A)
    right = parse_mold_quote(MOLD_QUOTE_B)
    result = compare_mold_quotes(left, right)
    assert result["detected"] is True
    assert len(result["parts"]) == 2
    door = next(row for row in result["parts"] if row["name"] == "Door Panel")
    assert door["match_confidence"] == 1.0
    fields = {row["key"]: row for row in door["fields"]}
    expected = {
        "configuration",
        "insulation",
        "demolding",
        "inserts",
        "compression",
        "sliders",
        "gating",
        "pur",
        "pur_sealing",
        "surface_finishing",
        "fim",
        "tool_temperature",
        "options",
        "lead_time",
    }
    assert set(fields) == expected
    assert fields["configuration"]["status"] == "same"
    assert fields["insulation"]["status"] == "different"
    assert fields["pur_sealing"]["status"] == "different"
    assert fields["tool_temperature"]["status"] == "different"
    assert door["price"]["difference"] == -4000


def test_tryout_cost_and_vendor_terms_are_separate():
    result = compare_mold_quotes(
        parse_mold_quote(MOLD_QUOTE_A),
        parse_mold_quote(MOLD_QUOTE_B),
    )
    assert result["tryouts"]["left"] == 14000
    assert result["tryouts"]["right"] == 18500
    assert result["tryouts"]["difference"] == 4500
    terms = {row["key"]: row for row in result["terms"]}
    assert terms["payment_terms"]["status"] == "different"
    assert terms["delivery_terms"]["left"] == "DDP plant"
    assert terms["delivery_terms"]["right"] == "EXW toolmaker"
    assert terms["warranty"]["status"] == "different"


def test_service_returns_molding_dashboard_and_totals():
    payload = compare_quote_pdfs(
        write_text_pdf(MOLD_QUOTE_A),
        write_text_pdf(MOLD_QUOTE_B),
        "Alpha.pdf",
        "Beta.pdf",
        "Interior trim tooling",
    )
    molding = payload["molding"]
    assert molding["detected"] is True
    assert payload["left"]["vendor"] == "Alpha Tooling"
    assert payload["right"]["vendor"] == "Beta Molds"
    assert molding["left"]["tooling_total"] == 202500
    assert molding["right"]["tooling_total"] == 195000
    assert molding["left"]["total_with_tryout"] == 216500
    assert molding["right"]["total_with_tryout"] == 213500
    assert "Recommended vendor" in payload["summary"]["headline"]
    assert payload["sourcing"]["detected"] is True


def test_table_form_can_extract_molding_fields():
    table = [
        ["Part", "Configuration", "Insulation", "Gating", "Price", "Lead Time"],
        ["Door Panel", "1+1 cavity", "12 mm plate", "4-drop hot runner", "$120,000", "18 weeks"],
    ]
    quote = parse_mold_quote("", [table])
    assert len(quote.parts) == 1
    part = quote.parts[0]
    assert part.configuration == "1+1 cavity"
    assert part.insulation == "12 mm plate"
    assert part.gating == "4-drop hot runner"
    assert part.price == 120000
    assert part.lead_time == "18 weeks"
