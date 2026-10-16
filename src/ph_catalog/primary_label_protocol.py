"""Pre-register blinded product-text labels before primary-category training.

Source categories are used only to form provisional strata in the private key.
Blind review records and downstream gold labels never contain those tags.
"""

from __future__ import annotations

import argparse
import hashlib
import heapq
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

from ph_catalog.primary_taxonomy import Taxonomy, load_taxonomy, primary_from_sources
from ph_catalog.primary_taxonomy_review import rank, rows_from_csv, sha256_file

SPLITS = ("development", "holdout_random", "holdout_stratified")
BLIND_FILES = {split: f"{split}-blind.json" for split in SPLITS}
NULL_REASONS = {"insufficient_text", "underdetermined", "outside_taxonomy"}


def _stratum(sources: list[str], taxonomy: Taxonomy) -> tuple[str, str | None, str]:
    category, outcome = primary_from_sources(sources, taxonomy)
    return (f"class:{category}" if category else outcome), category, outcome


def _retain(heap: list[tuple[int, str, tuple]], score: int, row: tuple, limit: int) -> None:
    if limit == 0:
        return
    item = (-score, row[0], row)
    if len(heap) < limit:
        heapq.heappush(heap, item)
    elif item > heap[0]:
        heapq.heapreplace(heap, item)


def _selected(heap: list[tuple[int, str, tuple]]) -> list[tuple]:
    return [item[2] for item in sorted(heap, reverse=True)]


def _scan(products_csv: Path):
    seen: set[str] = set()
    for row in rows_from_csv(products_csv):
        slug = row[0]
        if not slug or slug in seen:
            raise ValueError(f"missing or duplicate product slug: {slug!r}")
        seen.add(slug)
        yield row


def _excluded_slugs(previous_key: Path) -> set[str]:
    records = json.loads(previous_key.read_text())
    if not isinstance(records, list):
        raise ValueError("previous tuning key must be a list")
    slugs = {record["slug"] for record in records}
    if len(slugs) != len(records) or not slugs:
        raise ValueError("previous tuning key has duplicate or no slugs")
    return slugs


