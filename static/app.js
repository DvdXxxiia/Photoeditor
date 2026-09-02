(() => {
  const state = {
    sessionId: null,
    width: 0,
    height: 0,
    filename: "photo.png",
    objects: [],
    selectedId: null,
    tool: "select",
    drawing: false,
    lastPoint: null,
    boxStart: null,
    imageVersion: 0,
  };

  const els = {
    fileInput: document.getElementById("fileInput"),
    fileInputEmpty: document.getElementById("fileInputEmpty"),
    identifyBtn: document.getElementById("identifyBtn"),
    undoBtn: document.getElementById("undoBtn"),
    redoBtn: document.getElementById("redoBtn"),
    downloadBtn: document.getElementById("downloadBtn"),
    deleteBtn: document.getElementById("deleteBtn"),
    clearDrawBtn: document.getElementById("clearDrawBtn"),
    flattenBtn: document.getElementById("flattenBtn"),
    emptyState: document.getElementById("emptyState"),
    stage: document.getElementById("stage"),
    stageWrap: document.getElementById("stageWrap"),
    photo: document.getElementById("photo"),
    overlay: document.getElementById("overlay"),
    drawCanvas: document.getElementById("drawCanvas"),
    uiCanvas: document.getElementById("uiCanvas"),
    objectList: document.getElementById("objectList"),
    objectHint: document.getElementById("objectHint"),
    adjustSection: document.getElementById("adjustSection"),
    color: document.getElementById("color"),
    brushSize: document.getElementById("brushSize"),
    brushOpacity: document.getElementById("brushOpacity"),
    brightness: document.getElementById("brightness"),
    contrast: document.getElementById("contrast"),
    saturation: document.getElementById("saturation"),
    status: document.getElementById("status"),
    busy: document.getElementById("busy"),
    busyText: document.getElementById("busyText"),
  };

  const drawCtx = els.drawCanvas.getContext("2d");
  const uiCtx = els.uiCanvas.getContext("2d");

  function setStatus(text) {
    els.status.textContent = text || "";
  }

  function setBusy(on, text) {
    els.busy.classList.toggle("hidden", !on);
    if (text) els.busyText.textContent = text;
  }

  async function api(path, options = {}) {
    const res = await fetch(path, options);
    if (!res.ok) {
      let detail = res.statusText;
      try {
        const data = await res.json();
        detail = data.detail || detail;
      } catch {
        /* ignore */
      }
      throw new Error(detail);
    }
    const type = res.headers.get("content-type") || "";
    if (type.includes("application/json")) return res.json();
    return res;
  }

  function applySession(data, extra = {}) {
    state.sessionId = data.session_id;
    state.width = data.width;
    state.height = data.height;
    state.filename = data.filename || state.filename;
    state.objects = data.objects || [];
    if (extra.clearSelection) state.selectedId = null;
    if (data.selected_id) state.selectedId = data.selected_id;
    if (state.selectedId && !state.objects.some((o) => o.id === state.selectedId)) {
      state.selectedId = null;
    }
    els.undoBtn.disabled = !data.can_undo;
    els.redoBtn.disabled = !data.can_redo;
    els.identifyBtn.disabled = false;
    els.downloadBtn.disabled = false;
    els.clearDrawBtn.disabled = false;
    els.flattenBtn.disabled = false;
    els.deleteBtn.disabled = !state.selectedId;
    els.adjustSection.classList.toggle("disabled-block", !state.selectedId);
    renderObjects();
    fitStage();
  }

  function renderObjects() {
    els.objectList.innerHTML = "";
    if (!state.objects.length) {
      els.objectHint.textContent = "Identify objects or select a region with the wand or box tool.";
      return;
    }
    els.objectHint.textContent = `${state.objects.length} object${state.objects.length === 1 ? "" : "s"} found. Click one to edit or delete it.`;
    for (const obj of state.objects) {
      const li = document.createElement("li");
      li.className = obj.id === state.selectedId ? "selected" : "";
      const swatch = document.createElement("span");
      swatch.className = "swatch";
      swatch.style.background = `rgb(${obj.color.join(",")})`;
      const label = document.createElement("div");
      label.innerHTML = `<div>${escapeHtml(obj.label)}</div><small>${Math.round(obj.confidence * 100)}% · ${obj.source}</small>`;
      li.append(swatch, label);
      li.addEventListener("click", () => selectObject(obj.id));
      els.objectList.appendChild(li);
    }
  }

  function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, (ch) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    })[ch]);
  }

  function fitStage() {
    if (!state.width || !state.height) return;
    const pad = 40;
    const maxW = Math.max(120, els.stageWrap.clientWidth - pad);
    const maxH = Math.max(120, els.stageWrap.clientHeight - pad);
    const scale = Math.min(maxW / state.width, maxH / state.height);
    els.stage.style.width = `${Math.floor(state.width * scale)}px`;
    els.stage.style.height = `${Math.floor(state.height * scale)}px`;
    for (const canvas of [els.drawCanvas, els.uiCanvas]) {
      if (canvas.width !== state.width || canvas.height !== state.height) {
        canvas.width = state.width;
        canvas.height = state.height;
      }
    }
  }

  function refreshImages() {
    if (!state.sessionId) return;
    state.imageVersion += 1;
    const v = state.imageVersion;
    els.photo.src = `/api/session/${state.sessionId}/image?t=${v}`;
    const selected = state.selectedId ? `&selected=${encodeURIComponent(state.selectedId)}` : "";
    els.overlay.src = `/api/session/${state.sessionId}/overlay?t=${v}${selected}`;
  }

  function imagePoint(event, target) {
    const rect = target.getBoundingClientRect();
    const x = ((event.clientX - rect.left) / rect.width) * state.width;
    const y = ((event.clientY - rect.top) / rect.height) * state.height;
    return {
      x: Math.max(0, Math.min(state.width - 1, x)),
      y: Math.max(0, Math.min(state.height - 1, y)),
    };
  }

  function hexToRgb(hex) {
    const n = hex.replace("#", "");
    return [
      parseInt(n.slice(0, 2), 16),
      parseInt(n.slice(2, 4), 16),
      parseInt(n.slice(4, 6), 16),
    ];
  }

  function brushStyle() {
    const [r, g, b] = hexToRgb(els.color.value);
    const a = Number(els.brushOpacity.value) / 100;
    return {
      color: `rgba(${r}, ${g}, ${b}, ${a})`,
      size: Number(els.brushSize.value),
    };
  }

  function drawStroke(from, to) {
    const { color, size } = brushStyle();
    drawCtx.save();
    if (state.tool === "eraser") {
      drawCtx.globalCompositeOperation = "destination-out";
      drawCtx.strokeStyle = "rgba(0,0,0,1)";
    } else {
      drawCtx.globalCompositeOperation = "source-over";
      drawCtx.strokeStyle = color;
    }
    drawCtx.lineCap = "round";
    drawCtx.lineJoin = "round";
    drawCtx.lineWidth = size;
    drawCtx.beginPath();
    drawCtx.moveTo(from.x, from.y);
    drawCtx.lineTo(to.x, to.y);
    drawCtx.stroke();
    drawCtx.restore();
  }

  function clearUi() {
    uiCtx.clearRect(0, 0, els.uiCanvas.width, els.uiCanvas.height);
  }

  async function uploadFile(file) {
    if (!file) return;
    const body = new FormData();
    body.append("file", file);
    setBusy(true, "Loading photo…");
    try {
      const data = await api("/api/session", { method: "POST", body });
      applySession(data, { clearSelection: true });
      drawCtx.clearRect(0, 0, els.drawCanvas.width, els.drawCanvas.height);
      els.emptyState.classList.add("hidden");
      els.stage.classList.remove("hidden");
      refreshImages();
      setStatus(`${file.name} · ${data.width}×${data.height}`);
    } catch (err) {
      setStatus(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function identify() {
    if (!state.sessionId) return;
    setBusy(true, "Identifying objects…");
    try {
      const data = await api(`/api/session/${state.sessionId}/detect`, { method: "POST" });
      applySession(data, { clearSelection: true });
      refreshImages();
      setStatus(
        data.count
          ? `Found ${data.count} object${data.count === 1 ? "" : "s"}. Select one to edit or delete.`
          : "No objects found. Try the wand or box tool."
      );
    } catch (err) {
      setStatus(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function selectObject(id) {
    state.selectedId = id;
    els.deleteBtn.disabled = !id;
    els.adjustSection.classList.toggle("disabled-block", !id);
    renderObjects();
    refreshImages();
  }

  async function modify(operation, amount, extra = {}) {
    if (!state.sessionId || !state.selectedId) return;
    const payload = {
      object_id: state.selectedId,
      operation,
      amount: Number(amount) || 0,
      ...extra,
    };
    if (operation === "tint") payload.color = hexToRgb(els.color.value);
    setBusy(true, "Applying edit…");
    try {
      const data = await api(`/api/session/${state.sessionId}/modify`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      applySession(data);
      refreshImages();
      setStatus(`Applied ${operation} to ${state.selectedId}.`);
    } catch (err) {
      setStatus(err.message);
    } finally {
      setBusy(false);
      els.brightness.value = "0";
      els.contrast.value = "0";
      els.saturation.value = "0";
    }
  }

  async function deleteSelected() {
    if (!state.sessionId || !state.selectedId) return;
    setBusy(true, "Removing object…");
    try {
      const data = await api(`/api/session/${state.sessionId}/delete`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ object_id: state.selectedId }),
      });
      state.selectedId = null;
      applySession(data, { clearSelection: true });
      refreshImages();
      setStatus("Object removed and filled in.");
    } catch (err) {
      setStatus(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function undoRedo(kind) {
    if (!state.sessionId) return;
    try {
      const data = await api(`/api/session/${state.sessionId}/${kind}`, { method: "POST" });
      applySession(data);
      refreshImages();
      setStatus(kind === "undo" ? "Undid last photo edit." : "Redid last photo edit.");
    } catch (err) {
      setStatus(err.message);
    }
  }

  async function hitSelect(pt) {
    const data = await api(`/api/session/${state.sessionId}/hit?x=${pt.x}&y=${pt.y}`);
    if (data.object) {
      await selectObject(data.object.id);
      setStatus(`Selected ${data.object.label}.`);
    } else {
      await selectObject(null);
      setStatus("No object there. Identify objects, or use wand / box select.");
    }
  }

  async function wandSelect(pt) {
    setBusy(true, "Selecting region…");
    try {
      const data = await api(`/api/session/${state.sessionId}/wand`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ x: pt.x, y: pt.y, tolerance: 28 }),
      });
      applySession(data);
      refreshImages();
      setStatus("Magic wand selection added.");
    } catch (err) {
      setStatus(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function boxSelect(start, end) {
    const x = Math.min(start.x, end.x);
    const y = Math.min(start.y, end.y);
    const w = Math.abs(end.x - start.x);
    const h = Math.abs(end.y - start.y);
    if (w < 8 || h < 8) return;
    setBusy(true, "Cutting out selection…");
    try {
      const data = await api(`/api/session/${state.sessionId}/box-select`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ x, y, w, h, label: "Selection" }),
      });
      applySession(data);
      refreshImages();
      setStatus("Box selection added. You can modify or delete it.");
    } catch (err) {
      setStatus(err.message);
    } finally {
      setBusy(false);
    }
  }

  function download() {
    if (!state.sessionId) return;
    const canvas = document.createElement("canvas");
    canvas.width = state.width;
    canvas.height = state.height;
    const ctx = canvas.getContext("2d");
    ctx.drawImage(els.photo, 0, 0, state.width, state.height);
    ctx.drawImage(els.drawCanvas, 0, 0);
    const a = document.createElement("a");
    const base = state.filename.replace(/\.[^.]+$/, "") || "photo";
    a.download = `${base}-edited.png`;
    a.href = canvas.toDataURL("image/png");
    a.click();
  }

  async function flattenDrawing() {
    if (!state.sessionId) return;
    const overlay = els.drawCanvas.toDataURL("image/png");
    setBusy(true, "Merging drawing…");
    try {
      const data = await api(`/api/session/${state.sessionId}/flatten`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ overlay_png_base64: overlay }),
      });
      applySession(data);
      drawCtx.clearRect(0, 0, els.drawCanvas.width, els.drawCanvas.height);
      refreshImages();
      setStatus("Drawing merged into the photo.");
    } catch (err) {
      setStatus(err.message);
    } finally {
      setBusy(false);
    }
  }

  function setTool(tool) {
    state.tool = tool;
    document.querySelectorAll(".tool").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.tool === tool);
    });
    const cursors = {
      select: "default",
      wand: "crosshair",
      box: "crosshair",
      brush: "crosshair",
      eraser: "cell",
    };
    els.uiCanvas.style.cursor = cursors[tool] || "default";
  }

  els.uiCanvas.addEventListener("pointerdown", async (event) => {
    if (!state.sessionId) return;
    event.preventDefault();
    els.uiCanvas.setPointerCapture(event.pointerId);
    const pt = imagePoint(event, els.uiCanvas);
    if (state.tool === "brush" || state.tool === "eraser") {
      state.drawing = true;
      state.lastPoint = pt;
      drawStroke(pt, pt);
      return;
    }
    if (state.tool === "box") {
      state.boxStart = pt;
      return;
    }
    if (state.tool === "wand") {
      await wandSelect(pt);
      return;
    }
    await hitSelect(pt);
  });

  els.uiCanvas.addEventListener("pointermove", (event) => {
    if (!state.sessionId) return;
    const pt = imagePoint(event, els.uiCanvas);
    if (state.drawing && state.lastPoint) {
      drawStroke(state.lastPoint, pt);
      state.lastPoint = pt;
    }
    if (state.boxStart) {
      clearUi();
      const x = Math.min(state.boxStart.x, pt.x);
      const y = Math.min(state.boxStart.y, pt.y);
      const w = Math.abs(pt.x - state.boxStart.x);
      const h = Math.abs(pt.y - state.boxStart.y);
      uiCtx.strokeStyle = "#8b7cff";
      uiCtx.lineWidth = 2;
      uiCtx.setLineDash([6, 4]);
      uiCtx.strokeRect(x, y, w, h);
      uiCtx.fillStyle = "rgba(139, 124, 255, 0.12)";
      uiCtx.fillRect(x, y, w, h);
    }
  });

  async function endPointer(event) {
    if (state.drawing) {
      state.drawing = false;
      state.lastPoint = null;
    }
    if (state.boxStart) {
      const end = imagePoint(event, els.uiCanvas);
      const start = state.boxStart;
      state.boxStart = null;
      clearUi();
      await boxSelect(start, end);
    }
  }

  els.uiCanvas.addEventListener("pointerup", endPointer);
  els.uiCanvas.addEventListener("pointercancel", endPointer);

  document.querySelectorAll(".tool").forEach((btn) => {
    btn.addEventListener("click", () => setTool(btn.dataset.tool));
  });

  document.querySelectorAll("[data-op]").forEach((btn) => {
    btn.addEventListener("click", () => modify(btn.dataset.op, btn.dataset.amount || 100));
  });

  els.fileInput.addEventListener("change", (e) => uploadFile(e.target.files[0]));
  els.fileInputEmpty.addEventListener("change", (e) => uploadFile(e.target.files[0]));
  els.identifyBtn.addEventListener("click", identify);
  els.undoBtn.addEventListener("click", () => undoRedo("undo"));
  els.redoBtn.addEventListener("click", () => undoRedo("redo"));
  els.downloadBtn.addEventListener("click", download);
  els.deleteBtn.addEventListener("click", deleteSelected);
  els.clearDrawBtn.addEventListener("click", () => {
    drawCtx.clearRect(0, 0, els.drawCanvas.width, els.drawCanvas.height);
  });
  els.flattenBtn.addEventListener("click", flattenDrawing);

  ["brightness", "contrast", "saturation"].forEach((name) => {
    els[name].addEventListener("change", (event) => modify(name, event.target.value));
  });

  window.addEventListener("resize", fitStage);
  window.addEventListener("dragover", (e) => e.preventDefault());
  window.addEventListener("drop", (e) => {
    e.preventDefault();
    const file = e.dataTransfer?.files?.[0];
    if (file) uploadFile(file);
  });

  window.addEventListener("keydown", (event) => {
    if (["INPUT", "TEXTAREA"].includes(event.target.tagName)) return;
    const key = event.key.toLowerCase();
    if ((event.ctrlKey || event.metaKey) && key === "z") {
      event.preventDefault();
      undoRedo(event.shiftKey ? "redo" : "undo");
    } else if ((event.ctrlKey || event.metaKey) && key === "y") {
      event.preventDefault();
      undoRedo("redo");
    } else if (key === "delete" || key === "backspace") {
      if (state.selectedId) {
        event.preventDefault();
        deleteSelected();
      }
    } else if (key === "v") setTool("select");
    else if (key === "w") setTool("wand");
    else if (key === "m") setTool("box");
    else if (key === "b") setTool("brush");
    else if (key === "e") setTool("eraser");
  });

  setTool("select");
  setStatus("Upload a photo to begin.");
})();
