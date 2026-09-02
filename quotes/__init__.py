"""Quote Intelligence: ingest, match, and compare vendor quotes by meaning."""

from quotes.service import compare_quote_pdfs, load_comparison

__all__ = ["compare_quote_pdfs", "load_comparison"]
