"""Object identification: YOLO when available, plus GrabCut and magic wand."""

from __future__ import annotations

import logging
from functools import lru_cache

import cv2
import numpy as np

from editor.models import DetectedObject
from editor.operations import bbox_from_mask

logger = logging.getLogger(__name__)

PALETTE = [
    (124, 92, 252),
    (34, 211, 238),
    (250, 204, 21),
    (244, 114, 182),
    (52, 211, 153),
    (251, 146, 60),
    (96, 165, 250),
    (248, 113, 113),
    (167, 139, 250),
    (45, 212, 191),
]

MIN_AREA_RATIO = 0.004
MAX_AREA_RATIO = 0.85


def _color_for(index: int) -> tuple[int, int, int]:
    return PALETTE[index % len(PALETTE)]


@lru_cache(maxsize=1)
def _yolo_model():
    try:
        from ultralytics import YOLO
    except ImportError:
        logger.info("ultralytics is not installed; YOLO detection disabled")
        return None
    try:
        return YOLO("yolov8n-seg.pt")
    except Exception:
        logger.exception("Could not load YOLOv8 segmentation model")
        try:
            return YOLO("yolov8n.pt")
        except Exception:
            logger.exception("Could not load YOLOv8 detection model")
            return None


def grabcut_mask(
    image: np.ndarray | None,
    bbox: tuple[int, int, int, int],
    image_fallback_shape: tuple[int, int] | None = None,
    iterations: int = 4,
) -> np.ndarray:
    """Foreground mask from a user (or detector) rectangle."""
    if image is None:
        h, w = image_fallback_shape or (0, 0)
        mask = np.zeros((h, w), dtype=bool)
        x, y, bw, bh = bbox
        mask[y : y + bh, x : x + bw] = True
        return mask

    h, w = image.shape[:2]
    x, y, bw, bh = [int(v) for v in bbox]
    x = max(0, min(x, w - 2))
    y = max(0, min(y, h - 2))
    bw = max(2, min(bw, w - x))
    bh = max(2, min(bh, h - y))
    if bw < 8 or bh < 8:
        mask = np.zeros((h, w), dtype=bool)
        mask[y : y + bh, x : x + bw] = True
        return mask

    gc_mask = np.zeros((h, w), np.uint8)
    bgd = np.zeros((1, 65), np.float64)
    fgd = np.zeros((1, 65), np.float64)
    rect = (x, y, bw, bh)
    try:
        cv2.grabCut(image, gc_mask, rect, bgd, fgd, iterations, cv2.GC_INIT_WITH_RECT)
        result = np.where((gc_mask == cv2.GC_FGD) | (gc_mask == cv2.GC_PR_FGD), True, False)
        if result.sum() < 16:
            result = np.zeros((h, w), dtype=bool)
            result[y : y + bh, x : x + bw] = True
        return result
    except cv2.error:
        result = np.zeros((h, w), dtype=bool)
        result[y : y + bh, x : x + bw] = True
        return result


def magic_wand_mask(image: np.ndarray, x: int, y: int, tolerance: int = 28) -> np.ndarray:
    """Select a connected color region around a click, similar to a magic wand."""
    h, w = image.shape[:2]
    x = int(np.clip(x, 0, w - 1))
    y = int(np.clip(y, 0, h - 1))
    flood = image.copy()
    flood_mask = np.zeros((h + 2, w + 2), np.uint8)
    flags = 4 | cv2.FLOODFILL_MASK_ONLY | (255 << 8)
    lo = (int(tolerance),) * 3
    up = (int(tolerance),) * 3
    cv2.floodFill(flood, flood_mask, (x, y), (0, 0, 0), lo, up, flags)
    return flood_mask[1:-1, 1:-1] == 255


def region_masks(image: np.ndarray, k: int = 6) -> list[np.ndarray]:
    """Unsupervised color clustering so Identify still works without YOLO."""
    h, w = image.shape[:2]
    pixels = image.reshape(-1, 3).astype(np.float32)
    k = max(2, min(k, 8))
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 12, 1.0)
    _, labels, _ = cv2.kmeans(pixels, k, None, criteria, 4, cv2.KMEANS_PP_CENTERS)
    label_img = labels.reshape(h, w)
    area = h * w
    min_area = max(64, int(area * MIN_AREA_RATIO))
    max_area = int(area * MAX_AREA_RATIO)
    masks: list[np.ndarray] = []
    for cluster in range(k):
        cluster_mask = (label_img == cluster).astype(np.uint8)
        num, cc, stats, _ = cv2.connectedComponentsWithStats(cluster_mask, connectivity=8)
        for i in range(1, num):
            component_area = int(stats[i, cv2.CC_STAT_AREA])
            if component_area < min_area or component_area > max_area:
                continue
            masks.append(cc == i)
    masks.sort(key=lambda m: int(m.sum()), reverse=True)
    return masks[:12]


