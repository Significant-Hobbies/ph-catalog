"""Replay the frozen classifier on a disjoint, biased support supplement.

The original random 200 and targeted 500 retain their separate interpretation.
No model choice or threshold may use these heldout labels.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from ph_catalog.primary_heldout import (
    FROZEN_PREDICTIONS_SHA,
    FROZEN_SAMPLE_MANIFESTS,
    FROZEN_TAXONOMY_SHA,
    _summarize,
    load_reservations,
    make_predictions,
)
from ph_catalog.primary_label_protocol import _excluded_slugs
from ph_catalog.primary_taxonomy import Taxonomy, load_taxonomy
from ph_catalog.primary_taxonomy_review import sha256_file

SUPPORT_MANIFEST_SHA = "d76f2a9233590585b6a699ff0945e801644bee1b08f001f1d26866a2c5b17cc2"
SUPPORT_PREDICTIONS_SHA = "456ba7200a937116ac17edce043ab1220b51d28771e5e4500008575a24b63642"
SUPPORT_SPLITS = {"development": 0, "holdout_random": 0, "holdout_stratified": 125}


def check_exclusions(support: Path, previous_keys: tuple[Path, ...]) -> None:
    """Recheck the exact seven previous key hashes and slug disjointness."""
    manifest = json.loads((support / "manifest.json").read_text())
    if (
        len(previous_keys) != 7
        or [sha256_file(path) for path in previous_keys] != manifest["exclusion_key_sha256"]
    ):
        raise ValueError("support discovery exclusion key chain changed")
    previous = set().union(*(_excluded_slugs(path) for path in previous_keys))
    if previous.intersection(_excluded_slugs(support / "source-key.json")):
        raise ValueError("support discovery overlaps a prior review or reservation")
    if len(previous) != manifest["excluded_distinct_slugs"]:
        raise ValueError("support discovery exclusion count changed")
    core_manifest_path = previous_keys[4].parent / "manifest.json"
    if sha256_file(core_manifest_path) != FROZEN_SAMPLE_MANIFESTS["main"]:
        raise ValueError("original core sample manifest changed")
    core_manifest = json.loads(core_manifest_path.read_text())
    if manifest["products_csv_sha256"] != core_manifest["products_csv_sha256"]:
        raise ValueError("support discovery source archive differs from core holdout")


def load_support(
    taxonomy: Taxonomy,
    support: tuple[str, Path, Path],
    previous_keys: tuple[Path, ...],
    *,
    require_sealed: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    if support[0] != "support":
        raise ValueError("expected named support bundle")
    check_exclusions(support[1], previous_keys)
    return load_reservations(
        taxonomy,
        (support,),
        require_sealed=require_sealed,
        expected_splits={"support": SUPPORT_SPLITS},
        expected_manifest_hashes={"support": SUPPORT_MANIFEST_SHA},
    )


def evaluate_augmented(
    taxonomy: Taxonomy,
    core_rows: list[dict[str, Any]],
    support_rows: list[dict[str, Any]],
    core_predictions: dict[str, Any],
    support_predictions: dict[str, Any],
    core_replay: dict[str, Any],
    support_replay: dict[str, Any],
    *,
    minimum_targeted_support: int = 20,
) -> dict[str, Any]:
    """Keep the gate ahead of metrics and separate representative/bias strata."""
    if core_predictions != core_replay or support_predictions != support_replay:
        raise ValueError("heldout predictions differ from frozen artifact replay")
    if any(row["annotation"]["decision"] == "unreviewed" for row in core_rows + support_rows):
        raise ValueError("heldout annotations are incomplete")
    if minimum_targeted_support < 1:
        raise ValueError("minimum targeted support must be positive")
    if (
        core_predictions["model_sha256"] != support_predictions["model_sha256"]
        or core_predictions["thresholds_sha256"] != support_predictions["thresholds_sha256"]
        or core_predictions["taxonomy_sha256"] != support_predictions["taxonomy_sha256"]
    ):
        raise ValueError("support predictions use a different frozen candidate")
    random = [
        row for row in core_rows if row["bundle"] == "main" and row["split"] == "holdout_random"
    ]
    main_targeted = [
        row for row in core_rows if row["bundle"] == "main" and row["split"] == "holdout_stratified"
    ]
    home = [row for row in core_rows if row["bundle"] == "home"]
    sparse = [row for row in core_rows if row["bundle"] == "sparse"]
    if (
        len(core_rows) != 700
        or len(random) != 200
        or len(main_targeted) != 340
        or len(home) != 80
        or len(sparse) != 80
        or len(support_rows) != 125
    ):
        raise ValueError("heldout reservation counts changed")
    targeted = main_targeted + home + sparse + support_rows
    categories = sorted(taxonomy.category_names)
    support = Counter(
        row["annotation"]["primary_category"]
        for row in targeted
        if row["annotation"]["decision"] == "single"
    )
    shortfalls = {
        category: minimum_targeted_support - support[category]
        for category in categories
        if support[category] < minimum_targeted_support
    }
    report: dict[str, Any] = {
        "taxonomy_sha256": taxonomy.sha256,
        "model_sha256": core_predictions["model_sha256"],
        "thresholds_sha256": core_predictions["thresholds_sha256"],
        "core_prediction_file_sha256": FROZEN_PREDICTIONS_SHA,
        "support_prediction_file_sha256": SUPPORT_PREDICTIONS_SHA,
        "sample_manifests": core_predictions["sample_manifests"]
        + support_predictions["sample_manifests"],
        "label_gate": {
            "original_random_count": len(random),
            "original_targeted_count": 500,
            "biased_support_supplement_count": len(support_rows),
            "targeted_single_support": {category: support[category] for category in categories},
            "targeted_shortfalls": shortfalls,
            "evaluation_label_gate_open": not shortfalls,
        },
        "interpretation": (
            "original random estimates coverage of eligible archived CSV products after "
            "3,770 prior-review exclusions; original targeted and supplemental discovery "
            "samples are biased diagnostics, not population precision"
        ),
    }
    if shortfalls:
        return report
    by_slug = {row["slug"]: row for row in core_predictions["rows"] + support_predictions["rows"]}
    if len(by_slug) != 825 or set(by_slug) != {row["slug"] for row in core_rows + support_rows}:
        raise ValueError("prediction slugs differ from reserved holdouts")
    report["metrics"] = {
        "original_random": _summarize(random, by_slug, categories),
        "source_stratified": _summarize(main_targeted, by_slug, categories),
        "supplemental_home": _summarize(home, by_slug, categories),
        "supplemental_sparse": _summarize(sparse, by_slug, categories),
        "biased_support_supplement": _summarize(support_rows, by_slug, categories),
        "all_targeted": _summarize(targeted, by_slug, categories),
    }
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("predict-support", "evaluate-augmented"))
    parser.add_argument("--taxonomy", type=Path, required=True)
    parser.add_argument("--candidate-dir", type=Path, required=True)
    parser.add_argument("--support-bundle", nargs=2, required=True, metavar=("PATH", "ANNOTATIONS"))
    parser.add_argument("--previous-key", type=Path, action="append", required=True)
    parser.add_argument("--support-predictions", type=Path, required=True)
    parser.add_argument(
        "--bundle", nargs=3, action="append", metavar=("NAME", "PATH", "ANNOTATIONS")
    )
    parser.add_argument("--predictions", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    taxonomy = load_taxonomy(args.taxonomy)
    if taxonomy.sha256 != FROZEN_TAXONOMY_SHA or taxonomy.version != "v1":
        raise ValueError("expected frozen v1 taxonomy")
    support_bundle = ("support", Path(args.support_bundle[0]), Path(args.support_bundle[1]))
    support_rows, support_manifests = load_support(
        taxonomy,
        support_bundle,
        tuple(args.previous_key),
        require_sealed=args.command == "predict-support",
    )
    support_replay = make_predictions(taxonomy, args.candidate_dir, support_rows, support_manifests)
    if args.command == "predict-support":
        if args.support_predictions.exists():
            raise FileExistsError(args.support_predictions)
        payload = json.dumps(support_replay, indent=2, ensure_ascii=False) + "\n"
        if hashlib.sha256(payload.encode()).hexdigest() != SUPPORT_PREDICTIONS_SHA:
            raise ValueError("support predictions differ from pre-annotation frozen output")
        args.support_predictions.write_text(payload)
        print(
            json.dumps(
                {"count": len(support_rows), "sha256": sha256_file(args.support_predictions)}
            )
        )
        return
    if not args.bundle or args.predictions is None or args.report is None:
        raise ValueError("augmented evaluation requires three core bundles and both reports")
    if args.report.exists():
        raise FileExistsError(args.report)
    if sha256_file(args.predictions) != FROZEN_PREDICTIONS_SHA:
        raise ValueError("original 700 predictions differ from pre-annotation output")
    if sha256_file(args.support_predictions) != SUPPORT_PREDICTIONS_SHA:
        raise ValueError("support predictions differ from pre-annotation output")
    core_bundles = tuple((name, Path(path), Path(labels)) for name, path, labels in args.bundle)
    core_rows, core_manifests = load_reservations(taxonomy, core_bundles, require_sealed=False)
    if {row["slug"] for row in core_rows}.intersection(row["slug"] for row in support_rows):
        raise ValueError("support holdout overlaps original holdouts")
    if {row["review_id"] for row in core_rows}.intersection(
        row["review_id"] for row in support_rows
    ):
        raise ValueError("support review IDs overlap original holdouts")
    core_replay = make_predictions(taxonomy, args.candidate_dir, core_rows, core_manifests)
    report = evaluate_augmented(
        taxonomy,
        core_rows,
        support_rows,
        json.loads(args.predictions.read_text()),
        json.loads(args.support_predictions.read_text()),
        core_replay,
        support_replay,
    )
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"label_gate": report["label_gate"], "metrics_emitted": "metrics" in report}))


if __name__ == "__main__":
    main()
