"""Turn ingested PDF structure into a quote JSON object."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from quotes.catalog import lookup_equipment, lookup_vendor
from quotes.ingest import IngestedDocument

MONEY = re.compile(r"\$?\s*([\d,]+\.\d{2}|[\d,]+)")
QTY_PRICE = re.compile(
    r"^(?P<desc>.+?)\s+(?P<qty>\d+(?:\.\d+)?)\s+\$?(?P<price>[\d,]+(?:\.\d{2})?)\s*$"
)
PRICE_ONLY = re.compile(r"^(?P<desc>.+?)\s+\$?(?P<price>[\d,]+(?:\.\d{2})?)\s*$")
QUOTE_NO = re.compile(r"(?:quote\s*(?:number|no\.?|#)?|q)\s*[:#-]?\s*([A-Z]{0,4}\d{3,})", re.I)
DATE = re.compile(r"(20\d{2}[-/]\d{1,2}[-/]\d{1,2})")
TOTAL = re.compile(r"\btotal\b[:\s]*\$?\s*([\d,]+(?:\.\d{2})?)", re.I)
SKIP_DESC = re.compile(r"^(item|description|qty|quantity|price|unit|total|amount)\b", re.I)


@dataclass
class QuoteItem:
    description: str
    sku: str | None = None
    qty: float = 1
    unit: str = "ea"
    unit_price: float = 0
    ext_price: float = 0
    function: str | None = None
    category: str | None = None
    brand: str | None = None
    size: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ParsedQuote:
    vendor: str | None
    quote_number: str | None
    date: str | None
    filename: str
    items: list[QuoteItem] = field(default_factory=list)
    total: float = 0
    ingest_backend: str = "local"
    raw_text: str = ""

    def to_dict(self) -> dict:
        items = [item.to_dict() for item in self.items]
        total = self.total or round(sum(item.ext_price for item in self.items), 2)
        return {
            "vendor": self.vendor,
            "quote_number": self.quote_number,
            "date": self.date,
            "filename": self.filename,
            "total": total,
            "items": items,
            "ingest_backend": self.ingest_backend,
        }


def _money(value: str | None) -> float:
    if not value:
        return 0.0
    try:
        return float(str(value).replace(",", "").replace("$", "").strip())
    except ValueError:
        return 0.0


def _enrich(description: str, qty: float, price: float) -> QuoteItem:
    spec = lookup_equipment(description)
    ext = round(qty * price, 2) if qty and price else round(price, 2)
    return QuoteItem(
        description=description.strip(),
        sku=spec.sku if spec else None,
        qty=qty or 1,
        unit_price=price,
        ext_price=ext,
        function=spec.function if spec else None,
        category=spec.category if spec else None,
        brand=spec.brand if spec else None,
        size=spec.size if spec else None,
    )


def _items_from_tables(tables: list[list[list[str]]]) -> list[QuoteItem]:
    items: list[QuoteItem] = []
    for table in tables:
        if not table:
            continue
        header = [str(cell or "").strip().lower() for cell in table[0]]
        desc_i = next((i for i, h in enumerate(header) if any(k in h for k in ("desc", "item", "product", "model"))), 0)
        qty_i = next((i for i, h in enumerate(header) if "qty" in h or "qty" == h or "quantity" in h), None)
        price_i = next((i for i, h in enumerate(header) if any(k in h for k in ("price", "amount", "cost", "ext"))), None)
        rows = table[1:] if any(header) else table
        for row in rows:
            if not row:
                continue
            desc = str(row[desc_i] if desc_i < len(row) else "").strip()
            if not desc or SKIP_DESC.match(desc) or desc.lower().startswith("total"):
                continue
            qty = 1.0
            if qty_i is not None and qty_i < len(row):
                try:
                    qty = float(str(row[qty_i]).replace(",", "") or 1)
                except ValueError:
                    qty = 1.0
            price = 0.0
            if price_i is not None and price_i < len(row):
                price = _money(row[price_i])
            else:
                joined = " ".join(str(c or "") for c in row)
                found = MONEY.findall(joined)
                if found:
                    price = _money(found[-1])
            if price <= 0 and not lookup_equipment(desc):
                continue
            items.append(_enrich(desc, qty, price))
    return items


def _items_from_text(text: str) -> list[QuoteItem]:
    items: list[QuoteItem] = []
    for raw in text.splitlines():
        line = " ".join(raw.strip().split())
        if not line or SKIP_DESC.match(line) or TOTAL.search(line):
            continue
        match = QTY_PRICE.match(line)
        if match:
            items.append(_enrich(match.group("desc"), float(match.group("qty")), _money(match.group("price"))))
            continue
        match = PRICE_ONLY.match(line)
        if match and lookup_equipment(match.group("desc")):
            items.append(_enrich(match.group("desc"), 1, _money(match.group("price"))))
    return items


def parse_quote(doc: IngestedDocument) -> ParsedQuote:
    text = doc.text or ""
    vendor = lookup_vendor(text[:2500])
    number = None
    found_no = QUOTE_NO.search(text)
    if found_no:
        number = found_no.group(1).upper()
        if not number.startswith("Q") and found_no.group(0).lower().startswith("q"):
            number = "Q" + re.sub(r"^Q", "", number)
    date = None
    found_date = DATE.search(text)
    if found_date:
        date = found_date.group(1).replace("/", "-")
    items = _items_from_tables(doc.tables)
    if not items:
        items = _items_from_text(text)
    total = 0.0
    found_total = TOTAL.search(text)
    if found_total:
        total = _money(found_total.group(1))
    if not total:
        total = round(sum(item.ext_price for item in items), 2)
    return ParsedQuote(
        vendor=vendor,
        quote_number=number,
        date=date,
        filename=doc.filename,
        items=items,
        total=total,
        ingest_backend=doc.backend,
        raw_text=text,
    )