def select_bundle(
    products_csv: Path,
    taxonomy: Taxonomy,
    previous_tuning_key: Path,
    *,
    seed: str,
    random_count: int,
    heldout_per_stratum: int,
    development_per_stratum: int,
    additional_exclusion_keys: tuple[Path, ...] = (),
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]], dict[str, Any]]:
    """Select disjoint samples; all ranks are by slug, independent of row order."""
    if not seed or random_count < 1 or heldout_per_stratum < 1 or development_per_stratum < 1:
        raise ValueError("seed and sample sizes must be positive")
    tuning_excluded = _excluded_slugs(previous_tuning_key)
    additional_excluded = set().union(
        *(_excluded_slugs(path) for path in additional_exclusion_keys)
    )
    excluded = tuning_excluded | additional_excluded
    strata = [f"class:{category}" for category in taxonomy.category_names]
    strata += ["conflicting_source_categories", "no_unambiguous_source_category"]
    source_support: Counter[str] = Counter()
    random_heap: list[tuple[int, str, tuple]] = []
    total = 0
    for row in _scan(products_csv):
        total += 1
        slug = row[0]
        if slug in excluded:
            continue
        stratum, _, _ = _stratum(row[4] or [], taxonomy)
        source_support[stratum] += 1
        _retain(random_heap, int(rank(f"{seed}:random", slug), 16), row, random_count)
    random_rows = _selected(random_heap)
    chosen = {row[0] for row in random_rows} | excluded

    def per_stratum_pass(split: str, limit: int) -> list[tuple]:
        heaps: dict[str, list[tuple[int, str, tuple]]] = {stratum: [] for stratum in strata}
        for row in _scan(products_csv):
            slug = row[0]
            if slug in chosen:
                continue
            stratum, _, _ = _stratum(row[4] or [], taxonomy)
            _retain(heaps[stratum], int(rank(f"{seed}:{split}", slug), 16), row, limit)
        selected = [row for stratum in strata for row in _selected(heaps[stratum])]
        chosen.update(row[0] for row in selected)
        return selected

    stratified_rows = per_stratum_pass("holdout_stratified", heldout_per_stratum)
    development_rows = per_stratum_pass("development", development_per_stratum)
    by_split = {
        "development": development_rows,
        "holdout_random": random_rows,
        "holdout_stratified": stratified_rows,
    }
    blind: dict[str, list[dict[str, Any]]] = {}
    key: list[dict[str, Any]] = []
    selection_counts: dict[str, dict[str, int]] = {}
    all_ids: set[str] = set()
    for split in SPLITS:
        entries = []
        counts: Counter[str] = Counter()
        for slug, name, tagline, description, sources in sorted(
            by_split[split], key=lambda row: rank(f"{seed}:{split}", row[0])
        ):
            sources = sources or []
            stratum, provisional, outcome = _stratum(sources, taxonomy)
            review_id = rank(f"{seed}:review-id", slug)[:20]
            if review_id in all_ids:
                raise ValueError("review ID collision")
            all_ids.add(review_id)
            counts[stratum] += 1
            entries.append(
                {
                    "review_id": review_id,
                    "name": name or "",
                    "tagline": tagline or "",
                    "description": description or "",
                }
            )
            key.append(
                {
                    "review_id": review_id,
                    "slug": slug,
                    "split": split,
                    "stratum": stratum,
                    "source_categories": sources,
                    "provisional_source_category": provisional,
                    "source_outcome": outcome,
                }
            )
        blind[split] = entries
        selection_counts[split] = dict(sorted(counts.items()))
    deficits = {
        split: {
            stratum: limit - selection_counts[split].get(stratum, 0)
            for stratum in strata
            if selection_counts[split].get(stratum, 0) < limit
        }
        for split, limit in (
            ("development", development_per_stratum),
            ("holdout_stratified", heldout_per_stratum),
        )
    }
    manifest = {
        "protocol": "primary-label-protocol-v1",
        "purpose": "pre-registered label collection; prior review samples excluded",
        "taxonomy_version": taxonomy.version,
        "taxonomy_sha256": taxonomy.sha256,
        "products_csv_sha256": sha256_file(products_csv),
        "previous_tuning_key_sha256": sha256_file(previous_tuning_key),
        "additional_exclusion_key_sha256": [
            sha256_file(path) for path in additional_exclusion_keys
        ],
        "seed": seed,
        "total_products": total,
        "excluded_tuning_slugs": len(tuning_excluded),
        "excluded_additional_slugs": len(additional_excluded),
        "excluded_distinct_slugs": len(excluded),
        "requested": {
            "holdout_random": random_count,
            "holdout_stratified_per_stratum": heldout_per_stratum,
            "development_per_stratum": development_per_stratum,
        },
        "selected": {split: len(blind[split]) for split in SPLITS},
        "selected_by_source_stratum": selection_counts,
        "source_stratum_support_after_exclusion": dict(sorted(source_support.items())),
        "deficits": deficits,
        "holdout_rule": (
            "holdout_random first; source-stratified holdout next; "
            "development last; disjoint by slug"
        ),
        "evaluation_rule": "holdouts stay sealed until taxonomy/model/thresholds are frozen",
    }
    return blind, key, manifest


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode()


def write_bundle(
    output_dir: Path,
    blind: dict[str, list[dict[str, Any]]],
    key: list[dict[str, Any]],
    manifest: dict[str, Any],
) -> None:
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"review output is not empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    file_hashes = {}
    for split in SPLITS:
        name = BLIND_FILES[split]
        data = _json_bytes(blind[split])
        (output_dir / name).write_bytes(data)
        file_hashes[name] = hashlib.sha256(data).hexdigest()
    key_data = _json_bytes(key)
    (output_dir / "source-key.json").write_bytes(key_data)
    file_hashes["source-key.json"] = hashlib.sha256(key_data).hexdigest()
    manifest["file_sha256"] = file_hashes
    (output_dir / "manifest.json").write_bytes(_json_bytes(manifest))
    template = [
        {
            "review_id": entry["review_id"],
            "decision": "unreviewed",
            "primary_category": None,
            "co_primary_categories": [],
            "evidence": {},
            "null_reason": None,
            "reviewer_id": None,
        }
        for split in SPLITS
        for entry in blind[split]
    ]
    (output_dir / "annotations-template.json").write_bytes(_json_bytes(template))


