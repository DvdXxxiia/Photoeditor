from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from editor.models import DetectedObject, SessionState
from editor.operations import (
    apply_brightness,
    apply_grayscale,
    apply_operation,
    apply_tint,
    bbox_from_mask,
    flatten_overlay,
    inpaint_object,
    paste_pixels,
    resize_for_edit,
)
from editor.detect import (
    coarse_foreground_regions,
    grabcut_mask,
    hit_test,
    identify_objects,
    is_line_art,
    looks_like_line_diagram,
    looks_photographic,
    magic_wand_mask,
    overlay_png,
    propose_regions,
    region_masks,
)
from editor.vlm import SemanticBox
from editor.session import SessionStore


def _solid(color, h=80, w=100) -> np.ndarray:
    img = np.zeros((h, w, 3), dtype=np.uint8)
    img[:] = color
    return img


def _circle_mask(h=80, w=100, cx=40, cy=40, r=18) -> np.ndarray:
    yy, xx = np.ogrid[:h, :w]
    return (xx - cx) ** 2 + (yy - cy) ** 2 <= r * r


def test_brightness_only_changes_masked_pixels():
    image = _solid((10, 20, 30))
    mask = _circle_mask()
    interior = _circle_mask(r=10)
    far = ~_circle_mask(r=26)
    out = apply_brightness(image, mask, 40)
    assert out[far].tolist() == image[far].tolist()
    assert int(out[interior][:, 0].mean()) > int(image[interior][:, 0].mean())


def test_grayscale_collapses_channels_inside_mask():
    image = _solid((10, 80, 200))
    mask = _circle_mask()
    interior = _circle_mask(r=10)
    out = apply_grayscale(image, mask, 100)
    region = out[interior]
    assert np.allclose(region[:, 0], region[:, 1], atol=2)
    assert np.allclose(region[:, 1], region[:, 2], atol=2)


def test_tint_shifts_toward_target_color():
    image = _solid((0, 0, 0))
    mask = np.ones((80, 100), dtype=bool)
    out = apply_tint(image, mask, (0, 0, 255), 100)
    assert int(out[10, 10, 2]) > 200  # BGR red


def test_inpaint_removes_blob():
    image = _solid((240, 240, 240))
    mask = _circle_mask(r=12)
    image[mask] = (0, 0, 255)
    out = inpaint_object(image, mask, radius=4)
    interior = _circle_mask(r=8)
    # Background is light gray; the filled hole should no longer be saturated red.
    assert abs(int(out[interior].mean()) - 240) < 25
    assert int(out[interior][:, 0].mean()) > 150


def test_flatten_overlay_respects_alpha():
    base = _solid((0, 0, 0), 20, 20)
    overlay = np.zeros((20, 20, 4), dtype=np.uint8)
    overlay[5:10, 5:10] = (255, 0, 0, 255)  # red RGBA
    out = flatten_overlay(base, overlay)
    assert out[7, 7].tolist() == [0, 0, 255]  # BGR
    assert out[0, 0].tolist() == [0, 0, 0]


def test_resize_keeps_small_images():
    image = _solid((1, 2, 3), 40, 50)
    assert resize_for_edit(image).shape == image.shape


def test_bbox_from_mask():
    mask = np.zeros((20, 20), dtype=bool)
    mask[4:10, 2:8] = True
    assert bbox_from_mask(mask) == (2, 4, 6, 6)
    assert bbox_from_mask(np.zeros((4, 4), dtype=bool)) is None


def test_session_undo_redo():
    store = SessionStore()
    session = store.create(_solid((1, 1, 1)))
    session.snapshot()
    session.image = _solid((9, 9, 9))
    assert session.undo()
    assert session.image[0, 0, 0] == 1
    assert session.redo()
    assert session.image[0, 0, 0] == 9
    assert not session.redo()


