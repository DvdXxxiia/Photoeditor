"""Compare drawings and visual callouts in quote PDFs."""

from __future__ import annotations

import re

from quotes.ingest import IngestedDocument

COUNT_PATTERNS = (
    (r"(\d+)\s+loaders?", "loaders"),
    (r"(\d+)\s+hoppers?", "hoppers"),
    (r"hopper\s*size[^\d]*(\d+)", "hopper size"),
    (r"(\d+)\s+vacuum receivers?", "vacuum receivers"),
    (r"utility connections?", "utility connections"),
)


def _counts(text: str) -> dict[str, int]:
    found: dict[str, int] = {}
    blob = text or ""
    for pattern, label in COUNT_PATTERNS:
        match = re.search(pattern, blob, re.I)
        if match:
            if match.lastindex:
                found[label] = int(match.group(1))
            else:
                found[label] = 1
    return found


def compare_drawings(left: IngestedDocument, right: IngestedDocument) -> dict:
    left_counts = _counts(left.text)
    right_counts = _counts(right.text)
    highlights = []
    labels = sorted(set(left_counts) | set(right_counts))
    for label in labels:
        a = left_counts.get(label)
        b = right_counts.get(label)
        if a is not None and b is not None and a != b:
            highlights.append(f"Drawing B includes {b} {label}. Drawing A includes {a} {label}.")
        elif a is not None and b is None:
            highlights.append(f"Drawing A mentions {a} {label}; Quote B does not.")
        elif b is not None and a is None:
            highlights.append(f"Drawing B mentions {b} {label}; Quote A does not.")
    if left.images or right.images:
        highlights.append(
            f"Quote A has {len(left.images)} embedded image(s); Quote B has {len(right.images)}."
        )
    return {
        "left": {"images": len(left.images), "callouts": left_counts},
        "right": {"images": len(right.images), "callouts": right_counts},
        "highlights": highlights,
    }
