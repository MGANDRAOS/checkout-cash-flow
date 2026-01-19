// static/js/modules/item_trends.js
// Self-contained module with init().
// IMPORTANT: We also auto-init only when we detect the page container, so you don't need to touch main.js.

window.ItemTrendsModule = (function () {
  let chartInstance = null;
  let dataTableInstance = null;

  function setStatus(message) {
    const el = document.getElementById("it-status");
    if (el) el.textContent = message || "";
  }

  function getValue(id) {
    const el = document.getElementById(id);
    return el ? el.value : "";
  }

  function getChecked(id) {
    const el = document.getElementById(id);
    return !!(el && el.checked);
  }


  async function fetchJson(url) {
    const response = await fetch(url, { headers: { "Accept": "application/json" } });
    if (!response.ok) {
      const text = await response.text();
      throw new Error(text || `HTTP ${response.status}`);
    }
    return response.json();
  }

  function buildQueryParams() {
    const startDate = getValue("it-start-date");
    const endDate = getValue("it-end-date");

    const bucket = getValue("it-bucket");
    const topN = getValue("it-top-n");
    const rankBy = getValue("it-rank-by");
    const subgroup = getValue("it-subgroup");
    const itemCodes = getValue("it-item-codes");

    const params = new URLSearchParams();
    params.set("start_date", startDate);
    params.set("end_date", endDate);
    params.set("bucket", bucket);
    params.set("top_n", topN);
    params.set("rank_by", rankBy);
    params.set("format", "long");

    if (subgroup) params.set("subgroup", subgroup);
    if (itemCodes && itemCodes.trim()) params.set("item_codes", itemCodes.trim());

    return params.toString();
  }
  function addDays(dateStr, days) {
    const d = new Date(dateStr + "T00:00:00");
    d.setDate(d.getDate() + days);
    return d.toISOString().slice(0, 10);
  }

  function addMonths(dateStr, months) {
    const d = new Date(dateStr + "T00:00:00");
    d.setMonth(d.getMonth() + months);
    return d.toISOString().slice(0, 10);
  }

  function buildFutureLabels(lastLabel, bucket, horizon) {
    const labels = [];
    let cur = lastLabel;

    for (let i = 0; i < horizon; i++) {
      if (bucket === "daily") cur = addDays(cur, 1);
      else if (bucket === "weekly") cur = addDays(cur, 7);
      else cur = addMonths(cur, 1);

      labels.push(cur);
    }

    return labels;
  }

  function movingAverage(values, windowSize) {
    // Average of last N real values; ignores future zeros.
    const slice = values.slice(Math.max(0, values.length - windowSize));
    if (!slice.length) return 0;

    const sum = slice.reduce((a, b) => a + b, 0);
    return sum / slice.length;
  }

  function computeSimpleSlope(values, windowSize) {
    // Linear trend approximation without heavy math:
    // slope = (last - first) / (n-1) over the last windowSize points.
    const n = Math.min(windowSize, values.length);
    if (n < 2) return 0;

    const slice = values.slice(values.length - n);
    const first = slice[0];
    const last = slice[slice.length - 1];
    return (last - first) / (slice.length - 1);
  }

  function slopeToDirection(slope, threshold = 0.05) {
    // threshold avoids flipping on tiny noise
    if (slope > threshold) return "Up";
    if (slope < -threshold) return "Down";
    return "Flat";
  }


  function groupForChart(rows) {
    const bucket = getValue("it-bucket");
    const forecastEnabled = getChecked("it-forecast-enabled");
    const horizon = parseInt(getValue("it-forecast-horizon") || "8", 10);
    const maWindow = parseInt(getValue("it-forecast-window") || "6", 10);

    // Transform long rows into Chart.js datasets
    const labelsSet = new Set();
    const itemMap = new Map(); // item -> Map(bucket -> qty)

    rows.forEach(r => {
      labelsSet.add(r.bucket_start);

      const key = r.item; // display label
      if (!itemMap.has(key)) itemMap.set(key, new Map());
      itemMap.get(key).set(r.bucket_start, Number(r.qty || 0));
    });

    const actualLabels = Array.from(labelsSet).sort(); // YYYY-MM-DD lex sort OK
    const lastActualLabel = actualLabels.length ? actualLabels[actualLabels.length - 1] : null;

    // Build final labels = actual + future (optional)
    let futureLabels = [];
    if (forecastEnabled && lastActualLabel) {
      futureLabels = buildFutureLabels(lastActualLabel, bucket, horizon);
    }

    const labels = actualLabels.concat(futureLabels);

    const datasets = [];
    itemMap.forEach((bucketQtyMap, itemName) => {
      // Build actual data first
      const actualData = actualLabels.map(label => bucketQtyMap.get(label) || 0);

      if (!forecastEnabled || !futureLabels.length) {
        // No forecast: simple dataset
        datasets.push({
          label: itemName,
          data: actualData,
          tension: 0.25,
        });
        return;
      }

      // Forecast: compute forecast value from moving average, then extend flat
      const forecastValue = movingAverage(actualData, maWindow);
      const forecastData = futureLabels.map(() => forecastValue);

      // We want a dashed continuation:
      // - Dataset 1: actual (solid) only on actual labels, null after
      // - Dataset 2: forecast (dashed) starts from last actual point (to connect visually)
      const solidData = labels.map((lbl, idx) => {
        if (idx < actualLabels.length) return actualData[idx];
        return null; // break the line after actual period
      });

      // dashed starts at the last actual point, then continues
      const dashedData = labels.map((lbl, idx) => {
        if (idx < actualLabels.length - 1) return null;
        if (idx === actualLabels.length - 1) return actualData[actualData.length - 1] || 0;
        // after end => forecast values
        return forecastValue;
      });

      // Solid actual
      datasets.push({
        label: itemName,
        data: solidData,
        tension: 0.25,
      });

      // Dashed forecast
      datasets.push({
        label: itemName + " (forecast)",
        data: dashedData,
        tension: 0.25,
        borderDash: [6, 6],
      });
    });

    return { labels, datasets };
  }


  function renderChart(rows) {
    const ctx = document.getElementById("it-chart");
    if (!ctx) return;

    const { labels, datasets } = groupForChart(rows);

    if (chartInstance) {
      chartInstance.destroy();
      chartInstance = null;
    }

    chartInstance = new Chart(ctx, {
      type: "line",
      data: { labels, datasets },
      options: {
        responsive: true,
        plugins: {
          legend: { display: true, position: "bottom" }
        },
        scales: {
          y: { beginAtZero: true }
        }
      }
    });
  }

  function renderTable(rows) {
    const tableEl = document.getElementById("it-table");
    if (!tableEl) return;

    // 1) If DataTables is active, destroy it first (leaves the plain table in DOM)
    if ($.fn.dataTable.isDataTable(tableEl)) {
      $(tableEl).DataTable().destroy();
    }

    // 2) Pivot build: buckets x items
    const bucketsSet = new Set();
    const itemsSet = new Set();

    // bucket -> item -> qty
    const matrix = new Map();

    rows.forEach(r => {
      const bucket = r.bucket_start;
      const item = r.item;

      bucketsSet.add(bucket);
      itemsSet.add(item);

      if (!matrix.has(bucket)) matrix.set(bucket, new Map());
      matrix.get(bucket).set(item, Number(r.qty || 0));
    });

    const buckets = Array.from(bucketsSet).sort(); // YYYY-MM-DD sorts correctly
    const items = Array.from(itemsSet);            // keep natural order

    // 3) Hard reset table HTML so header/body always match the new pivot
    tableEl.innerHTML = "<thead></thead><tbody></tbody>";

    const thead = tableEl.querySelector("thead");
    const tbody = tableEl.querySelector("tbody");

    // Header row
    const headRow = document.createElement("tr");
    headRow.innerHTML =
      `<th>Bucket Start</th>` +
      items.map(it => `<th>${escapeHtml(it)}</th>`).join("") +
      `<th class="text-end">Total</th>`;
    thead.appendChild(headRow);

    // Body rows
    buckets.forEach(bucket => {
      const rowMap = matrix.get(bucket) || new Map();

      let total = 0;
      const cells = items.map(it => {
        const val = rowMap.get(it) || 0;
        total += val;
        return `<td class="text-end">${val.toFixed(2)}</td>`;
      }).join("");

      const tr = document.createElement("tr");
      tr.innerHTML = `<td>${bucket}</td>` + cells + `<td class="text-end fw-semibold">${total.toFixed(2)}</td>`;
      tbody.appendChild(tr);
    });

    // 4) Re-init DataTables fresh
    dataTableInstance = $(tableEl).DataTable({
      pageLength: 25,
      order: [[0, "asc"]],
      scrollX: true,
      destroy: true
    });
  }

  function renderForecastTable(rows) {
    const tableEl = document.getElementById("it-forecast-table");
    const noteEl = document.getElementById("it-forecast-table-note");
    if (!tableEl) return;

    // Remove any previous DataTables instance safely
    if ($.fn.dataTable.isDataTable(tableEl)) {
      $(tableEl).DataTable().destroy();
    }

    const bucket = getValue("it-bucket");
    const forecastEnabled = getChecked("it-forecast-enabled");
    const horizon = parseInt(getValue("it-forecast-horizon") || "8", 10);
    const maWindow = parseInt(getValue("it-forecast-window") || "6", 10);

    // Build pivot
    const { buckets, items, matrix } = buildPivot(rows);

    // If no data
    if (!buckets.length || !items.length) {
      tableEl.querySelector("tbody").innerHTML = "";
      if (noteEl) noteEl.textContent = "";
      return;
    }

    const lastBucket = buckets[buckets.length - 1];

    // Compute per-item stats
    const stats = items.map(item => {
      const series = buckets.map(b => (matrix.get(b)?.get(item)) || 0);
      const avg = series.reduce((a, b) => a + b, 0) / series.length;
      const last = (matrix.get(lastBucket)?.get(item)) || 0;

      const ma = movingAverage(series, maWindow);
      const forecastTotal = ma * horizon;

      const slope = computeSimpleSlope(series, Math.min(6, series.length));
      const direction = slopeToDirection(slope);

      return { item, avg, last, ma, forecastTotal, direction };
    });

    // Sort by forecastTotal desc (most important first)
    stats.sort((a, b) => b.forecastTotal - a.forecastTotal);

    // Render tbody
    const tbody = tableEl.querySelector("tbody");
    tbody.innerHTML = "";

    stats.forEach(s => {
      const badge =
        s.direction === "Up"
          ? `<span class="badge text-bg-success">Up</span>`
          : s.direction === "Down"
            ? `<span class="badge text-bg-danger">Down</span>`
            : `<span class="badge text-bg-secondary">Flat</span>`;

      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${escapeHtml(s.item)}</td>
        <td class="text-end">${s.avg.toFixed(2)}</td>
        <td class="text-end">${s.last.toFixed(2)}</td>
        <td class="text-end">${forecastEnabled ? s.forecastTotal.toFixed(2) : "<span class='text-secondary'>Enable forecast</span>"}</td>
        <td>${badge}</td>
      `;
      tbody.appendChild(tr);
    });

    // Note (explains the bucket/horizon)
    if (noteEl) {
      const hLabel = `${horizon} ${bucket}${horizon > 1 ? "s" : ""}`;
      noteEl.textContent = `Forecast horizon: next ${hLabel} | MA window: ${maWindow}`;
    }

    // Init DataTables for sorting/search
    $(tableEl).DataTable({
      pageLength: 15,
      order: [[3, "desc"]],
      destroy: true
    });
  }


  function renderMomentumKPIs(rows) {
    const risersEl = document.getElementById("it-kpi-risers");
    const fallersEl = document.getElementById("it-kpi-fallers");
    const fastEl = document.getElementById("it-kpi-fastmovers");

    if (!risersEl || !fallersEl || !fastEl) return;

    risersEl.innerHTML = "";
    fallersEl.innerHTML = "";
    fastEl.innerHTML = "";

    const { buckets, items, matrix } = buildPivot(rows);

    // Need at least 2 buckets for 1-bucket momentum
    if (buckets.length < 2) {
      risersEl.innerHTML = `<div class="text-secondary">Not enough data (need at least 2 buckets).</div>`;
      fallersEl.innerHTML = `<div class="text-secondary">Not enough data (need at least 2 buckets).</div>`;
    } else {
      const lastIdx = buckets.length - 1;
      const prevIdx = buckets.length - 2;

      const oneBucketChanges = items.map(item => {
        const current = (matrix.get(buckets[lastIdx])?.get(item)) || 0;
        const previous = (matrix.get(buckets[prevIdx])?.get(item)) || 0;
        const pct = computePercentChange(current, previous);

        return { item, current, previous, pct };
      });

      const risers = oneBucketChanges
        .filter(x => x.pct > 0)
        .sort((a, b) => b.pct - a.pct)
        .slice(0, 5);

      const fallers = oneBucketChanges
        .filter(x => x.pct < 0)
        .sort((a, b) => a.pct - b.pct) // most negative first
        .slice(0, 5);

      risersEl.innerHTML = risers.length ? risers.map(x => `
        <div class="d-flex justify-content-between border-bottom py-1">
          <div class="text-truncate pe-2">${escapeHtml(x.item)}</div>
          <div class="fw-semibold">${formatPct(x.pct)}</div>
        </div>
        <div class="text-secondary small mb-1">
          ${x.previous.toFixed(0)} → ${x.current.toFixed(0)} (last vs previous bucket)
        </div>
      `).join("") : `<div class="text-secondary">No increases in the last bucket.</div>`;

      fallersEl.innerHTML = fallers.length ? fallers.map(x => `
        <div class="d-flex justify-content-between border-bottom py-1">
          <div class="text-truncate pe-2">${escapeHtml(x.item)}</div>
          <div class="fw-semibold">${formatPct(x.pct)}</div>
        </div>
        <div class="text-secondary small mb-1">
          ${x.previous.toFixed(0)} → ${x.current.toFixed(0)} (last vs previous bucket)
        </div>
      `).join("") : `<div class="text-secondary">No drops in the last bucket.</div>`;
    }

    // Need at least 8 buckets for 4 vs 4
    if (buckets.length < 8) {
      fastEl.innerHTML = `<div class="text-secondary">Not enough data (need at least 8 buckets for 4 vs 4).</div>`;
      return;
    }

    const lastEnd = buckets.length - 1;
    const lastStart = buckets.length - 4;
    const prevEnd = buckets.length - 5;
    const prevStart = buckets.length - 8;

    const movers = items.map(item => {
      const last4 = sumWindow(matrix, buckets, item, lastStart, lastEnd);
      const prev4 = sumWindow(matrix, buckets, item, prevStart, prevEnd);
      const pct = computePercentChange(last4, prev4);
      return { item, last4, prev4, pct };
    })
      .sort((a, b) => Math.abs(b.pct) - Math.abs(a.pct))
      .slice(0, 5);

    fastEl.innerHTML = movers.map(x => `
      <div class="d-flex justify-content-between border-bottom py-1">
        <div class="text-truncate pe-2">${escapeHtml(x.item)}</div>
        <div class="fw-semibold">${formatPct(x.pct)}</div>
      </div>
      <div class="text-secondary small mb-1">
        Prev 4: ${x.prev4.toFixed(0)} | Last 4: ${x.last4.toFixed(0)}
      </div>
    `).join("");
  }


  function escapeHtml(text) {
    if (text === null || text === undefined) return "";
    return String(text)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function computePercentChange(current, previous) {
    // Avoid division by zero explosions.
    // If previous is 0 and current > 0 -> treat as "new spike" (very large).
    if (previous === 0 && current === 0) return 0;
    if (previous === 0 && current > 0) return 999; // capped "infinite" rise
    return ((current - previous) / previous) * 100;
  }

  function formatPct(pct) {
    if (pct === 999) return "+∞";
    const sign = pct > 0 ? "+" : "";
    return sign + pct.toFixed(0) + "%";
  }

  function buildPivot(rows) {
    const bucketsSet = new Set();
    const itemsSet = new Set();
    const matrix = new Map(); // bucket -> item -> qty

    rows.forEach(r => {
      const bucket = r.bucket_start;
      const item = r.item;

      bucketsSet.add(bucket);
      itemsSet.add(item);

      if (!matrix.has(bucket)) matrix.set(bucket, new Map());
      matrix.get(bucket).set(item, Number(r.qty || 0));
    });

    const buckets = Array.from(bucketsSet).sort();
    const items = Array.from(itemsSet);

    return { buckets, items, matrix };
  }

  function sumWindow(matrix, buckets, item, startIdx, endIdxInclusive) {
    let total = 0;
    for (let i = startIdx; i <= endIdxInclusive; i++) {
      const b = buckets[i];
      const v = (matrix.get(b)?.get(item)) || 0;
      total += v;
    }
    return total;
  }


  async function loadSubgroups() {
    const select = document.getElementById("it-subgroup");
    if (!select) return;

    try {
      const list = await fetchJson("/api/reports/subgroups");
      // Add options
      list.forEach(sg => {
        const opt = document.createElement("option");
        opt.value = sg.name; // we filter by label
        opt.textContent = sg.name;
        select.appendChild(opt);
      });
    } catch (e) {
      // Non-blocking
      console.warn("Failed to load subgroups:", e);
    }
  }



  function setDefaultDates() {
    // Default: last 60 days
    const startInput = document.getElementById("it-start-date");
    const endInput = document.getElementById("it-end-date");
    if (!startInput || !endInput) return;

    const today = new Date();
    const end = today;
    const start = new Date();
    start.setDate(start.getDate() - 60);

    // YYYY-MM-DD
    endInput.value = end.toISOString().slice(0, 10);
    startInput.value = start.toISOString().slice(0, 10);
  }

  async function generate() {
    setStatus("Generating…");

    try {
      const qs = buildQueryParams();
      const url = `/api/reports/item-trends?${qs}`;
      const rows = await fetchJson(url);

      if (rows && rows.error) {
        throw new Error(rows.error);
      }
      renderForecastTable(rows);
      renderMomentumKPIs(rows);
      renderChart(rows);
      renderTable(rows);

      setStatus(`Done. Rows: ${rows.length}`);
    } catch (e) {
      console.error(e);
      setStatus(`Error: ${e.message || e}`);
      alert(`Item Trends failed:\n${e.message || e}`);
    }
  }

  function reset() {
    document.getElementById("it-subgroup").value = "";
    document.getElementById("it-item-codes").value = "";
    document.getElementById("it-top-n").value = "20";
    document.getElementById("it-rank-by").value = "total";
    document.getElementById("it-bucket").value = "weekly";
    setDefaultDates();
    setStatus("");
  }

  function init() {
    const page = document.getElementById("item-trends-page");
    if (!page) return; // don't run on other pages

    setDefaultDates();
    loadSubgroups();
    // Enable Bootstrap tooltips for all info bubbles on this page
    const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    tooltipTriggerList.forEach(function (el) {
      new bootstrap.Tooltip(el);
    });

    const btn = document.getElementById("it-generate");
    const resetBtn = document.getElementById("it-reset");

    btn.addEventListener("click", generate);
    resetBtn.addEventListener("click", reset);
  }

  return { init };
})();

// Auto-init when DOM is ready (still keeps init() reusable)
document.addEventListener("DOMContentLoaded", function () {
  if (window.ItemTrendsModule && typeof window.ItemTrendsModule.init === "function") {
    window.ItemTrendsModule.init();
  }
});
