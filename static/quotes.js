(() => {
  const state = { left: null, right: null, comparison: null };

  const els = {
    compareBtn: document.getElementById("compareBtn"),
    projectName: document.getElementById("projectName"),
    fileLeft: document.getElementById("fileLeft"),
    fileRight: document.getElementById("fileRight"),
    dropLeft: document.getElementById("dropLeft"),
    dropRight: document.getElementById("dropRight"),
    nameLeft: document.getElementById("nameLeft"),
    nameRight: document.getElementById("nameRight"),
    metaLeft: document.getElementById("metaLeft"),
    metaRight: document.getElementById("metaRight"),
    results: document.getElementById("results"),
    kpiRow: document.getElementById("kpiRow"),
    headline: document.getElementById("headline"),
    recommendation: document.getElementById("recommendation"),
    bothQuoted: document.getElementById("bothQuoted"),
    leftIncludes: document.getElementById("leftIncludes"),
    rightScope: document.getElementById("rightScope"),
    matchTable: document.querySelector("#matchTable tbody"),
    missing: document.getElementById("missing"),
    added: document.getElementById("added"),
    functionNotes: document.getElementById("functionNotes"),
    functionShared: document.getElementById("functionShared"),
    drawings: document.getElementById("drawings"),
    savings: document.getElementById("savings"),
    chatLog: document.getElementById("chatLog"),
    chatForm: document.getElementById("chatForm"),
    chatInput: document.getElementById("chatInput"),
    status: document.getElementById("status"),
    busy: document.getElementById("busy"),
    busyText: document.getElementById("busyText"),
  };

  function money(value) {
    const n = Number(value) || 0;
    const sign = n < 0 ? "-" : "";
    return `${sign}$${Math.abs(n).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
  }

  function setStatus(text) {
    els.status.textContent = text || "";
  }

  function setBusy(on, text) {
    els.busy.classList.toggle("hidden", !on);
    if (text) els.busyText.textContent = text;
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

  function assignFile(side, file) {
    if (!file) return;
    const name = file.name || "quote.pdf";
    if (!name.toLowerCase().endsWith(".pdf") && file.type !== "application/pdf") {
      setStatus("Please choose a PDF quote.");
      return;
    }
    state[side] = file;
    const label = side === "left" ? els.nameLeft : els.nameRight;
    const meta = side === "left" ? els.metaLeft : els.metaRight;
    const drop = side === "left" ? els.dropLeft : els.dropRight;
    label.textContent = name;
    meta.textContent = `${Math.max(1, Math.round(file.size / 1024))} KB ready`;
    drop.classList.add("has-file");
    els.compareBtn.disabled = !(state.left && state.right);
    setStatus(state.left && state.right ? "Ready to compare quotes." : "Add the other quote PDF.");
  }

  function itemLabel(item) {
    if (!item) return "—";
    const sku = item.sku ? `${item.sku} · ` : "";
    return `${sku}${item.description} (${item.qty || 1} @ ${money(item.unit_price || item.ext_price)})`;
  }

  function render(data) {
    state.comparison = data;
    els.results.classList.remove("hidden");
    const totals = data.totals || {};
    els.kpiRow.innerHTML = `
      <div class="kpi"><span>Quote A</span><strong>${money(totals.left)}</strong><small>${data.left.vendor || "Vendor A"} ${data.left.quote_number || ""}</small></div>
      <div class="kpi"><span>Quote B</span><strong>${money(totals.right)}</strong><small>${data.right.vendor || "Vendor B"} ${data.right.quote_number || ""}</small></div>
      <div class="kpi ${totals.difference < 0 ? "down" : totals.difference > 0 ? "up" : ""}"><span>Difference</span><strong>${money(totals.difference)}</strong><small>${totals.percent}% vs Quote A</small></div>
    `;
    const summary = data.summary || {};
    els.headline.textContent = summary.headline || "";
    els.recommendation.textContent = summary.recommendation || "";
    fillList(els.bothQuoted, summary.both_quoted, "No shared equipment yet.");
    fillList(els.leftIncludes, summary.left_includes, "No extra scope on Quote A.");
    const rightScope = [];
    if (summary.right_excludes?.length) rightScope.push("Excludes: " + summary.right_excludes.join(", "));
    if (summary.right_includes?.length) rightScope.push("Adds: " + summary.right_includes.join(", "));
    fillList(els.rightScope, rightScope, "No unique scope on Quote B.");

    els.matchTable.innerHTML = "";
    for (const row of data.matches || []) {
      const tr = document.createElement("tr");
      const conf = Math.round((row.confidence || 0) * 100);
      const delta = row.price_delta || 0;
      tr.innerHTML = `<td>${itemLabel(row.left)}</td><td>${itemLabel(row.right)}</td><td>${conf}%</td><td class="${delta < 0 ? "down" : delta > 0 ? "up" : ""}">${delta ? money(delta) : "same"}</td>`;
      els.matchTable.appendChild(tr);
    }
    if (!(data.matches || []).length) {
      const tr = document.createElement("tr");
      tr.innerHTML = `<td colspan="4">No confident equipment matches.</td>`;
      els.matchTable.appendChild(tr);
    }

    fillList(
      els.missing,
      (data.missing_in_right || []).map((row) => itemLabel(row.left)),
      "Nothing missing."
    );
    fillList(
      els.added,
      (data.added_in_right || []).map((row) => itemLabel(row.right)),
      "Nothing added."
    );

    const fn = data.functions || {};
    els.functionNotes.textContent = (fn.notes || []).join(". ") || "Configurations cover the same functions.";
    els.functionShared.textContent = `Both systems provide: ${(fn.shared || []).join(", ") || "—"}.`;
    fillList(els.drawings, data.drawings?.highlights || [], "No drawing callouts found.");
    fillList(
      els.savings,
      (data.savings || []).map(
        (row) =>
          `${row.sku}: previous ${money(row.previous_price)} → current ${money(row.current_price)} (${row.increase_pct}%). ${ (row.reasons || []).join(", ")}`
      ),
      "No historical price increase stored for these SKUs yet."
    );
    els.chatLog.innerHTML = "";
    addChat("assistant", "Ask why a quote is cheaper, what was excluded, or how the drying/storage scope differs.");
  }

  function addChat(role, text) {
    const div = document.createElement("div");
    div.className = `chat-bubble ${role}`;
    div.textContent = text;
    els.chatLog.appendChild(div);
    els.chatLog.scrollTop = els.chatLog.scrollHeight;
  }

  async function compare() {
    if (!state.left || !state.right) return;
    const body = new FormData();
    body.append("left", state.left);
    body.append("right", state.right);
    body.append("project", els.projectName.value || "Quote comparison");
    setBusy(true, "Matching equipment and pricing…");
    try {
      const res = await fetch("/api/quotes/compare", { method: "POST", body });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || res.statusText);
      render(data);
      setStatus("Comparison ready. Ask the assistant follow-up questions.");
    } catch (err) {
      setStatus(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function chat(event) {
    event.preventDefault();
    if (!state.comparison?.comparison_id) return;
    const question = els.chatInput.value.trim();
    if (!question) return;
    els.chatInput.value = "";
    addChat("user", question);
    try {
      const res = await fetch(`/api/quotes/${state.comparison.comparison_id}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || res.statusText);
      addChat("assistant", data.answer || "");
    } catch (err) {
      addChat("assistant", err.message);
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
  els.chatForm.addEventListener("submit", chat);
  bindDrop(els.dropLeft, "left");
  bindDrop(els.dropRight, "right");
  window.addEventListener("dragover", (event) => event.preventDefault());
  window.addEventListener("drop", (event) => event.preventDefault());
})();
