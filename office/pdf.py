"""Extract, summarize, and compare two PDF documents."""

from __future__ import annotations

import io
import json
import logging
import os
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from pypdf import PdfReader
from pypdf.errors import PdfReadError, PdfStreamError

logger = logging.getLogger(__name__)

MAX_PDF_BYTES = 20 * 1024 * 1024
MAX_PAGES = 100
MAX_CHARS = 80_000
MAX_LIST_ITEMS = 40
CHANGE_RATIO = 0.55
LLM_CHARS = 12_000

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")
_WORD = re.compile(r"[a-z0-9']+")
_STOP = frozenset(
    """
    a an the and or but if to of in on for with at from by as is are was were be been
    being it this that those these they them their we our you your he she his her
    not no nor so than then there here such can will would should may might must
    have has had do does did into about over after before also just only other
    more most some any each all both few many much very
    """.split()
)


class PdfError(ValueError):
    """User-facing PDF problem."""


@dataclass
class ExtractedPdf:
    filename: str
    page_count: int
    text: str
    words: int

    def to_dict(self, summary: list[str]) -> dict:
        return {
            "filename": self.filename,
            "pages": self.page_count,
            "words": self.words,
            "summary": summary,
        }


@dataclass
class PdfComparison:
    backend: str
    left: ExtractedPdf
    right: ExtractedPdf
    left_summary: list[str]
    right_summary: list[str]
    similarity: float
    overview: str
    only_in_left: list[str] = field(default_factory=list)
    only_in_right: list[str] = field(default_factory=list)
    changes: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "backend": self.backend,
            "similarity": round(float(self.similarity), 3),
            "overview": self.overview,
            "left": self.left.to_dict(self.left_summary),
            "right": self.right.to_dict(self.right_summary),
            "only_in_left": self.only_in_left,
            "only_in_right": self.only_in_right,
            "changes": self.changes,
        }


def llm_enabled() -> bool:
    if os.environ.get("PHOTOEDITOR_DISABLE_VLM", "").strip().lower() in {"1", "true", "yes"}:
        return False
    return bool(os.environ.get("OPENAI_API_KEY", "").strip())


def extract_pdf(data: bytes, filename: str = "document.pdf") -> ExtractedPdf:
    if not data:
        raise PdfError("Empty file")
    if len(data) > MAX_PDF_BYTES:
        raise PdfError("PDF is larger than 20 MB")
    try:
        reader = PdfReader(io.BytesIO(data))
    except (PdfReadError, PdfStreamError, Exception) as exc:
        raise PdfError("Could not read that PDF") from exc
    if getattr(reader, "is_encrypted", False):
        try:
            if reader.decrypt("") == 0:
                raise PdfError("That PDF is password protected")
        except PdfError:
            raise
        except Exception as exc:
            raise PdfError("That PDF is password protected") from exc
    pages = reader.pages[:MAX_PAGES]
    chunks: list[str] = []
    for page in pages:
        try:
            chunks.append(page.extract_text() or "")
        except Exception:
            logger.exception("Failed to extract a PDF page from %s", filename)
            chunks.append("")
    text = re.sub(r"[ \t]+", " ", "\n".join(chunks))
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text:
        raise PdfError("No extractable text. Scanned PDFs without selectable text are not supported yet.")
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS]
    words = len(_WORD.findall(text.lower()))
    return ExtractedPdf(filename=filename or "document.pdf", page_count=len(reader.pages), text=text, words=words)


def split_sentences(text: str) -> list[str]:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned:
        return []
    parts = _SENT_SPLIT.split(cleaned)
    return [p.strip() for p in parts if p.strip()]


def summarize(text: str, max_bullets: int = 6) -> list[str]:
    sentences = split_sentences(text)
    if not sentences:
        return []
    if len(sentences) <= max_bullets:
        return sentences
    freqs: dict[str, int] = {}
    for sent in sentences:
        for word in _WORD.findall(sent.lower()):
            if word in _STOP or len(word) < 3:
                continue
            freqs[word] = freqs.get(word, 0) + 1
    if not freqs:
        return sentences[:max_bullets]
    scored: list[tuple[float, int, str]] = []
    for i, sent in enumerate(sentences):
        words = [w for w in _WORD.findall(sent.lower()) if w not in _STOP and len(w) >= 3]
        if not words:
            continue
        score = sum(freqs.get(w, 0) for w in words) / len(words)
        scored.append((score, i, sent))
    scored.sort(key=lambda item: (-item[0], item[1]))
    chosen = sorted(scored[:max_bullets], key=lambda item: item[1])
    return [item[2] for item in chosen]


def _norm(sentence: str) -> str:
    return re.sub(r"\s+", " ", sentence).strip().lower()


def diff_sentences(left_text: str, right_text: str) -> tuple[list[str], list[str], list[dict[str, str]]]:
    left = split_sentences(left_text)
    right = split_sentences(right_text)
    matched_right: set[int] = set()
    only_left: list[str] = []
    changes: list[dict[str, str]] = []
    for sentence in left:
        needle = _norm(sentence)
        exact = next((i for i, other in enumerate(right) if i not in matched_right and _norm(other) == needle), None)
        if exact is not None:
            matched_right.add(exact)
            continue
        best_i = None
        best_ratio = 0.0
        for i, other in enumerate(right):
            if i in matched_right:
                continue
            ratio = SequenceMatcher(None, needle, _norm(other)).ratio()
            if ratio > best_ratio:
                best_i = i
                best_ratio = ratio
        if best_i is not None and best_ratio >= CHANGE_RATIO:
            matched_right.add(best_i)
            changes.append({"left": sentence, "right": right[best_i]})
        else:
            only_left.append(sentence)
    only_right = [sentence for i, sentence in enumerate(right) if i not in matched_right]
    return only_left[:MAX_LIST_ITEMS], only_right[:MAX_LIST_ITEMS], changes[:MAX_LIST_ITEMS]


