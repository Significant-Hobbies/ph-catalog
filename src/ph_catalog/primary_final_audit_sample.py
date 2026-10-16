"""Reserve fresh blind Stage 7 random and model-stratified audit records.

This samples before any independent labels are opened. The random denominator
is the eligible archived mart; strata are a separate, model-selected diagnostic.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

import duckdb

from ph_catalog.primary_confidence_routing import route_mart
from ph_catalog.primary_heldout import FROZEN_MODEL_SHA, FROZEN_TAXONOMY_SHA
from ph_catalog.primary_taxonomy_review import sha256_file
from ph_catalog.primary_website_evidence import load_routes

SEED = "primary-stage7-independent-v1-2026-10-16"
RANDOM_COUNT = 200
SCREEN_COUNT = 5_000
PER_STRATUM = 3
OLD_BUNDLES = (
    "taxonomy-review-v1",
    "primary-label-v1-2026-10-16",
    "primary-label-v1-frozen-2026-10-16",
    "primary-label-v1-frozen-2026-10-16-r2",
)
FROZEN_BUNDLES = {
    "main": "primary-label-v1-frozen-2026-10-16-r3",
    "home": "primary-home-discovery-v1-2026-10-16",
    "sparse": "primary-sparse-discovery-v1-2026-10-16",
    "support": "primary-support-discovery-v1-2026-10-16",
}
ROUTE_COLUMNS = (
    "slug",
    "name",
    "tagline",
    "description",
    "website_url",
    "has_external_website",
    "entity_count",
    "trusted_label_count",
)
SEALED_FILES = frozenset({"blind-review.json", "source-key.json", "annotations-template.json"})


def _rank(purpose: str, slug: str) -> str:
    return hashlib.sha256(f"{SEED}:{purpose}:{slug}".encode()).hexdigest()


def _exclusions(data_root: Path, pilot_routes: Path) -> tuple[set[str], dict[str, str]]:
    excluded = set()
    hashes = {}
    for name in (*OLD_BUNDLES, *FROZEN_BUNDLES.values()):
        key = data_root / name / "source-key.json"
        hashes[name] = sha256_file(key)
        rows = json.loads(key.read_text())
        slugs = {row["slug"] for row in rows}
        if len(slugs) != len(rows) or excluded.intersection(slugs):
            raise ValueError(f"duplicate exclusion slug in {name}")
        excluded.update(slugs)
    hashes["stage5_pilot_routes"] = sha256_file(pilot_routes)
    pilot = [json.loads(line)["slug"] for line in pilot_routes.read_text().splitlines()]
    if len(pilot) != len(set(pilot)) or excluded.intersection(pilot):
        raise ValueError("pilot slugs overlap another excluded set")
    excluded.update(pilot)
    return excluded, hashes


def _band(confidence: float) -> str:
    if not 0 <= confidence <= 1:
        raise ValueError("route confidence outside [0,1]")
    return "low" if confidence < 0.5 else "middle" if confidence < 0.75 else "high"


def _select_strata(rows: list[dict], random_slugs: set[str]) -> tuple[list[dict], dict]:
    groups: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for row in rows:
        if row["slug"] in random_slugs:
            continue
        category = row["candidate_category"] or "abstained"
        group = (category, _band(float(row["confidence"])), row["next_step"])
        groups[group].append(row)
    selected = []
    support = {}
    for group, candidates in sorted(groups.items()):
        candidates.sort(key=lambda item: _rank("stratum", item["slug"]))
        chosen = candidates[:PER_STRATUM]
        selected.extend(chosen)
        support["|".join(group)] = {"screened": len(candidates), "selected": len(chosen)}
    return selected, support


def sample(
    source_mart: Path,
    taxonomy: Path,
    candidate_dir: Path,
    data_root: Path,
    pilot_routes: Path,
    output_dir: Path,
) -> dict:
    if output_dir.exists():
        raise FileExistsError(output_dir)
    excluded, exclusion_hashes = _exclusions(data_root, pilot_routes)
    source_sha = sha256_file(source_mart)
    source = duckdb.connect(str(source_mart), read_only=True)
    try:
        slugs = [row[0] for row in source.execute("SELECT slug FROM product_facts").fetchall()]
    finally:
        source.close()
    if len(slugs) != len(set(slugs)):
        raise ValueError("source mart has duplicate slugs")
    excluded_in_mart = len(set(slugs).intersection(excluded))
    eligible = [slug for slug in slugs if slug not in excluded]
    if len(eligible) < RANDOM_COUNT + SCREEN_COUNT:
        raise ValueError("not enough disjoint eligible products")
    eligible.sort(key=lambda slug: _rank("population", slug))
    random_slugs = eligible[:RANDOM_COUNT]
    screen_slugs = eligible[RANDOM_COUNT : RANDOM_COUNT + SCREEN_COUNT]
    selected_slugs = set(random_slugs + screen_slugs)
    output_dir.mkdir(parents=True)
    screen_mart = output_dir / "screen-mart.duckdb"
    source = duckdb.connect(str(source_mart), read_only=True)
    try:
        query = (
            "SELECT "
            + ",".join(ROUTE_COLUMNS)
            + " FROM product_facts WHERE slug IN (SELECT unnest(?)) ORDER BY slug"
        )
        products = source.execute(query, [list(selected_slugs)]).fetchall()
    finally:
        source.close()
    if len(products) != len(selected_slugs):
        raise ValueError("screening rows missing from source mart")
    mini = duckdb.connect(str(screen_mart))
    try:
        mini.execute(
            "CREATE TABLE product_facts (slug VARCHAR, name VARCHAR, tagline VARCHAR, "
            "description VARCHAR, website_url VARCHAR, has_external_website BOOLEAN, "
            "entity_count INTEGER, trusted_label_count INTEGER)"
        )
        mini.executemany("INSERT INTO product_facts VALUES (?, ?, ?, ?, ?, ?, ?, ?)", products)
        mini.execute("CHECKPOINT")
    finally:
        mini.close()
    bundles = tuple((name, data_root / directory) for name, directory in FROZEN_BUNDLES.items())
    routes_path = output_dir / "screen-routes.jsonl"
    route_report = route_mart(
        screen_mart,
        taxonomy,
        candidate_dir,
        routes_path,
        reservation_bundles=bundles,
    )
    rows = [json.loads(line) for line in routes_path.read_text().splitlines()]
    if len(rows) != len(selected_slugs) or {row["slug"] for row in rows} != selected_slugs:
        raise ValueError("frozen router changed audit screening membership")
    by_slug = {row["slug"]: row for row in rows}
    stratified, strata_support = _select_strata(rows, set(random_slugs))
    product_by_slug = {row[0]: dict(zip(ROUTE_COLUMNS, row, strict=True)) for row in products}
    selected = [("random", by_slug[slug]) for slug in random_slugs]
    selected.extend(("model_stratified", row) for row in stratified)
    blind = []
    key = []
    template = []
    for split, route in selected:
        slug = route["slug"]
        source_row = product_by_slug[slug]
        review_id = _rank("blind", slug)[:20]
        blind.append(
            {
                "review_id": review_id,
                "name": source_row["name"],
                "tagline": source_row["tagline"],
                "description": source_row["description"],
            }
        )
        key.append(
            {
                "review_id": review_id,
                "slug": slug,
                "split": split,
                "stage4_path": route["next_step"],
                "candidate_category": route["candidate_category"],
                "confidence_band": _band(float(route["confidence"])),
                "confidence": route["confidence"],
                "source_text_sha256": route["evidence_hash"],
            }
        )
        template.append(
            {
                "review_id": review_id,
                "decision": "unreviewed",
                "primary_category": None,
                "co_primary_categories": [],
                "evidence": {},
                "null_reason": None,
                "reviewer_id": None,
            }
        )
    if len({row["review_id"] for row in blind}) != len(blind):
        raise ValueError("blind review ID collision")
    for name, content in (
        ("blind-review.json", blind),
        ("source-key.json", key),
        ("annotations-template.json", template),
    ):
        (output_dir / name).write_text(json.dumps(content, ensure_ascii=False, indent=2) + "\n")
    report = {
        "status": "reserved, unreviewed final audit; no accuracy estimate",
        "seed": SEED,
        "sampler_code_sha256": sha256_file(Path(__file__)),
        "source_mart_sha256": source_sha,
        "screen_mart_sha256": sha256_file(screen_mart),
        "route_output_sha256": route_report["output_sha256"],
        "route_manifest_sha256": sha256_file(routes_path.with_suffix(".jsonl.manifest.json")),
        "taxonomy_sha256": FROZEN_TAXONOMY_SHA,
        "model_sha256": FROZEN_MODEL_SHA,
        "exclusion_file_sha256": exclusion_hashes,
        "population_count": len(slugs),
        "excluded_distinct_slugs": len(excluded),
        "excluded_in_mart": excluded_in_mart,
        "eligible_random_denominator": len(eligible),
        "random_count": len(random_slugs),
        "screening_count": len(screen_slugs),
        "model_stratified_count": len(stratified),
        "stage4_paths": dict(Counter(row["stage4_path"] for row in key)),
        "strata_support": strata_support,
        "file_sha256": {name: sha256_file(output_dir / name) for name in sorted(SEALED_FILES)},
    }
    (output_dir / "manifest.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def check(source_mart: Path, data_root: Path, pilot_routes: Path, output_dir: Path) -> dict:
    """Recompute the frame, selection and blind/key seal without reading labels."""
    report = json.loads((output_dir / "manifest.json").read_text())
    excluded, exclusion_hashes = _exclusions(data_root, pilot_routes)
    if (
        report["seed"] != SEED
        or report["sampler_code_sha256"] != sha256_file(Path(__file__))
        or report["taxonomy_sha256"] != FROZEN_TAXONOMY_SHA
        or report["model_sha256"] != FROZEN_MODEL_SHA
        or set(report["file_sha256"]) != SEALED_FILES
        or report["source_mart_sha256"] != sha256_file(source_mart)
        or report["screen_mart_sha256"] != sha256_file(output_dir / "screen-mart.duckdb")
        or report["exclusion_file_sha256"] != exclusion_hashes
        or any(
            sha256_file(output_dir / name) != digest
            for name, digest in report["file_sha256"].items()
        )
    ):
        raise ValueError("final audit file or exclusion provenance changed")
    source = duckdb.connect(str(source_mart), read_only=True)
    try:
        slugs = [row[0] for row in source.execute("SELECT slug FROM product_facts").fetchall()]
    finally:
        source.close()
    eligible = [slug for slug in slugs if slug not in excluded]
    eligible.sort(key=lambda slug: _rank("population", slug))
    random_slugs = eligible[:RANDOM_COUNT]
    screened_slugs = set(eligible[: RANDOM_COUNT + SCREEN_COUNT])
    if (
        len(slugs) != report["population_count"]
        or len(set(slugs)) != len(slugs)
        or len(excluded) != report["excluded_distinct_slugs"]
        or len(set(slugs).intersection(excluded)) != report["excluded_in_mart"]
        or len(eligible) != report["eligible_random_denominator"]
    ):
        raise ValueError("final audit random denominator changed")
    screen_mart = duckdb.connect(str(output_dir / "screen-mart.duckdb"), read_only=True)
    try:
        screen_rows = screen_mart.execute(
            "SELECT slug,name,tagline,description FROM product_facts"
        ).fetchall()
    finally:
        screen_mart.close()
    by_slug = {row[0]: row for row in screen_rows}
    if set(by_slug) != screened_slugs or len(by_slug) != len(screen_rows):
        raise ValueError("audit screening mart membership changed")
    route_path = output_dir / "screen-routes.jsonl"
    route_manifest = route_path.with_suffix(".jsonl.manifest.json")
    bundles = tuple((name, data_root / directory) for name, directory in FROZEN_BUNDLES.items())
    _, routing_report = load_routes(route_path, route_manifest, bundles)
    if (
        report["route_output_sha256"] != sha256_file(route_path)
        or report["route_manifest_sha256"] != sha256_file(route_manifest)
        or routing_report["source_mart_sha256"] != report["screen_mart_sha256"]
    ):
        raise ValueError("audit router output changed")
    routes = [json.loads(line) for line in route_path.read_text().splitlines()]
    if {row["slug"] for row in routes} != screened_slugs or len(routes) != len(screened_slugs):
        raise ValueError("audit router screening membership changed")
    route_by_slug = {row["slug"]: row for row in routes}
    stratified, support = _select_strata(routes, set(random_slugs))
    expected = [("random", slug) for slug in random_slugs]
    expected.extend(("model_stratified", row["slug"]) for row in stratified)
    blind = json.loads((output_dir / "blind-review.json").read_text())
    key = json.loads((output_dir / "source-key.json").read_text())
    template = json.loads((output_dir / "annotations-template.json").read_text())
    if (
        [(row["split"], row["slug"]) for row in key] != expected
        or len(blind) != len(key)
        or len(template) != len(key)
        or report["strata_support"] != support
        or report["random_count"] != len(random_slugs)
        or report["screening_count"] != SCREEN_COUNT
        or report["model_stratified_count"] != len(stratified)
        or report["stage4_paths"] != dict(Counter(row["stage4_path"] for row in key))
    ):
        raise ValueError("final audit selection changed")
    for b, k, t in zip(blind, key, template, strict=True):
        row = by_slug[k["slug"]]
        route = route_by_slug[k["slug"]]
        if (
            b
            != {
                "review_id": k["review_id"],
                "name": row[1],
                "tagline": row[2],
                "description": row[3],
            }
            or t
            != {
                "review_id": k["review_id"],
                "decision": "unreviewed",
                "primary_category": None,
                "co_primary_categories": [],
                "evidence": {},
                "null_reason": None,
                "reviewer_id": None,
            }
            or k["review_id"] != _rank("blind", k["slug"])[:20]
            or k["stage4_path"] != route["next_step"]
            or k["candidate_category"] != route["candidate_category"]
            or k["confidence_band"] != _band(float(route["confidence"]))
            or k["confidence"] != route["confidence"]
            or k["source_text_sha256"] != route["evidence_hash"]
        ):
            raise ValueError("final audit blind records or label seal changed")
    return {
        "status": "verified fresh, disjoint, unreviewed audit reservation",
        "random_count": len(random_slugs),
        "stratified_count": len(stratified),
        "eligible_random_denominator": len(eligible),
        "blind_sha256": report["file_sha256"]["blind-review.json"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-mart", type=Path, required=True)
    parser.add_argument("--taxonomy", type=Path, required=True)
    parser.add_argument("--candidate-dir", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--pilot-routes", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            sample(
                args.source_mart,
                args.taxonomy,
                args.candidate_dir,
                args.data_root,
                args.pilot_routes,
                args.output_dir,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
