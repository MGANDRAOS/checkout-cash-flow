/* ══════════════════════════════════════════════════════════════
   STOCK RADAR — inventory command center (vanilla, page-scoped)

   Loads /api/stock/list once, derives all widgets client-side, and
   lazy-loads /api/stock/item/<id> only when a row is expanded so the
   page stays snappy. Auto-refreshes live numbers while the operator
   is parked (never mid-interaction).
   ══════════════════════════════════════════════════════════════ */
(() => {
  "use strict";
  const root = document.getElementById("stockRadar");
  if (!root) return;

  const CURRENCY = root.dataset.currency || "";
  const AUTO_MS = 45000; // matches the POS units-sold cache TTL

  // ── element refs ───────────────────────────────────────────
  const el = {
    pos: id("srPos"), updated: id("srUpdated"), refresh: id("srRefresh"),
    addToggle: id("srAddToggle"), add: id("srAdd"), addSearch: id("srAddSearch"),
    addSubgroup: id("srAddSubgroup"), addSearchBtn: id("srAddSearchBtn"),
    addClose: id("srAddClose"), addResults: id("srAddResults"),
    kpis: id("srKpis"), radar: id("srRadar"), spot: id("srSpot"),
    filters: id("srFilters"), search: id("srSearch"), sort: id("srSort"),
    list: id("srList"),
  };
  function id(x) { return document.getElementById(x); }

  // ── state ──────────────────────────────────────────────────
  const state = {
    items: [], posLive: true, loadedAt: null,
    filter: "all", q: "", sort: "urgency",
  };
  const openIds = new Set();      // expanded item ids (numbers)
  const detailCache = {};         // id -> detail payload
  let subgroupsLoaded = false;
  let searchState = null;

  // ── status vocabulary ──────────────────────────────────────
  const STATUS = {
    out:     { label: "Out",     icon: "bi-exclamation-octagon-fill" },
    low:     { label: "Low",     icon: "bi-exclamation-triangle-fill" },
    ok:      { label: "OK",      icon: "bi-check-circle-fill" },
    unknown: { label: "Unknown", icon: "bi-question-circle-fill" },
  };
  const RANK = { out: 0, low: 1, unknown: 2, ok: 3 };

  // ── formatting ─────────────────────────────────────────────
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  function fmt(n) {
    if (n === null || n === undefined) return "—";
    const r = Math.round(n * 100) / 100;
    return r.toLocaleString(undefined, { maximumFractionDigits: 2 });
  }
  function money(cents) {
    if (cents === null || cents === undefined) return "—";
    return Math.round(cents / 100).toLocaleString() + " " + CURRENCY;
  }
  function coverTxt(r) {
    if (!r.has_baseline) return "—";
    if (r.days_cover !== null && r.days_cover !== undefined) return fmt(r.days_cover);
    if (r.live !== null && r.live > 0) return "∞";
    return "—";
  }
  function coverKey(r) {
    if (!r.has_baseline) return 9e12;
    if (r.days_cover !== null && r.days_cover !== undefined) return r.days_cover;
    return 9e9; // stock on hand, no observed sales -> very safe
  }

  // ── fetch helpers ──────────────────────────────────────────
  async function jget(url) {
    const r = await fetch(url);
    if (!r.ok) throw new Error("HTTP " + r.status);
    return r.json();
  }
  async function jpost(url, body) {
    const r = await fetch(url, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!r.ok && r.status !== 400 && r.status !== 404) throw new Error("HTTP " + r.status);
    return r.json();
  }

  // ── toast ──────────────────────────────────────────────────
  let toastEl, toastTimer;
  function toast(msg, kind) {
    if (!toastEl) {
      toastEl = document.createElement("div");
      toastEl.className = "sr-toast";
      document.body.appendChild(toastEl);
    }
    const icon = kind === "err" ? "bi-x-circle-fill" : "bi-check-circle-fill";
    toastEl.className = "sr-toast sr-toast--" + (kind === "err" ? "err" : "ok");
    toastEl.innerHTML = `<i class="bi ${icon}"></i> ${esc(msg)}`;
    requestAnimationFrame(() => toastEl.classList.add("is-show"));
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toastEl.classList.remove("is-show"), 2400);
  }

  // ══════════════════════════════════════════════════════════
  //  LOAD + RENDER
  // ══════════════════════════════════════════════════════════
  async function loadList(opts = {}) {
    if (opts.force) { for (const k in detailCache) delete detailCache[k]; }
    if (opts.force) el.refresh.classList.add("is-busy");
    let d;
    try { d = await jget("/api/stock/list"); }
    catch (e) {
      el.refresh.classList.remove("is-busy");
      if (!opts.silent) listMsg("bi-wifi-off", "Couldn’t load stock", "Refresh to retry.");
      return;
    }
    state.items = d.items || [];
    state.posLive = !d.live_unavailable;
    state.loadedAt = new Date();
    // drop expanded ids that no longer exist
    for (const oid of [...openIds]) if (!state.items.some((i) => i.id === oid)) openIds.delete(oid);
    renderAll();
    el.refresh.classList.remove("is-busy");
  }

  function renderAll() {
    renderPos();
    renderKpis();
    renderRadar();
    renderSpotlight();
    renderChips();
    renderList();
  }

  function renderPos() {
    const live = state.posLive;
    el.pos.className = "sr-pos " + (live ? "sr-pos--live" : "sr-pos--stale");
    el.pos.querySelector(".sr-pos__txt").textContent = live ? "Live feed" : "Baseline only";
    if (state.loadedAt) {
      const t = state.loadedAt;
      const hh = String(t.getHours()).padStart(2, "0");
      const mm = String(t.getMinutes()).padStart(2, "0");
      const ss = String(t.getSeconds()).padStart(2, "0");
      el.updated.textContent = `Updated ${hh}:${mm}:${ss}`;
    }
  }

  function counts() {
    const c = { all: state.items.length, out: 0, low: 0, ok: 0, unknown: 0,
                reorderItems: 0, reorderUnits: 0, value: 0, hasValue: false };
    for (const r of state.items) {
      c[r.status] = (c[r.status] || 0) + 1;
      if (r.needs_reorder) { c.reorderItems++; c.reorderUnits += r.reorder_qty || 0; }
      if (r.value_cents !== null && r.value_cents !== undefined) { c.value += r.value_cents; c.hasValue = true; }
    }
    return c;
  }

  // ── KPI tiles ──────────────────────────────────────────────
  function renderKpis() {
    const c = counts();
    const pctOk = c.all ? Math.round((c.ok / c.all) * 100) : 0;
    const tiles = [
      { act: "all", accent: "var(--azure)", icon: "bi-boxes", label: "Tracked",
        val: c.all, sub: `${c.ok} healthy` },
      { act: "out", accent: "var(--sr-out)", icon: "bi-exclamation-octagon-fill", label: "Out of stock",
        val: c.out, sub: c.out ? "needs restock now" : "all in stock" },
      { act: "low", accent: "var(--sr-low)", icon: "bi-exclamation-triangle-fill", label: "Running low",
        val: c.low, sub: `${c.reorderItems} to reorder` },
      { act: "ok", accent: "var(--sr-ok)", icon: "bi-check-circle-fill", label: "Healthy",
        val: c.ok, sub: `${pctOk}% of catalog` },
      { act: "reorder", accent: "var(--gold)", icon: "bi-cart-plus-fill", label: "Reorder units",
        val: c.reorderUnits, sub: `across ${c.reorderItems} item(s)` },
      { accent: "var(--sr-ok)", icon: "bi-cash-stack", label: "Stock value", money: true,
        val: c.hasValue ? money(c.value) : "—", sub: "at last cost" },
    ];
    el.kpis.innerHTML = tiles.map((t) => {
      const active = t.act && (state.filter === t.act) ? " is-active" : "";
      const valHtml = t.money ? esc(t.val) : `${fmt(t.val)}`;
      return `<div class="sr-kpi sr-kpi--n6${active}" style="--accent:${t.accent}"${t.act ? ` data-act="${t.act}"` : ""}>
        <div class="sr-kpi__top">
          <span class="sr-kpi__label">${t.label}</span>
          <span class="sr-kpi__icon"><i class="bi ${t.icon}"></i></span>
        </div>
        <div class="sr-kpi__val${t.money ? " num" : ""}">${valHtml}</div>
        <div class="sr-kpi__sub">${esc(t.sub)}</div>
      </div>`;
    }).join("");
  }

  // ── radar donut ────────────────────────────────────────────
  function renderRadar() {
    const c = counts();
    const segs = [
      { key: "out", val: c.out, color: "var(--sr-out)" },
      { key: "low", val: c.low, color: "var(--sr-low)" },
      { key: "ok", val: c.ok, color: "var(--sr-ok)" },
      { key: "unknown", val: c.unknown, color: "var(--sr-unk)" },
    ];
    const total = c.all || 0;
    let acc = 0; const stops = [];
    if (total) {
      for (const s of segs) {
        if (s.val <= 0) continue;
        const a0 = (acc / total) * 360; acc += s.val; const a1 = (acc / total) * 360;
        stops.push(`${s.color} ${a0}deg ${a1}deg`);
      }
    }
    const grad = stops.length ? `conic-gradient(${stops.join(",")})` : "conic-gradient(var(--sr-unk-dim) 0 360deg)";
    const health = total ? Math.round((c.ok / total) * 100) : 0;
    const legend = segs.map((s) => {
      const pct = total ? Math.round((s.val / total) * 100) : 0;
      return `<div class="sr-leg" data-f="${s.key}">
        <span class="sr-leg__dot" style="background:${s.color}"></span>
        <span class="sr-leg__name">${STATUS[s.key].label}</span>
        <span class="sr-leg__val num">${s.val}</span>
        <span class="sr-leg__pct">${pct}%</span>
      </div>`;
    }).join("");
    el.radar.innerHTML = `
      <div class="sr-panel__h"><i class="bi bi-pie-chart-fill"></i><h3>Stock health</h3>
        <span class="sr-count">${total} tracked</span></div>
      <div class="sr-radar__body">
        <div class="sr-donut" style="background:${grad}">
          <div class="sr-donut__c"><div class="sr-donut__pct num">${health}%</div><div class="sr-donut__lbl">healthy</div></div>
        </div>
        <div class="sr-legend">${legend}</div>
      </div>`;
  }

  // ── reorder spotlight ──────────────────────────────────────
  function renderSpotlight() {
    const urgent = state.items
      .filter((r) => r.status === "out" || r.status === "low" || r.needs_reorder)
      .sort((a, b) => (RANK[a.status] - RANK[b.status]) || (coverKey(a) - coverKey(b)) || ((b.reorder_qty || 0) - (a.reorder_qty || 0)))
      .slice(0, 8);
    const head = `<div class="sr-panel__h"><i class="bi bi-broadcast-pin"></i><h3>Needs attention</h3>
      <span class="sr-count">${urgent.length ? urgent.length + " flagged" : ""}</span></div>`;
    if (!urgent.length) {
      el.spot.innerHTML = head + `<div class="sr-empty">
        <i class="bi bi-shield-check"></i><strong>All stocked up</strong>
        <span>Nothing is out, low, or due for reorder.</span></div>`;
      return;
    }
    const cards = urgent.map((r) => {
      const isOut = r.status === "out";
      const cover = isOut ? "out of stock"
        : (r.days_cover !== null && r.days_cover !== undefined) ? `~${fmt(r.days_cover)}d of cover`
        : "below alert level";
      const chip = r.needs_reorder ? `order ${fmt(r.reorder_qty)}` : (isOut ? "out" : "low");
      return `<div class="sr-urg" data-status="${r.status}">
        <div class="sr-urg__name">${esc(r.title || r.itm_code)}</div>
        <div class="sr-urg__row">
          <span class="sr-urg__live num">${r.has_baseline ? fmt(r.live) : "—"}</span>
          <span class="sr-urg__cover">${esc(cover)}</span>
        </div>
        <div class="sr-urg__foot">
          <span class="sr-chip">${esc(chip)}</span>
          <button class="sr-urg__count" data-count="${r.id}" title="Set count"><i class="bi bi-pencil"></i></button>
        </div>
      </div>`;
    }).join("");
    el.spot.innerHTML = head + `<div class="sr-spot__grid">${cards}</div>`;
  }

  // ── filter chips ───────────────────────────────────────────
  function renderChips() {
    const c = counts();
    const chips = [
      { f: "all", label: "All", n: c.all },
      { f: "out", label: "Out", n: c.out },
      { f: "low", label: "Low", n: c.low },
      { f: "ok", label: "OK", n: c.ok },
    ];
    if (c.unknown) chips.push({ f: "unknown", label: "Unknown", n: c.unknown });
    if (c.reorderItems) chips.push({ f: "reorder", label: "Reorder", n: c.reorderItems });
    el.filters.innerHTML = chips.map((ch) =>
      `<button class="sr-fchip${state.filter === ch.f ? " is-active" : ""}" data-f="${ch.f}">
         ${ch.label} <span class="sr-fchip__n">${ch.n}</span></button>`).join("");
  }

  // ── item list ──────────────────────────────────────────────
  function viewItems() {
    let arr = state.items;
    const f = state.filter;
    if (f === "reorder") arr = arr.filter((r) => r.needs_reorder);
    else if (f !== "all") arr = arr.filter((r) => r.status === f);
    const q = state.q.trim().toLowerCase();
    if (q) arr = arr.filter((r) =>
      (r.title || "").toLowerCase().includes(q) ||
      (r.itm_code || "").toLowerCase().includes(q) ||
      (r.subgroup || "").toLowerCase().includes(q));
    return sortItems(arr);
  }

  function sortItems(arr) {
    const a = arr.slice();
    const byName = (x, y) => (x.title || x.itm_code || "").toLowerCase()
      .localeCompare((y.title || y.itm_code || "").toLowerCase());
    const numv = (v) => (v === null || v === undefined ? Infinity : v);
    switch (state.sort) {
      case "name": return a.sort(byName);
      case "live": return a.sort((x, y) => numv(x.live) - numv(y.live) || byName(x, y));
      case "velocity": return a.sort((x, y) => (y.velocity || 0) - (x.velocity || 0) || byName(x, y));
      case "value": return a.sort((x, y) => (y.value_cents || 0) - (x.value_cents || 0) || byName(x, y));
      case "cover": return a.sort((x, y) => coverKey(x) - coverKey(y) || byName(x, y));
      default: return a.sort((x, y) =>
        (RANK[x.status] - RANK[y.status]) || (coverKey(x) - coverKey(y)) ||
        ((y.reorder_qty || 0) - (x.reorder_qty || 0)) || byName(x, y));
    }
  }

  function renderList() {
    const view = viewItems();
    if (!state.items.length) {
      listMsg("bi-inbox", "No tracked items yet", "Use “Track item” to add your first item.");
      return;
    }
    if (!view.length) {
      listMsg("bi-search", "No matches", "Try a different filter or search term.");
      return;
    }
    el.list.innerHTML = view.map(rowHtml).join("");
    // restore any expanded rows present in this view
    for (const oid of openIds) {
      const row = el.list.querySelector(`.sr-item[data-id="${oid}"]`);
      if (row) openItem(oid, true);
    }
  }

  function rowHtml(r) {
    const live = r.has_baseline ? fmt(r.live) : "—";
    const st = STATUS[r.status] || STATUS.unknown;
    return `<article class="sr-item" data-id="${r.id}" data-status="${r.status}">
      <button class="sr-item__head" type="button">
        <span class="sr-item__rail"></span>
        <span class="sr-item__id">
          <span class="sr-item__name">${esc(r.title || r.itm_code)}</span>
          <span class="sr-item__meta">${esc(r.itm_code)}${r.subgroup ? " · " + esc(r.subgroup) : ""}</span>
        </span>
        <span class="sr-item__metrics">
          <span class="sr-m sr-m--live"><b class="num">${live}</b><i>on hand</i></span>
          <span class="sr-m sr-m--sec"><b class="num">${r.has_baseline ? fmt(r.velocity) : "—"}</b><i>/day</i></span>
          <span class="sr-m sr-m--sec sr-m--cover"><b class="num">${coverTxt(r)}</b><i>days left</i></span>
        </span>
        <span class="sr-item__status">
          <span class="sr-pill"><span class="sr-pill__dot"></span>${st.label}</span>
        </span>
        <span class="sr-item__chev"><i class="bi bi-chevron-down"></i></span>
      </button>
      <div class="sr-item__detail" hidden></div>
    </article>`;
  }

  function listMsg(icon, title, sub) {
    el.list.innerHTML = `<div class="sr-list__msg"><i class="bi ${icon}"></i>
      <strong>${esc(title)}</strong>${esc(sub || "")}</div>`;
  }

  // ══════════════════════════════════════════════════════════
  //  ITEM DETAIL (lazy)
  // ══════════════════════════════════════════════════════════
  function toggleItem(itemId) {
    if (openIds.has(itemId)) closeItem(itemId);
    else openItem(itemId);
  }

  async function openItem(itemId, silentReopen) {
    openIds.add(itemId);
    const row = el.list.querySelector(`.sr-item[data-id="${itemId}"]`);
    if (!row) return;
    row.classList.add("is-open");
    const d = row.querySelector(".sr-item__detail");
    d.hidden = false;
    if (detailCache[itemId]) { d.innerHTML = buildDetail(detailCache[itemId]); bindDetail(row, itemId); return; }
    if (!silentReopen) d.innerHTML = `<div class="sr-detail__loading"><i class="bi bi-arrow-repeat"></i> Loading detail…</div>`;
    try {
      const det = await jget(`/api/stock/item/${itemId}`);
      if (!det.ok) throw new Error("not ok");
      detailCache[itemId] = det;
      if (openIds.has(itemId) && row.isConnected) { d.innerHTML = buildDetail(det); bindDetail(row, itemId); }
    } catch (e) {
      d.innerHTML = `<div class="sr-detail__loading">Couldn’t load detail. <a href="#" class="srRetry">Retry</a></div>`;
      const rt = d.querySelector(".srRetry");
      if (rt) rt.addEventListener("click", (ev) => { ev.preventDefault(); openItem(itemId); });
    }
  }

  function closeItem(itemId) {
    openIds.delete(itemId);
    const row = el.list.querySelector(`.sr-item[data-id="${itemId}"]`);
    if (!row) return;
    row.classList.remove("is-open");
    const d = row.querySelector(".sr-item__detail");
    d.hidden = true; d.innerHTML = "";
  }

  function buildDetail(d) {
    const a = d.analytics || {};
    const stat = (l, v, s) =>
      `<div class="sr-stat"><div class="sr-stat__l">${l}</div><div class="sr-stat__v">${v}</div>${s ? `<div class="sr-stat__s">${esc(s)}</div>` : ""}</div>`;
    const cover = (!d.has_baseline) ? "—"
      : (a.days_cover !== null && a.days_cover !== undefined) ? fmt(a.days_cover) + " d"
      : (d.live > 0 ? "∞" : "—");
    const stats = [
      stat("Baseline", d.has_baseline ? `<span class="num">${fmt(d.q0)}</span>` : "—", d.has_baseline ? "on " + d.d0 : ""),
      stat("Sold since", `<span class="num">${fmt(d.sold)}</span>`, (d.has_baseline && a.days_since_baseline != null) ? `over ${a.days_since_baseline} d` : ""),
      stat("Received since", `<span class="num">${fmt(d.receives_since)}</span>`, `${a.receive_count || 0} receipt(s)`),
      stat("Velocity", d.has_baseline ? `<span class="num">${fmt(a.velocity)}</span><small> /day</small>` : "—", "avg sales/day"),
      stat("Days of cover", cover, "at current pace"),
      stat("Suggested reorder", `<span class="num">${fmt(a.reorder_qty)}</span>`, a.needs_reorder ? "restock now" : "healthy"),
      stat("Cost basis", a.last_cost_cents != null ? `<span class="num">${money(a.last_cost_cents)}</span>` : "—", "per unit"),
      stat("Stock value", a.value_cents != null ? `<span class="num">${money(a.value_cents)}</span>` : "—", "at cost basis"),
      stat("Last sold", d.last_sold ? `<span style="font-size:.8rem" class="num">${esc(d.last_sold)}</span>` : "—", "live POS"),
      stat("Alert level", `≤ <span class="num">${fmt(d.item.threshold)}</span>`, "low threshold"),
    ].join("");

    const math = d.has_baseline ? `<div class="sr-math">
        <span class="sr-math__t">Live math</span>
        <span class="sr-mterm"><b class="num">${fmt(d.q0)}</b><i>baseline</i></span>
        <span class="sr-mop">+</span>
        <span class="sr-mterm sr-mterm--recv"><b class="num">${fmt(d.receives_since)}</b><i>received</i></span>
        <span class="sr-mop">−</span>
        <span class="sr-mterm sr-mterm--sold"><b class="num">${fmt(d.sold)}</b><i>sold</i></span>
        <span class="sr-mop">=</span>
        <span class="sr-mterm sr-mterm--live"><b class="num">${fmt(d.live)}</b><i>on hand</i></span>
      </div>` : "";

    const recvRows = (d.receives || []).length
      ? d.receives.map((l) => `<tr>
          <td>${esc(l.date)}</td>
          <td class="r num">+${fmt(l.qty)}</td>
          <td class="r num">${l.unit_cost_cents != null ? money(l.unit_cost_cents) : "—"}</td>
          <td class="r num">${l.line_total_cents != null ? money(l.line_total_cents) : "—"}</td>
          <td><span class="sr-src sr-src--${l.source === "invoice" ? "invoice" : "manual"}">${esc(l.source)}</span></td>
        </tr>`).join("")
      : `<tr><td colspan="5" class="sr-tbl__empty">No purchases recorded yet.</td></tr>`;

    const countRows = (d.counts || []).length
      ? d.counts.map((l) => `<tr>
          <td>${esc(l.counted_at || l.date)}</td>
          <td class="r num">${fmt(l.qty)}</td>
          <td><span class="sr-src sr-src--${l.source === "invoice" ? "invoice" : "manual"}">${esc(l.source)}</span></td>
        </tr>`).join("")
      : `<tr><td colspan="3" class="sr-tbl__empty">No counts yet.</td></tr>`;

    const liveDefault = (d.has_baseline && d.live != null) ? Math.round(d.live) : "";
    const recvVal = d.totals.received_value_cents ? money(d.totals.received_value_cents) : "—";

    return `<div class="sr-detail">
      <div class="sr-detail__grid">${stats}</div>
      ${math}
      <div class="sr-detail__cols">
        <div class="sr-hist">
          <div class="sr-hist__h"><i class="bi bi-truck"></i> Purchase history
            <span class="sr-tot">${fmt(d.totals.received_units)} units · ${recvVal}</span></div>
          <table class="sr-tbl"><thead><tr><th>Date</th><th class="r">Qty</th><th class="r">Unit cost</th><th class="r">Total</th><th>Src</th></tr></thead>
            <tbody>${recvRows}</tbody></table>
        </div>
        <div class="sr-hist">
          <div class="sr-hist__h"><i class="bi bi-clipboard-check"></i> Count history
            <span class="sr-tot">${(d.counts || []).length} count(s)</span></div>
          <table class="sr-tbl"><thead><tr><th>When</th><th class="r">Counted</th><th>Src</th></tr></thead>
            <tbody>${countRows}</tbody></table>
        </div>
      </div>
      <div class="sr-actions">
        <div class="sr-field">
          <label>Set new count</label>
          <div class="sr-field__in">
            <input class="srCountIn" type="number" min="0" step="1" placeholder="${liveDefault}">
            <button class="sr-btn sr-btn--save sr-btn--mini srSetCount"><i class="bi bi-check-lg"></i> Save</button>
          </div>
        </div>
        <div class="sr-field">
          <label>Alert ≤</label>
          <div class="sr-field__in">
            <input class="srThr" type="number" min="0" step="1" value="${d.item.threshold}">
          </div>
        </div>
        <div class="sr-actions__sp"></div>
        <button class="sr-btn sr-btn--danger sr-btn--mini srRemove"><i class="bi bi-trash3"></i> Stop tracking</button>
      </div>
    </div>`;
  }

  function bindDetail(row, itemId) {
    const countIn = row.querySelector(".srCountIn");
    const saveBtn = row.querySelector(".srSetCount");
    const thr = row.querySelector(".srThr");
    const rmBtn = row.querySelector(".srRemove");

    async function saveCount() {
      const qty = parseFloat(countIn.value);
      if (isNaN(qty) || qty < 0) { toast("Enter a valid quantity", "err"); countIn.focus(); return; }
      saveBtn.disabled = true;
      const res = await jpost("/api/stock/set-count", { stock_item_id: itemId, qty });
      if (res.ok) { delete detailCache[itemId]; toast("Count updated", "ok"); await loadList(); }
      else { toast(res.error || "Failed", "err"); saveBtn.disabled = false; }
    }
    saveBtn.addEventListener("click", saveCount);
    countIn.addEventListener("keydown", (e) => { if (e.key === "Enter") saveCount(); });

    thr.addEventListener("change", async () => {
      const t = parseInt(thr.value, 10);
      if (isNaN(t) || t < 0) { toast("Threshold must be ≥ 0", "err"); return; }
      const res = await jpost("/api/stock/set-threshold", { stock_item_id: itemId, threshold: t });
      if (res.ok) { delete detailCache[itemId]; toast("Threshold saved", "ok"); await loadList(); }
      else toast(res.error || "Failed", "err");
    });

    rmBtn.addEventListener("click", async () => {
      if (!confirm("Stop tracking this item?")) return;
      const res = await jpost("/api/stock/remove", { stock_item_id: itemId });
      if (res.ok) { openIds.delete(itemId); delete detailCache[itemId]; toast("Removed from tracking", "ok"); await loadList(); }
      else toast(res.error || "Failed", "err");
    });
  }

  async function quickCount(itemId) {
    let row = el.list.querySelector(`.sr-item[data-id="${itemId}"]`);
    if (!row) { setFilter("all"); row = el.list.querySelector(`.sr-item[data-id="${itemId}"]`); }
    if (!row) return;
    if (!openIds.has(itemId)) await openItem(itemId);
    row.scrollIntoView({ behavior: "smooth", block: "center" });
    setTimeout(() => { const i = row.querySelector(".srCountIn"); if (i) i.focus(); }, 280);
  }

  // ══════════════════════════════════════════════════════════
  //  FILTER / SORT / SEARCH
  // ══════════════════════════════════════════════════════════
  function setFilter(f) {
    state.filter = f;
    renderChips(); renderKpis(); renderList();
  }

  // ══════════════════════════════════════════════════════════
  //  TRACK-ITEM PANEL
  // ══════════════════════════════════════════════════════════
  function toggleAdd(force) {
    const show = force !== undefined ? force : el.add.hidden;
    el.add.hidden = !show;
    el.addToggle.classList.toggle("is-active", show);
    if (show) {
      if (!subgroupsLoaded) loadSubgroups();
      setTimeout(() => el.addSearch.focus(), 30);
    }
  }

  async function loadSubgroups() {
    subgroupsLoaded = true;
    try {
      const d = await jget("/api/stock/subgroups");
      (d.subgroups || []).forEach((s) => {
        const o = document.createElement("option");
        o.value = s.id; o.textContent = `${s.subgroup} (${s.count})`;
        el.addSubgroup.appendChild(o);
      });
    } catch (e) { /* non-fatal */ }
  }

  async function doAddSearch() {
    const q = el.addSearch.value.trim();
    const sg = el.addSubgroup.value;
    searchState = { q, sg, page: 1, loaded: 0, total: 0 };
    el.addResults.innerHTML = `<div class="sr-hint"><i class="bi bi-hourglass-split"></i> Searching catalog…</div>`;
    try {
      const d = await jget(`/api/stock/search?q=${encodeURIComponent(q)}&subgroup=${encodeURIComponent(sg)}&page=1`);
      const items = d.items || [];
      searchState.loaded = items.length;
      searchState.total = d.total || items.length;
      if (!items.length) { el.addResults.innerHTML = `<div class="sr-hint">No items found.</div>`; return; }
      el.addResults.innerHTML = items.map(resultHtml).join("") + loadMoreHtml();
    } catch (e) { el.addResults.innerHTML = `<div class="sr-hint">Search failed. Try again.</div>`; }
  }

  function loadMoreHtml() {
    const rem = searchState.total - searchState.loaded;
    return rem > 0
      ? `<div class="sr-loadmore"><button class="sr-btn sr-btn--ghost sr-btn--mini" id="srLoadMore">Load more (${rem} more)</button></div>`
      : `<div class="sr-hint">${searchState.total} item(s)</div>`;
  }

  function resultHtml(it) {
    const tracked = it.tracked;
    const meta = [esc(it.code), esc(it.subgroup || ""), it.last_purchased ? "Last sold: " + esc(it.last_purchased) : ""]
      .filter(Boolean).join(" · ");
    return `<div class="sr-result">
      <div class="sr-result__id">
        <div class="sr-result__name">
          ${tracked ? '<span class="sr-tracked-tag"><i class="bi bi-check-circle-fill"></i>Tracked</span>' : ""}
          ${esc(it.title || it.code)}
        </div>
        <div class="sr-result__meta">${meta}</div>
      </div>
      ${tracked ? "" : `<input class="qtyIn" type="number" min="0" step="1" placeholder="Qty">
        <button class="sr-btn sr-btn--solid sr-btn--mini addBtn"
          data-code="${encodeURIComponent(it.code)}"
          data-title="${encodeURIComponent(it.title || "")}"
          data-subgroup="${encodeURIComponent(it.subgroup || "")}"><i class="bi bi-plus-lg"></i> Track</button>`}
    </div>`;
  }

  async function loadMore() {
    if (!searchState) return;
    searchState.page += 1;
    const btn = id("srLoadMore");
    if (btn) { btn.disabled = true; btn.textContent = "Loading…"; }
    try {
      const { q, sg, page } = searchState;
      const d = await jget(`/api/stock/search?q=${encodeURIComponent(q)}&subgroup=${encodeURIComponent(sg)}&page=${page}`);
      const items = d.items || [];
      searchState.loaded += items.length;
      const wrap = btn ? btn.closest(".sr-loadmore") : null;
      const frag = document.createElement("div");
      frag.innerHTML = items.map(resultHtml).join("");
      while (frag.firstChild) el.addResults.insertBefore(frag.firstChild, wrap);
      if (wrap) wrap.outerHTML = loadMoreHtml();
    } catch (e) { if (btn) { btn.disabled = false; btn.textContent = "Retry"; } }
  }

  async function onAddTrack(btn) {
    const row = btn.closest(".sr-result");
    const qtyEl = row.querySelector(".qtyIn");
    const qty = parseFloat(qtyEl && qtyEl.value);
    if (isNaN(qty) || qty < 0) { toast("Enter a starting quantity", "err"); qtyEl && qtyEl.focus(); return; }
    btn.disabled = true;
    const res = await jpost("/api/stock/add", {
      itm_code: decodeURIComponent(btn.dataset.code),
      title: decodeURIComponent(btn.dataset.title),
      subgroup: decodeURIComponent(btn.dataset.subgroup),
      qty,
    });
    if (res.ok) {
      toast("Now tracking", "ok");
      const nameEl = row.querySelector(".sr-result__name");
      nameEl.innerHTML = '<span class="sr-tracked-tag"><i class="bi bi-check-circle-fill"></i>Tracked</span>' + nameEl.innerHTML;
      qtyEl && qtyEl.remove(); btn.remove();
      loadList();
    } else { toast(res.error || "Failed", "err"); btn.disabled = false; }
  }

  // ══════════════════════════════════════════════════════════
  //  EVENTS (delegated)
  // ══════════════════════════════════════════════════════════
  el.list.addEventListener("click", (e) => {
    const head = e.target.closest(".sr-item__head");
    if (head) { const row = head.closest(".sr-item"); toggleItem(Number(row.dataset.id)); }
  });
  el.kpis.addEventListener("click", (e) => {
    const tile = e.target.closest(".sr-kpi[data-act]");
    if (tile) setFilter(tile.dataset.act);
  });
  el.filters.addEventListener("click", (e) => {
    const chip = e.target.closest(".sr-fchip");
    if (chip) setFilter(chip.dataset.f);
  });
  el.radar.addEventListener("click", (e) => {
    const leg = e.target.closest(".sr-leg");
    if (leg) setFilter(leg.dataset.f);
  });
  el.spot.addEventListener("click", (e) => {
    const cb = e.target.closest(".sr-urg__count");
    if (cb) { quickCount(Number(cb.dataset.count)); return; }
    const card = e.target.closest(".sr-urg");
    if (card) { /* clicking the card body could expand; reserved */ }
  });

  el.search.addEventListener("input", debounce(() => { state.q = el.search.value; renderList(); }, 140));
  el.sort.addEventListener("change", () => { state.sort = el.sort.value; renderList(); });
  el.refresh.addEventListener("click", () => loadList({ force: true }));

  el.addToggle.addEventListener("click", () => toggleAdd());
  el.addClose.addEventListener("click", () => toggleAdd(false));
  el.addSearchBtn.addEventListener("click", doAddSearch);
  el.addSearch.addEventListener("keydown", (e) => { if (e.key === "Enter") doAddSearch(); });
  el.addResults.addEventListener("click", (e) => {
    const add = e.target.closest(".addBtn");
    if (add) { onAddTrack(add); return; }
    if (e.target.closest("#srLoadMore")) loadMore();
  });

  document.addEventListener("keydown", (e) => {
    if (e.target.matches("input, select, textarea")) {
      if (e.key === "Escape" && !el.add.hidden && el.addSearch.contains(e.target)) toggleAdd(false);
      return;
    }
    if (e.key === "r" || e.key === "R") loadList({ force: true });
    else if (e.key === "/") { e.preventDefault(); el.search.focus(); }
    else if (e.key === "Escape" && !el.add.hidden) toggleAdd(false);
  });

  // ── auto refresh (never mid-interaction) ───────────────────
  setInterval(() => {
    if (document.hidden) return;
    if (openIds.size > 0) return;
    if (!el.add.hidden) return;
    if (document.activeElement && root.contains(document.activeElement) &&
        document.activeElement.matches("input, select, textarea")) return;
    loadList({ silent: true });
  }, AUTO_MS);

  // ── utils ──────────────────────────────────────────────────
  function debounce(fn, ms) {
    let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
  }

  // ── go ─────────────────────────────────────────────────────
  loadList();
})();
