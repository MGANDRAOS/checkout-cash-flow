// Modularized JavaScript for Checkout Cash Flow Application

// ----------------------------- Utility Module -------------------------------
const Utils = (() => {
    const log = (...args) => console.log("[Checkout]", ...args);
    const parseJSON = (elId) => {
        try {
            const el = document.getElementById(elId);
            if (!el) return null;
            return JSON.parse(el.textContent || "{}");
        } catch (err) {
            console.error(`Error parsing JSON from ${elId}:`, err);
            return null;
        }
    };
    return { log, parseJSON };


})();

// ----------------------------- Chart Module ---------------------------------
const DashboardChart = (() => {
    let chartInstance = null;

    function init() {
        const ctx = document.getElementById("salesBufferChart");
        const data = Utils.parseJSON("chart-data");
        if (!ctx || !data || !data.labels || data.labels.length === 0) return;

        // Destroy previous instance if exists
        if (chartInstance) chartInstance.destroy();

        chartInstance = new Chart(ctx, {
            type: "line",
            data: {
                labels: data.labels,
                datasets: [
                    {
                        label: "Sales",
                        data: data.sales,
                        borderColor: "rgba(37,99,235,1)",
                        backgroundColor: "rgba(37,99,235,0.1)",
                        tension: 0.25,
                        borderWidth: 2,
                        pointRadius: 2,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                animation: false,
                scales: {
                    x: { ticks: { color: "#555" } },
                    y: { beginAtZero: true, ticks: { color: "#555" } },
                },
                plugins: {
                    legend: {
                        display: true,
                        labels: { boxWidth: 12, font: { size: 12 } },
                    },
                },
            },
        });

        Utils.log("Dashboard chart rendered with", data.labels.length, "points");
    }

    return { init };
})();

// ----------------------------- Form Module ----------------------------------
const DailyCloseForm = (() => {
    function init() {
        const form = document.querySelector("form[action$='daily-close']");
        if (!form) return;

        form.addEventListener("submit", () => {
            Utils.log("Submitting daily closing...");
        });
    }

    return { init };
})();


// ----------------------------- Edit Closing Modal Module --------------------
const EditClosingModal = (() => {
    let modalElement, formElement;

    // Populate modal fields when it opens
    function handleShowModal(event) {
        const button = event.relatedTarget;
        if (!button) return;

        const id = button.getAttribute("data-id");
        const date = button.getAttribute("data-date");
        const sales = button.getAttribute("data-sales");
        const notes = button.getAttribute("data-notes");

        formElement.querySelector("#editClosingId").value = id;
        formElement.querySelector("#editDate").value = date;
        formElement.querySelector("#editSale").value = sales;
        formElement.querySelector("#editNotes").value = notes || "";
    }

    // Handle form submission (dynamic action)
    function handleSubmit(event) {
        event.preventDefault();
        const id = formElement.querySelector("#editClosingId").value;
        formElement.action = `/edit-closing/${id}`;
        formElement.submit();
    }

    // Initialize event bindings
    function init() {
        modalElement = document.getElementById("editClosingModal");
        formElement = document.getElementById("editClosingForm");

        if (!modalElement || !formElement) return;

        modalElement.addEventListener("show.bs.modal", handleShowModal);
        formElement.addEventListener("submit", handleSubmit);

        Utils.log("EditClosingModal initialized");
    }

    return { init };
})();


// ----------------------------- Delete Confirmation Module -------------------
const DeleteClosingModal = (() => {
    let modalElement, formElement, dateLabel;

    // Fill modal when it opens
    function handleShowModal(event) {
        const button = event.relatedTarget;
        if (!button) return;

        const id = button.getAttribute("data-id");
        const date = button.getAttribute("data-date");

        formElement.action = `/void-closing/${id}`;
        dateLabel.textContent = date;
    }

    function init() {
        modalElement = document.getElementById("deleteClosingModal");
        formElement = document.getElementById("deleteClosingForm");
        dateLabel = document.getElementById("deleteClosingDate");

        if (!modalElement || !formElement) return;

        modalElement.addEventListener("show.bs.modal", handleShowModal);
        Utils.log("DeleteClosingModal initialized");
    }

    return { init };
})();


// ----------------------------- Chart Fixed Expenses -------------------

const FixedCoverageReport = (() => {
    function render(kpis, points) {
        const dctx = document.getElementById("fixedDonut");
        if (dctx)
            new Chart(dctx, {
                type: "doughnut",
                data: {
                    labels: ["Funded", "Remaining"],
                    datasets: [{
                        data: [kpis.funded_pct, 100 - kpis.funded_pct],
                        backgroundColor: ["#198754", "#dee2e6"]
                    }]
                },
                options: { cutout: "75%", plugins: { legend: { display: false } } }
            });

        const tctx = document.getElementById("fixedTrend");
        if (tctx)
            new Chart(tctx, {
                type: "line",
                data: {
                    labels: points.map(p => p.date),
                    datasets: [{
                        label: "Cumulative Fixed ($)", data: points.map(p => p.balance),
                        borderColor: "#0d6efd", fill: false, tension: 0.3
                    }]
                },
                options: { responsive: true, plugins: { legend: { display: false } } }
            });
    }
    function init(kpis, points) { render(kpis, points); }
    return { init };
})();

// ----------------------------- Fixed Widget Module --------------------------

const FixedWidget = (() => {
    function init(kpis, points) {
        if (!kpis) return;

        const donut = document.getElementById("fixedDonutSmall");
        if (donut)
            new Chart(donut, {
                type: "doughnut",
                data: {
                    labels: ["Funded", "Remaining"],
                    datasets: [{
                        data: [kpis.funded_pct, 100 - kpis.funded_pct],
                        backgroundColor: ["#198754", "#e9ecef"]
                    }]
                },
                options: { cutout: "70%", plugins: { legend: { display: false } } }
            });

        const trend = document.getElementById("fixedTrendSmall");
        if (trend && points?.length)
            new Chart(trend, {
                type: "line",
                data: {
                    labels: points.map(p => p.date),
                    datasets: [{
                        label: "Cumulative Fixed ($)",
                        data: points.map(p => p.balance),
                        borderColor: "#0d6efd",
                        borderWidth: 2,
                        fill: false,
                        tension: 0.3
                    }]
                },
                options: { plugins: { legend: { display: false } }, responsive: true }
            });
    }
    return { init };
})();

// ----------------------------- Pairing --------------------------

function renderAffinity(rows) {

    const body = document.getElementById("affinityBody");
    if (!body) return;

    if (!rows.length) {
        body.innerHTML = "<tr><td colspan='5' class='text-muted'>Not enough data to compute pairs.</td></tr>";
        return;
    }

    // Build rows (keep it snappy)
    const html = rows.map(r => {
        const cov = (r.coverage_pct || 0) * 100;
        const lift = r.lift == null ? "—" : r.lift.toFixed(2);
        return `
      <tr>
        <td>${escapeHtml(r.a || "")}</td>
        <td>${escapeHtml(r.b || "")}</td>
        <td class="text-end">${(r.co_count || 0).toLocaleString()}</td>
        <td class="text-end">${cov.toFixed(1)}%</td>
        <td class="text-end">${lift}</td>
      </tr>`;
    }).join("");
    body.innerHTML = html;
}

// tiny HTML escape to be safe
function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, m =>
        ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[m]));
}

function enableTooltips() {
    const nodes = document.querySelectorAll('[data-bs-toggle="tooltip"]');
    nodes.forEach(el => { try { new bootstrap.Tooltip(el); } catch (_) { } });
}

// ----------------------------- App Bootstrap -------------------------------
document.addEventListener("DOMContentLoaded", function () {
    Utils.log("App initialized");
    DashboardChart.init();
    DailyCloseForm.init();
    EditClosingModal.init();
    DeleteClosingModal.init();
    ItemsPage.init();
    FixedCoverageReport.init(window.fixedKpis, window.fixedPoints)
    if (window.fixedKpis) FixedWidget.init(window.fixedKpis, window.fixedPoints);
    IntelligencePOS.init();

    const salesInput = document.getElementById("sales");
    if (salesInput && salesInput.form) {

        salesInput.addEventListener("focus", () => salesInput.select());
        // Allow Enter key to submit immediately
        salesInput.form.addEventListener("keypress", (e) => {
            if (e.key === "Enter") e.target.form.submit();
        });
    }
});
