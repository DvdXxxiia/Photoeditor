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


def clone_detected(obj: DetectedObject) -> DetectedObject:
    """Deep-copy an object so history frames do not share masks."""
    return DetectedObject(
        id=obj.id,
        label=obj.label,
        confidence=obj.confidence,
        bbox=tuple(obj.bbox),
        color=tuple(obj.color),
        mask=obj.mask.copy(),
        source=obj.source,
    )


@dataclass
class ClipboardItem:
    """Pixels and mask captured when the user copies an object."""

    pixels: np.ndarray  # BGR uint8, same size as the working image at copy time
    mask: np.ndarray
    label: str
    color: tuple[int, int, int]
    paste_count: int = 0


@dataclass
class HistoryFrame:
    image: np.ndarray
    objects: list[DetectedObject]


@dataclass
class SessionState:
    """In-memory editing session."""

    id: str
    image: np.ndarray  # BGR uint8
    objects: list[DetectedObject] = field(default_factory=list)
    history: list[HistoryFrame] = field(default_factory=list)
    redo_stack: list[HistoryFrame] = field(default_factory=list)
    filename: str = "photo.png"
    clipboard: ClipboardItem | None = None

    def _frame(self) -> HistoryFrame:
        return HistoryFrame(
            image=self.image.copy(),
            objects=[clone_detected(obj) for obj in self.objects],
        )

    def _restore(self, frame: HistoryFrame) -> None:
        self.image = frame.image
        self.objects = [clone_detected(obj) for obj in frame.objects]

    def snapshot(self) -> None:
        self.history.append(self._frame())
        self.redo_stack.clear()
        if len(self.history) > 40:
            self.history.pop(0)

    def undo(self) -> bool:
        if not self.history:
            return False
        self.redo_stack.append(self._frame())
        self._restore(self.history.pop())
        return True

    def redo(self) -> bool:
        if not self.redo_stack:
            return False
        self.history.append(self._frame())
        self._restore(self.redo_stack.pop())
        return True
