// static/js/sales_snapshot.js

(function () {
  window.SalesSnapshotModule = {
    init() {
      const pageRoot = document.getElementById("salesSnapshotPage");
      if (!pageRoot) return;

      // ── Elements ─────────────────────────────────────────────────
      const fromDateInput   = document.getElementById("fromDate");
      const toDateInput     = document.getElementById("toDate");
      const exportCsvBtn    = document.getElementById("exportCsvBtn");
      const totalSalesEl    = document.getElementById("totalSales");
      const totalSalesElUsd = document.getElementById("totalSalesUSD");
      const kpiSublineEl    = document.getElementById("kpiSubline");
      const breakdownHintEl = document.getElementById("breakdownHint");
      const breakdownBodyEl = document.getElementById("breakdownBody");
      const modeDaily       = document.getElementById("modeDaily");
      const modeMonthly     = document.getElementById("modeMonthly");
      const quickChips      = pageRoot.querySelectorAll(".snap-chip[data-quick]");

      // ── Default dates (yesterday) ────────────────────────────────
      applyQuickRange("yesterday");

      // ── Wire events ───────────────────────────────────────────────
      fromDateInput.addEventListener("change", refresh);
      toDateInput.addEventListener("change", refresh);
      modeDaily.addEventListener("change", refresh);
      modeMonthly.addEventListener("change", refresh);
      exportCsvBtn.addEventListener("click", exportCsv);

      quickChips.forEach((chip) => {
        chip.addEventListener("click", () => {
          quickChips.forEach(c => c.classList.remove("active"));
          chip.classList.add("active");
          applyQuickRange(chip.getAttribute("data-quick"));
          refresh();
        });
      });

      // Clear active chip when user types dates manually
      fromDateInput.addEventListener("change", clearActiveChip);
      toDateInput.addEventListener("change", clearActiveChip);

      // ── First load ────────────────────────────────────────────────
      refresh();

      // ── Helpers ───────────────────────────────────────────────────

      function getSelectedMode() {
        return modeMonthly.checked ? "monthly" : "daily";
      }

      function clearActiveChip() {
        quickChips.forEach(c => c.classList.remove("active"));
      }

      function applyQuickRange(key) {
        const now = new Date();
        const toISO = (d) => d.toISOString().slice(0, 10);
        const start = new Date(now);
        const end   = new Date(now);

        if (key === "yesterday") {
          start.setDate(start.getDate() - 1);
          end.setDate(end.getDate() - 1);
        } else if (key === "last7") {
          start.setDate(start.getDate() - 6);
        } else if (key === "thisMonth") {
          start.setDate(1);
        } else if (key === "lastMonth") {
          const firstOfThis = new Date(now.getFullYear(), now.getMonth(), 1);
          const lastOfLast  = new Date(firstOfThis);
          lastOfLast.setDate(lastOfLast.getDate() - 1);
          start.setFullYear(lastOfLast.getFullYear(), lastOfLast.getMonth(), 1);
          end.setFullYear(lastOfLast.getFullYear(), lastOfLast.getMonth(), lastOfLast.getDate());
        }
        // "today" → start/end already today

        fromDateInput.value = toISO(start);
        toDateInput.value   = toISO(end);
      }

      function formatNumber(value) {
        return Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 2 });
      }

      function setLoadingState() {
        totalSalesEl.textContent    = "—";
        totalSalesElUsd.textContent = "—";
        kpiSublineEl.textContent    = "Loading…";
        breakdownHintEl.textContent = "Loading…";
        breakdownBodyEl.innerHTML   =
          `<tr><td colspan="2" class="snap-empty-state">Loading sales…</td></tr>`;
      }

      function setEmptyState(message) {
        totalSalesEl.textContent    = "0";
        totalSalesElUsd.textContent = "0";
        kpiSublineEl.textContent    = message || "No sales found in this range.";
        breakdownHintEl.textContent = "—";
        breakdownBodyEl.innerHTML   =
          `<tr><td colspan="2" class="snap-empty-state">${message || "No rows to show."}</td></tr>`;
      }

      const DAY_NAMES = ["Sunday","Monday","Tuesday","Wednesday","Thursday","Friday","Saturday"];

      function parseDayInfo(label) {
        // Only parse YYYY-MM-DD daily labels (not YYYY-MM monthly)
        if (!/^\d{4}-\d{2}-\d{2}$/.test(label)) return { dayName: null, isWeekend: false };
        const d = new Date(label + "T12:00:00"); // noon avoids DST edge cases
        if (isNaN(d.getTime())) return { dayName: null, isWeekend: false };
        const dow = d.getDay();
        return { dayName: DAY_NAMES[dow], isWeekend: dow === 0 || dow === 6 };
      }

      function renderRows(rows) {
        const maxTotal = Math.max(...rows.map(r => Number(r.total || 0)), 1);

        breakdownBodyEl.innerHTML = rows.map((row) => {
          const label   = row.label ?? "—";
          const total   = Number(row.total ?? 0);
          const pct     = ((total / maxTotal) * 100).toFixed(1);
          const fmtd    = formatNumber(total);
          const { dayName, isWeekend } = parseDayInfo(label);

          const dayBadge = dayName
            ? `<span class="snap-day-badge${isWeekend ? " snap-day-weekend" : ""}">${dayName}</span>`
            : "";

          return `
            <tr class="${isWeekend ? "snap-row-weekend" : ""}">
              <td class="snap-td-label">
                <div class="snap-label-row">
                  <span class="snap-row-label">${label}</span>
                  ${dayBadge}
                </div>
                <div class="snap-bar-track">
                  <div class="snap-bar-fill" style="width:${pct}%"></div>
                </div>
              </td>
              <td class="snap-td-value">${fmtd}</td>
            </tr>`;
        }).join("");
      }

      function exportCsv() {
        const from = fromDateInput.value;
        const to   = toDateInput.value;
        const mode = getSelectedMode();
        if (!from || !to) { alert("Select From and To dates first."); return; }
        if (from > to)    { alert("From date cannot be after To date."); return; }
        window.location.href =
          `/api/sales-summary/export-csv?from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}&mode=${encodeURIComponent(mode)}`;
      }

      async function refresh() {
        const from = fromDateInput.value;
        const to   = toDateInput.value;
        const mode = getSelectedMode();

        if (!from || !to)  { setEmptyState("Select From and To dates."); return; }
        if (from > to)     { setEmptyState("From date cannot be after To date."); return; }

        setLoadingState();

        try {
          const url = `/api/sales-summary?from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}&mode=${encodeURIComponent(mode)}`;
          const res  = await fetch(url);
          if (!res.ok) throw new Error(`API error: ${res.status}`);

          const data = await res.json();
          if (!data || typeof data.total_sales === "undefined") {
            setEmptyState("No data returned from server.");
            return;
          }

          // KPI numbers
          totalSalesEl.textContent    = formatNumber(data.total_sales);
          totalSalesElUsd.textContent = formatNumber(data.total_sales / 89000);

          // Subline
          const countLabel = mode === "monthly" ? "months" : "days";
          const count      = data?.meta?.count ?? "—";
          const avg        = data?.meta?.avg ?? null;
          kpiSublineEl.textContent = avg !== null
            ? `${count} ${countLabel}  ·  Avg/${mode === "monthly" ? "month" : "day"} ${formatNumber(avg)}`
            : `${count} ${countLabel}`;

          breakdownHintEl.textContent = mode === "monthly" ? "Grouped by month" : "Grouped by day";

          // Rows
          const rows = Array.isArray(data.rows) ? data.rows : [];
          if (rows.length === 0) { setEmptyState("No sales in this range."); return; }
          renderRows(rows);

        } catch (err) {
          totalSalesEl.textContent    = "—";
          totalSalesElUsd.textContent = "—";
          kpiSublineEl.textContent    = "Failed to load sales.";
          breakdownHintEl.textContent = "—";
          breakdownBodyEl.innerHTML   =
            `<tr><td colspan="2" class="snap-empty-state" style="color:var(--crimson)">
               Error loading sales. (${String(err.message || err)})
             </td></tr>`;
        }
      }
    },
  };
})();
