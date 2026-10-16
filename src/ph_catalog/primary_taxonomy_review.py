"""Create a blinded, deterministic diagnostic review set for a taxonomy candidate.

This is a taxonomy-tuning sample, never a final classifier test sample.
Generated product records must remain in ignored local data, not Git.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

import duckdb

from ph_catalog.primary_taxonomy import Taxonomy, load_taxonomy, primary_from_sources


def rows_from_csv(path: Path):
    connection = duckdb.connect()
    cursor = connection.execute(
        "SELECT slug, name, tagline, description, categories::VARCHAR[] "
        "FROM read_csv_auto(?, sample_size=-1)",
        [str(path)],
    )
    while batch := cursor.fetchmany(10_000):
        yield from batch
    connection.close()


def rank(seed: str, slug: str) -> str:
    return hashlib.sha256(f"{seed}:{slug}".encode()).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def select_review(
    products_csv: Path,
    taxonomy: Taxonomy,
    *,
    seed: str,
    per_class: int,
    rare_per_class: int,
    rare_threshold: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    if per_class < 1 or rare_per_class < 0 or rare_threshold < 1:
        raise ValueError("invalid sample size or rare-source threshold")

    source_counts: Counter[str] = Counter()
    total = 0
    for _slug, _name, _tagline, _description, sources in rows_from_csv(products_csv):
        source_counts.update(set(sources or []))
        total += 1

    # Hold only the lowest hashed records per class and per rare source value.
    class_samples: dict[str, list[tuple[str, tuple]]] = {
        category: [] for category in taxonomy.category_names
    }
    rare_samples: dict[str, tuple[str, tuple]] = {}
    for row in rows_from_csv(products_csv):
        slug, _name, _tagline, _description, sources = row
        if not slug:
            continue
        category, outcome = primary_from_sources(sources or [], taxonomy)
        if outcome != "unique_source_mapping" or category is None:
            continue
        score = rank(seed, slug)
        sample = class_samples[category]
        sample.append((score, row))
        sample.sort(key=lambda value: value[0])
        del sample[per_class:]
        for source in sources or []:
            if source not in taxonomy.source_map or source_counts[source] > rare_threshold:
                continue
            previous = rare_samples.get(source)
            if previous is None or score < previous[0]:
                rare_samples[source] = score, row

    selected: dict[str, dict[str, Any]] = {}

    def add(row: tuple, stratum: str) -> None:
        slug, name, tagline, description, sources = row
        entry = selected.setdefault(
            slug,
            {
                "slug": slug,
                "name": name or "",
                "tagline": tagline or "",
                "description": description or "",
                "sources": sources or [],
                "strata": [],
            },
        )
        entry["strata"].append(stratum)

    for category, samples in class_samples.items():
        for _score, row in samples:
            add(row, f"class:{category}")

    by_class: dict[str, list[tuple[str, str, tuple]]] = {
        category: [] for category in taxonomy.category_names
    }
    for source, (score, row) in rare_samples.items():
        by_class[taxonomy.source_map[source]].append((score, source, row))
    for category, samples in by_class.items():
        for _score, source, row in sorted(samples)[:rare_per_class]:
            add(row, f"rare_source:{category}:{source}")

    blind = []
    key = []
    for slug, entry in sorted(selected.items(), key=lambda item: rank(seed, item[0])):
        category, _outcome = primary_from_sources(entry["sources"], taxonomy)
        review_id = rank(seed, slug)[:16]
        blind.append(
            {
                "review_id": review_id,
                "name": entry["name"],
                "tagline": entry["tagline"],
                "description": entry["description"],
                "review": {"primary_category": "", "evidence": "", "status": "unreviewed"},
            }
        )
        key.append(
            {
                "review_id": review_id,
                "slug": slug,
                "source_categories": entry["sources"],
                "source_mapping": category,
                "strata": sorted(entry["strata"]),
            }
        )
    manifest = {
        "purpose": "taxonomy tuning only; excluded from final classifier quality audit",
        "seed": seed,
        "taxonomy_version": taxonomy.version,
        "taxonomy_sha256": taxonomy.sha256,
        "products_csv_sha256": sha256_file(products_csv),
        "total_products": total,
        "per_class": per_class,
        "rare_per_class": rare_per_class,
        "rare_threshold": rare_threshold,
        "rare_source_values": sum(
            source in taxonomy.source_map and count <= rare_threshold
            for source, count in source_counts.items()
        ),
        "review_count": len(blind),
    }
    return blind, key, manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--taxonomy", type=Path, required=True)
    parser.add_argument("--products", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--seed", default="taxonomy-review-v1-2026-10-16")
    parser.add_argument("--per-class", type=int, default=5)
    parser.add_argument("--rare-per-class", type=int, default=2)
    parser.add_argument("--rare-threshold", type=int, default=10)
    args = parser.parse_args()
    blind, key, manifest = select_review(
        args.products,
        load_taxonomy(args.taxonomy),
        seed=args.seed,
        per_class=args.per_class,
        rare_per_class=args.rare_per_class,
        rare_threshold=args.rare_threshold,
    )
    outputs = ("blind-review.json", "source-key.json", "manifest.json")
    existing = [name for name in outputs if (args.output_dir / name).exists()]
    if existing:
        raise FileExistsError(
            f"review output already exists in {args.output_dir}: {existing}; "
            "choose a new output directory to preserve annotations"
        )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, value in (
        ("blind-review.json", blind),
        ("source-key.json", key),
        ("manifest.json", manifest),
    ):
        (args.output_dir / name).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
