"""Photo editor backend: sessions, detection, and pixel operations."""

from editor.models import DetectedObject, SessionState
from editor.operations import apply_operation, inpaint_object
from editor.session import SessionStore

__all__ = [
    "DetectedObject",
    "SessionState",
    "SessionStore",
    "apply_operation",
    "inpaint_object",
]
