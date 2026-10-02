// Offline state regression checks. No browser, catalogue, or network access.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function fixture({ stacked = false } = {}) {
  const navigation = [];
  const document = { activeElement: null };
  const nodes = new Map();
  const node = (id) => {
    if (!nodes.has(id)) nodes.set(id, {
      innerHTML: '', textContent: '', value: '', hidden: false, disabled: false,
      dataset: {}, attributes: {}, classList: { toggle() {}, add() {}, remove() {} },
      listeners: {},
      focus(options) { document.activeElement = this; navigation.push({ id, action: 'focus', options }); },
      scrollIntoView(options) { navigation.push({ id, action: 'scroll', options }); },
      querySelectorAll() {
        if (id !== 'product-list') return [];
        return [...this.innerHTML.matchAll(/data-slug="([^"]+)"/g)].map((match) => {
          const row = node(`row-${match[1]}`); row.dataset.slug = match[1]; return row;
        });
      },
      addEventListener(type, callback) { this.listeners[type] = callback; },
      insertAdjacentHTML() {},
      setAttribute(key, value) { this.attributes[key] = value; }
    });
    return nodes.get(id);
  };
  Object.assign(document, { getElementById: node, querySelector: node, querySelectorAll: () => [] });
  const requests = [];
  const context = vm.createContext({
    document,
    window: { history: { replaceState() {} }, location: { hash: '' },
      matchMedia: () => ({ matches: stacked }), scrollTo() {}, setTimeout() {}, clearTimeout() {}, addEventListener() {} },
    Intl, URL, URLSearchParams,
    fetch(path) { return new Promise((resolve) => requests.push({ path, resolve })); }
  });
  const source = fs.readFileSync('site/app.js', 'utf8').replace(/\}\)\(\);\s*$/, `
    window.test = { searchProducts, loadProduct, loadDashboard, renderEvidenceCounts, renderCoverage };
  })();`);
  vm.runInContext(source, context);
  return { node, requests, navigation, document, api: context.window.test };
}

function respond(request, data, status = 200) {
  request.resolve({ ok: status === 200, status, json: async () => data });
}


async function verifyEvidenceNavigation() {
  const detail = (name) => ({ name, labels: [], entities: [], launch_count: 1 });
  const flush = () => new Promise(setImmediate);
  for (const stacked of [true, false]) {
    const { node, requests, api, navigation, document } = fixture({ stacked });
    respond(requests[0], {}, 503);
    await flush();
    let pending = api.searchProducts(true);
    respond(requests.at(-1), { total: 48, items: [
      { slug: 'first', name: 'First' }, { slug: 'latest', name: 'Latest' }
    ] });
    await pending;
    respond(requests.at(-1), detail('First'));
    await flush();
    assert.equal(navigation.length, 0, 'initial automatic detail must never focus or scroll');
    const select = (slug) => node('product-list').listeners.click({
      target: { closest: () => ({ dataset: { slug } }) }
    });
    select('first');
    const obsolete = requests.at(-1);
    select('latest');
    const current = requests.at(-1);
    assert.equal(navigation.length, stacked ? 4 : 0, 'only explicit stacked selection navigates');
    if (stacked) {
      assert.equal(document.activeElement, node('product-detail'));
      assert.equal(navigation.at(-1).options.behavior, 'instant', 'navigation honors reduced motion');
      assert.equal(navigation.at(-1).options.block, 'start');
      assert.equal(navigation.at(-2).options.preventScroll, true);
    }
    // The user can return while the latest request is still pending.
    node('product-detail').listeners.click({ target: { closest: () => ({}) } });
    assert.equal(document.activeElement, node('row-latest'), 'return restores the current selected row');
    assert.equal(navigation.at(-1).options.block, 'nearest');
    node('return-to-product').focus({ preventScroll: true });
    const afterReturnFocus = navigation.length;
    respond(current, detail('Latest'));
    await flush();
    respond(obsolete, detail('Obsolete'));
    await flush();
    assert(node('product-evidence').innerHTML.includes('Latest'));
    assert(!node('product-evidence').innerHTML.includes('Obsolete'));
    assert.equal(navigation.length, afterReturnFocus, 'current or stale completion must not jump');
    assert.equal(document.activeElement, node('return-to-product'), 'persistent return control keeps focus across completion');
    assert.equal(node('product-detail').attributes['aria-busy'], 'false');

    select('first');
    const staleFailure = requests.at(-1);
    select('latest');
    const latestFailure = requests.at(-1);
    const beforeFailure = navigation.length;
    respond(staleFailure, {}, 503);
    await flush();
    assert.equal(node('product-detail').attributes['aria-busy'], 'true', 'stale failure cannot clear current busy status');
    respond(latestFailure, {}, 503);
    await flush();
    assert.equal(navigation.length, beforeFailure, 'failures never initiate navigation');
    assert.equal(node('return-to-product').hidden, false, 'return remains available on failure');
    assert(node('product-evidence').innerHTML.includes('select it again to retry'));
    node('product-detail').listeners.click({ target: { closest: () => ({}) } });
    assert.equal(document.activeElement, node('row-latest'));
    select('latest');
    respond(requests.at(-1), detail('Recovered'));
    await flush();
    assert(node('product-evidence').innerHTML.includes('Recovered'));

    select('first');
    const invalidated = requests.at(-1);
    pending = api.searchProducts(true);
    node('product-search').focus({ preventScroll: true });
    const afterReset = navigation.length;
    respond(invalidated, detail('Invalidated'));
    respond(requests.at(-1), { total: 0, items: [] });
    await pending;
    await flush();
    assert.equal(navigation.length, afterReset, 'search reset invalidates detail navigation');
    assert.equal(document.activeElement, node('product-search'));
    assert(node('product-evidence').innerHTML.includes('No matching products'));
    assert.equal(node('product-detail').attributes['aria-busy'], 'false');
  }
}

