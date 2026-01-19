// js/modules/items_explorer.js
window.ItemsExplorer = (function () {
  let dataTable = null;

  function escapeHtml(str) {
    return String(str ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function setStatus(text) {
    const el = document.getElementById("ix-status");
    if (el) el.textContent = text || "";
  }

  function initTooltips() {
    // Important: info bubbles explain what each control/number means (2–3 lines)
    const list = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    list.forEach(el => new bootstrap.Tooltip(el));
  }

  function getValue(id) {
    const el = document.getElementById(id);
    return el ? el.value : "";
  }

  function buildQueryString() {
    const params = new URLSearchParams();

    params.set("q", getValue("ix-search").trim());
    params.set("days", getValue("ix-days"));
    params.set("trend", getValue("ix-trend"));
    params.set("subgroup", getValue("ix-subgroup").trim());
    params.set("limit", getValue("ix-limit"));

    return params.toString();
  }

  async function fetchData() {
    const qs = buildQueryString();
    const url = `/api/items/explorer?${qs}`;

    setStatus("Loading...");
    const res = await fetch(url);
    if (!res.ok) {
      setStatus("Failed to load");
      return [];
    }
    const data = await res.json();
    setStatus("");
    return Array.isArray(data) ? data : [];
  }

  function trendBadge(trend) {
    // Visual signal + short meaning (no math here; details belong to Item 360 later)
    if (trend === "up") return `<span class="badge text-bg-success">↑ Rising</span>`;
    if (trend === "down") return `<span class="badge text-bg-danger">↓ Falling</span>`;
    return `<span class="badge text-bg-secondary">→ Flat</span>`;
  }

  function renderTable(rows) {
    const tableEl = document.getElementById("ix-table");
    const countEl = document.getElementById("ix-count");
    if (!tableEl) return;

    // Destroy DataTables cleanly between runs (table updates must be reliable)
    if ($.fn.dataTable.isDataTable(tableEl)) {
      $(tableEl).DataTable().destroy();
    }

    const tbody = tableEl.querySelector("tbody");
    tbody.innerHTML = "";

    rows.forEach(r => {
      const itemTitle = r.item || r.item_code;
      const itemCell = `
        <div class="fw-semibold">${escapeHtml(itemTitle)}</div>
        <div class="text-secondary small">${escapeHtml(r.item_code || "")}</div>
      `;

      const action = `
        <a class="btn btn-sm btn-outline-primary"
           href="/items/360/${encodeURIComponent(r.item_code)}"
           title="Open Item 360° (coming next)">
          <i class="bi bi-eye"></i> View
        </a>
      `;

      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${itemCell}</td>
        <td>${escapeHtml(r.subgroup || "")}</td>
        <td class="text-end">${Number(r.avg_per_day || 0).toFixed(2)}</td>
        <td>${escapeHtml(r.last_sold || "")}</td>
        <td>${trendBadge(r.trend)}</td>
        <td class="text-end">${action}</td>
      `;
      tbody.appendChild(tr);
    });

    if (countEl) countEl.textContent = `${rows.length} items`;

    // DataTables gives sorting + search on rendered rows
    dataTable = $(tableEl).DataTable({
      pageLength: 25,
      order: [[2, "desc"]], // Avg/day desc by default
      destroy: true
    });
  }

  async function run() {
    try {
      const rows = await fetchData();
      renderTable(rows);
    } catch (e) {
      console.error(e);
      setStatus("Error");
    }
  }

  function reset() {
    document.getElementById("ix-search").value = "";
    document.getElementById("ix-days").value = "30";
    document.getElementById("ix-trend").value = "";
    document.getElementById("ix-subgroup").value = "";
    document.getElementById("ix-limit").value = "500";
    run();
  }

  function bindEvents() {
    document.getElementById("ix-run").addEventListener("click", run);

    // Enter key triggers search
    document.getElementById("ix-search").addEventListener("keydown", (e) => {
      if (e.key === "Enter") run();
    });

    document.getElementById("ix-reset").addEventListener("click", reset);
  }

  function init() {
    initTooltips();
    bindEvents();
    run(); // initial load
  }

  return { init };
})();
