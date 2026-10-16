"""Routed-only public evidence obeys robots, caps, and immutable provenance."""

import asyncio
import hashlib
import json
import socket
from pathlib import Path

import httpcore
import httpx
import pytest

from ph_catalog import primary_confidence_routing as routing
from ph_catalog import primary_website_evidence as evidence


def _dns_record(ip):
    return (None, None, None, None, (ip, 443))


def test_connect_time_dns_pinning_rejects_any_private_address():
    assert evidence._public_ip([_dns_record("93.184.215.14")]) == "93.184.215.14"
    with pytest.raises(httpcore.ConnectError, match="globally routable"):
        evidence._public_ip([_dns_record("93.184.215.14"), _dns_record("127.0.0.1")])
    with pytest.raises(httpcore.ConnectError, match="globally routable"):
        evidence._public_ip([_dns_record("169.254.169.254")])


def test_backend_connects_only_to_resolved_public_ip(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [_dns_record("93.184.215.14")],
    )

    class Recorder:
        called = None

        async def connect_tcp(self, host, port, **_kwargs):
            self.called = (host, port)
            return "fake-stream"

    async def scenario():
        backend = evidence.PublicAddressBackend()
        recorder = Recorder()
        backend.backend = recorder
        result = await backend.connect_tcp("example.com", 443)
        return result, recorder.called

    result, called = asyncio.run(scenario())
    assert result == "fake-stream"
    assert called == ("93.184.215.14", 443)


def test_only_pinned_routed_external_rows_are_admitted(tmp_path, monkeypatch):
    monkeypatch.setattr(evidence, "reserved_slugs", lambda _bundles: {"reserved"})
    rows = [
        {
            "slug": "route",
            "route": True,
            "next_step": "website_evidence_candidate",
            "website_url": "https://example.com/page",
            "evidence_hash": "text-hash",
        },
        {
            "slug": "accepted",
            "route": False,
            "next_step": "candidate_accept",
            "website_url": "https://example.com/accepted",
        },
    ]
    route_path = tmp_path / "routes.jsonl"
    route_path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    manifest = {
        "output_sha256": hashlib.sha256(route_path.read_bytes()).hexdigest(),
        "routing_code_sha256": evidence.sha256_file(Path(routing.__file__)),
        "reserved_slug_exclusion_count": 1,
        "routing_policy": routing.ROUTING_POLICY,
        "taxonomy_sha256": evidence.FROZEN_TAXONOMY_SHA,
        "model_sha256": evidence.FROZEN_MODEL_SHA,
        "thresholds_sha256": evidence.FROZEN_THRESHOLDS_SHA,
        "candidate_manifest_sha256": evidence.FROZEN_CANDIDATE_MANIFEST_SHA,
    }
    manifest_path = tmp_path / "routes.manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    selected, _ = evidence.load_routes(route_path, manifest_path, ())
    assert [row["slug"] for row in selected] == ["route"]
    rows.append({"slug": "reserved", "route": False, "next_step": "candidate_accept"})
    route_path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    manifest["output_sha256"] = hashlib.sha256(route_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="reserved"):
        evidence.load_routes(route_path, manifest_path, ())


def test_robots_rules_and_retry_after_block_without_fetching_page(monkeypatch):
    async def allow_test_url(_url):
        return None

    monkeypatch.setattr(evidence, "_validate_public_url", allow_test_url)
    seen = []

    def handler(request):
        seen.append(str(request.url))
        if request.url.host == "cool.example" and request.url.path == "/robots.txt":
            return httpx.Response(503, headers={"Retry-After": "3600"})
        if request.url.path == "/robots.txt":
            return httpx.Response(
                200,
                text="User-agent: PHCatalogEvidence\nDisallow: /private\nAllow: /public",
            )
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text=(
                "<html><meta name='description' "
                "content='A useful workflow for readers every day'></html>"
            ),
        )

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            fetcher = evidence.WebsiteEvidenceFetcher(client, evidence.FetchConfig())

            async def no_wait():
                return None

            fetcher.rate.wait = no_wait
            blocked = await fetcher.fetch("private", "https://example.com/private", "route", "text")
            allowed = await fetcher.fetch("public", "https://example.com/public", "route", "text")
            cooling = await fetcher.fetch("cool", "https://cool.example/page", "route", "text")
            return blocked, allowed, cooling, fetcher.requests

    blocked, allowed, cooling, requests = asyncio.run(scenario())
    assert blocked["outcome"] == "robots_disallowed"
    assert allowed["outcome"] == "fetched"
    assert allowed["fields"][0]["source"] == "meta_description"
    assert cooling["outcome"] == "robots_disallowed"
    assert "https://example.com/private" not in seen
    assert "https://cool.example/page" not in seen
    assert requests == 3  # two robots requests and one allowed HTML page


def test_media_header_prevents_body_read_and_redirect_rechecks_url(monkeypatch):
    async def validate(url):
        if "private.local" in url:
            raise evidence.UnsafeWebsiteUrl("private address")

    monkeypatch.setattr(evidence, "_validate_public_url", validate)

    class ForbiddenBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            raise AssertionError("media bytes were read")
            yield b""

    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        if request.url.path == "/redirect":
            return httpx.Response(302, headers={"Location": "http://private.local/secret"})
        return httpx.Response(
            200, headers={"Content-Type": "application/pdf"}, stream=ForbiddenBody()
        )

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            fetcher = evidence.WebsiteEvidenceFetcher(client, evidence.FetchConfig())

            async def no_wait():
                return None

            fetcher.rate.wait = no_wait
            media = await fetcher.fetch("media", "https://example.com/media", "route", "text")
            unsafe = await fetcher.fetch("unsafe", "https://example.com/redirect", "route", "text")
            return media, unsafe

    media, unsafe = asyncio.run(scenario())
    assert media["outcome"] == "non_html"
    assert media["fields"] == []
    assert unsafe["outcome"] == "unsafe_url"


