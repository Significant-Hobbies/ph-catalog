"""Supplemental social/data discovery stays blinded and disjoint."""

import json
from pathlib import Path

import pytest

from ph_catalog import primary_home_discovery as base
from ph_catalog import primary_sparse_discovery as discovery
from ph_catalog.primary_label_protocol import write_bundle

TAXONOMY = Path(__file__).resolve().parents[1] / "taxonomy" / "v1.json"


def test_sparse_discovery_reserves_text_only_candidates(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    products = tmp_path / "products.csv"
    products.write_text("verified archive")
    prior = tmp_path / "prior-key.json"
    prior.write_text(json.dumps([{"slug": "old-friends"}]))
    rows = [
        ("old-friends", "Friendship App", "Make new friends", "Previously sampled"),
        ("friends-a", "Friendship App", "Make new friends", "Meet people"),
        ("friends-b", "People", "Social networking for neighbours", "Meet people"),
        ("community-a", "Group Hub", "Online community platform", "Join groups"),
        ("community-b", "Circle", "Group chat for families", "Share messages"),
        ("bi-a", "Report Hub", "Business intelligence dashboard", "Explore data"),
        ("bi-b", "Viz", "Data visualization for teams", "Plot metrics"),
        ("metrics-a", "Insights", "Data analytics for stores", "Analyze sales"),
        ("metrics-b", "Metrics", "Monitor business metrics", "Measure change"),
    ]
    monkeypatch.setattr(base, "text_rows", lambda _path: iter(rows))
    options = {"seed": "fixed", "development_per_group": 1, "heldout_per_group": 1}
    blind, key, manifest = discovery.select_sparse_discovery(
        products, TAXONOMY, (prior,), **options
    )
    assert (blind, key, manifest) == discovery.select_sparse_discovery(
        products, TAXONOMY, (prior,), **options
    )
    assert manifest["selected"] == {
        "development": 4,
        "holdout_random": 0,
        "holdout_stratified": 4,
    }
    assert manifest["excluded_distinct_slugs"] == 1
    assert len({record["slug"] for record in key}) == 8
    assert "old-friends" not in {record["slug"] for record in key}
    assert all(
        set(record) == {"review_id", "name", "tagline", "description"}
        for split in blind.values()
        for record in split
    )
    assert all(set(record) == {"review_id", "slug", "split", "group"} for record in key)
    output = tmp_path / "bundle"
    write_bundle(output, blind, key, manifest)
    assert "source_categories" not in (output / "source-key.json").read_text()
