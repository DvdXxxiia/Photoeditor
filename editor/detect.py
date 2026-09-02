"""Object identification: discrete parts, not background areas."""

from __future__ import annotations

import logging
from dataclasses import dataclass
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
MAX_OBJECTS = 40


def _color_for(index: int) -> tuple[int, int, int]:
    return PALETTE[index % len(PALETTE)]


@dataclass
class _Part:
    mask: np.ndarray
    bbox: tuple[int, int, int, int]
    area: int
    mean_bgr: np.ndarray
    source: str

    @property
    def fill(self) -> float:
        x, y, w, h = self.bbox
        return self.area / max(1, w * h)

    @property
    def aspect(self) -> float:
        x, y, w, h = self.bbox
        return max(w, h) / max(1, min(w, h))


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


def looks_photographic(image: np.ndarray) -> bool:
    """True for real-world photos; false for icons, CAD, and schematics."""
    h, w = image.shape[:2]
    if max(h, w) < 180:
        return False
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    light_frac = float((gray > 230).mean())
    sat_mean = float(hsv[:, :, 1].mean())
    if light_frac > 0.40 and sat_mean < 40:
        return False
    border = np.concatenate([image[0], image[-1], image[:, 0], image[:, -1]])
    if border.std() < 18 and float(gray.mean()) > 210 and light_frac > 0.25:
        return False
    return True


def looks_like_line_diagram(image: np.ndarray) -> bool:
    h, w = image.shape[:2]
    if max(h, w) < 200:
        return False
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    light_frac = float((gray > 230).mean())
    sat_mean = float(hsv[:, :, 1].mean())
    return light_frac > 0.40 and sat_mean < 45


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


