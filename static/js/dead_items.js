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
    // Avoid crashing if Bootstrap JS isn't loaded for some reason
    if (!window.bootstrap || !window.bootstrap.Tooltip) return;
    const list = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    list.forEach(el => new bootstrap.Tooltip(el));
  }

  function getFilters() {
    return {
      q: (qs("di-q")?.value || "").trim(),
      subgroup: (qs("di-subgroup")?.value || "").trim(),
      dead_days: (qs("di-dead-days")?.value || "60").trim()
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
    const filters = getFilters();
    const url = buildUrl("/api/reports/dead-items", {
      q: filters.q,
      subgroup: filters.subgroup,
      dead_days: filters.dead_days,
      page: pageNumber,
      page_size: pageSize
    });

    setStatus("Loading...");
    const res = await fetch(url);
    if (!res.ok) {
      setStatus("Failed to load");
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
      const itemTitle = r.item_title || r.item_code;
      const lastSold = r.last_sold || "—";
      const daysSince = (r.days_since_sold === null || r.days_since_sold === undefined)
        ? "—"
        : Number(r.days_since_sold).toLocaleString();

      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>
          <div class="fw-semibold">${escapeHtml(itemTitle)}</div>
          <div class="text-secondary small">${escapeHtml(r.item_code || "")}</div>
        </td>
        <td>${escapeHtml(r.subgroup || "")}</td>
        <td>${escapeHtml(lastSold)}</td>
        <td class="text-end">${escapeHtml(daysSince)}</td>
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
    qs("di-q").value = "";
    qs("di-subgroup").value = "";
    qs("di-dead-days").value = "60";
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

    // Enter key in search triggers run
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
