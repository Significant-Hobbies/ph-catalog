"""Frozen holdout inference must replay exactly and keep sampling claims separate."""

import hashlib
import json
import sys
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from ph_catalog.primary_heldout import (
    evaluate_combined,
    load_candidate,
    load_reservations,
    make_predictions,
)
from ph_catalog.primary_label_protocol import SPLITS, write_bundle
from ph_catalog.primary_taxonomy import Taxonomy
from ph_catalog.primary_taxonomy_review import sha256_file


class FakeModel:
    classes_ = ["alpha", "beta"]

    def predict_proba(self, texts):
        return [[0.9, 0.1] if "Alpha" in text else [0.1, 0.9] for text in texts]


@pytest.fixture
def fake_optional_runtime(monkeypatch):
    # Default CI intentionally does not install the optional classifier extra.
    monkeypatch.setitem(sys.modules, "joblib", SimpleNamespace(load=lambda _path: FakeModel()))
    monkeypatch.setitem(
        sys.modules,
        "threadpoolctl",
        SimpleNamespace(threadpool_limits=lambda **_kwargs: nullcontext()),
    )


@pytest.fixture
def taxonomy():
    return Taxonomy(
        version="v1",
        source_snapshot="test",
        category_names={"alpha": "Alpha", "beta": "Beta"},
        source_map={},
        rationales={},
        sha256="test-taxonomy-sha",
    )


def _record(review_id, category):
    return {
        "review_id": review_id,
        "name": f"{category.title()} product",
        "tagline": f"{category.title()} workflow",
        "description": "",
    }


def _annotation(review_id, category, *, sealed):
    return {
        "review_id": review_id,
        "decision": "unreviewed" if sealed else "single",
        "primary_category": None if sealed else category,
        "co_primary_categories": [],
        "evidence": {} if sealed else {category: f"{category.title()} workflow"},
        "null_reason": None,
        "reviewer_id": None if sealed else "independent",
    }


def _bundles(tmp_path, taxonomy, *, sealed):
    plan = {
        "main": {
            "development": ["alpha"],
            "holdout_random": ["beta"],
            "holdout_stratified": ["alpha"],
        },
        "home": {"development": ["beta"], "holdout_random": [], "holdout_stratified": ["beta"]},
        "sparse": {"development": ["alpha"], "holdout_random": [], "holdout_stratified": ["alpha"]},
    }
    bundles = []
    expected = {}
    for name, split_categories in plan.items():
        blind = {split: [] for split in SPLITS}
        key = []
        annotations = []
        for split, categories in split_categories.items():
            for index, category in enumerate(categories):
                review_id = f"{name}-{split}-{index}"
                blind[split].append(_record(review_id, category))
                key.append({"review_id": review_id, "slug": review_id, "split": split})
                annotations.append(
                    _annotation(review_id, category, sealed=sealed and split != "development")
                )
        bundle = tmp_path / name
        write_bundle(
            bundle,
            blind,
            key,
            {
                "taxonomy_sha256": taxonomy.sha256,
                "products_csv_sha256": "archive-sha",
                "selected": {split: len(blind[split]) for split in SPLITS},
            },
        )
        annotation_path = tmp_path / f"{name}-annotations.json"
        annotation_path.write_text(json.dumps(annotations))
        bundles.append((name, bundle, annotation_path))
        expected[name] = {split: len(blind[split]) for split in SPLITS}
    manifest_hashes = {name: sha256_file(bundle / "manifest.json") for name, bundle, _ in bundles}
    return tuple(bundles), expected, manifest_hashes


def _candidate(tmp_path, taxonomy):
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    model = candidate / "model.joblib"
    model.write_bytes(b"test-only fake artifact")
    thresholds = candidate / "thresholds.json"
    thresholds.write_text(json.dumps({"confidence": 0.7, "margin": 0.2}))
    model_sha, thresholds_sha, development_sha = (
        sha256_file(model),
        sha256_file(thresholds),
        hashlib.sha256(b"development").hexdigest(),
    )
    (candidate / "candidate-manifest.json").write_text(
        json.dumps(
            {
                "taxonomy_sha256": taxonomy.sha256,
                "development_sha256": development_sha,
                "model_sha256": model_sha,
                "thresholds_sha256": thresholds_sha,
                "features": "word_char",
                "development_count": 1_000,
                "heldouts_used": 0,
            }
        )
    )
    return (
        candidate,
        model_sha,
        thresholds_sha,
        development_sha,
        sha256_file(candidate / "candidate-manifest.json"),
    )


