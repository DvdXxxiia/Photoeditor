from __future__ import annotations

import numpy as np
import pytest

from editor.vlm import SemanticBox, _clean_label, caption_crop, dense_detect, is_weak_lineart_label, vlm_enabled


def test_clean_label_strips_caption_boilerplate():
    assert _clean_label("a drawing of an ornamental metal fence") == "ornamental metal fence"
    assert _clean_label("a black and white photo of a table with a vase of flowers on it") == "table with a vase of flowers on it"
    assert _clean_label("  Window security grille. ") == "Window security grille"


def test_weak_lineart_labels():
    assert is_weak_lineart_label("black and white pixel art of a person")
    assert not is_weak_lineart_label("ornamental metal fence")


def test_vlm_disabled_in_tests():
    assert vlm_enabled() is False
    blank = np.zeros((32, 32, 3), dtype=np.uint8)
    assert dense_detect(blank) == []
    assert caption_crop(blank, (0, 0, 16, 16)) is None


def test_semantic_box_fields():
    box = SemanticBox("flower stand", 0.88, (1.0, 2.0, 10.0, 20.0))
    assert box.label == "flower stand"
    assert box.confidence == 0.88
    assert box.bbox_xyxy[2] == 10.0
