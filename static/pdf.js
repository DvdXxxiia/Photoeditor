(() => {
  const state = { left: null, right: null };

  const els = {
    compareBtn: document.getElementById("compareBtn"),
    fileLeft: document.getElementById("fileLeft"),
    fileRight: document.getElementById("fileRight"),
    dropLeft: document.getElementById("dropLeft"),
    dropRight: document.getElementById("dropRight"),
    nameLeft: document.getElementById("nameLeft"),
    nameRight: document.getElementById("nameRight"),
    metaLeft: document.getElementById("metaLeft"),
    metaRight: document.getElementById("metaRight"),
    results: document.getElementById("results"),
    overview: document.getElementById("overview"),
    similarity: document.getElementById("similarity"),
    sumLeftTitle: document.getElementById("sumLeftTitle"),
    sumRightTitle: document.getElementById("sumRightTitle"),
    sumLeft: document.getElementById("sumLeft"),
    sumRight: document.getElementById("sumRight"),
    onlyLeft: document.getElementById("onlyLeft"),
    onlyRight: document.getElementById("onlyRight"),
    changes: document.getElementById("changes"),
    status: document.getElementById("status"),
    busy: document.getElementById("busy"),
    busyText: document.getElementById("busyText"),
  };

  function setStatus(text) {
    els.status.textContent = text || "";
  }

  function setBusy(on, text) {
    els.busy.classList.toggle("hidden", !on);
    if (text) els.busyText.textContent = text;
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

  function updateCompareEnabled() {
    els.compareBtn.disabled = !(state.left && state.right);
  }

  function assignFile(side, file) {
    if (!file) return;
    const name = file.name || "document.pdf";
    if (!name.toLowerCase().endsWith(".pdf") && file.type !== "application/pdf") {
      setStatus("Please choose a PDF file.");
      return;
    }
    state[side] = file;
    const label = side === "left" ? els.nameLeft : els.nameRight;
    const meta = side === "left" ? els.metaLeft : els.metaRight;
    const drop = side === "left" ? els.dropLeft : els.dropRight;
    label.textContent = name;
    meta.textContent = `${Math.max(1, Math.round(file.size / 1024))} KB ready`;
    drop.classList.add("has-file");
    updateCompareEnabled();
    setStatus(state.left && state.right ? "Ready to summarize and compare." : "Add the other PDF.");
  }

  function fillList(ul, items, empty) {
    ul.innerHTML = "";
    if (!items || !items.length) {
      const li = document.createElement("li");
      li.className = "empty-item";
      li.textContent = empty;
      ul.appendChild(li);
      return;
    }
    for (const item of items) {
      const li = document.createElement("li");
      li.textContent = item;
      ul.appendChild(li);
    }
  }

  function render(data) {
    els.results.classList.remove("hidden");
    els.overview.textContent = data.overview || "";
    const pct = Math.round((data.similarity || 0) * 100);
    const backend = data.backend === "openai" ? "GPT-4o" : "built-in comparison";
    els.similarity.textContent = `${pct}% similar · ${backend}`;
    els.sumLeftTitle.textContent = `Summary · ${data.left.filename} (${data.left.pages} page${data.left.pages === 1 ? "" : "s"}, ${data.left.words} words)`;
    els.sumRightTitle.textContent = `Summary · ${data.right.filename} (${data.right.pages} page${data.right.pages === 1 ? "" : "s"}, ${data.right.words} words)`;
    fillList(els.sumLeft, data.left.summary, "No summary available.");
    fillList(els.sumRight, data.right.summary, "No summary available.");
    fillList(els.onlyLeft, data.only_in_left, "Nothing unique in the first PDF.");
    fillList(els.onlyRight, data.only_in_right, "Nothing unique in the second PDF.");
    els.changes.innerHTML = "";
    if (!data.changes || !data.changes.length) {
      const p = document.createElement("p");
      p.className = "hint";
      p.textContent = "No reworded statements were found.";
      els.changes.appendChild(p);
    } else {
      for (const change of data.changes) {
        const row = document.createElement("div");
        row.className = "change-row";
        row.innerHTML = `<div><span>First</span><p>${escapeHtml(change.left)}</p></div><div><span>Second</span><p>${escapeHtml(change.right)}</p></div>`;
        els.changes.appendChild(row);
      }
    }
  }

  async function compare() {
    if (!state.left || !state.right) return;
    const body = new FormData();
    body.append("left", state.left);
    body.append("right", state.right);
    setBusy(true, "Summarizing and comparing…");
    try {
      const res = await fetch("/api/pdf/compare", { method: "POST", body });
      let data;
      try {
        data = await res.json();
      } catch {
        data = {};
      }
      if (!res.ok) throw new Error(data.detail || res.statusText);
      render(data);
      setStatus("Comparison ready.");
    } catch (err) {
      setStatus(err.message);
    } finally {
      setBusy(false);
    }
  }

  function bindDrop(drop, side) {
    drop.addEventListener("dragover", (event) => {
      event.preventDefault();
      drop.classList.add("dragover");
    });
    drop.addEventListener("dragleave", () => drop.classList.remove("dragover"));
    drop.addEventListener("drop", (event) => {
      event.preventDefault();
      drop.classList.remove("dragover");
      assignFile(side, event.dataTransfer?.files?.[0]);
    });
  }

  els.fileLeft.addEventListener("change", (event) => assignFile("left", event.target.files[0]));
  els.fileRight.addEventListener("change", (event) => assignFile("right", event.target.files[0]));
  els.compareBtn.addEventListener("click", compare);
  bindDrop(els.dropLeft, "left");
  bindDrop(els.dropRight, "right");

  window.addEventListener("dragover", (event) => event.preventDefault());
  window.addEventListener("drop", (event) => event.preventDefault());
})();
