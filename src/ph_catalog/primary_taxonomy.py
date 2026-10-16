"""Conservative, versioned primary-category mapping from Product Hunt evidence."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Taxonomy:
    version: str
    source_snapshot: str
    category_names: dict[str, str]
    source_map: dict[str, str]
    rationales: dict[str, str]
    sha256: str


def load_taxonomy(path: Path) -> Taxonomy:
    raw = path.read_bytes()
    document = json.loads(raw)
    categories = document["categories"]
    if not 12 <= len(categories) <= 18:
        raise ValueError("primary taxonomy must have 12–18 categories")
    names: dict[str, str] = {}
    mapping: dict[str, str] = {}
    rationales: dict[str, str] = {}
    for category in categories:
        category_id = category["id"]
        if not category_id or category_id in names:
            raise ValueError(f"duplicate or empty primary category: {category_id!r}")
        if not category["boundary"].strip() or not category["rationale"].strip():
            raise ValueError(f"missing boundary or mapping rationale: {category_id}")
        names[category_id] = category["name"]
        for source in category["source_categories"]:
            if not source or source != source.strip() or source in mapping:
                raise ValueError(f"duplicate or malformed source category: {source!r}")
            mapping[source] = category_id
            rationales[source] = category["rationale"]
    return Taxonomy(
        version=document["version"],
        source_snapshot=document["source_snapshot"],
        category_names=names,
        source_map=mapping,
        rationales=rationales,
        sha256=hashlib.sha256(raw).hexdigest(),
    )


def primary_from_sources(
    source_categories: list[str], taxonomy: Taxonomy
) -> tuple[str | None, str]:
    """Return a label only when all mapped source evidence agrees."""
    mapped = set()
    for source in source_categories:
        if source in taxonomy.source_map:
            mapped.add(taxonomy.source_map[source])
    if len(mapped) == 1:
        return next(iter(mapped)), "unique_source_mapping"
    if mapped:
        return None, "conflicting_source_categories"
    return None, "no_unambiguous_source_category"
