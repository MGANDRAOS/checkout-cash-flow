// static/js/sales.js
// POS Sales Dashboard Logic
// ------------------------------------------------------------

(function () {
    // Cached DOM elements
    const dateInput = document.getElementById("salesDate");
    const btnRefresh = document.getElementById("salesRefresh");

    const kpiTotalSales = document.getElementById("kpiTotalSales");
    const kpiReceipts = document.getElementById("kpiReceipts");
    const kpiAvgTicket = document.getElementById("kpiAvgTicket");
    const kpiGrowthYesterday = document.getElementById("kpiGrowthYesterday");
    const kpiGrowth4W = document.getElementById("kpiGrowth4W");
    const kpiPeakHour = document.getElementById("kpiPeakHour");

    let chartHourly, chartCategory;

    // ------------------------------------------------------------
    // UTILITIES
    // ------------------------------------------------------------

    const fmt = new Intl.NumberFormat("en-LB", { maximumFractionDigits: 0 });
    function fmtLBP(value) {
        return value ? fmt.format(value) + " LBP" : "–";
    }
    function fmtPct(value) {
        if (value === null || value === undefined) return "–";
        const cls = value >= 0 ? "text-success" : "text-danger";
        const arrow = value >= 0 ? "▲" : "▼";
        return `<span class="${cls}">${arrow} ${value.toFixed(1)}%</span>`;
    }

    async function fetchJSON(url) {
        const res = await fetch(url);
        if (!res.ok) throw new Error("Fetch failed: " + url);
        return await res.json();
    }

    // ------------------------------------------------------------
    // KPI LOADER
    // ------------------------------------------------------------
    async function loadKPIs(date) {
        try {
            const data = await fetchJSON(`/api/sales/summary?date=${date}`);
            kpiTotalSales.textContent = fmtLBP(data.total_sales);
            kpiReceipts.textContent = data.receipts.toLocaleString();
            kpiAvgTicket.textContent = fmtLBP(data.avg_ticket);
            kpiGrowthYesterday.innerHTML = fmtPct(data.growth_vs_yesterday);
            kpiGrowth4W.innerHTML = fmtPct(data.growth_vs_4week);
            kpiPeakHour.textContent = data.peak_hour || "–";
        } catch (err) {
            console.error(err);
        }
    }

    // ------------------------------------------------------------
    // CHARTS
    // ------------------------------------------------------------

    async function loadHourlyChart(date) {
        try {
            const today = await fetchJSON(`/api/sales/hourly?date=${date}`);
            const prev4w = await fetchJSON(`/api/sales/hourly-4weeks?date=${date}`);

            const ctx = document.getElementById("chartHourlySales");
            if (chartHourly) chartHourly.destroy();

            const labels = today.map((p) => `${((p.hour + 8) % 24)}:00`);
            const datasets = [
                {
                    label: "Today",
                    data: today.map((p) => p.sales),
                    borderColor: "#0d6efd",
                    backgroundColor: "rgba(13,110,253,0.15)",
                    fill: true,
                    tension: 0.3,
                    borderWidth: 2,
                },
            ];

            const colors = ["#adb5bd", "#6c757d", "#ced4da", "#dee2e6"];
            prev4w.forEach((week, i) => {
                datasets.push({
                    label: week.date,
                    data: week.series.map((p) => p.sales),
                    borderColor: colors[i % colors.length],
                    borderDash: [3, 3],
                    fill: false,
                    tension: 0.3,
                });
            });

            chartHourly = new Chart(ctx, {
                type: "line",
                data: { labels, datasets },
                options: {
                    responsive: true,
                    plugins: {
                        legend: { display: true, position: "bottom" },
                        tooltip: {
                            callbacks: {
                                label: (ctx) =>
                                    fmt.format(ctx.parsed.y) + " LBP (" + ctx.dataset.label + ")",
                            },
                        },
                    },
                    scales: {
                        y: {
                            ticks: {
                                callback: (val) => fmt.format(val),
                            },
                        },
                    },
                },
            });
        } catch (err) {
            console.error(err);
        }
    }

    async function loadCategoryChart(date) {
        try {
            const data = await fetchJSON(`/api/sales/category?date=${date}`);
            const ctx = document.getElementById("chartCategorySales");
            if (chartCategory) chartCategory.destroy();

            chartCategory = new Chart(ctx, {
                type: "bar",
                data: {
                    labels: data.map((r) => r.subgroup),
                    datasets: [
                        {
                            label: "Sales (LBP)",
                            data: data.map((r) => r.sales),
                            backgroundColor: "rgba(13,110,253,0.6)",
                        },
                    ],
                },
                options: {
                    indexAxis: "y",
                    scales: {
                        x: {
                            ticks: {
                                callback: (val) => fmt.format(val),
                            },
                        },
                    },
                    plugins: {
                        legend: { display: false },
                    },
                },
            });
        } catch (err) {
            console.error(err);
        }
    }


    // ------------------------------------------------------------
    // DATATABLE HELPERS
    // ------------------------------------------------------------
    function makeTable(selector, columns, ajaxUrl) {
        return new DataTable(selector, {
            ajax: {
                url: ajaxUrl,
                dataSrc: '',
            },
            columns,
            responsive: true,
            pageLength: 10,
            lengthMenu: [5, 10, 25, 50],
            order: [],
            language: {
                search: '',
                searchPlaceholder: 'Filter...',
                lengthMenu: '_MENU_ per page',
                zeroRecords: 'No data available',
                info: 'Showing _START_–_END_ of _TOTAL_',
                infoEmpty: 'No entries',
                paginate: { previous: '‹', next: '›' },
            },
            dom:
                "<'row mb-2'<'col-sm-6'l><'col-sm-6'f>>" +
                "<'table-responsive'tr>" +
                "<'row mt-2'<'col-sm-6'i><'col-sm-6'p>>",
        });
    }

    let tableTop, tableSlow, tableReceipts;

    function initTables(date) {
        if (tableTop) tableTop.destroy();
        if (tableSlow) tableSlow.destroy();
        if (tableReceipts) tableReceipts.destroy();

        tableTop = makeTable('#tblTopProducts', [
            { data: 'title', title: 'Item' },
            {
                data: 'qty',
                title: 'Qty',
                className: 'text-end',
                render: DataTable.render.number(',', '.', 0),
            },
            {
                data: 'sales',
                title: 'Sales (LBP)',
                className: 'text-end',
                render: DataTable.render.number(',', '.', 0),
            },
        ], `/api/sales/top?date=${date}`);

        tableSlow = makeTable('#tblSlowProducts', [
            { data: 'title', title: 'Item' },
            { data: 'subgroup', title: 'Subgroup' },
            { data: 'last_sold', title: 'Last Sold', defaultContent: '–' },
        ], `/api/sales/slow?days=7`);

        tableReceipts = makeTable('#tblReceipts', [
            { data: 'id', title: 'Receipt ID' },
            { data: 'datetime', title: 'Time' },
            {
                data: 'items_count',
                title: 'Items',
                className: 'text-end',
                render: DataTable.render.number(',', '.', 0),
            },
            {
                data: 'total',
                title: 'Total (LBP)',
                className: 'text-end',
                render: DataTable.render.number(',', '.', 0),
            },
        ], `/api/sales/receipts?date=${date}`);
    }


    // ------------------------------------------------------------
    // MASTER LOADER
    // ------------------------------------------------------------
    async function loadAll() {
        const date = dateInput.value;
        loadKPIs(date);
        loadHourlyChart(date);
        loadCategoryChart(date);
        initTables(date);

    }

    // ------------------------------------------------------------
    // EVENTS
    // ------------------------------------------------------------
    btnRefresh.addEventListener("click", loadAll);
    dateInput.addEventListener("change", loadAll);

    // ------------------------------------------------------------
    // INIT
    // ------------------------------------------------------------
    document.addEventListener("DOMContentLoaded", loadAll);
})();
