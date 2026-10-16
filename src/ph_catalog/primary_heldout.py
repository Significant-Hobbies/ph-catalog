"""Run and audit the frozen text classifier on independently reserved holdouts.

The original random sample is reported separately from source-stratified and
text-discovered samples. Source tags and discovery queries never enter inference.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from ph_catalog.primary_classifier import _top_two, text_input
from ph_catalog.primary_label_protocol import BLIND_FILES, SPLITS, validate_annotations
from ph_catalog.primary_taxonomy import Taxonomy, load_taxonomy
from ph_catalog.primary_taxonomy_review import sha256_file

FROZEN_TAXONOMY_SHA = "3f160113db54be27e59eb9b366b656154525f1f0aa6cd6abb9da29d180ca8270"
FROZEN_MODEL_SHA = "a561cb0d70129e25f56893abc6c4ee853391c6a9169d12aec20d308030f8b847"
FROZEN_THRESHOLDS_SHA = "6bf58337cf258cd889c908914831b38f39a77dc7cb7e16f7bf56202681ae9aa3"
FROZEN_DEVELOPMENT_SHA = "eebca5f22230d881645deaba1f7e904b93e039bfe6ab2174ff998993f62d6ddd"
FROZEN_CANDIDATE_MANIFEST_SHA = "ed6ad5a3bc9640ffe9e4c71fb4dbd119c317e4abe71c2d9cc4165771ff5ec1d2"
FROZEN_PREDICTIONS_SHA = "e97a8c855d09bcf53a607ca4965e63c177a326132f40668b9143c55e2403eef3"
EXPECTED_SPLITS = {
    "main": {"development": 680, "holdout_random": 200, "holdout_stratified": 340},
    "home": {"development": 160, "holdout_random": 0, "holdout_stratified": 80},
    "sparse": {"development": 160, "holdout_random": 0, "holdout_stratified": 80},
}
FROZEN_SAMPLE_MANIFESTS = {
    "main": "83aa177e208bad022d028c8732579cb6c30ba487710b580259f17ec771ba801a",
    "home": "410a7fa23d949b9fca200c433c03b35c60d9e397006ad825b542c47b9baf663f",
    "sparse": "58de922acac822dc1eaecb83d4cec88b60d3170ae3a2318321ca165e39bf6014",
}


def load_reservations(
    taxonomy: Taxonomy,
    bundles: tuple[tuple[str, Path, Path], ...],
    *,
    require_sealed: bool,
    expected_splits: dict[str, dict[str, int]] = EXPECTED_SPLITS,
    expected_manifest_hashes: dict[str, str] = FROZEN_SAMPLE_MANIFESTS,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Check the full manifest chain and return only heldout text/labels."""
    if set(expected_manifest_hashes) != set(expected_splits):
        raise ValueError("manifest pins differ from required reservations")
    if {name for name, _, _ in bundles} != set(expected_splits) or len(bundles) != len(
        expected_splits
    ):
        raise ValueError("required reservation bundles differ")
    rows: list[dict[str, Any]] = []
    manifests: list[dict[str, str]] = []
    all_slugs: set[str] = set()
    all_ids: set[str] = set()
    archive_sha: str | None = None
    for name, bundle, annotation_path in bundles:
        manifest_path = bundle / "manifest.json"
        if sha256_file(manifest_path) != expected_manifest_hashes[name]:
            raise ValueError(f"frozen sample manifest hash mismatch in {name}")
        manifest = json.loads(manifest_path.read_text())
        if manifest["taxonomy_sha256"] != taxonomy.sha256:
            raise ValueError(f"taxonomy hash mismatch in {name}")
        if archive_sha is None:
            archive_sha = manifest["products_csv_sha256"]
        elif archive_sha != manifest["products_csv_sha256"]:
            raise ValueError(f"source archive hash mismatch in {name}")
        if manifest["selected"] != expected_splits[name]:
            raise ValueError(f"reservation split counts changed in {name}")
        blind = {}
        for split, filename in BLIND_FILES.items():
            path = bundle / filename
            if sha256_file(path) != manifest["file_sha256"][filename]:
                raise ValueError(f"blind file hash mismatch in {name}: {filename}")
            blind[split] = json.loads(path.read_text())
            if len(blind[split]) != expected_splits[name][split]:
                raise ValueError(f"blind split count changed in {name}: {split}")
        key_path = bundle / "source-key.json"
        if sha256_file(key_path) != manifest["file_sha256"]["source-key.json"]:
            raise ValueError(f"source key hash mismatch in {name}")
        key_records = json.loads(key_path.read_text())
        key = {entry["review_id"]: entry for entry in key_records}
        if len(key) != len(key_records):
            raise ValueError(f"duplicate source key review ID in {name}")
        split_by_id = {entry["review_id"]: split for split in SPLITS for entry in blind[split]}
        if len(split_by_id) != len(key) or set(split_by_id) != set(key):
            raise ValueError(f"blind and source key IDs differ in {name}")
        if any(key[review_id]["split"] != split for review_id, split in split_by_id.items()):
            raise ValueError(f"blind and source key splits differ in {name}")
        annotations = json.loads(annotation_path.read_text())
        decisions = validate_annotations(blind, annotations, taxonomy)
        if decisions["development"].get("unreviewed", 0):
            raise ValueError(f"development labels incomplete in {name}")
        heldout_unreviewed = sum(
            decisions[split].get("unreviewed", 0)
            for split in ("holdout_random", "holdout_stratified")
        )
        heldout_total = (
            expected_splits[name]["holdout_random"] + expected_splits[name]["holdout_stratified"]
        )
        if require_sealed and heldout_unreviewed != heldout_total:
            raise ValueError(f"heldout labels were opened before prediction in {name}")
        if not require_sealed and heldout_unreviewed:
            raise ValueError(f"heldout labels incomplete in {name}")
        if all_ids.intersection(key):
            raise ValueError(f"overlapping review IDs in {name}")
        all_ids.update(key)
        slugs = {entry["slug"] for entry in key_records}
        if len(slugs) != len(key_records) or all_slugs.intersection(slugs):
            raise ValueError(f"overlapping product slugs in {name}")
        all_slugs.update(slugs)
        labels = {entry["review_id"]: entry for entry in annotations}
        for split in ("holdout_random", "holdout_stratified"):
            for record in blind[split]:
                review_id = record["review_id"]
                rows.append(
                    {
                        "bundle": name,
                        "split": split,
                        "slug": key[review_id]["slug"],
                        "review_id": review_id,
                        "name": record["name"],
                        "tagline": record["tagline"],
                        "description": record["description"],
                        "annotation": labels[review_id],
                    }
                )
        manifests.append(
            {
                "name": name,
                "manifest_sha256": sha256_file(manifest_path),
                "blind_random_sha256": manifest["file_sha256"][BLIND_FILES["holdout_random"]],
                "blind_stratified_sha256": manifest["file_sha256"][
                    BLIND_FILES["holdout_stratified"]
                ],
            }
        )
    if len(rows) != sum(
        counts["holdout_random"] + counts["holdout_stratified"]
        for counts in expected_splits.values()
    ):
        raise ValueError("heldout count changed")
    return sorted(rows, key=lambda row: row["slug"]), sorted(manifests, key=lambda row: row["name"])