def validate_annotations(
    blind: dict[str, list[dict[str, Any]]],
    annotations: list[dict[str, Any]],
    taxonomy: Taxonomy,
) -> dict[str, dict[str, int]]:
    """Validate independently entered labels before reading the source key."""
    records = {entry["review_id"]: (split, entry) for split in SPLITS for entry in blind[split]}
    if len(records) != sum(map(len, blind.values())):
        raise ValueError("duplicate blind review IDs")
    if len(annotations) != len(records):
        raise ValueError("annotation count does not match blind records")
    if {entry["review_id"] for entry in annotations} != set(records):
        raise ValueError("annotation IDs do not match blind records")
    counts: dict[str, Counter[str]] = {split: Counter() for split in SPLITS}
    for annotation in annotations:
        review_id = annotation["review_id"]
        split, record = records[review_id]
        decision = annotation["decision"]
        if decision not in {"unreviewed", "single", "co_primary", "null"}:
            raise ValueError(f"invalid decision for {review_id}")
        counts[split][decision] += 1
        if decision == "unreviewed":
            if (
                annotation.get("primary_category") is not None
                or annotation.get("co_primary_categories") != []
                or annotation.get("evidence") != {}
                or annotation.get("null_reason") is not None
                or annotation.get("reviewer_id") is not None
            ):
                raise ValueError(f"unreviewed annotation contains verdict fields for {review_id}")
            continue
        if not annotation.get("reviewer_id"):
            raise ValueError(f"missing reviewer for {review_id}")
        primary = annotation.get("primary_category")
        co_primary = annotation.get("co_primary_categories")
        evidence = annotation.get("evidence")
        null_reason = annotation.get("null_reason")
        text = "\n".join(str(record[field]) for field in ("name", "tagline", "description"))
        if decision == "single":
            if primary not in taxonomy.category_names or co_primary or null_reason:
                raise ValueError(f"invalid single-category decision for {review_id}")
            expected = {primary}
        elif decision == "co_primary":
            if primary is not None or null_reason or not isinstance(co_primary, list):
                raise ValueError(f"invalid co-primary decision for {review_id}")
            expected = set(co_primary)
            if len(expected) < 2 or len(expected) != len(co_primary):
                raise ValueError(f"invalid co-primary categories for {review_id}")
            if not expected <= set(taxonomy.category_names):
                raise ValueError(f"unknown co-primary category for {review_id}")
        else:
            if primary is not None or co_primary or null_reason not in NULL_REASONS or evidence:
                raise ValueError(f"invalid null decision for {review_id}")
            continue
        if not isinstance(evidence, dict) or set(evidence) != expected:
            raise ValueError(f"missing category evidence for {review_id}")
        if any(
            not isinstance(span, str) or not span or span not in text for span in evidence.values()
        ):
            raise ValueError(f"evidence is not an exact product-text span for {review_id}")
    return {split: dict(sorted(counts[split].items())) for split in SPLITS}


