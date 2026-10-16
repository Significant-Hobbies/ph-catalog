"""Pin one unlabeled final candidate or explicit null/error per Stage 7 record."""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from pathlib import Path

from ph_catalog.primary_local_fallback import PROMPT_VERSION
from ph_catalog.primary_taxonomy_review import sha256_file

AUDIT_MODEL = "qwen3.5:27b"
AUDIT_MODEL_DIGEST = "64ae5b1d651fb2709d5928ccb8dcfb4bb2cc9c2c8001ac34497e36a6cf905b59"


def _rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def build(
    audit_bundle: Path,
    selected_paths: Path,
    website_evidence: Path,
    handoff: Path,
    batch_paths: list[Path],
    output: Path,
) -> dict:
    if not batch_paths:
        raise ValueError("all Stage 6 batches are required")
    output_manifest = output.with_suffix(output.suffix + ".manifest.json")
    partial = output.with_suffix(output.suffix + ".partial")
    if output.exists() or output_manifest.exists() or partial.exists():
        raise FileExistsError(output)
    audit_manifest = json.loads((audit_bundle / "manifest.json").read_text())
    path_manifest = json.loads((selected_paths / "manifest.json").read_text())
    if path_manifest["audit_manifest_sha256"] != sha256_file(audit_bundle / "manifest.json"):
        raise ValueError("selected paths do not match sealed audit")
    key = json.loads((audit_bundle / "source-key.json").read_text())
    if (
        sha256_file(audit_bundle / "source-key.json")
        != audit_manifest["file_sha256"]["source-key.json"]
        or len(key) != 320
        or len({row["slug"] for row in key}) != 320
    ):
        raise ValueError("sealed audit key changed")
    routes_path = selected_paths / "selected-routes.jsonl"
    routes = _rows(routes_path)
    route_counts = Counter(row["next_step"] for row in routes)
    if (
        sha256_file(routes_path) != path_manifest["selected_route_output_sha256"]
        or len(routes) != 320
        or {row["slug"] for row in routes} != {row["slug"] for row in key}
        or route_counts
        != Counter(
            {
                name: path_manifest[name]
                for name in (
                    "candidate_accept",
                    "website_evidence_candidate",
                    "non_web_review",
                )
            }
        )
    ):
        raise ValueError("selected routes changed")
    by_route = {row["slug"]: row for row in routes}
    website_manifest_path = website_evidence.with_suffix(website_evidence.suffix + ".manifest.json")
    website_manifest = json.loads(website_manifest_path.read_text())
    website_rows = _rows(website_evidence)
    website_slugs = {row["slug"] for row in website_rows}
    expected_website = {
        row["slug"] for row in routes if row["next_step"] == "website_evidence_candidate"
    }
    if (
        website_manifest["output_sha256"] != sha256_file(website_evidence)
        or website_manifest["routing_output_sha256"]
        != path_manifest["selected_route_output_sha256"]
        or len(website_rows) != len(expected_website)
        or website_slugs != expected_website
    ):
        raise ValueError("Stage 5 does not cover every selected website route exactly once")
    website_by_slug = {row["slug"]: row for row in website_rows}
    handoff_manifest_path = handoff.with_suffix(handoff.suffix + ".manifest.json")
    handoff_manifest = json.loads(handoff_manifest_path.read_text())
    handoff_rows = _rows(handoff)
    handoff_slugs = [row["slug"] for row in handoff_rows]
    expected_routed = {row["slug"] for row in routes if row["next_step"] != "candidate_accept"}
    if (
        handoff_manifest["output_sha256"] != sha256_file(handoff)
        or handoff_manifest["routing_output_sha256"]
        != path_manifest["selected_route_output_sha256"]
        or handoff_manifest["website_evidence_output_sha256"] != website_manifest["output_sha256"]
        or len(handoff_slugs) != len(expected_routed)
        or set(handoff_slugs) != expected_routed
        or len(set(handoff_slugs)) != len(handoff_slugs)
    ):
        raise ValueError("Stage 5 handoff does not cover every unresolved route")
    batch_meta = []
    predictions = {}
    expected_start = 0
    identity = None
    for path in batch_paths:
        manifest_path = path.with_suffix(path.suffix + ".manifest.json")
        manifest = json.loads(manifest_path.read_text())
        rows = _rows(path)
        current_identity = (
            manifest["model"],
            manifest["model_digest"],
            manifest["prompt_version"],
            manifest["prompt_sha256"],
            manifest["taxonomy_sha256"],
            manifest["handoff_output_sha256"],
        )
        if identity is None:
            identity = current_identity
        if (
            manifest["output_sha256"] != sha256_file(path)
            or manifest["start_index"] != expected_start
            or manifest["total_unresolved_input"] != len(handoff_rows)
            or not 1 <= manifest["selected_products"] <= 25
            or len(rows) != manifest["selected_products"]
            or [row["slug"] for row in rows]
            != handoff_slugs[expected_start : expected_start + len(rows)]
            or current_identity != identity
            or manifest["model"] != AUDIT_MODEL
            or manifest["model_digest"] != AUDIT_MODEL_DIGEST
            or manifest["prompt_version"] != PROMPT_VERSION
            or manifest["handoff_output_sha256"] != handoff_manifest["output_sha256"]
            or any(
                row["model"] != identity[0]
                or row["model_digest"] != identity[1]
                or row["prompt_version"] != identity[2]
                or row["prompt_sha256"] != identity[3]
                or row["taxonomy_sha256"] != identity[4]
                or row["handoff_output_sha256"] != identity[5]
                for row in rows
            )
        ):
            raise ValueError("Stage 6 batch gap, overlap, identity, or provenance mismatch")
        for row in rows:
            if row["status"] == "candidate":
                if row["primary_category"] is None or not row["citations"]:
                    raise ValueError("Stage 6 candidate lacks category or citations")
            elif row["status"] in {"null", "error"}:
                if row["primary_category"] is not None:
                    raise ValueError("Stage 6 null/error contains category")
            else:
                raise ValueError("unknown Stage 6 status")
            predictions[row["slug"]] = row
        status_counts = Counter(row["status"] for row in rows)
        if manifest["counts"] != {
            name: status_counts[name] for name in ("candidate", "null", "error")
        }:
            raise ValueError("Stage 6 batch status counts changed")
        batch_meta.append(
            {"output_sha256": sha256_file(path), "manifest_sha256": sha256_file(manifest_path)}
        )
        expected_start += len(rows)
    if expected_start != len(handoff_rows) or set(predictions) != expected_routed:
        raise ValueError("Stage 6 batches do not partition every unresolved record")
    ledger = []
    for item in key:
        slug = item["slug"]
        route = by_route[slug]
        if route["next_step"] != item["stage4_path"]:
            raise ValueError("Stage 4 path differs from audit key")
        if route["next_step"] == "candidate_accept":
            if route["route"] is not False or route["primary_category"] is None:
                raise ValueError("Stage 4 accepted route lacks a primary category")
            category = route["primary_category"]
            status = "candidate"
            path = "source_text_only"
            website_outcome = None
        else:
            if route["route"] is not True or route["primary_category"] is not None:
                raise ValueError("Stage 4 routed candidate masquerades as accepted")
            prediction = predictions[slug]
            category = (
                prediction["primary_category"] if prediction["status"] == "candidate" else None
            )
            status = prediction["status"]
            path = "llm_final"
            website_outcome = website_by_slug[slug]["outcome"] if slug in website_by_slug else None
        ledger.append(
            {
                "review_id": item["review_id"],
                "slug": slug,
                "split": item["split"],
                "stage4_path": route["next_step"],
                "final_path": path,
                "website_outcome": website_outcome,
                "status": status,
                "primary_category": category,
            }
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    with partial.open("w") as handle:
        for row in ledger:
            handle.write(json.dumps(row) + "\n")
    os.replace(partial, output)
    manifest = {
        "status": "frozen unlabeled Stage 7 candidates; no accuracy estimate",
        "decision_rule": "stage7-prelabel-v1-exact-unique-primary",
        "audit_manifest_sha256": sha256_file(audit_bundle / "manifest.json"),
        "selected_paths_manifest_sha256": sha256_file(selected_paths / "manifest.json"),
        "website_manifest_sha256": sha256_file(website_manifest_path),
        "handoff_manifest_sha256": sha256_file(handoff_manifest_path),
        "stage6_batches": batch_meta,
        "model": identity[0],
        "model_digest": identity[1],
        "prompt_version": identity[2],
        "prompt_sha256": identity[3],
        "taxonomy_sha256": identity[4],
        "ledger_code_sha256": sha256_file(Path(__file__)),
        "evaluator_code_sha256": sha256_file(
            Path(__file__).with_name("primary_final_audit_evaluate.py")
        ),
        "records": len(ledger),
        "random": sum(row["split"] == "random" for row in ledger),
        "biased_diagnostic": sum(row["split"] != "random" for row in ledger),
        "statuses": dict(Counter(row["status"] for row in ledger)),
        "random_statuses": dict(
            Counter(row["status"] for row in ledger if row["split"] == "random")
        ),
        "diagnostic_statuses": dict(
            Counter(row["status"] for row in ledger if row["split"] != "random")
        ),
        "website_outcomes": dict(Counter(row["outcome"] for row in website_rows)),
        "output_sha256": sha256_file(output),
    }
    output_manifest.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-bundle", type=Path, required=True)
    parser.add_argument("--selected-paths", type=Path, required=True)
    parser.add_argument("--website-evidence", type=Path, required=True)
    parser.add_argument("--handoff", type=Path, required=True)
    parser.add_argument("--stage6-batch", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            build(
                args.audit_bundle,
                args.selected_paths,
                args.website_evidence,
                args.handoff,
                args.stage6_batch,
                args.output,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
