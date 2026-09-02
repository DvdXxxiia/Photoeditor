"""Vision-language labeling for detected regions.

Prefers Florence-2 dense region captions. If OPENAI_API_KEY is set, GPT-4o
Vision can caption crops. Color/shape names are not used here.
"""

from __future__ import annotations

import io
import json
import logging
import os
import re
from dataclasses import dataclass
from functools import lru_cache

import cv2
import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

FLORENCE_MODEL = os.environ.get("PHOTOEDITOR_FLORENCE_MODEL", "microsoft/Florence-2-base")
MAX_CAPTION_WORDS = 8
WEAK_LINEART_LABELS = (
    "person",
    "people",
    "man",
    "woman",
    "boy",
    "girl",
    "car",
    "truck",
    "dog",
    "cat",
)


@dataclass
class SemanticBox:
    label: str
    confidence: float
    bbox_xyxy: tuple[float, float, float, float]


def vlm_enabled() -> bool:
    return os.environ.get("PHOTOEDITOR_DISABLE_VLM", "").strip() not in {"1", "true", "yes"}


def vlm_backend() -> str:
    if not vlm_enabled():
        return "off"
    if os.environ.get("OPENAI_API_KEY"):
        if _florence_ready():
            return "florence+openai"
        return "openai"
    if _florence_ready():
        return "florence"
    return "none"


def _florence_ready() -> bool:
    return _florence()[0] is not None


@lru_cache(maxsize=1)
def _florence():
    """Load Florence-2 once. Returns (model, processor, device, dtype) or (None,)*4."""
    if not vlm_enabled():
        return None, None, None, None
    try:
        import torch
        from transformers import AutoModelForCausalLM, AutoProcessor
    except ImportError:
        logger.info("transformers/torch not available; Florence-2 disabled")
        return None, None, None, None
    device = "cuda" if torch.cuda.is_available() else "cpu"
    dtype = torch.float16 if device == "cuda" else torch.float32
    kwargs = dict(trust_remote_code=True)
    try:
        model = AutoModelForCausalLM.from_pretrained(FLORENCE_MODEL, dtype=dtype, attn_implementation="eager", **kwargs)
    except TypeError:
        try:
            model = AutoModelForCausalLM.from_pretrained(FLORENCE_MODEL, torch_dtype=dtype, **kwargs)
        except Exception:
            logger.exception("Could not load Florence-2 from %s", FLORENCE_MODEL)
            return None, None, None, None
    except Exception:
        logger.exception("Could not load Florence-2 from %s", FLORENCE_MODEL)
        return None, None, None, None
    try:
        processor = AutoProcessor.from_pretrained(FLORENCE_MODEL, trust_remote_code=True)
    except Exception:
        logger.exception("Could not load Florence-2 processor")
        return None, None, None, None
    model = model.to(device).eval()
    logger.info("Florence-2 ready on %s (%s)", device, FLORENCE_MODEL)
    return model, processor, device, dtype


def _to_pil(image_bgr: np.ndarray, min_side: int = 384) -> tuple[Image.Image, float]:
    rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
    pil = Image.fromarray(rgb)
    w, h = pil.size
    shortest = min(w, h)
    if shortest < min_side:
        scale = min_side / max(1, shortest)
        resample = Image.Resampling.NEAREST if max(w, h) < 160 else Image.Resampling.BICUBIC
        pil = pil.resize((max(1, int(w * scale)), max(1, int(h * scale))), resample)
        return pil, scale
    return pil, 1.0


def _clean_label(text: str) -> str:
    label = (text or "").strip()
    label = re.sub(r"\s+", " ", label)
    match = re.search(
        r"(?:photo|image|picture|drawing|illustration|icon|sketch|pixel art) of (?:a |an |the )?([^.]{3,80})",
        label,
        flags=re.I,
    )
    if match:
        label = match.group(1)
    else:
        label = re.sub(
            r"^(the image shows |this is )?(a |an |the )?(photo|image|picture|drawing|illustration|icon|sketch) of (a |an |the )?",
            "",
            label,
            flags=re.I,
        )
    label = label.strip(" .,:;\"'")
    words = label.split()
    if len(words) > MAX_CAPTION_WORDS:
        label = " ".join(words[:MAX_CAPTION_WORDS])
    return label or "object"


def is_weak_lineart_label(label: str) -> bool:
    low = (label or "").lower()
    return any(re.search(rf"\b{re.escape(word)}\b", low) for word in WEAK_LINEART_LABELS)


