"""Sparse-class discovery keeps source tags sealed and prior samples disjoint."""

import json
from pathlib import Path

import pytest

from ph_catalog import primary_home_discovery as discovery
from ph_catalog.primary_label_protocol import write_bundle

TAXONOMY = Path(__file__).resolve().parents[1] / "taxonomy" / "v1.json"


def test_text_discovery_is_blind_deterministic_and_disjoint(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    products = tmp_path / "products.csv"
    products.write_text("verified archive")
    prior = tmp_path / "prior-key.json"
    prior.write_text(json.dumps([{"slug": "old-apartment"}]))
    rows = [
        ("old-apartment", "Apartment Finder", "Find a home", "Prior sample"),
        ("apartment", "Apartment Finder", "Find a place", "Search homes"),
        ("roommate", "Roommate Match", "Find a roommate", "Share a home"),
        ("interior", "Interior Design", "Design your living room", "Plan a home"),
        ("repair", "Home Repair", "Fix your house", "Organize repairs"),
        ("recipe", "Recipe Book", "Cook dinner", "Save family recipes"),
        ("garden", "Gardening Helper", "Grow plants", "Plan a garden"),
        ("household", "Household Planner", "Family life", "Share chores"),
        ("parenting", "Parenting Guide", "Raise children", "Plan family life"),
    ]
    monkeypatch.setattr(discovery, "text_rows", lambda _path: iter(rows))
    args = (products, TAXONOMY, (prior,))
    options = {"seed": "fixed", "development_per_group": 1, "heldout_per_group": 1}
    blind, key, manifest = discovery.select_home_discovery(*args, **options)
    assert (blind, key, manifest) == discovery.select_home_discovery(*args, **options)
    assert manifest["taxonomy_version"] == "v1"
    assert manifest["excluded_distinct_slugs"] == 1
    assert manifest["selected"] == {
        "development": 4,
        "holdout_random": 0,
        "holdout_stratified": 4,
    }
    assert len({record["slug"] for record in key}) == 8
    assert "old-apartment" not in {record["slug"] for record in key}
    assert all(
        set(record) == {"review_id", "name", "tagline", "description"}
        for split in blind.values()
        for record in split
    )
    assert all(set(record) == {"review_id", "slug", "split", "group"} for record in key)

    output = tmp_path / "bundle"
    write_bundle(output, blind, key, manifest)
    assert "source_categories" not in (output / "source-key.json").read_text()
    with pytest.raises(FileExistsError):
        write_bundle(output, blind, key, manifest)
