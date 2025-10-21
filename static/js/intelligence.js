// ----------------------------- Intelligence POS Module ----------------------
const IntelligencePOS = (() => {
  let inited = false;
  let charts = {};

  const $ = (id) => document.getElementById(id);
  const fmtNum = (n, d=0) => (n == null ? "—" : Number(n).toLocaleString(undefined, { maximumFractionDigits: d, minimumFractionDigits: d }));
  const fmtMoney = (n) => (n == null ? "—" : `$ ${Number(n).toFixed(2)}`);

  async function j(url) {
    const r = await fetch(url, { headers: { "Accept": "application/json" } });
    if (!r.ok) throw new Error(`HTTP ${r.status} for ${url}`);
    return await r.json();
  }

  function destroy(key) { if (charts[key]) { charts[key].destroy(); charts[key] = null; } }

  // KPIs
  function renderKPIs(k) {
    const map = {
      kpiTotalReceipts: fmtNum(k?.total_receipts),
      kpiAvgReceipt:    fmtMoney(k?.avg_receipt_value),
      kpiItemsPerReceipt: fmtNum(k?.items_per_receipt, 2),
      kpiUniqueItems:   fmtNum(k?.unique_items)
    };
    Object.entries(map).forEach(([id, val]) => { const el = $(id); if (el) el.textContent = val; });
  }

  // Charts
  function renderReceiptsByDay(points) {
    const el = $("chartReceiptsByDay"); if (!el) return;
    destroy("rbd");
    charts.rbd = new Chart(el, {
      type: "bar",
      data: {
        labels: (points || []).map(p => p.date || ""),
        datasets: [{ label: "Receipts", data: (points || []).map(p => p.receipts || 0) }]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: { x: { ticks: { color: "#555" } }, y: { beginAtZero: true, ticks: { color: "#555" } } }
      }
    });
  }

  function renderHourly(points) {
    const el = $("chartHourlyReceipts"); if (!el) return;
    destroy("hourly");
    charts.hourly = new Chart(el, {
      type: "line",
      data: {
        labels: (points || []).map(p => String(p.hour).padStart(2,"0") + ":00"),
        datasets: [{ label: "Receipts / hour", data: (points || []).map(p => p.receipts || 0), tension: 0.3 }]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: { x: { ticks: { color: "#555" } }, y: { beginAtZero: true, ticks: { color: "#555" } } }
      }
    });
  }

  function renderTopItems(items) {
    const el = $("chartTopItems"); if (!el) return;
    destroy("top");
    charts.top = new Chart(el, {
      type: "bar",
      data: {
        labels: (items || []).map(r => r.item || ""),
        datasets: [{ label: "Qty", data: (items || []).map(r => r.qty || 0) }]
      },
      options: {
        indexAxis: "y",
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: { x: { beginAtZero: true, ticks: { color: "#555" } }, y: { ticks: { color: "#555" } } }
      }
    });
  }

  function renderPaymentSplit(rows) {
    const el = $("chartPaymentSplit"); if (!el) return;
    destroy("pay");
    charts.pay = new Chart(el, {
      type: "doughnut",
      data: { labels: (rows || []).map(r => r.method || ""), datasets: [{ data: (rows || []).map(r => r.count || 0) }] },
      options: { responsive: true, maintainAspectRatio: false, cutout: "70%", plugins: { legend: { position: "bottom" } } }
    });
  }

  async function init() {
    const root = $("intelligence-root");
    if (!root || inited) return; inited = true;

    try {
      const [kpis, rbd, hourly, top, pay] = await Promise.all([
        j("/api/intelligence/kpis"),
        j("/api/intelligence/receipts-by-day"),
        j("/api/intelligence/hourly-today"),
        j("/api/intelligence/top-items"),
        j("/api/intelligence/payment-split")
      ]);
      renderKPIs(kpis || {});
      renderReceiptsByDay(rbd || []);
      renderHourly(hourly || []);
      renderTopItems(top || []);
      renderPaymentSplit(pay || []);
    } catch (err) {
      console.error("[IntelligencePOS] load failed:", err);
    }
  }

  return { init };
})();
