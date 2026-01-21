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

  function todayISO() {
    const d = new Date();
    const mm = String(d.getMonth() + 1).padStart(2, "0");
    const dd = String(d.getDate()).padStart(2, "0");
    return `${d.getFullYear()}-${mm}-${dd}`;
  }

  function daysAgoISO(days) {
    const d = new Date();
    d.setDate(d.getDate() - days);
    const mm = String(d.getMonth() + 1).padStart(2, "0");
    const dd = String(d.getDate()).padStart(2, "0");
    return `${d.getFullYear()}-${mm}-${dd}`;
  }

  function ensureDefaultDates() {
    const startEl = qs("inv-start");
    const endEl = qs("inv-end");
    if (!startEl || !endEl) return;

    // If empty, default to last 30 calendar days (backend uses BizDate anyway)
    if (!endEl.value) endEl.value = todayISO();
    if (!startEl.value) startEl.value = daysAgoISO(30);
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
    const res = await fetch(url);
    if (!res.ok) return null;
    return await res.json();
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
    const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
    modal.show();
  }

  // ---------------------------
  // Tab 1: Invoices
  // ---------------------------
  async function loadInvoices() {
    const f = getFilters();
    const url = buildUrl("/api/invoices", {
      start: f.start,
      end: f.end,
      q: f.q,
      item_code: f.item_code,
      min_amount: f.min_amount,
      max_amount: f.max_amount,
      page: 1,
      page_size: 80
    });
    return await fetchJson(url);
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
    const data = await fetchJson(`/api/invoices/${encodeURIComponent(rcptId)}`);
    if (!data) return;

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
    const url = buildUrl("/api/invoices/daily-items", {
      start: f.start,
      end: f.end,
      page: 1,
      page_size: 60
    });
    return await fetchJson(url);
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
    const data = await fetchJson(`/api/invoices/daily-items/${encodeURIComponent(bizDate)}`);
    if (!data) return;

    const rows = data.rows || [];

    const body = `
      <div class="small text-secondary mb-2">
        Unique items sold on <b>${escapeHtml(bizDate)}</b>. Sorted by total qty.
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
            ${rows.map(r => `
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
    `;

    await openModal(`Daily Items — ${bizDate}`, `Unique items: ${rows.length}`, body);
  }

  // ---------------------------
  // Run
  // ---------------------------
  async function runAll() {
    try {
      setStatus("Loading...");
      ensureDefaultDates();

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
    ensureDefaultDates();
    bindEvents();
    runAll();
  }

  return { init };

})();
