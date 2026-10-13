// Vanilla JS, no build step. Two flows: single label and batch.
(() => {
  "use strict";
  const $ = (sel) => document.querySelector(sel);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  const STATUS = {
    pass:    { icon: "✓", pill: "Match",        title: "Matches application" },
    review:  { icon: "!",      pill: "Check",        title: "Needs a quick look" },
    fail:    { icon: "✗", pill: "Problem",      title: "Does not match" },
    skipped: { icon: "–", pill: "Not checked",  title: "Nothing checked" },
    error:   { icon: "✗", pill: "Error",        title: "Could not process" },
  };

  // ---------- Tabs ----------
  const tabs = [["#tab-single", "#panel-single"], ["#tab-batch", "#panel-batch"]];
  tabs.forEach(([t, p]) => $(t).addEventListener("click", () => {
    tabs.forEach(([t2, p2]) => {
      const on = t2 === t;
      $(t2).setAttribute("aria-selected", on);
      $(p2).hidden = !on;
    });
  }));

  // ---------- Single: image picker ----------
  const imageInput = $("#image"), preview = $("#preview"), dropText = $("#drop-text"), drop = $("#drop");
  let currentFile = null;

  function setFile(file) {
    currentFile = file;
    if (!file) { preview.hidden = true; dropText.hidden = false; return; }
    preview.src = URL.createObjectURL(file);
    preview.alt = "Label preview: " + file.name;
    preview.hidden = false;
    dropText.hidden = true;
  }
  imageInput.addEventListener("change", () => setFile(imageInput.files[0] || null));
  ["dragenter", "dragover"].forEach((e) => drop.addEventListener(e, (ev) => { ev.preventDefault(); drop.classList.add("dragover"); }));
  ["dragleave", "drop"].forEach((e) => drop.addEventListener(e, () => drop.classList.remove("dragover")));
  drop.addEventListener("drop", (ev) => {
    ev.preventDefault();
    const f = ev.dataTransfer.files[0];
    if (f) setFile(f);
  });

  // ---------- Single: sample picker ----------
  const FIELDS = ["brand_name", "class_type", "alcohol_content", "net_contents", "bottler", "country_of_origin", "beverage_type"];
  let samples = [];
  fetch("/api/samples").then((r) => r.json()).then((rows) => {
    samples = rows;
    const sel = $("#sample-select");
    rows.forEach((r, i) => {
      const o = document.createElement("option");
      o.value = i;
      o.textContent = `${r.filename} — expect: ${r.expected_outcome}`;
      sel.appendChild(o);
    });
  }).catch(() => { $(".sample-bar").hidden = true; });

  $("#sample-select").addEventListener("change", async (ev) => {
    const row = samples[ev.target.value];
    if (!row) return;
    FIELDS.forEach((f) => { const el = $("#" + f); if (el) el.value = row[f] || (f === "beverage_type" ? "spirits" : ""); });
    if (row.bottler || row.country_of_origin) $(".optional").open = true;
    const blob = await (await fetch("/samples/" + encodeURIComponent(row.filename))).blob();
    setFile(new File([blob], row.filename, { type: blob.type }));
    $("#single-result").innerHTML = "";
  });

  // ---------- Single: submit ----------
  function showError(el, msg) { el.textContent = msg; el.hidden = !msg; }

  $("#single-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const errEl = $("#single-error"), out = $("#single-result"), btn = $("#check-btn");
    showError(errEl, "");
    if (!currentFile) { showError(errEl, "Please choose a label image first (step 1)."); return; }

    const fd = new FormData();
    fd.append("image", currentFile);
    FIELDS.forEach((f) => fd.append(f, ($("#" + f)?.value || "").trim()));

    btn.disabled = true; btn.textContent = "Checking…";
    out.innerHTML = "";
    try {
      const resp = await fetch("/api/verify", { method: "POST", body: fd });
      const data = await resp.json().catch(() => ({ error: "Unexpected server response." }));
      if (!resp.ok) throw new Error(data.error || "Something went wrong.");
      out.innerHTML = renderReport(data, true);
      out.scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (e) {
      showError(errEl, e.message === "Failed to fetch" ? "Couldn't reach the server. Check your connection and try again." : e.message);
    } finally {
      btn.disabled = false; btn.textContent = "Check label";
    }
  });

  $("#clear-btn").addEventListener("click", () => {
    $("#single-form").reset();
    $("#sample-select").value = "";
    setFile(null);
    $("#single-result").innerHTML = "";
    showError($("#single-error"), "");
  });

  // ---------- Rendering ----------
  function renderCheck(c) {
    const s = STATUS[c.status];
    const rows = [];
    if (c.expected && c.field !== "government_warning") rows.push(`<dt>Application</dt><dd>${esc(c.expected)}</dd>`);
    if (c.found) rows.push(`<dt>On label</dt><dd>${esc(c.found)}</dd>`);
    const details = (c.details || []).length ? `<ul>${c.details.map((d) => `<li>${esc(d)}</li>`).join("")}</ul>` : "";
    return `<li class="check ${c.status}">
      <div><span class="pill ${c.status}">${s.icon} ${s.pill}</span></div>
      <div><h4>${esc(c.label)}</h4><p class="msg">${esc(c.message)}</p>
        ${rows.length ? `<dl>${rows.join("")}</dl>` : ""}${details}</div>
    </li>`;
  }

  function renderReport(r, withBanner) {
    const s = STATUS[r.overall];
    const order = { fail: 0, review: 1, pass: 2, skipped: 3 };
    const checks = [...r.checks].sort((a, b) => order[a.status] - order[b.status]);
    return `<div class="result">
      ${withBanner ? `<div class="banner ${r.overall}" role="status">
        <span class="icon" aria-hidden="true">${s.icon}</span>
        <div><h3>${s.title}</h3><p>${esc(r.summary)} <span class="hint">(${(r.elapsed_ms / 1000).toFixed(1)} s)</span></p></div>
      </div>` : ""}
      <p class="quality">Image quality: <strong>${esc(r.image_quality)}</strong> — ${esc(r.image_quality_note)}</p>
      <ul class="checks">${checks.map(renderCheck).join("")}</ul>
      <details class="ocr"><summary>Show the text read from the label</summary><pre>${esc(r.ocr_text)}</pre></details>
    </div>`;
  }

  // ---------- Batch ----------
  $("#batch-images").addEventListener("change", (ev) => {
    const n = ev.target.files.length;
    $("#batch-image-count").textContent = n ? `${n} image${n === 1 ? "" : "s"} selected.` : "";
  });

  let pollTimer = null, lastJob = null, filterValue = "all";

  $("#batch-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const errEl = $("#batch-error"), btn = $("#batch-btn");
    showError(errEl, "");
    const images = $("#batch-images").files, manifest = $("#batch-manifest").files[0];
    if (!images.length) { showError(errEl, "Please select the label images (step 1)."); return; }
    if (!manifest) { showError(errEl, "Please add the application data CSV (step 2)."); return; }

    const fd = new FormData();
    [...images].forEach((f) => fd.append("images", f));
    fd.append("manifest", manifest);
    btn.disabled = true; btn.textContent = "Uploading…";
    $("#batch-result").innerHTML = "";
    try {
      const resp = await fetch("/api/batch", { method: "POST", body: fd });
      const data = await resp.json().catch(() => ({ error: "Unexpected server response." }));
      if (!resp.ok) throw new Error(data.error || "Something went wrong.");
      if (data.skipped?.length) showError(errEl, `Skipped unsupported files: ${data.skipped.join(", ")}`);
      $("#batch-progress").hidden = false;
      poll(data.id);
    } catch (e) {
      showError(errEl, e.message);
      btn.disabled = false; btn.textContent = "Check all labels";
    }
  });

  async function poll(id) {
    clearTimeout(pollTimer);
    try {
      const job = await (await fetch(`/api/batch/${id}`)).json();
      lastJob = job;
      const pct = job.total ? Math.round((job.completed / job.total) * 100) : 100;
      $("#bar").style.width = pct + "%";
      $("#progress-text").textContent = job.done
        ? `Done — checked ${job.total} label${job.total === 1 ? "" : "s"}.`
        : `Checking… ${job.completed} of ${job.total} done.`;
      renderBatch(job);
      if (!job.done) { pollTimer = setTimeout(() => poll(id), 1000); return; }
    } catch {
      $("#progress-text").textContent = "Lost connection while checking. Retrying…";
      pollTimer = setTimeout(() => poll(id), 2000);
      return;
    }
    const btn = $("#batch-btn");
    btn.disabled = false; btn.textContent = "Check all labels";
  }

  function itemStatus(i) { return i.status === "error" ? "error" : (i.result ? i.result.overall : "queued"); }

  function renderBatch(job) {
    const c = job.counts;
    const items = job.items
      .filter((i) => filterValue === "all" || itemStatus(i) === filterValue)
      .sort((a, b) => ({ fail: 0, error: 1, review: 2, pass: 3, queued: 4 }[itemStatus(a)] - { fail: 0, error: 1, review: 2, pass: 3, queued: 4 }[itemStatus(b)]));
    const rows = items.map((i, idx) => {
      const st = itemStatus(i);
      const pill = st === "queued" ? `<span class="pill skipped">Waiting</span>`
        : `<span class="pill ${st === "error" ? "fail" : st}">${STATUS[st].icon} ${STATUS[st].pill}</span>`;
      const issues = i.error ? esc(i.error) : i.result
        ? esc(i.result.checks.filter((k) => k.status === "fail" || k.status === "review").map((k) => k.label).join(", ") || "—")
        : "";
      return `<tr class="row" data-idx="${idx}" tabindex="0" aria-expanded="false"><td>${esc(i.filename)}</td><td>${pill}</td><td>${issues}</td></tr>`;
    }).join("");

    $("#batch-result").innerHTML = `
      <div class="counts">
        <span class="pill pass">${STATUS.pass.icon} ${c.pass} match</span>
        <span class="pill review">! ${c.review} to check</span>
        <span class="pill fail">${STATUS.fail.icon} ${c.fail} problem${c.fail === 1 ? "" : "s"}</span>
        ${c.error ? `<span class="pill fail">${c.error} error${c.error === 1 ? "" : "s"}</span>` : ""}
        <label for="filter" class="hint">Show:</label>
        <select id="filter" class="filter">
          ${["all", "fail", "review", "pass", "error"].map((v) => `<option value="${v}" ${v === filterValue ? "selected" : ""}>${{ all: "All", fail: "Problems", review: "To check", pass: "Matches", error: "Errors" }[v]}</option>`).join("")}
        </select>
        ${job.done ? `<a class="button" href="/api/batch/${job.id}/results.csv">Download results (CSV)</a>` : ""}
      </div>
      <div class="table-wrap"><table class="batch">
        <thead><tr><th>Label file</th><th>Result</th><th>Items to look at</th></tr></thead>
        <tbody>${rows}</tbody>
      </table></div>`;

    $("#filter").addEventListener("change", (e) => { filterValue = e.target.value; renderBatch(lastJob); });
    document.querySelectorAll("tr.row").forEach((tr) => {
      const toggle = () => {
        const next = tr.nextElementSibling;
        if (next && next.classList.contains("detail")) { next.remove(); tr.setAttribute("aria-expanded", "false"); return; }
        const item = items[+tr.dataset.idx];
        if (!item.result) return;
        tr.insertAdjacentHTML("afterend", `<tr class="detail"><td colspan="3">${renderReport(item.result, false)}</td></tr>`);
        tr.setAttribute("aria-expanded", "true");
      };
      tr.addEventListener("click", toggle);
      tr.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); } });
    });
  }
})();