def label_gate(
    blind: dict[str, list[dict[str, Any]]],
    annotations: list[dict[str, Any]],
    taxonomy: Taxonomy,
    *,
    minimum_development_per_class: int = 30,
    minimum_holdout_per_class: int = 20,
    minimum_random_holdout: int = 200,
) -> dict[str, Any]:
    """Report label support without interpreting source tags as gold labels."""
    decisions = validate_annotations(blind, annotations, taxonomy)
    split_by_id = {entry["review_id"]: split for split in SPLITS for entry in blind[split]}
    support: dict[str, Counter[str]] = {split: Counter() for split in SPLITS}
    for annotation in annotations:
        if annotation["decision"] == "single":
            support[split_by_id[annotation["review_id"]]][annotation["primary_category"]] += 1
    development_support = support["development"]
    heldout_support = support["holdout_stratified"]
    development_shortfalls = {
        category: minimum_development_per_class - development_support[category]
        for category in taxonomy.category_names
        if development_support[category] < minimum_development_per_class
    }
    heldout_shortfalls = {
        category: minimum_holdout_per_class - heldout_support[category]
        for category in taxonomy.category_names
        if heldout_support[category] < minimum_holdout_per_class
    }
    frozen = taxonomy.version.startswith("v") and taxonomy.version[1:].isdigit()
    development_complete = decisions["development"].get("unreviewed", 0) == 0
    holdout_complete = all(
        decisions[split].get("unreviewed", 0) == 0
        for split in ("holdout_random", "holdout_stratified")
    )
    random_holdout_sized = len(blind["holdout_random"]) >= minimum_random_holdout
    return {
        "decision_counts": decisions,
        "single_label_support": {
            split: {category: support[split][category] for category in taxonomy.category_names}
            for split in SPLITS
        },
        "development_shortfalls": development_shortfalls,
        "heldout_stratified_shortfalls": heldout_shortfalls,
        "taxonomy_frozen": frozen,
        "development_complete": development_complete,
        "holdouts_complete": holdout_complete,
        "random_holdout_sized": random_holdout_sized,
        "train_gate_open": frozen and development_complete and not development_shortfalls,
        "evaluation_label_gate_open": (
            frozen and holdout_complete and random_holdout_sized and not heldout_shortfalls
        ),
    }


