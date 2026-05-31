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

    rows.forEach(r => {
      const tr = document.createElement("tr");
      tr.style.cursor = "pointer";
      tr.dataset.rcptId = r.rcpt_id;

      tr.innerHTML = `
        <td class="fw-semibold">${escapeHtml(r.rcpt_id)}</td>
        <td>${escapeHtml(r.biz_date || "")}</td>
        <td>${escapeHtml(r.rcpt_date || "")}</td>
        <td class="text-end">${formatMoney(r.amount)}</td>
        <td class="text-end">${formatNumber(r.lines_count)}</td>
      `;

      tr.addEventListener("click", async () => {
        await openInvoiceDetails(r.rcpt_id);
      });

      tbody.appendChild(tr);
    });
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

    rows.forEach(r => {
      const tr = document.createElement("tr");
      tr.style.cursor = "pointer";
      tr.dataset.bizDate = r.biz_date;

      tr.innerHTML = `
        <td class="fw-semibold">${escapeHtml(r.biz_date)}</td>
        <td class="text-end">${formatNumber(r.unique_items)}</td>
        <td class="text-end">${formatNumber(r.total_qty)}</td>
        <td class="text-end">${formatNumber(r.receipts_count)}</td>
        <td class="text-end">${formatMoney(r.total_sales)}</td>
      `;

      tr.addEventListener("click", async () => {
        await openDailyDetail(r.biz_date);
      });

      tbody.appendChild(tr);
    });
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
  // Run
  // ---------------------------
  async function runAll() {
    try {
      setStatus("Loading...");

      const [inv, daily] = await Promise.all([
        loadInvoices(),
        loadDailyItems()
      ]);

      renderInvoices(inv || { total: 0, rows: [] });
      renderDailyItems(daily || { total: 0, rows: [] });

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
