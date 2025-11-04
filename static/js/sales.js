// static/js/sales.js
// POS Sales Dashboard Logic
// ------------------------------------------------------------

(function () {
    // Cached DOM elements
    const dateInput = document.getElementById("salesDate");
    const btnRefresh = document.getElementById("salesRefresh");

    const kpiTotalSales = document.getElementById("kpiTotalSales");
    const kpiTotalSalesUSD = document.getElementById("kpiTotalSalesUSD");
    const kpiReceipts = document.getElementById("kpiReceipts");
    const kpiAvgTicket = document.getElementById("kpiAvgTicket");
    const kpiGrowthYesterday = document.getElementById("kpiGrowthYesterday");
    const kpiGrowth4W = document.getElementById("kpiGrowth4W");
    const kpiPeakHour = document.getElementById("kpiPeakHour");

    let chartHourly, chartCategory;

    // ------------------------------------------------------------
    // UTILITIES
    // ------------------------------------------------------------

    // ------------------------------------------------------------
    // DATE PICKER SETUP
    // ------------------------------------------------------------
    const today = new Date();

    // compute yesterday in local time
    const yesterday = new Date(today);
    yesterday.setDate(today.getDate() - 1);

    // format helper
    function fmtDate(d) {
        const y = d.getFullYear();
        const m = String(d.getMonth() + 1).padStart(2, "0");
        const dd = String(d.getDate()).padStart(2, "0");
        return `${y}-${m}-${dd}`;
    }

    // prefill with yesterday
    dateInput.value = fmtDate(yesterday);

    // disable today & future
    dateInput.max = fmtDate(yesterday);

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
            kpiTotalSalesUSD.textContent = (data.total_sales / 89000).toFixed(2) + " USD";
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
            // ------------------------------------------------------------
            // Fetch hourly sales + 4-week comparison + weather (5 weeks)
            // ------------------------------------------------------------
            const [today, prev4w, weather5w] = await Promise.all([
                fetchJSON(`/api/sales/hourly?date=${date}`),
                fetchJSON(`/api/sales/hourly-4weeks?date=${date}`),
                fetchJSON(`/api/weather/hourly-5weeks?date=${date}`)
            ]);

            window.weather5w = weather5w; // keep globally accessible for tooltip

            const ctx = document.getElementById("chartHourlySales");
            if (chartHourly) chartHourly.destroy();

            const labels = today.map((p) => `${((p.hour + 8) % 24)}:00`);
            const fmt = new Intl.NumberFormat("en-US");

            // ------------------------------------------------------------
            // Build datasets (today + 4 previous weeks)
            // ------------------------------------------------------------
            const datasets = [
                {
                    label: "Today",
                    data: today.map((p) => p.sales),
                    borderColor: "#0d6efd",
                    backgroundColor: "rgba(13,110,253,0.15)",
                    fill: true,
                    tension: 0.3,
                    borderWidth: 2,
                    date: date, // used for tooltip weather lookup
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
                    date: week.date, // used for tooltip weather lookup
                });
            });

            // ------------------------------------------------------------
            // Create chart with enriched tooltip
            // ------------------------------------------------------------
            chartHourly = new Chart(ctx, {
                type: "line",
                data: { labels, datasets },
                options: {
                    responsive: true,
                    plugins: {
                        legend: { display: true, position: "bottom" },
                        tooltip: {
                            usePointStyle: true,
                            callbacks: {
                                label: function (ctx) {
                                    const date = ctx.dataset.date;
                                    const hour = ctx.dataIndex;
                                    const salesVal = fmt.format(ctx.parsed.y);

                                    // find matching weather info for this date/hour
                                    const wSeries = window.weather5w?.series?.find((s) => s.date === date);
                                    const w = wSeries?.hours?.find((h) => h.hour === ((hour + 8) % 24));
                                    const weatherText = w
                                        ? ` | ${Math.round(w.temp)}°C ${w.cond}`
                                        : "";

                                    return `${salesVal} LBP (${date})${weatherText}`;
                                },
                            },
                        },
                    },
                    scales: {
                        y: {
                            ticks: { callback: (val) => fmt.format(val) },
                            title: { display: true, text: "Sales (LBP)" },
                        },
                        x: {
                            title: { display: true, text: "Hour" },
                        },
                    },
                },
            });

            // ------------------------------------------------------------
            // Generate AI summary for today’s hourly data
            // ------------------------------------------------------------
            //await generateAISummary("sales_hourly", today, "#summaryHourly");

        } catch (err) {
            console.error("loadHourlyChart error:", err);
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
            //await generateAISummary('sales_category', data, '#summaryCategory');

        } catch (err) {
            console.error(err);
        }
    }

    // ----------------------------------------------------------
    // HOURLY TOTAL SALES TREND (CUMULATIVE, TODAY + 4 WEEKS)
    // ----------------------------------------------------------
    async function loadHourlyCumulativeChart(date) {
        try {
            const data = await fetchJSON(`/api/sales/hourly-cumulative?date=${date}`);
            const ctx = document.getElementById("chartHourlyCumulative");
            if (!ctx) return;

            // destroy old chart if exists
            if (window.chartHourlyCumulative && typeof window.chartHourlyCumulative.destroy === "function") {
                window.chartHourlyCumulative.destroy();
            }

            const fmt = new Intl.NumberFormat("en-US");

            // build datasets for each date
            const datasets = data.map((entry, idx) => {
                const label =
                    idx === 0 ? "This Week" : `Week -${idx}`;
                const color = [
                    "#20c997", // bright green for current
                    "#6c757d",
                    "#adb5bd",
                    "#ced4da",
                    "#dee2e6",
                ][idx] || "#dee2e6";

                return {
                    label,
                    data: entry.series.map(p => p.sales_total),
                    borderColor: color,
                    backgroundColor: "transparent",
                    tension: 0.3,
                    borderWidth: idx === 0 ? 2.5 : 1.5,
                    fill: false,
                };
            });

            // labels (0..23 shifted by +8h rule)
            const labels = Array.from({ length: 24 }, (_, h) => `${((h + 8) % 24).toString().padStart(2, "0")}:00`);

            // render chart
            window.chartHourlyCumulative = new Chart(ctx, {
                type: "line",
                data: { labels, datasets },
                options: {
                    responsive: true,
                    interaction: { mode: "index", intersect: false },
                    plugins: {
                        legend: { position: "top" },
                        tooltip: {
                            callbacks: {
                                label: (ctx) => `${fmt.format(ctx.parsed.y)} LBP`,
                            },
                        },
                    },
                    scales: {
                        y: {
                            title: { display: true, text: "Cumulative Sales (LBP)" },
                            ticks: { callback: val => fmt.format(val) },
                        },
                        x: {
                            title: { display: true, text: "Hour (rotated business time)" },
                        },
                    },
                },
            });

            // optional AI summary
            //await generateAISummary("sales_hourly_cumulative", data, "#summaryHourlyCumulative");
        } catch (err) {
            console.error("loadHourlyCumulativeChart error:", err);
        }
    }


    // ------------------------------------------------------------
    // ITEMS SOLD TABLE (FULL DAILY LIST)
    // ------------------------------------------------------------
    let tableItems;

    async function initItemsTable(date) {
        // destroy previous if exists
        if (tableItems) tableItems.destroy();

        tableItems = new DataTable("#tblItemsSold", {
            ajax: {
                url: `/api/sales/items?date=${date}`,
                dataSrc: "",
            },
            columns: [
                { data: null, title: "#", render: (data, type, row, meta) => meta.row + 1 },
                { data: "item_name", title: "Item" },
                { data: "category", title: "Category" },
                {
                    data: "total_qty",
                    title: "Units",
                    className: "text-end",
                    render: DataTable.render.number(",", ".", 2),
                },
                {
                    data: "avg_price",
                    title: "Avg. Price (LBP)",
                    className: "text-end",
                    render: DataTable.render.number(",", ".", 0),
                },
                {
                    data: "total_revenue",
                    title: "Revenue (LBP)",
                    className: "text-end fw-bold",
                    render: DataTable.render.number(",", ".", 0),
                },
                {
                    data: "share",
                    title: "Share %",
                    className: "text-end text-muted",
                    render: (data) => `${data.toFixed(1)}%`,
                },
            ],
            responsive: true,
            pageLength: 10,
            lengthMenu: [10, 25, 50, 100],
            order: [[5, "desc"]],
            language: {
                search: "",
                searchPlaceholder: "Filter items...",
                lengthMenu: "_MENU_ per page",
                zeroRecords: "No items sold for this date",
                info: "Showing _START_–_END_ of _TOTAL_ items",
                infoEmpty: "No entries",
                paginate: { previous: "‹", next: "›" },
            },
            dom:
                "<'row mb-2'<'col-sm-6'l><'col-sm-6'f>>" +
                "<'table-responsive'tr>" +
                "<'row mt-2'<'col-sm-6'i><'col-sm-6'p>>",
        });
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
    // AI Summaries
    // ------------------------------------------------------------
    async function generateAISummary(widget, data, selector) {
        try {
            const res = await fetch('/api/ai/summarize', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ widget, data })
            });
            const json = await res.json();
            const el = document.querySelector(`${selector} .ai-text`);
            if (el) {
                el.classList.remove('show');
                setTimeout(() => {
                    el.textContent = json.summary || '(No summary)';
                    el.classList.add('show');
                }, 100);
            }
        } catch (err) {
            console.error('AI summary error', err);
        }
    }

    // ------------------------------------------------------------
    // WEATHER BADGE
    // ------------------------------------------------------------
    async function loadWeather(date) {
        try {
            const res = await fetch(`/api/weather?date=${date}`);
            const w = await res.json();
            const badge = document.getElementById("weatherBadge");

            if (w.error) {
                badge.textContent = "Weather unavailable";
                return;
            }

            badge.innerHTML = `
      <img src="${w.icon}" width="22" height="22" alt="${w.condition}" class="me-1">
      <span>${Math.round(w.temp)}°C ${w.condition}</span>
    `;
        } catch (err) {
            console.error(err);
            document.getElementById("weatherBadge").textContent = "Weather unavailable";
        }
    }

    // ----------------------------------------------------------
    // LAST 14 DAYS SALES TREND
    // ----------------------------------------------------------
    async function loadDaily14DaysChart() {
        try {
            const data = await fetchJSON("/api/sales/daily-14days");
            const ctx = document.getElementById("chartDaily14Days");
            if (!ctx) return;

            if (window.chartDaily14Days && typeof window.chartDaily14Days.destroy === "function") {
                window.chartDaily14Days.destroy();
            }

            const labels = data.map(d => d.date.slice(5)); // "MM-DD"
            const totals = data.map(d => d.sales_total);
            const fmt = new Intl.NumberFormat("en-US");

            window.chartDaily14Days = new Chart(ctx, {
                type: "line",
                data: {
                    labels,
                    datasets: [{
                        label: "Total Sales (LBP)",
                        data: totals,
                        borderColor: "#0d6efd",
                        backgroundColor: "rgba(13,110,253,0.1)",
                        fill: true,
                        tension: 0.3,
                        borderWidth: 2,
                    }],
                },
                options: {
                    responsive: true,
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            callbacks: {
                                label: (ctx) => fmt.format(ctx.parsed.y) + " LBP",
                            },
                        },
                    },
                    scales: {
                        y: {
                            title: { display: true, text: "Sales (LBP)" },
                            ticks: { callback: val => fmt.format(val) },
                        },
                        x: { title: { display: true, text: "Last 14 Business Days" } },
                    },
                },
            });

            // optional AI summary
            //await generateAISummary("sales_last14days", data, "#summaryDaily14Days");
        } catch (err) {
            console.error("loadDaily14DaysChart error:", err);
        }
    }




    // ------------------------------------------------------------
    // MASTER LOADER
    // ------------------------------------------------------------
    async function loadAll() {
        const date = dateInput.value;
        loadKPIs(date);
        loadWeather(date);
        loadHourlyChart(date);
        loadHourlyCumulativeChart(date);
        loadCategoryChart(date);
        loadDaily14DaysChart(date);
        initItemsTable(date);
        initTables(date);

    }

    // ------------------------------------------------------------
    // EVENTS
    // ------------------------------------------------------------
    btnRefresh.addEventListener("click", loadAll);
    //dateInput.addEventListener("change", loadAll);

    // ------------------------------------------------------------
    // INIT
    // ------------------------------------------------------------
    document.addEventListener("DOMContentLoaded", loadAll);
})();