def export_development_gold(
    bundle: Path,
    blind: dict[str, list[dict[str, Any]]],
    annotations: list[dict[str, Any]],
    taxonomy: Taxonomy,
    output: Path,
) -> None:
    """Reveal slugs only after development labels are complete; omit source tags."""
    counts = validate_annotations(blind, annotations, taxonomy)
    if counts["development"].get("unreviewed", 0):
        raise ValueError("development annotations are incomplete")
    if output.exists():
        raise FileExistsError(f"gold output already exists: {output}")
    manifest = json.loads((bundle / "manifest.json").read_text())
    key_path = bundle / "source-key.json"
    if sha256_file(key_path) != manifest["file_sha256"]["source-key.json"]:
        raise ValueError("source key changed since reservation")
    key = {entry["review_id"]: entry for entry in json.loads(key_path.read_text())}
    annotated = {entry["review_id"]: entry for entry in annotations}
    gold = []
    for record in blind["development"]:
        review_id = record["review_id"]
        if key[review_id]["split"] != "development":
            raise ValueError(f"key split mismatch for {review_id}")
        annotation = annotated[review_id]
        text = "\n".join(str(record[field]) for field in ("name", "tagline", "description"))
        gold.append(
            {
                "slug": key[review_id]["slug"],
                "decision": annotation["decision"],
                "primary_category": annotation["primary_category"],
                "co_primary_categories": annotation["co_primary_categories"],
                "null_reason": annotation["null_reason"],
                "reviewer_id": annotation["reviewer_id"],
                "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
            }
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(_json_bytes(gold))


def evaluate_predictions(
    bundle: Path,
    blind: dict[str, list[dict[str, Any]]],
    annotations: list[dict[str, Any]],
    taxonomy: Taxonomy,
    predictions: dict[str, Any],
    *,
    minimum_holdout_per_class: int = 20,
    minimum_random_holdout: int = 200,
) -> dict[str, Any]:
    """Score sealed holdouts only after their true-label support gate passes."""
    gate = label_gate(
        blind,
        annotations,
        taxonomy,
        minimum_holdout_per_class=minimum_holdout_per_class,
        minimum_random_holdout=minimum_random_holdout,
    )
    if not gate["evaluation_label_gate_open"]:
        raise ValueError("heldout label gate is closed; do not report model metrics")
    if predictions.get("taxonomy_sha256") != taxonomy.sha256:
        raise ValueError("prediction taxonomy hash mismatch")
    if predictions.get("method") != "local_classifier":
        raise ValueError("predictions must be from the local classifier")
    for name in ("model_sha256", "thresholds_sha256"):
        value = predictions.get(name)
        if (
            not isinstance(value, str)
            or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
        ):
            raise ValueError(f"missing or malformed {name}")
    manifest = json.loads((bundle / "manifest.json").read_text())
    key_path = bundle / "source-key.json"
    if sha256_file(key_path) != manifest["file_sha256"]["source-key.json"]:
        raise ValueError("source key changed since reservation")
    key = {entry["review_id"]: entry for entry in json.loads(key_path.read_text())}
    heldout = {
        key[record["review_id"]]["slug"]: (split, record["review_id"], record)
        for split in ("holdout_random", "holdout_stratified")
        for record in blind[split]
    }
    rows = predictions.get("rows")
    if not isinstance(rows, list) or len(rows) != len(heldout):
        raise ValueError("predictions must cover every heldout slug exactly once")
    by_slug = {row["slug"]: row for row in rows}
    if len(by_slug) != len(rows) or set(by_slug) != set(heldout):
        raise ValueError("prediction slugs differ from sealed holdouts")
    labels = {entry["review_id"]: entry for entry in annotations}
    confusion: dict[str, Counter[tuple[str, str]]] = {
        split: Counter() for split in ("holdout_random", "holdout_stratified")
    }
    for slug, (split, review_id, record) in heldout.items():
        row = by_slug[slug]
        predicted = row.get("primary_category")
        runner_up = row.get("runner_up")
        if predicted is not None and predicted not in taxonomy.category_names:
            raise ValueError(f"unknown predicted category for {slug}")
        if runner_up is not None and runner_up not in taxonomy.category_names:
            raise ValueError(f"unknown runner-up category for {slug}")
        for field in ("confidence", "margin"):
            value = row.get(field)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or not 0 <= value <= 1
            ):
                raise ValueError(f"invalid {field} for {slug}")
        text = "\n".join(str(record[field]) for field in ("name", "tagline", "description"))
        if row.get("evidence_hash") != hashlib.sha256(text.encode()).hexdigest():
            raise ValueError(f"product-text hash mismatch for {slug}")
        annotation = labels[review_id]
        expected = annotation["primary_category"] if annotation["decision"] == "single" else None
        confusion[split][(expected or "__null__", predicted or "__null__")] += 1

    def summarize(split: str) -> dict[str, Any]:
        pairs = confusion[split]
        total = sum(pairs.values())
        predicted = sum(n for (_, proposed), n in pairs.items() if proposed != "__null__")
        correct = sum(
            n for (actual, proposed), n in pairs.items() if actual == proposed != "__null__"
        )
        single_gold = sum(n for (actual, _), n in pairs.items() if actual != "__null__")
        null_gold = total - single_gold
        null_abstained = pairs.get(("__null__", "__null__"), 0)
        per_category = {}
        for category in taxonomy.category_names:
            tp = pairs.get((category, category), 0)
            fp = sum(
                n
                for (actual, proposed), n in pairs.items()
                if proposed == category and actual != category
            )
            fn = sum(
                n
                for (actual, proposed), n in pairs.items()
                if actual == category and proposed != category
            )
            per_category[category] = {
                "support": tp + fn,
                "precision": tp / (tp + fp) if tp + fp else 0.0,
                "recall": tp / (tp + fn) if tp + fn else 0.0,
            }
        summary = {
            "count": total,
            "non_null_predictions": predicted,
            "single_gold": single_gold,
            "null_or_co_primary_gold": null_gold,
            "coverage": predicted / total if total else 0.0,
            "non_null_precision": correct / predicted if predicted else 0.0,
            "single_gold_recall": correct / single_gold if single_gold else 0.0,
            "null_gold_abstention_rate": null_abstained / null_gold if null_gold else 0.0,
            "confusion": [
                {"actual": actual, "predicted": proposed, "count": count}
                for (actual, proposed), count in sorted(pairs.items())
            ],
        }
        if split == "holdout_stratified":
            ordered = sorted(taxonomy.category_names)
            summary["macro_precision"] = sum(per_category[c]["precision"] for c in ordered) / len(
                ordered
            )
            summary["macro_recall"] = sum(per_category[c]["recall"] for c in ordered) / len(ordered)
            summary["per_category"] = dict(sorted(per_category.items()))
        return summary

    return {
        "taxonomy_sha256": taxonomy.sha256,
        "model_sha256": predictions["model_sha256"],
        "thresholds_sha256": predictions["thresholds_sha256"],
        "sample_manifest_sha256": sha256_file(bundle / "manifest.json"),
        "interpretation": (
            "random estimates archive behavior; stratified supports per-category errors"
        ),
        "holdout_random": summarize("holdout_random"),
        "holdout_stratified": summarize("holdout_stratified"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    sample = commands.add_parser(
        "sample", help="reserve disjoint blind development and holdout sets"
    )
    sample.add_argument("--taxonomy", type=Path, required=True)
    sample.add_argument("--products", type=Path, required=True)
    sample.add_argument("--previous-tuning-key", type=Path, required=True)
    sample.add_argument(
        "--exclude-key",
        type=Path,
        action="append",
        default=[],
        help="exclude every slug in another preserved review source key",
    )
    sample.add_argument("--output-dir", type=Path, required=True)
    sample.add_argument("--seed", default="primary-label-v1-2026-10-16")
    sample.add_argument("--random-count", type=int, default=200)
    sample.add_argument("--heldout-per-stratum", type=int, default=20)
    sample.add_argument("--development-per-stratum", type=int, default=40)
    check = commands.add_parser("check", help="validate blind annotations without opening the key")
    check.add_argument("--taxonomy", type=Path, required=True)
    check.add_argument("--bundle", type=Path, required=True)
    check.add_argument("--annotations", type=Path, required=True)
    export = commands.add_parser(
        "export-development", help="write reviewed gold without source tags"
    )
    export.add_argument("--taxonomy", type=Path, required=True)
    export.add_argument("--bundle", type=Path, required=True)
    export.add_argument("--annotations", type=Path, required=True)
    export.add_argument("--output", type=Path, required=True)
    evaluate = commands.add_parser("evaluate", help="score a frozen model on sealed holdouts")
    evaluate.add_argument("--taxonomy", type=Path, required=True)
    evaluate.add_argument("--bundle", type=Path, required=True)
    evaluate.add_argument("--annotations", type=Path, required=True)
    evaluate.add_argument("--predictions", type=Path, required=True)
    evaluate.add_argument("--model-artifact", type=Path, required=True)
    evaluate.add_argument("--thresholds-file", type=Path, required=True)
    evaluate.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    taxonomy = load_taxonomy(args.taxonomy)
    if args.command == "sample":
        blind, key, manifest = select_bundle(
            args.products,
            taxonomy,
            args.previous_tuning_key,
            seed=args.seed,
            random_count=args.random_count,
            heldout_per_stratum=args.heldout_per_stratum,
            development_per_stratum=args.development_per_stratum,
            additional_exclusion_keys=tuple(args.exclude_key),
        )
        write_bundle(args.output_dir, blind, key, manifest)
        print(json.dumps(manifest, indent=2))
    else:
        manifest = json.loads((args.bundle / "manifest.json").read_text())
        if manifest["taxonomy_sha256"] != taxonomy.sha256:
            raise ValueError("taxonomy hash differs from reserved sample")
        blind = {}
        for split, name in BLIND_FILES.items():
            if sha256_file(args.bundle / name) != manifest["file_sha256"][name]:
                raise ValueError(f"blind review changed since reservation: {name}")
            blind[split] = json.loads((args.bundle / name).read_text())
        annotations = json.loads(args.annotations.read_text())
        if args.command == "check":
            print(json.dumps(label_gate(blind, annotations, taxonomy), indent=2))
        elif args.command == "export-development":
            export_development_gold(args.bundle, blind, annotations, taxonomy, args.output)
            print(f"wrote development gold: {args.output}")
        else:
            if args.output.exists():
                raise FileExistsError(f"evaluation output already exists: {args.output}")
            predictions = json.loads(args.predictions.read_text())
            if predictions.get("model_sha256") != sha256_file(args.model_artifact):
                raise ValueError("model artifact hash differs from predictions")
            if predictions.get("thresholds_sha256") != sha256_file(args.thresholds_file):
                raise ValueError("threshold file hash differs from predictions")
            result = evaluate_predictions(args.bundle, blind, annotations, taxonomy, predictions)
            result["predictions_sha256"] = sha256_file(args.predictions)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_bytes(_json_bytes(result))
            print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