async function main() {
  await verifyEvidenceNavigation();
  const { node, requests, api } = fixture();
  respond(requests[0], {}, 503);
  await new Promise(setImmediate);
  assert(node('metric-grid').innerHTML.includes('Retry analytics'));
  assert.equal(node('metric-grid').attributes['aria-busy'], 'false');
  let pending = api.searchProducts(true);
  respond(requests.at(-1), { total: 1, items: [{ slug: 'alpha', name: 'Alpha' }] });
  await pending;
  const staleDetail = requests.at(-1);
  pending = api.searchProducts(true);
  assert.equal(node('product-list').innerHTML, '');
  assert(!node('product-evidence').innerHTML.includes('Alpha'));
  respond(requests.at(-1), { total: 0, items: [] });
  await pending;
  respond(staleDetail, {}, 503);
  await new Promise(setImmediate);
  assert(node('product-evidence').innerHTML.includes('No matching products'));
  assert(node('result-count').textContent.startsWith('0 matching'));
  assert.equal(node('load-more').hidden, true);

  pending = api.searchProducts(true);
  respond(requests.at(-1), {}, 503);
  await pending;
  assert(node('result-count').textContent.includes('could not be loaded'));
  assert.equal(node('product-list').attributes['aria-busy'], 'false');
  assert.equal(node('load-more').textContent, 'Retry search');
  assert.equal(node('load-more').disabled, false);
  pending = api.searchProducts(true);
  respond(requests.at(-1), { total: 0, items: [] });
  await pending;
  assert(node('result-count').textContent.startsWith('0 matching'));

  // Exercise the actual row and retry click handlers, including a result-count
  // boundary that used to hide retry and a normal 24-of-48 pagination fixture.
  for (const firstPageSize of [1, 24]) {
    const firstPage = Array.from({ length: firstPageSize }, (_, i) => ({
      slug: `first-${i}`, name: `First ${i}`, tagline: 'Synthetic', launch_count: 1
    }));
    pending = api.searchProducts(true);
    respond(requests.at(-1), { total: firstPageSize === 1 ? 1 : 48, items: firstPage });
    await pending;
    respond(requests.at(-1), {}, 503); // Initial auto-selected detail.
    await new Promise(setImmediate);

    pending = api.searchProducts(false);
    const failedPage = requests.at(-1);
    assert.equal(new URL(failedPage.path, 'http://fixture.test').searchParams.get('offset'), String(firstPageSize));
    respond(failedPage, {}, 503);
    await pending;
    const failureText = node('result-count').textContent;
    for (let click = 0; click < 2; click++) {
      node('product-list').listeners.click({ target: { closest: () => ({ dataset: { slug: 'first-0' } }) } });
      assert.equal(node('load-more').hidden, false, 'row selection must preserve failed-page retry');
      assert.equal(node('load-more').disabled, false);
      assert.equal(node('load-more').textContent, 'Retry search');
      assert.equal(node('result-count').textContent, failureText);
      respond(requests.at(-1), {}, 503);
      await new Promise(setImmediate);
    }
    node('load-more').listeners.click();
    const retry = requests.at(-1);
    assert.equal(retry.path, failedPage.path, 'retry must keep the failed offset and filters');
    const nextPage = Array.from({ length: firstPageSize }, (_, i) => ({
      slug: `next-${i}`, name: `Next ${i}`, tagline: 'Synthetic', launch_count: 1
    }));
    respond(retry, { total: firstPageSize * 2, items: nextPage });
    await new Promise(setImmediate);
    const slugs = [...node('product-list').innerHTML.matchAll(/data-slug="([^"]+)"/g)].map((match) => match[1]);
    assert.equal(slugs.length, firstPageSize * 2);
    assert.equal(new Set(slugs).size, slugs.length, 'successful retry must not duplicate retained rows');
    assert.equal(slugs[0], 'first-0');
    assert.equal(slugs[firstPageSize], 'next-0');
    assert.equal(node('load-more').hidden, true, 'completed pagination hides load more');
    assert.equal(node('load-more').textContent, 'Load more');
    assert(node('result-count').textContent.endsWith(`showing ${firstPageSize * 2}`));
  }

  // Editing the debounced input must not mix a new query with retained rows.
  node('product-search').value = 'original';
  pending = api.searchProducts(true);
  respond(requests.at(-1), { total: 48, items: Array.from({ length: 24 }, (_, i) => ({ slug: `owned-${i}`, name: `Owned ${i}` })) });
  await pending;
  respond(requests.at(-1), {}, 503);
  await new Promise(setImmediate);
  node('product-search').value = 'changed';
  pending = api.searchProducts(false);
  const ownedQuery = new URL(requests.at(-1).path, 'http://fixture.test');
  assert.equal(ownedQuery.searchParams.get('q'), 'changed');
  assert.equal(ownedQuery.searchParams.get('offset'), '0', 'changed query must reset before pagination');
  assert.equal(node('product-list').innerHTML, '', 'changed query cannot retain old rows');
  respond(requests.at(-1), { total: 0, items: [] });
  await pending;

  const old = api.searchProducts(true);
  const oldRequest = requests.at(-1);
  const current = api.searchProducts(true);
  respond(requests.at(-1), { total: 0, items: [] });
  await current;
  respond(oldRequest, {}, 503);
  await old;
  assert(node('result-count').textContent.startsWith('0 matching'));

  // Both late success and late failure must leave the current selection intact.
  const detail = (name) => ({ name, labels: [], entities: [], launch_count: 1 });
  const firstDetail = api.loadProduct('old-detail');
  const firstDetailRequest = requests.at(-1);
  const nextDetail = api.loadProduct('new-detail');
  respond(requests.at(-1), detail('New detail'));
  await nextDetail;
  respond(firstDetailRequest, detail('Old detail'));
  await firstDetail;
  assert(node('product-evidence').innerHTML.includes('New detail'));
  assert(!node('product-evidence').innerHTML.includes('Old detail'));

  const lateSearch = api.searchProducts(true);
  const lateSearchRequest = requests.at(-1);
  const freshSearch = api.searchProducts(true);
  respond(requests.at(-1), { total: 0, items: [] });
  await freshSearch;
  respond(lateSearchRequest, { total: 1, items: [{ slug: 'obsolete', name: 'Obsolete' }] });
  await lateSearch;
  assert.equal(node('product-list').innerHTML, '');
  assert(node('result-count').textContent.startsWith('0 matching'));

  for (const value of [null, -1, 2]) {
    const metrics = { products: 1, categorized_products: value, labeled_products: value };
    api.renderEvidenceCounts(metrics);
    api.renderCoverage(metrics);
    assert(node('coverage-rings').innerHTML.includes('Unavailable'));
    assert(node('category-coverage').textContent.startsWith('Unavailable'), `invalid coverage ${value}`);
    assert(node('label-coverage').textContent.startsWith('Unavailable'));
  }
  api.renderEvidenceCounts({ products: 1, categorized_products: 0, labeled_products: 0,
    category_assignments: 0, label_assignments: 0, entity_assignments: 0 });
  assert.equal(node('opened-product-count').textContent, '1 products in this mart');
  assert.equal(node('quality-product-count').textContent, '1 products');
  assert.equal(node('category-assignment-count').textContent, '0 assignments');
  assert.equal(node('label-assignment-count').textContent, '0 assignments');
  assert.equal(node('entity-assignment-count').textContent, '0 assignments');
  assert(node('category-coverage').textContent.startsWith('0.0%'));
  api.renderEvidenceCounts({ products: 0, categorized_products: 0, labeled_products: 0 });
  assert(node('category-coverage').textContent.startsWith('Not applicable'));
  api.renderEvidenceCounts({ products: null });
  assert(node('opened-product-count').textContent.includes('Unavailable'));
  api.renderEvidenceCounts({ products: -1, categorized_products: 0 });
  api.renderCoverage({ products: -1 });
  assert(node('category-coverage').textContent.startsWith('Unavailable'));
  assert(node('coverage-rings').innerHTML.includes('unavailable'));
  console.log('PASS: empty, reset, stale detail/error, failure/recovery, pagination retry/row selection/no duplicates, coverage boundaries, stacked explicit focus/return/retry, initial and desktop nojump, stale completion nojump');
}
main().catch((error) => { console.error(error); process.exitCode = 1; });
