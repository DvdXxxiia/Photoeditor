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


def test_office_pages_and_pdf_compare():
    from office.pdf import write_text_pdf

    left_text = (
        "The office opens at 9 AM. Staff must badge in at the lobby. Lunch is served at noon. "
        "Visitors sign the front desk log."
    )
    right_text = (
        "The office opens at 10 AM. Staff must badge in at the lobby. Remote work is allowed on Friday. "
        "Visitors sign the front desk log."
    )

    client = TestClient(app_module.app)
    home = client.get("/")
    assert home.status_code == 200
    assert b"Office Applications" in home.content
    assert b"PDF Compare" in home.content

    photo = client.get("/photo")
    assert photo.status_code == 200
    assert b"Photo Editor" in photo.content

    pdf_page = client.get("/pdf")
    assert pdf_page.status_code == 200
    assert b"Summarize" in pdf_page.content

    health = client.get("/api/health").json()
    assert health["ok"] is True
    assert "pdf" in health["apps"]

    bad = client.post(
        "/api/pdf/compare",
        files={
            "left": ("a.pdf", b"not a pdf", "application/pdf"),
            "right": ("b.pdf", write_text_pdf(right_text), "application/pdf"),
        },
    )
    assert bad.status_code == 400

    compared = client.post(
        "/api/pdf/compare",
        files={
            "left": ("hours-a.pdf", write_text_pdf(left_text), "application/pdf"),
            "right": ("hours-b.pdf", write_text_pdf(right_text), "application/pdf"),
        },
    )
    assert compared.status_code == 200
    data = compared.json()
    assert data["left"]["filename"] == "hours-a.pdf"
    assert data["right"]["filename"] == "hours-b.pdf"
    assert data["only_in_left"]
    assert data["only_in_right"]
    assert 0 <= data["similarity"] < 1
