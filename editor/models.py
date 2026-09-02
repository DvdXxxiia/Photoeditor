"""Shared data models for the photo editor."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class DetectedObject:
    """A selectable region in the working image."""

    id: str
    label: str
    confidence: float
    bbox: tuple[int, int, int, int]  # x, y, w, h
    color: tuple[int, int, int]
    mask: np.ndarray  # bool array, same H×W as the working image
    source: str = "detect"

    def contains(self, x: int, y: int) -> bool:
        h, w = self.mask.shape[:2]
        if x < 0 or y < 0 or x >= w or y >= h:
            return False
        return bool(self.mask[y, x])

    def to_dict(self) -> dict:
        x, y, w, h = self.bbox
        return {
            "id": self.id,
            "label": self.label,
            "confidence": round(float(self.confidence), 3),
            "bbox": [int(x), int(y), int(w), int(h)],
            "color": list(self.color),
            "source": self.source,
        }


@dataclass
class SessionState:
    """In-memory editing session."""

    id: str
    image: np.ndarray  # BGR uint8
    objects: list[DetectedObject] = field(default_factory=list)
    history: list[np.ndarray] = field(default_factory=list)
    redo_stack: list[np.ndarray] = field(default_factory=list)
    filename: str = "photo.png"

    def snapshot(self) -> None:
        self.history.append(self.image.copy())
        self.redo_stack.clear()
        if len(self.history) > 40:
            self.history.pop(0)

    def undo(self) -> bool:
        if not self.history:
            return False
        self.redo_stack.append(self.image.copy())
        self.image = self.history.pop()
        return True

    def redo(self) -> bool:
        if not self.redo_stack:
            return False
        self.history.append(self.image.copy())
        self.image = self.redo_stack.pop()
        return True
