"""In-memory photo-editor sessions."""

from __future__ import annotations

from uuid import uuid4

import numpy as np

from editor.models import DetectedObject, SessionState


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, SessionState] = {}

    def create(self, image: np.ndarray, filename: str = "photo.png") -> SessionState:
        session = SessionState(id=str(uuid4()), image=image, filename=filename)
        self._sessions[session.id] = session
        return session

    def get(self, session_id: str) -> SessionState | None:
        return self._sessions.get(session_id)

    def require(self, session_id: str) -> SessionState:
        session = self.get(session_id)
        if session is None:
            raise KeyError(session_id)
        return session

    def set_objects(self, session_id: str, objects: list[DetectedObject]) -> SessionState:
        session = self.require(session_id)
        session.objects = objects
        return session

    def find_object(self, session_id: str, object_id: str) -> DetectedObject | None:
        session = self.require(session_id)
        for obj in session.objects:
            if obj.id == object_id:
                return obj
        return None