def test_session_undo_restores_objects():
    store = SessionStore()
    session = store.create(_solid((1, 1, 1), 40, 40))
    mask = np.zeros((40, 40), dtype=bool)
    mask[4:10, 4:10] = True
    session.objects = [
        DetectedObject("obj-1", "block", 1, (4, 4, 6, 6), (1, 2, 3), mask, "wand"),
    ]
    session.snapshot()
    session.objects = []
    session.image = _solid((9, 9, 9), 40, 40)
    assert session.undo()
    assert session.image[0, 0, 0] == 1
    assert len(session.objects) == 1
    assert session.objects[0].label == "block"
    assert session.objects[0].mask[5, 5]


def test_paste_pixels_shifts_and_clips():
    dest = _solid((0, 0, 0), 40, 40)
    src = _solid((0, 0, 0), 40, 40)
    mask = np.zeros((40, 40), dtype=bool)
    mask[5:10, 5:10] = True
    src[mask] = (0, 0, 255)
    out, new_mask = paste_pixels(dest, src, mask, 8, 4)
    assert new_mask[9, 13]
    assert out[9, 13].tolist() == [0, 0, 255]
    assert not new_mask[5, 5]
    assert dest[9, 13].tolist() == [0, 0, 0]

    clipped, clipped_mask = paste_pixels(dest, src, mask, 1000, 0)
    assert not clipped_mask.any()
    assert clipped[0, 0].tolist() == [0, 0, 0]

    partial, partial_mask = paste_pixels(dest, src, mask, 32, 0)
    assert partial_mask.any()
    assert int(partial_mask.sum()) < int(mask.sum())
    assert partial[5, 37].tolist() == [0, 0, 255]


def test_magic_wand_selects_connected_color():
    image = _solid((255, 255, 255), 60, 80)
    image[10:30, 10:40] = (0, 0, 220)
    image[40:50, 50:70] = (0, 0, 220)
    mask = magic_wand_mask(image, 20, 20, tolerance=8)
    assert mask[20, 20]
    assert mask[15, 15]
    assert not mask[45, 60]


def test_region_masks_finds_distinct_blocks():
    image = _solid((250, 250, 250), 80, 120)
    image[10:40, 10:50] = (20, 20, 200)
    image[45:75, 60:110] = (20, 180, 20)
    masks = region_masks(image, k=3)
    assert len(masks) >= 2


def test_hit_test_prefers_smaller_object():
    big = np.zeros((40, 40), dtype=bool)
    big[5:35, 5:35] = True
    small = np.zeros((40, 40), dtype=bool)
    small[15:22, 15:22] = True
    objects = [
        DetectedObject("a", "big", 1, (5, 5, 30, 30), (1, 2, 3), big),
        DetectedObject("b", "small", 1, (15, 15, 7, 7), (4, 5, 6), small),
    ]
    hit = hit_test(objects, 18, 18)
    assert hit is not None and hit.id == "b"
    assert hit_test(objects, 0, 0) is None


def test_overlay_png_shape_and_alpha():
    mask = _circle_mask(40, 40, 20, 20, 8)
    obj = DetectedObject("obj-1", "dot", 1, (12, 12, 16, 16), (255, 0, 0), mask)
    overlay = overlay_png((40, 40), [obj], "obj-1")
    assert overlay.shape == (40, 40, 4)
    assert overlay[20, 20, 3] > 0
    assert overlay[1, 1, 3] == 0


def test_grabcut_tiny_box_falls_back_to_rectangle():
    image = _solid((30, 30, 30), 40, 40)
    image[10:30, 10:30] = (200, 40, 40)
    mask = grabcut_mask(image, (12, 12, 4, 4))
    assert mask[13, 13]


def test_unknown_operation_raises():
    with pytest.raises(ValueError):
        apply_operation(_solid((1, 2, 3)), np.ones((80, 100), dtype=bool), "explode")


def test_session_store_missing():
    store = SessionStore()
    with pytest.raises(KeyError):
        store.require("nope")


FIXTURES = Path(__file__).parent / "fixtures"