def test_reservations_verify_seal_hashes_disjointness_and_counts(tmp_path, taxonomy):
    bundles, expected, manifest_hashes = _bundles(tmp_path, taxonomy, sealed=True)
    rows, manifests = load_reservations(
        taxonomy,
        bundles,
        require_sealed=True,
        expected_splits=expected,
        expected_manifest_hashes=manifest_hashes,
    )
    assert len(rows) == 4
    assert len(manifests) == 3
    assert all("source_categories" not in row for row in rows)
    with pytest.raises(ValueError, match="incomplete"):
        load_reservations(
            taxonomy,
            bundles,
            require_sealed=False,
            expected_splits=expected,
            expected_manifest_hashes=manifest_hashes,
        )

    annotation_path = bundles[0][2]
    annotations = json.loads(annotation_path.read_text())
    heldout = next(entry for entry in annotations if entry["decision"] == "unreviewed")
    heldout["evidence"] = {"alpha": "hidden verdict"}
    annotation_path.write_text(json.dumps(annotations))
    with pytest.raises(ValueError, match="unreviewed annotation contains verdict"):
        load_reservations(
            taxonomy,
            bundles,
            require_sealed=True,
            expected_splits=expected,
            expected_manifest_hashes=manifest_hashes,
        )

    annotation_path.write_text(
        json.dumps(
            [
                _annotation(entry["review_id"], "alpha", sealed=True)
                if entry["review_id"] == heldout["review_id"]
                else entry
                for entry in annotations
            ]
        )
    )
    path = bundles[0][1] / "holdout_random-blind.json"
    path.write_text(path.read_text() + " ")
    with pytest.raises(ValueError, match="blind file hash mismatch"):
        load_reservations(
            taxonomy,
            bundles,
            require_sealed=True,
            expected_splits=expected,
            expected_manifest_hashes=manifest_hashes,
        )


def test_frozen_predictions_replay_and_combined_gate(tmp_path, taxonomy, fake_optional_runtime):
    bundles, expected, manifest_hashes = _bundles(tmp_path, taxonomy, sealed=False)
    rows, manifests = load_reservations(
        taxonomy,
        bundles,
        require_sealed=False,
        expected_splits=expected,
        expected_manifest_hashes=manifest_hashes,
    )
    candidate, model_sha, thresholds_sha, development_sha, manifest_sha = _candidate(
        tmp_path, taxonomy
    )
    options = {
        "expected_model_sha": model_sha,
        "expected_thresholds_sha": thresholds_sha,
        "expected_development_sha": development_sha,
        "expected_manifest_sha": manifest_sha,
    }
    predictions = make_predictions(taxonomy, candidate, rows, manifests, **options)
    assert predictions == make_predictions(taxonomy, candidate, rows, manifests, **options)
    assert len(predictions["rows"]) == 4
    assert all(row["primary_category"] is not None for row in predictions["rows"])
    report = evaluate_combined(
        taxonomy,
        rows,
        predictions,
        predictions,
        minimum_targeted_support=1,
        expected_random_count=1,
        expected_targeted_count=3,
    )
    assert report["label_gate"]["evaluation_label_gate_open"] is True
    assert report["metrics"]["original_random"]["count"] == 1
    assert report["metrics"]["all_targeted"]["count"] == 3
    assert report["metrics"]["all_targeted"]["non_null_precision"] == 1

    submitted = json.loads(json.dumps(predictions))
    submitted["rows"][0]["primary_category"] = (
        "alpha" if submitted["rows"][0]["primary_category"] == "beta" else "beta"
    )
    with pytest.raises(ValueError, match="frozen artifact replay"):
        evaluate_combined(
            taxonomy,
            rows,
            submitted,
            predictions,
            minimum_targeted_support=1,
            expected_random_count=1,
            expected_targeted_count=3,
        )

    with pytest.raises(ValueError, match="artifact hash mismatch"):
        (candidate / "model.joblib").write_bytes(b"tampered")
        load_candidate(taxonomy, candidate, **options)


def test_missing_true_targeted_class_suppresses_all_metrics(
    tmp_path, taxonomy, fake_optional_runtime
):
    bundles, expected, manifest_hashes = _bundles(tmp_path, taxonomy, sealed=False)
    rows, manifests = load_reservations(
        taxonomy,
        bundles,
        require_sealed=False,
        expected_splits=expected,
        expected_manifest_hashes=manifest_hashes,
    )
    candidate, model_sha, thresholds_sha, development_sha, manifest_sha = _candidate(
        tmp_path, taxonomy
    )
    predictions = make_predictions(
        taxonomy,
        candidate,
        rows,
        manifests,
        expected_model_sha=model_sha,
        expected_thresholds_sha=thresholds_sha,
        expected_development_sha=development_sha,
        expected_manifest_sha=manifest_sha,
    )
    for row in rows:
        row["annotation"]["primary_category"] = "alpha"
    report = evaluate_combined(
        taxonomy,
        rows,
        predictions,
        predictions,
        minimum_targeted_support=1,
        expected_random_count=1,
        expected_targeted_count=3,
    )
    assert report["label_gate"]["targeted_shortfalls"] == {"beta": 1}
    assert "metrics" not in report
