/* ============================================================
   Items Sold report — fetch + group-by-subgroup + render.
   Public API: ItemsSoldModule.init()
   ============================================================ */
const ItemsSoldModule = (() => {
  const API = '/api/reports/items-sold';
  const SUBS_API = '/api/reports/subgroups';
  const CSV_API = '/api/reports/items-sold/export-csv';

  let els = {};
  let data = null;             // last successful API payload
  let expanded = new Set();    // subgroup names currently open

  const nfInt = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 });
  const nfUsd = new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  // ── helpers ──────────────────────────────────────────────
  function fmtQty(n) {
    n = Number(n) || 0;
    return Number.isInteger(n) ? nfInt.format(n) : n.toLocaleString('en-US', { maximumFractionDigits: 2 });
  }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => (
      { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
    ));
  }
  function ymd(d) {
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${y}-${m}-${day}`;
  }
  function clearChips() {
    document.querySelectorAll('.is-chip').forEach(b => b.classList.remove('active'));
  }
  function marginClass(m) {
    if (m == null) return 'na';
    if (m < 0) return 'neg';
    if (m > 0) return 'pos';
    return 'na';
  }
  function marginText(m) {
    return (m == null) ? '—' : `${Number(m).toFixed(1)}%`;
  }

  function setRange(from, to) {
    els.from.value = ymd(from);
    els.to.value = ymd(to);
  }

  function quickRange(key) {
    const today = new Date(); today.setHours(0, 0, 0, 0);
    let from = new Date(today);
    let to = new Date(today);
    if (key === 'yesterday') { from.setDate(from.getDate() - 1); to.setDate(to.getDate() - 1); }
    else if (key === 'last7') { from.setDate(from.getDate() - 6); }
    else if (key === 'last30') { from.setDate(from.getDate() - 29); }
    else if (key === 'thisMonth') { from = new Date(today.getFullYear(), today.getMonth(), 1); }
    // 'today' keeps both at today
    setRange(from, to);
  }

  function params() {
    const p = new URLSearchParams();
    p.set('start_date', els.from.value);
    p.set('end_date', els.to.value);
    if (els.subgroup.value) p.set('subgroup', els.subgroup.value);
    return p;
  }

  function searchText() {
    return (els.search.value || '').trim().toLowerCase();
  }

  // ── data load ────────────────────────────────────────────
  async function loadSubgroups() {
    try {
      const r = await fetch(SUBS_API);
      const list = await r.json();
      const frag = document.createDocumentFragment();
      (list || []).forEach(s => {
        const o = document.createElement('option');
        o.value = s.name;
        o.textContent = s.name;
        frag.appendChild(o);
      });
      els.subgroup.appendChild(frag);
    } catch (e) { /* leave "All subgroups" only */ }
  }

  function setBusy(b) {
    els.apply.disabled = b;
    els.export.disabled = b;
    els.expandAll.disabled = b;
  }
  function setStatus(html) { els.status.innerHTML = html || ''; }

  async function load() {
    if (!els.from.value || !els.to.value) return;
    setBusy(true);
    setStatus('');
    els.results.innerHTML = '<div class="is-skeleton"></div><div class="is-skeleton"></div><div class="is-skeleton"></div>';
    try {
      const r = await fetch(`${API}?${params().toString()}`);
      const body = await r.json();
      if (!r.ok || body.error) throw new Error(body.error || `Request failed (${r.status})`);

      data = body;
      renderKpis(body);

      // Default expansion: explicit subgroup filter -> open all; otherwise -> open the top group.
      const groups = buildGroups(body.rows);
      expanded = new Set();
      if (els.subgroup.value && groups.length) groups.forEach(g => expanded.add(g.name));
      else if (groups.length) expanded.add(groups[0].name);

      renderResults();
    } catch (e) {
      data = null;
      renderKpis(null);
      els.results.innerHTML = '';
      els.hint.textContent = '—';
      setStatus(`<div class="is-banner error"><i class="bi bi-exclamation-triangle"></i> ${esc(e.message)}</div>`);
    } finally {
      setBusy(false);
    }
  }

  // ── rendering ────────────────────────────────────────────
  function renderKpis(body) {
    const t = (body && body.totals) || {};
    els.kpiRevLbp.textContent = nfInt.format(t.revenue || 0);
    els.kpiRevUsd.textContent = nfUsd.format(t.revenue_usd || 0);
    els.kpiProfitLbp.textContent = nfInt.format(t.profit || 0);
    els.kpiProfitUsd.textContent = nfUsd.format(t.profit_usd || 0);
    els.kpiUnits.textContent = fmtQty(t.qty || 0);
    els.kpiItems.textContent = nfInt.format(t.items || 0);

    // margin badge next to Profit (color-coded)
    const margin = (t.margin == null) ? null : t.margin;
    els.kpiMargin.textContent = (margin == null) ? '—' : `${margin.toFixed(1)}% margin`;
    els.kpiMargin.className = 'is-kpi-margin ' + marginClass(margin);

    // caveat: how many items lack a cost (excluded from profit)
    const unc = t.uncosted_items || 0;
    if (unc > 0) {
      els.caveat.style.display = '';
      els.caveat.innerHTML = `<i class="bi bi-info-circle"></i> Profit uses each item's current cost · ` +
        `${nfInt.format(unc)} item${unc === 1 ? ' has' : 's have'} no cost set (excluded from profit).`;
    } else {
      els.caveat.style.display = 'none';
      els.caveat.textContent = '';
    }

    const m = (body && body.meta) || {};
    if (m.start_date) {
      const sub = m.subgroup ? ` · ${m.subgroup}` : ' · all subgroups';
      els.meta.textContent = `${m.start_date} → ${m.end_date}  ·  ${m.days} day${m.days === 1 ? '' : 's'}${sub}`;
    } else {
      els.meta.textContent = 'Pick a range to load sales.';
    }
  }

  function buildGroups(rows) {
    const map = new Map();
    (rows || []).forEach(r => {
      let g = map.get(r.subgroup);
      if (!g) { g = { name: r.subgroup, items: [], qty: 0, revenue: 0 }; map.set(r.subgroup, g); }
      g.items.push(r);
      g.qty += Number(r.qty) || 0;
      g.revenue += Number(r.revenue) || 0;
    });
    const groups = Array.from(map.values());
    groups.sort((a, b) => b.revenue - a.revenue);
    return groups;
  }

  function rowHtml(it, topItemRev) {
    const rev = Number(it.revenue) || 0;
    const isTop = topItemRev > 0 && rev === topItemRev;
    const microW = topItemRev ? (rev / topItemRev * 100) : 0;
    const costTxt = (it.unit_cost == null) ? '—' : nfInt.format(it.unit_cost);
    const mCls = marginClass(it.margin);
    return `
      <div class="is-row${isTop ? ' is-top' : ''}">
        <div class="is-row-id">
          <span class="is-row-name">${esc(it.item)}</span><span class="is-row-code">#${esc(it.item_code)}</span>
        </div>
        <div class="is-row-stats">
          <span class="qty">${fmtQty(it.qty)} u</span>
          <span class="cost">cost ${costTxt}</span>
          <span class="avg">@${nfInt.format(Number(it.avg_price) || 0)}</span>
          <span class="is-microbar"><span style="width:${microW.toFixed(1)}%"></span></span>
          <span class="is-margin ${mCls}">${marginText(it.margin)}</span>
        </div>
        <div class="is-row-rev">${nfInt.format(rev)}</div>
      </div>`;
  }

  function renderResults() {
    if (!data) return;
    const q = searchText();
    const groups = buildGroups(data.rows);

    let visibleItems = 0;
    const rendered = groups.map(g => {
      const items = q
        ? g.items.filter(it => (it.item || '').toLowerCase().includes(q) || String(it.item_code || '').toLowerCase().includes(q))
        : g.items;
      if (!items.length) return null;
      visibleItems += items.length;
      const rev = items.reduce((s, it) => s + (Number(it.revenue) || 0), 0);
      const qty = items.reduce((s, it) => s + (Number(it.qty) || 0), 0);
      // group profit/margin over costed items only (mirrors the server rule)
      let cost = 0, profit = 0, costedRev = 0;
      items.forEach(it => {
        if (it.unit_cost != null && it.profit != null) {
          cost += Number(it.total_cost) || 0;
          profit += Number(it.profit) || 0;
          costedRev += Number(it.revenue) || 0;
        }
      });
      const margin = costedRev ? (profit / costedRev * 100) : null;
      return { name: g.name, items, rev, qty, cost, profit, margin };
    }).filter(Boolean);

    if (!rendered.length) {
      els.results.innerHTML = `<div class="is-empty"><i class="bi bi-inboxes"></i>${q ? 'No items match your search.' : 'No items sold in this range.'}</div>`;
      els.hint.textContent = '0 items';
      updateExpandLabel([]);
      return;
    }

    els.hint.textContent = `${nfInt.format(visibleItems)} item${visibleItems === 1 ? '' : 's'} · ${rendered.length} subgroup${rendered.length === 1 ? '' : 's'}`;
    const maxGroupRev = Math.max(...rendered.map(g => g.rev), 1);

    els.results.innerHTML = rendered.map(g => {
      const open = q ? true : expanded.has(g.name);   // searching reveals matches
      const barPct = g.rev / maxGroupRev * 100;
      const topItemRev = g.items.reduce((m, it) => Math.max(m, Number(it.revenue) || 0), 0);
      const rows = g.items.map(it => rowHtml(it, topItemRev)).join('');
      return `
        <div class="is-group${open ? ' open' : ''}" data-sub="${esc(g.name)}">
          <button class="is-group-head" type="button" data-sub="${esc(g.name)}">
            <span class="is-caret"><i class="bi bi-chevron-right"></i></span>
            <span class="is-group-name">${esc(g.name)} <span class="is-count">${nfInt.format(g.items.length)}</span></span>
            <span class="is-group-figs">
              <span class="is-group-rev">${nfInt.format(g.rev)}</span>
              <span class="is-group-sub">${fmtQty(g.qty)} u · <span class="is-margin ${marginClass(g.margin)}">${marginText(g.margin)}</span> margin</span>
            </span>
          </button>
          <div class="is-sharebar"><span style="width:${barPct.toFixed(1)}%"></span></div>
          <div class="is-group-body">${rows}</div>
        </div>`;
    }).join('');

    updateExpandLabel(rendered.map(g => g.name));
  }

  function updateExpandLabel(names) {
    const allOpen = names.length && names.every(n => expanded.has(n));
    const lbl = els.expandAll.querySelector('span');
    if (lbl) lbl.textContent = allOpen ? 'Collapse all' : 'Expand all';
  }

  // ── interactions ─────────────────────────────────────────
  function toggleGroup(name) {
    if (expanded.has(name)) expanded.delete(name); else expanded.add(name);
    renderResults();
  }

  function toggleExpandAll() {
    if (!data) return;
    const names = buildGroups(data.rows).map(g => g.name);
    const allOpen = names.length && names.every(n => expanded.has(n));
    expanded = allOpen ? new Set() : new Set(names);
    renderResults();
  }

  function exportCsv() {
    if (!els.from.value || !els.to.value) return;
    window.location.href = `${CSV_API}?${params().toString()}`;
  }

  // ── init ─────────────────────────────────────────────────
  function init() {
    els = {
      from: document.getElementById('isFrom'),
      to: document.getElementById('isTo'),
      subgroup: document.getElementById('isSubgroup'),
      search: document.getElementById('isSearch'),
      apply: document.getElementById('isApply'),
      export: document.getElementById('isExport'),
      expandAll: document.getElementById('isExpandAll'),
      kpiRevLbp: document.getElementById('isKpiRevLbp'),
      kpiRevUsd: document.getElementById('isKpiRevUsd'),
      kpiProfitLbp: document.getElementById('isKpiProfitLbp'),
      kpiProfitUsd: document.getElementById('isKpiProfitUsd'),
      kpiMargin: document.getElementById('isKpiMargin'),
      kpiUnits: document.getElementById('isKpiUnits'),
      kpiItems: document.getElementById('isKpiItems'),
      meta: document.getElementById('isMeta'),
      caveat: document.getElementById('isCaveat'),
      hint: document.getElementById('isResultsHint'),
      results: document.getElementById('isResults'),
      status: document.getElementById('isStatus'),
    };

    quickRange('last7');

    els.apply.addEventListener('click', load);
    els.from.addEventListener('change', () => { clearChips(); load(); });
    els.to.addEventListener('change', () => { clearChips(); load(); });
    els.subgroup.addEventListener('change', load);
    els.export.addEventListener('click', exportCsv);
    els.expandAll.addEventListener('click', toggleExpandAll);

    let searchT;
    els.search.addEventListener('input', () => {
      clearTimeout(searchT);
      searchT = setTimeout(renderResults, 120);
    });

    document.querySelectorAll('.is-chip[data-quick]').forEach(btn => {
      btn.addEventListener('click', () => {
        clearChips();
        btn.classList.add('active');
        quickRange(btn.dataset.quick);
        load();
      });
    });

    // delegated subgroup-card toggle
    els.results.addEventListener('click', (e) => {
      const head = e.target.closest('.is-group-head');
      if (head) toggleGroup(head.dataset.sub);
    });

    loadSubgroups();
    load();
  }

  return { init };
})();
