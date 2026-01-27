// static/js/modules/dead_items.js
window.DeadItemsModule = (function () {
  let currentPageNumber = 1;
  const pageSize = 50; // client preference; server caps anyway
  let lastTotalRows = 0;

  function qs(id) { return document.getElementById(id); }

  function escapeHtml(str) {
    return String(str ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function setStatus(msg) {
    const el = qs("di-status");
    if (el) el.textContent = msg || "";
  }

  function initTooltips() {
    // Avoid crashing if Bootstrap JS isn't loaded
    if (!window.bootstrap || !window.bootstrap.Tooltip) return;
    const list = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    list.forEach(el => new bootstrap.Tooltip(el));
  }

  function getFilters() {
    return {
      q: (qs("di-q")?.value || "").trim(),
      subgroup: (qs("di-subgroup")?.value || "").trim(),

      // NEW: “recently active window”
      lookback_days: (qs("di-lookback-days")?.value || "90").trim(),

      // “now dead window”
      dead_days: (qs("di-dead-days")?.value || "30").trim(),

      // Optional noise filters (if you add inputs later, they’ll work automatically)
      min_qty: (qs("di-min-qty")?.value || "").trim(),
      min_receipts: (qs("di-min-receipts")?.value || "").trim(),
    };
  }

  function buildUrl(base, params) {
    const u = new URL(base, window.location.origin);
    Object.entries(params || {}).forEach(([k, v]) => {
      if (v !== undefined && v !== null && String(v).length > 0) u.searchParams.set(k, v);
    });
    return u.toString();
  }

  async function fetchPage(pageNumber) {
    const f = getFilters();

    // ✅ Correct endpoint
    const url = buildUrl("/api/dead-items", {
      q: f.q,
      subgroup: f.subgroup,
      lookback_days: f.lookback_days,
      dead_days: f.dead_days,
      min_qty: f.min_qty,
      min_receipts: f.min_receipts,
      page: pageNumber,
      page_size: pageSize
    });

    setStatus("Loading...");
    const res = await fetch(url);

    if (!res.ok) {
      setStatus(`Failed to load (${res.status})`);
      return { total: 0, rows: [] };
    }

    const data = await res.json();
    setStatus("");
    return data && typeof data === "object" ? data : { total: 0, rows: [] };
  }

  function updatePagerUi() {
    const pageEl = qs("di-page");
    const countEl = qs("di-count");
    const prevBtn = qs("di-prev");
    const nextBtn = qs("di-next");

    const startRow = (currentPageNumber - 1) * pageSize + 1;
    const endRow = Math.min(currentPageNumber * pageSize, lastTotalRows);

    if (pageEl) pageEl.textContent = `Page ${currentPageNumber}`;
    if (countEl) {
      countEl.textContent = lastTotalRows === 0
        ? "0 results"
        : `Showing ${startRow}–${endRow} of ${lastTotalRows}`;
    }

    if (prevBtn) prevBtn.disabled = (currentPageNumber <= 1);
    if (nextBtn) nextBtn.disabled = (endRow >= lastTotalRows);
  }

  function renderRows(rows) {
    const tbody = qs("di-table")?.querySelector("tbody");
    if (!tbody) return;

    tbody.innerHTML = "";

    rows.forEach(r => {
      const itemTitle = r.item_title || r.item_code || "—";
      const subgroup = r.subgroup || "";
      const lastSold = r.last_sold || "—";

      // ✅ Correct field name from backend
      const daysSince = (r.days_since_last_sold === null || r.days_since_last_sold === undefined)
        ? "—"
        : Number(r.days_since_last_sold).toLocaleString();

      const qtyLookback = (r.qty_lookback === null || r.qty_lookback === undefined)
        ? "—"
        : Number(r.qty_lookback).toLocaleString(undefined, { maximumFractionDigits: 2 });

      const receiptsLookback = (r.receipts_lookback === null || r.receipts_lookback === undefined)
        ? "—"
        : Number(r.receipts_lookback).toLocaleString();

      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>
          <div class="fw-semibold">${escapeHtml(itemTitle)}</div>
          <div class="text-secondary small">${escapeHtml(r.item_code || "")}</div>
        </td>
        <td>${escapeHtml(subgroup)}</td>
        <td>${escapeHtml(lastSold)}</td>
        <td class="text-end">${escapeHtml(daysSince)}</td>
        <td class="text-end">${escapeHtml(qtyLookback)}</td>
        <td class="text-end">${escapeHtml(receiptsLookback)}</td>
      `;
      tbody.appendChild(tr);
    });
  }

  async function run(pageNumber) {
    const payload = await fetchPage(pageNumber);
    lastTotalRows = Number(payload.total || 0);
    currentPageNumber = pageNumber;

    renderRows(Array.isArray(payload.rows) ? payload.rows : []);
    updatePagerUi();
  }

  function reset() {
    if (qs("di-q")) qs("di-q").value = "";
    if (qs("di-subgroup")) qs("di-subgroup").value = "";
    if (qs("di-lookback-days")) qs("di-lookback-days").value = "90";
    if (qs("di-dead-days")) qs("di-dead-days").value = "30";
    if (qs("di-min-qty")) qs("di-min-qty").value = "";
    if (qs("di-min-receipts")) qs("di-min-receipts").value = "";
    run(1);
  }

  function bindEvents() {
    qs("di-run")?.addEventListener("click", () => run(1));
    qs("di-reset")?.addEventListener("click", reset);

    qs("di-prev")?.addEventListener("click", () => {
      if (currentPageNumber > 1) run(currentPageNumber - 1);
    });

    qs("di-next")?.addEventListener("click", () => {
      const endRow = Math.min(currentPageNumber * pageSize, lastTotalRows);
      if (endRow < lastTotalRows) run(currentPageNumber + 1);
    });

    // Enter key triggers run
    qs("di-q")?.addEventListener("keydown", (e) => {
      if (e.key === "Enter") run(1);
    });
  }

  function init() {
    initTooltips();
    bindEvents();
    run(1);
  }

  return { init };
})();
