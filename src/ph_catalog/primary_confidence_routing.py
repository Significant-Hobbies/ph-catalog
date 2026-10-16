"""Route uncertain frozen-v1 primary-category candidates to later evidence stages.

This is a candidate policy, not promotion: independent heldout validation is
still required before any primary category is published.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

import duckdb

from ph_catalog.primary_classifier import _top_two, text_input
from ph_catalog.primary_heldout import (
    FROZEN_SAMPLE_MANIFESTS,
    FROZEN_TAXONOMY_SHA,
    load_candidate,
)
from ph_catalog.primary_taxonomy import load_taxonomy
from ph_catalog.primary_taxonomy_review import sha256_file

ROUTING_POLICY = "primary-confidence-routing-v1-candidate"
PLACEHOLDER = re.compile(r"\b(?:lorem ipsum|coming soon|under construction|tbd)\b", re.I)
FIELD_MINIMUM = {"tagline": 25, "description": 80}
FIELD_CONFIDENCE_FLOOR = 0.75
FIELD_MARGIN_FLOOR = 0.15
MINIMUM_SOURCE_CHARS = 40


def reserved_slugs(bundles: tuple[tuple[str, Path], ...]) -> set[str]:
    """Exclude every frozen development/holdout slug from routing rehearsals."""
    if len(bundles) != 3 or {name for name, _ in bundles} != set(FROZEN_SAMPLE_MANIFESTS):
        raise ValueError("all three frozen reservation bundles must be excluded")
    slugs = set()
    for name, bundle in bundles:
        manifest_path = bundle / "manifest.json"
        if sha256_file(manifest_path) != FROZEN_SAMPLE_MANIFESTS[name]:
            raise ValueError(f"frozen sample manifest changed in {name}")
        manifest = json.loads(manifest_path.read_text())
        key_path = bundle / "source-key.json"
        if sha256_file(key_path) != manifest["file_sha256"]["source-key.json"]:
            raise ValueError(f"frozen source key changed in {name}")
        records = json.loads(key_path.read_text())
        local = {record["slug"] for record in records}
        if len(local) != len(records) or slugs.intersection(local):
            raise ValueError(f"duplicate reserved slug in {name}")
        slugs.update(local)
    return slugs


def quality_flags(row: dict[str, Any]) -> list[str]:
    """Route only explicit weak-copy patterns, never infer a market from them."""
    name = str(row["name"] or "").strip()
    tagline = str(row["tagline"] or "").strip()
    description = str(row["description"] or "").strip()
    flags = []
    source_chars = sum(not char.isspace() for char in tagline + description)
    if not name or source_chars < MINIMUM_SOURCE_CHARS:
        flags.append("insufficient_source_text")
    if PLACEHOLDER.search(tagline) or PLACEHOLDER.search(description):
        flags.append("placeholder_copy")
    if len(tagline) >= 25 and tagline.casefold() == description.casefold():
        flags.append("duplicated_copy")
    return flags


def field_disagreements(model: Any, rows: list[dict[str, Any]]) -> list[bool]:
    """Batch strong field-only disagreement checks; never use them as labels."""
    texts: list[str] = []
    eligible: list[int] = []
    for index, row in enumerate(rows):
        fields = [str(row[field] or "").strip() for field in FIELD_MINIMUM]
        if all(
            len(value) >= minimum
            for value, minimum in zip(fields, FIELD_MINIMUM.values(), strict=True)
        ):
            eligible.append(index)
            texts.extend(fields)
    result = [False] * len(rows)
    if not texts:
        return result
    predictions = model.predict_proba(texts)
    for position, row_index in enumerate(eligible):
        strong = []
        for probabilities in predictions[position * 2 : position * 2 + 2]:
            category, _, confidence, margin = _top_two(
                list(model.classes_), list(map(float, probabilities))
            )
            if confidence < FIELD_CONFIDENCE_FLOOR or margin < FIELD_MARGIN_FLOOR:
                break
            strong.append(category)
        result[row_index] = len(strong) == 2 and strong[0] != strong[1]
    return result


def route_candidate(
    row: dict[str, Any],
    probabilities: list[float],
    classes: list[str],
    thresholds: dict[str, Any],
    *,
    fields_disagree: bool,
) -> dict[str, Any]:
    """Accept clean strong candidates locally; route only concrete uncertainty."""
    top, runner_up, confidence, margin = _top_two(classes, probabilities)
    category = (
        top if confidence >= thresholds["confidence"] and margin >= thresholds["margin"] else None
    )
    reasons = quality_flags(row)
    if category is None:
        reasons.append("classifier_abstained")
    if fields_disagree:
        reasons.append("tagline_description_disagreement")
    entity_count = int(row["entity_count"])
    trusted_label_count = int(row["trusted_label_count"])
    if entity_count < 0 or trusted_label_count < 0:
        raise ValueError("negative auxiliary evidence count")
    if category is None and not entity_count and not trusted_label_count:
        reasons.append("no_auxiliary_labels")
    website_url = str(row["website_url"] or "")
    has_external_website = bool(row["has_external_website"])
    routed = bool(reasons)
    return {
        "slug": row["slug"],
        "primary_category": category if not routed else None,
        "candidate_category": category,
        "runner_up": runner_up,
        "confidence": confidence,
        "margin": margin,
        "method": "local_classifier",
        "routing_policy": ROUTING_POLICY,
        "route": routed,
        "reasons": reasons,
        "next_step": (
            "candidate_accept"
            if not routed
            else "website_evidence_candidate"
            if website_url and has_external_website
            else "non_web_review"
        ),
        "website_url": website_url if has_external_website else None,
        "entity_count": entity_count,
        "trusted_label_count": trusted_label_count,
        "evidence_hash": hashlib.sha256(text_input(row).encode()).hexdigest(),
    }


def route_mart(
    mart_path: Path,
    taxonomy_path: Path,
    candidate_dir: Path,
    output: Path,
    *,
    batch_size: int = 1_000,
    limit: int | None = None,
    reservation_bundles: tuple[tuple[str, Path], ...],
) -> dict[str, Any]:
    """Stream mart products through the pinned candidate and write atomic JSONL."""
    from threadpoolctl import threadpool_limits

    if batch_size < 1 or batch_size > 5_000 or limit is not None and limit < 1:
        raise ValueError("invalid routing batch size or limit")
    excluded_slugs = reserved_slugs(reservation_bundles)
    manifest_output = output.with_suffix(output.suffix + ".manifest.json")
    if (
        output.exists()
        or output.with_suffix(output.suffix + ".partial").exists()
        or manifest_output.exists()
    ):
        raise FileExistsError(output)
    taxonomy = load_taxonomy(taxonomy_path)
    if taxonomy.sha256 != FROZEN_TAXONOMY_SHA or taxonomy.version != "v1":
        raise ValueError("routing requires frozen v1 taxonomy")
    model, thresholds, hashes = load_candidate(taxonomy, candidate_dir)
    partial = output.with_suffix(output.suffix + ".partial")
    output.parent.mkdir(parents=True, exist_ok=True)
    counts = {"seen": 0, "excluded": 0, "written": 0, "routed": 0, "candidate_accept": 0}
    connection = duckdb.connect(str(mart_path), read_only=True)
    cursor = ""
    try:
        with partial.open("w") as handle, threadpool_limits(limits=1):
            while True:
                records = connection.execute(
                    """
                    SELECT slug, name, tagline, description, website_url,
                           has_external_website, entity_count, trusted_label_count
                    FROM product_facts
                    WHERE slug > ?
                    ORDER BY slug LIMIT ?
                    """,
                    [cursor, batch_size],
                ).fetchall()
                if not records:
                    break
                cursor = records[-1][0]
                counts["seen"] += len(records)
                rows = [
                    dict(
                        zip(
                            (
                                "slug",
                                "name",
                                "tagline",
                                "description",
                                "website_url",
                                "has_external_website",
                                "entity_count",
                                "trusted_label_count",
                            ),
                            record,
                            strict=True,
                        )
                    )
                    for record in records
                    if record[0] not in excluded_slugs
                ]
                counts["excluded"] += len(records) - len(rows)
                if limit is not None:
                    rows = rows[: max(0, limit - counts["written"])]
                if rows:
                    probabilities = model.predict_proba([text_input(row) for row in rows])
                    disagreements = field_disagreements(model, rows)
                    for row, values, disagree in zip(
                        rows, probabilities, disagreements, strict=True
                    ):
                        result = route_candidate(
                            row,
                            list(map(float, values)),
                            list(model.classes_),
                            thresholds,
                            fields_disagree=disagree,
                        )
                        handle.write(json.dumps(result, ensure_ascii=False) + "\n")
                        counts["written"] += 1
                        counts["routed" if result["route"] else "candidate_accept"] += 1
                if limit is not None and counts["written"] >= limit:
                    break
        os.replace(partial, output)
    finally:
        connection.close()
    report = {
        **counts,
        "taxonomy_sha256": taxonomy.sha256,
        **hashes,
        "routing_policy": ROUTING_POLICY,
        "routing_code_sha256": sha256_file(Path(__file__)),
        "source_mart_sha256": sha256_file(mart_path),
        "reserved_slug_exclusion_count": len(excluded_slugs),
        "output_sha256": sha256_file(output),
        "status": "development candidate; independent heldout validation pending",
    }
    manifest_output.write_text(json.dumps(report, indent=2) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mart", type=Path, required=True)
    parser.add_argument("--taxonomy", type=Path, required=True)
    parser.add_argument("--candidate-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=1_000)
    parser.add_argument("--limit", type=int)
    parser.add_argument(
        "--exclude-bundle",
        nargs=2,
        action="append",
        required=True,
        metavar=("NAME", "PATH"),
    )
    args = parser.parse_args()
    print(
        json.dumps(
            route_mart(
                args.mart,
                args.taxonomy,
                args.candidate_dir,
                args.output,
                batch_size=args.batch_size,
                limit=args.limit,
                reservation_bundles=tuple((name, Path(path)) for name, path in args.exclude_bundle),
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
