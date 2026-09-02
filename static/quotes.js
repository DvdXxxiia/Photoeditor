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
    sourcingResults: document.getElementById("sourcingResults"),
    sourcingSummary: document.getElementById("sourcingSummary"),
    sourcingParts: document.getElementById("sourcingParts"),
    sourcingCosts: document.querySelector("#sourcingCosts tbody"),
    sourcingTryouts: document.querySelector("#sourcingTryouts tbody"),
    sourcingTerms: document.querySelector("#sourcingTerms tbody"),
    moldingResults: document.getElementById("moldingResults"),
    partComparisons: document.getElementById("partComparisons"),
    tryoutKpis: document.getElementById("tryoutKpis"),
    termsTable: document.querySelector("#termsTable tbody"),
    equipmentResults: document.getElementById("equipmentResults"),
    matchTable: document.querySelector("#matchTable tbody"),
    missing: document.getElementById("missing"),
    added: document.getElementById("added"),
    functionNotes: document.getElementById("functionNotes"),
    functionShared: document.getElementById("functionShared"),
    savings: document.getElementById("savings"),
    chatLog: document.getElementById("chatLog"),
    chatForm: document.getElementById("chatForm"),
    chatInput: document.getElementById("chatInput"),
    status: document.getElementById("status"),
    busy: document.getElementById("busy"),
    busyText: document.getElementById("busyText"),
    genericSummary: document.getElementById("genericSummary"),
  };

  function money(value) {
    const n = Number(value) || 0;
    const sign = n < 0 ? "-" : "";
    return `${sign}$${Math.abs(n).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
  }

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    })[ch]);
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

  function statusLabel(status) {
    const labels = {
      same: "Same",
      different: "Different",
      missing_in_b: "Missing in B",
      added_in_b: "Added in B",
      not_specified: "Not specified",
      matched: "Matched",
    };
    return labels[status] || status || "—";
  }

  function evidenceHtml(evidence) {
    if (!evidence?.text) return `<small class="source-evidence missing">No source evidence</small>`;
    return `<small class="source-evidence">Page ${Number(evidence.page) || 1}: “${escapeHtml(evidence.text)}”</small>`;
  }

  function sourcingValue(value, evidence, isMoney = false) {
    const rendered = value == null || value === ""
      ? "Not specified"
      : isMoney && typeof value === "number"
        ? money(value)
        : escapeHtml(value);
    return `<span>${rendered}</span>${evidenceHtml(evidence)}`;
  }

  function renderMatrixRows(tbody, rows, moneyValues = false) {
    tbody.innerHTML = "";
    for (const row of rows || []) {
      const tr = document.createElement("tr");
      tr.className = `field-${row.status}`;
      const difference = row.difference_amount == null
        ? row.difference
        : row.unit === "count"
          ? String(row.difference_amount)
          : money(row.difference_amount);
      const showMoney = (moneyValues || row.is_money) && row.unit !== "count";
      tr.innerHTML = `
        <th>${escapeHtml(row.label)}</th>
        <td>${sourcingValue(row.left, row.left_evidence, showMoney)}</td>
        <td>${sourcingValue(row.right, row.right_evidence, showMoney)}</td>
        <td>${escapeHtml(difference || "—")}</td>
        <td>${escapeHtml(row.higher_scope || "—")}</td>
        <td><span class="impact impact-${String(row.commercial_impact || "none").toLowerCase()}">${escapeHtml(row.commercial_impact || row.higher_scope || "—")}</span></td>
      `;
      tbody.appendChild(tr);
    }
  }

  function renderSourcing(sourcing) {
    els.sourcingResults.classList.remove("hidden");
    els.moldingResults.classList.add("hidden");
    els.equipmentResults.classList.add("hidden");
    if (els.genericSummary) els.genericSummary.classList.add("hidden");
    if (!sourcing) return true;

    const summary = sourcing.summary || {};
    const summaryItems = [
      ["Lowest tool cost", summary.lowest_tool_cost],
      ["Lowest tryout cost", summary.lowest_tryout_cost],
      ["Best technical scope", summary.best_technical_scope],
      ["Best commercial terms", summary.best_commercial_terms],
      ["Recommended vendor", summary.recommended_vendor],
    ];
    els.sourcingSummary.innerHTML = summaryItems.map(([label, value]) => `
      <div><span>${escapeHtml(label)}</span><strong>${escapeHtml(value || "Not specified")}</strong></div>
    `).join("");
    for (const [label, items] of [
      ["Missing from Vendor A", summary.missing_from_vendor_a],
      ["Missing from Vendor B", summary.missing_from_vendor_b],
      ["Potential risks", summary.potential_risks],
    ]) {
      const div = document.createElement("div");
      div.className = "summary-list";
      const title = document.createElement("span");
      title.textContent = label;
      const text = document.createElement("p");
      text.textContent = items?.length ? items.join("; ") : "None identified";
      div.append(title, text);
      els.sourcingSummary.appendChild(div);
    }

    els.sourcingParts.innerHTML = "";
    for (const part of sourcing.parts || []) {
      const card = document.createElement("section");
      card.className = "part-card";
      card.innerHTML = `
        <div class="part-card-header">
          <div><h3>${escapeHtml(part.part || "Unnamed part")}</h3>
          <small>${Math.round((part.match_confidence || 0) * 100)}% part match${part.part_number ? ` · ${escapeHtml(part.part_number)}` : ""}</small></div>
        </div>
        <div class="table-wrap">
          <table class="quote-table sourcing-table">
            <thead><tr><th>Category</th><th>Vendor A</th><th>Vendor B</th><th>Difference</th><th>Higher scope</th><th>Commercial impact</th></tr></thead>
            <tbody></tbody>
          </table>
        </div>
      `;
      const rows = [
        ...(part.technical || []),
        ...(part.costs || []).map((row) => ({ ...row, label: `Cost · ${row.label}`, is_money: true })),
      ];
      renderMatrixRows(card.querySelector("tbody"), rows);
      els.sourcingParts.appendChild(card);
    }
    renderMatrixRows(els.sourcingCosts, sourcing.costs, true);
    renderMatrixRows(els.sourcingTryouts, sourcing.tryouts, true);
    renderMatrixRows(els.sourcingTerms, sourcing.terms);
    return true;
  }

  function renderMolding(molding) {
    const detected = Boolean(molding?.detected);
    els.moldingResults.classList.toggle("hidden", !detected);
    els.equipmentResults.classList.toggle("hidden", detected);
    if (!detected) return;

    els.partComparisons.innerHTML = "";
    for (const part of molding.parts || []) {
      const card = document.createElement("section");
      card.className = "part-card";
      const price = part.price || {};
      card.innerHTML = `
        <div class="part-card-header">
          <div>
            <h3>${escapeHtml(part.name)}</h3>
            <small>${part.status === "matched" ? `${Math.round((part.match_confidence || 0) * 100)}% part match` : statusLabel(part.status)}</small>
          </div>
          <div class="part-price">
            <span>A ${money(price.left)}</span>
            <span>B ${money(price.right)}</span>
            <strong class="${price.difference < 0 ? "down" : price.difference > 0 ? "up" : ""}">${money(price.difference)}</strong>
          </div>
        </div>
        <div class="table-wrap">
          <table class="quote-table field-table">
            <thead><tr><th>Feature</th><th>Vendor A</th><th>Vendor B</th><th>Result</th></tr></thead>
            <tbody></tbody>
          </table>
        </div>
      `;
      const tbody = card.querySelector("tbody");
      for (const field of part.fields || []) {
        const tr = document.createElement("tr");
        tr.className = `field-${field.status}`;
        tr.innerHTML = `
          <th>${escapeHtml(field.label)}</th>
          <td>${escapeHtml(field.left || "Not specified")}</td>
          <td>${escapeHtml(field.right || "Not specified")}</td>
          <td><span class="comparison-status ${escapeHtml(field.status)}">${escapeHtml(statusLabel(field.status))}</span></td>
        `;
        tbody.appendChild(tr);
      }
      els.partComparisons.appendChild(card);
    }

    const tryouts = molding.tryouts || {};
    els.tryoutKpis.innerHTML = `
      <div class="kpi"><span>Vendor A tryouts</span><strong>${money(tryouts.left)}</strong></div>
      <div class="kpi"><span>Vendor B tryouts</span><strong>${money(tryouts.right)}</strong></div>
      <div class="kpi ${tryouts.difference < 0 ? "down" : tryouts.difference > 0 ? "up" : ""}">
        <span>Tryout difference</span><strong>${money(tryouts.difference)}</strong>
        <small>${tryouts.percent == null ? "—" : `${tryouts.percent}% vs Vendor A`}</small>
      </div>
    `;

    els.termsTable.innerHTML = "";
    for (const term of molding.terms || []) {
      const tr = document.createElement("tr");
      tr.className = `field-${term.status}`;
      tr.innerHTML = `
        <th>${escapeHtml(term.label)}</th>
        <td>${escapeHtml(term.left || "Not specified")}</td>
        <td>${escapeHtml(term.right || "Not specified")}</td>
        <td><span class="comparison-status ${escapeHtml(term.status)}">${escapeHtml(statusLabel(term.status))}</span></td>
      `;
      els.termsTable.appendChild(tr);
    }
  }

  function render(data) {
    state.comparison = data;
    els.results.classList.remove("hidden");
    const totals = data.totals || {};
    els.kpiRow.innerHTML = `
      <div class="kpi"><span>Quote A</span><strong>${money(totals.left)}</strong><small>${escapeHtml(data.left.vendor || "Vendor A")} ${escapeHtml(data.left.quote_number || "")}</small></div>
      <div class="kpi"><span>Quote B</span><strong>${money(totals.right)}</strong><small>${escapeHtml(data.right.vendor || "Vendor B")} ${escapeHtml(data.right.quote_number || "")}</small></div>
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
    renderMolding(data.molding);
    renderSourcing(data.sourcing);

    els.matchTable.innerHTML = "";
    for (const row of data.matches || []) {
      const tr = document.createElement("tr");
      const conf = Math.round((row.confidence || 0) * 100);
      const delta = row.price_delta || 0;
      tr.innerHTML = `<td>${escapeHtml(itemLabel(row.left))}</td><td>${escapeHtml(itemLabel(row.right))}</td><td>${conf}%</td><td class="${delta < 0 ? "down" : delta > 0 ? "up" : ""}">${delta ? money(delta) : "same"}</td>`;
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
    fillList(
      els.savings,
      (data.savings || []).map(
        (row) =>
          `${row.sku}: previous ${money(row.previous_price)} → current ${money(row.current_price)} (${row.increase_pct}%). ${ (row.reasons || []).join(", ")}`
      ),
      "No historical price increase stored for these SKUs yet."
    );
    els.chatLog.innerHTML = "";
    addChat("assistant", "Ask about cavities, steel, hot runners, technical scope, costs, tryouts, risks, or vendor terms.");
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
    setBusy(true, "Extracting sourcing matrix…");
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
