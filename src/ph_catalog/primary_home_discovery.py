"""Reserve blinded product-text candidates for sparse home/lifestyle labels.

Selection reads only product text. The groups find candidates for adjudication;
they are not labels, training examples, or a representative evaluation sample.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from ph_catalog.primary_label_protocol import _excluded_slugs, write_bundle
from ph_catalog.primary_taxonomy import load_taxonomy
from ph_catalog.primary_taxonomy_review import rank, sha256_file

PATTERNS = {
    "living_space": (
        r"\b(?:apartment|roommate|housing|room rental|"
        r"rent(?:al|ing)? (?:a )?(?:home|house|room|apartment)|"
        r"house hunting|housing search|find (?:a|your) (?:home|house|room)|"
        r"property search)\b"
    ),
    "home_improvement": (
        r"\b(?:interior design|home decor|home improvement|home repair|"
        r"renovation|remodel|floor plan|garden design|landscaping|"
        r"kitchen design|home layout)\b"
    ),
    "food_garden": (
        r"\b(?:recipes?|meal plan|home cooking|gardening|plant care|"
        r"planting calendar|vegetable garden|food planning)\b"
    ),
    "family_life": (
        r"\b(?:family organizer|family calendar|household|parenting|"
        r"co-parenting|family chores|family planning|family life|pet care)\b"
    ),
}


def text_rows(products_csv: Path) -> Iterator[tuple[str, str, str, str]]:
    """Read only slug and product text; never extract source-category columns."""
    with products_csv.open(newline="") as stream:
        reader = csv.DictReader(stream)
        if not {"slug", "name", "tagline", "description"} <= set(reader.fieldnames or []):
            raise ValueError("product archive lacks required text fields")
        seen: set[str] = set()
        for record in reader:
            slug = record["slug"]
            if not slug or slug in seen:
                raise ValueError(f"missing or duplicate product slug: {slug!r}")
            seen.add(slug)
            yield (
                slug,
                record["name"] or "",
                record["tagline"] or "",
                record["description"] or "",
            )


def select_home_discovery(
    products_csv: Path,
    taxonomy_path: Path,
    exclusion_keys: tuple[Path, ...],
    *,
    seed: str,
    development_per_group: int = 40,
    heldout_per_group: int = 20,
) -> tuple[dict[str, list[dict[str, str]]], list[dict[str, str]], dict[str, Any]]:
    return select_text_discovery(
        products_csv,
        taxonomy_path,
        exclusion_keys,
        patterns=PATTERNS,
        protocol="home-text-discovery-v1",
        purpose="supplemental product-text discovery; groups are not true labels",
        seed=seed,
        development_per_group=development_per_group,
        heldout_per_group=heldout_per_group,
    )


def select_text_discovery(
    products_csv: Path,
    taxonomy_path: Path,
    exclusion_keys: tuple[Path, ...],
    *,
    patterns: dict[str, str],
    protocol: str,
    purpose: str,
    seed: str,
    development_per_group: int = 40,
    heldout_per_group: int = 20,
) -> tuple[dict[str, list[dict[str, str]]], list[dict[str, str]], dict[str, Any]]:
    """Reserve disjoint, title-matched candidates without reading source tags."""
    if not seed or development_per_group < 1 or heldout_per_group < 1:
        raise ValueError("seed and sample sizes must be positive")
    if not patterns or not protocol or not purpose:
        raise ValueError("patterns, protocol, and purpose are required")
    if not exclusion_keys:
        raise ValueError("previous sample keys are required for disjoint selection")
    taxonomy = load_taxonomy(taxonomy_path)
    if taxonomy.version != "v1":
        raise ValueError("text discovery requires frozen v1 taxonomy")
    exclusions = [_excluded_slugs(path) for path in exclusion_keys]
    excluded = set().union(*exclusions)
    compiled = {group: re.compile(pattern, re.IGNORECASE) for group, pattern in patterns.items()}
    pools: dict[str, list[tuple[str, str, str, str]]] = {group: [] for group in patterns}
    total = 0
    for row in text_rows(products_csv):
        total += 1
        if row[0] in excluded:
            continue
        title = " ".join(row[1:3])
        for group, pattern in compiled.items():
            if pattern.search(title):
                pools[group].append(row)

    chosen = set(excluded)
    selected: dict[str, list[tuple[str, tuple[str, str, str, str]]]] = {
        "development": [],
        "holdout_stratified": [],
    }
    selection_counts: dict[str, Counter[str]] = {
        "development": Counter(),
        "holdout_stratified": Counter(),
    }
    for split, limit in (
        ("holdout_stratified", heldout_per_group),
        ("development", development_per_group),
    ):
        for group, rows in pools.items():
            ranked = sorted(rows, key=lambda row: rank(f"{seed}:{split}:{group}", row[0]))
            for row in ranked:
                if row[0] in chosen:
                    continue
                selected[split].append((group, row))
                selection_counts[split][group] += 1
                chosen.add(row[0])
                if selection_counts[split][group] == limit:
                    break

    blind: dict[str, list[dict[str, str]]] = {
        "development": [],
        "holdout_random": [],
        "holdout_stratified": [],
    }
    key: list[dict[str, str]] = []
    ids: set[str] = set()
    for split in ("development", "holdout_stratified"):
        for group, (slug, name, tagline, description) in sorted(
            selected[split], key=lambda entry: rank(f"{seed}:{split}:output", entry[1][0])
        ):
            review_id = rank(f"{seed}:review-id", slug)[:20]
            if review_id in ids:
                raise ValueError("review ID collision")
            ids.add(review_id)
            blind[split].append(
                {
                    "review_id": review_id,
                    "name": name,
                    "tagline": tagline,
                    "description": description,
                }
            )
            key.append({"review_id": review_id, "slug": slug, "split": split, "group": group})

    manifest = {
        "protocol": protocol,
        "purpose": purpose,
        "taxonomy_version": taxonomy.version,
        "taxonomy_sha256": taxonomy.sha256,
        "products_csv_sha256": sha256_file(products_csv),
        "exclusion_key_sha256": [sha256_file(path) for path in exclusion_keys],
        "excluded_distinct_slugs": len(excluded),
        "seed": seed,
        "total_products": total,
        "title_patterns": patterns,
        "candidate_pool_size_by_group": {group: len(rows) for group, rows in pools.items()},
        "requested_per_group": {
            "development": development_per_group,
            "holdout_stratified": heldout_per_group,
        },
        "selected_by_group": {
            split: dict(sorted(counts.items())) for split, counts in selection_counts.items()
        },
        "selected": {split: len(rows) for split, rows in blind.items()},
        "limitations": (
            "name/tagline keyword discovery is biased; blind independent product-text labels "
            "are required before any true class support or metric is claimed"
        ),
    }
    return blind, key, manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--taxonomy", type=Path, required=True)
    parser.add_argument("--products", type=Path, required=True)
    parser.add_argument("--exclude-key", type=Path, action="append", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--seed", default="home-text-discovery-v1-2026-10-16")
    parser.add_argument("--development-per-group", type=int, default=40)
    parser.add_argument("--heldout-per-group", type=int, default=20)
    args = parser.parse_args()
    blind, key, manifest = select_home_discovery(
        args.products,
        args.taxonomy,
        tuple(args.exclude_key),
        seed=args.seed,
        development_per_group=args.development_per_group,
        heldout_per_group=args.heldout_per_group,
    )
    write_bundle(args.output_dir, blind, key, manifest)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
