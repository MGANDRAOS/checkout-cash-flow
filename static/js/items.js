// static/js/items.js
const ItemsPage = (() => {
    const state = { page: 1, pageSize: 25, q: "" };
    const fmtDate = (s) => s ? new Date(s).toLocaleString() : "—";

    async function j(url) {
        const r = await fetch(url, { headers: { "Accept": "application/json" } });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return await r.json();
    }

    function qs(sel) { return document.querySelector(sel); }

    function applySummary(total) {
        const start = (state.page - 1) * state.pageSize + 1;
        const end = Math.min(total, state.page * state.pageSize);
        qs("#itemsSummary").textContent = total ? `${start}–${end} of ${total}` : "No results";
        qs("#itemsPrev").disabled = state.page <= 1;
        qs("#itemsNext").disabled = end >= total;
    }

    function renderTable(items) {
        const body = qs("#itemsBody");
        if (!items || !items.length) {
            body.innerHTML = `<tr><td colspan="5" class="text-muted">No results.</td></tr>`;
            return;
        }
        const esc = (s) => String(s || "").replace(/[&<>"']/g, m => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[m]));
        body.innerHTML = items.map(r => `
        <tr>
            <td class="text-monospace">${esc(r.code)}</td>
            <td>${esc(r.title)}</td>
            <td>${esc(r.type)}</td>
            <td>${esc(r.subgroup)}</td>
            <td>${fmtDate(r.last_purchased)}</td>   <!-- NEW -->
            <td class="text-truncate" style="max-width: 480px;">${esc(r.description)}</td>
        </tr>
        `).join("");
    }

    async function load() {
        const url = `/api/items?page=${state.page}&page_size=${state.pageSize}&q=${encodeURIComponent(state.q)}`;
        const data = await j(url);
        renderTable(data.items || []);
        applySummary(data.total || 0);
    }

    function wire() {
        const search = qs("#itemsSearch");
        const pageSize = qs("#itemsPageSize");
        const prev = qs("#itemsPrev");
        const next = qs("#itemsNext");

        let timer = null;
        search.addEventListener("input", () => {
            clearTimeout(timer);
            timer = setTimeout(() => {
                state.q = search.value.trim();
                state.page = 1;
                load().catch(console.error);
            }, 250);
        });

        pageSize.addEventListener("change", () => {
            state.pageSize = parseInt(pageSize.value, 10) || 25;
            state.page = 1;
            load().catch(console.error);
        });

        prev.addEventListener("click", () => {
            if (state.page > 1) { state.page -= 1; load().catch(console.error); }
        });
        next.addEventListener("click", () => {
            state.page += 1; load().catch(console.error);
        });
    }

    async function init() {
        wire();
        await load();
    }

    return { init };
})();
