// static/js/invoices.js
window.InvoicesModule = (function () {
  let invoicesTable = null;
  let dailyItemsTable = null;

  function initTooltips() {
    const list = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    list.forEach(el => new bootstrap.Tooltip(el));
  }

  function qs(id) { return document.getElementById(id); }

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

  function buildUrl(base, paramsObj) {
    const p = new URLSearchParams();
    Object.entries(paramsObj).forEach(([k, v]) => {
      if (v === "" || v === null || v === undefined) return;
      p.set(k, v);
    });
    return `${base}?${p.toString()}`;
  }

  async function loadInvoices() {
    const filters = getFilters();
    const url = buildUrl("/api/invoices", { ...filters, page: 1, page_size: 200 });

    const res = await fetch(url);
    if (!res.ok) return { total: 0, rows: [] };
    return await res.json();
  }

  async function loadDailyItems() {
    const filters = getFilters();
    const url = buildUrl("/api/invoices/daily-items", { start: filters.start, end: filters.end, page: 1, page_size: 60 });

    const res = await fetch(url);
    if (!res.ok) return { total: 0, rows: [] };
    return await res.json();
  }

  function destroyDataTableIfExists(tableEl) {
    if (!tableEl) return;
    if ($.fn.dataTable.isDataTable(tableEl)) {
      $(tableEl).DataTable().destroy();
    }
  }

  function renderInvoices(rows) {
    const tableEl = qs("invoicesTable");
    if (!tableEl) return;

    destroyDataTableIfExists(tableEl);
    const tbody = tableEl.querySelector("tbody");
    tbody.innerHTML = "";

    rows.forEach(r => {
      const tr = document.createElement("tr");
      tr.style.cursor = "pointer";
      tr.dataset.rcptId = r.rcpt_id;

      tr.innerHTML = `
        <td class="fw-semibold">${r.rcpt_id}</td>
        <td>${r.rcpt_date || "—"}</td>
        <td class="text-end">${Number(r.amount || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}</td>
        <td class="text-end">${Number(r.lines_count || 0).toLocaleString()}</td>
        <td>${r.biz_date || "—"}</td>
      `;
      tbody.appendChild(tr);
    });

    invoicesTable = $(tableEl).DataTable({
      pageLength: 25,
      order: [[1, "desc"]],
      destroy: true
    });
  }

  function renderDailyItems(rows) {
    const tableEl = qs("dailyItemsTable");
    if (!tableEl) return;

    destroyDataTableIfExists(tableEl);
    const tbody = tableEl.querySelector("tbody");
    tbody.innerHTML = "";

    rows.forEach(r => {
      const tr = document.createElement("tr");
      tr.style.cursor = "pointer";
      tr.dataset.bizDate = r.biz_date;

      tr.innerHTML = `
        <td class="fw-semibold">${r.biz_date}</td>
        <td class="text-end">${Number(r.unique_items || 0).toLocaleString()}</td>
        <td class="text-end">${Number(r.total_qty || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}</td>
        <td class="text-end">${Number(r.receipts_count || 0).toLocaleString()}</td>
        <td class="text-end">${Number(r.total_sales || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}</td>
      `;
      tbody.appendChild(tr);
    });

    dailyItemsTable = $(tableEl).DataTable({
      pageLength: 25,
      order: [[0, "desc"]],
      destroy: true
    });
  }

  async function openModal(title, htmlBody) {
    qs("invoiceModalTitle").textContent = title;
    qs("invoiceModalBody").innerHTML = htmlBody;

    const modalEl = qs("invoiceModal");
    const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
    modal.show();
  }

  async function openInvoiceDetails(rcptId) {
    const res = await fetch(`/api/invoices/${encodeURIComponent(rcptId)}`);
    if (!res.ok) return;

    // ADD/UPDATE inside openInvoiceDetails(...) after fetching details JSON

    // IMPORTANT: compute summary safely (no NaN / no fake zeros)
    const amountEl = document.getElementById("invSumAmount");
    const linesEl = document.getElementById("invSumLines");
    const qtyEl = document.getElementById("invSumQty");

    if (amountEl) amountEl.textContent = formatMoney(details.receipt_amount);
    if (linesEl) linesEl.textContent = String((details.lines || []).length);

    let sumQty = 0;
    (details.lines || []).forEach(line => {
      const q = Number(line.qty);
      if (Number.isFinite(q)) sumQty += q;
    });
    if (qtyEl) qtyEl.textContent = formatNumber(sumQty);

    const data = await res.json();
    const rows = data.rows || [];

    const body = `
      <div class="small text-secondary mb-2">
        Line items in this receipt. Qty is taken from receipt contents (ITM_QUANTITY).
      </div>
      <div class="table-responsive">
        <table class="table table-sm align-middle">
          <thead>
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
                <td class="text-end">${Number(r.qty || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}</td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      </div>
    `;

    await openModal(`Invoice ${rcptId}`, body);
  }

  async function openDailyItemsDetails(bizDate) {
    const res = await fetch(`/api/invoices/daily-items/${encodeURIComponent(bizDate)}`);
    if (!res.ok) return;

    const data = await res.json();
    const rows = data.rows || [];

    const body = `
      <div class="small text-secondary mb-2">
        Unique items sold on <strong>${bizDate}</strong>. Total qty is summed across all receipts for that BizDate.
      </div>
      <div class="table-responsive">
        <table class="table table-sm align-middle">
          <thead>
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
                <td class="text-end">${Number(r.total_qty || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}</td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      </div>
    `;

    await openModal(`Daily Items — ${bizDate}`, body);
  }

  function escapeHtml(str) {
    return String(str ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  async function runAll() {
    const invoicesPayload = await loadInvoices();
    renderInvoices(invoicesPayload.rows || []);

    const dailyPayload = await loadDailyItems();
    renderDailyItems(dailyPayload.rows || []);
  }

  function bindEvents() {
    // Run button
    qs("inv-run")?.addEventListener("click", runAll);

    // Invoices row click -> invoice detail modal
    $("#invoicesTable tbody").on("click", "tr", async function () {
      const rcptId = this.dataset.rcptId;
      if (!rcptId) return;
      await openInvoiceDetails(rcptId);
    });

    // Daily items row click -> daily items detail modal
    $("#dailyItemsTable tbody").on("click", "tr", async function () {
      const bizDate = this.dataset.bizDate;
      if (!bizDate) return;
      await openDailyItemsDetails(bizDate);
    });
  }

  function initPrefillItemCode() {
    // If template passed a prefill item_code (deep-link from Item 360)
    const prefill = (window.__prefill_item_code || "").trim();
    if (prefill && qs("inv-item-code")) {
      qs("inv-item-code").value = prefill;
    }
  }

  function formatNumber(v) {
    const n = Number(v);
    if (!Number.isFinite(n)) return "—";
    return n.toLocaleString(undefined, { maximumFractionDigits: 2 });
  }

  function formatMoney(v) {
    const n = Number(v);
    if (!Number.isFinite(n)) return "—";
    return n.toLocaleString(undefined, { maximumFractionDigits: 2 });
  }

  function init() {
    initTooltips();
    initPrefillItemCode();
    bindEvents();
    runAll();
  }

  return { init };
})();
