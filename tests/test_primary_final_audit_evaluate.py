"""Pre-registered audit metrics count ambiguous gold as accepted errors."""

import pytest

from ph_catalog.primary_final_audit_evaluate import score, wilson_95


def test_random_denominator_and_ambiguous_gold_are_conservative():
    ledger = [
        {
            "review_id": f"r{index}",
            "split": "random" if index < 200 else "model_stratified",
            "status": "null" if index == 3 else "candidate",
            "primary_category": None if index == 3 else "developer_tools",
            "final_path": "source_text_only",
            "stage4_path": "candidate_accept",
            "website_outcome": None,
        }
        for index in range(320)
    ]
    labels = [
        {
            "review_id": f"r{index}",
            "decision": "single",
            "primary_category": "developer_tools",
        }
        for index in range(320)
    ]
    labels[0] = {"review_id": "r0", "decision": "co_primary", "primary_category": None}
    labels[1] = {"review_id": "r1", "decision": "null", "primary_category": None}
    labels[2]["primary_category"] = "finance"
    result = score(ledger, labels)
    assert result["random"]["denominator"] == 200
    assert result["random"]["accepted"] == 199
    assert result["random"]["correct_unique_primary"] == 196
    assert result["random"]["coverage"] == 199 / 200
    assert result["biased_diagnostic"]["denominator"] == 120
    assert result["random_paths"]["source_text_only"]["correct_unique_primary"] == 196
    assert result["random_confusion"]["co_primary"]["developer_tools"] == 1
    assert result["random_confusion"]["null"]["developer_tools"] == 1
    assert result["path_gates"]["llm_final"] is False
    assert result["broad_promotion_gate"] is False
    assert wilson_95(0, 0) == (0.0, 1.0)
    with pytest.raises(ValueError, match="incomplete"):
        score(ledger, [{**labels[0], "decision": "unreviewed"}, *labels[1:]])