def load_candidate(
    taxonomy: Taxonomy,
    candidate_dir: Path,
    *,
    expected_model_sha: str = FROZEN_MODEL_SHA,
    expected_thresholds_sha: str = FROZEN_THRESHOLDS_SHA,
    expected_development_sha: str = FROZEN_DEVELOPMENT_SHA,
    expected_manifest_sha: str = FROZEN_CANDIDATE_MANIFEST_SHA,
) -> tuple[Any, dict[str, Any], dict[str, str]]:
    """Hash-check the approved local artifact before loading pickle data."""
    import joblib

    manifest_path = candidate_dir / "candidate-manifest.json"
    model_path = candidate_dir / "model.joblib"
    threshold_path = candidate_dir / "thresholds.json"
    if sha256_file(manifest_path) != expected_manifest_sha:
        raise ValueError("frozen candidate manifest hash mismatch")
    manifest = json.loads(manifest_path.read_text())
    if (
        manifest["taxonomy_sha256"] != taxonomy.sha256
        or manifest["development_sha256"] != expected_development_sha
        or manifest["model_sha256"] != expected_model_sha
        or manifest["thresholds_sha256"] != expected_thresholds_sha
        or manifest["features"] != "word_char"
        or manifest["development_count"] != 1_000
        or manifest["heldouts_used"] != 0
    ):
        raise ValueError("candidate differs from frozen development contract")
    if (
        sha256_file(model_path) != expected_model_sha
        or sha256_file(threshold_path) != expected_thresholds_sha
    ):
        raise ValueError("frozen candidate artifact hash mismatch")
    thresholds = json.loads(threshold_path.read_text())
    for field in ("confidence", "margin"):
        value = thresholds.get(field)
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not 0 <= value <= 1:
            raise ValueError(f"invalid frozen threshold: {field}")
    model = joblib.load(model_path)
    if set(model.classes_) != set(taxonomy.category_names):
        raise ValueError("frozen model classes differ from taxonomy")
    return (
        model,
        thresholds,
        {
            "model_sha256": expected_model_sha,
            "thresholds_sha256": expected_thresholds_sha,
            "candidate_manifest_sha256": expected_manifest_sha,
        },
    )


