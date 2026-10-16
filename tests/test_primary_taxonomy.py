"""Tests for conservative primary source mapping."""

import csv
import json
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


@pytest.mark.parametrize(
    "source",
    [
        "Productivity",
        "productivity",
        "No-code Platforms",
        "No-Code",
        "no-code",
        "Newsletter platforms",
        "Video hosting platforms",
        "AI notetakers",
        "Microblogging platforms",
        "Figma Plugins",
        "AI Generative Media",
        "Books",
        "sports",
        "Email",
        "Telegram",
        "Space design apps",
        "Marketplace sites",
        "Apps for kids",
        "Real estate",
        "Time tracking apps",
        "time-tracking",
        "Furniture",
        "Writing assistants",
        "Legal services",
        "legal",
        "Music",
        "music",
        "Meetings",
        "meetings",
        "Writing",
        "writing",
        "Education",
        "education",
        "sales",
        "Sales",
        "advertising",
        "Advertising",
        "delivery",
        "books",
        "cookbooks",
        "Art",
        "art",
        "Payroll software",
        "Blogging platforms",
        "CRM software",
        "crm",
        "Shopify Apps",
        "Twitter apps",
        "NFT creation tools",
    ],
)
def test_ambiguous_source_is_unmapped(source: str) -> None:
    taxonomy = load_taxonomy(TAXONOMY)
    assert primary_from_sources([source], taxonomy) == (None, "no_unambiguous_source_category")


@pytest.mark.parametrize("source", ["Project management software", "SEO tools"])
def test_duplicate_source_fails_closed(tmp_path: Path, source: str) -> None:
    document = json.loads(TAXONOMY.read_text())
    document["categories"][0]["source_categories"].append(source)
    path = tmp_path / "taxonomy.json"
    path.write_text(json.dumps(document))
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


def test_case_equivalent_values_cannot_map_to_different_classes(tmp_path: Path) -> None:
    document = json.loads(TAXONOMY.read_text())
    developer_tools = next(c for c in document["categories"] if c["id"] == "developer_tools")
    developer_tools["source_categories"].append("PROJECT MANAGEMENT SOFTWARE")
    path = tmp_path / "taxonomy.json"
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError, match="case-equivalent source categories map differently"):
        load_taxonomy(path)


def test_audit_rejects_mapped_and_unmapped_case_twins(tmp_path: Path) -> None:
    document = json.loads(TAXONOMY.read_text())
    media = next(c for c in document["categories"] if c["id"] == "media_entertainment")
    media["source_categories"].append("Music")
    taxonomy = tmp_path / "taxonomy.json"
    taxonomy.write_text(json.dumps(document))
    products = tmp_path / "products.csv"
    with products.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["slug", "categories"])
        writer.writerow(["one", "[Music]"])
        writer.writerow(["two", "[music]"])
    with pytest.raises(ValueError, match="case-equivalent source categories mapped and unmapped"):
        audit(taxonomy, products, require_complete_source_snapshot=False)
