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
  <button type="button"
          class="btn btn-sm btn-outline-primary btn-view-item"
          data-item-code="${escapeHtml(r.item_code)}"
          data-item-title="${escapeHtml(r.item || r.item_code)}"
          data-subgroup="${escapeHtml(r.subgroup || "")}"
          data-avg-per-day="${escapeHtml(r.avg_per_day)}"
          data-last-sold="${escapeHtml(r.last_sold || "")}"
          data-total-qty="${escapeHtml(r.total_qty ?? "")}"
          title="Open Item 360° drawer">
    <i class="bi bi-eye"></i> View
  </button>
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

    // Important: keep chart instance so we can destroy + re-create cleanly on every click
    let itemSparklineChart = null;

    function initItem360Drawer() {
        // tooltips for info bubbles
        const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
        tooltipTriggerList.forEach((el) => new bootstrap.Tooltip(el));

        // Click "View" button -> open drawer
        $("#ix-table tbody").on("click", ".btn-view-item", async function (e) {
            e.preventDefault();
            e.stopPropagation();

            const btn = e.currentTarget;

            const row = {
                item_code: btn.dataset.itemCode,
                item: btn.dataset.itemTitle,
                subgroup: btn.dataset.subgroup,
                avg_per_day: btn.dataset.avgPerDay,
                last_sold: btn.dataset.lastSold,
                total_qty: btn.dataset.totalQty
            };

            await openItem360Drawer(row);
        });


        // Optional: click row (except last column) -> open drawer
        $("#ix-table tbody").on("click", "tr", async function (e) {
            // If click came from the View button, ignore (handled above)
            if ($(e.target).closest(".btn-view-item").length) return;

            const dt = $("#ix-table").DataTable();
            const rowData = dt.row(this).data();
            if (!rowData) return;

            await openItem360Drawer(rowData);
        });
    }

    async function openItem360Drawer(row) {
        // These keys must match what your API returns in the table rows
        // (Based on your explorer output)
        const itemCode = row.item_code;
        const itemTitle = row.item || row.item_title || row.item_code;
        const subgroupName = row.subgroup || row.subgroup_name || "—";
        const lastSold = row.last_sold || "—";
        const totalQty = row.total_qty ?? "—";
        const avgPerDay = row.avg_per_day ?? "—";

        // Fill drawer basic fields
        document.getElementById("drawerItemCode").textContent = `Code: ${itemCode}`;
        document.getElementById("drawerItemTitle").textContent = itemTitle || "—";
        document.getElementById("drawerSubgroup").textContent = subgroupName;
        document.getElementById("drawerLastSold").textContent = lastSold;
        document.getElementById("drawerAvgPerDay").textContent = formatNumber(avgPerDay);

        // If total_qty is not currently in your table API, compute it safely when missing:
        // fallback: avg/day * days (approx) is misleading, so show "—" unless present.
        document.getElementById("drawerTotalQty").textContent = (totalQty !== "—") ? formatNumber(totalQty) : "—";

        // Show the drawer
        const drawerEl = document.getElementById("item360Drawer");
        const drawer = bootstrap.Offcanvas.getOrCreateInstance(drawerEl);
        drawer.show();

        // Fetch and render sparkline + invoices (Last 10)
        const days = getCurrentDaysFilter();

        // 1) Sparkline (already existing)
        const series = await fetchItemSeries(itemCode, days, 14);
        renderItemSparkline(series);

        // 2) Invoices (Last 10)
        const invoicesPayload = await fetchItemLastInvoices(itemCode, days, 10);
        renderItemInvoices(invoicesPayload.rows || []);

        // ✅ Momentum KPIs 
        const kpis = await fetchItemMomentumKpis(itemCode, days);
        renderItemMomentumKpis(kpis);

        // items_explorer.js (inside openItem360Drawer)

        const seeAllBtn = document.getElementById("drawerSeeAllInvoices");
        if (seeAllBtn) {
            // Important: deep-link to invoices module with the current item_code
            seeAllBtn.href = `/invoices?item_code=${encodeURIComponent(itemCode)}`;
            seeAllBtn.classList.remove("disabled");
            seeAllBtn.removeAttribute("aria-disabled");
            seeAllBtn.title = "Open the Invoices module filtered to this item.";
        }


    }

    async function fetchItemSeries(itemCode, days, lookback) {
        const url = `/api/items/explorer/item-series?item_code=${encodeURIComponent(itemCode)}&days=${encodeURIComponent(days)}&lookback=${encodeURIComponent(lookback)}`;
        const res = await fetch(url);
        if (!res.ok) return [];
        const data = await res.json();
        return data.series || [];
    }

    function renderItemSparkline(series) {
        const labels = series.map(x => x.biz_date);
        const values = series.map(x => Number(x.qty || 0));

        const ctx = document.getElementById("itemSparkline").getContext("2d");

        // Destroy previous chart to avoid stacking & memory leaks
        if (itemSparklineChart) {
            itemSparklineChart.destroy();
            itemSparklineChart = null;
        }

        itemSparklineChart = new Chart(ctx, {
            type: "line",
            data: {
                labels,
                datasets: [{
                    label: "Qty",
                    data: values,
                    tension: 0.35,
                    pointRadius: 2,
                    borderWidth: 2,
                    fill: false
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: { enabled: true }
                },
                scales: {
                    x: { display: true },
                    y: { display: true, beginAtZero: true }
                }
            }
        });
    }

    // --- small utilities (keep descriptive) ---
    function getCurrentDaysFilter() {
        const el = document.getElementById("ix-days");
        const parsed = el ? parseInt(el.value, 10) : 30;
        return Number.isFinite(parsed) ? parsed : 30;
    }

    function formatNumber(value) {
        const num = Number(value);
        if (!Number.isFinite(num)) return String(value ?? "—");
        return num.toLocaleString(undefined, { maximumFractionDigits: 2 });
    }

    // static/js/modules/items_explorer.js

    async function fetchItemLastInvoices(itemCode, days, limit) {
        const url =
            `/api/items/360/invoices?item_code=${encodeURIComponent(itemCode)}` +
            `&days=${encodeURIComponent(days)}` +
            `&limit=${encodeURIComponent(limit)}`;

        const res = await fetch(url);
        if (!res.ok) return { rows: [] };
        return await res.json();
    }

    function renderItemInvoices(rows) {
        const statusEl = document.getElementById("drawerInvoicesStatus");
        const tbody = document.getElementById("drawerInvoicesTbody");

        if (!tbody) return;

        // Clear old rows every time (critical: drawer opens many times)
        tbody.innerHTML = "";

        if (!rows || rows.length === 0) {
            if (statusEl) statusEl.textContent = "No invoices found for this item in the selected window.";
            return;
        }

        if (statusEl) statusEl.textContent = `Showing last ${rows.length} invoices`;

        rows.forEach((r) => {
            const tr = document.createElement("tr");

            // Important: keep rendering defensive (no NaN / undefined)
            const dt = r.biz_dt || "—";
            const rcptId = (r.rcpt_id ?? "—");
            const qty = Number(r.item_qty ?? 0);
            const amount = Number(r.rcpt_amount ?? 0);

            tr.innerHTML = `
      <td style="white-space:nowrap;">${escapeHtml(dt)}</td>
      <td style="white-space:nowrap;">${escapeHtml(rcptId)}</td>
      <td class="text-end">${Number.isFinite(qty) ? qty.toLocaleString() : "—"}</td>
      <td class="text-end">${Number.isFinite(amount) ? amount.toLocaleString(undefined, { maximumFractionDigits: 2 }) : "—"}</td>
    `;

            tbody.appendChild(tr);
        });
    }

    // static/js/modules/items_explorer.js

    async function fetchItemMomentumKpis(itemCode, days) {
        const url =
            `/api/items/360/kpis?item_code=${encodeURIComponent(itemCode)}` +
            `&days=${encodeURIComponent(days)}`;

        const res = await fetch(url);
        if (!res.ok) return null;
        return await res.json();
    }

    function renderItemMomentumKpis(kpis) {
        const daysEl = document.getElementById("drawerDaysSinceSold");
        const lastBizEl = document.getElementById("drawerLastBizDateHint");
        const peakEl = document.getElementById("drawerPeakHour");
        const peakHintEl = document.getElementById("drawerPeakHourHint");

        if (!kpis) {
            if (daysEl) daysEl.textContent = "—";
            if (lastBizEl) lastBizEl.textContent = "Last biz date: —";
            if (peakEl) peakEl.textContent = "—";
            if (peakHintEl) peakHintEl.textContent = "Qty in peak hour: —";
            return;
        }

        // Days since last sold
        const daysSince = kpis.days_since_last_sold;
        const lastBizDate = kpis.last_biz_date;

        if (daysEl) daysEl.textContent = (daysSince === null || daysSince === undefined) ? "—" : String(daysSince);
        if (lastBizEl) lastBizEl.textContent = `Last biz date: ${lastBizDate || "—"}`;

        // Peak hour
        const peakHour = kpis.peak_hour;
        const peakQty = kpis.peak_hour_qty;

        if (peakEl) {
            if (peakHour === null || peakHour === undefined) {
                peakEl.textContent = "—";
            } else {
                // Pretty hour label: 14:00
                const hh = String(peakHour).padStart(2, "0");
                peakEl.textContent = `${hh}:00`;
            }
        }

        if (peakHintEl) {
            const qtyText = (peakQty === null || peakQty === undefined) ? "—" : formatNumber(peakQty);
            peakHintEl.textContent = `Qty in peak hour: ${qtyText}`;
        }
    }


    function init() {
        initTooltips();
        bindEvents();
        initItem360Drawer();
        run(); // initial load
    }

    return { init };
})();
