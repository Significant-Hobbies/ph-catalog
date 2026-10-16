"""Strong clean candidates stay local; only concrete uncertainty is routed."""

import json
import sys
from contextlib import nullcontext
from types import SimpleNamespace

import duckdb
import pytest

from ph_catalog import primary_confidence_routing as routing
from ph_catalog.primary_taxonomy import Taxonomy


class FakeModel:
    classes_ = ["alpha", "beta"]

    def predict_proba(self, texts):
        probabilities = []
        for text in texts:
            if "Alpha" in text:
                probabilities.append([0.9, 0.1])
            elif "Beta" in text:
                probabilities.append([0.1, 0.9])
            else:
                probabilities.append([0.55, 0.45])
        return probabilities


def _row(slug, tagline, description, *, website="https://example.com", entities=0):
    return {
        "slug": slug,
        "name": "Product",
        "tagline": tagline,
        "description": description,
        "website_url": website,
        "has_external_website": bool(website),
        "entity_count": entities,
        "trusted_label_count": 0,
    }


def test_strong_clean_candidate_accepts_without_ner_labels():
    row = _row("clean", "Alpha workflow for creating plans", "Alpha workflow for managing work")
    result = routing.route_candidate(
        row,
        [0.9, 0.1],
        ["alpha", "beta"],
        {"confidence": 0.6, "margin": 0},
        fields_disagree=False,
    )
    assert result["primary_category"] == "alpha"
    assert result["route"] is False
    assert result["reasons"] == []
    assert result["next_step"] == "candidate_accept"


def test_weak_or_poor_copy_routes_with_reasons_and_abstention():
    weak = _row("weak", "", "", website="")
    result = routing.route_candidate(
        weak,
        [0.55, 0.45],
        ["alpha", "beta"],
        {"confidence": 0.6, "margin": 0},
        fields_disagree=False,
    )
    assert result["primary_category"] is None
    assert result["reasons"] == [
        "insufficient_source_text",
        "classifier_abstained",
        "no_auxiliary_labels",
    ]
    assert result["next_step"] == "non_web_review"

    placeholder = _row("placeholder", "Coming soon", "Alpha product under construction")
    result = routing.route_candidate(
        placeholder,
        [0.9, 0.1],
        ["alpha", "beta"],
        {"confidence": 0.6, "margin": 0},
        fields_disagree=False,
    )
    assert result["route"] is True
    assert "placeholder_copy" in result["reasons"]
    assert result["next_step"] == "website_evidence_candidate"


def test_batch_field_disagreement_is_conservative():
    model = FakeModel()
    rows = [
        _row(
            "different", "Alpha workflow for creating plans", "Beta workflow for managing projects"
        ),
        _row("same", "Alpha workflow for creating plans", "Alpha workflow for managing projects"),
        _row("short", "Alpha", "Beta"),
    ]
    assert routing.field_disagreements(model, rows) == [False, False, False]
    rows[0]["description"] += " and helping groups work together with important tasks"
    rows[1]["description"] += " and helping groups work together with important tasks"
    assert routing.field_disagreements(model, rows) == [True, False, False]


def test_mart_router_streams_candidates_and_respects_exclusions(tmp_path, monkeypatch):
    taxonomy = Taxonomy(
        version="v1",
        source_snapshot="test",
        category_names={"alpha": "Alpha", "beta": "Beta"},
        source_map={},
        rationales={},
        sha256="test-taxonomy-sha",
    )
    monkeypatch.setattr(routing, "FROZEN_TAXONOMY_SHA", taxonomy.sha256)
    monkeypatch.setattr(routing, "load_taxonomy", lambda _path: taxonomy)
    monkeypatch.setattr(
        routing,
        "load_candidate",
        lambda _taxonomy, _path: (
            FakeModel(),
            {"confidence": 0.6, "margin": 0},
            {"model_sha256": "m", "thresholds_sha256": "t"},
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "threadpoolctl",
        SimpleNamespace(threadpool_limits=lambda **_kwargs: nullcontext()),
    )
    mart = tmp_path / "mart.duckdb"
    with duckdb.connect(str(mart)) as connection:
        connection.execute(
            """
            CREATE TABLE product_facts (
                slug VARCHAR, name VARCHAR, tagline VARCHAR,
                description VARCHAR, website_url VARCHAR,
                has_external_website BOOLEAN,
                entity_count INTEGER, trusted_label_count INTEGER
            )
            """
        )
        connection.executemany(
            "INSERT INTO product_facts VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    "a",
                    "A",
                    "Alpha workflow for creating plans",
                    "Alpha workflow for managing work",
                    "https://example.com",
                    True,
                    0,
                    0,
                ),
                ("b", "B", "", "", None, False, 0, 0),
                (
                    "c",
                    "C",
                    "Beta workflow for creating plans",
                    "Beta workflow for managing work",
                    "https://example.com",
                    True,
                    1,
                    1,
                ),
            ],
        )
    output = tmp_path / "routed.jsonl"
    report = routing.route_mart(
        mart,
        tmp_path / "taxonomy.json",
        tmp_path / "candidate",
        output,
        batch_size=2,
        excluded_slugs={"c"},
    )
    rows = [json.loads(line) for line in output.read_text().splitlines()]
    assert report["seen"] == 3
    assert report["excluded"] == 1
    assert report["written"] == 2
    assert report["candidate_accept"] == 1
    assert report["routed"] == 1
    assert [row["slug"] for row in rows] == ["a", "b"]
    assert "source_categories" not in output.read_text()
    assert json.loads((tmp_path / "routed.jsonl.manifest.json").read_text()) == report
    with pytest.raises(FileExistsError):
        routing.route_mart(
            mart,
            tmp_path / "taxonomy.json",
            tmp_path / "candidate",
            output,
            excluded_slugs={"c"},
        )


def test_reservation_exclusions_require_pinned_keys(tmp_path, monkeypatch):
    import hashlib

    bundles = []
    pins = {}
    for name in ("main", "home", "sparse"):
        bundle = tmp_path / name
        bundle.mkdir()
        key = json.dumps([{"slug": name}]).encode()
        (bundle / "source-key.json").write_bytes(key)
        (bundle / "manifest.json").write_text(
            json.dumps({"file_sha256": {"source-key.json": hashlib.sha256(key).hexdigest()}})
        )
        pins[name] = routing.sha256_file(bundle / "manifest.json")
        bundles.append((name, bundle))
    monkeypatch.setattr(routing, "FROZEN_SAMPLE_MANIFESTS", pins)
    assert routing.reserved_slugs(tuple(bundles)) == {"main", "home", "sparse"}
    with pytest.raises(ValueError, match="all three"):
        routing.reserved_slugs(tuple(bundles[:2]))
    (bundles[0][1] / "source-key.json").write_text("[]")
    with pytest.raises(ValueError, match="source key changed"):
        routing.reserved_slugs(tuple(bundles))
