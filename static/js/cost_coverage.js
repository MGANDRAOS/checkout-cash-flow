/* ============================================================
   Cost Coverage report — which items need a cost, ranked by
   revenue-at-risk. Public API: CostCoverageModule.init()
   ============================================================ */
const CostCoverageModule = (() => {
  const API = '/api/reports/cost-coverage';
  const SUBS_API = '/api/reports/subgroups';
  const CSV_API = '/api/reports/cost-coverage/export-csv';

  let els = {};
  let data = null;
  let days = 90;

  const nfInt = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 });
  const nfUsd = new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  function fmtQty(n) {
    n = Number(n) || 0;
    return Number.isInteger(n) ? nfInt.format(n) : n.toLocaleString('en-US', { maximumFractionDigits: 2 });
  }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => (
      { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
    ));
  }
  function searchText() { return (els.search.value || '').trim().toLowerCase(); }

  function params() {
    const p = new URLSearchParams();
    p.set('days', String(days));
    if (els.subgroup.value) p.set('subgroup', els.subgroup.value);
    return p;
  }

  async function loadSubgroups() {
    try {
      const r = await fetch(SUBS_API);
      const list = await r.json();
      const frag = document.createDocumentFragment();
      (list || []).forEach(s => {
        const o = document.createElement('option');
        o.value = s.name; o.textContent = s.name;
        frag.appendChild(o);
      });
      els.subgroup.appendChild(frag);
    } catch (e) { /* keep "All subgroups" only */ }
  }

  function setBusy(b) { els.export.disabled = b; }
  function setStatus(html) { els.status.innerHTML = html || ''; }

  async function load() {
    setBusy(true);
    setStatus('');
    els.results.innerHTML = '<div class="is-skeleton"></div><div class="is-skeleton"></div><div class="is-skeleton"></div>';
    try {
      const r = await fetch(`${API}?${params().toString()}`);
      const body = await r.json();
      if (!r.ok || body.error) throw new Error(body.error || `Request failed (${r.status})`);
      data = body;
      renderHero(body);
      renderResults();
    } catch (e) {
      data = null;
      els.results.innerHTML = '';
      els.hint.textContent = '—';
      setStatus(`<div class="is-banner error"><i class="bi bi-exclamation-triangle"></i> ${esc(e.message)}</div>`);
    } finally {
      setBusy(false);
    }
  }

  function renderHero(body) {
    const cov = body.coverage || {};
    const risk = body.at_risk || {};
    const pct = (cov.coverage_pct == null) ? 0 : cov.coverage_pct;
    els.coveragePct.textContent = pct.toFixed(1);
    els.bar.style.setProperty('--cov', `${Math.max(0, Math.min(100, pct))}%`);
    els.atRiskRev.textContent = nfInt.format(risk.revenue || 0);
    els.atRiskUsd.textContent = nfUsd.format(risk.revenue_usd || 0);
    els.uncosted.textContent = nfInt.format(cov.uncosted_active || 0);
    els.atRiskItems.textContent = nfInt.format(risk.items || 0);
    els.dormant.textContent = nfInt.format(body.dormant_uncosted || 0);
  }

  function rowHtml(it, topRev) {
    const rev = Number(it.revenue) || 0;
    const isTop = topRev > 0 && rev === topRev;
    const last = it.last_sold ? `last ${esc(it.last_sold)}` : '';
    return `
      <div class="cc-row${isTop ? ' cc-top' : ''}">
        <div class="cc-code">#${esc(it.item_code)}</div>
        <div class="cc-id">
          <span class="cc-name">${esc(it.item)}</span><span class="cc-sub">${esc(it.subgroup)}</span>
        </div>
        <div class="cc-rowmeta">
          <span class="u">${fmtQty(it.qty)} u</span>
          <span>@${nfInt.format(Number(it.avg_price) || 0)}</span>
          <span>${last}</span>
        </div>
        <div class="cc-rev">${nfInt.format(rev)}<small>at risk</small></div>
      </div>`;
  }

  function renderResults() {
    if (!data) return;
    const q = searchText();
    let rows = data.rows || [];
    if (q) {
      rows = rows.filter(it => (it.item || '').toLowerCase().includes(q) ||
        String(it.item_code || '').toLowerCase().includes(q) ||
        (it.subgroup || '').toLowerCase().includes(q));
    }

    if (!rows.length) {
      const covered = (data.at_risk && data.at_risk.items === 0 && !q);
      els.results.innerHTML = `<div class="is-empty"><i class="bi ${covered ? 'bi-check2-circle' : 'bi-inboxes'}"></i>` +
        `${covered ? 'Every item that sold has a cost — 100% covered 🎉' : (q ? 'No items match your search.' : 'Nothing to fix in this window.')}</div>`;
      els.hint.textContent = '0 items';
      return;
    }

    els.hint.textContent = `${nfInt.format(rows.length)} item${rows.length === 1 ? '' : 's'} to cost`;
    const topRev = rows.reduce((m, it) => Math.max(m, Number(it.revenue) || 0), 0);
    els.results.innerHTML = rows.map(it => rowHtml(it, topRev)).join('');
  }

  function exportCsv() {
    window.location.href = `${CSV_API}?${params().toString()}`;
  }

  function init() {
    els = {
      subgroup: document.getElementById('ccSubgroup'),
      search: document.getElementById('ccSearch'),
      export: document.getElementById('ccExport'),
      coveragePct: document.getElementById('ccCoveragePct'),
      bar: document.getElementById('ccBar'),
      atRiskRev: document.getElementById('ccAtRiskRev'),
      atRiskUsd: document.getElementById('ccAtRiskUsd'),
      uncosted: document.getElementById('ccUncosted'),
      atRiskItems: document.getElementById('ccAtRiskItems'),
      dormant: document.getElementById('ccDormant'),
      hint: document.getElementById('ccHint'),
      results: document.getElementById('ccResults'),
      status: document.getElementById('ccStatus'),
    };

    document.querySelectorAll('.is-chip[data-days]').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.is-chip[data-days]').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        days = parseInt(btn.dataset.days, 10) || 90;
        load();
      });
    });

    els.subgroup.addEventListener('change', load);
    els.export.addEventListener('click', exportCsv);

    let searchT;
    els.search.addEventListener('input', () => {
      clearTimeout(searchT);
      searchT = setTimeout(renderResults, 120);
    });

    loadSubgroups();
    load();
  }

  return { init };
})();
