"""The review sampler must be reproducible and keep the source answer key separate."""

import hashlib

import pytest

from ph_catalog import primary_taxonomy_review as review
from ph_catalog.primary_taxonomy import Taxonomy


def test_review_sampling_is_blinded_deterministic_and_excludes_conflicts(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    products = tmp_path / "products.csv"
    products.write_text("source snapshot")
    taxonomy = Taxonomy(
        version="v1-candidate",
        source_snapshot="test",
        category_names={"developer_tools": "Developer tools", "design_creative": "Design"},
        source_map={
            "Code editors": "developer_tools",
            "Git clients": "developer_tools",
            "Art": "design_creative",
        },
        rationales={},
        sha256="taxonomy-test-sha",
    )
    rows = [
        ("a", "A", "build code", "editor", ["Code editors"]),
        ("b", "B", "manage git", "git client", ["Code editors", "Git clients"]),
        ("c", "C", "draw", "art tool", ["Art"]),
        ("d", "D", "unknown", "conflicting source", ["Code editors", "Art"]),
    ]
    monkeypatch.setattr(review, "rows_from_csv", lambda _path: iter(rows))

    first = review.select_review(
        products, taxonomy, seed="fixed", per_class=1, rare_per_class=1, rare_threshold=1
    )
    second = review.select_review(
        products, taxonomy, seed="fixed", per_class=1, rare_per_class=1, rare_threshold=1
    )
    assert first == second
    blind, key, manifest = first
    assert len(blind) == len(key) == manifest["review_count"]
    assert "d" not in {entry["slug"] for entry in key}
    assert "b" in {entry["slug"] for entry in key}  # rare Git clients stratum
    assert all(
        "source_categories" not in entry and "source_mapping" not in entry for entry in blind
    )
    assert all(entry["review"]["status"] == "unreviewed" for entry in blind)
    assert manifest["products_csv_sha256"] == hashlib.sha256(b"source snapshot").hexdigest()
    assert manifest["rare_source_values"] == 1
