import json
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse
from xml.etree import ElementTree

LANDING = Path(__file__).resolve().parents[1] / "landing"
ORIGIN = "https://ph.significanthobbies.com"


class HeadParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.meta = {}
        self.canonical = None
        self.schemas = []
        self.in_schema = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "meta":
            self.meta[attrs.get("property", attrs.get("name"))] = attrs.get("content")
        if tag == "link" and attrs.get("rel") == "canonical":
            self.canonical = attrs.get("href")
        self.in_schema = tag == "script" and attrs.get("type") == "application/ld+json"

    def handle_data(self, data):
        if self.in_schema:
            self.schemas.append(json.loads(data))

    def handle_endtag(self, tag):
        if tag == "script":
            self.in_schema = False


def test_landing_has_consistent_canonical_social_and_structured_identity():
    parser = HeadParser()
    parser.feed((LANDING / "index.html").read_text())
    assert parser.canonical == f"{ORIGIN}/"
    assert parser.meta["og:url"] == parser.canonical
    assert parser.meta["description"]
    assert parser.meta["og:title"] == parser.meta["twitter:title"]
    assert parser.meta["og:image"] == parser.meta["twitter:image"]
    application = next(
        schema for schema in parser.schemas if schema["@type"] == "SoftwareApplication"
    )
    assert application["url"] == parser.canonical
    assert application["codeRepository"] == "https://github.com/Significant-Hobbies/ph-catalog"


def test_agent_manifest_and_sitemap_only_advertise_existing_public_files():
    manifest = json.loads((LANDING / "api/ai").read_text())
    sitemap = ElementTree.parse(LANDING / "sitemap.xml")
    advertised = [manifest[key] for key in ("llms", "sitemap", "markdown")]
    advertised += [surface[key] for surface in manifest["surfaces"] for key in ("url", "md")]
    sitemap_urls = [element.text for element in sitemap.findall(".//{*}loc")]
    advertised += sitemap_urls
    for url in advertised:
        parsed = urlparse(url)
        assert f"{parsed.scheme}://{parsed.netloc}" == ORIGIN
        path = LANDING / (parsed.path.lstrip("/") or "index.html")
        assert path.is_file() or path.with_suffix(".html").is_file()
    # Fictional parser fixtures remain accessible to demo users and agents,
    # but are deliberately excluded from search discovery.
    assert set(sitemap_urls) == {f"{ORIGIN}/"}
    assert "/samples/*\n  X-Robots-Tag: noindex" in (LANDING / "_headers").read_text()
    assert f"Sitemap: {ORIGIN}/sitemap.xml" in (LANDING / "robots.txt").read_text()
    assert "Content-Type: application/json" in (LANDING / "_headers").read_text()


def test_sample_click_reports_to_both_analytics_without_requiring_either_loader():
    page = (LANDING / "index.html").read_text()
    assert "window.appHealth?.track('sample_opened')" in page
    assert "window.clarity?.('event', 'sample_opened')" in page
    assert "window.appHealth?.track('source_repository_opened')" in page
    assert "window.clarity?.('event', 'source_repository_opened')" in page
    manifest = json.loads((LANDING / "api/ai").read_text())
    for surface in manifest["surfaces"]:
        if surface["id"] != "home":
            markdown = (LANDING / urlparse(surface["md"]).path.lstrip("/")).read_text()
            assert "fictional" in markdown
