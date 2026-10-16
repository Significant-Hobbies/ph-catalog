"""Pin unresolved Stage 4/5 candidates for later, non-promoting review.

Only fetched website routes and non-web routes enter this provisional handoff.
An unfetched website route remains queued for Stage 5 instead of bypassing it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

from ph_catalog.primary_heldout import (
    FROZEN_MODEL_SHA,
    FROZEN_TAXONOMY_SHA,
    FROZEN_THRESHOLDS_SHA,
)
from ph_catalog.primary_taxonomy_review import sha256_file
from ph_catalog.primary_website_evidence import load_routes

HANDOFF_POLICY = "primary-stage5-unresolved-v1-candidate"


def _evidence_rows(path: Path, route_hash: str, candidates: dict[str, dict]) -> dict[str, dict]:
    evidence = {}
    for line in path.read_bytes().splitlines():
        row = json.loads(line)
        slug = row["slug"]
        route = candidates.get(slug)
        if slug in evidence or route is None:
            raise ValueError("duplicate or unreserved website evidence row")
        if (
            row["routing_output_sha256"] != route_hash
            or row["product_text_sha256"] != route["evidence_hash"]
            or row["requested_url"] != route["website_url"]
        ):
            raise ValueError("website evidence does not match its pinned route")
        secondary = row.get("secondary_page")
        for field in row["fields"]:
            page = row if field["page_role"] == "primary" else secondary
            if (
                page is None
                or field["page_role"] not in {"primary", "secondary"}
                or field["source_url"] != page["final_url"]
                or field["response_sha256"] != page["response_sha256"]
                or not field["fetched_at"]
                or not field["text"]
                or field["outcome"] != page["outcome"]
            ):
                raise ValueError("website field lacks matching page provenance")
        evidence[slug] = {"row": row, "sha256": hashlib.sha256(line).hexdigest()}
    return evidence


def run(
    routes: Path,
    route_manifest_path: Path,
    website_evidence: Path,
    website_manifest_path: Path,
    output: Path,
    bundles: tuple[tuple[str, Path], ...],
) -> dict:
    website_candidates, route_manifest = load_routes(routes, route_manifest_path, bundles)
    candidate_by_slug = {row["slug"]: row for row in website_candidates}
    website_manifest = json.loads(website_manifest_path.read_text())
    if (
        website_manifest["output_sha256"] != sha256_file(website_evidence)
        or website_manifest["routing_manifest_sha256"] != sha256_file(route_manifest_path)
        or website_manifest["routing_output_sha256"] != route_manifest["output_sha256"]
        or website_manifest["taxonomy_sha256"] != FROZEN_TAXONOMY_SHA
        or website_manifest["model_sha256"] != FROZEN_MODEL_SHA
        or website_manifest["thresholds_sha256"] != FROZEN_THRESHOLDS_SHA
        or website_manifest["eligible_routes"] != len(candidate_by_slug)
    ):
        raise ValueError("website evidence manifest does not match frozen routing")
    by_slug = _evidence_rows(website_evidence, route_manifest["output_sha256"], candidate_by_slug)
    manifest_output = output.with_suffix(output.suffix + ".manifest.json")
    partial = output.with_suffix(output.suffix + ".partial")
    if output.exists() or manifest_output.exists() or partial.exists():
        raise FileExistsError(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    counts = {"unresolved": 0, "non_web": 0, "website_evidence": 0, "awaiting_website": 0}
    with partial.open("w") as handle:
        for line in routes.read_text().splitlines():
            route = json.loads(line)
            if not route["route"]:
                continue
            if route["next_step"] == "website_evidence_candidate":
                evidence = by_slug.get(route["slug"])
                if evidence is None:
                    counts["awaiting_website"] += 1
                    continue
                website = evidence["row"]
                reason = (
                    "website_evidence_pending_adjudication"
                    if website["fields"]
                    else "website_fetch_without_usable_evidence"
                )
                counts["website_evidence"] += 1
            elif route["next_step"] == "non_web_review":
                evidence = None
                website = None
                reason = "no_external_website"
                counts["non_web"] += 1
            else:
                raise ValueError("routed product has an unexpected next step")
            record = {
                "slug": route["slug"],
                "unresolved": True,
                "reason": reason,
                "policy": HANDOFF_POLICY,
                "routing_output_sha256": route_manifest["output_sha256"],
                "product_text_sha256": route["evidence_hash"],
                "website_evidence_output_sha256": website_manifest["output_sha256"]
                if evidence
                else None,
                "website_evidence_record_sha256": evidence["sha256"] if evidence else None,
                "website_outcome": website["outcome"] if website else None,
                "website_field_count": len(website["fields"]) if website else 0,
            }
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            counts["unresolved"] += 1
    os.replace(partial, output)
    report = {
        "status": "provisional unresolved handoff; no category promotion",
        "policy": HANDOFF_POLICY,
        "routing_manifest_sha256": sha256_file(route_manifest_path),
        "routing_output_sha256": route_manifest["output_sha256"],
        "website_manifest_sha256": sha256_file(website_manifest_path),
        "website_evidence_output_sha256": website_manifest["output_sha256"],
        "taxonomy_sha256": FROZEN_TAXONOMY_SHA,
        "model_sha256": FROZEN_MODEL_SHA,
        "thresholds_sha256": FROZEN_THRESHOLDS_SHA,
        "counts": counts,
        "output_sha256": sha256_file(output),
    }
    manifest_output.write_text(json.dumps(report, indent=2) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--routes", type=Path, required=True)
    parser.add_argument("--route-manifest", type=Path, required=True)
    parser.add_argument("--website-evidence", type=Path, required=True)
    parser.add_argument("--website-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--exclude-bundle", nargs=2, action="append", required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            run(
                args.routes,
                args.route_manifest,
                args.website_evidence,
                args.website_manifest,
                args.output,
                tuple((name, Path(path)) for name, path in args.exclude_bundle),
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
