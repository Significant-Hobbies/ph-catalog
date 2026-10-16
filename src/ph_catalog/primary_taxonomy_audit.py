"""Audit source-category coverage without changing source data or training a model."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import duckdb

from ph_catalog.primary_taxonomy import (
    load_taxonomy,
    normalized_source_value,
    primary_from_sources,
)


def audit(
    taxonomy_path: Path,
    products_csv: Path,
    *,
    require_complete_source_snapshot: bool = True,
) -> dict[str, object]:
    taxonomy = load_taxonomy(taxonomy_path)
    connection = duckdb.connect()
    source_counts: Counter[str] = Counter()
    class_counts: Counter[str] = Counter()
    outcomes: Counter[str] = Counter()
    categorized_products = 0
    cursor = connection.execute(
        "SELECT slug, categories::VARCHAR[] FROM read_csv_auto(?, sample_size=-1)",
        [str(products_csv)],
    )
    while rows := cursor.fetchmany(10_000):
        for _slug, source_values in rows:
            sources = source_values or []
            if sources:
                categorized_products += 1
            source_counts.update(set(sources))
            primary, outcome = primary_from_sources(sources, taxonomy)
            outcomes[outcome] += 1
            if primary:
                class_counts[primary] += 1
    absent = sorted(set(taxonomy.source_map) - set(source_counts))
    if absent and require_complete_source_snapshot:
        raise ValueError(f"mapped source categories absent from snapshot: {absent}")
    normalized_mapped = {normalized_source_value(source) for source in taxonomy.source_map}
    mixed_case = sorted(
        source
        for source in source_counts
        if source not in taxonomy.source_map
        and normalized_source_value(source) in normalized_mapped
    )
    if mixed_case:
        raise ValueError(f"case-equivalent source categories mapped and unmapped: {mixed_case}")
    return {
        "taxonomy_version": taxonomy.version,
        "taxonomy_sha256": taxonomy.sha256,
        "source_snapshot": taxonomy.source_snapshot,
        "source_category_values": len(source_counts),
        "mapped_source_values": len(taxonomy.source_map),
        "categorized_products": categorized_products,
        "total_products": sum(outcomes.values()),
        "unmapped_source_values": [
            {"source": source, "assignments": count}
            for source, count in sorted(source_counts.items(), key=lambda item: (-item[1], item[0]))
            if source not in taxonomy.source_map
        ],
        "product_outcomes": dict(sorted(outcomes.items())),
        "uniquely_labeled_products_by_category": dict(sorted(class_counts.items())),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--taxonomy", type=Path, required=True)
    parser.add_argument("--products", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.taxonomy, args.products)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    brief = {key: value for key, value in result.items() if key != "unmapped_source_values"}
    print(json.dumps(brief, indent=2))


if __name__ == "__main__":
    main()
