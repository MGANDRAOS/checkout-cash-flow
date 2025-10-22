// ----------------------------- Intelligence POS Module ----------------------
const IntelligencePOS = (() => {
  let inited = false;
  const charts = {};
  let selectedSubgroup = null;


  const $ = (id) => document.getElementById(id);
  const fmtNum = (n, d = 0) =>
    n == null ? "—" : Number(n).toLocaleString(undefined, { maximumFractionDigits: d, minimumFractionDigits: d });
  const fmtMoney = (n) => (n == null ? "—" : `$ ${Number(n).toFixed(2)}`);

  async function fetchJSON(url) {
    const r = await fetch(url, { headers: { Accept: "application/json" } });
    if (!r.ok) throw new Error(`HTTP ${r.status} for ${url}`);
    return r.json();
  }

  function destroyChart(key) {
    if (charts[key]) {
      charts[key].destroy();
      charts[key] = null;
    }
  }

  // fetch JSON helper (module-local)
  async function j(url) {
    const r = await fetch(url, { headers: { "Accept": "application/json" } });
    if (!r.ok) throw new Error(`HTTP ${r.status} for ${url}`);
    return await r.json();
  }


  const fmtLBP = (n) => (n == null ? "—" : `${Math.round(Number(n)).toLocaleString()} LBP`);


  // --- Defensive accessors for timing data ---
  const getClockHour = (r) => {
    // primary: clock_hour (0..23)
    if (Number.isFinite(r?.clock_hour)) return r.clock_hour;
    // fallback: biz_hour (0..23 where 0 == 07:00); map back to local clock hour
    if (Number.isFinite(r?.biz_hour)) return (r.biz_hour + 7) % 24;
    // ultimate fallback: hour (already clock hour)
    if (Number.isFinite(r?.hour)) return r.hour;
    return null;
  };

  const getAvgReceipts = (r) => {
    // primary: avg_receipts
    if (r?.avg_receipts != null) return Number(r.avg_receipts);
    // fallback aliases from SQL
    if (r?.avg_rcpts != null) return Number(r.avg_rcpts);
    if (r?.avg != null) return Number(r.avg);
    if (r?.receipts != null) return Number(r.receipts);
    return 0;
  };

  const fmtHour = (h) => (h == null ? "—" : String(h).padStart(2, "0") + ":00");


  // ---------- KPIs ----------
  function renderKPIs(k) {
    const map = {
      kpiTotalReceipts: fmtNum(k?.total_receipts),
      kpiAvgReceipt: fmtMoney(k?.avg_receipt_value),
      kpiItemsPerReceipt: fmtNum(k?.items_per_receipt, 2),
      kpiUniqueItems: fmtNum(k?.unique_items),
    };
    Object.entries(map).forEach(([id, val]) => {
      const el = $(id);
      if (el) el.textContent = val;
    });
  }

  // ---------- Charts ----------
  function renderReceiptsByDay(points) {
    const el = $("chartReceiptsByDay");
    if (!el) return;
    destroyChart("rbd");
    charts.rbd = new Chart(el, {
      type: "bar",
      data: {
        labels: (points || []).map((p) => p.date || ""),
        datasets: [{ label: "Receipts", data: (points || []).map((p) => p.receipts || 0) }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: { x: { ticks: { color: "#555" } }, y: { beginAtZero: true, ticks: { color: "#555" } } },
      },
    });
  }

  function renderHourly(points) {
    const el = $("chartHourlyReceipts");
    if (!el) return;
    destroyChart("hourly");
    charts.hourly = new Chart(el, {
      type: "line",
      data: {
        labels: (points || []).map((p) => String(p.hour).padStart(2, "0") + ":00"),
        datasets: [{ label: "Receipts / hour", data: (points || []).map((p) => p.receipts || 0), tension: 0.3 }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: { x: { ticks: { color: "#555" } }, y: { beginAtZero: true, ticks: { color: "#555" } } },
      },
    });
  }

  function renderTopItems(items) {
    const el = $("chartTopItems");
    if (!el) return;
    destroyChart("top");
    charts.top = new Chart(el, {
      type: "bar",
      data: {
        labels: (items || []).map((r) => r.item || ""),
        datasets: [{ label: "Qty", data: (items || []).map((r) => r.qty || 0) }],
      },
      options: {
        indexAxis: "y",
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: { x: { beginAtZero: true, ticks: { color: "#555" } }, y: { ticks: { color: "#555" } } },
      },
    });
  }

  function renderSubgroupBar(rows) {
    const el = document.getElementById("chartSubgroup"); if (!el) return;
    if (charts.subgroupBar) { charts.subgroupBar.destroy(); charts.subgroupBar = null; }

    // Sort by amount desc; cap to top 12 (already capped in API, but safe)
    const data = (rows || []).slice(0, 12);
    charts.subgroupBar = new Chart(el, {
      type: "bar",
      data: {
        labels: data.map(r => r.subgroup || "Unknown"),
        datasets: [{ label: "Amount", data: data.map(r => r.amount || 0) }]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: { x: { ticks: { color: "#555" } }, y: { beginAtZero: true, ticks: { color: "#555" } } }
      }
    });
    // Click-to-drill-down
    el.onclick = (evt) => {
      const pts = charts.subgroupBar.getElementsAtEventForMode(evt, "nearest", { intersect: true }, true);
      if (!pts.length) return;
      const idx = pts[0].index;
      const label = charts.subgroupBar.data.labels[idx];
      onSubgroupSelected(label);
    };
  }

  function renderSubgroupShare(rows) {
    const el = document.getElementById("chartSubgroupShare"); if (!el) return;
    if (charts.subgroupShare) { charts.subgroupShare.destroy(); charts.subgroupShare = null; }

    // Sort by amount desc; top 7 slices, rest → 'Other'
    const sorted = (rows || []).slice().sort((a, b) => (b.amount || 0) - (a.amount || 0));
    const top = sorted.slice(0, 7);

    const labels = top.map(r => r.subgroup || "Unknown");
    const amounts = top.map(r => r.amount || 0);

    const otherAmt = sorted.slice(7).reduce((s, r) => s + (r.amount || 0), 0);
    if (otherAmt > 0) { labels.push("Other"); amounts.push(otherAmt); }

    const total = amounts.reduce((s, v) => s + v, 0);
    if (total <= 0 || labels.length < 2) {
      el.parentElement.innerHTML = "<div class='text-muted small'>Not enough subgroup variety to chart.</div>";
      return;
    }

    // Convert to percentage share (keep 1 decimal place)
    const perc = amounts.map(v => (v / total) * 100);

    charts.subgroupShare = new Chart(el, {
      type: "doughnut",
      data: { labels, datasets: [{ data: perc }] },
      options: {
        responsive: true, maintainAspectRatio: false, cutout: "70%",
        plugins: {
          legend: { position: "bottom" },
          tooltip: {
            callbacks: {
              // Show both % and absolute LBP in the tooltip
              label: (ctx) => {
                const i = ctx.dataIndex;
                const pct = ctx.parsed;               // already percent value
                const amt = amounts[i] || 0;          // closure-captured absolute
                return `${ctx.label}: ${pct.toFixed(1)}% (${fmtLBP(amt)})`;
              }
            }
          }
        }
      }
    });

    el.onclick = (evt) => {
      const pts = charts.subgroupShare.getElementsAtEventForMode(evt, "nearest", { intersect: true }, true);
      if (!pts.length) return;
      const idx = pts[0].index;
      const label = charts.subgroupShare.data.labels[idx];
      if (label === "Other") return; // can't drill into collapsed bucket
      onSubgroupSelected(label);
    };
  }

  function onSubgroupSelected(name) {
    selectedSubgroup = name;
    const t = document.getElementById("selSubgroupName");
    if (t) t.textContent = name;
    fetchTopItemsInSubgroup(name);
  }

  async function fetchTopItemsInSubgroup(name) {
    const url = `/api/intelligence/subgroup-top-items?name=${encodeURIComponent(name)}`;
    try {
      const rows = await j(url);
      renderTopItemsInSubgroup(rows || [], name);
    } catch (err) {
      console.error("[IntelligencePOS] subgroup drilldown failed:", err);
    }
  }

  function renderTopItemsInSubgroup(rows, name) {
    const el = document.getElementById("chartSubgroupItems"); if (!el) return;
    if (charts.subgroupItems) { charts.subgroupItems.destroy(); charts.subgroupItems = null; }

    if (!rows.length) {
      el.parentElement.innerHTML = "<div class='text-muted small'>No items found for this subgroup in the selected period.</div>";
      return;
    }

    charts.subgroupItems = new Chart(el, {
      type: "bar",
      data: {
        labels: rows.map(r => r.item || ""),
        datasets: [
          { label: "Qty", yAxisID: "y1", data: rows.map(r => r.qty || 0) },
          { label: "Amount (LBP)", yAxisID: "y2", data: rows.map(r => r.amount || 0) }
        ]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: {
          legend: { position: "bottom" }, tooltip: {
            callbacks: {
              label: (ctx) => ctx.dataset.yAxisID === "y2"
                ? `${ctx.dataset.label}: ${fmtLBP(ctx.parsed.y)}`
                : `${ctx.dataset.label}: ${ctx.parsed.y}`
            }
          }
        },
        scales: {
          x: { ticks: { color: "#555" } },
          y1: { position: "left", beginAtZero: true, ticks: { color: "#555" }, title: { display: true, text: "Qty" } },
          y2: { position: "right", beginAtZero: true, grid: { drawOnChartArea: false }, ticks: { color: "#555" }, title: { display: true, text: "LBP" } }
        }
      }
    });
  }


  function renderItemsPerReceipt(rows) {
    const el = document.getElementById("chartItemsPerReceipt"); if (!el) return;
    if (charts.ipr) { charts.ipr.destroy(); charts.ipr = null; }
    charts.ipr = new Chart(el, {
      type: "bar",
      data: {
        labels: rows.map(r => r.bin),
        datasets: [{ label: "Receipts", data: rows.map(r => r.count || 0) }]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: { x: { ticks: { color: "#555" } }, y: { beginAtZero: true, ticks: { color: "#555" } } }
      }
    });
  }


  function renderReceiptAmounts(rows) {
    const el = document.getElementById("chartReceiptAmounts"); if (!el) return;
    if (charts.ramt) { charts.ramt.destroy(); charts.ramt = null; }
    charts.ramt = new Chart(el, {
      type: "bar",
      data: {
        labels: rows.map(r => r.bin),
        datasets: [{ label: "Receipts", data: rows.map(r => r.count || 0) }]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: { x: { ticks: { color: "#555" } }, y: { beginAtZero: true, ticks: { color: "#555" } } }
      }
    });
  }


  function renderSubgroupVelocity(rows) {
    const el = document.getElementById("chartSubgroupVelocity"); if (!el) return;
    if (charts.vel) { charts.vel.destroy(); charts.vel = null; }

    // Show delta% as bars; tooltip also includes absolute LBP for context
    const labels = rows.map(r => r.subgroup || "Unknown");
    const deltas = rows.map(r => (r.delta_pct == null ? 0 : r.delta_pct * 100));

    charts.vel = new Chart(el, {
      type: "bar",
      data: { labels, datasets: [{ label: "Δ% (last 7d vs prior 7d)", data: deltas }] },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: (ctx) => {
                const i = ctx.dataIndex;
                const last = rows[i].last7 || 0;
                const prev = rows[i].prev7 || 0;
                const pct = deltas[i];
                return `${pct.toFixed(1)}%  (last7: ${Math.round(last).toLocaleString()} LBP, prev7: ${Math.round(prev).toLocaleString()} LBP)`;
              }
            }
          }
        },
        scales: {
          x: { ticks: { color: "#555" } },
          y: {
            ticks: {
              color: "#555",
              callback: (v) => `${v}%`
            },
            grid: { drawBorder: true },
            beginAtZero: true
          }
        }
      }
    });
  }


  function renderHourlyProfile(rows) {
    const el = document.getElementById("chartHourlyProfile"); if (!el) return;
    if (charts.hourlyProfile) { charts.hourlyProfile.destroy(); charts.hourlyProfile = null; }

    // Fallback to 24 hours if response is empty/short
    const hours = Array.from({ length: 24 }, (_, i) => i);
    const payload = (rows && rows.length === 24)
      ? rows
      : hours.map(h => ({ clock_hour: (h + 7) % 24, avg_receipts: 0 }));

    const labels = payload.map(r => String(getClockHour(r)).padStart(2, "0") + ":00");
    const data = payload.map(r => getAvgReceipts(r));

    charts.hourlyProfile = new Chart(el, {
      type: "line",
      data: { labels, datasets: [{ label: "Avg receipts", data, tension: 0.25 }] },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: { x: { ticks: { color: "#555" } }, y: { beginAtZero: true, ticks: { color: "#555" } } }
      }
    });
  }


  function renderDowProfile(rows) {
    const el = document.getElementById("chartDowProfile"); if (!el) return;
    if (charts.dowProfile) { charts.dowProfile.destroy(); charts.dowProfile = null; }

    const labels = (rows || []).map(r => r.dow_label || "");
    const data = (rows || []).map(r => getAvgReceipts(r)); // handles avg_rcpts vs avg_receipts

    if (!labels.length) {
      el.parentElement.innerHTML = "<div class='text-muted small'>No day-of-week data.</div>";
      return;
    }

    charts.dowProfile = new Chart(el, {
      type: "bar",
      data: { labels, datasets: [{ label: "Avg receipts/day", data }] },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: { x: { ticks: { color: "#555" } }, y: { beginAtZero: true, ticks: { color: "#555" } } }
      }
    });
  }

  function renderPeakHours(rows) {
    const body = document.getElementById("peakHoursBody"); if (!body) return;

    const arr = (Array.isArray(rows) ? rows : [])
      .map(r => ({ hour: getClockHour(r), avg: getAvgReceipts(r) }))
      .filter(x => x.hour != null);

    if (!arr.length) {
      body.innerHTML = "<tr><td colspan='3' class='text-muted'>No data.</td></tr>";
      return;
    }

    // Peak = top 5 across all hours (unchanged)
    const byAvgDesc = arr.slice().sort((a, b) => b.avg - a.avg);
    const top5 = byAvgDesc.slice(0, 5);

    // Quiet = bottom 3 but only during normal operation hours: 08:00..23:59 and 00:00..03:59
    const isOpHour = (h) => (h >= 8 || h <= 3);         // 8→23 and 0→3
    const opHours = arr.filter(x => isOpHour(x.hour));

    if (!opHours.length) {
      body.innerHTML = "<tr><td colspan='3' class='text-muted'>No operational-hour data (08:00–03:00).</td></tr>";
      return;
    }

    const byAvgAscOp = opHours.slice().sort((a, b) => a.avg - b.avg);
    const quiet3 = byAvgAscOp.slice(0, 3);

    const renderRow = (rankLabel, h) =>
      `<tr><td>${rankLabel}</td><td>${fmtHour(h.hour)}</td><td class="text-end">${h.avg.toFixed(2)}</td></tr>`;

    let html = "";
    top5.forEach((h, i) => { html += renderRow(`#${i + 1}`, h); });
    html += `<tr><td colspan="3" class="table-light"></td></tr>`;
    quiet3.forEach((h, i) => { html += renderRow(`Quiet #${i + 1}`, h); });

    body.innerHTML = html;
  }


  function renderTopWindows(payload) {
    const topBody = document.getElementById("topWindowsBody");
    const quietBody = document.getElementById("quietWindowsBody");
    if (!topBody || !quietBody) return;

    const fmtHour = (h) => String(h).padStart(2, "0") + ":00";
    const fmtLBP = (n) => (n == null ? "—" : `${Math.round(Number(n)).toLocaleString()} LBP`);

    const renderRows = (rows) => {
      if (!rows || !rows.length) {
        return "<tr><td colspan='3' class='text-muted'>No data.</td></tr>";
      }
      return rows.map(r => `
      <tr>
        <td>${fmtHour(r.start_clock)}–${fmtHour(r.end_clock)}</td>
        <td class="text-end">${(r.avg_receipts || 0).toFixed(2)}</td>
        <td class="text-end">${fmtLBP(r.avg_amount || 0)}</td>
      </tr>
    `).join("");
    };

    topBody.innerHTML = renderRows(payload.top);
    quietBody.innerHTML = renderRows(payload.quiet);
  }








  // ---------- Boot ----------
  async function init() {
    const root = $("intelligence-root");
    if (!root || inited) return;
    inited = true;

    try {
      const [
        kpisRes,
        receiptsByDayRes,
        hourlyRes,
        topItemsRes,
        subgroupRes,
        iprData,
        amtData,
        velData,
        affinityData,
        hourlyProfileData,
        dowProfileData,
        topWindowsData
      ] = await Promise.all([
        fetchJSON("/api/intelligence/kpis"),
        fetchJSON("/api/intelligence/receipts-by-day"),
        fetchJSON("/api/intelligence/hourly-today"),
        fetchJSON("/api/intelligence/top-items"),
        fetchJSON("/api/intelligence/subgroup"),
        fetchJSON("/api/intelligence/items-per-receipt"),
        fetchJSON("/api/intelligence/receipt-amounts"),
        fetchJSON("/api/intelligence/subgroup-velocity"),
        fetchJSON("/api/intelligence/affinity"),
        fetchJSON("/api/intelligence/hourly-profile"),
        fetchJSON("/api/intelligence/dow-profile"),
        fetchJSON("/api/intelligence/top-windows"),
      ]);

      enableTooltips();
      renderKPIs(kpisRes ?? {});
      renderReceiptsByDay(receiptsByDayRes ?? []);
      renderHourly(hourlyRes ?? []);
      renderTopItems(topItemsRes ?? []);
      renderSubgroupBar(subgroupRes ?? []);
      renderSubgroupShare(subgroupRes || []);
      renderItemsPerReceipt(iprData || []);
      renderReceiptAmounts(amtData || []);
      renderSubgroupVelocity(velData || []);
      renderAffinity(affinityData || []);
      renderHourlyProfile(hourlyProfileData || []);
      renderDowProfile(dowProfileData || []);
      renderPeakHours(hourlyProfileData || []);
      renderTopWindows(topWindowsData || []);


    } catch (err) {
      console.error("[IntelligencePOS] load failed:", err);
    }

    // Clear selection
    document.addEventListener("click", (e) => {
      if (e.target && e.target.id === "clearSubgroup") {
        selectedSubgroup = null;
        const t = document.getElementById("selSubgroupName"); if (t) t.textContent = "—";
        const el = document.getElementById("chartSubgroupItems");
        if (charts.subgroupItems) { charts.subgroupItems.destroy(); charts.subgroupItems = null; }
        if (el) el.parentElement.innerHTML = "<div class='chart-wrap'><canvas id='chartSubgroupItems'></canvas></div>";
      }
    });
  }

  return { init };
})();