def background_mask(image: np.ndarray, tolerance: int = 14) -> np.ndarray:
    """Flood from the border so paper/backdrop is not treated as an object."""
    h, w = image.shape[:2]
    mask = np.zeros((h + 2, w + 2), np.uint8)
    flags = 4 | cv2.FLOODFILL_MASK_ONLY | (255 << 8)
    lo = (tolerance,) * 3
    up = (tolerance,) * 3
    canvas = image.copy()
    seeds = [
        (0, 0),
        (w - 1, 0),
        (0, h - 1),
        (w - 1, h - 1),
        (w // 2, 0),
        (w // 2, h - 1),
        (0, h // 2),
        (w - 1, h // 2),
    ]
    for seed in seeds:
        cv2.floodFill(canvas, mask, seed, (0, 0, 0), lo, up, flags)
    return mask[1:-1, 1:-1] > 0


def region_masks(image: np.ndarray, k: int = 6) -> list[np.ndarray]:
    """Unsupervised color clustering (legacy fallback)."""
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


def _part_from_mask(mask: np.ndarray, image: np.ndarray, source: str) -> _Part | None:
    if mask.dtype != bool:
        mask = mask.astype(bool)
    if not np.any(mask):
        return None
    bbox = bbox_from_mask(mask)
    if bbox is None:
        return None
    return _Part(
        mask=mask,
        bbox=bbox,
        area=int(mask.sum()),
        mean_bgr=image[mask].mean(axis=0),
        source=source,
    )


def _is_sliver(part: _Part) -> bool:
    x, y, w, h = part.bbox
    short, long = min(w, h), max(w, h)
    if short <= 2 and long >= 8:
        return True
    if part.source in {"unit", "stroke"}:
        return False
    if part.fill < 0.18:
        return True
    return False


def _filter_parts(parts: list[_Part], image: np.ndarray) -> list[_Part]:
    h, w = image.shape[:2]
    img_area = h * w
    kept: list[_Part] = []
    for part in parts:
        x, y, bw, bh = part.bbox
        area_frac = part.area / img_area
        bbox_frac = (bw * bh) / img_area
        if part.area < max(16, int(img_area * 0.0007)):
            continue
        if _is_sliver(part):
            continue
        if bbox_frac > 0.50 and area_frac > 0.12:
            continue
        if area_frac > 0.32:
            continue
        # Large solid fills are backdrops, not objects.
        if area_frac > 0.16 and part.fill > 0.50:
            continue
        kept.append(part)
    return _drop_container_areas(kept, img_area)


def _bbox_contains(outer: tuple[int, int, int, int], inner: tuple[int, int, int, int], pad: int = 1) -> bool:
    ox, oy, ow, oh = outer
    ix, iy, iw, ih = inner
    return ix >= ox - pad and iy >= oy - pad and ix + iw <= ox + ow + pad and iy + ih <= oy + oh + pad


def _drop_container_areas(parts: list[_Part], img_area: int) -> list[_Part]:
    """Drop large backdrops that only exist to hold smaller objects."""
    survivors: list[_Part] = []
    for part in parts:
        nested = [
            other
            for other in parts
            if other is not part and _bbox_contains(part.bbox, other.bbox) and other.area < part.area * 0.7
        ]
        if nested and part.area > 0.08 * img_area and part.fill > 0.45:
            continue
        survivors.append(part)
    return survivors


def _merge_similar_parts(parts: list[_Part], image: np.ndarray, gap: int = 2) -> list[_Part]:
    """Join only tiny adjacent chips of the same color (anti-aliased fragments)."""
    if len(parts) < 2:
        return parts
    parent = list(range(len(parts)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        a, b = find(i), find(j)
        if a != b:
            parent[b] = a

    small = 90
    for i, a in enumerate(parts):
        if a.area > small:
            continue
        ax, ay, aw, ah = a.bbox
        for j in range(i + 1, len(parts)):
            b = parts[j]
            if b.area > small:
                continue
            if np.linalg.norm(a.mean_bgr - b.mean_bgr) > 20:
                continue
            bx, by, bw, bh = b.bbox
            close = ax - gap <= bx + bw and bx - gap <= ax + aw and ay - gap <= by + bh and by - gap <= ay + ah
            if close:
                union(i, j)

    groups: dict[int, list[_Part]] = {}
    for i, part in enumerate(parts):
        groups.setdefault(find(i), []).append(part)
    merged: list[_Part] = []
    for group in groups.values():
        if len(group) == 1:
            merged.append(group[0])
            continue
        mask = np.zeros(image.shape[:2], dtype=bool)
        for part in group:
            mask |= part.mask
        item = _part_from_mask(mask, image, group[0].source)
        if item:
            merged.append(item)
    return merged


def color_part_masks(image: np.ndarray) -> list[_Part]:
    """Distinct same-color objects after removing the backdrop."""
    h, w = image.shape[:2]
    bg = background_mask(image)
    if h * w <= 90_000:
        parts = _flood_color_parts(image, bg)
    else:
        parts = _quantize_color_parts(image, bg)
    parts = _merge_similar_parts(parts, image)
    return _filter_parts(parts, image)


def _flood_color_parts(image: np.ndarray, bg: np.ndarray) -> list[_Part]:
    h, w = image.shape[:2]
    visited = bg.copy()
    flags = 4 | cv2.FLOODFILL_MASK_ONLY | (255 << 8)
    canvas = image.copy()
    parts: list[_Part] = []
    for y in range(h):
        for x in range(w):
            if visited[y, x]:
                continue
            flood_mask = np.zeros((h + 2, w + 2), np.uint8)
            cv2.floodFill(canvas, flood_mask, (int(x), int(y)), (0, 0, 0), (16, 16, 16), (16, 16, 16), flags)
            region = flood_mask[1:-1, 1:-1] > 0
            region &= ~bg
            visited |= region
            part = _part_from_mask(region, image, "object")
            if part:
                parts.append(part)
    return parts


def _quantize_color_parts(image: np.ndarray, bg: np.ndarray) -> list[_Part]:
    h, w = image.shape[:2]
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB).reshape(-1, 3).astype(np.float32)
    k = 8
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 16, 1.0)
    _, labels, _ = cv2.kmeans(lab, k, None, criteria, 4, cv2.KMEANS_PP_CENTERS)
    labels = labels.reshape(h, w)
    parts: list[_Part] = []
    for cluster in range(k):
        cluster_mask = ((labels == cluster) & (~bg)).astype(np.uint8)
        if cluster_mask.sum() < 8:
            continue
        num, cc, stats, _ = cv2.connectedComponentsWithStats(cluster_mask, connectivity=8)
        for i in range(1, num):
            part = _part_from_mask(cc == i, image, "object")
            if part:
                parts.append(part)
    return parts


def diagram_unit_masks(image: np.ndarray) -> list[_Part]:
    """Dense ink clusters (stations, blocks). Colored pipes are left to stroke detection."""
    h, w = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    ink = (gray < 175).astype(np.float32)
    win = max(9, min(h, w) // 80)
    if win % 2 == 0:
        win += 1
    density = cv2.blur(ink, (win, win))
    img_area = h * w
    best: list[_Part] = []
    best_score = -1
    for thresh in (0.24, 0.30, 0.36):
        hot = (density > thresh).astype(np.uint8)
        num, cc, stats, _ = cv2.connectedComponentsWithStats(hot, connectivity=8)
        batch: list[_Part] = []
        for i in range(1, num):
            x, y, bw, bh = (int(stats[i, c]) for c in range(4))
            if bw * bh > 0.30 * img_area:
                continue
            if bw > 0.42 * w and bh > 0.20 * h:
                continue
            region = (cc == i) & (ink > 0)
            part = _part_from_mask(region, image, "unit")
            if part is None or part.area < max(120, int(img_area * 0.00035)):
                continue
            if min(bw, bh) < 10:
                continue
            batch.append(part)
        score = 0
        for part in batch:
            short = min(part.bbox[2], part.bbox[3])
            long = max(part.bbox[2], part.bbox[3])
            if short >= 28 and part.area >= 800:
                score += 4
            elif short >= 18 and part.area >= 400 and long / max(1, short) < 8:
                score += 2
        if score > best_score:
            best_score = score
            best = batch
    return best[:MAX_OBJECTS]


def color_stroke_masks(image: np.ndarray) -> list[_Part]:
    """Saturated connectors (pipes, arrows) as their own objects."""
    h, w = image.shape[:2]
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    colorful = ((hsv[:, :, 1] > 50) & (hsv[:, :, 2] < 245)).astype(np.uint8)
    colorful = cv2.morphologyEx(colorful, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    num, cc, stats, _ = cv2.connectedComponentsWithStats(colorful, connectivity=8)
    parts: list[_Part] = []
    for i in range(1, num):
        x, y, bw, bh = (int(stats[i, c]) for c in range(4))
        area = int(stats[i, cv2.CC_STAT_AREA])
        if area < 30:
            continue
        if bw * bh > 0.08 * h * w:
            continue
        if bw > 0.32 * w and bh > 0.32 * h:
            continue
        part = _part_from_mask(cc == i, image, "stroke")
        if part:
            parts.append(part)
    return _filter_parts(parts, image)[:16]


def _nms_parts(parts: list[_Part], iou_thresh: float = 0.55) -> list[_Part]:
    parts = sorted(parts, key=lambda p: p.area, reverse=True)
    kept: list[_Part] = []
    for part in parts:
        redundant = False
        for other in kept:
            inter = int(np.logical_and(part.mask, other.mask).sum())
            if inter == 0:
                continue
            union = part.area + other.area - inter
            iou = inter / max(1, union)
            smaller = min(part.area, other.area)
            if iou > iou_thresh or inter / smaller > 0.8:
                # Keep the more compact / specific mask.
                if part.fill > other.fill + 0.08 and part.area < other.area:
                    _discard_part(kept, other)
                    break
                redundant = True
                break
        if not redundant:
            kept.append(part)
        if len(kept) >= MAX_OBJECTS:
            break
    return kept


def _discard_part(kept: list[_Part], other: _Part) -> None:
    for i, item in enumerate(kept):
        if item is other:
            kept.pop(i)
            return


def color_name(bgr: np.ndarray) -> str:
    b, g, r = [float(v) for v in bgr]
    mx, mn = max(r, g, b), min(r, g, b)
    if mx < 45:
        return "black"
    if mn > 225:
        return "white"
    if mx - mn < 22:
        return "gray"
    if r >= g and r >= b:
        return "orange" if g > 80 else "red"
    if g >= r and g >= b:
        return "green"
    return "blue"


def shape_name(part: _Part) -> str:
    if part.source == "stroke" or part.aspect >= 4.5:
        return "line"
    if part.source == "unit":
        return "unit"
    if part.aspect <= 1.35 and part.fill >= 0.7:
        return "square" if abs(part.bbox[2] - part.bbox[3]) < 6 else "block"
    if part.fill < 0.35:
        return "frame"
    return "object"


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


def _objects_from_parts(parts: list[_Part]) -> list[DetectedObject]:
    objects: list[DetectedObject] = []
    for part in parts:
        obj = _object_from_mask(
            part.mask,
            len(objects) + 1,
            f"object {len(objects) + 1}",
            0.55,
            part.source,
        )
        if obj:
            objects.append(obj)
    return objects


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


def is_line_art(image: np.ndarray) -> bool:
    """True for B/W icons and schematics where color fragments are not objects."""
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    sat = float(hsv[:, :, 1].mean())
    if sat > 28:
        return False
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    light = float((gray > 220).mean())
    dark = float((gray < 50).mean())
    return light + dark > 0.30 or (max(image.shape[:2]) < 180 and sat < 22)


def coarse_foreground_regions(image: np.ndarray) -> list[_Part]:
    """One blob per connected drawing, so a lattice stays a single object."""
    h, w = image.shape[:2]
    bg = background_mask(image)
    content = (~bg).astype(np.uint8) * 255
    k = max(3, min(h, w) // 30)
    if k % 2 == 0:
        k += 1
    closed = cv2.morphologyEx(
        content,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_RECT, (k, k)),
    )
    num, cc, stats, _ = cv2.connectedComponentsWithStats((closed > 0).astype(np.uint8), 8)
    parts: list[_Part] = []
    min_area = max(24, int(h * w * 0.008))
    for i in range(1, num):
        area = int(stats[i, cv2.CC_STAT_AREA])
        if area < min_area:
            continue
        x, y, bw, bh = (int(stats[i, c]) for c in range(4))
        if bw * bh > 0.96 * h * w:
            continue
        region = (cc == i) & (~bg)
        part = _part_from_mask(region, image, "object")
        if part:
            parts.append(part)
    return parts


def propose_regions(image: np.ndarray) -> list[_Part]:
    """Stage 1: boxes/masks only. Naming happens in the VLM stage."""
    if looks_like_line_diagram(image):
        parts = diagram_unit_masks(image) + color_stroke_masks(image)
        if parts:
            return parts
    if is_line_art(image) or max(image.shape[:2]) < 160:
        blobs = coarse_foreground_regions(image)
        if blobs:
            return blobs
    parts = color_part_masks(image)
    if parts:
        return parts
    return coarse_foreground_regions(image)


def mask_from_xyxy(image: np.ndarray, xyxy: tuple[float, float, float, float]) -> np.ndarray:
    h, w = image.shape[:2]
    x1, y1, x2, y2 = [int(round(v)) for v in xyxy]
    x1, x2 = max(0, min(x1, x2)), min(w, max(x1, x2))
    y1, y2 = max(0, min(y1, y2)), min(h, max(y1, y2))
    mask = np.zeros((h, w), dtype=bool)
    if x2 - x1 < 2 or y2 - y1 < 2:
        return mask
    gray = cv2.cvtColor(image[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
    ink = gray < 200
    if int(ink.sum()) >= 12:
        mask[y1:y2, x1:x2] = ink
    else:
        mask[y1:y2, x1:x2] = True
    return mask


def objects_from_semantic_boxes(image: np.ndarray, boxes) -> list[DetectedObject]:
    objects: list[DetectedObject] = []
    for box in boxes:
        mask = mask_from_xyxy(image, box.bbox_xyxy)
        obj = _object_from_mask(mask, len(objects) + 1, box.label, box.confidence, "vlm")
        if obj:
            objects.append(obj)
    return objects


def objects_from_captioned_parts(image: np.ndarray, parts: list[_Part]) -> list[DetectedObject]:
    from editor.vlm import caption_crop

    objects: list[DetectedObject] = []
    for part in parts:
        named = caption_crop(image, part.bbox)
        if not named:
            continue
        label, confidence = named
        obj = _object_from_mask(part.mask, len(objects) + 1, label, confidence, "vlm")
        if obj:
            objects.append(obj)
    return objects


def identify_objects(image: np.ndarray) -> list[DetectedObject]:
    """Detect regions, then name them with a vision-language model when available."""
    from editor.vlm import dense_detect, vlm_enabled

    if vlm_enabled():
        # Photos: Florence can detect and name in one pass.
        # Line-art icons/schematics: propose whole objects, then caption crops
        # so a grille is not split into "blue line" fragments or a false "person".
        if looks_photographic(image):
            semantic = dense_detect(image)
            if semantic:
                found = objects_from_semantic_boxes(image, semantic)
                if found:
                    return found
        parts = propose_regions(image)
        captioned = objects_from_captioned_parts(image, parts)
        if captioned:
            return captioned

    if looks_photographic(image):
        found = detect_yolo(image)
        if found:
            return found

    parts = propose_regions(image)
    objects = _objects_from_parts(parts)
    if objects:
        return objects
    logger.info("No objects found; using color-region fallback")
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
    """Smallest object under the cursor wins, so nested parts stay selectable."""
    hits = [obj for obj in objects if obj.contains(x, y)]
    if not hits:
        return None
    return min(hits, key=lambda obj: int(obj.mask.sum()))
