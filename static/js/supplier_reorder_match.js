(() => {
  const API_LIST = "/api/supplier-reorder/match/unmatched";
  const API_CONFIRM = "/api/supplier-reorder/match/confirm";
  const list = document.getElementById("supMatchList");

  function esc(s) {
    return (s ?? "").toString().replace(/[&<>"']/g, c => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  function rowHtml(item) {
    const candidates = item.candidates.map(c =>
      `<option value="${esc(c.code)}">${esc(c.title)} (${Math.round(c.score * 100)}%)</option>`
    ).join("");
    return `
      <div class="sup-match-row" data-id="${item.id}">
        <div class="sup-match-name">${esc(item.name)}<span class="sup-match-supplier">${esc(item.supplier)}</span></div>
        <select class="sup-match-select">
          <option value="">-- no match --</option>
          ${candidates}
        </select>
        <button class="sup-match-confirm" type="button">Confirm</button>
      </div>`;
  }

  async function load() {
    const r = await fetch(API_LIST);
    const body = await r.json();
    list.innerHTML = body.items.map(rowHtml).join("") || "<p>No unmatched items.</p>";
  }

  list.addEventListener("click", async (e) => {
    const btn = e.target.closest(".sup-match-confirm");
    if (!btn) return;
    const row = btn.closest(".sup-match-row");
    const id = row.dataset.id;
    const itm_code = row.querySelector(".sup-match-select").value;
    await fetch(API_CONFIRM, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ supplier_item_id: Number(id), itm_code }),
    });
    row.remove();
  });

  document.addEventListener("DOMContentLoaded", load);
})();
