"""Photo editor backend: sessions, detection, and pixel operations."""

from editor.models import ClipboardItem, DetectedObject, SessionState
from editor.operations import apply_operation, inpaint_object
from editor.session import SessionStore

__all__ = [
    "ClipboardItem",
    "DetectedObject",
    "SessionState",
    "SessionStore",
    "apply_operation",
    "inpaint_object",
]
