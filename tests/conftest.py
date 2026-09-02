"""Keep API tests off the YOLO weight download path."""

from __future__ import annotations

import pytest

from editor.detect import detect_regions


@pytest.fixture(autouse=True)
def skip_yolo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.identify_objects", lambda image: detect_regions(image))
