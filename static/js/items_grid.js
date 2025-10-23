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
        subgroupId: null,
        inactiveDays: null,
        neverSold: false
    };


    // --- utils
    const qs = sel => document.querySelector(sel);
    const esc = s => String(s ?? "").replace(/[&<>"']/g, m => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[m]));
    const fmtDate = s => s ? new Date(s).toLocaleString() : "—";

    const fmtLBP = (n) => {
        if (n == null) return "—";
        try { return new Intl.NumberFormat(undefined, { maximumFractionDigits: 0 }).format(n) + " LBP"; }
        catch { return String(n) + " LBP"; }
    };

    async function j(url) {
        const r = await fetch(url, { headers: { "Accept": "application/json" } });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
    }

    function apiUrl(params = {}) {
        const {
            page,
            pageSize,
            q = "",
            sort = "",
            subgroup = "",
            subgroupId = null,
            inactiveDays: _inactiveDays = null,  // local alias prevents ReferenceError
            neverSold: _neverSold = false        // local alias prevents ReferenceError
        } = params;

        const s = sort ? `&sort=${encodeURIComponent(sort)}` : "";
        const g = subgroup ? `&subgroup=${encodeURIComponent(subgroup)}` : "";
        const gid = (subgroupId !== null && subgroupId !== "" && !Number.isNaN(Number(subgroupId)))
            ? `&subgroup_id=${encodeURIComponent(subgroupId)}` : "";
        const inact = (_inactiveDays !== null && _inactiveDays !== "" && !Number.isNaN(Number(_inactiveDays)))
            ? `&inactive_days=${encodeURIComponent(_inactiveDays)}` : "";
        const ns = (_neverSold ? `&never_sold=1` : "");

        return `/api/items?page=${page}&page_size=${pageSize}&q=${encodeURIComponent(q)}${s}${g}${gid}${inact}${ns}`;
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
                        subgroupId: state.subgroupId,
                        inactiveDays: state.inactiveDays,
                        neverSold: state.neverSold
                    }));
                    state.total = data.total || 0;
                    state.page = data.page || page;



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

    async function openDetails(row) {
        const code = row?.code;
        if (!code) return;

        const drawerEl = document.getElementById("itemDrawer");
        const bodyEl = document.getElementById("itemDrawerBody");
        const titleEl = document.getElementById("itemDrawerTitle");
        if (!drawerEl || !bodyEl || !titleEl) return;

        // Loading state
        titleEl.textContent = "Item details";
        bodyEl.innerHTML = `<div class="text-center text-muted small py-4">Fetching 30-day profile…</div>`;
        const drawer = new bootstrap.Offcanvas(drawerEl);
        drawer.show();

        try {
            const resp = await fetch(`/api/items/${encodeURIComponent(code)}/details?days=30`, {
                headers: { "Accept": "application/json" }
            });
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            const data = await resp.json();

            const it = data.item || {};
            const s = data.summary || {};
            const series = Array.isArray(data.series) ? data.series : [];
            const recent = Array.isArray(data.recent) ? data.recent : [];

            // Build sparkline points from qty (you can switch to amount by changing map)
            const points = series.map(d => [d.date, Number(d.qty || 0)]);
            const spark = renderSparkline(points);

            // Title & header chips
            titleEl.textContent = it.title || "(no title)";

            bodyEl.innerHTML = `
      <div class="d-flex justify-content-between align-items-start mb-2">
        <div class="small">
          <div class="text-muted">Code</div>
          <div class="text-monospace">${esc(it.code || "")}</div>
        </div>
        <div class="text-end">
          <span class="pill">${esc(it.subgroup || "Unknown")}</span>
          <div class="small text-muted mt-1">Last purchased: ${fmtDate(it.last_purchased)}</div>
        </div>
      </div>

      <div class="row g-2 mb-3">
        <div class="col-6 col-md-3">
          <div class="kpi-card">
            <div class="kpi-label">Receipts (30d)</div>
            <div class="kpi-value">${s.receipts ?? 0}</div>
          </div>
        </div>
        <div class="col-6 col-md-3">
          <div class="kpi-card">
            <div class="kpi-label">Units (30d)</div>
            <div class="kpi-value">${s.units ?? 0}</div>
          </div>
        </div>
        <div class="col-6 col-md-3">
          <div class="kpi-card">
            <div class="kpi-label">Gross (30d)</div>
            <div class="kpi-value">${fmtLBP(s.amount)}</div>
          </div>
        </div>
        <div class="col-6 col-md-3">
          <div class="kpi-card">
            <div class="kpi-label">Unit price min/avg/max</div>
            <div class="kpi-value">
              ${(s.price_min != null ? fmtLBP(s.price_min) : "—")} /
              ${(s.price_avg != null ? fmtLBP(s.price_avg) : "—")} /
              ${(s.price_max != null ? fmtLBP(s.price_max) : "—")}
            </div>
          </div>
        </div>
      </div>

      <div class="mb-3">
        <div class="d-flex justify-content-between align-items-center">
          <div class="section-title">Trend (qty per business day, 30d)</div>
          <div class="btn-group btn-group-sm" role="group" aria-label="Metric">
            <button type="button" class="btn btn-outline-secondary active" id="sparkQtyBtn">Qty</button>
            <button type="button" class="btn btn-outline-secondary" id="sparkAmtBtn">Amount</button>
          </div>
        </div>
        <div id="itemSparkline">${spark}</div>
      </div>

      <div>
        <div class="section-title">Recent receipts</div>
        ${recent.length === 0
                    ? `<div class="small text-muted">No receipts.</div>`
                    : `<div class="table-responsive">
                 <table class="table table-sm table-striped align-middle mb-0">
                   <thead class="table-light">
                     <tr>
                       <th style="width: 20%;">Receipt</th>
                       <th style="width: 35%;">Date/Time</th>
                       <th style="width: 15%;">Qty</th>
                       <th style="width: 15%;">Unit price</th>
                       <th style="width: 15%;">Total</th>
                     </tr>
                   </thead>
                   <tbody>
                     ${recent.map(r => `
                       <tr>
                         <td class="text-monospace">${esc(r.rcpt_id)}</td>
                         <td>${fmtDate(r.rcpt_date)}</td>
                         <td>${esc(r.qty)}</td>
                         <td>${r.unit_price != null ? fmtLBP(r.unit_price) : "—"}</td>
                         <td>${fmtLBP(r.line_total)}</td>
                       </tr>`).join("")}
                   </tbody>
                 </table>
               </div>`
                }
      </div>
    `;

            // Wire metric toggle without hardcoding series choices
            const elSpark = document.getElementById("itemSparkline");
            const qtyBtn = document.getElementById("sparkQtyBtn");
            const amtBtn = document.getElementById("sparkAmtBtn");

            const render = (metric) => {
                const pts = series.map(d => [d.date, Number(metric === "amount" ? (d.amount || 0) : (d.qty || 0))]);
                elSpark.innerHTML = renderSparkline(pts);
                qtyBtn?.classList.toggle("active", metric === "qty");
                amtBtn?.classList.toggle("active", metric === "amount");
            };
            qtyBtn?.addEventListener("click", () => render("qty"));
            amtBtn?.addEventListener("click", () => render("amount"));
            // initial render already done as qty
        } catch (err) {
            console.error("[ItemsGrid] details load failed:", err);
            bodyEl.innerHTML = `<div class="text-danger small">Failed to load item details.</div>`;
        }
    }

    function renderSparkline(points, opts = {}) {
        const height = opts.height ?? 72;       // controlled by CSS but we compute viewBox
        const width = opts.width ?? 300;

        // Map series to [0..1] then scale
        const vals = (points || []).map(p => Number(p[1]) || 0);
        if (!vals.length || vals.every(v => v === 0)) {
            return `<svg class="sparkline" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none">
              <text x="50%" y="50%" dominant-baseline="middle" text-anchor="middle"
                    fill="currentColor" font-size="10">No recent trend</text>
            </svg>`;
        }
        const min = Math.min(...vals), max = Math.max(...vals);
        const pad = 4; // visual padding in viewBox coords
        const h = height - pad * 2, w = width - pad * 2;
        const n = vals.length;
        const xs = vals.map((_, i) => (n === 1 ? w / 2 : (i / (n - 1)) * w) + pad);
        const ys = vals.map(v => (max === min ? h / 2 : (1 - (v - min) / (max - min)) * h) + pad);

        const line = xs.map((x, i) => `${i === 0 ? 'M' : 'L'}${x.toFixed(2)},${ys[i].toFixed(2)}`).join(' ');
        const area = `${line} L ${xs[xs.length - 1].toFixed(2)},${height - pad} L ${xs[0].toFixed(2)},${height - pad} Z`;

        return `<svg class="sparkline" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none">
            <path d="${area}"></path>
          </svg>`;
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

        const inact = document.getElementById("itemsInactive");
        if (inact) {
            inact.addEventListener("change", () => {
                const v = inact.value;
                state.neverSold = (v === "never");
                state.inactiveDays = (!state.neverSold && v) ? parseInt(v, 10) : null;
                state.page = 1;
                state.api.setGridOption('datasource', makeDataSource());
            })
        }
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
