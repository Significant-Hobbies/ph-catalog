"""Pin Stage 4 routes for exactly the sealed Stage 7 audit records."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb

from ph_catalog.primary_confidence_routing import route_mart
from ph_catalog.primary_final_audit_sample import FROZEN_BUNDLES, ROUTE_COLUMNS, check
from ph_catalog.primary_taxonomy_review import sha256_file


def prepare(
    source_mart: Path,
    taxonomy: Path,
    candidate_dir: Path,
    data_root: Path,
    pilot_routes: Path,
    audit_bundle: Path,
    output_dir: Path,
) -> dict:
    """Replay the sealed selection, then route only its 320 records."""
    if output_dir.exists():
        raise FileExistsError(output_dir)
    verified = check(source_mart, data_root, pilot_routes, audit_bundle)
    key = json.loads((audit_bundle / "source-key.json").read_text())
    selected_slugs = {row["slug"] for row in key}
    if len(selected_slugs) != len(key) or len(key) != 320:
        raise ValueError("audit key must contain 320 distinct products")
    screening = {
        row["slug"]: row
        for row in map(json.loads, (audit_bundle / "screen-routes.jsonl").read_text().splitlines())
        if row["slug"] in selected_slugs
    }
    if len(screening) != len(key):
        raise ValueError("selected products missing from pinned Stage 4 screening")
    output_dir.mkdir(parents=True)
    mini_path = output_dir / "selected-mart.duckdb"
    source = duckdb.connect(str(source_mart), read_only=True)
    try:
        products = source.execute(
            "SELECT "
            + ",".join(ROUTE_COLUMNS)
            + " FROM product_facts WHERE slug IN (SELECT unnest(?)) ORDER BY slug",
            [list(selected_slugs)],
        ).fetchall()
    finally:
        source.close()
    if len(products) != len(key):
        raise ValueError("selected products missing from source mart")
    mini = duckdb.connect(str(mini_path))
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
    routes_path = output_dir / "selected-routes.jsonl"
    bundles = tuple((name, data_root / directory) for name, directory in FROZEN_BUNDLES.items())
    report = route_mart(
        mini_path,
        taxonomy,
        candidate_dir,
        routes_path,
        reservation_bundles=bundles,
    )
    routes = [json.loads(line) for line in routes_path.read_text().splitlines()]
    if len(routes) != len(key) or any(screening.get(row["slug"]) != row for row in routes):
        raise ValueError("selected Stage 4 replay differs from frozen screening")
    manifest = {
        "status": "selected Stage 4 audit paths only; gold unopened",
        "audit_manifest_sha256": sha256_file(audit_bundle / "manifest.json"),
        "audit_blind_sha256": verified["blind_sha256"],
        "audit_key_sha256": sha256_file(audit_bundle / "source-key.json"),
        "preparation_code_sha256": sha256_file(Path(__file__)),
        "selected_mart_sha256": sha256_file(mini_path),
        "selected_route_output_sha256": report["output_sha256"],
        "selected_route_manifest_sha256": sha256_file(
            routes_path.with_suffix(".jsonl.manifest.json")
        ),
        "selected_count": len(routes),
        "candidate_accept": sum(row["next_step"] == "candidate_accept" for row in routes),
        "website_evidence_candidate": sum(
            row["next_step"] == "website_evidence_candidate" for row in routes
        ),
        "non_web_review": sum(row["next_step"] == "non_web_review" for row in routes),
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-mart", type=Path, required=True)
    parser.add_argument("--taxonomy", type=Path, required=True)
    parser.add_argument("--candidate-dir", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--pilot-routes", type=Path, required=True)
    parser.add_argument("--audit-bundle", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            prepare(
                args.source_mart,
                args.taxonomy,
                args.candidate_dir,
                args.data_root,
                args.pilot_routes,
                args.audit_bundle,
                args.output_dir,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