def test_identify_parts_not_background_area():
    image = np.full((80, 100, 3), (204, 241, 246), dtype=np.uint8)
    image[28:42, 38:54] = (8, 40, 90)
    image[66:74, 24:70] = (25, 110, 175)
    objects = identify_objects(image)
    assert len(objects) >= 2
    h, w = image.shape[:2]
    for obj in objects:
        x, y, bw, bh = obj.bbox
        assert bw * bh < 0.5 * h * w
        assert obj.mask.sum() < 0.25 * h * w


def test_device_icon_finds_parts():
    image = cv2.imread(str(FIXTURES / "device-icon.png"))
    assert image is not None
    assert not looks_photographic(image)
    objects = identify_objects(image)
    assert objects
    assert all(obj.source != "region" for obj in objects)
    assert all(obj.bbox[2] * obj.bbox[3] < 0.92 * image.shape[0] * image.shape[1] for obj in objects)


def test_plant_diagram_finds_units_not_page():
    image = cv2.imread(str(FIXTURES / "plant-diagram.png"))
    assert image is not None
    assert looks_like_line_diagram(image)
    objects = identify_objects(image)
    assert len(objects) >= 5
    assert all(obj.source != "yolo" for obj in objects)
    page = image.shape[0] * image.shape[1]
    assert all(obj.bbox[2] * obj.bbox[3] < 0.35 * page for obj in objects)


def test_diagram_ignores_yolo_false_positives(monkeypatch: pytest.MonkeyPatch):
    image = cv2.imread(str(FIXTURES / "plant-diagram.png"))
    fake_mask = np.zeros(image.shape[:2], dtype=bool)
    fake_mask[10:20, 10:20] = True
    fake = DetectedObject("yolo-1", "traffic light", 0.9, (10, 10, 10, 10), (1, 2, 3), fake_mask, "yolo")
    monkeypatch.setattr("editor.detect.detect_yolo", lambda _image: [fake])
    objects = identify_objects(image)
    assert objects
    assert all(obj.source != "yolo" for obj in objects)


def test_lattice_is_one_drawing_not_many_lines():
    image = cv2.imread(str(FIXTURES / "lattice-icon.png"))
    assert image is not None
    assert is_line_art(image)
    regions = coarse_foreground_regions(image)
    assert len(regions) == 1
    x, y, w, h = regions[0].bbox
    assert w * h < 0.95 * image.shape[0] * image.shape[1]
    assert regions[0].area > 200


def test_lattice_gets_semantic_vlm_name(monkeypatch: pytest.MonkeyPatch):
    image = cv2.imread(str(FIXTURES / "lattice-icon.png"))
    monkeypatch.setattr("editor.vlm.vlm_enabled", lambda: True)
    monkeypatch.setattr("editor.vlm.dense_detect", lambda _image: [])
    monkeypatch.setattr(
        "editor.vlm.caption_crop",
        lambda _image, _bbox: ("ornamental metal fence", 0.91),
    )
    objects = identify_objects(image)
    assert objects
    assert objects[0].label == "ornamental metal fence"
    assert objects[0].source == "vlm"
    assert objects[0].to_dict()["bbox"] == list(objects[0].bbox)


def test_dense_vlm_boxes_become_objects(monkeypatch: pytest.MonkeyPatch):
    image = np.full((80, 60, 3), 240, dtype=np.uint8)
    image[10:50, 8:50] = 20
    monkeypatch.setattr("editor.vlm.vlm_enabled", lambda: True)
    monkeypatch.setattr("editor.detect.looks_photographic", lambda _image: True)
    monkeypatch.setattr(
        "editor.vlm.dense_detect",
        lambda _image: [SemanticBox("window security grille", 0.84, (8, 10, 50, 50))],
    )
    objects = identify_objects(image)
    assert len(objects) == 1
    assert objects[0].label == "window security grille"
    assert objects[0].to_dict()["bbox"][2] > 0


