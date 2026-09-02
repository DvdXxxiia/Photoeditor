"""FastAPI app for the interactive photo editor."""

from __future__ import annotations

import io
import logging

import cv2
import numpy as np
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pydantic import BaseModel, Field

from editor.detect import grabcut_mask, hit_test, identify_objects, magic_wand_mask, overlay_png
from editor.models import DetectedObject
from editor.operations import (
    OPERATIONS,
    apply_operation,
    bbox_from_mask,
    flatten_overlay,
    inpaint_object,
    resize_for_edit,
)
from editor.session import SessionStore

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Photo Editor", version="1.0.0")
store = SessionStore()

app.mount("/static", StaticFiles(directory="static"), name="static")


class ModifyBody(BaseModel):
    object_id: str
    operation: str
    amount: float = 0
    color: list[int] | None = None  # RGB


class DeleteBody(BaseModel):
    object_id: str


class BoxSelectBody(BaseModel):
    x: float
    y: float
    w: float
    h: float
    label: str = "Selection"


class WandBody(BaseModel):
    x: float
    y: float
    tolerance: int = Field(default=28, ge=1, le=80)


class FlattenBody(BaseModel):
    overlay_png_base64: str


def _encode_jpeg(image_bgr: np.ndarray, quality: int = 90) -> bytes:
    success, buf = cv2.imencode(".jpg", image_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not success:
        raise RuntimeError("Could not encode image")
    return buf.tobytes()


def _encode_png_rgba(image_rgba: np.ndarray) -> bytes:
    pil = Image.fromarray(image_rgba, mode="RGBA")
    out = io.BytesIO()
    pil.save(out, format="PNG")
    return out.getvalue()


def _read_image(data: bytes) -> np.ndarray:
    arr = np.frombuffer(data, dtype=np.uint8)
    image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("Unsupported or corrupted image")
    return resize_for_edit(image)


def _session_payload(session, extra: dict | None = None) -> dict:
    payload = {
        "session_id": session.id,
        "width": int(session.image.shape[1]),
        "height": int(session.image.shape[0]),
        "filename": session.filename,
        "objects": [obj.to_dict() for obj in session.objects],
        "can_undo": bool(session.history),
        "can_redo": bool(session.redo_stack),
        "operations": list(OPERATIONS),
    }
    if extra:
        payload.update(extra)
    return payload


def _renumber(objects: list[DetectedObject]) -> list[DetectedObject]:
    for i, obj in enumerate(objects, start=1):
        obj.id = f"obj-{i}"
    return objects


def _drop_object(session, object_id: str) -> None:
    session.objects = [obj for obj in session.objects if obj.id != object_id]


@app.get("/")
def index() -> FileResponse:
    return FileResponse("static/index.html")


@app.post("/api/session")
async def create_session(file: UploadFile = File(...)) -> dict:
    data = await file.read()
    if not data:
        raise HTTPException(400, "Empty file")
    try:
        image = _read_image(data)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    name = file.filename or "photo.png"
    session = store.create(image, filename=name)
    return _session_payload(session)


@app.get("/api/session/{session_id}")
def get_session(session_id: str) -> dict:
    try:
        session = store.require(session_id)
    except KeyError as exc:
        raise HTTPException(404, "Session not found") from exc
    return _session_payload(session)


@app.get("/api/session/{session_id}/image")
def get_image(session_id: str) -> Response:
    try:
        session = store.require(session_id)
    except KeyError as exc:
        raise HTTPException(404, "Session not found") from exc
    return Response(content=_encode_jpeg(session.image), media_type="image/jpeg")


@app.get("/api/session/{session_id}/overlay")
def get_overlay(session_id: str, selected: str | None = Query(default=None)) -> Response:
    try:
        session = store.require(session_id)
    except KeyError as exc:
        raise HTTPException(404, "Session not found") from exc
    overlay = overlay_png(session.image.shape, session.objects, selected)
    return Response(content=_encode_png_rgba(overlay), media_type="image/png")


@app.post("/api/session/{session_id}/detect")
def detect(session_id: str) -> dict:
    try:
        session = store.require(session_id)
    except KeyError as exc:
        raise HTTPException(404, "Session not found") from exc
    objects = identify_objects(session.image)
    store.set_objects(session_id, objects)
    return _session_payload(session, {"count": len(objects)})


@app.get("/api/session/{session_id}/hit")
def hit(session_id: str, x: float, y: float) -> dict:
    try:
        session = store.require(session_id)
    except KeyError as exc:
        raise HTTPException(404, "Session not found") from exc
    obj = hit_test(session.objects, int(round(x)), int(round(y)))
    return {"object": obj.to_dict() if obj else None}


@app.post("/api/session/{session_id}/box-select")
def box_select(session_id: str, body: BoxSelectBody) -> dict:
    try:
        session = store.require(session_id)
    except KeyError as exc:
        raise HTTPException(404, "Session not found") from exc
    mask = grabcut_mask(session.image, (int(body.x), int(body.y), int(body.w), int(body.h)))
    bbox = bbox_from_mask(mask)
    if bbox is None:
        raise HTTPException(400, "Nothing was selected in that box")
    obj = DetectedObject(
        id=f"obj-{len(session.objects) + 1}",
        label=body.label or "Selection",
        confidence=1.0,
        bbox=bbox,
        color=(124, 92, 252),
        mask=mask,
        source="box",
    )
    session.objects.append(obj)
    _renumber(session.objects)
    return _session_payload(session, {"selected_id": obj.id})


@app.post("/api/session/{session_id}/wand")
def wand(session_id: str, body: WandBody) -> dict:
    try:
        session = store.require(session_id)
    except KeyError as exc:
        raise HTTPException(404, "Session not found") from exc
    mask = magic_wand_mask(session.image, int(body.x), int(body.y), body.tolerance)
    bbox = bbox_from_mask(mask)
    if bbox is None:
        raise HTTPException(400, "Magic wand did not find a region")
    obj = DetectedObject(
        id=f"obj-{len(session.objects) + 1}",
        label="Wand selection",
        confidence=1.0,
        bbox=bbox,
        color=(34, 211, 238),
        mask=mask,
        source="wand",
    )
    session.objects.append(obj)
    _renumber(session.objects)
    return _session_payload(session, {"selected_id": obj.id})


@app.post("/api/session/{session_id}/modify")
def modify(session_id: str, body: ModifyBody) -> dict:
    try:
        session = store.require(session_id)
    except KeyError as exc:
        raise HTTPException(404, "Session not found") from exc
    obj = store.find_object(session_id, body.object_id)
    if obj is None:
        raise HTTPException(404, "Object not found")
    color = None
    if body.color is not None:
        if len(body.color) != 3:
            raise HTTPException(400, "color must be RGB with 3 values")
        r, g, b = [int(c) for c in body.color]
        color = (b, g, r)  # OpenCV BGR
    session.snapshot()
    try:
        session.image = apply_operation(session.image, obj.mask, body.operation, body.amount, color)
    except ValueError as exc:
        session.history.pop()
        raise HTTPException(400, str(exc)) from exc
    return _session_payload(session)


@app.post("/api/session/{session_id}/delete")
def delete_object(session_id: str, body: DeleteBody) -> dict:
    try:
        session = store.require(session_id)
    except KeyError as exc:
        raise HTTPException(404, "Session not found") from exc
    obj = store.find_object(session_id, body.object_id)
    if obj is None:
        raise HTTPException(404, "Object not found")
    session.snapshot()
    session.image = inpaint_object(session.image, obj.mask)
    _drop_object(session, body.object_id)
    _renumber(session.objects)
    return _session_payload(session)


@app.post("/api/session/{session_id}/undo")
def undo(session_id: str) -> dict:
    try:
        session = store.require(session_id)
    except KeyError as exc:
        raise HTTPException(404, "Session not found") from exc
    if not session.undo():
        raise HTTPException(400, "Nothing to undo")
    return _session_payload(session)


@app.post("/api/session/{session_id}/redo")
def redo(session_id: str) -> dict:
    try:
        session = store.require(session_id)
    except KeyError as exc:
        raise HTTPException(404, "Session not found") from exc
    if not session.redo():
        raise HTTPException(400, "Nothing to redo")
    return _session_payload(session)


@app.post("/api/session/{session_id}/flatten")
def flatten(session_id: str, body: FlattenBody) -> dict:
    try:
        session = store.require(session_id)
    except KeyError as exc:
        raise HTTPException(404, "Session not found") from exc
    raw = body.overlay_png_base64
    if "," in raw:
        raw = raw.split(",", 1)[1]
    try:
        import base64

        overlay_bytes = base64.b64decode(raw)
        overlay = Image.open(io.BytesIO(overlay_bytes)).convert("RGBA")
        overlay_np = np.array(overlay)
    except Exception as exc:
        raise HTTPException(400, "Invalid overlay image") from exc
    session.snapshot()
    session.image = flatten_overlay(session.image, overlay_np)
    return _session_payload(session)


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
