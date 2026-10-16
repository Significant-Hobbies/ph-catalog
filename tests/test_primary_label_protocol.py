"""Product-label samples must stay blinded, disjoint, and honest about support."""

import json
from dataclasses import replace

import pytest

from ph_catalog import primary_label_protocol as protocol
from ph_catalog.primary_taxonomy import Taxonomy


@pytest.fixture
def taxonomy() -> Taxonomy:
    return Taxonomy(
        version="v1-candidate",
        source_snapshot="test",
        category_names={"developer_tools": "Developer tools", "home_lifestyle": "Home"},
        source_map={"Code editors": "developer_tools", "Home": "home_lifestyle"},
        rationales={},
        sha256="taxonomy-test-sha",
    )


def test_sample_is_deterministic_disjoint_and_blinded(
    monkeypatch: pytest.MonkeyPatch, tmp_path, taxonomy: Taxonomy
) -> None:
    products = tmp_path / "products.csv"
    products.write_text("verified archive")
    previous = tmp_path / "previous-source-key.json"
    previous.write_text(json.dumps([{"slug": "old", "source_categories": ["Home"]}]))
    rehearsal = tmp_path / "rehearsal-source-key.json"
    rehearsal.write_text(json.dumps([{"slug": "b", "split": "holdout_random"}]))
    rows = [
        ("old", "Old", "home", "prior tuning", ["Home"]),
        ("a", "A", "editor", "Build software", ["Code editors"]),
        ("b", "B", "editor", "Build websites", ["Code editors"]),
        ("c", "C", "home", "Plan your house", ["Home"]),
        ("d", "D", "home", "Improve your home", ["Home"]),
        ("e", "E", "misc", "Mystery product", []),
        ("f", "F", "misc", "Unknown product", []),
        ("g", "G", "mixed", "Software for homes", ["Home", "Code editors"]),
        ("h", "H", "mixed", "Code for living", ["Home", "Code editors"]),
    ]
    monkeypatch.setattr(protocol, "rows_from_csv", lambda _path: iter(rows))
    args = (products, taxonomy, previous)
    options = {
        "seed": "fixed",
        "random_count": 1,
        "heldout_per_stratum": 1,
        "development_per_stratum": 1,
        "additional_exclusion_keys": (rehearsal,),
    }
    blind, key, manifest = protocol.select_bundle(*args, **options)
    assert (blind, key, manifest) == protocol.select_bundle(*args, **options)
    assert len({entry["slug"] for entry in key}) == len(key)
    assert "old" not in {entry["slug"] for entry in key}
    assert "b" not in {entry["slug"] for entry in key}
    assert sum(map(len, blind.values())) == len(key)
    assert all(
        set(entry) == {"review_id", "name", "tagline", "description"}
        for split in protocol.SPLITS
        for entry in blind[split]
    )
    assert manifest["excluded_tuning_slugs"] == 1
    assert manifest["excluded_additional_slugs"] == 1
    assert manifest["excluded_distinct_slugs"] == 2
    assert manifest["additional_exclusion_key_sha256"] == [protocol.sha256_file(rehearsal)]
    assert manifest["total_products"] == len(rows)

    output = tmp_path / "bundle"
    protocol.write_bundle(output, blind, key, manifest)
    assert (output / "source-key.json").exists()
    assert (output / "annotations-template.json").exists()
    with pytest.raises(FileExistsError):
        protocol.write_bundle(output, blind, key, manifest)


def test_annotation_decisions_and_gate_are_validated(tmp_path, taxonomy: Taxonomy) -> None:
    blind = {
        "development": [
            {"review_id": "single", "name": "Editor", "tagline": "Build code", "description": ""},
            {
                "review_id": "co",
                "name": "Hybrid",
                "tagline": "Build and plan homes",
                "description": "",
            },
        ],
        "holdout_random": [
            {"review_id": "null", "name": "Mystery", "tagline": "", "description": ""}
        ],
        "holdout_stratified": [],
    }
    annotations = [
        {
            "review_id": "single",
            "decision": "single",
            "primary_category": "developer_tools",
            "co_primary_categories": [],
            "evidence": {"developer_tools": "Build code"},
            "null_reason": None,
            "reviewer_id": "reviewer-a",
        },
        {
            "review_id": "co",
            "decision": "co_primary",
            "primary_category": None,
            "co_primary_categories": ["developer_tools", "home_lifestyle"],
            "evidence": {"developer_tools": "Build", "home_lifestyle": "homes"},
            "null_reason": None,
            "reviewer_id": "reviewer-a",
        },
        {
            "review_id": "null",
            "decision": "null",
            "primary_category": None,
            "co_primary_categories": [],
            "evidence": {},
            "null_reason": "insufficient_text",
            "reviewer_id": "reviewer-b",
        },
    ]
    gate = protocol.label_gate(
        blind,
        annotations,
        taxonomy,
        minimum_development_per_class=1,
        minimum_holdout_per_class=1,
    )
    assert gate["single_label_support"]["development"]["developer_tools"] == 1
    assert gate["development_shortfalls"] == {"home_lifestyle": 1}
    assert gate["train_gate_open"] is False
    assert gate["evaluation_label_gate_open"] is False

    wrong = [entry.copy() for entry in annotations]
    wrong[0]["evidence"] = {"developer_tools": "source tag not in product text"}
    with pytest.raises(ValueError, match="exact product-text span"):
        protocol.validate_annotations(blind, wrong, taxonomy)
    wrong[0]["evidence"] = {"developer_tools": "Build code"}
    wrong[1]["co_primary_categories"] = ["developer_tools", "developer_tools"]
    with pytest.raises(ValueError, match="invalid co-primary categories"):
        protocol.validate_annotations(blind, wrong, taxonomy)

    key = [
        {
            "review_id": review_id,
            "slug": f"slug-{review_id}",
            "split": split,
            "source_categories": ["secret source tag"],
        }
        for split in protocol.SPLITS
        for review_id in (entry["review_id"] for entry in blind[split])
    ]
    bundle = tmp_path / "bundle"
    protocol.write_bundle(bundle, blind, key, {"taxonomy_sha256": taxonomy.sha256})
    output = tmp_path / "gold.json"
    protocol.export_development_gold(bundle, blind, annotations, taxonomy, output)
    gold = json.loads(output.read_text())
    assert len(gold) == 2
    assert gold[0]["slug"] == "slug-single"
    assert "source_categories" not in output.read_text()
    assert "name" not in gold[0]  # text is loaded from source by slug, never copied from key
    with pytest.raises(FileExistsError):
        protocol.export_development_gold(bundle, blind, annotations, taxonomy, output)