def _object_from_mask(
    mask: np.ndarray,
    index: int,
    label: str,
    confidence: float,
    source: str,
) -> DetectedObject | None:
    bbox = bbox_from_mask(mask)
    if bbox is None:
        return None
    return DetectedObject(
        id=f"obj-{index}",
        label=label,
        confidence=confidence,
        bbox=bbox,
        color=_color_for(index),
        mask=mask.astype(bool),
        source=source,
    )


def detect_yolo(image: np.ndarray) -> list[DetectedObject]:
    model = _yolo_model()
    if model is None:
        return []
    h, w = image.shape[:2]
    results = model.predict(image, verbose=False, conf=0.25, iou=0.45)
    if not results:
        return []
    result = results[0]
    names = result.names if hasattr(result, "names") else {}
    objects: list[DetectedObject] = []
    boxes = getattr(result, "boxes", None)
    n = 0 if boxes is None else len(boxes)
    for i in range(n):
        cls_id = int(boxes.cls[i].item()) if boxes.cls is not None else 0
        conf = float(boxes.conf[i].item()) if boxes.conf is not None else 0.0
        label = str(names.get(cls_id, f"object {i + 1}"))
        mask = None
        if getattr(result, "masks", None) is not None and result.masks is not None:
            raw = result.masks.data[i].cpu().numpy()
            mask = cv2.resize(raw, (w, h), interpolation=cv2.INTER_LINEAR) > 0.5
        else:
            xyxy = boxes.xyxy[i].cpu().numpy().astype(int)
            x1, y1, x2, y2 = [int(v) for v in xyxy]
            pad = 6
            rx = max(0, x1 - pad)
            ry = max(0, y1 - pad)
            rw = min(w - rx, (x2 - x1) + 2 * pad)
            rh = min(h - ry, (y2 - y1) + 2 * pad)
            mask = grabcut_mask(image, (rx, ry, rw, rh))
        if mask is None or not np.any(mask):
            continue
        obj = _object_from_mask(mask, len(objects) + 1, label, conf, "yolo")
        if obj:
            objects.append(obj)
    return objects


def detect_regions(image: np.ndarray) -> list[DetectedObject]:
    objects: list[DetectedObject] = []
    for mask in region_masks(image):
        obj = _object_from_mask(
            mask,
            len(objects) + 1,
            f"Region {len(objects) + 1}",
            0.5,
            "region",
        )
        if obj:
            objects.append(obj)
    return objects


def identify_objects(image: np.ndarray) -> list[DetectedObject]:
    """Prefer named YOLO detections; fall back to color regions."""
    found = detect_yolo(image)
    if found:
        return found
    logger.info("No YOLO detections; using color-region fallback")
    return detect_regions(image)


def overlay_png(image_shape: tuple[int, int], objects: list[DetectedObject], selected_id: str | None) -> np.ndarray:
    """RGBA overlay with translucent fills and outlines for each object."""
    h, w = image_shape[:2]
    overlay = np.zeros((h, w, 4), dtype=np.uint8)
    for obj in objects:
        r, g, b = obj.color
        alpha = 110 if obj.id == selected_id else 55
        overlay[obj.mask] = (r, g, b, alpha)
        mask_u8 = obj.mask.astype(np.uint8) * 255
        contours, _ = cv2.findContours(mask_u8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        line_alpha = 230 if obj.id == selected_id else 160
        thickness = 3 if obj.id == selected_id else 2
        cv2.drawContours(overlay, contours, -1, (r, g, b, line_alpha), thickness)
    return overlay


def hit_test(objects: list[DetectedObject], x: int, y: int) -> DetectedObject | None:
    """Smallest object under the cursor wins, so nested regions stay selectable."""
    hits = [obj for obj in objects if obj.contains(x, y)]
    if not hits:
        return None
    return min(hits, key=lambda obj: int(obj.mask.sum()))
