(() => {
  const root = document.getElementById("supplierReorder");

  const el = {
    kpiCount: document.getElementById("supKpiCount"),
    kpiTotal: document.getElementById("supKpiTotal"),
    kpiUnpriced: document.getElementById("supKpiUnpriced"),
    unmatchedLabel: document.getElementById("supUnmatchedLabel"),
    reorderList: document.getElementById("supReorderList"),
    catalogList: document.getElementById("supCatalogList"),
    catalogSearch: document.getElementById("supCatalogSearch"),
    orderTotals: document.getElementById("supOrderTotals"),
    exportBtn: document.getElementById("supExportBtn"),
  };

  const nfUsd = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });

  // order state: Map<lineKey, {supplier_item_id, supplier, unit_price_usd_cents, qty, name}>
  const order = new Map();

  function esc(s) {
    return (s ?? "").toString().replace(/[&<>"']/g, c => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  function usd(cents) {
    return nfUsd.format((cents || 0) / 100);
  }

  function renderTotals() {
    const bySupplier = new Map();
    for (const line of order.values()) {
      const cents = line.unit_price_usd_cents * line.qty;
      bySupplier.set(line.supplier, (bySupplier.get(line.supplier) || 0) + cents);
    }
    if (bySupplier.size === 0) {
      el.orderTotals.innerHTML = "<span>No items picked yet.</span>";
      return;
    }
    el.orderTotals.innerHTML = [...bySupplier.entries()]
      .map(([supplier, cents]) => `<span>${esc(supplier)}: ${usd(cents)}</span>`)
      .join("");
  }

  function reorderRowHtml(row) {
    const chosen = row.options.find(o => o.supplier_item_id === row.chosen_supplier_item_id);
    const alt = row.options.find(o => o.supplier_item_id !== row.chosen_supplier_item_id);
    const priceHtml = chosen
      ? `<div class="sup-card__title">${esc(chosen.supplier)}</div>
         <div>${usd(chosen.unit_price_usd_cents)}/u${alt ? ` <span class="sup-card__price-alt">${usd(alt.unit_price_usd_cents)}</span>` : ""}</div>`
      : `<div class="sup-card__meta">no supplier price &mdash; <a href="/supplier-reorder/match">match it</a></div>`;
    const supplierSelect = row.options.length > 1
      ? `<select class="sup-supplier-select">
           ${row.options.map(o => `<option value="${o.supplier_item_id}" ${o.supplier_item_id === row.chosen_supplier_item_id ? "selected" : ""}>${esc(o.supplier)} (${usd(o.unit_price_usd_cents)})</option>`).join("")}
         </select>`
      : "";
    return `
      <div class="sup-card" data-stock-item-id="${row.stock_item_id}">
        <div class="sup-card__top">
          <div>
            <div class="sup-card__title">${esc(row.title || row.itm_code)}</div>
            <div class="sup-card__meta">${row.live ?? "?"} left &middot; ${row.days_cover ?? "?"} days cover</div>
          </div>
          <div class="sup-card__price">${priceHtml}</div>
        </div>
        ${chosen ? `
        <div class="sup-card__row">
          ${supplierSelect}
          <input class="sup-qty-input" type="number" min="0" step="1" value="${row.reorder_qty}">
          <div class="sup-line-total">${usd(chosen.unit_price_usd_cents * row.reorder_qty)}</div>
        </div>` : ""}
      </div>`;
  }

  function syncReorderLine(cardEl) {
    const row = cardEl._row;
    const qtyInput = cardEl.querySelector(".sup-qty-input");
    if (!qtyInput) return;
    const select = cardEl.querySelector(".sup-supplier-select");
    const qty = Math.max(0, parseInt(qtyInput.value, 10) || 0);
    const supplierItemId = select ? Number(select.value) : row.chosen_supplier_item_id;
    const chosen = row.options.find(o => o.supplier_item_id === supplierItemId);
    const key = `stock:${row.stock_item_id}`;
    if (qty > 0 && chosen) {
      order.set(key, {
        supplier_item_id: chosen.supplier_item_id, supplier: chosen.supplier,
        unit_price_usd_cents: chosen.unit_price_usd_cents, qty, name: row.title || row.itm_code,
      });
    } else {
      order.delete(key);
    }
    const totalEl = cardEl.querySelector(".sup-line-total");
    if (totalEl && chosen) totalEl.textContent = usd(chosen.unit_price_usd_cents * qty);
    renderTotals();
  }

  async function loadReorderNow() {
    const r = await fetch("/api/supplier-reorder/reorder-now");
    const body = await r.json();
    el.kpiCount.textContent = body.items.length;
    const totalCents = Object.values(body.totals_by_supplier_cents || {}).reduce((a, b) => a + b, 0);
    el.kpiTotal.textContent = usd(totalCents);
    el.kpiUnpriced.textContent = body.unpriced_count;

    el.reorderList.innerHTML = body.items.map(reorderRowHtml).join("") || "<p>Nothing needs reordering right now.</p>";
    [...el.reorderList.children].forEach((cardEl, i) => {
      if (!body.items[i]) return;
      cardEl._row = body.items[i];
      syncReorderLine(cardEl);
    });
  }

  el.reorderList.addEventListener("input", (e) => {
    const card = e.target.closest(".sup-card");
    if (card) syncReorderLine(card);
  });
  el.reorderList.addEventListener("change", (e) => {
    const card = e.target.closest(".sup-card");
    if (card) syncReorderLine(card);
  });

  async function loadUnmatchedCount() {
    const r = await fetch("/api/supplier-reorder/match/unmatched");
    const body = await r.json();
    el.unmatchedLabel.textContent = `${body.items.length} unmatched items`;
  }

  function catalogRowHtml(item) {
    const existing = order.get(`catalog:${item.id}`);
    const qty = existing ? existing.qty : 0;
    return `
      <div class="sup-card" data-supplier-item-id="${item.id}">
        <div class="sup-card__top">
          <div>
            <div class="sup-card__title">${esc(item.name)}</div>
            <div class="sup-card__meta">${esc(item.supplier)} &middot; ${esc(item.category)}</div>
          </div>
          <div class="sup-card__price">
            <span class="sup-price-display">${usd(item.unit_price_usd_cents)}/u</span>
            <input class="sup-price-edit" type="number" step="0.01" min="0" hidden value="${(item.unit_price_usd_cents / 100).toFixed(2)}">
          </div>
        </div>
        <div class="sup-card__row">
          <input class="sup-qty-input sup-catalog-qty" type="number" min="0" step="1" value="${qty}">
          <button class="sup-edit-btn" type="button" title="Edit price"><i class="bi bi-pencil"></i></button>
          <button class="sup-deactivate-btn" type="button" title="Remove from catalog"><i class="bi bi-trash"></i></button>
        </div>
      </div>`;
  }

  const catalogCategorySel = document.getElementById("supCatalogCategory");

  let catalogItems = [];
  async function loadCatalog(q = "") {
    const category = catalogCategorySel.value;
    const params = new URLSearchParams({ q, category, page: "1" });
    const r = await fetch(`/api/supplier-reorder/catalog?${params.toString()}`);
    const body = await r.json();
    catalogItems = body.items;
    el.catalogList.innerHTML = catalogItems.map(catalogRowHtml).join("") || "<p>No matching items.</p>";
  }

  async function loadCategories() {
    const r = await fetch("/api/supplier-reorder/categories");
    const body = await r.json();
    catalogCategorySel.innerHTML = '<option value="">All categories</option>' +
      body.categories.map(c => `<option value="${esc(c)}">${esc(c)}</option>`).join("");
  }

  let searchTimer;
  el.catalogSearch.addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => loadCatalog(el.catalogSearch.value.trim()), 250);
  });
  catalogCategorySel.addEventListener("change", () => loadCatalog(el.catalogSearch.value.trim()));

  el.catalogList.addEventListener("input", (e) => {
    if (!e.target.classList.contains("sup-catalog-qty")) return;
    const card = e.target.closest(".sup-card");
    const id = Number(card.dataset.supplierItemId);
    const item = catalogItems.find(it => it.id === id);
    if (!item) return;
    const qty = Math.max(0, parseInt(e.target.value, 10) || 0);
    const key = `catalog:${id}`;
    if (qty > 0) {
      order.set(key, {
        supplier_item_id: id, supplier: item.supplier,
        unit_price_usd_cents: item.unit_price_usd_cents, qty, name: item.name,
      });
    } else {
      order.delete(key);
    }
    renderTotals();
  });

  el.exportBtn.addEventListener("click", async () => {
    const lines = [...order.values()];
    if (lines.length === 0) return;
    const r = await fetch("/api/supplier-reorder/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ lines }),
    });
    if (!r.ok) return;
    const blob = await r.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "supplier_orders.csv";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  });

  el.catalogList.addEventListener("click", async (e) => {
    const card = e.target.closest(".sup-card");
    if (!card) return;
    const id = Number(card.dataset.supplierItemId);

    if (e.target.closest(".sup-edit-btn")) {
      const display = card.querySelector(".sup-price-display");
      const editInput = card.querySelector(".sup-price-edit");
      if (editInput.hidden) {
        display.hidden = true;
        editInput.hidden = false;
        editInput.focus();
        return;
      }
      const r = await fetch(`/api/supplier-reorder/item/${id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ unit_price_usd: editInput.value }),
      });
      const body = await r.json();
      if (body.ok) loadCatalog(el.catalogSearch.value.trim());
      return;
    }

    if (e.target.closest(".sup-deactivate-btn")) {
      if (!confirm("Remove this item from the catalog?")) return;
      await fetch(`/api/supplier-reorder/item/${id}/deactivate`, { method: "POST" });
      loadCatalog(el.catalogSearch.value.trim());
    }
  });

  const addBtn = document.getElementById("supAddItemBtn");
  const addPanel = document.getElementById("supAddItemPanel");
  const addSupplierSel = document.getElementById("supAddSupplier");

  addBtn.addEventListener("click", () => { addPanel.hidden = !addPanel.hidden; });

  async function loadSuppliersForAdd() {
    const r = await fetch("/api/supplier-reorder/suppliers");
    const body = await r.json();
    addSupplierSel.innerHTML = body.suppliers
      .map(s => `<option value="${s.id}">${esc(s.name)}</option>`).join("");
  }

  document.getElementById("supAddSave").addEventListener("click", async () => {
    const payload = {
      supplier_id: Number(addSupplierSel.value),
      name: document.getElementById("supAddName").value.trim(),
      category: document.getElementById("supAddCategory").value.trim(),
      unit_price_usd: document.getElementById("supAddPrice").value,
    };
    if (!payload.name || !payload.unit_price_usd) return;
    const r = await fetch("/api/supplier-reorder/item", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const body = await r.json();
    if (body.ok) {
      addPanel.hidden = true;
      document.getElementById("supAddName").value = "";
      document.getElementById("supAddPrice").value = "";
      loadCatalog(el.catalogSearch.value.trim());
    }
  });

  window.SupplierReorder = { esc, usd, renderTotals, order, loadReorderNow, loadUnmatchedCount, el };

  document.addEventListener("DOMContentLoaded", () => {
    loadReorderNow();
    loadCatalog();
    loadCategories();
    loadUnmatchedCount();
    loadSuppliersForAdd();
    renderTotals();
  });
})();