def make_predictions(
    taxonomy: Taxonomy,
    candidate_dir: Path,
    rows: list[dict[str, Any]],
    manifests: list[dict[str, str]],
    *,
    expected_model_sha: str = FROZEN_MODEL_SHA,
    expected_thresholds_sha: str = FROZEN_THRESHOLDS_SHA,
    expected_development_sha: str = FROZEN_DEVELOPMENT_SHA,
    expected_manifest_sha: str = FROZEN_CANDIDATE_MANIFEST_SHA,
) -> dict[str, Any]:
    """Apply the frozen candidate once to each heldout product text."""
    from threadpoolctl import threadpool_limits

    model, thresholds, hashes = load_candidate(
        taxonomy,
        candidate_dir,
        expected_model_sha=expected_model_sha,
        expected_thresholds_sha=expected_thresholds_sha,
        expected_development_sha=expected_development_sha,
        expected_manifest_sha=expected_manifest_sha,
    )
    with threadpool_limits(limits=1):
        probabilities = model.predict_proba([text_input(row) for row in rows])
    predictions = []
    for row, values in zip(rows, probabilities, strict=True):
        top, runner_up, confidence, margin = _top_two(
            list(model.classes_), list(map(float, values))
        )
        predictions.append(
            {
                "slug": row["slug"],
                "primary_category": (
                    top
                    if confidence >= thresholds["confidence"] and margin >= thresholds["margin"]
                    else None
                ),
                "runner_up": runner_up,
                "confidence": confidence,
                "margin": margin,
                "evidence_hash": hashlib.sha256(text_input(row).encode()).hexdigest(),
            }
        )
    return {
        "method": "local_classifier",
        "taxonomy_sha256": taxonomy.sha256,
        **hashes,
        "sample_manifests": manifests,
        "rows": predictions,
    }


def _summarize(
    records: list[dict[str, Any]], predictions: dict[str, dict[str, Any]], categories: list[str]
) -> dict[str, Any]:
    confusion: Counter[tuple[str, str]] = Counter()
    decisions: Counter[str] = Counter()
    for record in records:
        annotation = record["annotation"]
        actual = (
            annotation["primary_category"] if annotation["decision"] == "single" else "__null__"
        )
        proposed = predictions[record["slug"]]["primary_category"] or "__null__"
        confusion[(actual, proposed)] += 1
        decisions[annotation["decision"]] += 1
    n = len(records)
    predicted = sum(count for (_, proposed), count in confusion.items() if proposed != "__null__")
    correct = sum(
        count for (actual, proposed), count in confusion.items() if actual == proposed != "__null__"
    )
    single = decisions["single"]
    abstention_gold = n - single
    per_category = {}
    for category in categories:
        tp = confusion[(category, category)]
        fp = sum(
            count
            for (actual, proposed), count in confusion.items()
            if proposed == category and actual != category
        )
        fn = sum(
            count
            for (actual, proposed), count in confusion.items()
            if actual == category and proposed != category
        )
        per_category[category] = {
            "support": tp + fn,
            "predicted": tp + fp,
            "precision": tp / (tp + fp) if tp + fp else 0.0,
            "recall": tp / (tp + fn) if tp + fn else 0.0,
        }
    return {
        "count": n,
        "gold_decisions": dict(sorted(decisions.items())),
        "non_null_predictions": predicted,
        "coverage": predicted / n if n else 0.0,
        "non_null_precision": correct / predicted if predicted else 0.0,
        "single_gold_recall": correct / single if single else 0.0,
        "null_gold_abstention_rate": (
            confusion[("__null__", "__null__")] / abstention_gold if abstention_gold else 0.0
        ),
        "macro_precision": sum(per_category[c]["precision"] for c in categories) / len(categories),
        "macro_recall": sum(per_category[c]["recall"] for c in categories) / len(categories),
        "per_category": per_category,
        "confusion": [
            {"actual": actual, "predicted": proposed, "count": count}
            for (actual, proposed), count in sorted(confusion.items())
            if count
        ],
    }


