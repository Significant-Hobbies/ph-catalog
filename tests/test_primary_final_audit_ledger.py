"""Stage 7 ledger rejects missing or overlapping bounded model batches."""

import json

import pytest

from ph_catalog.primary_final_audit_ledger import (
    AUDIT_MODEL,
    AUDIT_MODEL_DIGEST,
    PROMPT_VERSION,
    build,
)
from ph_catalog.primary_taxonomy_review import sha256_file


def _json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) + "\n")


def _jsonl(path, values):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(value) + "\n" for value in values))


def test_ledger_requires_contiguous_exact_model_partition(tmp_path):
    audit = tmp_path / "audit"
    selected = tmp_path / "selected"
    key = [
        {
            "slug": f"product-{index:03d}",
            "review_id": f"review-{index:03d}",
            "split": "random" if index < 200 else "model_stratified",
            "stage4_path": (
                "website_evidence_candidate"
                if index == 318
                else "non_web_review"
                if index == 319
                else "candidate_accept"
            ),
        }
        for index in range(320)
    ]
    _json(audit / "source-key.json", key)
    _json(
        audit / "manifest.json",
        {"file_sha256": {"source-key.json": sha256_file(audit / "source-key.json")}},
    )
    routes = [
        {
            "slug": item["slug"],
            "next_step": item["stage4_path"],
            "route": item["stage4_path"] != "candidate_accept",
            "primary_category": "developer_tools"
            if item["stage4_path"] == "candidate_accept"
            else None,
        }
        for item in key
    ]
    routes_path = selected / "selected-routes.jsonl"
    _jsonl(routes_path, routes)
    _json(
        selected / "manifest.json",
        {
            "audit_manifest_sha256": sha256_file(audit / "manifest.json"),
            "selected_route_output_sha256": sha256_file(routes_path),
            "candidate_accept": 318,
            "website_evidence_candidate": 1,
            "non_web_review": 1,
        },
    )
    website = tmp_path / "website.jsonl"
    _jsonl(website, [{"slug": "product-318", "outcome": "fetched"}])
    _json(
        website.with_suffix(".jsonl.manifest.json"),
        {
            "output_sha256": sha256_file(website),
            "routing_output_sha256": sha256_file(routes_path),
        },
    )
    handoff = tmp_path / "handoff.jsonl"
    _jsonl(handoff, [{"slug": "product-318"}, {"slug": "product-319"}])
    _json(
        handoff.with_suffix(".jsonl.manifest.json"),
        {
            "output_sha256": sha256_file(handoff),
            "routing_output_sha256": sha256_file(routes_path),
            "website_evidence_output_sha256": sha256_file(website),
        },
    )
    batches = []
    for index, slug in enumerate(("product-318", "product-319")):
        path = tmp_path / f"batch-{index}.jsonl"
        _jsonl(
            path,
            [
                {
                    "slug": slug,
                    "status": "candidate" if index == 0 else "null",
                    "primary_category": "home_lifestyle" if index == 0 else None,
                    "citations": [{"quote": "Home"}] if index == 0 else [],
                    "model": AUDIT_MODEL,
                    "model_digest": AUDIT_MODEL_DIGEST,
                    "prompt_version": PROMPT_VERSION,
                    "prompt_sha256": "prompt",
                    "taxonomy_sha256": "taxonomy",
                    "handoff_output_sha256": sha256_file(handoff),
                }
            ],
        )
        _json(
            path.with_suffix(".jsonl.manifest.json"),
            {
                "output_sha256": sha256_file(path),
                "start_index": index,
                "total_unresolved_input": 2,
                "selected_products": 1,
                "model": AUDIT_MODEL,
                "model_digest": AUDIT_MODEL_DIGEST,
                "prompt_version": PROMPT_VERSION,
                "prompt_sha256": "prompt",
                "taxonomy_sha256": "taxonomy",
                "handoff_output_sha256": sha256_file(handoff),
            },
        )
        batches.append(path)
    output = tmp_path / "ledger.jsonl"
    report = build(audit, selected, website, handoff, batches, output)
    assert report["records"] == 320
    assert report["statuses"] == {"candidate": 319, "null": 1}
    assert [json.loads(line)["final_path"] for line in output.read_text().splitlines()][-2:] == [
        "llm_final",
        "llm_final",
    ]
    second_manifest = batches[1].with_suffix(".jsonl.manifest.json")
    original = json.loads(second_manifest.read_text())
    for bad_start in (0, 2):
        _json(second_manifest, {**original, "start_index": bad_start})
        with pytest.raises(ValueError, match="gap, overlap"):
            build(audit, selected, website, handoff, batches, tmp_path / f"bad-{bad_start}.jsonl")
    _json(second_manifest, original)
    first_row = json.loads(batches[0].read_text().splitlines()[0])
    _jsonl(batches[0], [{**first_row, "prompt_version": "primary-local-fallback-v2-category-only"}])
    first_manifest_path = batches[0].with_suffix(".jsonl.manifest.json")
    first_manifest = json.loads(first_manifest_path.read_text())
    _json(
        first_manifest_path,
        {
            **first_manifest,
            "prompt_version": "primary-local-fallback-v2-category-only",
            "output_sha256": sha256_file(batches[0]),
        },
    )
    with pytest.raises(ValueError, match="identity"):
        build(audit, selected, website, handoff, batches, tmp_path / "bad-v2.jsonl")
