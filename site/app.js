(function () {
  "use strict";

  const state = { dashboard: null, products: [], total: 0, offset: 0, selected: null, request: 0, detailRequest: 0, searchStatus: "idle", failedSearchReset: true };
  const routes = [...document.querySelectorAll("[data-route]")];
  const pages = [...document.querySelectorAll("[data-page]")];
  const sidebar = document.querySelector(".sidebar");
  const context = document.getElementById("page-context");
  const names = { overview: "Overview", trends: "Relative trends", explore: "Explore products", quality: "Data quality" };
  const nf = new Intl.NumberFormat("en-US");
  const count = (value) => Number.isFinite(value) ? nf.format(value) : "Unavailable";
  const pct = (value, digits = 1) => Number.isFinite(value) ? `${(value * 100).toFixed(digits)}%` : "Unavailable";
  const title = (value) => String(value || "").replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
  const escapeHtml = (value) => String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;");
  const safeUrl = (value) => { try { const url = new URL(value); return ["http:", "https:"].includes(url.protocol) ? url.href : "#"; } catch { return "#"; } };

  async function api(path) {
    const response = await fetch(path, { headers: { Accept: "application/json" } });
    if (!response.ok) throw new Error(`Request failed (${response.status})`);
    return response.json();
  }

  function toast(message) {
    const root = document.getElementById("toast");
    root.textContent = message;
    root.classList.add("is-visible");
    window.setTimeout(() => root.classList.remove("is-visible"), 3200);
  }

  function activate(name) {
    if (!names[name]) name = "overview";
    routes.forEach((item) => item.classList.toggle("is-active", item.dataset.route === name));
    pages.forEach((page) => {
      const active = page.dataset.page === name;
      page.hidden = !active;
      page.classList.toggle("is-active", active);
    });
    context.textContent = `Internal analytics / ${names[name]}`;
    window.history.replaceState(null, "", `#${name}`);
    sidebar.classList.remove("is-open");
    window.scrollTo({ top: 0, behavior: "auto" });
    if (name === "explore" && !state.products.length) searchProducts(true);
  }

  function renderMetrics(data) {
    const cards = [
      ["Complete products", data.products, "Deduplicated, complete text"],
      ["Launch relationships", data.launch_relationships, `${count(data.relaunched_products)} products relaunched`],
      ["Destination hosts", data.distinct_domains, `${count(data.external_websites)} external URLs`],
      ["Products with entities", data.entity_products, `${count(data.entity_assignments)} retained mentions`]
    ];
    document.getElementById("metric-grid").innerHTML = cards.map(([label, value, note]) => `<article class="metric-card"><span class="metric-label">${escapeHtml(label)}</span><strong>${count(value)}</strong><p>${escapeHtml(note)}</p></article>`).join("");
    renderEvidenceCounts(data);
  }

  function renderEvidenceCounts(data) {
    const coverage = (value) => !Number.isFinite(data.products) || !Number.isFinite(value) ? "Unavailable" : data.products > 0 ? pct(value / data.products) : "Not applicable";
    document.getElementById("opened-product-count").textContent = `${count(data.products)} products in this mart`;
    document.getElementById("quality-product-count").textContent = `${count(data.products)} products`;
    document.getElementById("category-assignment-count").textContent = `${count(data.category_assignments)} assignments`;
    document.getElementById("label-assignment-count").textContent = `${count(data.label_assignments)} assignments`;
    document.getElementById("entity-assignment-count").textContent = `${count(data.entity_assignments)} assignments`;
    document.getElementById("category-coverage").textContent = `${coverage(data.categorized_products)} product coverage in this mart.`;
    document.getElementById("label-coverage").textContent = `${coverage(data.labeled_products)} product coverage in this mart.`;
  }

  function renderRankChart(items) {
    const shown = items.slice(0, 12);
    const max = Math.max(...shown.map((item) => item.products));
    document.getElementById("label-chart").innerHTML = shown.map((item) => `<div class="rank-row"><span class="rank-name">${escapeHtml(title(item.label))}</span><div class="rank-track"><div class="rank-value" style="width:${(item.products / max * 100).toFixed(1)}%"></div></div><span class="rank-count">${nf.format(item.products)}</span></div>`).join("");
  }

  function renderCoverage(data) {
    const total = data.products;
    if (!Number.isFinite(total)) {
      document.getElementById("coverage-rings").innerHTML = `<p class="panel-note">Product count unavailable. Coverage cannot be calculated.</p>`;
      return;
    }
    if (total === 0) {
      document.getElementById("coverage-rings").innerHTML = `<p class="panel-note">No products in this mart. Coverage percentages are not applicable.</p>`;
      return;
    }
    const rings = [["PH categories", data.categorized_products], ["Broad labels", data.labeled_products], ["Entities", data.entity_products]];
    document.getElementById("coverage-rings").innerHTML = rings.map(([label, numerator]) => {
      const value = Number.isFinite(numerator) && numerator >= 0 && numerator <= total ? numerator / total : null;
      return `<div class="coverage-ring${value === null ? " is-unavailable" : ""}"${value === null ? "" : ` style="--coverage:${pct(value)}"`}><div><strong>${pct(value)}</strong><span>${escapeHtml(label)}</span></div></div>`;
    }).join("");
  }

  function renderEntityTypes(items) {
    document.getElementById("entity-types").innerHTML = items.map((item) => `<article class="entity-type"><i></i><strong>${nf.format(item.products)}</strong><span>${escapeHtml(title(item.entity_type))}<br>${nf.format(item.distinct_values)} distinct</span></article>`).join("");
  }

  function renderDomains(items) {
    document.getElementById("domain-list").innerHTML = items.slice(0, 10).map((item) => `<div class="domain-row"><span>${escapeHtml(item.website_host)}</span><strong>${nf.format(item.products)}</strong></div>`).join("");
  }

  function renderPairs(items) {
    document.getElementById("label-pairs").innerHTML = items.slice(0, 10).map((item) => `<article class="pair-card"><div>${escapeHtml(title(item.label_a))}<br><i>×</i> ${escapeHtml(title(item.label_b))}</div><strong>${nf.format(item.products)}</strong></article>`).join("");
  }

  function linePath(points) {
    return points.map((point, index) => `${index ? "L" : "M"}${point[0].toFixed(1)},${point[1].toFixed(1)}`).join(" ");
  }

  function renderCohorts(items) {
    if (items.length < 2) {
      document.getElementById("cohort-chart").innerHTML = `<p class="panel-note">Not enough mapped launch-order cohorts to draw a comparison.</p>`;
      return;
    }
    const width = 1000, height = 300, left = 42, right = 18, top = 18, bottom = 34;
    const series = [["trusted_label_coverage", "#f26d4f"], ["entity", "#6e8ff5"], ["category_coverage", "#14211b"]];
    const values = items.flatMap((item) => [item.trusted_label_coverage, item.entity_products / item.products, item.category_coverage]);
    const max = Math.max(...values, 0.01) * 1.08;
    const x = (index) => left + index * ((width - left - right) / (items.length - 1));
    const y = (value) => top + (max - value) / max * (height - top - bottom);
    const grid = [0, .25, .5, .75, 1].map((step) => {
      const value = max * step, py = y(value);
      return `<line class="chart-grid" x1="${left}" y1="${py}" x2="${width-right}" y2="${py}"/><text class="chart-axis" x="0" y="${py+3}">${pct(value,0)}</text>`;
    }).join("");
    const paths = series.map(([key, color]) => {
      const points = items.map((item, index) => [x(index), y(key === "entity" ? item.entity_products / item.products : item[key])]);
      return `<path class="chart-line" stroke="${color}" d="${linePath(points)}"/>${points.map((point) => `<circle class="chart-dot" fill="${color}" cx="${point[0]}" cy="${point[1]}" r="3"/>`).join("")}`;
    }).join("");
    const labels = items.map((item, index) => index % 2 === 0 ? `<text class="chart-axis" text-anchor="middle" x="${x(index)}" y="${height-8}">${item.relative_cohort}</text>` : "").join("");
    document.getElementById("cohort-chart").innerHTML = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Evidence coverage across ${items.length} relative launch-order cohorts">${grid}${paths}${labels}</svg>`;
  }

  function renderLabelTrends(items) {
    const max = Math.max(...items.map((item) => Math.abs(item.labeled_share_change)));
    document.getElementById("label-trends").innerHTML = items.map((item) => {
      const change = item.labeled_share_change;
      const width = Math.abs(change) / max * 50;
      const style = change >= 0 ? `left:50%;width:${width}%` : `right:50%;width:${width}%`;
      return `<div class="shift-row"><span>${escapeHtml(title(item.label))}</span><div class="shift-track"><div class="shift-value ${change < 0 ? "negative" : ""}" style="${style}"></div></div><strong class="shift-change">${change >= 0 ? "+" : ""}${(change*100).toFixed(1)}</strong></div>`;
    }).join("");
  }

  function renderEntityTrends(id, items, falling) {
    document.getElementById(id).innerHTML = items.slice(0, 14).map((item) => {
      const ratio = item.coverage_normalized_growth_index;
      const display = ratio == null ? "new" : `${ratio.toFixed(1)}×`;
      return `<div class="trend-row"><div><strong>${escapeHtml(title(item.canonical_value))}</strong><small>${escapeHtml(title(item.entity_type))} · ${nf.format(item.all_products)} products</small></div><span class="trend-ratio ${falling ? "down" : ""}">${escapeHtml(display)}</span></div>`;
    }).join("");
  }

  function populateFilters(data) {
    document.getElementById("label-filter").insertAdjacentHTML("beforeend", data.labels.map((item) => `<option value="${escapeHtml(item.label)}">${escapeHtml(title(item.label))}</option>`).join(""));
    document.getElementById("entity-filter").insertAdjacentHTML("beforeend", data.entity_types.map((item) => `<option value="${escapeHtml(item.entity_type)}">${escapeHtml(title(item.entity_type))}</option>`).join(""));
  }

  async function loadDashboard() {
    document.getElementById("metric-grid").setAttribute("aria-busy", "true");
    try {
      const data = await api("/api/dashboard");
      state.dashboard = data;
      renderMetrics(data.metrics);
      renderRankChart(data.labels);
      renderCoverage(data.metrics);
      renderEntityTypes(data.entity_types);
      renderDomains(data.domains);
      renderPairs(data.label_pairs);
      renderCohorts(data.cohorts);
      renderLabelTrends(data.label_trends);
      renderEntityTrends("entity-risers", data.entity_risers, false);
      renderEntityTrends("entity-fallers", data.entity_fallers, true);
      populateFilters(data);
    } catch (error) {
      document.getElementById("metric-grid").innerHTML = `<article class="metric-card" style="grid-column:1 / -1"><p role="alert">Could not load analytics. Counts and coverage are unavailable.</p><button type="button" class="load-more" data-retry-dashboard>Retry analytics</button></article>`;
    } finally {
      document.getElementById("metric-grid").setAttribute("aria-busy", "false");
    }
  }

  function productQuery(reset) {
    const params = new URLSearchParams({
      q: document.getElementById("product-search").value,
      label: document.getElementById("label-filter").value,
      entity_type: document.getElementById("entity-filter").value,
      sort: document.getElementById("sort-filter").value,
      limit: "24",
      offset: String(reset ? 0 : state.offset)
    });
    return `/api/products?${params}`;
  }

  function renderProducts() {
    const root = document.getElementById("product-list");
    root.innerHTML = state.products.map((product) => `<button class="product-row ${state.selected === product.slug ? "is-active" : ""}" type="button" data-slug="${escapeHtml(product.slug)}"><span><span class="product-name">${escapeHtml(product.name)}</span><span class="product-tagline">${escapeHtml(product.tagline)}</span></span><span class="product-meta">${product.top_trusted_label ? escapeHtml(title(product.top_trusted_label)) : "Unlabeled"}<br>${product.launch_count} launch${product.launch_count === 1 ? "" : "es"}</span></button>`).join("");
    if (state.searchStatus === "loaded") document.getElementById("result-count").textContent = `${nf.format(state.total)} matching products · showing ${nf.format(state.products.length)}`;
    document.getElementById("load-more").hidden = state.products.length >= state.total;
  }

  async function searchProducts(reset = true) {
    const request = ++state.request;
    state.searchStatus = "pending";
    if (reset) {
      state.offset = 0; state.products = []; state.selected = null; state.total = 0;
      state.detailRequest++;
      renderProducts();
      document.getElementById("product-detail").innerHTML = `<div class="detail-placeholder">Select a product to inspect its full record.</div>`;
    }
    document.getElementById("result-count").textContent = reset ? "Loading products…" : "Loading more products…";
    document.getElementById("product-list").setAttribute("aria-busy", "true");
    document.getElementById("load-more").disabled = true;
    try {
      const result = await api(productQuery(reset));
      if (request !== state.request) return;
      if (!Array.isArray(result.items) || !Number.isFinite(result.total) || result.total < 0) throw new Error("Invalid product list");
      state.searchStatus = "loaded";
      state.total = result.total;
      state.products.push(...result.items);
      state.offset = state.products.length;
      if (!state.selected && state.products.length) state.selected = state.products[0].slug;
      renderProducts();
      if (reset && state.selected) loadProduct(state.selected);
      if (reset && !state.products.length) document.getElementById("product-detail").innerHTML = `<div class="detail-placeholder">No matching products. Change or clear the search filters.</div>`;
    } catch (error) {
      if (request !== state.request) return;
      state.searchStatus = "error";
      state.failedSearchReset = reset;
      document.getElementById("result-count").textContent = "Products could not be loaded. Retry or change the search filters.";
      document.getElementById("load-more").hidden = false;
    } finally {
      if (request === state.request) {
        document.getElementById("product-list").setAttribute("aria-busy", "false");
        document.getElementById("load-more").disabled = false;
        document.getElementById("load-more").textContent = state.searchStatus === "error" ? "Retry search" : "Load more";
      }
    }
  }

  function chips(items, className = "") {
    return items.length ? items.map((item) => `<span class="chip ${className}">${escapeHtml(item)}</span>`).join("") : `<span class="chip ${className}">None recorded</span>`;
  }

  async function loadProduct(slug) {
    const request = ++state.detailRequest;
    state.selected = slug;
    renderProducts();
    const root = document.getElementById("product-detail");
    root.innerHTML = `<div class="detail-placeholder">Loading product evidence…</div>`;
    try {
      const product = await api(`/api/products/${encodeURIComponent(slug)}`);
      if (request !== state.detailRequest || state.selected !== slug) return;
      root.innerHTML = `<div class="detail-top"><span class="detail-kicker">${product.top_trusted_label ? `Top broad label · ${escapeHtml(title(product.top_trusted_label))}` : "No broad label assigned"}</span><span class="detail-id">Product ID ${product.latest_product_id ? nf.format(product.latest_product_id) : "unavailable"}</span></div><h2>${escapeHtml(product.name)}</h2><p class="detail-tagline">${escapeHtml(product.tagline)}</p><p class="detail-description">${escapeHtml(product.description)}</p><dl class="detail-facts"><div><dt>Launch relationships</dt><dd>${nf.format(product.launch_count)}</dd></div><div><dt>Post ID span</dt><dd>${product.first_post_id ? `${nf.format(product.first_post_id)}–${nf.format(product.latest_post_id)}` : "None mapped"}</dd></div><div><dt>External host</dt><dd>${escapeHtml(product.website_host || "Unavailable")}</dd></div></dl><div class="detail-section"><span>Trusted broad labels</span><div class="chips">${chips(product.labels.map((item) => title(item.label)))}</div></div><div class="detail-section"><span>Original Product Hunt categories</span><div class="chips">${chips(product.source_categories || [], "source")}</div></div><div class="detail-section"><span>Concrete entity mentions</span><div class="chips">${chips(product.entities.map((item) => `${title(item.entity_type)} · ${title(item.canonical_value)}`), "entity")}</div></div><div class="detail-actions">${product.has_external_website ? `<a href="${escapeHtml(safeUrl(product.website_url))}" target="_blank" rel="noopener noreferrer">Visit website</a>` : ""}<a class="secondary" href="${escapeHtml(safeUrl(product.producthunt_url))}" target="_blank" rel="noopener noreferrer">Product Hunt</a></div>`;
    } catch (error) {
      if (request !== state.detailRequest || state.selected !== slug) return;
      root.innerHTML = `<div class="detail-placeholder">Could not load this product. Select it again to retry.</div>`;
      toast(error.message);
    }
  }

  routes.forEach((item) => item.addEventListener("click", (event) => { event.preventDefault(); activate(item.dataset.route); }));
  document.querySelector(".menu-button").addEventListener("click", () => sidebar.classList.toggle("is-open"));
  document.querySelector("[data-go-explore]").addEventListener("click", () => activate("explore"));
  document.getElementById("search-form").addEventListener("submit", (event) => { event.preventDefault(); searchProducts(true); });
  let timer;
  document.getElementById("product-search").addEventListener("input", () => { window.clearTimeout(timer); timer = window.setTimeout(() => searchProducts(true), 280); });
  ["label-filter", "entity-filter", "sort-filter"].forEach((id) => document.getElementById(id).addEventListener("change", () => searchProducts(true)));
  document.getElementById("load-more").addEventListener("click", () => searchProducts(state.searchStatus === "error" ? state.failedSearchReset : false));
  document.getElementById("metric-grid").addEventListener("click", (event) => { if (event.target.closest("[data-retry-dashboard]")) loadDashboard(); });
  document.getElementById("product-list").addEventListener("click", (event) => { const row = event.target.closest("[data-slug]"); if (row) loadProduct(row.dataset.slug); });
  window.addEventListener("hashchange", () => activate(window.location.hash.slice(1)));

  loadDashboard();
  activate(window.location.hash.slice(1) || "overview");
})();