def _overview(similarity: float, only_left: list[str], only_right: list[str], changes: list) -> str:
    pct = round(similarity * 100)
    bits = [f"The two documents are about {pct}% similar."]
    if only_left:
        bits.append(f"The first PDF has {len(only_left)} statement{'s' if len(only_left) != 1 else ''} not in the second.")
    if only_right:
        bits.append(f"The second PDF has {len(only_right)} statement{'s' if len(only_right) != 1 else ''} not in the first.")
    if changes:
        n = len(changes)
        verb = "looks" if n == 1 else "look"
        bits.append(f"{n} statement{'s' if n != 1 else ''} {verb} related but wording changed.")
    if not only_left and not only_right and not changes:
        bits.append("No sentence-level differences were found.")
    return " ".join(bits)


def _local_compare(left: ExtractedPdf, right: ExtractedPdf) -> PdfComparison:
    only_left, only_right, changes = diff_sentences(left.text, right.text)
    similarity = SequenceMatcher(None, left.text, right.text).ratio()
    return PdfComparison(
        backend="local",
        left=left,
        right=right,
        left_summary=summarize(left.text),
        right_summary=summarize(right.text),
        similarity=similarity,
        overview=_overview(similarity, only_left, only_right, changes),
        only_in_left=only_left,
        only_in_right=only_right,
        changes=changes,
    )


def _trim(text: str, limit: int = LLM_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n\n[truncated]"


def _llm_compare(left: ExtractedPdf, right: ExtractedPdf) -> PdfComparison | None:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None
    model = os.environ.get("PHOTOEDITOR_OPENAI_MODEL", "gpt-4o")
    prompt = (
        "Compare these two office documents. Reply JSON only with keys: "
        "overview (string), left_summary (array of short strings), right_summary (array of short strings), "
        "only_in_left (array of strings), only_in_right (array of strings), "
        'changes (array of {"left": string, "right": string}). '
        "Summaries should be 4-8 bullets of the main points. "
        "only_in_* lists facts present in one document and absent from the other. "
        "changes lists the same idea with different wording or values.\n\n"
        f"Document A ({left.filename}):\n{_trim(left.text)}\n\n"
        f"Document B ({right.filename}):\n{_trim(right.text)}"
    )
    body = {
        "model": model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": "You compare business documents. Return strict JSON. Do not invent facts.",
            },
            {"role": "user", "content": prompt},
        ],
    }
    try:
        import httpx

        response = httpx.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=body,
            timeout=90.0,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        match = re.search(r"\{.*\}", content, re.S)
        data = json.loads(match.group(0) if match else content)
    except Exception:
        logger.exception("OpenAI document compare failed")
        return None

    def _strings(value) -> list[str]:
        if not isinstance(value, list):
            return []
        out = []
        for item in value:
            text = str(item).strip()
            if text:
                out.append(text)
        return out[:MAX_LIST_ITEMS]

    def _changes(value) -> list[dict[str, str]]:
        if not isinstance(value, list):
            return []
        out = []
        for item in value:
            if not isinstance(item, dict):
                continue
            a = str(item.get("left", "")).strip()
            b = str(item.get("right", "")).strip()
            if a and b:
                out.append({"left": a, "right": b})
        return out[:MAX_LIST_ITEMS]

    only_left = _strings(data.get("only_in_left"))
    only_right = _strings(data.get("only_in_right"))
    changes = _changes(data.get("changes"))
    similarity = SequenceMatcher(None, left.text, right.text).ratio()
    overview = str(data.get("overview") or "").strip() or _overview(similarity, only_left, only_right, changes)
    left_summary = _strings(data.get("left_summary")) or summarize(left.text)
    right_summary = _strings(data.get("right_summary")) or summarize(right.text)
    return PdfComparison(
        backend="openai",
        left=left,
        right=right,
        left_summary=left_summary,
        right_summary=right_summary,
        similarity=similarity,
        overview=overview,
        only_in_left=only_left,
        only_in_right=only_right,
        changes=changes,
    )


def compare_pdf_bytes(
    left_data: bytes,
    right_data: bytes,
    left_name: str = "left.pdf",
    right_name: str = "right.pdf",
) -> PdfComparison:
    left = extract_pdf(left_data, left_name)
    right = extract_pdf(right_data, right_name)
    if llm_enabled():
        llm = _llm_compare(left, right)
        if llm is not None:
            return llm
    return _local_compare(left, right)


def write_text_pdf(text: str) -> bytes:
    """Build a one-page PDF whose text pypdf can extract. Used by tests."""
    lines = [line for line in text.split("\n") if line] or [text]
    ops = ["BT /F1 12 Tf 72 720 Td"]
    for i, line in enumerate(lines):
        escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        if i:
            ops.append("0 -16 Td")
        ops.append(f"({escaped}) Tj")
    ops.append("ET")
    stream = "\n".join(ops).encode("latin-1", "replace")
    bodies = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> >> >>"
        ),
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for i, body in enumerate(bodies, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(bodies) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets[1:]:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(bodies) + 1} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF\n".encode()
    )
    return bytes(out)
