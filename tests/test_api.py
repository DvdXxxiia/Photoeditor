from __future__ import annotations

import io

import numpy as np
from fastapi.testclient import TestClient
from PIL import Image

import app as app_module
from editor.session import SessionStore


def _png_bytes(color=(220, 40, 40), size=(80, 60), bg=(245, 245, 245)) -> bytes:
    img = Image.new("RGB", size, bg)
    for x in range(10, 40):
        for y in range(10, 40):
            img.putpixel((x, y), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def setup_function() -> None:
    app_module.store = SessionStore()


def test_health():
    client = TestClient(app_module.app)
    assert client.get("/api/health").json()["ok"] is True


def test_upload_detect_wand_modify_delete():
    client = TestClient(app_module.app)
    upload = client.post("/api/session", files={"file": ("red.png", _png_bytes(), "image/png")})
    assert upload.status_code == 200
    session_id = upload.json()["session_id"]
    assert upload.json()["width"] == 80

    image = client.get(f"/api/session/{session_id}/image")
    assert image.status_code == 200
    assert image.headers["content-type"] == "image/jpeg"

    detect = client.post(f"/api/session/{session_id}/detect")
    assert detect.status_code == 200
    assert detect.json()["count"] >= 1

    wand = client.post(
        f"/api/session/{session_id}/wand",
        json={"x": 20, "y": 20, "tolerance": 20},
    )
    assert wand.status_code == 200
    selected = wand.json()["selected_id"]
    assert selected

    modify = client.post(
        f"/api/session/{session_id}/modify",
        json={"object_id": selected, "operation": "grayscale", "amount": 100},
    )
    assert modify.status_code == 200
    assert modify.json()["can_undo"] is True

    delete = client.post(
        f"/api/session/{session_id}/delete",
        json={"object_id": selected},
    )
    assert delete.status_code == 200

    undo = client.post(f"/api/session/{session_id}/undo")
    assert undo.status_code == 200

    overlay = client.get(f"/api/session/{session_id}/overlay")
    assert overlay.status_code == 200
    assert overlay.headers["content-type"] == "image/png"


def test_copy_paste_duplicates_object():
    client = TestClient(app_module.app)
    upload = client.post("/api/session", files={"file": ("red.png", _png_bytes(), "image/png")})
    session_id = upload.json()["session_id"]
    assert upload.json()["can_paste"] is False

    empty_paste = client.post(f"/api/session/{session_id}/paste", json={})
    assert empty_paste.status_code == 400

    wand = client.post(
        f"/api/session/{session_id}/wand",
        json={"x": 20, "y": 20, "tolerance": 20},
    )
    selected = wand.json()["selected_id"]
    before = len(wand.json()["objects"])

    missing = client.post(
        f"/api/session/{session_id}/copy",
        json={"object_id": "obj-missing"},
    )
    assert missing.status_code == 404

    copied = client.post(
        f"/api/session/{session_id}/copy",
        json={"object_id": selected},
    )
    assert copied.status_code == 200
    assert copied.json()["can_paste"] is True

    pasted = client.post(f"/api/session/{session_id}/paste", json={})
    assert pasted.status_code == 200
    data = pasted.json()
    assert data["can_paste"] is True
    assert data["can_undo"] is True
    assert len(data["objects"]) == before + 1
    assert data["selected_id"] != selected
    pasted_obj = next(obj for obj in data["objects"] if obj["id"] == data["selected_id"])
    assert pasted_obj["source"] == "paste"
    assert pasted_obj["label"].endswith("copy")
    orig = next(obj for obj in data["objects"] if obj["id"] == selected)
    assert pasted_obj["bbox"] != orig["bbox"]

    preview = Image.open(io.BytesIO(client.get(f"/api/session/{session_id}/image").content))
    ox, oy, ow, oh = orig["bbox"]
    px, py, pw, ph = pasted_obj["bbox"]
    src = preview.getpixel((ox + ow // 2, oy + oh // 2))
    dst = preview.getpixel((px + pw // 2, py + ph // 2))
    assert src[0] > 150 and dst[0] > 150

    placed = client.post(f"/api/session/{session_id}/paste", json={"x": 55, "y": 20})
    assert placed.status_code == 200
    assert len(placed.json()["objects"]) == before + 2

    undone = client.post(f"/api/session/{session_id}/undo")
    assert undone.status_code == 200
    assert len(undone.json()["objects"]) == before + 1
    assert undone.json()["can_paste"] is True


def test_flatten_drawings():
    client = TestClient(app_module.app)
    upload = client.post("/api/session", files={"file": ("bg.png", _png_bytes(), "image/png")})
    session_id = upload.json()["session_id"]
    overlay = Image.new("RGBA", (80, 60), (0, 0, 0, 0))
    for x in range(0, 10):
        for y in range(0, 10):
            overlay.putpixel((x, y), (0, 255, 0, 255))
    buf = io.BytesIO()
    overlay.save(buf, format="PNG")
    import base64

    b64 = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
    res = client.post(f"/api/session/{session_id}/flatten", json={"overlay_png_base64": b64})
    assert res.status_code == 200
    assert res.json()["can_undo"] is True


def test_office_pages_and_quote_compare():
    from office.pdf import write_text_pdf
    from quotes.samples import QUOTE_A, QUOTE_B

    client = TestClient(app_module.app)
    home = client.get("/")
    assert home.status_code == 200
    assert b"Office Applications" in home.content
    assert b"Quote Intelligence" in home.content

    photo = client.get("/photo")
    assert photo.status_code == 200
    assert b"Photo Editor" in photo.content

    quotes_page = client.get("/quotes")
    assert quotes_page.status_code == 200
    assert b"Compare quotes" in quotes_page.content

    health = client.get("/api/health").json()
    assert health["ok"] is True
    assert "quotes" in health["apps"]

    bad = client.post(
        "/api/quotes/compare",
        files={
            "left": ("a.pdf", b"not a pdf", "application/pdf"),
            "right": ("b.pdf", write_text_pdf(QUOTE_B), "application/pdf"),
        },
    )
    assert bad.status_code == 400

    compared = client.post(
        "/api/quotes/compare",
        files={
            "left": ("Quote_A.pdf", write_text_pdf(QUOTE_A), "application/pdf"),
            "right": ("Quote_B.pdf", write_text_pdf(QUOTE_B), "application/pdf"),
        },
        data={"project": "Dryer package"},
    )
    assert compared.status_code == 200
    data = compared.json()
    assert data["left"]["vendor"] == "Piovan"
    assert data["matches"]
    assert data["comparison_id"]
    chat = client.post(
        f"/api/quotes/{data['comparison_id']}/chat",
        json={"question": "Why is Quote B cheaper?"},
    )
    assert chat.status_code == 200
    assert chat.json()["answer"]
