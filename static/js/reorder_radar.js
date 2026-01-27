// static/js/reorder_radar.js

(function () {
  "use strict";

  /**
   * Reorder Radar JS Module
   * - Server-side paging (DataTables)
   * - Reads filters from the form
   * - Row click -> triggers Item 360 drawer (if your Items Explorer exposes a global open function)
   */
  const ReorderRadarModule = {
    init: function init(options) {
      const tableSelector = options.tableSelector;
      const filtersFormSelector = options.filtersFormSelector;
      const applyButtonSelector = options.applyButtonSelector;
      const exportLinkSelector = options.exportLinkSelector;

      const filtersForm = document.querySelector(filtersFormSelector);
      const applyButton = document.querySelector(applyButtonSelector);
      const exportLink = document.querySelector(exportLinkSelector);

      if (!filtersForm || !applyButton || !exportLink) {
        console.error("ReorderRadarModule: missing required DOM elements.");
        return;
      }

      const getFilters = () => {
        const formData = new FormData(filtersForm);
        return {
          q: (formData.get("q") || "").toString().trim(),
          lookback: parseInt((formData.get("lookback") || "30").toString(), 10),
          onlyAction: (formData.get("onlyAction") || "1").toString(),
          subgroup: (formData.get("subgroup") || "").toString().trim()
        };
      };

      const buildQueryString = (filters) => {
        const params = new URLSearchParams();
        if (filters.q) params.set("q", filters.q);
        if (filters.subgroup) params.set("subgroup", filters.subgroup);
        params.set("lookback", String(filters.lookback || 30));
        params.set("onlyAction", String(filters.onlyAction || "1"));
        return params.toString();
      };

      // IMPORTANT: DataTables server-side mode (paged from backend)
      const dataTable = $(tableSelector).DataTable({
        processing: true,
        serverSide: true,
        searching: false, // we use our own search box
        lengthMenu: [10, 25, 50, 100],
        pageLength: 25,
        order: [[2, "desc"]], // Score desc by default
        ajax: function (data, callback) {
          const filters = getFilters();

          const payload = {
            draw: data.draw,
            start: data.start,
            length: data.length,
            order: data.order,
            columns: data.columns,
            // Custom filters
            q: filters.q,
            subgroup: filters.subgroup,
            lookback: filters.lookback,
            onlyAction: filters.onlyAction
          };

          fetch("/api/reorder-radar", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
          })
            .then((res) => res.json())
            .then((json) => callback(json))
            .catch((err) => {
              console.error("ReorderRadarModule ajax error:", err);
              callback({
                draw: data.draw,
                recordsTotal: 0,
                recordsFiltered: 0,
                data: []
              });
            });
        },
        columns: [
          { data: "itm_code" },
          { data: "itm_name" },
          { data: "score", className: "text-end" },
          { data: "qty_7d", className: "text-end" },
          { data: "qty_30d", className: "text-end" },
          { data: "avg_daily_30d", className: "text-end" },
          { data: "trend_ratio", className: "text-end" },
          { data: "days_since_last_sale", className: "text-end" },
          { data: "last_sold_bizdate" },
          { data: "flags" }
        ]
      });

      // Apply filters reload
      applyButton.addEventListener("click", function () {
        dataTable.ajax.reload();
        const qs = buildQueryString(getFilters());
        exportLink.href = "/api/reorder-radar/export?" + qs;
      });

      // Initialize export link
      exportLink.href = "/api/reorder-radar/export?" + buildQueryString(getFilters());

      // Row click -> attempt to open Item 360° drawer (optional integration)
      // IMPORTANT: we do NOT hard-depend on your existing drawer implementation.
      $(tableSelector + " tbody").on("click", "tr", function () {
        const rowData = dataTable.row(this).data();
        if (!rowData) return;

        // If you already expose a global function for the drawer, call it here:
        // Example: window.ItemsExplorer.openItem360(itmCode)
        if (window.ItemsExplorer && typeof window.ItemsExplorer.openItem360 === "function") {
          window.ItemsExplorer.openItem360(rowData.itm_code);
        }
      });
    }
  };

  window.ReorderRadarModule = ReorderRadarModule;
})();
