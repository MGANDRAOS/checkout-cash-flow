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

  window.SupplierReorder = { esc, usd, renderTotals, order, loadReorderNow, loadUnmatchedCount, el };

  document.addEventListener("DOMContentLoaded", () => {
    loadReorderNow();
    loadUnmatchedCount();
  });
})();
