"""A biased supplement opens metrics only after true support and replay checks."""

from copy import deepcopy

import pytest

from ph_catalog.primary_augmented_heldout import evaluate_augmented
from ph_catalog.primary_taxonomy import Taxonomy


def _row(bundle, split, index, category):
    slug = f"{bundle}-{split}-{index}"
    return {
        "slug": slug,
        "review_id": slug,
        "bundle": bundle,
        "split": split,
        "annotation": {
            "decision": "single" if category else "null",
            "primary_category": category,
        },
    }


def _predictions(rows):
    return {
        "taxonomy_sha256": "test-taxonomy",
        "model_sha256": "frozen-model",
        "thresholds_sha256": "frozen-thresholds",
        "sample_manifests": [],
        "rows": [
            {"slug": row["slug"], "primary_category": row["annotation"]["primary_category"]}
            for row in rows
        ],
    }


def test_augmented_gate_precedes_metrics_and_preserves_original_random():
    taxonomy = Taxonomy(
        version="v1",
        source_snapshot="test",
        category_names={"alpha": "Alpha", "beta": "Beta"},
        source_map={},
        rationales={},
        sha256="test-taxonomy",
    )
    core = (
        [_row("main", "holdout_random", i, "alpha") for i in range(200)]
        + [_row("main", "holdout_stratified", i, "alpha") for i in range(340)]
        + [_row("home", "holdout_stratified", i, "alpha") for i in range(80)]
        + [_row("sparse", "holdout_stratified", i, "alpha") for i in range(80)]
    )
    supplement = [
        _row("support", "holdout_stratified", i, "beta" if i < 19 else None) for i in range(125)
    ]
    core_predictions, support_predictions = _predictions(core), _predictions(supplement)
    closed = evaluate_augmented(
        taxonomy,
        core,
        supplement,
        core_predictions,
        support_predictions,
        core_predictions,
        support_predictions,
    )
    assert closed["label_gate"]["original_random_count"] == 200
    assert closed["label_gate"]["biased_support_supplement_count"] == 125
    assert closed["label_gate"]["targeted_shortfalls"] == {"beta": 1}
    assert "metrics" not in closed

    supplement[19]["annotation"] = {"decision": "single", "primary_category": "beta"}
    support_predictions = _predictions(supplement)
    opened = evaluate_augmented(
        taxonomy,
        core,
        supplement,
        core_predictions,
        support_predictions,
        core_predictions,
        support_predictions,
    )
    assert opened["label_gate"]["evaluation_label_gate_open"] is True
    assert opened["metrics"]["original_random"]["count"] == 200
    assert opened["metrics"]["all_targeted"]["count"] == 625
    assert opened["metrics"]["biased_support_supplement"]["count"] == 125

    tampered = deepcopy(support_predictions)
    tampered["rows"][0]["primary_category"] = "alpha"
    with pytest.raises(ValueError, match="replay"):
        evaluate_augmented(
            taxonomy,
            core,
            supplement,
            core_predictions,
            tampered,
            core_predictions,
            support_predictions,
        )
