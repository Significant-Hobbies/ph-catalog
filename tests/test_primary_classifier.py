"""Slug folds and abstention tuning avoid leakage and forced classifications."""

import hashlib

import pytest

from ph_catalog.primary_classifier import (
    assign_slug_folds,
    choose_thresholds,
    threshold_diagnostics,
    validate_development_input,
    verify_export_provenance,
)


def test_slug_folds_are_order_independent_and_class_balanced() -> None:
    rows = [
        {"slug": f"social-{index}", "decision": "single", "primary_category": "social"}
        for index in range(35)
    ]
    rows += [
        {"slug": f"data-{index}", "decision": "single", "primary_category": "data"}
        for index in range(37)
    ]
    rows += [
        {"slug": f"null-{index}", "decision": "null", "primary_category": None}
        for index in range(12)
    ]
    assigned = assign_slug_folds(rows)
    assert assigned == assign_slug_folds(list(reversed(rows)))
    assert len(assigned) == len(rows)
    for group in ("social", "data", None):
        folds = [assigned[row["slug"]] for row in rows if row["primary_category"] == group]
        counts = [folds.count(fold) for fold in range(5)]
        assert max(counts) - min(counts) <= 1


def test_threshold_tuning_abstains_on_wrong_and_null_development_rows() -> None:
    predictions = []
    for _ in range(60):
        predictions.append(
            {
                "decision": "single",
                "primary_category": "social",
                "top_category": "social",
                "confidence": 0.9,
                "margin": 0.5,
            }
        )
    for _ in range(20):
        predictions.append(
            {
                "decision": "single",
                "primary_category": "data",
                "top_category": "social",
                "confidence": 0.6,
                "margin": 0.1,
            }
        )
        predictions.append(
            {
                "decision": "null",
                "primary_category": None,
                "top_category": "social",
                "confidence": 0.55,
                "margin": 0.05,
            }
        )
    thresholds = choose_thresholds(predictions, ["social", "data"])
    diagnostics = threshold_diagnostics(
        predictions, thresholds["confidence"], thresholds["margin"], ["social", "data"]
    )
    assert diagnostics["non_null_predictions"] == 60
    assert diagnostics["non_null_precision"] == 1.0
    assert diagnostics["null_gold_abstention_rate"] == 1.0
    assert diagnostics["per_category"]["data"]["recall"] == 0.0


def test_combined_input_refuses_source_tags() -> None:
    row = {
        "slug": "example",
        "name": "Example",
        "tagline": "A social platform",
        "description": "Meet friends",
        "decision": "single",
        "primary_category": "social",
        "co_primary_categories": [],
        "null_reason": None,
    }
    row["text_sha256"] = hashlib.sha256(b"Example\nA social platform\nMeet friends").hexdigest()
    report = {
        "train_gate_open": True,
        "taxonomy_sha256": "frozen",
        "heldout_count": 1,
        "development_count": 1,
        "minimum_development_per_class": 1,
        "single_label_support": {"social": 1},
    }
    assert validate_development_input({"report": report, "rows": [row]}, "frozen", ["social"])
    row["source_categories"] = ["Social"]
    with pytest.raises(ValueError, match="extra or missing fields"):
        validate_development_input({"report": report, "rows": [row]}, "frozen", ["social"])


def test_export_provenance_rejects_tampering_and_sample_drift() -> None:
    report = {
        "development_count": 2,
        "heldout_count": 3,
        "random_holdout_count": 1,
        "bundles": [{"name": "first"}, {"name": "second"}],
    }
    rows = [{"slug": "a"}, {"slug": "b"}]
    expected = {
        "expected_development": 2,
        "expected_heldouts": 3,
        "expected_random_holdout": 1,
        "expected_bundles": 2,
    }
    verify_export_provenance({"report": report, "rows": rows}, report, rows, **expected)
    with pytest.raises(ValueError, match="differs from current verified"):
        verify_export_provenance(
            {"report": report, "rows": [{"slug": "tampered"}]}, report, rows, **expected
        )
    with pytest.raises(ValueError, match="sample counts changed"):
        verify_export_provenance(
            {"report": report, "rows": rows},
            report,
            rows,
            **{**expected, "expected_random_holdout": 2},
        )
