"""Keep tests off live Florence-2 / OpenAI calls by default."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("PHOTOEDITOR_DISABLE_VLM", "1")


@pytest.fixture(autouse=True)
def skip_yolo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("editor.detect.detect_yolo", lambda image: [])
