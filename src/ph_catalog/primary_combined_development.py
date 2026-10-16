"""Validate disjoint, independently labeled development bundles before training.

The private keys are read only to join slugs and verify disjointness after
development review is complete. Source categories and discovery groups never
enter the exported text/label rows.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from ph_catalog.primary_label_protocol import BLIND_FILES, SPLITS, validate_annotations
from ph_catalog.primary_taxonomy import Taxonomy, load_taxonomy
from ph_catalog.primary_taxonomy_review import sha256_file


def load_combined_development(
    taxonomy: Taxonomy,
    bundles: tuple[tuple[str, Path, Path], ...],
    *,
    minimum_per_class: int = 30,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Return a provenance report and source-tag-free rows when all gates pass."""
    if not taxonomy.version.startswith("v") or not taxonomy.version[1:].isdigit():
        raise ValueError("training requires a frozen versioned taxonomy")
    if len(bundles) < 2 or len({name for name, _, _ in bundles}) != len(bundles):
        raise ValueError("at least two differently named bundles are required")
    if minimum_per_class < 1:
        raise ValueError("minimum class support must be positive")
    support: Counter[str] = Counter()
    seen_slugs: set[str] = set()
    seen_review_ids: set[str] = set()
    rows: list[dict[str, Any]] = []
    manifests: list[dict[str, Any]] = []
    archive_sha: str | None = None
    for name, bundle, annotation_path in bundles:
        manifest_path = bundle / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        if manifest["taxonomy_sha256"] != taxonomy.sha256:
            raise ValueError(f"taxonomy hash mismatch in {name}")
        if archive_sha is None:
            archive_sha = manifest["products_csv_sha256"]
        elif manifest["products_csv_sha256"] != archive_sha:
            raise ValueError(f"source archive hash mismatch in {name}")
        blind: dict[str, list[dict[str, Any]]] = {}
        for filename in BLIND_FILES.values():
            path = bundle / filename
            if sha256_file(path) != manifest["file_sha256"][filename]:
                raise ValueError(f"blind file hash mismatch in {name}: {filename}")
        # Verify heldout bytes by hash without parsing their product text.
        blind["development"] = json.loads((bundle / BLIND_FILES["development"]).read_text())
        annotations = json.loads(annotation_path.read_text())
        development_ids = {entry["review_id"] for entry in blind["development"]}
        if len(development_ids) != len(blind["development"]):
            raise ValueError(f"duplicate development review ID in {name}")
        if any(
            entry["decision"] == "unreviewed"
            for entry in annotations
            if entry["review_id"] in development_ids
        ):
            raise ValueError(f"development labels incomplete in {name}")
        if any(
            entry["decision"] != "unreviewed"
            for entry in annotations
            if entry["review_id"] not in development_ids
        ):
            raise ValueError(f"heldout annotations were opened before model freeze in {name}")
        key_path = bundle / "source-key.json"
        if sha256_file(key_path) != manifest["file_sha256"]["source-key.json"]:
            raise ValueError(f"source key hash mismatch in {name}")
        key_records = json.loads(key_path.read_text())
        key = {entry["review_id"]: entry for entry in key_records}
        for split in ("holdout_random", "holdout_stratified"):
            blind[split] = [
                {"review_id": entry["review_id"], "name": "", "tagline": "", "description": ""}
                for entry in key_records
                if entry["split"] == split
            ]
        if any(len(blind[split]) != manifest["selected"][split] for split in SPLITS):
            raise ValueError(f"reserved split counts differ from source key in {name}")
        counts = validate_annotations(blind, annotations, taxonomy)
        blind_ids = {record["review_id"] for split in SPLITS for record in blind[split]}
        if len(key) != len(key_records) or set(key) != blind_ids:
            raise ValueError(f"source key IDs mismatch in {name}")
        for split in SPLITS:
            for record in blind[split]:
                review_id = record["review_id"]
                slug = key[review_id]["slug"]
                if key[review_id]["split"] != split:
                    raise ValueError(f"source key split mismatch in {name}")
                if review_id in seen_review_ids or slug in seen_slugs:
                    raise ValueError(f"overlapping review ID or slug in {name}")
                seen_review_ids.add(review_id)
                seen_slugs.add(slug)
        by_id = {entry["review_id"]: entry for entry in annotations}
        for record in blind["development"]:
            review_id = record["review_id"]
            annotation = by_id[review_id]
            decision = annotation["decision"]
            category = annotation["primary_category"] if decision == "single" else None
            if category:
                support[category] += 1
            text = "\n".join(str(record[field]) for field in ("name", "tagline", "description"))
            rows.append(
                {
                    "slug": key[review_id]["slug"],
                    "name": record["name"],
                    "tagline": record["tagline"],
                    "description": record["description"],
                    "decision": decision,
                    "primary_category": category,
                    "co_primary_categories": annotation["co_primary_categories"],
                    "null_reason": annotation["null_reason"],
                    "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
                }
            )
        manifests.append(
            {
                "name": name,
                "manifest_sha256": sha256_file(manifest_path),
                "annotations_sha256": sha256_file(annotation_path),
                "development_decisions": counts["development"],
                "random_holdout_count": len(blind["holdout_random"]),
                "heldout_count": len(blind["holdout_random"]) + len(blind["holdout_stratified"]),
            }
        )
    shortfalls = {
        category: minimum_per_class - support[category]
        for category in taxonomy.category_names
        if support[category] < minimum_per_class
    }
    report = {
        "taxonomy_sha256": taxonomy.sha256,
        "source_archive_sha256": archive_sha,
        "bundles": manifests,
        "development_count": len(rows),
        "development_decision_counts": dict(
            sorted(Counter(row["decision"] for row in rows).items())
        ),
        "heldout_count": sum(item["heldout_count"] for item in manifests),
        "random_holdout_count": sum(item["random_holdout_count"] for item in manifests),
        "single_label_support": {
            category: support[category] for category in taxonomy.category_names
        },
        "minimum_development_per_class": minimum_per_class,
        "development_shortfalls": shortfalls,
        "train_gate_open": not shortfalls,
        "interpretation": "developmental support only; no model or population accuracy estimate",
    }
    return report, sorted(rows, key=lambda row: row["slug"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--taxonomy", type=Path, required=True)
    parser.add_argument(
        "--bundle",
        nargs=3,
        action="append",
        metavar=("NAME", "PATH", "ANNOTATIONS"),
        required=True,
    )
    parser.add_argument("--minimum-per-class", type=int, default=30)
    parser.add_argument(
        "--output", type=Path, help="ignored local development rows; refuse overwrite"
    )
    args = parser.parse_args()
    bundles = tuple(
        (name, Path(path), Path(annotations)) for name, path, annotations in args.bundle
    )
    report, rows = load_combined_development(
        load_taxonomy(args.taxonomy), bundles, minimum_per_class=args.minimum_per_class
    )
    if args.output:
        if not report["train_gate_open"]:
            raise ValueError("combined development class-support gate is closed")
        if args.output.exists():
            raise FileExistsError(args.output)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({"report": report, "rows": rows}, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
