"""Bounded, category-only local LLM candidate for unresolved Stage 4/5 rows.

This is an ignored experimental output, never a published primary category.
No source tags, heldout annotations, generated labels, or reasoning are inputs.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Protocol

import duckdb
import httpx

from ph_catalog.primary_classifier import text_input
from ph_catalog.primary_confidence_routing import reserved_slugs
from ph_catalog.primary_heldout import (
    FROZEN_MODEL_SHA,
    FROZEN_TAXONOMY_SHA,
    FROZEN_THRESHOLDS_SHA,
)
from ph_catalog.primary_stage5_handoff import HANDOFF_POLICY, _evidence_rows
from ph_catalog.primary_taxonomy import load_taxonomy
from ph_catalog.primary_taxonomy_review import sha256_file
from ph_catalog.primary_website_evidence import load_routes

PROMPT_VERSION = "primary-local-fallback-v1-category-only"
SYSTEM_PROMPT = (
    "Choose one primary market category for each product from the supplied "
    "frozen taxonomy, or null when text is weak, outside the taxonomy, or "
    "two markets are co-primary. Classify the user's workflow, never a mere "
    "implementation technology. Cite one or two exact short spans from "
    "the supplied field IDs for every non-null choice. Return no reasoning "
    "and no generated labels. Confidence is only an uncalibrated candidate score."
)
MAX_FIELD_CHARS = 2_000
MAX_TOTAL_CHARS = 10_000


def _sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def _taxonomy_definitions(taxonomy_path: Path) -> tuple[dict[str, str], str]:
    taxonomy = load_taxonomy(taxonomy_path)
    if taxonomy.version != "v1" or taxonomy.sha256 != FROZEN_TAXONOMY_SHA:
        raise ValueError("local fallback requires frozen v1 taxonomy")
    document = json.loads(taxonomy_path.read_text())
    return {item["id"]: item["boundary"] for item in document["categories"]}, taxonomy.sha256


def _load_inputs(
    handoff_path: Path,
    handoff_manifest_path: Path,
    routes_path: Path,
    route_manifest_path: Path,
    evidence_path: Path,
    evidence_manifest_path: Path,
    mart_path: Path,
    bundles: tuple[tuple[str, Path], ...],
) -> tuple[list[dict], dict]:
    # load_routes verifies the exact frozen router, model and all four bundle
    # manifests/keys before any source text is selected.
    website_candidates, route_manifest = load_routes(routes_path, route_manifest_path, bundles)
    candidate_by_slug = {row["slug"]: row for row in website_candidates}
    all_routes = {row["slug"]: row for row in map(json.loads, routes_path.read_text().splitlines())}
    if len(all_routes) != len(routes_path.read_text().splitlines()):
        raise ValueError("duplicate route slug")
    website_manifest = json.loads(evidence_manifest_path.read_text())
    if (
        website_manifest["output_sha256"] != sha256_file(evidence_path)
        or website_manifest["routing_manifest_sha256"] != sha256_file(route_manifest_path)
        or website_manifest["routing_output_sha256"] != route_manifest["output_sha256"]
        or website_manifest["taxonomy_sha256"] != FROZEN_TAXONOMY_SHA
        or website_manifest["model_sha256"] != FROZEN_MODEL_SHA
        or website_manifest["thresholds_sha256"] != FROZEN_THRESHOLDS_SHA
        or website_manifest["eligible_routes"] != len(candidate_by_slug)
    ):
        raise ValueError("website evidence provenance changed")
    evidence = _evidence_rows(evidence_path, route_manifest["output_sha256"], candidate_by_slug)
    handoff_manifest = json.loads(handoff_manifest_path.read_text())
    if (
        handoff_manifest["policy"] != HANDOFF_POLICY
        or handoff_manifest["output_sha256"] != sha256_file(handoff_path)
        or handoff_manifest["routing_manifest_sha256"] != sha256_file(route_manifest_path)
        or handoff_manifest["routing_output_sha256"] != route_manifest["output_sha256"]
        or handoff_manifest["website_manifest_sha256"] != sha256_file(evidence_manifest_path)
        or handoff_manifest["website_evidence_output_sha256"] != website_manifest["output_sha256"]
        or handoff_manifest["taxonomy_sha256"] != FROZEN_TAXONOMY_SHA
        or handoff_manifest["model_sha256"] != FROZEN_MODEL_SHA
        or handoff_manifest["thresholds_sha256"] != FROZEN_THRESHOLDS_SHA
        or route_manifest["source_mart_sha256"] != sha256_file(mart_path)
    ):
        raise ValueError("unresolved handoff or source mart provenance changed")
    reserved = reserved_slugs(bundles)
    records = []
    seen = set()
    for line in handoff_path.read_text().splitlines():
        item = json.loads(line)
        slug = item["slug"]
        route = all_routes.get(slug)
        if slug in seen or slug in reserved or route is None or not route["route"]:
            raise ValueError("duplicate, reserved, accepted, or unknown handoff product")
        seen.add(slug)
        website = evidence.get(slug)
        expected_reason = (
            "no_external_website"
            if route["next_step"] == "non_web_review"
            else "website_evidence_pending_adjudication"
            if website and website["row"]["fields"]
            else "website_fetch_without_usable_evidence"
        )
        if (
            item["unresolved"] is not True
            or item["policy"] != HANDOFF_POLICY
            or item["reason"] != expected_reason
            or item["routing_output_sha256"] != route_manifest["output_sha256"]
            or item["product_text_sha256"] != route["evidence_hash"]
            or item["website_evidence_record_sha256"] != (website["sha256"] if website else None)
            or item["website_field_count"] != (len(website["row"]["fields"]) if website else 0)
            or (route["next_step"] == "website_evidence_candidate") != bool(website)
        ):
            raise ValueError("handoff row does not match unresolved route and evidence")
        records.append({"route": route, "website": website["row"] if website else None})
    if len(records) != handoff_manifest["counts"]["unresolved"]:
        raise ValueError("handoff count changed")
    connection = duckdb.connect(str(mart_path), read_only=True)
    try:
        for item in records:
            route = item["route"]
            result = connection.execute(
                "SELECT slug,name,tagline,description,website_url FROM product_facts WHERE slug=?",
                [route["slug"]],
            ).fetchall()
            if len(result) != 1:
                raise ValueError("source product missing or duplicated")
            row = dict(
                zip(
                    ("slug", "name", "tagline", "description", "website_url"),
                    result[0],
                    strict=True,
                )
            )
            if hashlib.sha256(text_input(row).encode()).hexdigest() != route[
                "evidence_hash"
            ] or route["website_url"] != (row["website_url"] if route["website_url"] else None):
                raise ValueError("source product text or website changed")
            item["source"] = row
    finally:
        connection.close()
    return records, {
        "handoff_output_sha256": handoff_manifest["output_sha256"],
        "route_output_sha256": route_manifest["output_sha256"],
        "website_output_sha256": website_manifest["output_sha256"],
        "source_mart_sha256": route_manifest["source_mart_sha256"],
    }


def _product_input(item: dict) -> dict:
    route = item["route"]
    source = item["source"]
    fields = []
    for name in ("name", "tagline", "description"):
        value = str(source[name] or "").strip()
        if value:
            fields.append({"id": f"ph_{name}", "text": value[:MAX_FIELD_CHARS], "url": None})
    if item["website"]:
        for index, value in enumerate(item["website"]["fields"][:8]):
            fields.append(
                {
                    "id": f"web_{index}",
                    "text": value["text"][:MAX_FIELD_CHARS],
                    "url": value["source_url"],
                    "response_sha256": value["response_sha256"],
                    "field_type": value["field"],
                }
            )
    remaining = MAX_TOTAL_CHARS
    for field in fields:
        field["text"] = field["text"][:remaining]
        remaining -= len(field["text"])
    fields = [field for field in fields if field["text"]]
    return {"slug": route["slug"], "fields": fields, "input_sha256": _sha(fields)}


def _schema(ids: list[str], category_ids: list[str]) -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["decisions"],
        "properties": {
            "decisions": {
                "type": "array",
                "minItems": len(ids),
                "maxItems": len(ids),
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["id", "primary_category", "confidence", "citations"],
                    "properties": {
                        "id": {"type": "string", "enum": ids},
                        "primary_category": {
                            "type": ["string", "null"],
                            "enum": [*category_ids, None],
                        },
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                        "citations": {
                            "type": "array",
                            "maxItems": 2,
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["field_id", "quote"],
                                "properties": {
                                    "field_id": {"type": "string"},
                                    "quote": {"type": "string"},
                                },
                            },
                        },
                    },
                },
            }
        },
    }


def _validated_decisions(
    content: str, inputs: list[dict], category_ids: set[str]
) -> dict[str, dict]:
    payload = json.loads(content)
    if not isinstance(payload, dict) or set(payload) != {"decisions"}:
        raise ValueError("model response schema mismatch")
    decisions = payload["decisions"]
    ids = {f"p{index}" for index in range(len(inputs))}
    if not isinstance(decisions, list) or len(decisions) != len(ids):
        raise ValueError("model response count mismatch")
    by_id = {}
    for decision in decisions:
        if not isinstance(decision, dict) or set(decision) != {
            "id",
            "primary_category",
            "confidence",
            "citations",
        }:
            raise ValueError("model decision schema mismatch")
        identifier = decision["id"]
        if identifier not in ids or identifier in by_id:
            raise ValueError("missing or duplicate model decision ID")
        category = decision["primary_category"]
        confidence = decision["confidence"]
        citations = decision["citations"]
        if (
            category is not None
            and category not in category_ids
            or isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not math.isfinite(confidence)
            or not 0 <= confidence <= 1
            or not isinstance(citations, list)
        ):
            raise ValueError("invalid category, confidence, or citations")
        fields = {field["id"]: field for field in inputs[int(identifier[1:])]["fields"]}
        if category is None:
            if confidence != 0 or citations:
                raise ValueError("null category must have zero confidence and no citations")
        elif not 1 <= len(citations) <= 2:
            raise ValueError("category requires one or two exact citations")
        checked = []
        for citation in citations:
            if not isinstance(citation, dict) or set(citation) != {"field_id", "quote"}:
                raise ValueError("citation schema mismatch")
            field = fields.get(citation["field_id"])
            quote = citation["quote"]
            if (
                field is None
                or not isinstance(quote, str)
                or not 8 <= len(quote) <= 160
                or quote not in field["text"]
            ):
                raise ValueError("citation is not an exact bounded input span")
            checked.append(
                {
                    "field_id": citation["field_id"],
                    "quote": quote,
                    "url": field["url"],
                    "response_sha256": field.get("response_sha256"),
                }
            )
        by_id[identifier] = {
            "primary_category": category,
            "confidence": float(confidence),
            "citations": checked,
        }
    if set(by_id) != ids:
        raise ValueError("missing model decision ID")
    return by_id


class LocalClient(Protocol):
    model: str
    digest: str

    async def classify(self, system: str, user: str, schema: dict) -> str: ...


class OllamaClient:
    def __init__(self, model: str, digest: str) -> None:
        self.model = model
        self.digest = digest
        self.client = httpx.AsyncClient(
            base_url="http://127.0.0.1:11434",
            timeout=httpx.Timeout(180),
            trust_env=False,
        )

    async def verify(self) -> None:
        response = await self.client.get("/api/tags")
        response.raise_for_status()
        if not any(
            item.get("name") == self.model and item.get("digest") == self.digest
            for item in response.json().get("models", [])
        ):
            raise ValueError("local Ollama model digest changed")

    async def classify(self, system: str, user: str, schema: dict) -> str:
        response = await self.client.post(
            "/api/chat",
            json={
                "model": self.model,
                "stream": False,
                "think": False,
                "format": schema,
                "options": {"temperature": 0},
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
        )
        response.raise_for_status()
        body = response.json()
        if body.get("model") != self.model or body.get("done") is not True:
            raise ValueError("local model identity or completion changed")
        return body["message"]["content"]

    async def close(self) -> None:
        await self.client.aclose()


async def run(
    handoff_path: Path,
    handoff_manifest_path: Path,
    routes_path: Path,
    route_manifest_path: Path,
    evidence_path: Path,
    evidence_manifest_path: Path,
    mart_path: Path,
    taxonomy_path: Path,
    output: Path,
    bundles: tuple[tuple[str, Path], ...],
    client: LocalClient,
    *,
    batch_size: int = 3,
    max_products: int = 8,
) -> dict:
    if not 2 <= batch_size <= 4 or not 1 <= max_products <= 25:
        raise ValueError("local fallback must use 2–4 per batch and at most 25 products")
    definitions, taxonomy_sha = _taxonomy_definitions(taxonomy_path)
    records, inputs_hashes = _load_inputs(
        handoff_path,
        handoff_manifest_path,
        routes_path,
        route_manifest_path,
        evidence_path,
        evidence_manifest_path,
        mart_path,
        bundles,
    )
    manifest_path = output.with_suffix(output.suffix + ".manifest.json")
    partial = output.with_suffix(output.suffix + ".partial")
    if output.exists() or manifest_path.exists() or partial.exists():
        raise FileExistsError(output)
    if isinstance(client, OllamaClient):
        await client.verify()
    system = SYSTEM_PROMPT + "\nTaxonomy boundaries: " + json.dumps(definitions, sort_keys=True)
    prompt_sha = hashlib.sha256(system.encode()).hexdigest()
    selected = [_product_input(item) for item in records[:max_products]]
    counts = {"candidate": 0, "null": 0, "error": 0}
    output.parent.mkdir(parents=True, exist_ok=True)
    with partial.open("w") as handle:
        for start in range(0, len(selected), batch_size):
            batch = selected[start : start + batch_size]
            ids = [f"p{index}" for index in range(len(batch))]
            user = json.dumps(
                [
                    {"id": identifier, "fields": item["fields"]}
                    for identifier, item in zip(ids, batch, strict=True)
                ],
                ensure_ascii=False,
            )
            try:
                content = await client.classify(system, user, _schema(ids, list(definitions)))
                decisions = _validated_decisions(content, batch, set(definitions))
                error = None
            except (httpx.HTTPError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
                decisions = {}
                error = (
                    str(exc)
                    if isinstance(exc, ValueError) and not isinstance(exc, json.JSONDecodeError)
                    else "model_call_or_json_failure"
                )
            for index, item in enumerate(batch):
                result = decisions.get(f"p{index}")
                if result is None:
                    result = {"primary_category": None, "confidence": 0.0, "citations": []}
                status = (
                    "error"
                    if error
                    else "null"
                    if result["primary_category"] is None
                    else "candidate"
                )
                counts[status] += 1
                handle.write(
                    json.dumps(
                        {
                            "slug": item["slug"],
                            "status": status,
                            "error": error,
                            **result,
                            "method": "local_llm_candidate",
                            "model": client.model,
                            "model_digest": client.digest,
                            "prompt_version": PROMPT_VERSION,
                            "prompt_sha256": prompt_sha,
                            "input_sha256": item["input_sha256"],
                            "taxonomy_sha256": taxonomy_sha,
                            "handoff_output_sha256": inputs_hashes["handoff_output_sha256"],
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
    os.replace(partial, output)
    report = {
        "status": "local category-only candidate; no promotion or generated labels",
        "model": client.model,
        "model_digest": client.digest,
        "prompt_version": PROMPT_VERSION,
        "prompt_sha256": prompt_sha,
        "taxonomy_sha256": taxonomy_sha,
        **inputs_hashes,
        "batch_size": batch_size,
        "selected_products": len(selected),
        "counts": counts,
        "output_sha256": sha256_file(output),
    }
    manifest_path.write_text(json.dumps(report, indent=2) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--handoff", type=Path, required=True)
    parser.add_argument("--handoff-manifest", type=Path, required=True)
    parser.add_argument("--routes", type=Path, required=True)
    parser.add_argument("--route-manifest", type=Path, required=True)
    parser.add_argument("--website-evidence", type=Path, required=True)
    parser.add_argument("--website-manifest", type=Path, required=True)
    parser.add_argument("--mart", type=Path, required=True)
    parser.add_argument("--taxonomy", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--exclude-bundle", nargs=2, action="append", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--model-digest", required=True)
    parser.add_argument("--batch-size", type=int, default=3)
    parser.add_argument("--max-products", type=int, default=8)
    args = parser.parse_args()

    async def execute() -> dict:
        client = OllamaClient(args.model, args.model_digest)
        try:
            return await run(
                args.handoff,
                args.handoff_manifest,
                args.routes,
                args.route_manifest,
                args.website_evidence,
                args.website_manifest,
                args.mart,
                args.taxonomy,
                args.output,
                tuple((name, Path(path)) for name, path in args.exclude_bundle),
                client,
                batch_size=args.batch_size,
                max_products=args.max_products,
            )
        finally:
            await client.close()

    print(json.dumps(asyncio.run(execute()), indent=2))


if __name__ == "__main__":
    main()