def _run_florence(image_bgr: np.ndarray, task: str, max_new_tokens: int = 1024) -> dict | None:
    model, processor, device, dtype = _florence()
    if model is None:
        return None
    import torch

    pil, scale = _to_pil(image_bgr)
    inputs = processor(text=task, images=pil, return_tensors="pt")
    move = {}
    for key, value in inputs.items():
        if hasattr(value, "to"):
            if value.dtype.is_floating_point:
                move[key] = value.to(device=device, dtype=dtype)
            else:
                move[key] = value.to(device)
        else:
            move[key] = value
    with torch.inference_mode():
        generated = model.generate(
            input_ids=move["input_ids"],
            pixel_values=move["pixel_values"],
            max_new_tokens=max_new_tokens,
            num_beams=1,
            do_sample=False,
            use_cache=False,
        )
    text = processor.batch_decode(generated, skip_special_tokens=False)[0]
    parsed = processor.post_process_generation(text, task=task, image_size=(pil.width, pil.height))
    payload = parsed.get(task, parsed)
    if scale != 1.0 and isinstance(payload, dict) and "bboxes" in payload:
        scaled = []
        for box in payload["bboxes"]:
            x1, y1, x2, y2 = box
            scaled.append([x1 / scale, y1 / scale, x2 / scale, y2 / scale])
        payload = {**payload, "bboxes": scaled}
    return payload


def dense_detect(image_bgr: np.ndarray) -> list[SemanticBox]:
    """Florence-2 dense region captions / object detection on the full image."""
    if not vlm_enabled():
        return []
    for task in ("<DENSE_REGION_CAPTION>", "<OD>"):
        try:
            payload = _run_florence(image_bgr, task)
        except Exception:
            logger.exception("Florence-2 %s failed", task)
            continue
        if not payload:
            continue
        boxes = payload.get("bboxes") or []
        labels = payload.get("labels") or []
        scores = payload.get("scores") or [0.78] * len(boxes)
        found: list[SemanticBox] = []
        for i, box in enumerate(boxes):
            if len(box) < 4:
                continue
            label = _clean_label(labels[i] if i < len(labels) else "object")
            if not label:
                continue
            conf = float(scores[i]) if i < len(scores) else 0.78
            found.append(SemanticBox(label=label, confidence=conf, bbox_xyxy=tuple(map(float, box[:4]))))
        if found:
            logger.info("Florence-2 %s returned %s regions", task, len(found))
            return found
    return []


def caption_crop(image_bgr: np.ndarray, bbox: tuple[int, int, int, int]) -> tuple[str, float] | None:
    """Name one cropped region. Florence caption first, then GPT-4o if configured."""
    if not vlm_enabled():
        return None
    x, y, w, h = [int(v) for v in bbox]
    ih, iw = image_bgr.shape[:2]
    x = max(0, min(x, iw - 1))
    y = max(0, min(y, ih - 1))
    w = max(1, min(w, iw - x))
    h = max(1, min(h, ih - y))
    crop = image_bgr[y : y + h, x : x + w]
    if crop.size == 0:
        return None
    florence = _caption_florence(crop)
    if florence:
        return florence
    return _caption_openai(crop)


def _caption_florence(crop_bgr: np.ndarray) -> tuple[str, float] | None:
    for task, tokens in (("<DETAILED_CAPTION>", 80), ("<CAPTION>", 48)):
        try:
            payload = _run_florence(crop_bgr, task, max_new_tokens=tokens)
        except Exception:
            logger.exception("Florence-2 %s failed", task)
            continue
        if payload is None:
            continue
        if isinstance(payload, dict):
            payload = payload.get(task) or payload.get("caption") or ""
        if isinstance(payload, str) and payload.strip():
            return _clean_label(payload), 0.74
    return None


def _caption_openai(crop_bgr: np.ndarray) -> tuple[str, float] | None:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None
    rgb = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2RGB)
    pil = Image.fromarray(rgb)
    buf = io.BytesIO()
    pil.save(buf, format="JPEG", quality=85)
    import base64

    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    body = {
        "model": os.environ.get("PHOTOEDITOR_OPENAI_MODEL", "gpt-4o"),
        "temperature": 0,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "Name the main object in this image crop in 2-6 words. "
                            "Prefer a concrete noun phrase such as "
                            '"ornamental metal fence", "window security grille", or "flower stand". '
                            "Do not use color-only names like \"blue line\". "
                            'Reply JSON only: {"label": "...", "confidence": 0.0}'
                        ),
                    },
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                ],
            }
        ],
    }
    try:
        import httpx

        response = httpx.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=body,
            timeout=45.0,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        match = re.search(r"\{.*\}", content, re.S)
        data = json.loads(match.group(0) if match else content)
        label = _clean_label(str(data.get("label", "")))
        conf = float(data.get("confidence", 0.8))
        return label, max(0.0, min(conf, 1.0))
    except Exception:
        logger.exception("OpenAI vision caption failed")
        return None
