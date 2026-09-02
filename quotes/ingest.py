"""PDF ingestion: Azure Document Intelligence, pdfplumber, PyMuPDF, OCR fallback."""

from __future__ import annotations

import io
import logging
import os
from dataclasses import dataclass, field

from office.pdf import PdfError

logger = logging.getLogger(__name__)

MAX_PDF_BYTES = 20 * 1024 * 1024
MAX_PAGES = 100


@dataclass
class IngestedDocument:
    filename: str
    page_count: int
    text: str
    tables: list[list[list[str]]] = field(default_factory=list)
    images: list[dict] = field(default_factory=list)
    blocks: list[dict] = field(default_factory=list)
    backend: str = "local"
    ocr_used: bool = False

    def to_dict(self) -> dict:
        return {
            "filename": self.filename,
            "pages": self.page_count,
            "text": self.text,
            "tables": self.tables,
            "images": [{"page": img.get("page"), "width": img.get("width"), "height": img.get("height")} for img in self.images],
            "blocks": self.blocks[:80],
            "backend": self.backend,
            "ocr_used": self.ocr_used,
        }


def azure_configured() -> bool:
    return bool(
        os.environ.get("AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT", "").strip()
        and os.environ.get("AZURE_DOCUMENT_INTELLIGENCE_KEY", "").strip()
    )


def ingest_pdf(data: bytes, filename: str = "quote.pdf") -> IngestedDocument:
    if not data:
        raise PdfError("Empty file")
    if len(data) > MAX_PDF_BYTES:
        raise PdfError("PDF is larger than 20 MB")
    if azure_configured() and os.environ.get("PHOTOEDITOR_DISABLE_VLM", "").strip() not in {"1", "true", "yes"}:
        azure = _ingest_azure(data, filename)
        if azure is not None:
            return azure
    local = _ingest_local(data, filename)
    if len((local.text or "").strip()) < 40:
        ocr = _ingest_ocr(data, filename)
        if ocr is not None and len(ocr.text.strip()) > len(local.text.strip()):
            local.text = ocr.text
            local.ocr_used = True
            local.backend = f"{local.backend}+ocr"
    if not (local.text or "").strip() and not local.tables:
        raise PdfError("No extractable text. If this is a scan, install Tesseract or set Azure Document Intelligence.")
    return local


def _ingest_azure(data: bytes, filename: str) -> IngestedDocument | None:
    endpoint = os.environ.get("AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT", "").rstrip("/")
    key = os.environ.get("AZURE_DOCUMENT_INTELLIGENCE_KEY", "").strip()
    model = os.environ.get("AZURE_DOCUMENT_INTELLIGENCE_MODEL", "prebuilt-layout")
    try:
        import httpx

        analyze = httpx.post(
            f"{endpoint}/formrecognizer/documentModels/{model}:analyze",
            params={"api-version": "2023-07-31"},
            headers={"Ocp-Apim-Subscription-Key": key, "Content-Type": "application/pdf"},
            content=data,
            timeout=60.0,
        )
        if analyze.status_code >= 400:
            analyze = httpx.post(
                f"{endpoint}/documentintelligence/documentModels/{model}:analyze",
                params={"api-version": "2024-11-30"},
                headers={"Ocp-Apim-Subscription-Key": key, "Content-Type": "application/pdf"},
                content=data,
                timeout=60.0,
            )
        analyze.raise_for_status()
        operation = analyze.headers.get("operation-location") or analyze.headers.get("Operation-Location")
        if not operation:
            return None
        for _ in range(30):
            poll = httpx.get(operation, headers={"Ocp-Apim-Subscription-Key": key}, timeout=30.0)
            poll.raise_for_status()
            payload = poll.json()
            status = (payload.get("status") or "").lower()
            if status in {"succeeded", "failed"}:
                break
            import time

            time.sleep(1.0)
        else:
            return None
        if (payload.get("status") or "").lower() != "succeeded":
            return None
        return _azure_to_document(payload, filename)
    except Exception:
        logger.exception("Azure Document Intelligence failed; using local ingest")
        return None


