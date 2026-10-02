"""Root-run rendered acceptance fixture. No catalogue, credentials, or external traffic.

Run from the project root with existing Python Playwright and Chrome installed:
rtk proxy python3 tests/verify_pagination_browser.py
Do not run again in the managed sandbox that already blocked Chrome.
"""

import argparse
import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / ".review-output" / "pagination-browser"
ORIGIN = "http://127.0.0.1:18975"
PRODUCTS = [
    {
        "slug": f"fixture-{i}",
        "name": f"Fixture {i:02}",
        "tagline": "Original synthetic pagination fixture",
        "description": "Local test evidence only; no market measurement.",
        "launch_count": 1,
        "top_trusted_label": None,
        "latest_product_id": i + 1,
        "first_post_id": i + 1,
        "latest_post_id": i + 1,
        "website_host": "example.test",
        "labels": [],
        "entities": [],
        "source_categories": [],
        "has_external_website": False,
        "producthunt_url": "https://example.test",
    }
    for i in range(48)
]
METRICS = {
    "products": len(PRODUCTS),
    "launch_relationships": 48,
    "relaunched_products": 0,
    "distinct_domains": 0,
    "external_websites": 0,
    "entity_products": 0,
    "entity_assignments": 0,
    "categorized_products": 0,
    "labeled_products": 0,
    "category_assignments": 0,
    "label_assignments": 0,
}
DASHBOARD = {
    "metrics": METRICS,
    **{
        key: []
        for key in [
            "labels",
            "entity_types",
            "domains",
            "label_pairs",
            "cohorts",
            "label_trends",
            "entity_risers",
            "entity_fallers",
        ]
    },
}


class StaticFixtureHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        # Only these public static files can be served; never expose the checkout.
        files = {
            "/": "site/index.html",
            "/app.js": "site/app.js",
            "/styles.css": "site/styles.css",
            "/landing": "landing/index.html",
            "/samples/acme-toolkit.html": "landing/samples/acme-toolkit.html",
        }
        filename = files.get(urlparse(self.path).path)
        if filename is None:
            self.send_error(404)
            return
        payload = (ROOT / filename).read_bytes()
        self.send_response(200)
        self.send_header(
            "Content-Type",
            {".js": "text/javascript", ".css": "text/css"}.get(Path(filename).suffix, "text/html"),
        )
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_args):
        pass


