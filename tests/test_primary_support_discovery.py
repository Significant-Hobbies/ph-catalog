"""Support discovery reserves only disjoint blind heldout text."""

import json
from pathlib import Path

from ph_catalog import primary_home_discovery as home
from ph_catalog.primary_support_discovery import select_support_discovery

TAXONOMY = Path(__file__).resolve().parents[1] / "taxonomy" / "v1.json"


def test_five_group_support_sample_has_no_development_or_query_leak(monkeypatch, tmp_path):
    products = tmp_path / "products.csv"
    products.write_text("verified archive")
    prior = tmp_path / "prior-key.json"
    prior.write_text(json.dumps([{"slug": "prior"}]))
    rows = [
        ("prior", "Project Management", "Team management", "Prior sample"),
        ("business", "Project Management", "Team workflow", "Plans work"),
        ("health", "Sleep Tracker", "Improve sleep", "Tracks rest"),
        ("security", "Password Manager", "Protect accounts", "Stores passwords"),
        ("travel", "Trip Planner", "Plan journeys", "Build itineraries"),
        ("work", "Resume Builder", "Find a job", "Create a CV"),
    ]
    monkeypatch.setattr(home, "text_rows", lambda _path: iter(rows))
    blind, key, manifest = select_support_discovery(
        products, TAXONOMY, (prior,), seed="fixed", heldout_per_group=1
    )
    assert manifest["selected"] == {
        "development": 0,
        "holdout_random": 0,
        "holdout_stratified": 5,
    }
    assert manifest["excluded_distinct_slugs"] == 1
    assert {entry["group"] for entry in key} == set(manifest["title_patterns"])
    assert "prior" not in {entry["slug"] for entry in key}
    assert all(
        set(entry) == {"review_id", "name", "tagline", "description"}
        for entry in blind["holdout_stratified"]
    )
