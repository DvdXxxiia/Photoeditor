"""Shared quote-text helpers. Never treat filenames, titles, or years as prices."""

from __future__ import annotations

import re

MONTHS = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
    "jan",
    "feb",
    "mar",
    "apr",
    "jun",
    "jul",
    "aug",
    "sep",
    "sept",
    "oct",
    "nov",
    "dec",
)

DATE_PHRASE = re.compile(
    rf"\b(?:{'|'.join(MONTHS)})\b\.?\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+(?:19|20)\d{{2}}\b",
    re.I,
)
ISO_DATE = re.compile(r"\b(?:19|20)\d{2}[-/.]\d{1,2}[-/.]\d{1,2}\b")
BARE_YEAR = re.compile(r"^(?:19|20)\d{2}(?:\.0+)?$")
FILENAME_SUFFIX = re.compile(r"\.(?:pdf|docx?|xlsx?|png|jpe?g)\b", re.I)
CURRENCY = re.compile(r"(?:USD|EUR|GBP|CAD|CNY|RMB|[$€£])", re.I)


def is_year_amount(value) -> bool:
    if value in {None, ""}:
        return False
    text = str(value).strip().replace(",", "").replace("$", "").replace("€", "").replace("£", "")
    if not BARE_YEAR.match(text):
        try:
            number = float(text)
        except ValueError:
            return False
        return number.is_integer() and 1900 <= number <= 2099
    return True


def looks_like_document_title(text: str) -> bool:
    blob = " ".join((text or "").split())
    if not blob:
        return True
    if DATE_PHRASE.search(blob) or ISO_DATE.search(blob) or FILENAME_SUFFIX.search(blob):
        return True
    tokens = blob.replace(",", "").split()
    if not tokens:
        return True
    last = re.sub(r"[^\d]", "", tokens[-1])
    if BARE_YEAR.match(last) and not CURRENCY.search(blob):
        return True
    return False
