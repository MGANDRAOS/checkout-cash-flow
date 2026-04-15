// static/js/items_explorer.js
window.ItemsExplorer = (function () {

  // ── State ──────────────────────────────────────────────────────
  let dataTable = null;
  let itemSparklineChart = null;

  // ── Utilities ─────────────────────────────────────────────────
  function escapeHtml(str) {
    return String(str ?? "")
      .replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function getValue(id) {
    const el = document.getElementById(id);
    return el ? el.value : "";
  }

  function formatNumber(value) {
    const num = Number(value);
    if (!Number.isFinite(num)) return String(value ?? "—");
    return num.toLocaleString(undefined, { maximumFractionDigits: 2 });
  }

  function setStatus(text) {
    const el = document.getElementById("ix-status");
    if (el) el.textContent = text || "";
  }

  function trendBadge(trend) {
    if (trend === "up")   return `<span class="ix-badge ix-badge-up">↑ Rising</span>`;
    if (trend === "down") return `<span class="ix-badge ix-badge-down">↓ Falling</span>`;
    return                       `<span class="ix-badge ix-badge-flat">→ Flat</span>`;
  }

  // ── Filter helpers ────────────────────────────────────────────
  function buildQueryString() {
    const params = new URLSearchParams();
    params.set("q",        getValue("ix-search").trim());
    params.set("days",     getValue("ix-days"));
    params.set("trend",    getValue("ix-trend"));
    params.set("subgroup", getValue("ix-subgroup").trim());
    params.set("limit",    getValue("ix-limit"));
    return params.toString();
  }

  function getCurrentDaysFilter() {
    const parsed = parseInt(getValue("ix-days"), 10);
    return Number.isFinite(parsed) ? parsed : 30;
  }

  // ── Data fetching ─────────────────────────────────────────────
  async function fetchData() {
    const url = `/api/items/explorer?${buildQueryString()}`;
    setStatus("Loading…");
    const res = await fetch(url);
    if (!res.ok) { setStatus("Failed to load"); return []; }
    const data = await res.json();
    setStatus("");
    return Array.isArray(data) ? data : [];
  }

  async function fetchItemSeries(itemCode, days, lookback) {
    const url = `/api/items/explorer/item-series` +
      `?item_code=${encodeURIComponent(itemCode)}` +
      `&days=${encodeURIComponent(days)}` +
      `&lookback=${encodeURIComponent(lookback)}`;
    const res = await fetch(url);
    if (!res.ok) return [];
    const data = await res.json();
    return data.series || [];
  }

  async function fetchItemLastInvoices(itemCode, days, limit) {
    const url = `/api/items/360/invoices` +
      `?item_code=${encodeURIComponent(itemCode)}` +
      `&days=${encodeURIComponent(days)}` +
      `&limit=${encodeURIComponent(limit)}`;
    const res = await fetch(url);
    if (!res.ok) return { rows: [] };
    return await res.json();
  }

  async function fetchItemMomentumKpis(itemCode, days) {
    const url = `/api/items/360/kpis` +
      `?item_code=${encodeURIComponent(itemCode)}` +
      `&days=${encodeURIComponent(days)}`;
    const res = await fetch(url);
    if (!res.ok) return null;
    return await res.json();
  }

  // ── Table rendering ───────────────────────────────────────────
  function showTableLoading() {
    const tbody = document.querySelector("#ix-table tbody");
    if (tbody) tbody.innerHTML = `
      <tr class="ix-loading-row">
        <td colspan="6" class="text-center py-4" style="color:var(--text-3);">
          <div class="spinner-border spinner-border-sm me-2" role="status"></div>
          Loading items…
        </td>
      </tr>`;
  }

  function renderTable(rows) {
    const tableEl = document.getElementById("ix-table");
    const countEl = document.getElementById("ix-count");
    if (!tableEl) return;

    // Clean destroy
    if ($.fn.dataTable.isDataTable(tableEl)) {
      $(tableEl).DataTable().destroy();
      dataTable = null;
    }

    const tbody = tableEl.querySelector("tbody");
    tbody.innerHTML = "";

    if (rows.length === 0) {
      tbody.innerHTML = `
        <tr>
          <td colspan="6" class="text-center py-5" style="color:var(--text-3);font-size:0.88rem;">
            No items match the current filters.
          </td>
        </tr>`;
      if (countEl) countEl.textContent = "0";
      return;
    }

    rows.forEach(r => {
      const itemCell = `
        <div class="fw-semibold" style="font-size:0.88rem;color:var(--text);">${escapeHtml(r.item || r.item_code)}</div>
        <div style="font-size:0.75rem;color:var(--text-3);font-family:var(--font-mono);">${escapeHtml(r.item_code || "")}</div>`;

      const tr = document.createElement("tr");
      tr.style.cursor = "pointer";
      // Store all data on the row for the row-click handler
      tr.dataset.itemCode  = r.item_code  || "";
      tr.dataset.itemTitle = r.item       || r.item_code || "";
      tr.dataset.subgroup  = r.subgroup   || "";
      tr.dataset.avgPerDay = r.avg_per_day ?? "";
      tr.dataset.lastSold  = r.last_sold  || "";
      tr.dataset.totalQty  = r.total_qty  ?? "";

      tr.innerHTML = `
        <td>${itemCell}</td>
        <td style="font-size:0.82rem;color:var(--text-2);">${escapeHtml(r.subgroup || "—")}</td>
        <td class="text-end" style="font-family:var(--font-mono);font-size:0.85rem;">${Number(r.avg_per_day || 0).toFixed(2)}</td>
        <td style="font-size:0.82rem;color:var(--text-2);white-space:nowrap;">${escapeHtml(r.last_sold || "—")}</td>
        <td>${trendBadge(r.trend)}</td>
        <td class="text-end">
          <button type="button" class="btn btn-sm ix-view-btn" title="Open Item 360°">
            <i class="bi bi-eye"></i>
          </button>
        </td>`;
      tbody.appendChild(tr);
    });

    if (countEl) countEl.textContent = rows.length.toLocaleString();

    dataTable = $(tableEl).DataTable({
      pageLength: 25,
      order: [[2, "desc"]],
      destroy: true,
      columnDefs: [
        { orderable: false, targets: 5 }   // Action column not sortable
      ]
    });
  }

  // ── Item 360° drawer ──────────────────────────────────────────
  function openDrawerFromEl(el) {
    // Works from both tr (data attrs) and the view button inside it
    const tr = el.closest("tr[data-item-code]");
    if (!tr) return;
    const row = {
      item_code:   tr.dataset.itemCode,
      item:        tr.dataset.itemTitle,
      subgroup:    tr.dataset.subgroup,
      avg_per_day: tr.dataset.avgPerDay,
      last_sold:   tr.dataset.lastSold,
      total_qty:   tr.dataset.totalQty,
    };
    openItem360Drawer(row);
  }

  async function openItem360Drawer(row) {
    const itemCode    = row.item_code || "";
    const itemTitle   = row.item || row.item_code || "—";
    const subgroup    = row.subgroup || "—";
    const lastSold    = row.last_sold || "—";
    const totalQty    = row.total_qty;
    const avgPerDay   = row.avg_per_day;

    // ── Populate header
    document.getElementById("drawerItemTitle").textContent  = itemTitle;
    document.getElementById("drawerItemCode").textContent   = itemCode;
    document.getElementById("drawerSubgroup").textContent   = subgroup;

    // ── Summary KPIs
    document.getElementById("drawerLastSold").textContent   = lastSold;
    document.getElementById("drawerAvgPerDay").textContent  = formatNumber(avgPerDay);
    document.getElementById("drawerTotalQty").textContent   =
      (totalQty !== "" && totalQty !== undefined && totalQty !== null)
        ? formatNumber(totalQty) : "—";

    // ── Invoices link
    const seeAllBtn = document.getElementById("drawerSeeAllInvoices");
    if (seeAllBtn) {
      seeAllBtn.href = `/invoices?item_code=${encodeURIComponent(itemCode)}`;
    }

    // ── Reset async sections while loading
    resetSparkline();
    document.getElementById("drawerInvoicesTbody").innerHTML =
      `<tr><td colspan="4" class="ix-drawer-empty" style="color:var(--text-3);">
         <div class="spinner-border spinner-border-sm me-2"></div> Loading…
       </td></tr>`;
    document.getElementById("drawerInvoicesStatus").textContent = "";
    document.getElementById("drawerDaysSinceSold").textContent = "—";
    document.getElementById("drawerLastBizDateHint").textContent = "—";
    document.getElementById("drawerPeakHour").textContent = "—";
    document.getElementById("drawerPeakHourHint").textContent = "—";

    // ── Show drawer
    bootstrap.Offcanvas.getOrCreateInstance(
      document.getElementById("item360Drawer")
    ).show();

    // ── Fire all 3 async fetches
    const days = getCurrentDaysFilter();
    const [series, invoicesPayload, kpis] = await Promise.all([
      fetchItemSeries(itemCode, days, 14),
      fetchItemLastInvoices(itemCode, days, 10),
      fetchItemMomentumKpis(itemCode, days),
    ]);

    renderItemSparkline(series);
    renderItemInvoices(invoicesPayload.rows || []);
    renderItemMomentumKpis(kpis);
  }

  // ── Sparkline ─────────────────────────────────────────────────
  function resetSparkline() {
    if (itemSparklineChart) {
      itemSparklineChart.destroy();
      itemSparklineChart = null;
    }
  }

  function renderItemSparkline(series) {
    resetSparkline();
    if (!series || series.length === 0) return;

    // Abbreviated date labels  "Apr 14"
    const labels = series.map(x => {
      const d = new Date(x.biz_date + "T00:00:00");
      return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
    });
    const values = series.map(x => Number(x.qty || 0));

    const ctx = document.getElementById("itemSparkline").getContext("2d");

    itemSparklineChart = new Chart(ctx, {
      type: "line",
      data: {
        labels,
        datasets: [{
          label: "Qty",
          data: values,
          tension: 0.4,
          pointRadius: 0,
          pointHoverRadius: 5,
          borderWidth: 2,
          borderColor: "#2563EB",
          backgroundColor: "rgba(37,99,235,0.08)",
          fill: true,
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: ctx => ` ${formatNumber(ctx.parsed.y)} units`
            }
          }
        },
        scales: {
          x: {
            ticks: {
              font: { size: 10, family: "'DM Sans', sans-serif" },
              color: "#94A3B8",
              maxRotation: 0,
            },
            grid: { display: false },
          },
          y: {
            beginAtZero: true,
            ticks: {
              font: { size: 10, family: "'JetBrains Mono', monospace" },
              color: "#94A3B8",
            },
            grid: { color: "rgba(0,0,0,0.05)" },
          }
        }
      }
    });
  }

  // ── Invoices table ────────────────────────────────────────────
  function renderItemInvoices(rows) {
    const statusEl = document.getElementById("drawerInvoicesStatus");
    const tbody    = document.getElementById("drawerInvoicesTbody");
    if (!tbody) return;
    tbody.innerHTML = "";

    if (!rows || rows.length === 0) {
      if (statusEl) statusEl.textContent = "No invoices in this window.";
      tbody.innerHTML = `<tr><td colspan="4" class="ix-drawer-empty">No invoices found.</td></tr>`;
      return;
    }

    if (statusEl) statusEl.textContent = `Last ${rows.length}`;

    rows.forEach(r => {
      const qty    = Number(r.item_qty ?? 0);
      const amount = Number(r.rcpt_amount ?? 0);
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td style="white-space:nowrap;font-size:0.8rem;">${escapeHtml(r.biz_dt || "—")}</td>
        <td style="white-space:nowrap;font-size:0.8rem;font-family:var(--font-mono);">${escapeHtml(String(r.rcpt_id ?? "—"))}</td>
        <td class="text-end" style="font-family:var(--font-mono);font-size:0.8rem;">${Number.isFinite(qty) ? qty.toLocaleString() : "—"}</td>
        <td class="text-end" style="font-family:var(--font-mono);font-size:0.8rem;">${Number.isFinite(amount) ? amount.toLocaleString(undefined,{maximumFractionDigits:2}) : "—"}</td>`;
      tbody.appendChild(tr);
    });
  }

  // ── Momentum KPIs ─────────────────────────────────────────────
  function renderItemMomentumKpis(kpis) {
    const daysEl     = document.getElementById("drawerDaysSinceSold");
    const lastBizEl  = document.getElementById("drawerLastBizDateHint");
    const peakEl     = document.getElementById("drawerPeakHour");
    const peakHintEl = document.getElementById("drawerPeakHourHint");

    if (!kpis) {
      [daysEl, lastBizEl, peakEl, peakHintEl].forEach(el => { if (el) el.textContent = "—"; });
      return;
    }

    const daysSince  = kpis.days_since_last_sold;
    const lastBiz    = kpis.last_biz_date;
    const peakHour   = kpis.peak_hour;
    const peakQty    = kpis.peak_hour_qty;

    if (daysEl)     daysEl.textContent = (daysSince == null) ? "—" : String(daysSince);
    if (lastBizEl)  lastBizEl.textContent = lastBiz ? `Last sold: ${lastBiz}` : "—";

    if (peakEl) {
      if (peakHour == null) { peakEl.textContent = "—"; }
      else {
        const hh = String(peakHour).padStart(2, "0");
        peakEl.textContent = `${hh}:00`;
      }
    }
    if (peakHintEl) {
      peakHintEl.textContent = (peakQty == null) ? "—" : `${formatNumber(peakQty)} units`;
    }
  }

  // ── Main run/reset ────────────────────────────────────────────
  async function run() {
    try {
      showTableLoading();
      const rows = await fetchData();
      renderTable(rows);
    } catch (e) {
      console.error(e);
      setStatus("Error loading data");
    }
  }

  function reset() {
    document.getElementById("ix-search").value   = "";
    document.getElementById("ix-days").value     = "30";
    document.getElementById("ix-trend").value    = "";
    document.getElementById("ix-subgroup").value = "";
    document.getElementById("ix-limit").value    = "500";
    run();
  }

  // ── Event binding ─────────────────────────────────────────────
  function bindEvents() {
    document.getElementById("ix-run").addEventListener("click", run);
    document.getElementById("ix-reset").addEventListener("click", reset);

    document.getElementById("ix-search").addEventListener("keydown", e => {
      if (e.key === "Enter") run();
    });

    // Row click (any cell except action col) and view-button click
    // Both read from tr data-* attributes — no DataTables row.data() needed
    document.getElementById("ix-table").addEventListener("click", e => {
      const btn = e.target.closest(".ix-view-btn");
      const row = e.target.closest("tr[data-item-code]");
      if (btn || row) openDrawerFromEl(e.target);
    });
  }

  // ── Init ──────────────────────────────────────────────────────
  function init() {
    bindEvents();
    // Init tooltips
    document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(el =>
      new bootstrap.Tooltip(el)
    );
    run();
  }

  return { init };
})();
