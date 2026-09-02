"""Semantic line-item matching with local embeddings and catalog knowledge."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import numpy as np
from rapidfuzz import fuzz

from quotes.catalog import lookup_equipment, normalize_key
from quotes.parse import QuoteItem

MATCH_THRESHOLD = 0.72


def _embed(text: str) -> np.ndarray:
    """Hashed character-trigram embedding so similar wording lands nearby."""
    vec = np.zeros(256, dtype=np.float32)
    blob = normalize_key(text)
    if not blob:
        return vec
    for i in range(len(blob) - 2):
        gram = blob[i : i + 3]
        digest = hashlib.md5(gram.encode("utf-8")).digest()
        idx = int.from_bytes(digest[:2], "little") % 256
        vec[idx] += 1.0
    spec = lookup_equipment(text)
    if spec:
        token = hashlib.md5(spec.sku.encode("utf-8")).digest()
        vec[int.from_bytes(token[:2], "little") % 256] += 8.0
        if spec.function:
            fn = hashlib.md5(spec.function.encode("utf-8")).digest()
            vec[int.from_bytes(fn[:2], "little") % 256] += 3.0
    norm = float(np.linalg.norm(vec))
    return vec / norm if norm else vec


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    if a is None or b is None:
        return 0.0
    return float(np.clip(np.dot(a, b), -1.0, 1.0))


def openai_embed(texts: list[str]) -> list[np.ndarray] | None:
    import os

    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key or os.environ.get("PHOTOEDITOR_DISABLE_VLM", "").strip() in {"1", "true", "yes"}:
        return None
    try:
        import httpx

        response = httpx.post(
            "https://api.openai.com/v1/embeddings",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": os.environ.get("QUOTE_EMBEDDING_MODEL", "text-embedding-3-small"), "input": texts},
            timeout=45.0,
        )
        response.raise_for_status()
        data = sorted(response.json()["data"], key=lambda row: row["index"])
        return [np.array(row["embedding"], dtype=np.float32) for row in data]
    except Exception:
        return None


@dataclass
class ItemMatch:
    match: bool
    confidence: float
    left: QuoteItem | None
    right: QuoteItem | None
    kind: str = "unmatched"

    def to_dict(self) -> dict:
        return {
            "match": self.match,
            "confidence": round(float(self.confidence), 3),
            "kind": self.kind,
            "left": self.left.to_dict() if self.left else None,
            "right": self.right.to_dict() if self.right else None,
        }


def item_similarity(left: QuoteItem, right: QuoteItem, left_vec: np.ndarray, right_vec: np.ndarray) -> float:
    scores = [cosine(left_vec, right_vec)]
    fuzzy = fuzz.token_set_ratio(left.description, right.description) / 100.0
    scores.append(fuzzy)
    left_spec = lookup_equipment(left.description)
    right_spec = lookup_equipment(right.description)
    if left_spec and right_spec and left_spec.sku == right_spec.sku:
        return 0.98
    if left.sku and right.sku and normalize_key(left.sku) == normalize_key(right.sku):
        return 0.97
    if left_spec and right_spec and left_spec.function == right_spec.function and left_spec.brand == right_spec.brand:
        scores.append(0.78)
        if left_spec.size and right_spec.size and left_spec.size != right_spec.size:
            scores.append(0.74)
    return max(scores)


def match_kind(left: QuoteItem, right: QuoteItem) -> str:
    left_spec = lookup_equipment(left.description)
    right_spec = lookup_equipment(right.description)
    if left.sku and right.sku and normalize_key(left.sku) == normalize_key(right.sku):
        return "same_item"
    if left_spec and right_spec and left_spec.sku == right_spec.sku:
        return "same_item"
    if left_spec and right_spec and left_spec.function == right_spec.function:
        return "same_function"
    return "similar"


def match_items(left_items: list[QuoteItem], right_items: list[QuoteItem]) -> list[ItemMatch]:
    if not left_items and not right_items:
        return []
    texts = [item.description for item in left_items] + [item.description for item in right_items]
    openai_vecs = openai_embed(texts)
    if openai_vecs is not None and len(openai_vecs) == len(texts):
        left_vecs = openai_vecs[: len(left_items)]
        right_vecs = openai_vecs[len(left_items) :]
    else:
        left_vecs = [_embed(item.description) for item in left_items]
        right_vecs = [_embed(item.description) for item in right_items]

    pairs: list[tuple[float, int, int]] = []
    for i, left in enumerate(left_items):
        for j, right in enumerate(right_items):
            score = item_similarity(left, right, left_vecs[i], right_vecs[j])
            if score >= MATCH_THRESHOLD:
                pairs.append((score, i, j))
    pairs.sort(reverse=True)
    used_l: set[int] = set()
    used_r: set[int] = set()
    matches: list[ItemMatch] = []
    for score, i, j in pairs:
        if i in used_l or j in used_r:
            continue
        used_l.add(i)
        used_r.add(j)
        matches.append(ItemMatch(True, score, left_items[i], right_items[j], match_kind(left_items[i], right_items[j])))
    for i, left in enumerate(left_items):
        if i not in used_l:
            matches.append(ItemMatch(False, 0.0, left, None, "unmatched"))
    for j, right in enumerate(right_items):
        if j not in used_r:
            matches.append(ItemMatch(False, 0.0, None, right, "unmatched"))
    return matches
