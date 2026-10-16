"""Fetch bounded public evidence only for frozen-v1 routed website candidates.

This writes an immutable, ignored candidate artifact; it never updates source
Product Hunt text or promotes a primary category.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import ipaddress
import json
import os
import re
import socket
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpcore
import httpx
import orjson
from protego import Protego
from selectolax.parser import HTMLParser

from ph_catalog import primary_confidence_routing
from ph_catalog.network import GlobalRateLimiter, retry_after_seconds
from ph_catalog.primary_confidence_routing import ROUTING_POLICY, reserved_slugs
from ph_catalog.primary_heldout import (
    FROZEN_CANDIDATE_MANIFEST_SHA,
    FROZEN_MODEL_SHA,
    FROZEN_TAXONOMY_SHA,
    FROZEN_THRESHOLDS_SHA,
)
from ph_catalog.primary_taxonomy_review import sha256_file
from ph_catalog.website_enricher import UnsafeWebsiteUrl, _validate_public_url
from ph_catalog.website_enrichment import extract_website_metadata

USER_AGENT_TOKEN = "PHCatalogEvidence"
USER_AGENT = f"{USER_AGENT_TOKEN}/1.0 (+https://github.com/Significant-Hobbies/ph-catalog)"
ROBOT_CACHE_SECONDS = 24 * 60 * 60


def _public_ip(records: list[tuple]) -> str:
    addresses = {ipaddress.ip_address(record[4][0]) for record in records}
    if not addresses or any(not address.is_global for address in addresses):
        raise httpcore.ConnectError("website address is not globally routable")
    return str(sorted(addresses, key=lambda item: (item.version, int(item)))[0])


class PublicAddressBackend:
    """Resolve at actual TCP connect and pin a validated public IP."""

    def __init__(self) -> None:
        self.backend = httpcore.AnyIOBackend()

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        try:
            records = await asyncio.get_running_loop().getaddrinfo(
                host, port, type=socket.SOCK_STREAM
            )
            address = _public_ip(records)
        except (OSError, ValueError) as exc:
            raise httpcore.ConnectError("public website hostname did not resolve") from exc
        return await self.backend.connect_tcp(
            address,
            port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )

    async def connect_unix_socket(self, *args, **kwargs):
        raise httpcore.ConnectError("Unix sockets are disabled for website evidence")


class PinnedPublicTransport(httpx.AsyncHTTPTransport):
    """HTTPX 0.28.1 / HTTPCore 1.0.9 transport with connect-time IP checks."""

    def __init__(self) -> None:
        limits = httpx.Limits(max_connections=4, max_keepalive_connections=0)
        super().__init__(trust_env=False, limits=limits, retries=0)
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=httpx.create_ssl_context(verify=True, trust_env=False),
            max_connections=4,
            max_keepalive_connections=0,
            network_backend=PublicAddressBackend(),
            retries=0,
        )


@dataclass(frozen=True)
class FetchConfig:
    max_pages: int = 25
    max_requests: int = 100
    max_redirects: int = 5
    max_page_bytes: int = 2_000_000
    max_robots_bytes: int = 512_000
    timeout_seconds: float = 15.0
    requests_per_second: float = 2.0

    def __post_init__(self) -> None:
        if (
            self.max_pages < 1
            or self.max_requests < 1
            or self.max_redirects < 0
            or self.max_page_bytes < 1
            or self.max_robots_bytes < 1
            or self.timeout_seconds <= 0
            or not 0 < self.requests_per_second <= 2
        ):
            raise ValueError("invalid public-evidence fetch limits")


@dataclass(frozen=True)
class FetchResponse:
    url: str
    status: int
    headers: dict[str, str]
    body: bytes
    outcome: str


def origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme.lower()}://{parts.netloc.lower()}"


def extra_page_fields(body: bytes) -> list[dict[str, str]]:
    """Keep a few bounded publisher or main-content evidence candidates."""
    tree = HTMLParser(body)
    fields: list[dict[str, str]] = []

    def add(field: str, source: str, value: object, *, minimum: int = 12) -> None:
        if not isinstance(value, str):
            return
        text = re.sub(r"\s+", " ", value).strip()
        if minimum <= len(text) <= 240 and not any(item["text"] == text for item in fields):
            fields.append({"field": field, "source": source, "text": text})

    og_title = tree.css_first('meta[property="og:title"]')
    if og_title:
        add("tagline", "og_title", og_title.attributes.get("content"))
    for script in tree.css('script[type="application/ld+json"]')[:5]:
        try:
            payload = orjson.loads(script.text())
        except orjson.JSONDecodeError:
            continue
        items = payload if isinstance(payload, list) else [payload]
        for item in items[:20]:
            if not isinstance(item, dict):
                continue
            nested = item.get("@graph")
            candidates = nested if isinstance(nested, list) else [item]
            for candidate in candidates[:20]:
                if not isinstance(candidate, dict):
                    continue
                types = candidate.get("@type")
                values = types if isinstance(types, list) else [types]
                if any(
                    isinstance(value, str) and value.casefold() == "organization"
                    for value in values
                ):
                    add("organization_slogan", "json_ld_organization", candidate.get("slogan"))
                    add(
                        "organization_description",
                        "json_ld_organization",
                        candidate.get("description"),
                        minimum=24,
                    )
    for section in tree.css("main section, article section")[:4]:
        add("feature_text", "main_section", section.text(separator=" ", strip=True), minimum=30)
    return fields[:8]


def secondary_link(body: bytes, page_url: str) -> str | None:
    """Pick one obvious same-origin about/features/product page, if present."""
    tree = HTMLParser(body)
    for anchor in tree.css("a[href]")[:40]:
        target = urljoin(page_url, anchor.attributes.get("href", ""))
        parts = urlsplit(target)
        if (
            origin(target) == origin(page_url)
            and target != page_url
            and re.match(r"^/(?:about|features|product)(?:/|$)", parts.path, re.I)
        ):
            return target
    return None


def _evidence_order(field: dict[str, str]) -> int:
    source = field["source"]
    if source.startswith("json_ld"):
        return 0
    if source.startswith("og_"):
        return 1
    if source == "main_section":
        return 4
    if source == "h1":
        return 3
    return 2


class WebsiteEvidenceFetcher:
    def __init__(self, client: httpx.AsyncClient, config: FetchConfig) -> None:
        self.client = client
        self.config = config
        self.rate = GlobalRateLimiter(config.requests_per_second, 0, 0)
        self.requests = 0
        self.robots_cache: dict[str, tuple[float, Protego | None, str]] = {}
        self.cooldowns: dict[str, float] = {}
        self.denied_origins: set[str] = set()

    async def _request(self, url: str, *, robots: bool) -> FetchResponse:
        await _validate_public_url(url)
        if self.requests >= self.config.max_requests:
            return FetchResponse(url, 0, {}, b"", "request_cap")
        if origin(url) in self.denied_origins or time.monotonic() < self.cooldowns.get(
            origin(url), 0
        ):
            return FetchResponse(url, 0, {}, b"", "origin_denied_or_cooling")
        await self.rate.wait()
        self.requests += 1
        try:
            async with self.client.stream("GET", url) as response:
                status = response.status_code
                headers = {key.lower(): value for key, value in response.headers.items()}
                final_url = str(response.url)
                if status in {401, 403}:
                    self.denied_origins.add(origin(url))
                if status in {429, 503} or (300 <= status < 400 and headers.get("retry-after")):
                    delay = min(86_400, retry_after_seconds(headers.get("retry-after"), 60))
                    self.cooldowns[origin(url)] = time.monotonic() + delay
                if response.is_redirect or status >= 400:
                    return FetchResponse(final_url, status, headers, b"", "http_status")
                if not robots and not any(
                    kind in headers.get("content-type", "").lower()
                    for kind in ("text/html", "application/xhtml+xml")
                ):
                    return FetchResponse(final_url, status, headers, b"", "non_html")
                limit = self.config.max_robots_bytes if robots else self.config.max_page_bytes
                length = headers.get("content-length", "")
                if length.isdigit() and int(length) > limit:
                    return FetchResponse(final_url, status, headers, b"", "too_large")
                chunks = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > limit:
                        return FetchResponse(final_url, status, headers, b"", "too_large")
                    chunks.append(chunk)
                return FetchResponse(final_url, status, headers, b"".join(chunks), "ok")
        except (httpx.TransportError, httpcore.NetworkError, httpcore.TimeoutException):
            return FetchResponse(url, 0, {}, b"", "network_error")

    async def _robots(self, url: str) -> tuple[Protego | None, str]:
        authority = origin(url)
        cached = self.robots_cache.get(authority)
        if cached and time.monotonic() - cached[0] <= ROBOT_CACHE_SECONDS:
            return cached[1], cached[2]
        current = authority + "/robots.txt"
        parser: Protego | None = None
        outcome = "robots_unavailable"
        for _ in range(max(5, self.config.max_redirects) + 1):
            try:
                response = await self._request(current, robots=True)
            except UnsafeWebsiteUrl:
                outcome = "robots_unsafe_url"
                break
            if 300 <= response.status < 400 and response.headers.get("location"):
                if response.headers.get("retry-after"):
                    outcome = "robots_retry_after_deferred"
                    break
                current = urljoin(response.url, response.headers["location"])
                continue
            if response.status == 200 and response.outcome == "ok":
                try:
                    parser = Protego.parse(response.body.decode("utf-8", errors="replace"))
                    outcome = "robots_rules"
                except ValueError:
                    outcome = "robots_parse_error"
            elif 400 <= response.status < 500 and response.status not in {401, 403, 429}:
                outcome = "robots_4xx_allow"
            else:
                outcome = f"robots_{response.outcome}_{response.status}"
            break
        self.robots_cache[authority] = (time.monotonic(), parser, outcome)
        return parser, outcome

    async def _allowed(self, url: str) -> tuple[bool, str]:
        rules, outcome = await self._robots(url)
        if outcome == "robots_4xx_allow":
            return True, outcome
        if rules is None:
            return False, outcome
        return rules.can_fetch(url, USER_AGENT_TOKEN), outcome

    async def fetch(
        self,
        slug: str,
        url: str,
        route_hash: str,
        text_hash: str,
        *,
        allow_secondary: bool = True,
    ) -> dict:
        current = url
        outcome = "redirect_limit"
        response: FetchResponse | None = None
        robots_outcome = None
        for _ in range(self.config.max_redirects + 1):
            try:
                allowed, robots_outcome = await self._allowed(current)
                if not allowed:
                    outcome = (
                        "unsafe_url"
                        if robots_outcome == "robots_unsafe_url"
                        else "robots_disallowed"
                    )
                    break
                response = await self._request(current, robots=False)
            except UnsafeWebsiteUrl:
                outcome = "unsafe_url"
                break
            if 300 <= response.status < 400 and response.headers.get("location"):
                if response.headers.get("retry-after"):
                    outcome = "retry_after_deferred"
                    break
                current = urljoin(response.url, response.headers["location"])
                continue
            outcome = response.outcome if response.outcome != "ok" else "fetched"
            break
        fields = []
        if response and outcome == "fetched" and 200 <= response.status < 300:
            metadata = extract_website_metadata(response.body)
            for field, candidates in (
                ("tagline", metadata.tagline_candidates),
                ("description", metadata.description_candidates),
            ):
                fields.extend(
                    {"field": field, "source": item.source, "text": item.value}
                    for item in candidates[:3]
                )
            fields.extend(extra_page_fields(response.body))
            fields.sort(key=_evidence_order)
            if not fields:
                outcome = "no_metadata"
        fetched_at = datetime.now(UTC).isoformat()
        response_sha = (
            hashlib.sha256(response.body).hexdigest() if response and response.body else None
        )
        for field in fields:
            field.update(
                {
                    "page_role": "primary" if allow_secondary else "secondary",
                    "source_url": response.url,
                    "fetched_at": fetched_at,
                    "response_sha256": response_sha,
                    "outcome": outcome,
                }
            )
        secondary = None
        if allow_secondary and response and outcome == "no_metadata":
            target = secondary_link(response.body, response.url)
            if target:
                second = await self.fetch(
                    slug,
                    target,
                    route_hash,
                    text_hash,
                    allow_secondary=False,
                )
                fields.extend(second["fields"])
                secondary = {
                    "requested_url": target,
                    "final_url": second["final_url"],
                    "outcome": second["outcome"],
                    "http_status": second["http_status"],
                    "robots_outcome": second["robots_outcome"],
                    "response_sha256": second["response_sha256"],
                }
                if fields:
                    outcome = "fetched_with_secondary"
        return {
            "slug": slug,
            "routing_output_sha256": route_hash,
            "product_text_sha256": text_hash,
            "requested_url": url,
            "final_url": response.url if response else None,
            "fetched_at": fetched_at,
            "outcome": outcome,
            "http_status": response.status if response else None,
            "robots_outcome": robots_outcome,
            "response_sha256": response_sha,
            "fields": fields,
            "secondary_page": secondary,
        }


def load_routes(
    routes: Path, manifest_path: Path, bundles: tuple[tuple[str, Path], ...]
) -> tuple[list[dict], dict]:
    """Reject altered routing outputs and every reserved review/holdout slug."""
    manifest = json.loads(manifest_path.read_text())
    excluded = reserved_slugs(bundles)
    if (
        manifest["output_sha256"] != sha256_file(routes)
        or manifest["routing_code_sha256"] != sha256_file(Path(primary_confidence_routing.__file__))
        or manifest["reserved_slug_exclusion_count"] != len(excluded)
        or manifest["routing_policy"] != ROUTING_POLICY
        or manifest["taxonomy_sha256"] != FROZEN_TAXONOMY_SHA
        or manifest["model_sha256"] != FROZEN_MODEL_SHA
        or manifest["thresholds_sha256"] != FROZEN_THRESHOLDS_SHA
        or manifest["candidate_manifest_sha256"] != FROZEN_CANDIDATE_MANIFEST_SHA
    ):
        raise ValueError("routing candidate provenance changed")
    candidates = []
    seen = set()
    for line in routes.read_text().splitlines():
        row = json.loads(line)
        slug = row["slug"]
        if slug in seen or slug in excluded:
            raise ValueError("duplicate or reserved product in routing output")
        seen.add(slug)
        if row["route"] and row["next_step"] == "website_evidence_candidate":
            website = row.get("website_url")
            host = urlsplit(website or "").hostname or ""
            if not website or host == "producthunt.com" or host.endswith(".producthunt.com"):
                raise ValueError("website route lacks an external public URL")
            candidates.append(row)
    return candidates, manifest


async def run(
    routes: Path,
    manifest_path: Path,
    output: Path,
    bundles: tuple[tuple[str, Path], ...],
    config: FetchConfig,
    *,
    client: httpx.AsyncClient | None = None,
) -> dict:
    candidates, route_manifest = load_routes(routes, manifest_path, bundles)
    result_manifest = output.with_suffix(output.suffix + ".manifest.json")
    partial = output.with_suffix(output.suffix + ".partial")
    if output.exists() or result_manifest.exists() or partial.exists():
        raise FileExistsError(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
            timeout=httpx.Timeout(config.timeout_seconds),
            transport=PinnedPublicTransport(),
            follow_redirects=False,
            trust_env=False,
        )
    fetcher = WebsiteEvidenceFetcher(client, config)
    counts: dict[str, int] = {}
    try:
        with partial.open("w") as handle:
            for row in candidates[: config.max_pages]:
                evidence = await fetcher.fetch(
                    row["slug"],
                    row["website_url"],
                    route_manifest["output_sha256"],
                    row["evidence_hash"],
                )
                handle.write(json.dumps(evidence, ensure_ascii=False) + "\n")
                counts[evidence["outcome"]] = counts.get(evidence["outcome"], 0) + 1
                if fetcher.requests >= config.max_requests:
                    break
        os.replace(partial, output)
    finally:
        if owns_client:
            await client.aclose()
    result = {
        "status": "development evidence candidate; independent validation pending",
        "routing_manifest_sha256": sha256_file(manifest_path),
        "routing_output_sha256": route_manifest["output_sha256"],
        "taxonomy_sha256": FROZEN_TAXONOMY_SHA,
        "model_sha256": FROZEN_MODEL_SHA,
        "thresholds_sha256": FROZEN_THRESHOLDS_SHA,
        "eligible_routes": len(candidates),
        "requested_page_cap": config.max_pages,
        "request_cap": config.max_requests,
        "actual_requests": fetcher.requests,
        "outcomes": counts,
        "output_sha256": sha256_file(output),
    }
    result_manifest.write_text(json.dumps(result, indent=2) + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--routes", type=Path, required=True)
    parser.add_argument("--route-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--exclude-bundle", nargs=2, action="append", required=True)
    parser.add_argument("--max-pages", type=int, default=25)
    parser.add_argument("--max-requests", type=int, default=100)
    args = parser.parse_args()
    report = asyncio.run(
        run(
            args.routes,
            args.route_manifest,
            args.output,
            tuple((name, Path(path)) for name, path in args.exclude_bundle),
            FetchConfig(max_pages=args.max_pages, max_requests=args.max_requests),
        )
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
