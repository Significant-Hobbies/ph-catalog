"""Combined development gold excludes source tags and enforces sealed holdouts."""

import json
from pathlib import Path

import pytest

from ph_catalog.primary_combined_development import load_combined_development
from ph_catalog.primary_label_protocol import write_bundle
from ph_catalog.primary_taxonomy import load_taxonomy

TAXONOMY = Path(__file__).resolve().parents[1] / "taxonomy" / "v1.json"


def _bundle(tmp_path: Path, name: str, categories: list[str]):
    taxonomy = load_taxonomy(TAXONOMY)
    development = [
        {
            "review_id": f"{name}-{index}",
            "name": f"{category} tool",
            "tagline": f"A {category} workflow",
            "description": "Clear product text",
        }
        for index, category in enumerate(categories)
    ]
    holdout = [
        {
            "review_id": f"{name}-heldout",
            "name": "Unseen product",
            "tagline": "Sealed",
            "description": "Do not read this for training",
        }
    ]
    blind = {"development": development, "holdout_random": [], "holdout_stratified": holdout}
    key = [
        {
            "review_id": record["review_id"],
            "slug": f"{name}-{index}",
            "split": "development",
            "source_categories": ["must never leak"],
            "group": "must never leak",
        }
        for index, record in enumerate(development)
    ]
    key.append(
        {"review_id": f"{name}-heldout", "slug": f"{name}-heldout", "split": "holdout_stratified"}
    )
    bundle = tmp_path / name
    write_bundle(
        bundle,
        blind,
        key,
        {
            "taxonomy_sha256": taxonomy.sha256,
            "products_csv_sha256": "a" * 64,
            "selected": {
                "development": len(development),
                "holdout_random": 0,
                "holdout_stratified": 1,
            },
        },
    )
    annotations = json.loads((bundle / "annotations-template.json").read_text())
    for annotation, category in zip(annotations[: len(categories)], categories, strict=True):
        annotation.update(
            decision="single",
            primary_category=category,
            evidence={category: category},
            reviewer_id="independent-blind-reviewer",
        )
    annotation_path = bundle / "annotations-working.json"
    annotation_path.write_text(json.dumps(annotations))
    return name, bundle, annotation_path


def test_combined_gate_uses_disjoint_true_labels_and_seals_holdouts(tmp_path: Path) -> None:
    taxonomy = load_taxonomy(TAXONOMY)
    categories = list(taxonomy.category_names)
    first = _bundle(tmp_path, "first", categories[:8])
    second = _bundle(tmp_path, "second", categories[8:])
    report, rows = load_combined_development(taxonomy, (first, second), minimum_per_class=1)
    assert report["train_gate_open"]
    assert report["development_count"] == 16
    assert report["heldout_count"] == 2
    assert all(value == 1 for value in report["single_label_support"].values())
    assert all(
        set(row)
        == {
            "slug",
            "name",
            "tagline",
            "description",
            "decision",
            "primary_category",
            "co_primary_categories",
            "null_reason",
            "text_sha256",
        }
        for row in rows
    )
    assert "must never leak" not in json.dumps(rows)
    assert not any("heldout" in row["slug"] for row in rows)


def test_combined_gate_rejects_open_holdout_or_overlap(tmp_path: Path) -> None:
    taxonomy = load_taxonomy(TAXONOMY)
    categories = list(taxonomy.category_names)
    first = _bundle(tmp_path, "first", categories[:8])
    second = _bundle(tmp_path, "second", categories[8:])
    annotations = json.loads(second[2].read_text())
    annotations[-1].update(decision="null", null_reason="underdetermined", reviewer_id="reviewer")
    second[2].write_text(json.dumps(annotations))
    with pytest.raises(ValueError, match="heldout annotations were opened"):
        load_combined_development(taxonomy, (first, second), minimum_per_class=1)
    annotations[-1].update(decision="unreviewed", null_reason=None, reviewer_id=None)
    second[2].write_text(json.dumps(annotations))
    key_path = second[1] / "source-key.json"
    key = json.loads(key_path.read_text())
    key[0]["slug"] = "first-0"
    key_path.write_text(json.dumps(key))
    with pytest.raises(ValueError, match="source key hash mismatch"):
        load_combined_development(taxonomy, (first, second), minimum_per_class=1)
