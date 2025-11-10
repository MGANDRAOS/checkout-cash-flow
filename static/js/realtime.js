// static/js/realtime.js
// ------------------------------------------------------------
// Realtime tab logic (open-day). Mirrors your sales.js style.
// ------------------------------------------------------------
(function () {
    // Cache Realtime DOM
    const tabRealtime = document.getElementById("tab-realtime");
    if (!tabRealtime) return; // exit if tab absent

    // Realtime is “today only”; no date/refresh controls.
    let rtLoadedOnce = false; // prevents double-load on initial render + tab show


    const kpiTotal = document.getElementById("rtKpiTotalSales");
    const kpiReceipts = document.getElementById("rtKpiReceipts");
    const kpiAvg = document.getElementById("rtKpiAvgTicket");
    const kpiItems = document.getElementById("rtKpiItemsSold");
    const kpiPeak = document.getElementById("rtKpiPeakHour");
    const kpiGY = document.getElementById("rtKpiGrowthYesterday");

    let chartHourly, chartCum, chartCategory;
    let tblItems, tblReceipts;

    const nf = new Intl.NumberFormat("en-LB", { maximumFractionDigits: 0 });



    async function j(url) {
        const r = await fetch(url);
        if (!r.ok) throw new Error(url);
        return r.json();
    }

    // ------------------------------ KPIs ------------------------------
    async function loadKPIs() {
        const d = await j(`/api/realtime/kpis`);
        kpiTotal.textContent = nf.format(d.total_sales) + " LBP";
        kpiReceipts.textContent = (d.receipts ?? 0).toLocaleString();
        kpiAvg.textContent = nf.format(d.avg_ticket) + " LBP";
        kpiItems.textContent = (d.items_sold ?? 0).toLocaleString();
        kpiPeak.textContent = d.peak_hour || "–";
        kpiGY.textContent = (d.growth_vs_yesterday ?? 0).toFixed(1) + "%";
    }

    // ------------------------------ Charts ------------------------------
    async function loadHourly() {
        const data = await j(`/api/realtime/hourly`);
        const labels = data.map(p => `${(p.hour + 8) % 24}:00`);
        const values = data.map(p => p.sales);

        const ctx = document.getElementById("rtChartHourly");
        if (chartHourly) chartHourly.destroy();
        chartHourly = new Chart(ctx, {
            type: "line",
            data: { labels, datasets: [{ label: "Live Today", data: values, borderWidth: 2, fill: true }] },
            options: { plugins: { legend: { display: false } } }
        });
    }

    async function loadCumulative() {
        const data = await j(`/api/realtime/hourly-cumulative`);
        const series = data[0]?.series ?? [];
        const labels = series.map(p => `${(p.hour + 8) % 24}:00`);
        const values = series.map(p => p.sales_total);

        const ctx = document.getElementById("rtChartCumulative");
        if (chartCum) chartCum.destroy();
        chartCum = new Chart(ctx, {
            type: "line",
            data: { labels, datasets: [{ label: "Cumulative", data: values, borderWidth: 2 }] },
            options: { plugins: { legend: { display: false } } }
        });
    }

    async function loadCategory() {
        const data = await j(`/api/realtime/category`);
        const labels = data.map(r => r.subgroup);
        const values = data.map(r => r.sales);

        const ctx = document.getElementById("rtChartCategory");
        if (chartCategory) chartCategory.destroy();
        chartCategory = new Chart(ctx, {
            type: "bar",
            data: { labels, datasets: [{ label: "Sales (LBP)", data: values }] },
            options: { indexAxis: "y", plugins: { legend: { display: false } } }
        });
    }

    // ------------------------------ Tables ------------------------------
    function makeTable(selector, columns, url) {
        return new DataTable(selector, {
            ajax: { url, dataSrc: "" },
            columns,
            responsive: true,
            pageLength: 10,
            lengthMenu: [10, 25, 50, 100],
            dom:
                "<'row mb-2'<'col-sm-6'l><'col-sm-6'f>>" +
                "<'table-responsive'tr>" +
                "<'row mt-2'<'col-sm-6'i><'col-sm-6'p>>",
            order: [],
            language: {
                search: "", searchPlaceholder: "Filter...",
                lengthMenu: "_MENU_ per page", zeroRecords: "No data",
                info: "Showing _START_–_END_ of _TOTAL_", infoEmpty: "No entries",
                paginate: { previous: "‹", next: "›" },
            },
        });
    }

    async function loadItemsTable() {
        if (tblItems) tblItems.destroy();
        tblItems = makeTable("#rtTblItemsSold", [
            { data: null, title: "#", render: (d, t, r, m) => m.row + 1 },
            { data: "item_name", title: "Item" },
            { data: "category", title: "Category" },
            { data: "total_qty", title: "Units", className: "text-end", render: DataTable.render.number(",", ".", 2) },
            { data: "avg_price", title: "Avg. Price", className: "text-end", render: DataTable.render.number(",", ".", 0) },
            { data: "total_revenue", title: "Revenue", className: "text-end fw-semibold", render: DataTable.render.number(",", ".", 0) },
            { data: "share", title: "Share %", className: "text-end", render: d => `${(d ?? 0).toFixed(1)}%` },
        ], `/api/realtime/items`);
    }

    async function loadReceiptsTable() {
        if (tblReceipts) tblReceipts.destroy();
        tblReceipts = makeTable("#rtTblReceipts", [
            { data: "id", title: "Receipt ID" },
            { data: "datetime", title: "Time" },
            { data: "items_count", title: "Items", className: "text-end", render: DataTable.render.number(",", ".", 0) },
            { data: "total", title: "Total (LBP)", className: "text-end", render: DataTable.render.number(",", ".", 0) },
            {
                data: null,
                title: "",
                className: "text-end",
                orderable: false,
                render: (d, t, row) => `<button class="btn btn-sm btn-outline-primary rt-view" data-id="${row.id}">View</button>`
            }
        ], `/api/realtime/receipts`);

        // row click → fetch detail modal
        document.querySelector("#rtTblReceipts").addEventListener("click", async (e) => {
            const btn = e.target.closest(".rt-view");
            if (!btn) return;
            const id = btn.getAttribute("data-id");
            const detail = await j(`/api/realtime/receipt/${id}`);
            showReceiptModal(detail);
        });
    }

    // ------------------------------ Modal (Invoice) ------------------------------
    function ensureModal() {
        // inject once
        if (document.getElementById("rtReceiptModal")) return;
        const div = document.createElement("div");
        div.innerHTML = `
<div class="modal fade" id="rtReceiptModal" tabindex="-1" aria-hidden="true">
  <div class="modal-dialog modal-lg modal-dialog-scrollable">
    <div class="modal-content">
      <div class="modal-header">
        <h6 class="modal-title">Receipt <span id="rtMdlRcptNo">—</span></h6>
        <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
      </div>
      <div class="modal-body">
        <div class="mb-2 small text-muted" id="rtMdlMeta"></div>
        <div class="table-responsive">
          <table class="table table-sm align-middle">
            <thead class="table-light">
              <tr>
                <th>#</th>
                <th>Item</th>
                <th>Category</th>
                <th class="text-end">Qty</th>
                <th class="text-end">Unit Price</th>
                <th class="text-end">Line Total</th>
              </tr>
            </thead>
            <tbody id="rtMdlLines">
              <tr><td colspan="6" class="text-center text-muted">Loading…</td></tr>
            </tbody>
            <tfoot class="table-light">
              <tr>
                <td colspan="5" class="text-end fw-semibold">Total</td>
                <td class="text-end fw-bold" id="rtMdlTotal">0</td>
              </tr>
            </tfoot>
          </table>
        </div>
      </div>
      <div class="modal-footer">
        <button class="btn btn-outline-secondary btn-sm" data-bs-dismiss="modal">Close</button>
      </div>
    </div>
  </div>
</div>`;
        document.body.appendChild(div.firstElementChild);
    }

    function showReceiptModal(detail) {
        ensureModal();
        const modalEl = document.getElementById("rtReceiptModal");
        const rcptNo = document.getElementById("rtMdlRcptNo");
        const meta = document.getElementById("rtMdlMeta");
        const body = document.getElementById("rtMdlLines");
        const totalEl = document.getElementById("rtMdlTotal");

        if (!detail.exists) {
            rcptNo.textContent = "Not found";
            meta.textContent = "";
            body.innerHTML = `<tr><td colspan="6" class="text-center text-danger">Receipt not found</td></tr>`;
            totalEl.textContent = "0";
        } else {
            rcptNo.textContent = detail.header.rcpt_no ?? detail.header.rcpt_id;
            meta.textContent = `${detail.header.datetime}`;
            const rows = detail.lines.map(l => `
        <tr>
          <td>${l.line}</td>
          <td>${l.item_name}</td>
          <td>${l.category}</td>
          <td class="text-end">${l.qty.toFixed(2)}</td>
          <td class="text-end">${nf.format(l.unit_price)}</td>
          <td class="text-end fw-semibold">${nf.format(l.line_total)}</td>
        </tr>`).join("");
            body.innerHTML = rows || `<tr><td colspan="6" class="text-center text-muted">No lines</td></tr>`;
            totalEl.textContent = nf.format(detail.header.total_amount);
        }

        const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
        modal.show();
    }

    // ------------------------------ Orchestrator ------------------------------
    // Master loader (Realtime = today only; server decides "today")
    async function loadAll() {
        // run KPIs/charts first (can be parallelized)
        await Promise.all([
            loadKPIs(),
            loadHourly(),
            loadCumulative(),
            loadCategory()
        ]);

        // then tables (init/destroy timing is cleaner sequentially)
        await loadItemsTable();
        await loadReceiptsTable();
    }


    // Auto-load when the Realtime tab is shown, but only once on first entry.
    document.getElementById("realtime-tab")?.addEventListener("shown.bs.tab", () => {
        if (rtLoadedOnce) return;
        rtLoadedOnce = true;
        loadAll();
    });

    // If Realtime tab is already active on initial page load, fire once.
    document.addEventListener("DOMContentLoaded", () => {
        const rtPane = document.getElementById("tab-realtime");
        if (rtPane && rtPane.classList.contains("show") && rtPane.classList.contains("active")) {
            if (!rtLoadedOnce) {
                rtLoadedOnce = true;
                loadAll();
            }
        }
    });


})();
