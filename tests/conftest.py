"""Keep API tests off the YOLO weight download path."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def skip_yolo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("editor.detect.detect_yolo", lambda image: [])
