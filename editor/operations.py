"""Pixel-level edits applied to a selected object mask."""

from __future__ import annotations

import cv2
import numpy as np

MAX_LONG_SIDE = 1920

OPERATIONS = (
    "brightness",
    "contrast",
    "saturation",
    "blur",
    "grayscale",
    "invert",
    "pixelate",
    "tint",
    "sharpen",
)


def resize_for_edit(image: np.ndarray, max_side: int = MAX_LONG_SIDE) -> np.ndarray:
    """Downscale huge photos so detection and inpainting stay responsive."""
    h, w = image.shape[:2]
    long_side = max(h, w)
    if long_side <= max_side:
        return image
    scale = max_side / long_side
    new_size = (max(1, int(w * scale)), max(1, int(h * scale)))
    return cv2.resize(image, new_size, interpolation=cv2.INTER_AREA)


def feather_mask(mask: np.ndarray, radius: int = 2) -> np.ndarray:
    """Soft alpha from a boolean mask so edits blend at object edges."""
    alpha = mask.astype(np.float32)
    if radius > 0:
        k = radius * 2 + 1
        alpha = cv2.GaussianBlur(alpha, (k, k), 0)
    return np.clip(alpha, 0.0, 1.0)


def composite(base: np.ndarray, modified: np.ndarray, mask: np.ndarray, feather: int = 2) -> np.ndarray:
    alpha = feather_mask(mask.astype(bool), feather)[..., None]
    mixed = modified.astype(np.float32) * alpha + base.astype(np.float32) * (1.0 - alpha)
    return np.clip(mixed, 0, 255).astype(np.uint8)


def _ensure_mask(image: np.ndarray, mask: np.ndarray) -> np.ndarray:
    if mask.dtype != bool:
        mask = mask.astype(bool)
    if mask.shape[:2] != image.shape[:2]:
        raise ValueError("Mask size does not match image size")
    return mask


def apply_brightness(image: np.ndarray, mask: np.ndarray, amount: float) -> np.ndarray:
    """amount is roughly -100..100."""
    mask = _ensure_mask(image, mask)
    delta = float(amount)
    adjusted = cv2.convertScaleAbs(image, alpha=1.0, beta=delta)
    return composite(image, adjusted, mask)


def apply_contrast(image: np.ndarray, mask: np.ndarray, amount: float) -> np.ndarray:
    """amount is roughly -50..50, mapped onto a scale factor."""
    mask = _ensure_mask(image, mask)
    alpha = 1.0 + (float(amount) / 100.0)
    adjusted = cv2.convertScaleAbs(image, alpha=alpha, beta=0)
    return composite(image, adjusted, mask)


def apply_saturation(image: np.ndarray, mask: np.ndarray, amount: float) -> np.ndarray:
    """amount is roughly -100..100."""
    mask = _ensure_mask(image, mask)
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[:, :, 1] = np.clip(hsv[:, :, 1] * (1.0 + float(amount) / 100.0), 0, 255)
    adjusted = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)
    return composite(image, adjusted, mask)