def test_redirect_retry_after_defers_follow_up(monkeypatch):
    async def allow_test_url(_url):
        return None

    monkeypatch.setattr(evidence, "_validate_public_url", allow_test_url)
    seen = []

    def handler(request):
        seen.append(str(request.url))
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        if request.url.path == "/start":
            return httpx.Response(302, headers={"Location": "/after", "Retry-After": "120"})
        raise AssertionError("redirect was followed despite Retry-After")

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            fetcher = evidence.WebsiteEvidenceFetcher(client, evidence.FetchConfig())

            async def no_wait():
                return None

            fetcher.rate.wait = no_wait
            return await fetcher.fetch("defer", "https://example.com/start", "route", "text")

    result = asyncio.run(scenario())
    assert result["outcome"] == "retry_after_deferred"
    assert "https://example.com/after" not in seen


def test_one_justified_same_origin_secondary_page_with_field_provenance(monkeypatch):
    async def allow_test_url(_url):
        return None

    monkeypatch.setattr(evidence, "_validate_public_url", allow_test_url)
    seen = []

    def handler(request):
        seen.append(str(request.url))
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        if request.url.path == "/":
            return httpx.Response(
                200,
                headers={"content-type": "text/html"},
                text=(
                    "<a href='https://elsewhere.example/features'>Other</a>"
                    "<a href='/features'>Features</a>"
                ),
            )
        if request.url.path == "/features":
            return httpx.Response(
                200,
                headers={"content-type": "text/html"},
                text=(
                    "<meta name='description' "
                    "content='Plan your weekly reading and save useful notes in one place'>"
                    "<a href='/about'>About</a>"
                ),
            )
        raise AssertionError("a third page was fetched")

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            fetcher = evidence.WebsiteEvidenceFetcher(client, evidence.FetchConfig())

            async def no_wait():
                return None

            fetcher.rate.wait = no_wait
            return await fetcher.fetch("reader", "https://example.com/", "route", "text")

    result = asyncio.run(scenario())
    assert result["outcome"] == "fetched_with_secondary"
    assert result["secondary_page"]["requested_url"] == "https://example.com/features"
    assert len(result["fields"]) == 2  # description can also be a tagline candidate
    assert all(field["page_role"] == "secondary" for field in result["fields"])
    assert all(
        field["source_url"] == "https://example.com/features"
        and field["response_sha256"] == result["secondary_page"]["response_sha256"]
        and field["fetched_at"]
        and field["outcome"] == "fetched"
        for field in result["fields"]
    )
    assert seen == [
        "https://example.com/robots.txt",
        "https://example.com/",
        "https://example.com/features",
    ]


def test_routed_run_writes_immutable_evidence_and_manifest(tmp_path, monkeypatch):
    async def allow_test_url(_url):
        return None

    monkeypatch.setattr(evidence, "_validate_public_url", allow_test_url)
    monkeypatch.setattr(evidence, "reserved_slugs", lambda _bundles: {"reserved"})
    row = {
        "slug": "route",
        "route": True,
        "next_step": "website_evidence_candidate",
        "website_url": "https://example.com/",
        "evidence_hash": "original-text-hash",
    }
    routes = tmp_path / "routes.jsonl"
    routes.write_text(json.dumps(row) + "\n")
    route_manifest = tmp_path / "routes.manifest.json"
    route_manifest.write_text(
        json.dumps(
            {
                "output_sha256": hashlib.sha256(routes.read_bytes()).hexdigest(),
                "routing_code_sha256": evidence.sha256_file(Path(routing.__file__)),
                "reserved_slug_exclusion_count": 1,
                "routing_policy": routing.ROUTING_POLICY,
                "taxonomy_sha256": evidence.FROZEN_TAXONOMY_SHA,
                "model_sha256": evidence.FROZEN_MODEL_SHA,
                "thresholds_sha256": evidence.FROZEN_THRESHOLDS_SHA,
                "candidate_manifest_sha256": evidence.FROZEN_CANDIDATE_MANIFEST_SHA,
            }
        )
    )

    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text=(
                "<meta name='description' content='A useful workflow for readers every day'>"
                "<meta property='og:title' content='Organize useful work together'>"
                '<script type="application/ld+json">'
                '{"@type":"Organization","description":"A team helping people organize work."}'
                "</script><main><section><h2>Work better</h2>"
                "<p>Track team tasks and document decisions in one place.</p></section></main>"
            ),
        )

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await evidence.run(
                routes,
                route_manifest,
                tmp_path / "evidence.jsonl",
                (),
                evidence.FetchConfig(max_pages=1, max_requests=2),
                client=client,
            )

    report = asyncio.run(scenario())
    output = tmp_path / "evidence.jsonl"
    record = json.loads(output.read_text())
    assert report["actual_requests"] == 2
    assert report["output_sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
    assert record["product_text_sha256"] == "original-text-hash"
    assert record["requested_url"] == "https://example.com/"
    assert record["fields"][0]["source"] == "json_ld_organization"
    assert [evidence._evidence_order(field) for field in record["fields"]] == sorted(
        evidence._evidence_order(field) for field in record["fields"]
    )
    assert {field["source"] for field in record["fields"]} >= {
        "json_ld_organization",
        "og_title",
        "main_section",
    }
    assert all(
        field["source_url"] == record["final_url"]
        and field["fetched_at"] == record["fetched_at"]
        and field["response_sha256"] == record["response_sha256"]
        for field in record["fields"]
    )
    assert (tmp_path / "evidence.jsonl.manifest.json").exists()
    with pytest.raises(FileExistsError):
        asyncio.run(scenario())
