"""Stage 5 handoff cannot bypass unfetched routes or alter pinned evidence."""

import hashlib
import json
from pathlib import Path

import pytest

from ph_catalog import primary_confidence_routing as routing
from ph_catalog import primary_stage5_handoff as handoff
from ph_catalog import primary_website_evidence as website


def _write_json(path, value):
    path.write_text(json.dumps(value) + "\n")


def _fixture(tmp_path, monkeypatch):
    monkeypatch.setattr(website, "reserved_slugs", lambda _bundles: {"reserved"})
    routes = tmp_path / "routes.jsonl"
    route_rows = [
        {
            "slug": "web",
            "route": True,
            "next_step": "website_evidence_candidate",
            "website_url": "https://example.com/",
            "evidence_hash": "text-web",
        },
        {
            "slug": "no-web",
            "route": True,
            "next_step": "non_web_review",
            "website_url": None,
            "evidence_hash": "text-non-web",
        },
        {
            "slug": "unfetched",
            "route": True,
            "next_step": "website_evidence_candidate",
            "website_url": "https://other.example/",
            "evidence_hash": "text-unfetched",
        },
        {
            "slug": "accepted",
            "route": False,
            "next_step": "candidate_accept",
            "website_url": "https://accepted.example/",
            "evidence_hash": "text-accepted",
        },
    ]
    routes.write_text("".join(json.dumps(row) + "\n" for row in route_rows))
    route_manifest = tmp_path / "routes.jsonl.manifest.json"
    route_hash = hashlib.sha256(routes.read_bytes()).hexdigest()
    _write_json(
        route_manifest,
        {
            "output_sha256": route_hash,
            "routing_code_sha256": website.sha256_file(Path(routing.__file__)),
            "reserved_slug_exclusion_count": 1,
            "routing_policy": routing.ROUTING_POLICY,
            "taxonomy_sha256": handoff.FROZEN_TAXONOMY_SHA,
            "model_sha256": handoff.FROZEN_MODEL_SHA,
            "thresholds_sha256": handoff.FROZEN_THRESHOLDS_SHA,
            "candidate_manifest_sha256": website.FROZEN_CANDIDATE_MANIFEST_SHA,
        },
    )
    evidence = tmp_path / "evidence.jsonl"
    evidence_row = {
        "slug": "web",
        "routing_output_sha256": route_hash,
        "product_text_sha256": "text-web",
        "requested_url": "https://example.com/",
        "final_url": "https://example.com/",
        "outcome": "fetched",
        "response_sha256": "page-hash",
        "fields": [
            {
                "page_role": "primary",
                "source_url": "https://example.com/",
                "response_sha256": "page-hash",
                "fetched_at": "2026-10-16T00:00:00+00:00",
                "outcome": "fetched",
                "text": "A useful product description",
            }
        ],
    }
    evidence.write_text(json.dumps(evidence_row) + "\n")
    evidence_manifest = tmp_path / "evidence.jsonl.manifest.json"
    _write_json(
        evidence_manifest,
        {
            "output_sha256": hashlib.sha256(evidence.read_bytes()).hexdigest(),
            "routing_manifest_sha256": hashlib.sha256(route_manifest.read_bytes()).hexdigest(),
            "routing_output_sha256": route_hash,
            "taxonomy_sha256": handoff.FROZEN_TAXONOMY_SHA,
            "model_sha256": handoff.FROZEN_MODEL_SHA,
            "thresholds_sha256": handoff.FROZEN_THRESHOLDS_SHA,
            "eligible_routes": 2,
        },
    )
    return routes, route_manifest, evidence, evidence_manifest


def test_handoff_is_immutable_and_skips_accepted_and_unfetched(tmp_path, monkeypatch):
    paths = _fixture(tmp_path, monkeypatch)
    output = tmp_path / "handoff.jsonl"
    report = handoff.run(*paths, output, ())
    rows = [json.loads(line) for line in output.read_text().splitlines()]
    assert [row["slug"] for row in rows] == ["web", "no-web"]
    assert all(row["unresolved"] for row in rows)
    assert rows[0]["reason"] == "website_evidence_pending_adjudication"
    assert rows[0]["website_field_count"] == 1
    assert rows[1]["reason"] == "no_external_website"
    assert rows[1]["website_evidence_record_sha256"] is None
    assert report["counts"] == {
        "unresolved": 2,
        "non_web": 1,
        "website_evidence": 1,
        "awaiting_website": 1,
    }
    assert report["output_sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
    with pytest.raises(FileExistsError):
        handoff.run(*paths, output, ())


def test_handoff_rejects_changed_evidence_and_field_provenance(tmp_path, monkeypatch):
    routes, route_manifest, evidence, evidence_manifest = _fixture(tmp_path, monkeypatch)
    output = tmp_path / "handoff.jsonl"
    evidence.write_text(evidence.read_text().replace("page-hash", "changed"))
    with pytest.raises(ValueError, match="manifest"):
        handoff.run(routes, route_manifest, evidence, evidence_manifest, output, ())
    manifest = json.loads(evidence_manifest.read_text())
    manifest["output_sha256"] = hashlib.sha256(evidence.read_bytes()).hexdigest()
    _write_json(evidence_manifest, manifest)
    row = json.loads(evidence.read_text())
    row["fields"][0]["response_sha256"] = "mismatched"
    evidence.write_text(json.dumps(row) + "\n")
    manifest["output_sha256"] = hashlib.sha256(evidence.read_bytes()).hexdigest()
    _write_json(evidence_manifest, manifest)
    with pytest.raises(ValueError, match="field lacks matching"):
        handoff.run(routes, route_manifest, evidence, evidence_manifest, output, ())