def test_evaluation_refuses_candidate_and_scores_only_reviewed_holdouts(
    tmp_path, taxonomy: Taxonomy
) -> None:
    frozen = replace(taxonomy, version="v1")
    blind = {
        "development": [],
        "holdout_random": [{"review_id": "r", "name": "Mystery", "tagline": "", "description": ""}],
        "holdout_stratified": [
            {"review_id": "d", "name": "Editor", "tagline": "Build code", "description": ""},
            {"review_id": "h", "name": "Home", "tagline": "Plan houses", "description": ""},
        ],
    }
    key = [
        {
            "review_id": review_id,
            "slug": f"slug-{review_id}",
            "split": split,
            "source_categories": ["private source tag"],
        }
        for split in protocol.SPLITS
        for review_id in (entry["review_id"] for entry in blind[split])
    ]
    bundle = tmp_path / "bundle"
    protocol.write_bundle(bundle, blind, key, {"taxonomy_sha256": frozen.sha256})
    annotations = [
        {
            "review_id": "r",
            "decision": "null",
            "primary_category": None,
            "co_primary_categories": [],
            "evidence": {},
            "null_reason": "underdetermined",
            "reviewer_id": "independent",
        },
        {
            "review_id": "d",
            "decision": "single",
            "primary_category": "developer_tools",
            "co_primary_categories": [],
            "evidence": {"developer_tools": "Build code"},
            "null_reason": None,
            "reviewer_id": "independent",
        },
        {
            "review_id": "h",
            "decision": "single",
            "primary_category": "home_lifestyle",
            "co_primary_categories": [],
            "evidence": {"home_lifestyle": "Plan houses"},
            "null_reason": None,
            "reviewer_id": "independent",
        },
    ]
    predictions = {
        "taxonomy_sha256": frozen.sha256,
        "method": "local_classifier",
        "model_sha256": "a" * 64,
        "thresholds_sha256": "b" * 64,
        "rows": [
            {
                "slug": f"slug-{entry['review_id']}",
                "primary_category": "developer_tools" if entry["review_id"] == "d" else None,
                "runner_up": None,
                "confidence": 0.8,
                "margin": 0.3,
                "evidence_hash": protocol.hashlib.sha256(
                    "\n".join(
                        str(entry[field]) for field in ("name", "tagline", "description")
                    ).encode()
                ).hexdigest(),
            }
            for split in ("holdout_random", "holdout_stratified")
            for entry in blind[split]
        ],
    }
    with pytest.raises(ValueError, match="label gate is closed"):
        protocol.evaluate_predictions(
            bundle,
            blind,
            annotations,
            taxonomy,
            predictions,
            minimum_holdout_per_class=1,
            minimum_random_holdout=1,
        )
    report = protocol.evaluate_predictions(
        bundle,
        blind,
        annotations,
        frozen,
        predictions,
        minimum_holdout_per_class=1,
        minimum_random_holdout=1,
    )
    assert report["holdout_random"]["null_gold_abstention_rate"] == 1
    assert "macro_precision" not in report["holdout_random"]
    assert report["holdout_stratified"]["coverage"] == 0.5
    assert report["holdout_stratified"]["macro_recall"] == 0.5
    assert "private source tag" not in json.dumps(report)
    predictions["rows"][0]["evidence_hash"] = "wrong"
    with pytest.raises(ValueError, match="product-text hash mismatch"):
        protocol.evaluate_predictions(
            bundle,
            blind,
            annotations,
            frozen,
            predictions,
            minimum_holdout_per_class=1,
            minimum_random_holdout=1,
        )
