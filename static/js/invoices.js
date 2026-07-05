// static/js/invoices.js
window.InvoicesModule = (function () {

  function qs(id) { return document.getElementById(id); }

  function escapeHtml(str) {
    return String(str ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function setStatus(text) {
    const el = qs("inv-status");
    if (el) el.textContent = text || "";
  }

  function initTooltips() {
    const list = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    list.forEach(el => new bootstrap.Tooltip(el));
  }

  function toISO(d) {
    const mm = String(d.getMonth() + 1).padStart(2, "0");
    const dd = String(d.getDate()).padStart(2, "0");
    return `${d.getFullYear()}-${mm}-${dd}`;
  }

  // Returns {start, end} ISO strings for a named quick range.
  function quickRange(key) {
    const now = new Date();
    const start = new Date(now);
    const end = new Date(now);

    if (key === "today") {
      // start/end already today
    } else if (key === "yesterday") {
      start.setDate(start.getDate() - 1);
      end.setDate(end.getDate() - 1);
    } else if (key === "last7") {
      start.setDate(start.getDate() - 6);
    } else if (key === "thisMonth") {
      start.setDate(1);
    } else if (key === "lastMonth") {
      const firstOfThis = new Date(now.getFullYear(), now.getMonth(), 1);
      const lastOfLast = new Date(firstOfThis);
      lastOfLast.setDate(lastOfLast.getDate() - 1);
      start.setFullYear(lastOfLast.getFullYear(), lastOfLast.getMonth(), 1);
      end.setFullYear(lastOfLast.getFullYear(), lastOfLast.getMonth(), lastOfLast.getDate());
    }

    return { start: toISO(start), end: toISO(end) };
  }

  function applyQuickRange(key) {
    const startEl = qs("inv-start");
    const endEl = qs("inv-end");
    if (!startEl || !endEl) return;
    const { start, end } = quickRange(key);
    startEl.value = start;
    endEl.value = end;
  }

  function setActiveChip(key) {
    document.querySelectorAll("#inv-quick .snap-chip").forEach(c => {
      c.classList.toggle("active", c.getAttribute("data-quick") === key);
    });
  }

  function clearActiveChip() {
    document.querySelectorAll("#inv-quick .snap-chip").forEach(c => c.classList.remove("active"));
  }

  function ensureDefaultDates() {
    const startEl = qs("inv-start");
    const endEl = qs("inv-end");
    if (!startEl || !endEl) return;

    // Default to yesterday's BizDate (last fully-complete business day).
    if (!startEl.value || !endEl.value) applyQuickRange("yesterday");
  }

  function getFilters() {
    return {
      start: (qs("inv-start")?.value || "").trim(),
      end: (qs("inv-end")?.value || "").trim(),
      q: (qs("inv-search")?.value || "").trim(),
      item_code: (qs("inv-item-code")?.value || "").trim(),
      min_amount: (qs("inv-min")?.value || "").trim(),
      max_amount: (qs("inv-max")?.value || "").trim(),
    };
  }

  function buildUrl(base, params) {
    const usp = new URLSearchParams();
    Object.entries(params || {}).forEach(([k, v]) => {
      if (v === undefined || v === null) return;
      if (String(v).trim() === "") return;
      usp.set(k, v);
    });
    const qs = usp.toString();
    return qs ? `${base}?${qs}` : base;
  }

  async function fetchJson(url) {
    try {
      const res = await fetch(url);
      if (!res.ok) {
        console.error("fetchJson", url, "HTTP", res.status);
        return null;
      }
      return await res.json();
    } catch (e) {
      console.error("fetchJson", url, e);
      return null;
    }
  }

  function formatMoney(v) {
    const n = Number(v);
    if (!Number.isFinite(n)) return "—";
    return n.toLocaleString(undefined, { maximumFractionDigits: 2 });
  }

  function formatNumber(v) {
    const n = Number(v);
    if (!Number.isFinite(n)) return "—";
    return n.toLocaleString(undefined, { maximumFractionDigits: 2 });
  }

  function formatInt(v) {
    const n = Number(v);
    if (!Number.isFinite(n)) return "—";
    return n.toLocaleString(undefined, { maximumFractionDigits: 0 });
  }

  // Margin color class, mirroring the items-sold report (pos / neg / na).
  function marginClass(m) {
    if (m == null || !Number.isFinite(m)) return "na";
    if (m < 0) return "neg";
    if (m > 0) return "pos";
    return "na";
  }

  function marginCell(m) {
    const cls = marginClass(m);
    const txt = (m == null || !Number.isFinite(m)) ? "—" : `${Number(m).toFixed(1)}%`;
    return `<span class="inv-margin ${cls}">${txt}</span>`;
  }

  // A receipt is fully costed when every line has a known cost. Only then do we
  // show profit/margin (full receipt revenue minus a partial cost overstates it).
  function receiptProfit(r) {
    const amount = Number(r.amount || 0);
    const cost = Number(r.cost || 0);
    const fully = Number(r.uncosted_lines || 0) === 0 && Number(r.lines_count || 0) > 0;
    if (!fully) return { fully: false, profit: null, margin: null };
    const profit = amount - cost;
    const margin = amount ? (profit / amount) * 100 : null;
    return { fully: true, profit, margin };
  }

  // Day-level profit uses only that day's fully-costed receipts — revenue AND
  // cost from the same receipt set, so the two bases match.
  function dayProfit(r) {
    const costedSales = Number(r.costed_sales || 0);
    const costedCost = Number(r.costed_recpt_cost || 0);
    const costedReceipts = Number(r.costed_receipts || 0);
    if (costedReceipts <= 0) return { profit: null, margin: null };
    const profit = costedSales - costedCost;
    const margin = costedSales ? (profit / costedSales) * 100 : null;
    return { profit, margin };
  }

  // ---------------------------
  // Modal
  // ---------------------------
  async function openModal(title, sub, bodyHtml) {
    const titleEl = qs("invoiceModalTitle");
    const subEl = qs("invoiceModalSub");
    const bodyEl = qs("invoiceModalBody");

    if (titleEl) titleEl.textContent = title || "Details";
    if (subEl) subEl.textContent = sub || "";
    if (bodyEl) bodyEl.innerHTML = bodyHtml || "";

    const modalEl = qs("invoiceModal");
    // Reparent to <body> so the backdrop stacking context isn't trapped
    // inside a transformed/animated ancestor (e.g. main.container fadeUp).
    if (modalEl && modalEl.parentElement !== document.body) {
      document.body.appendChild(modalEl);
    }
    const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
    modal.show();
  }

  // ---------------------------
  // Tab 1: Invoices
  // ---------------------------
  async function loadInvoices() {
    const f = getFilters();
    const pageSize = 500;
    const allRows = [];
    let total = 0;
    let page = 1;

    // Page through until we've fetched everything (cap at 50 pages = 25k rows for safety)
    while (page <= 50) {
      const url = buildUrl("/api/invoices", {
        start: f.start,
        end: f.end,
        q: f.q,
        item_code: f.item_code,
        min_amount: f.min_amount,
        max_amount: f.max_amount,
        page,
        page_size: pageSize
      });
      const payload = await fetchJson(url);
      if (!payload) break;

      const rows = payload.rows || [];
      total = payload.total ?? total;
      allRows.push(...rows);

      if (rows.length < pageSize) break;        // last page
      if (allRows.length >= total && total > 0) break;
      page += 1;
    }

    return { total: total || allRows.length, rows: allRows };
  }

  function renderInvoices(payload) {
    const table = qs("invoices-table");
    if (!table) return;

    const tbody = table.querySelector("tbody");
    tbody.innerHTML = "";

    const rows = payload?.rows || [];
    const total = payload?.total ?? rows.length;

    const countEl = qs("inv-count");
    if (countEl) countEl.textContent = `${rows.length} shown • ${total} total`;

    let totAmount = 0, totLines = 0, totCost = 0, totProfit = 0, totCostedSales = 0;

    rows.forEach(r => {
      const tr = document.createElement("tr");
      tr.style.cursor = "pointer";
      tr.dataset.rcptId = r.rcpt_id;

      const p = receiptProfit(r);
      const partial = Number(r.uncosted_lines || 0) > 0;
      const dot = partial
        ? `<span class="inv-partial" data-bs-toggle="tooltip" title="${formatInt(r.uncosted_lines)} of ${formatInt(r.lines_count)} lines have no cost"></span>`
        : "";

      totAmount += Number(r.amount || 0);
      totLines += Number(r.lines_count || 0);
      totCost += Number(r.cost || 0);
      if (p.fully) { totProfit += p.profit; totCostedSales += Number(r.amount || 0); }

      tr.innerHTML = `
        <td class="fw-semibold">${escapeHtml(r.rcpt_id)}</td>
        <td>${escapeHtml(r.biz_date || "")}</td>
        <td>${escapeHtml(r.rcpt_date || "")}</td>
        <td class="text-end">${formatMoney(r.amount)}</td>
        <td class="text-end">${formatInt(r.lines_count)}${dot}</td>
        <td class="text-end inv-cost">${formatMoney(r.cost)}</td>
        <td class="text-end">${p.profit == null ? "—" : formatMoney(p.profit)}</td>
        <td class="text-end">${marginCell(p.margin)}</td>
      `;

      tr.addEventListener("click", async () => {
        await openInvoiceDetails(r.rcpt_id);
      });

      tbody.appendChild(tr);
    });

    const blended = totCostedSales ? (totProfit / totCostedSales) * 100 : null;
    const tfoot = table.querySelector("tfoot");
    if (tfoot) {
      tfoot.innerHTML = rows.length ? `
        <tr>
          <td class="fw-semibold">Totals</td>
          <td></td>
          <td class="text-end text-secondary small">${rows.length} receipts</td>
          <td class="text-end">${formatMoney(totAmount)}</td>
          <td class="text-end">${formatInt(totLines)}</td>
          <td class="text-end inv-cost">${formatMoney(totCost)}</td>
          <td class="text-end">${formatMoney(totProfit)}</td>
          <td class="text-end">${marginCell(blended)}</td>
        </tr>
      ` : "";
    }

    initTooltips();
  }

  async function openInvoiceDetails(rcptId) {
    await openModal(
      `Invoice ${rcptId}`,
      "Loading line items…",
      `<div class="d-flex justify-content-center py-4">
         <div class="spinner-border text-secondary" role="status"></div>
       </div>`
    );

    const data = await fetchJson(`/api/invoices/${encodeURIComponent(rcptId)}`);
    if (!data) {
      await openModal(
        `Invoice ${rcptId}`,
        "Failed to load",
        `<div class="text-danger small">Could not load invoice details. Check the server log / browser console.</div>`
      );
      return;
    }

    const rows = data.rows || [];

    const body = `
      <div class="small text-secondary mb-2">
        Line items inside this receipt. Qty comes from receipt contents (ITM_QUANTITY).
      </div>
      <div class="table-responsive">
        <table class="table table-sm align-middle mb-0">
          <thead class="table-light">
            <tr>
              <th>Item</th>
              <th>Subgroup</th>
              <th class="text-end">Qty</th>
            </tr>
          </thead>
          <tbody>
            ${rows.map(r => `
              <tr>
                <td>
                  <div class="fw-semibold">${escapeHtml(r.item_title || r.item_code)}</div>
                  <div class="text-secondary small">${escapeHtml(r.item_code || "")}</div>
                </td>
                <td>${escapeHtml(r.subgroup || "")}</td>
                <td class="text-end">${formatNumber(r.qty)}</td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      </div>
    `;

    await openModal(`Invoice ${rcptId}`, `Items: ${rows.length}`, body);
  }

  // ---------------------------
  // Tab 2: Daily Items
  // ---------------------------
  async function loadDailyItems() {
    const f = getFilters();
    const pageSize = 500;
    const allRows = [];
    let total = 0;
    let page = 1;

    while (page <= 20) {
      const url = buildUrl("/api/invoices/daily-items", {
        start: f.start,
        end: f.end,
        page,
        page_size: pageSize
      });
      const payload = await fetchJson(url);
      if (!payload) break;

      const rows = payload.rows || [];
      total = payload.total ?? total;
      allRows.push(...rows);

      if (rows.length < pageSize) break;
      if (allRows.length >= total && total > 0) break;
      page += 1;
    }

    return { total: total || allRows.length, rows: allRows };
  }

  function renderDailyItems(payload) {
    const table = qs("daily-table");
    if (!table) return;

    const tbody = table.querySelector("tbody");
    tbody.innerHTML = "";

    const rows = payload?.rows || [];
    const total = payload?.total ?? rows.length;

    const countEl = qs("daily-count");
    if (countEl) countEl.textContent = `${rows.length} days shown • ${total} total`;

    let totQty = 0, totReceipts = 0, totSales = 0, totCost = 0, totCostedSales = 0, totCostedCost = 0, totProfit = 0;

    rows.forEach(r => {
      const tr = document.createElement("tr");
      tr.style.cursor = "pointer";
      tr.dataset.bizDate = r.biz_date;

      const p = dayProfit(r);
      const partial = Number(r.costed_receipts || 0) < Number(r.receipts_count || 0);
      const dot = (partial && Number(r.receipts_count || 0) > 0)
        ? `<span class="inv-partial" data-bs-toggle="tooltip" title="${formatInt(r.costed_receipts)} of ${formatInt(r.receipts_count)} receipts fully costed"></span>`
        : "";

      totQty += Number(r.total_qty || 0);
      totReceipts += Number(r.receipts_count || 0);
      totSales += Number(r.total_sales || 0);
      totCost += Number(r.cost || 0);
      totCostedSales += Number(r.costed_sales || 0);
      totCostedCost += Number(r.costed_recpt_cost || 0);
      if (Number(r.costed_receipts || 0) > 0) totProfit += (Number(r.costed_sales || 0) - Number(r.costed_recpt_cost || 0));

      tr.innerHTML = `
        <td class="fw-semibold">${escapeHtml(r.biz_date)}</td>
        <td class="text-end">${formatInt(r.unique_items)}</td>
        <td class="text-end">${formatNumber(r.total_qty)}</td>
        <td class="text-end">${formatInt(r.receipts_count)}${dot}</td>
        <td class="text-end">${formatMoney(r.total_sales)}</td>
        <td class="text-end inv-cost">${formatMoney(r.cost)}</td>
        <td class="text-end">${p.profit == null ? "—" : formatMoney(p.profit)}</td>
        <td class="text-end">${marginCell(p.margin)}</td>
      `;

      tr.addEventListener("click", async () => {
        await openDailyDetail(r.biz_date);
      });

      tbody.appendChild(tr);
    });

    const blended = totCostedSales ? (totProfit / totCostedSales) * 100 : null;
    const tfoot = table.querySelector("tfoot");
    if (tfoot) {
      tfoot.innerHTML = rows.length ? `
        <tr>
          <td class="fw-semibold">Totals</td>
          <td class="text-end text-secondary small">${rows.length} days</td>
          <td class="text-end">${formatNumber(totQty)}</td>
          <td class="text-end">${formatInt(totReceipts)}</td>
          <td class="text-end">${formatMoney(totSales)}</td>
          <td class="text-end inv-cost">${formatMoney(totCost)}</td>
          <td class="text-end">${formatMoney(totProfit)}</td>
          <td class="text-end">${marginCell(blended)}</td>
        </tr>
      ` : "";
    }

    initTooltips();
  }

  async function openDailyDetail(bizDate) {
    await openModal(
      `Daily Items — ${bizDate}`,
      "Loading items…",
      `<div class="d-flex justify-content-center py-4">
         <div class="spinner-border text-secondary" role="status"></div>
       </div>`
    );

    const data = await fetchJson(`/api/invoices/daily-items/${encodeURIComponent(bizDate)}`);
    if (!data) {
      await openModal(
        `Daily Items — ${bizDate}`,
        "Failed to load",
        `<div class="text-danger small">Could not load daily items. Check the server log / browser console.</div>`
      );
      return;
    }

    const rows = data.rows || [];

    // Group rows by subgroup
    const grouped = {};
    rows.forEach(r => {
      const subgroup = (r.subgroup || "Uncategorized").trim() || "Uncategorized";
      if (!grouped[subgroup]) grouped[subgroup] = [];
      grouped[subgroup].push(r);
    });

    const subgroupSections = Object.entries(grouped).map(([subgroup, items]) => {
      const subtotalQty = items.reduce((sum, item) => sum + Number(item.total_qty || 0), 0);

      return `
      <div class="mb-3">
        <div class="fw-semibold border-bottom pb-1 mb-2">
          ${escapeHtml(subgroup)}
          <span class="text-secondary small ms-2">
            (${items.length} items • ${formatNumber(subtotalQty)} qty)
          </span>
        </div>

        <div class="table-responsive">
          <table class="table table-sm align-middle mb-0">
            <thead class="table-light">
              <tr>
                <th>Item</th>
                <th class="text-end">Total qty</th>
              </tr>
            </thead>
            <tbody>
              ${items.map(r => `
                <tr>
                  <td>
                    <div class="fw-semibold">${escapeHtml(r.item_title || r.item_code)}</div>
                    <div class="text-secondary small">${escapeHtml(r.item_code || "")}</div>
                  </td>
                  <td class="text-end">${formatNumber(r.total_qty)}</td>
                </tr>
              `).join("")}
            </tbody>
          </table>
        </div>
      </div>
    `;
    }).join("");

    const body = `
    <div class="small text-secondary mb-3">
      Unique items sold on <b>${escapeHtml(bizDate)}</b>, grouped by subgroup.
    </div>
    ${subgroupSections || '<div class="text-secondary small">No items found for this date.</div>'}
  `;

    await openModal(
      `Daily Items — ${bizDate}`,
      `Grouped by subgroup • ${rows.length} unique items`,
      body
    );
  }

  // ---------------------------
  // KPI summary strip (computed from the loaded invoice rows)
  // ---------------------------
  function renderKpis(invoicePayload) {
    const strip = qs("inv-kpis");
    const caveat = qs("inv-kpi-caveat");
    const rows = invoicePayload?.rows || [];

    if (!rows.length) {
      if (strip) strip.hidden = true;
      if (caveat) caveat.hidden = true;
      return;
    }

    let receipts = rows.length;
    let sales = 0, qty = 0, cost = 0, profit = 0, costedSales = 0, costedReceipts = 0;

    rows.forEach(r => {
      sales += Number(r.amount || 0);
      qty += Number(r.total_qty || 0);
      cost += Number(r.cost || 0);
      const p = receiptProfit(r);
      if (p.fully) { profit += p.profit; costedSales += Number(r.amount || 0); costedReceipts += 1; }
    });

    const avg = receipts ? sales / receipts : 0;
    const margin = costedSales ? (profit / costedSales) * 100 : null;

    const set = (id, txt) => { const el = qs(id); if (el) el.textContent = txt; };
    set("kpi-receipts", formatInt(receipts));
    set("kpi-sales", formatMoney(sales));
    set("kpi-avg", formatMoney(avg));
    set("kpi-qty", formatNumber(qty));
    set("kpi-cost", formatMoney(cost));
    set("kpi-profit", formatMoney(profit));

    const marginEl = qs("kpi-margin");
    if (marginEl) {
      marginEl.className = "inv-kpi-value";
      marginEl.innerHTML = marginCell(margin);
    }

    if (strip) strip.hidden = false;
    if (caveat) {
      const pct = receipts ? Math.round((costedReceipts / receipts) * 100) : 0;
      caveat.textContent = `Profit & margin over ${formatInt(costedReceipts)} of ${formatInt(receipts)} receipts fully costed (${pct}%). Cost totals include every costed line.`;
      caveat.hidden = false;
    }
  }

  // ---------------------------
  // Run
  // ---------------------------
  async function runAll() {
    try {
      setStatus("Loading...");

      const [inv, daily] = await Promise.all([
        loadInvoices(),
        loadDailyItems()
      ]);

      const invPayload = inv || { total: 0, rows: [] };
      renderInvoices(invPayload);
      renderDailyItems(daily || { total: 0, rows: [] });
      renderKpis(invPayload);

      setStatus("");
    } catch (e) {
      console.error(e);
      setStatus("Error loading data");
    }
  }

  function bindEvents() {
    qs("inv-run")?.addEventListener("click", runAll);

    // Quick range chips: set dates, highlight, and load.
    document.querySelectorAll("#inv-quick .snap-chip").forEach(chip => {
      chip.addEventListener("click", () => {
        const key = chip.getAttribute("data-quick");
        applyQuickRange(key);
        setActiveChip(key);
        runAll();
      });
    });

    // Manually editing dates clears the active chip.
    qs("inv-start")?.addEventListener("change", clearActiveChip);
    qs("inv-end")?.addEventListener("change", clearActiveChip);

    // Enter on search triggers apply
    qs("inv-search")?.addEventListener("keydown", (e) => {
      if (e.key === "Enter") runAll();
    });
    qs("inv-item-code")?.addEventListener("keydown", (e) => {
      if (e.key === "Enter") runAll();
    });
  }

  function init() {
    initTooltips();

    // Deep-link from Item360 ("See all invoices"): show the item's full
    // history rather than forcing a yesterday default that would hide it.
    const prefillItem = (qs("inv-item-code")?.value || "").trim();
    if (prefillItem) {
      clearActiveChip();
    } else {
      ensureDefaultDates();
    }

    bindEvents();
    runAll();
  }

  return { init };

})();