def apply_blur(image: np.ndarray, mask: np.ndarray, amount: float) -> np.ndarray:
    mask = _ensure_mask(image, mask)
    radius = max(1, int(abs(amount)))
    k = radius * 2 + 1
    blurred = cv2.GaussianBlur(image, (k, k), 0)
    return composite(image, blurred, mask, feather=max(2, radius // 2))


def apply_grayscale(image: np.ndarray, mask: np.ndarray, amount: float = 100) -> np.ndarray:
    mask = _ensure_mask(image, mask)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray_bgr = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    strength = np.clip(float(amount) / 100.0, 0.0, 1.0)
    mixed = (gray_bgr.astype(np.float32) * strength + image.astype(np.float32) * (1.0 - strength)).astype(
        np.uint8
    )
    return composite(image, mixed, mask)


def apply_invert(image: np.ndarray, mask: np.ndarray, amount: float = 100) -> np.ndarray:
    mask = _ensure_mask(image, mask)
    inverted = cv2.bitwise_not(image)
    strength = np.clip(float(amount) / 100.0, 0.0, 1.0)
    mixed = (inverted.astype(np.float32) * strength + image.astype(np.float32) * (1.0 - strength)).astype(
        np.uint8
    )
    return composite(image, mixed, mask)


def apply_pixelate(image: np.ndarray, mask: np.ndarray, amount: float) -> np.ndarray:
    mask = _ensure_mask(image, mask)
    h, w = image.shape[:2]
    block = max(4, int(abs(amount)))
    small_w = max(1, w // block)
    small_h = max(1, h // block)
    small = cv2.resize(image, (small_w, small_h), interpolation=cv2.INTER_LINEAR)
    pixelated = cv2.resize(small, (w, h), interpolation=cv2.INTER_NEAREST)
    return composite(image, pixelated, mask, feather=1)


def apply_tint(image: np.ndarray, mask: np.ndarray, color: tuple[int, int, int], amount: float) -> np.ndarray:
    """Tint the object. color is BGR. amount 0..100."""
    mask = _ensure_mask(image, mask)
    strength = np.clip(float(amount) / 100.0, 0.0, 1.0)
    overlay = np.empty_like(image)
    overlay[:, :] = color
    tinted = cv2.addWeighted(image, 1.0 - strength, overlay, strength, 0)
    return composite(image, tinted, mask)


def apply_sharpen(image: np.ndarray, mask: np.ndarray, amount: float) -> np.ndarray:
    mask = _ensure_mask(image, mask)
    strength = max(0.1, float(amount) / 50.0)
    blur = cv2.GaussianBlur(image, (0, 0), 3)
    sharp = cv2.addWeighted(image, 1.0 + strength, blur, -strength, 0)
    return composite(image, sharp, mask)


def inpaint_object(image: np.ndarray, mask: np.ndarray, radius: int = 5) -> np.ndarray:
    """Remove an object by inpainting its (slightly dilated) mask."""
    mask = _ensure_mask(image, mask)
    kernel = np.ones((5, 5), np.uint8)
    dilate = cv2.dilate(mask.astype(np.uint8) * 255, kernel, iterations=1)
    if not np.any(dilate):
        return image.copy()
    r = max(3, int(radius))
    return cv2.inpaint(image, dilate, r, cv2.INPAINT_TELEA)


def flatten_overlay(image_bgr: np.ndarray, overlay_rgba: np.ndarray) -> np.ndarray:
    """Composite an RGBA drawing layer onto the BGR working image."""
    if overlay_rgba.shape[2] != 4:
        raise ValueError("Overlay must be RGBA")
    if overlay_rgba.shape[:2] != image_bgr.shape[:2]:
        overlay_rgba = cv2.resize(
            overlay_rgba,
            (image_bgr.shape[1], image_bgr.shape[0]),
            interpolation=cv2.INTER_LINEAR,
        )
    overlay_bgr = overlay_rgba[:, :, 2::-1].astype(np.float32)
    alpha = (overlay_rgba[:, :, 3:4].astype(np.float32)) / 255.0
    out = image_bgr.astype(np.float32) * (1.0 - alpha) + overlay_bgr * alpha
    return np.clip(out, 0, 255).astype(np.uint8)


def apply_operation(
    image: np.ndarray,
    mask: np.ndarray,
    operation: str,
    amount: float = 0,
    color: tuple[int, int, int] | None = None,
) -> np.ndarray:
    op = operation.lower().strip()
    if op == "brightness":
        return apply_brightness(image, mask, amount)
    if op == "contrast":
        return apply_contrast(image, mask, amount)
    if op == "saturation":
        return apply_saturation(image, mask, amount)
    if op == "blur":
        return apply_blur(image, mask, amount if amount else 7)
    if op == "grayscale":
        return apply_grayscale(image, mask, amount if amount else 100)
    if op == "invert":
        return apply_invert(image, mask, amount if amount else 100)
    if op == "pixelate":
        return apply_pixelate(image, mask, amount if amount else 12)
    if op == "sharpen":
        return apply_sharpen(image, mask, amount if amount else 40)
    if op == "tint":
        if color is None:
            raise ValueError("tint requires a color")
        return apply_tint(image, mask, color, amount if amount else 45)
    raise ValueError(f"Unknown operation: {operation}")


def bbox_from_mask(mask: np.ndarray) -> tuple[int, int, int, int] | None:
    ys, xs = np.where(mask)
    if len(xs) == 0:
        return None
    x0, x1 = int(xs.min()), int(xs.max())
    y0, y1 = int(ys.min()), int(ys.max())
    return x0, y0, x1 - x0 + 1, y1 - y0 + 1


def paste_pixels(
    dest: np.ndarray,
    source_pixels: np.ndarray,
    source_mask: np.ndarray,
    dx: int,
    dy: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Copy masked source pixels onto dest, shifted by (dx, dy).

    Pixels that land outside dest are clipped. Returns the new image and a
    boolean mask of whatever actually landed on dest.
    """
    if source_mask.shape[:2] != source_pixels.shape[:2]:
        raise ValueError("Clipboard mask does not match clipboard pixels")
    dest_h, dest_w = dest.shape[:2]
    src_h, src_w = source_pixels.shape[:2]
    out = dest.copy()
    new_mask = np.zeros((dest_h, dest_w), dtype=bool)
    ys, xs = np.where(source_mask.astype(bool))
    if len(xs) == 0:
        return out, new_mask
    ny = ys + int(dy)
    nx = xs + int(dx)
    valid = (
        (ys >= 0)
        & (ys < src_h)
        & (xs >= 0)
        & (xs < src_w)
        & (ny >= 0)
        & (ny < dest_h)
        & (nx >= 0)
        & (nx < dest_w)
    )
    if not np.any(valid):
        return out, new_mask
    out[ny[valid], nx[valid]] = source_pixels[ys[valid], xs[valid]]
    new_mask[ny[valid], nx[valid]] = True
    return out, new_mask
