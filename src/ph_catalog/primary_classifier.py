"""Train a local text-only primary classifier with out-of-fold abstention tuning.

Inputs are independently adjudicated development rows. No source categories,
discovery groups, or heldout examples enter model selection or thresholding.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from ph_catalog.primary_combined_development import load_combined_development
from ph_catalog.primary_taxonomy import load_taxonomy
from ph_catalog.primary_taxonomy_review import sha256_file

FOLDS = 5
FOLD_SEED = "primary-v1-development-folds"
TARGET_OOF_PRECISION = 0.85
MINIMUM_NON_NULL_OOF_PREDICTIONS = 30
ROW_FIELDS = {
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


def text_input(row: dict[str, Any]) -> str:
    return "\n".join(str(row[field]) for field in ("name", "tagline", "description"))


def assign_slug_folds(rows: list[dict[str, Any]], *, folds: int = FOLDS) -> dict[str, int]:
    """Assign each slug once, balanced by true development class."""
    if folds < 2:
        raise ValueError("at least two folds are required")
    groups: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        group = row["primary_category"] if row["decision"] == "single" else "__null__"
        groups[group].append(row["slug"])
    assigned = {}
    for slugs in groups.values():
        for index, slug in enumerate(
            sorted(
                slugs, key=lambda value: hashlib.sha256(f"{FOLD_SEED}:{value}".encode()).hexdigest()
            )
        ):
            assigned[slug] = index % folds
    return assigned


def _model(features: str):
    """Use a proven sparse linear text model with internal sigmoid calibration."""
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import FeatureUnion, Pipeline

    if features not in {"word", "word_char"}:
        raise ValueError("unknown fixed feature configuration")
    word = TfidfVectorizer(
        ngram_range=(1, 2),
        min_df=2,
        max_features=60_000,
        strip_accents="unicode",
        sublinear_tf=True,
    )
    if features == "word_char":
        vectorizer = FeatureUnion(
            [
                ("word", word),
                (
                    "char",
                    TfidfVectorizer(
                        analyzer="char_wb",
                        ngram_range=(3, 5),
                        min_df=2,
                        max_features=80_000,
                        strip_accents="unicode",
                        sublinear_tf=True,
                    ),
                ),
            ]
        )
    else:
        vectorizer = word

    base = Pipeline(
        [
            ("tfidf", vectorizer),
            (
                "linear",
                LogisticRegression(C=2.0, class_weight="balanced", max_iter=1_000, random_state=17),
            ),
        ]
    )
    return CalibratedClassifierCV(estimator=base, method="sigmoid", cv=3, ensemble=False)


def _top_two(classes: list[str], probabilities: list[float]) -> tuple[str, str, float, float]:
    ranking = sorted(zip(classes, probabilities, strict=True), key=lambda x: (-x[1], x[0]))
    return ranking[0][0], ranking[1][0], ranking[0][1], ranking[0][1] - ranking[1][1]


def threshold_diagnostics(
    predictions: list[dict[str, Any]], confidence: float, margin: float, classes: list[str]
) -> dict[str, Any]:
    """Score development OOF predictions; null/co-primary are true abstentions."""
    confusion: Counter[tuple[str, str]] = Counter()
    decision_counts: Counter[str] = Counter()
    for row in predictions:
        predicted = (
            row["top_category"]
            if row["confidence"] >= confidence and row["margin"] >= margin
            else "__null__"
        )
        actual = row["primary_category"] if row["decision"] == "single" else "__null__"
        confusion[(actual, predicted)] += 1
        decision_counts[row["decision"]] += 1
    predicted_count = sum(n for (_, predicted), n in confusion.items() if predicted != "__null__")
    correct = sum(
        n for (actual, predicted), n in confusion.items() if actual == predicted != "__null__"
    )
    true_single = sum(n for (actual, _), n in confusion.items() if actual != "__null__")
    null_count = sum(n for (actual, _), n in confusion.items() if actual == "__null__")
    null_abstained = confusion[("__null__", "__null__")]
    per_class = {}
    for category in classes:
        tp = confusion[(category, category)]
        fp = sum(
            n
            for (actual, predicted), n in confusion.items()
            if predicted == category and actual != category
        )
        fn = sum(
            n
            for (actual, predicted), n in confusion.items()
            if actual == category and predicted != category
        )
        per_class[category] = {
            "support": tp + fn,
            "predicted": tp + fp,
            "precision": tp / (tp + fp) if tp + fp else 0.0,
            "recall": tp / (tp + fn) if tp + fn else 0.0,
            "abstained": confusion[(category, "__null__")],
        }
    return {
        "confidence_threshold": confidence,
        "margin_threshold": margin,
        "count": len(predictions),
        "gold_decisions": dict(sorted(decision_counts.items())),
        "non_null_predictions": predicted_count,
        "coverage": predicted_count / len(predictions),
        "non_null_precision": correct / predicted_count if predicted_count else 0.0,
        "single_gold_recall": correct / true_single if true_single else 0.0,
        "null_or_co_primary_gold": null_count,
        "null_gold_abstained": null_abstained,
        "null_gold_abstention_rate": null_abstained / null_count if null_count else 0.0,
        "macro_precision": sum(per_class[c]["precision"] for c in classes) / len(classes),
        "macro_recall": sum(per_class[c]["recall"] for c in classes) / len(classes),
        "per_category": per_class,
        "confusion": [
            {"actual": actual, "predicted": predicted, "count": n}
            for (actual, predicted), n in sorted(confusion.items())
            if n
        ],
    }


def choose_thresholds(predictions: list[dict[str, Any]], classes: list[str]) -> dict[str, Any]:
    """Choose maximum OOF coverage meeting a fixed precision floor."""
    candidates = []
    for confidence_step in range(4, 20):
        confidence = confidence_step / 20
        for margin_step in range(11):
            margin = margin_step / 20
            result = threshold_diagnostics(predictions, confidence, margin, classes)
            if (
                result["non_null_predictions"] >= MINIMUM_NON_NULL_OOF_PREDICTIONS
                and result["non_null_precision"] >= TARGET_OOF_PRECISION
            ):
                candidates.append(result)
    if not candidates:
        chosen = threshold_diagnostics(predictions, 1.0, 1.0, classes)
        status = "no threshold met the preregistered development precision and count floors"
    else:
        chosen = max(
            candidates,
            key=lambda row: (
                row["non_null_predictions"],
                row["non_null_precision"],
                -row["confidence_threshold"],
                -row["margin_threshold"],
            ),
        )
        status = "development-only OOF threshold selected; heldout verification pending"
    return {
        "confidence": chosen["confidence_threshold"],
        "margin": chosen["margin_threshold"],
        "selection_status": status,
        "target_oof_precision": TARGET_OOF_PRECISION,
        "minimum_oof_predictions": MINIMUM_NON_NULL_OOF_PREDICTIONS,
        "grid": "confidence 0.20..0.95 step 0.05; margin 0.00..0.50 step 0.05",
        "fold_seed": FOLD_SEED,
        "folds": FOLDS,
        "interpretation": "development out-of-fold tuning; not final population accuracy",
    }


def validate_development_input(document: dict[str, Any], taxonomy_sha: str, classes: list[str]):
    report = document["report"]
    rows = document["rows"]
    if not report["train_gate_open"] or report["taxonomy_sha256"] != taxonomy_sha:
        raise ValueError("combined development gate is closed or taxonomy changed")
    if report["heldout_count"] < 1 or len(rows) != report["development_count"]:
        raise ValueError("combined development manifest is incomplete")
    if len({row["slug"] for row in rows}) != len(rows):
        raise ValueError("duplicate development slug")
    if any(set(row) != ROW_FIELDS for row in rows):
        raise ValueError("development rows contain extra or missing fields")
    support: Counter[str] = Counter()
    for row in rows:
        if hashlib.sha256(text_input(row).encode()).hexdigest() != row["text_sha256"]:
            raise ValueError("product text hash mismatch")
        if row["decision"] == "single":
            if row["primary_category"] not in classes:
                raise ValueError("unknown development class")
            support[row["primary_category"]] += 1
        elif row["decision"] not in {"co_primary", "null"}:
            raise ValueError("invalid development decision")
    if any(support[c] < report["minimum_development_per_class"] for c in classes):
        raise ValueError("true class support below the combined gate")
    if {c: support[c] for c in classes} != report["single_label_support"]:
        raise ValueError("class support differs from combined manifest")
    return sorted(rows, key=lambda row: row["slug"])


def verify_export_provenance(
    document: dict[str, Any],
    rechecked_report: dict[str, Any],
    rechecked_rows: list[dict[str, Any]],
    *,
    expected_development: int = 1_000,
    expected_heldouts: int = 700,
    expected_random_holdout: int = 200,
    expected_bundles: int = 3,
) -> None:
    """Reject stale/tampered exports and changes to the reserved sample contract."""
    if document != {"report": rechecked_report, "rows": rechecked_rows}:
        raise ValueError("development export differs from current verified bundle provenance")
    if (
        rechecked_report["development_count"] != expected_development
        or rechecked_report["heldout_count"] != expected_heldouts
        or rechecked_report["random_holdout_count"] != expected_random_holdout
        or len(rechecked_report["bundles"]) != expected_bundles
    ):
        raise ValueError("frozen-v1 main and supplemental sample counts changed")


def train_candidate(
    development: Path,
    taxonomy_path: Path,
    bundles: tuple[tuple[str, Path, Path], ...],
    output_dir: Path,
    *,
    features: str = "word",
) -> dict[str, Any]:
    """Fit only development singles; tune abstention on slug-disjoint OOF rows."""
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(output_dir)
    import joblib
    import sklearn
    from threadpoolctl import threadpool_limits

    taxonomy = load_taxonomy(taxonomy_path)
    classes = list(taxonomy.category_names)
    document = json.loads(development.read_text())
    rechecked_report, rechecked_rows = load_combined_development(taxonomy, bundles)
    verify_export_provenance(document, rechecked_report, rechecked_rows)
    rows = validate_development_input(document, taxonomy.sha256, classes)
    folds = assign_slug_folds(rows)
    oof = []
    with threadpool_limits(limits=1):
        for fold in range(FOLDS):
            train = [
                row for row in rows if row["decision"] == "single" and folds[row["slug"]] != fold
            ]
            test = [row for row in rows if folds[row["slug"]] == fold]
            model = _model(features)
            model.fit(
                [text_input(row) for row in train], [row["primary_category"] for row in train]
            )
            if set(model.classes_) != set(classes):
                raise ValueError("a slug fold lost a taxonomy class")
            probabilities = model.predict_proba([text_input(row) for row in test])
            for row, values in zip(test, probabilities, strict=True):
                top, runner_up, confidence, margin = _top_two(
                    list(model.classes_), list(map(float, values))
                )
                oof.append(
                    {
                        "slug": row["slug"],
                        "fold": fold,
                        "decision": row["decision"],
                        "primary_category": row["primary_category"],
                        "top_category": top,
                        "runner_up": runner_up,
                        "confidence": confidence,
                        "margin": margin,
                    }
                )
        final = _model(features)
        singles = [row for row in rows if row["decision"] == "single"]
        final.fit(
            [text_input(row) for row in singles], [row["primary_category"] for row in singles]
        )
    if len(oof) != len(rows) or {row["slug"] for row in oof} != {row["slug"] for row in rows}:
        raise ValueError("out-of-fold predictions do not cover development exactly once")
    oof.sort(key=lambda row: row["slug"])
    thresholds = choose_thresholds(oof, classes)
    diagnostics = threshold_diagnostics(
        oof, thresholds["confidence"], thresholds["margin"], classes
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    model_path = output_dir / "model.joblib"
    joblib.dump(final, model_path)
    threshold_path = output_dir / "thresholds.json"
    threshold_path.write_text(json.dumps(thresholds, indent=2) + "\n")
    oof_path = output_dir / "development-oof.json"
    oof_path.write_text(
        json.dumps({"predictions": oof, "diagnostics": diagnostics}, indent=2) + "\n"
    )
    result = {
        "taxonomy_sha256": taxonomy.sha256,
        "development_sha256": sha256_file(development),
        "model_sha256": sha256_file(model_path),
        "thresholds_sha256": sha256_file(threshold_path),
        "development_oof_sha256": sha256_file(oof_path),
        "sklearn_version": sklearn.__version__,
        "algorithm": (
            f"{features} TF-IDF + balanced logistic regression + 3-fold sigmoid calibration"
        ),
        "features": features,
        "slug_folds": FOLDS,
        "fold_seed": FOLD_SEED,
        "development_count": len(rows),
        "training_single_count": len(singles),
        "heldouts_used": 0,
        "threshold_selection": thresholds["selection_status"],
        "development_oof": diagnostics,
        "interpretation": "development-only tuning diagnostic; independent heldout metrics pending",
    }
    (output_dir / "candidate-manifest.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--development", type=Path, required=True)
    parser.add_argument("--taxonomy", type=Path, required=True)
    parser.add_argument(
        "--bundle",
        nargs=3,
        action="append",
        metavar=("NAME", "PATH", "ANNOTATIONS"),
        required=True,
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--features", choices=("word", "word_char"), default="word")
    args = parser.parse_args()
    bundles = tuple(
        (name, Path(path), Path(annotations)) for name, path, annotations in args.bundle
    )
    print(
        json.dumps(
            train_candidate(
                args.development,
                args.taxonomy,
                bundles,
                args.output_dir,
                features=args.features,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
