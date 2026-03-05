// static/js/sales_snapshot.js

(function () {
  // Expose as a module (matches your preference: module with init())
  window.SalesSnapshotModule = {
    init() {


      const pageRoot = document.getElementById("salesSnapshotPage");
      if (!pageRoot) return; // Safety: only run on this page

      // Elements
      const fromDateInput = document.getElementById("fromDate");
      const toDateInput = document.getElementById("toDate");
      const exportCsvBtn = document.getElementById("exportCsvBtn");

      const totalSalesEl = document.getElementById("totalSales");
      const totalSalesElUsd = document.getElementById("totalSalesUSD");
      const kpiSublineEl = document.getElementById("kpiSubline");
      const breakdownHintEl = document.getElementById("breakdownHint");
      const breakdownBodyEl = document.getElementById("breakdownBody");

      // Mode radios
      const modeDaily = document.getElementById("modeDaily");
      const modeMonthly = document.getElementById("modeMonthly");

      // Quick buttons
      const quickButtons = pageRoot.querySelectorAll("[data-quick]");

      // ----------------------------
      // IMPORTANT: Default dates
      // ----------------------------
      // If user opens the page, give them "today" by default.
      const todayISO = new Date().toISOString().slice(0, 10);
      fromDateInput.value = todayISO;
      toDateInput.value = todayISO;

      // Wire events
      fromDateInput.addEventListener("change", refresh);
      toDateInput.addEventListener("change", refresh);
      modeDaily.addEventListener("change", refresh);
      modeMonthly.addEventListener("change", refresh);
      exportCsvBtn.addEventListener("click", () => {
        exportCsv();
      });

      quickButtons.forEach((btn) => {
        btn.addEventListener("click", () => {
          applyQuickRange(btn.getAttribute("data-quick"));
          refresh();
        });
      });

      function exportCsv() {
        const fromDate = fromDateInput.value;
        const toDate = toDateInput.value;
        const mode = getSelectedMode();

        if (!fromDate || !toDate) {
          alert("Select From and To dates first.");
          return;
        }
        if (fromDate > toDate) {
          alert("From date cannot be after To date.");
          return;
        }

        // IMPORTANT: this triggers a file download (no fetch needed)
        const url = `/api/sales-summary/export-csv?from=${encodeURIComponent(fromDate)}&to=${encodeURIComponent(toDate)}&mode=${encodeURIComponent(mode)}`;
        window.location.href = url;
      }

      // First load
      refresh();

      // ----------------------------
      // Helpers
      // ----------------------------

      function getSelectedMode() {
        return modeMonthly.checked ? "monthly" : "daily";
      }

      function applyQuickRange(key) {
        const now = new Date();

        const toISO = (d) => d.toISOString().slice(0, 10);

        // Create new Date objects so we don't mutate "now"
        const start = new Date(now);
        const end = new Date(now);

        if (key === "today") {
          // start/end already today
        } else if (key === "yesterday") {
          start.setDate(start.getDate() - 1);
          end.setDate(end.getDate() - 1);
        } else if (key === "last7") {
          start.setDate(start.getDate() - 6); // inclusive range: today + 6 previous days = 7
        } else if (key === "thisMonth") {
          start.setDate(1);
        } else if (key === "lastMonth") {
          // Go to first day of current month, then step back one day to reach last month
          const firstOfThisMonth = new Date(now.getFullYear(), now.getMonth(), 1);
          const lastOfLastMonth = new Date(firstOfThisMonth);
          lastOfLastMonth.setDate(lastOfLastMonth.getDate() - 1);

          start.setFullYear(lastOfLastMonth.getFullYear(), lastOfLastMonth.getMonth(), 1);
          end.setFullYear(lastOfLastMonth.getFullYear(), lastOfLastMonth.getMonth(), lastOfLastMonth.getDate());
        }

        fromDateInput.value = toISO(start);
        toDateInput.value = toISO(end);
      }

      function setLoadingState() {
        totalSalesEl.textContent = "Loading…";
        kpiSublineEl.textContent = "—";
        breakdownHintEl.textContent = "Loading…";
        breakdownBodyEl.innerHTML = `
          <tr>
            <td class="px-4 px-lg-5 py-4 text-muted fs-5" colspan="2">Loading sales…</td>
          </tr>
        `;
      }

      function setEmptyState(message) {
        totalSalesEl.textContent = "0";
        kpiSublineEl.textContent = message || "No sales found in this range.";
        breakdownHintEl.textContent = "—";
        breakdownBodyEl.innerHTML = `
          <tr>
            <td class="px-4 px-lg-5 py-4 text-muted fs-5" colspan="2">No rows to show.</td>
          </tr>
        `;
      }

      function formatNumber(value) {
        // Keep it simple: 12,345.67
        const numberValue = Number(value || 0);
        return numberValue.toLocaleString(undefined, { maximumFractionDigits: 2 });
      }

      async function refresh() {
        const fromDate = fromDateInput.value;
        const toDate = toDateInput.value;
        const mode = getSelectedMode();

        // Basic validation: both dates must exist
        if (!fromDate || !toDate) {
          setEmptyState("Select From and To dates.");
          return;
        }

        // Basic validation: From must be <= To
        if (fromDate > toDate) {
          setEmptyState("From date cannot be after To date.");
          return;
        }

        setLoadingState();

        try {
          // IMPORTANT: API endpoint contract
          // Backend should return: { total_sales, rows: [{ label, total }], meta: { days_or_months_count, avg } }
          const url = `/api/sales-summary?from=${encodeURIComponent(fromDate)}&to=${encodeURIComponent(toDate)}&mode=${encodeURIComponent(mode)}`;
          const response = await fetch(url);

          if (!response.ok) {
            throw new Error(`API error: ${response.status}`);
          }

          const data = await response.json();

          if (!data || typeof data.total_sales === "undefined") {
            setEmptyState("No data returned from server.");
            return;
          }

          // Render KPI
          totalSalesEl.textContent = formatNumber(data.total_sales);
          totalSalesElUsd.textContent = formatNumber(data.total_sales/89000);

          // Render KPI subline
          const countLabel = mode === "monthly" ? "months" : "days";
          const countValue = data?.meta?.count ?? "—";
          const avgValue = data?.meta?.avg ?? null;

          kpiSublineEl.textContent = avgValue !== null
            ? `${countValue} ${countLabel} • Avg/${mode === "monthly" ? "month" : "day"} ${formatNumber(avgValue)}`
            : `${countValue} ${countLabel}`;

          breakdownHintEl.textContent = mode === "monthly" ? "Grouped by month" : "Grouped by day";

          // Render table rows
          const rows = Array.isArray(data.rows) ? data.rows : [];
          if (rows.length === 0) {
            setEmptyState("No sales in this range.");
            return;
          }

          breakdownBodyEl.innerHTML = rows.map((row) => {
            const label = row.label ?? "—";
            const total = formatNumber(row.total ?? 0);
            return `
              <tr>
                <td class="px-4 px-lg-5 fs-5">${label}</td>
                <td class="px-4 px-lg-5 fs-5 text-end fw-semibold">${total}</td>
              </tr>
            `;
          }).join("");

        } catch (error) {
          // IMPORTANT: user-friendly failure
          totalSalesEl.textContent = "—";
          kpiSublineEl.textContent = "Failed to load sales.";
          breakdownHintEl.textContent = "—";
          breakdownBodyEl.innerHTML = `
            <tr>
              <td class="px-4 px-lg-5 py-4 text-danger fs-5" colspan="2">
                Error loading sales. Check server logs. (${String(error.message || error)})
              </td>
            </tr>
          `;
        }
      }
    },




  };
})();