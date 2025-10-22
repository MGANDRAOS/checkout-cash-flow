// static/js/items_grid.js
const ItemsGrid = (() => {
    const state = {
        q: "",
        pageSize: 25,
        page: 1,
        total: 0,
        api: null,
        columnApi: null,
        sort: "",
        subgroup: "",
        subgroupId: null

    };


    // --- utils
    const qs = sel => document.querySelector(sel);
    const esc = s => String(s ?? "").replace(/[&<>"']/g, m => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[m]));
    const fmtDate = s => s ? new Date(s).toLocaleString() : "—";

    async function j(url) {
        const r = await fetch(url, { headers: { "Accept": "application/json" } });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
    }

    function apiUrl({ page, pageSize, q = "", sort = "", subgroup = "", subgroupId = null }) {
        const s = sort ? `&sort=${encodeURIComponent(sort)}` : "";
        const g = subgroup ? `&subgroup=${encodeURIComponent(subgroup)}` : "";
        const gid = (subgroupId !== null && subgroupId !== "" && !Number.isNaN(Number(subgroupId)))
            ? `&subgroup_id=${encodeURIComponent(subgroupId)}`
            : "";
        return `/api/items?page=${page}&page_size=${pageSize}&q=${encodeURIComponent(q)}${s}${g}${gid}`;
    }


    // --- AG Grid datasource (infinite row model)
    function makeDataSource() {
        return {
            getRows: async (params) => {
                const blockSize = state.pageSize;
                const page = Math.floor(params.startRow / blockSize) + 1;

                // ✅ Infinite Row Model: sort lives at params.sortModel (not params.request.sortModel)
                const sortModel = Array.isArray(params.sortModel) && params.sortModel.length
                    ? params.sortModel
                    : (params.request && Array.isArray(params.request.sortModel) ? params.request.sortModel : []);

                if (sortModel.length) {
                    const m = sortModel[0];
                    const field = m.colId;
                    const dir = (m.sort || "asc").toLowerCase();
                    if (["code", "title", "type", "subgroup", "last_purchased"].includes(field) &&
                        (dir === "asc" || dir === "desc")) {
                        state.sort = `${field},${dir}`;
                    } else {
                        state.sort = "";
                    }
                } else {
                    state.sort = "";
                }

                try {
                    const data = await j(apiUrl({
                        page,
                        pageSize: blockSize,
                        q: state.q,
                        sort: state.sort,
                        subgroup: state.subgroup,
                        subgroupId: state.subgroupId
                    }));
                    state.total = data.total || 0;
                    state.page = data.page || page;

                    const start = (state.page - 1) * state.pageSize + 1;
                    const end = Math.min(state.total, state.page * state.pageSize);
                    document.querySelector("#itemsSummary").textContent = state.total ? `${start}–${end} of ${state.total}` : "No results";
                    document.querySelector("#itemsPrev").disabled = state.page <= 1;
                    document.querySelector("#itemsNext").disabled = end >= state.total;

                    params.successCallback(data.items || [], state.total);
                } catch (err) {
                    console.error("[ItemsGrid] load failed:", err);
                    params.failCallback();
                }
            }
        };
    }

    async function loadSubgroups() {
        const sel = document.getElementById("itemsSubgroup");
        if (!sel) return;
        sel.innerHTML = `<option value="">All subgroups</option>`;
        try {
            const rows = await j("/api/items/subgroups");
            rows.forEach(r => {
                const opt = document.createElement("option");
                opt.value = String(r.id);
                opt.textContent = `${r.subgroup} (${r.count})`;
                sel.appendChild(opt);
            });
        } catch (e) { console.warn("[ItemsGrid] subgroup list failed", e); }
    }

    // wire change
    function wireSubgroup() {
        const sel = document.getElementById("itemsSubgroup");
        if (!sel) return;
        sel.addEventListener("change", () => {
            const v = sel.value;
            state.subgroupId = v ? parseInt(v, 10) : null;
            state.subgroup = "";
            state.page = 1;
            state.api.setGridOption('datasource', makeDataSource());
        });
    }


    // --- Actions cell renderer
    function actionsRenderer(params) {
        const row = params.data || {};
        const el = document.createElement("div");
        el.className = "d-flex align-items-center gap-1";
        el.innerHTML = `
  <button class="btn btn-sm btn-outline-primary" title="View details">
    <i class="bi bi-eye"></i>
  </button>
     `;
        const [btnView] = el.querySelectorAll("button");
        btnView.addEventListener("click", () => openDetails(row));

        return el;
    }

    function openDetails(row) {
        const dl = qs("#itemDetails");
        if (!dl) return;
        dl.innerHTML = `
      <dt class="col-sm-3">Code</dt><dd class="col-sm-9">${esc(row.code)}</dd>
      <dt class="col-sm-3">Title</dt><dd class="col-sm-9">${esc(row.title)}</dd>
      <dt class="col-sm-3">Subgroup</dt><dd class="col-sm-9">${esc(row.subgroup)}</dd>
      <dt class="col-sm-3">Last purchased</dt><dd class="col-sm-9">${fmtDate(row.last_purchased)}</dd>
    `;
        const modal = new bootstrap.Modal(document.getElementById("itemModal"));
        modal.show();
    }

    // --- Column definitions
    function colDefs() {
        return [
            {
                headerName: "Actions", field: "_actions", width: 90, pinned: "left",
                cellRenderer: actionsRenderer, sortable: false, filter: false, resizable: false
            },

            { headerName: "Code", field: "code", width: 120, cellClass: "text-monospace" },
            { headerName: "Title", field: "title", flex: 1, maxWidth: 400 },
            { headerName: "Subgroup", field: "subgroup", width: 200 },

            {
                headerName: "Last purchased", field: "last_purchased", width: 250,
                valueFormatter: p => fmtDate(p.value)
            },
        ];
    }

    function buildColumnsMenu() {
        const menu = document.querySelector("#itemsColsMenu");
        if (!menu || !state.api) return;

        const defs = state.api.getGridOption('columnDefs').filter(c => c.field !== "_actions");
        menu.innerHTML = defs.map(c => `
    <li class="form-check form-switch">
      <input class="form-check-input" type="checkbox" id="col_${c.field}" ${c.hide ? "" : "checked"} data-field="${c.field}">
      <label class="form-check-label" for="col_${c.field}">${c.headerName}</label>
    </li>
  `).join("");

        menu.querySelectorAll("input[type=checkbox]").forEach(cb => {
            cb.addEventListener("change", () => {
                const field = cb.getAttribute("data-field");
                state.columnApi.setColumnVisible(field, cb.checked);
            });
        });
    }

    function setDensity(mode) {
        const grid = document.getElementById("itemsGrid");
        if (!grid) return;
        const s = grid.style;
        if (mode === "comfy") {
            s.setProperty("--ag-font-size", "13px");
            s.setProperty("--ag-grid-size", "8px");
            s.setProperty("--ag-row-height", "40px");
        } else {
            s.setProperty("--ag-font-size", "12px");
            s.setProperty("--ag-grid-size", "6px");
            s.setProperty("--ag-row-height", "34px");
        }
    }

    function wireDensity() {
        const c = document.getElementById("densCompact");
        const f = document.getElementById("densComfy");
        if (!c || !f) return;
        const activate = (compact) => {
            c.classList.toggle("active", compact);
            f.classList.toggle("active", !compact);
            setDensity(compact ? "compact" : "comfy");
        };
        c.addEventListener("click", () => activate(true));
        f.addEventListener("click", () => activate(false));
        activate(true);
    }

    // --- Handlers for toolbar & pager
    function wireUI() {
        const q = document.getElementById("itemsQ");
        if (q) {
            let t = null;
            q.addEventListener("input", () => {
                clearTimeout(t);
                t = setTimeout(() => {
                    state.q = q.value.trim();
                    state.page = 1;
                    state.api.setGridOption('paginationPageSize', state.pageSize);
                    state.api.setGridOption('cacheBlockSize', state.pageSize);
                    state.api.setGridOption('datasource', makeDataSource());
                }, 250);
            });
        }

        const size = document.getElementById("itemsPageSize");
        if (size) {
            size.addEventListener("change", () => {
                state.pageSize = parseInt(size.value, 10) || 25;
                state.page = 1;
                state.api.setGridOption('paginationPageSize', state.pageSize);
                state.api.setGridOption('cacheBlockSize', state.pageSize);
                state.api.setGridOption('datasource', makeDataSource());
            });
        }

        const prev = document.getElementById("itemsPrev");
        if (prev) prev.addEventListener("click", () => {
            if (state.page > 1) {
                state.page -= 1;
                state.api.setGridOption('datasource', makeDataSource());
            }
        });

        const next = document.getElementById("itemsNext");
        if (next) next.addEventListener("click", () => {
            const maxPage = Math.ceil(state.total / state.pageSize) || 1;
            if (state.page < maxPage) {
                state.page += 1;
                state.api.setGridOption('datasource', makeDataSource());
            }
        });
    }


    // --- Init
    async function init() {
        if (window.location.pathname !== "/items") return;

        const gridEl = document.querySelector("#itemsGrid");
        const gridOptions = {
            theme: 'legacy',                 // ✅ explicit modern theme
            columnDefs: colDefs(),
            defaultColDef: {
                sortable: true, resizable: true,
                tooltipValueGetter: p => (p.value == null || p.value === "" ? null : String(p.value))
            },
            rowModelType: "infinite",
            cacheBlockSize: state.pageSize,
            pagination: true,
            paginationPageSize: state.pageSize,
            suppressMultiSort: false,
            animateRows: true,
            datasource: makeDataSource(),     // ✅ initial datasource (v34 style)
            onGridReady: (params) => {
                state.api = params.api;
                state.columnApi = params.columnApi;
                buildColumnsMenu();
            },
              onSortChanged: () => {
                state.page = 1;
                state.api.setGridOption('datasource', makeDataSource());
            }
        };

        // Works for modern & legacy UMD builds

        if (window.agGrid?.createGrid) {
            window.agGrid.createGrid(gridEl, gridOptions);
        } else {
            new window.agGrid.Grid(gridEl, gridOptions);
        }

        wireUI();
        await loadSubgroups();
        wireSubgroup();
        //wireDensity();

    }
    return { init };
})();

// boot
document.addEventListener("DOMContentLoaded", () => {
    try { ItemsGrid.init(); } catch (e) { console.error(e); }
});
