from __future__ import annotations

from office.pdf import PdfError, compare_pdf_bytes, diff_sentences, extract_pdf, summarize, write_text_pdf

LEFT_TEXT = (
    "The office opens at 9 AM. Staff must badge in at the lobby. Lunch is served at noon. "
    "Visitors sign the front desk log."
)
RIGHT_TEXT = (
    "The office opens at 10 AM. Staff must badge in at the lobby. Remote work is allowed on Friday. "
    "Visitors sign the front desk log."
)


def test_extract_pdf_reads_sentences():
    doc = extract_pdf(write_text_pdf(LEFT_TEXT), "policy.pdf")
    assert doc.filename == "policy.pdf"
    assert doc.page_count == 1
    assert "office opens" in doc.text.lower()
    assert doc.words > 10


def test_extract_rejects_empty_and_non_pdf():
    try:
        extract_pdf(b"")
        assert False
    except PdfError:
        pass
    try:
        extract_pdf(b"not a pdf")
        assert False
    except PdfError:
        pass


def test_summarize_keeps_important_sentences():
    bullets = summarize(LEFT_TEXT, max_bullets=3)
    assert bullets
    joined = " ".join(bullets).lower()
    assert "office" in joined or "staff" in joined or "lunch" in joined


def test_diff_sentences_finds_unique_and_changed():
    only_left, only_right, changes = diff_sentences(LEFT_TEXT, RIGHT_TEXT)
    left_blob = " ".join(only_left).lower()
    right_blob = " ".join(only_right).lower()
    change_blob = " ".join(f"{c['left']} {c['right']}" for c in changes).lower()
    assert "lunch" in left_blob
    assert "remote work" in right_blob
    assert "9 am" in change_blob and "10 am" in change_blob
    assert not any("badge in" in item.lower() for item in only_left + only_right)


def test_compare_pdf_bytes_reports_both_sides():
    result = compare_pdf_bytes(write_text_pdf(LEFT_TEXT), write_text_pdf(RIGHT_TEXT), "a.pdf", "b.pdf")
    payload = result.to_dict()
    assert payload["backend"] == "local"
    assert payload["left"]["filename"] == "a.pdf"
    assert payload["right"]["filename"] == "b.pdf"
    assert payload["similarity"] < 1
    assert payload["left"]["summary"]
    assert payload["right"]["summary"]
    assert any("lunch" in item.lower() for item in payload["only_in_left"])
    assert any("remote" in item.lower() for item in payload["only_in_right"])


def test_identical_pdfs_have_no_diff():
    data = write_text_pdf(LEFT_TEXT)
    result = compare_pdf_bytes(data, data, "same.pdf", "copy.pdf")
    assert result.similarity > 0.99
    assert result.only_in_left == []
    assert result.only_in_right == []
    assert result.changes == []