def _azure_to_document(payload: dict, filename: str) -> IngestedDocument:
    result = payload.get("analyzeResult") or payload.get("analyze_result") or {}
    content = result.get("content") or ""
    tables = []
    for table in result.get("tables") or []:
        rows: dict[int, dict[int, str]] = {}
        for cell in table.get("cells") or []:
            r = int(cell.get("rowIndex", 0))
            c = int(cell.get("columnIndex", 0))
            rows.setdefault(r, {})[c] = str(cell.get("content") or "")
        grid = []
        for r in sorted(rows):
            cols = rows[r]
            width = max(cols) + 1 if cols else 0
            grid.append([cols.get(i, "") for i in range(width)])
        if grid:
            tables.append(grid)
    blocks = []
    for para in result.get("paragraphs") or []:
        regions = para.get("boundingRegions") or para.get("bounding_regions") or []
        page_number = regions[0].get("pageNumber") if regions else None
        blocks.append(
            {
                "type": "paragraph",
                "page": page_number,
                "text": para.get("content") or "",
            }
        )
    pages = result.get("pages") or []
    return IngestedDocument(
        filename=filename,
        page_count=len(pages) or 1,
        text=content,
        tables=tables,
        images=[{"page": p.get("pageNumber"), "width": p.get("width"), "height": p.get("height")} for p in pages],
        blocks=blocks,
        backend="azure-document-intelligence",
    )


def _ingest_local(data: bytes, filename: str) -> IngestedDocument:
    text_parts: list[str] = []
    tables: list[list[list[str]]] = []
    images: list[dict] = []
    blocks: list[dict] = []
    page_count = 1
    backends: list[str] = []

    try:
        import pdfplumber

        with pdfplumber.open(io.BytesIO(data)) as pdf:
            page_count = len(pdf.pages)
            for page_number, page in enumerate(pdf.pages[:MAX_PAGES], start=1):
                extracted = page.extract_text() or ""
                if extracted:
                    text_parts.append(extracted)
                    blocks.append({"type": "page_text", "page": page_number, "text": extracted})
                for table in page.extract_tables() or []:
                    cleaned = [[str(cell or "").strip() for cell in row] for row in table]
                    if any(any(cell for cell in row) for row in cleaned):
                        tables.append(cleaned)
                        blocks.append(
                            {
                                "type": "table",
                                "page": page_number,
                                "rows": cleaned,
                                "text": "\n".join(" | ".join(row) for row in cleaned),
                            }
                        )
        backends.append("pdfplumber")
    except Exception:
        logger.exception("pdfplumber ingest failed")

    try:
        import fitz

        doc = fitz.open(stream=data, filetype="pdf")
        page_count = max(page_count, doc.page_count)
        pdfplumber_had_text = bool(text_parts)
        for index, page in enumerate(doc, start=1):
            if index > MAX_PAGES:
                break
            extracted = page.get_text("text") or ""
            if extracted and not pdfplumber_had_text:
                text_parts.append(extracted)
                blocks.append({"type": "page_text", "page": index, "text": extracted})
            for img in page.get_images(full=True):
                images.append({"page": index, "xref": int(img[0]), "width": None, "height": None})
        doc.close()
        backends.append("pymupdf")
    except Exception:
        logger.exception("PyMuPDF ingest failed")

    if not text_parts:
        from office.pdf import extract_pdf

        fallback = extract_pdf(data, filename)
        text_parts.append(fallback.text)
        page_count = fallback.page_count
        backends.append("pypdf")

    text = "\n".join(part.strip() for part in text_parts if part and part.strip())
    return IngestedDocument(
        filename=filename,
        page_count=page_count,
        text=text,
        tables=tables,
        images=images,
        blocks=blocks,
        backend="+".join(backends) or "local",
    )


def _ingest_ocr(data: bytes, filename: str) -> IngestedDocument | None:
    try:
        import fitz
        import pytesseract
        from PIL import Image
    except ImportError:
        logger.info("OCR skipped; pytesseract not installed")
        return None
    try:
        doc = fitz.open(stream=data, filetype="pdf")
        chunks = []
        blocks = []
        for index, page in enumerate(doc, start=1):
            if index > min(MAX_PAGES, 8):
                break
            pix = page.get_pixmap(dpi=140)
            image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            page_text = pytesseract.image_to_string(image) or ""
            chunks.append(page_text)
            if page_text.strip():
                blocks.append({"type": "page_text", "page": index, "text": page_text})
        doc.close()
        text = "\n".join(chunks).strip()
        if not text:
            return None
        return IngestedDocument(
            filename=filename,
            page_count=len(chunks),
            text=text,
            blocks=blocks,
            backend="ocr",
            ocr_used=True,
        )
    except Exception:
        logger.exception("OCR ingest failed")
        return None