async def verify(browser_executable):
    OUTPUT.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", 18975), StaticFixtureHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    results = []
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                executable_path=browser_executable,
                headless=True,
            )
            try:
                for width in (390, 768, 1440):
                    for boundary in (False, True):
                        context = await browser.new_context(
                            viewport={"width": width, "height": 900},
                            service_workers="block",
                            reduced_motion="reduce" if boundary else "no-preference",
                        )
                        await context.add_init_script("""(() => {
                            window.evidenceNavigation = [];
                            for (const [prototype, method] of [
                                [HTMLElement.prototype, 'focus'],
                                [Element.prototype, 'scrollIntoView']
                            ]) {
                                const original = prototype[method];
                                prototype[method] = function(options) {
                                    window.evidenceNavigation.push({method, id: this.id, options});
                                    return original.call(this, options);
                                };
                            }
                        })();""")
                        page = await context.new_page()
                        errors = []
                        page.on("pageerror", lambda error, errors=errors: errors.append(str(error)))
                        fixture = {"failed": False, "offsets": [], "detail_fail_slug": None}

                        async def intercept(route, _request, fixture=fixture, boundary=boundary):
                            request = route.request
                            parsed = urlparse(request.url)
                            if (
                                parsed.scheme != "http"
                                or parsed.netloc != "127.0.0.1:18975"
                                or request.method not in ("GET", "HEAD")
                            ):
                                await route.abort()
                                return
                            if parsed.path == "/api/dashboard":
                                await route.fulfill(json=DASHBOARD)
                            elif parsed.path.startswith("/api/products/"):
                                slug = parsed.path.rsplit("/", 1)[1]
                                if fixture["detail_fail_slug"] == slug:
                                    fixture["detail_fail_slug"] = None
                                    await route.fulfill(status=503, json={})
                                else:
                                    await route.fulfill(
                                        json=next(p for p in PRODUCTS if p["slug"] == slug)
                                    )
                            elif parsed.path == "/api/products":
                                offset = int(parse_qs(parsed.query).get("offset", ["0"])[0])
                                fixture["offsets"].append(offset)
                                if offset == 24 and not fixture["failed"]:
                                    fixture["failed"] = True
                                    await route.fulfill(status=503, json={})
                                else:
                                    total = 24 if boundary and offset == 0 else 48
                                    await route.fulfill(
                                        json={
                                            "total": total,
                                            "items": PRODUCTS[offset : offset + 24],
                                        }
                                    )
                            else:
                                await route.continue_()

                        await context.route("**/*", intercept)
                        await page.goto(f"{ORIGIN}/#explore")
                        await page.wait_for_function(
                            "document.querySelectorAll('.product-row').length === 24"
                        )
                        await page.wait_for_function(
                            "document.querySelector('#opened-product-count').textContent"
                            ".includes('48 products')"
                        )
                        assert (
                            await page.locator("#opened-product-count").text_content()
                            == "48 products in this mart"
                        )
                        await page.wait_for_function(
                            "document.querySelector('#product-detail h2')?.textContent"
                            " === 'Fixture 00'"
                        )
                        initial = await page.evaluate("""() => ({
                            scrollY, focus: document.activeElement.id,
                            navigation: window.evidenceNavigation
                        })""")
                        assert initial["scrollY"] == 0, initial
                        assert initial["focus"] != "product-detail", initial
                        assert initial["navigation"] == [], initial
                        # Boundary case reproduces an in-flight request at a prior total;
                        # dispatch the real existing handler even if the button is hidden.
                        if boundary:
                            await page.locator("#load-more").evaluate("button => button.click()")
                        else:
                            await page.get_by_role("button", name="Load more", exact=True).click()
                        retry = page.get_by_role("button", name="Retry search", exact=True)
                        await retry.wait_for()
                        for _ in range(2):
                            await page.locator('[data-slug="fixture-0"]').click()
                            await page.wait_for_function(
                                "document.querySelector('#product-detail h2')?.textContent"
                                " === 'Fixture 00'"
                            )
                            assert await retry.is_visible() and await retry.is_enabled()
                            assert (
                                "could not be loaded"
                                in await page.locator("#result-count").inner_text()
                            )
                        suffix = f"{width}-{'boundary' if boundary else 'normal'}"
                        await page.screenshot(
                            path=str(OUTPUT / f"retry-{suffix}.png"), full_page=True
                        )
                        await retry.click()
                        await page.wait_for_function(
                            "document.querySelectorAll('.product-row').length === 48"
                        )
                        slugs = await page.locator(".product-row").evaluate_all(
                            "rows => rows.map(row => row.dataset.slug)"
                        )
                        assert slugs == [p["slug"] for p in PRODUCTS]
                        assert fixture["offsets"] == [0, 24, 24]
                        assert await page.locator("#load-more").is_hidden()
                        assert (
                            await page.locator("#result-count").inner_text()
                            == "48 matching products · showing 48"
                        )
                        assert await page.evaluate(
                            "document.documentElement.scrollWidth <= innerWidth"
                        )
                        # Resolve detail by the selected slug, never a fixed Fixture 00 mock.
                        selected = page.locator('[data-slug="fixture-24"]')
                        # Native keyboard activation: focusing the row may scroll it into
                        # view; only navigation after Enter belongs to the correction.
                        await selected.focus()
                        before_selection = await page.evaluate("scrollY")
                        await page.evaluate("window.evidenceNavigation = []")
                        await page.keyboard.press("Enter")
                        await page.wait_for_function(
                            "document.querySelector('#product-detail h2')?.textContent"
                            " === 'Fixture 24'"
                        )
                        assert await selected.evaluate("row => row.classList.contains('is-active')")
                        placement = await page.evaluate("""() => {
                            const rect = document.querySelector('#product-detail')
                                .getBoundingClientRect();
                            return {top: rect.top, bottom: rect.bottom, viewportHeight: innerHeight,
                                    visible: rect.top < innerHeight && rect.bottom > 0};
                        }""")
                        navigation = await page.evaluate("window.evidenceNavigation")
                        focus = await page.evaluate("document.activeElement.id")
                        return_control = page.get_by_role(
                            "button", name="Return to selected product", exact=True
                        )
                        if width <= 900:
                            assert placement["visible"] and 66 <= placement["top"] < 900, placement
                            heading = await page.locator("#product-detail h2").bounding_box()
                            assert (
                                heading
                                and heading["y"] >= 66
                                and heading["y"] + heading["height"] <= 900
                            ), heading
                            assert focus == "product-detail", focus
                            assert [entry["method"] for entry in navigation] == [
                                "focus",
                                "scrollIntoView",
                            ], navigation
                            assert navigation[-1]["options"]["behavior"] == "instant", navigation
                            assert await return_control.is_visible()
                        else:
                            assert navigation == [], navigation
                            assert await page.evaluate("scrollY") == before_selection
                            assert abs(placement["top"] - 86) < 1, placement
                            assert focus != "product-detail"
                            assert await return_control.is_hidden()
                        await page.screenshot(path=str(OUTPUT / f"selected-viewport-{suffix}.png"))
                        await page.screenshot(
                            path=str(OUTPUT / f"recovered-{suffix}.png"), full_page=True
                        )
                        returned = None
                        if width <= 900:
                            # From the focused evidence region, Tab reaches the one
                            # native return control. Enter returns to the selected row.
                            await page.keyboard.press("Tab")
                            assert await return_control.evaluate(
                                "button => button === document.activeElement"
                            )
                            await page.keyboard.press("Enter")
                            assert await selected.evaluate("row => row === document.activeElement")
                            returned = await selected.bounding_box()
                            assert (
                                returned
                                and returned["y"] >= 66
                                and returned["y"] + returned["height"] <= 900
                            ), returned
                            assert await selected.evaluate(
                                "row => row.classList.contains('is-active')"
                            )
                            await page.screenshot(
                                path=str(OUTPUT / f"returned-viewport-{suffix}.png")
                            )
                            # A failed detail request keeps the same keyboard return
                            # path, and reselecting the row retries the selected slug.
                            fixture["detail_fail_slug"] = "fixture-24"
                            await page.keyboard.press("Enter")
                            await page.wait_for_function(
                                "document.querySelector('#product-evidence').textContent"
                                ".includes('Could not load this product')"
                            )
                            assert await page.evaluate(
                                "document.activeElement.id === 'product-detail'"
                            )
                            assert await return_control.is_visible()
                            await page.keyboard.press("Tab")
                            assert await return_control.evaluate(
                                "button => button === document.activeElement"
                            )
                            await page.keyboard.press("Enter")
                            assert await selected.evaluate("row => row === document.activeElement")
                            await page.keyboard.press("Enter")
                            await page.wait_for_function(
                                "document.querySelector('#product-detail h2')?.textContent"
                                " === 'Fixture 24'"
                            )
                            assert await page.evaluate(
                                "document.activeElement.id === 'product-detail'"
                            )
                        await page.goto(f"{ORIGIN}/landing")
                        await page.screenshot(
                            path=str(OUTPUT / f"landing-{suffix}.png"), full_page=True
                        )
                        await page.locator('[data-sample="acme-toolkit"]').click()
                        assert page.url == f"{ORIGIN}/samples/acme-toolkit.html"
                        assert not errors, errors
                        results.append(
                            {
                                "width": width,
                                "boundary": boundary,
                                "offsets": fixture["offsets"],
                                "unique_rows": len(set(slugs)),
                                "selected_slug": "fixture-24",
                                "detail_name": "Fixture 24",
                                "detail_placement": placement,
                                "initial_navigation": initial,
                                "selection_navigation": navigation,
                                "selection_focus": focus,
                                "returned_row": returned,
                                "detail_failure_retry": "asserted"
                                if width <= 900
                                else "not-applicable",
                                "reduced_motion": "reduce" if boundary else "no-preference",
                                "external_requests": "blocked",
                                "page_errors": errors,
                            }
                        )
                        await context.close()
            finally:
                await browser.close()
        (OUTPUT / "results.json").write_text(json.dumps(results, indent=2) + "\n")
        print(json.dumps(results, indent=2))
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--browser-executable",
        default="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        help="Existing Chromium/Chrome executable; no download or installation.",
    )
    asyncio.run(verify(parser.parse_args().browser_executable))