def evaluate_combined(
    taxonomy: Taxonomy,
    rows: list[dict[str, Any]],
    submitted: dict[str, Any],
    independently_recomputed: dict[str, Any],
    *,
    minimum_targeted_support: int = 20,
    expected_random_count: int = 200,
    expected_targeted_count: int = 500,
) -> dict[str, Any]:
    """Report metrics only when labels and prediction provenance both pass."""
    if submitted != independently_recomputed:
        raise ValueError("predictions differ from frozen artifact replay")
    if any(row["annotation"]["decision"] == "unreviewed" for row in rows):
        raise ValueError("heldout annotations are incomplete")
    if minimum_targeted_support < 1:
        raise ValueError("minimum targeted support must be positive")
    random = [row for row in rows if row["bundle"] == "main" and row["split"] == "holdout_random"]
    main_targeted = [
        row for row in rows if row["bundle"] == "main" and row["split"] == "holdout_stratified"
    ]
    home = [row for row in rows if row["bundle"] == "home"]
    sparse = [row for row in rows if row["bundle"] == "sparse"]
    targeted = main_targeted + home + sparse
    support = Counter(
        row["annotation"]["primary_category"]
        for row in targeted
        if row["annotation"]["decision"] == "single"
    )
    categories = sorted(taxonomy.category_names)
    if len(random) != expected_random_count or len(targeted) != expected_targeted_count:
        raise ValueError("combined reserved holdout split counts changed")
    shortfalls = {
        category: minimum_targeted_support - support[category]
        for category in categories
        if support[category] < minimum_targeted_support
    }
    gate = {
        "random_holdout_count": len(random),
        "source_stratified_count": len(main_targeted),
        "supplemental_home_count": len(home),
        "supplemental_sparse_count": len(sparse),
        "targeted_single_support": {category: support[category] for category in categories},
        "targeted_shortfalls": shortfalls,
        "evaluation_label_gate_open": not shortfalls,
    }
    report = {
        "taxonomy_sha256": taxonomy.sha256,
        "model_sha256": submitted["model_sha256"],
        "thresholds_sha256": submitted["thresholds_sha256"],
        "prediction_document_sha256": hashlib.sha256(
            (json.dumps(submitted, sort_keys=True, ensure_ascii=False) + "\n").encode()
        ).hexdigest(),
        "sample_manifests": submitted["sample_manifests"],
        "label_gate": gate,
        "interpretation": (
            "original random sample estimates coverage of eligible archived CSV products "
            "after 3,770 prior-review exclusions; targeted and supplemental samples are biased "
            "diagnostics, not population precision"
        ),
    }
    if shortfalls:
        return report
    by_slug = {row["slug"]: row for row in submitted["rows"]}
    if len(by_slug) != len(rows) or set(by_slug) != {row["slug"] for row in rows}:
        raise ValueError("prediction slugs differ from reserved holdouts")
    report["metrics"] = {
        "original_random": _summarize(random, by_slug, categories),
        "source_stratified": _summarize(main_targeted, by_slug, categories),
        "supplemental_home": _summarize(home, by_slug, categories),
        "supplemental_sparse": _summarize(sparse, by_slug, categories),
        "all_targeted": _summarize(targeted, by_slug, categories),
    }
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("predict", "evaluate"))
    parser.add_argument("--taxonomy", type=Path, required=True)
    parser.add_argument("--candidate-dir", type=Path, required=True)
    parser.add_argument(
        "--bundle", nargs=3, action="append", required=True, metavar=("NAME", "PATH", "ANNOTATIONS")
    )
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    taxonomy = load_taxonomy(args.taxonomy)
    if taxonomy.sha256 != FROZEN_TAXONOMY_SHA or taxonomy.version != "v1":
        raise ValueError("expected frozen v1 taxonomy")
    bundles = tuple((name, Path(path), Path(labels)) for name, path, labels in args.bundle)
    rows, manifests = load_reservations(taxonomy, bundles, require_sealed=args.command == "predict")
    current = make_predictions(taxonomy, args.candidate_dir, rows, manifests)
    if args.command == "predict":
        if args.predictions.exists():
            raise FileExistsError(args.predictions)
        serialized = json.dumps(current, indent=2, ensure_ascii=False) + "\n"
        if hashlib.sha256(serialized.encode()).hexdigest() != FROZEN_PREDICTIONS_SHA:
            raise ValueError("frozen prediction output changed before heldout annotation")
        args.predictions.parent.mkdir(parents=True, exist_ok=True)
        args.predictions.write_text(serialized)
        print(
            json.dumps(
                {"heldout_count": len(rows), "prediction_sha256": sha256_file(args.predictions)}
            )
        )
        return
    if args.report is None:
        raise ValueError("evaluation requires --report")
    if args.report.exists():
        raise FileExistsError(args.report)
    if sha256_file(args.predictions) != FROZEN_PREDICTIONS_SHA:
        raise ValueError("prediction file differs from frozen pre-annotation output")
    submitted = json.loads(args.predictions.read_text())
    report = evaluate_combined(taxonomy, rows, submitted, current)
    report["prediction_file_sha256"] = FROZEN_PREDICTIONS_SHA
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"label_gate": report["label_gate"], "metrics_emitted": "metrics" in report}))


if __name__ == "__main__":
    main()
