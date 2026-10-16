"""Tests for conservative primary source mapping."""

import csv
from pathlib import Path

import pytest

from ph_catalog.primary_taxonomy import load_taxonomy, primary_from_sources
from ph_catalog.primary_taxonomy_audit import audit

TAXONOMY = Path(__file__).resolve().parents[1] / "taxonomy" / "v1-candidate.json"


def test_source_evidence_must_agree() -> None:
    taxonomy = load_taxonomy(TAXONOMY)
    assert primary_from_sources(["SEO tools", "Email marketing"], taxonomy) == (
        "marketing_sales",
        "unique_source_mapping",
    )
    assert primary_from_sources(["SEO tools", "Medical"], taxonomy) == (
        None,
        "conflicting_source_categories",
    )
    assert primary_from_sources(["AI Chatbots", "Chrome Extensions"], taxonomy) == (
        None,
        "no_unambiguous_source_category",
    )


def test_duplicate_source_fails_closed(tmp_path: Path) -> None:
    content = TAXONOMY.read_text()
    duplicate = content.replace(
        '"source_categories": ["Project management software"',
        '"source_categories": ["SEO tools", "Project management software"',
        1,
    )
    path = tmp_path / "taxonomy.json"
    path.write_text(duplicate)
    with pytest.raises(ValueError, match="duplicate"):
        load_taxonomy(path)


def test_audit_keeps_unknown_and_conflicting_products_unlabeled(tmp_path: Path) -> None:
    products = tmp_path / "products.csv"
    with products.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["slug", "categories"])
        writer.writerow(["one", "[SEO tools,Email marketing]"])
        writer.writerow(["conflict", "[SEO tools,Medical]"])
        writer.writerow(["unknown", "[AI Chatbots]"])
        writer.writerow(["empty", "[]"])
    report = audit(TAXONOMY, products, require_complete_source_snapshot=False)
    assert report["categorized_products"] == 3
    assert report["product_outcomes"] == {
        "conflicting_source_categories": 1,
        "no_unambiguous_source_category": 2,
        "unique_source_mapping": 1,
    }
    assert report["uniquely_labeled_products_by_category"] == {"marketing_sales": 1}
