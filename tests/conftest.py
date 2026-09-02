"""Keep tests off live Florence-2 / OpenAI calls by default."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("PHOTOEDITOR_DISABLE_VLM", "1")
os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/pytest-quotes.db")


@pytest.fixture(autouse=True)
def skip_yolo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("editor.detect.detect_yolo", lambda image: [])


@pytest.fixture(autouse=True)
def fresh_quote_db() -> None:
    from pathlib import Path

    path = Path("/tmp/pytest-quotes.db")
    if path.exists():
        path.unlink()
    from quotes.db import reset_engine

    reset_engine()
    yield
    reset_engine()
    if path.exists():
        path.unlink()
