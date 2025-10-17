// static/js/main.js
// ============================================================================
//  Main JavaScript Entry Point for the Checkout App
//  Handles: Charts, Forms, UI behavior
// ============================================================================

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
                    {
                        label: "Buffer",
                        data: data.buffer,
                        borderColor: "rgba(16,185,129,1)",
                        backgroundColor: "rgba(16,185,129,0.1)",
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

// ----------------------------- App Bootstrap -------------------------------
document.addEventListener("DOMContentLoaded", function () {
    Utils.log("App initialized");
    DashboardChart.init();
    DailyCloseForm.init();


    const salesInput = document.getElementById("sales");
    salesInput.addEventListener("focus", () => salesInput.select());
    // Allow Enter key to submit immediately
    salesInput.form.addEventListener("keypress", (e) => {
        if (e.key === "Enter") e.target.form.submit();
    });
});
