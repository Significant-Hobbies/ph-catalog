"""Evaluate frozen Stage 7 candidates once independent gold labels are complete."""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

from ph_catalog.primary_heldout import FROZEN_TAXONOMY_SHA
from ph_catalog.primary_label_protocol import validate_annotations
from ph_catalog.primary_taxonomy import load_taxonomy
from ph_catalog.primary_taxonomy_review import sha256_file

RULE = "stage7-prelabel-v1-exact-unique-primary"


def wilson_95(correct: int, accepted: int) -> tuple[float, float]:
    if accepted == 0:
        return 0.0, 1.0
    z = 1.959963984540054
    p = correct / accepted
    denominator = 1 + z * z / accepted
    center = (p + z * z / (2 * accepted)) / denominator
    half = z * math.sqrt(p * (1 - p) / accepted + z * z / (4 * accepted**2)) / denominator
    return max(0.0, center - half), min(1.0, center + half)


def _metrics(rows: list[dict], gold: dict[str, dict], *, denominator: int) -> dict:
    accepted = [row for row in rows if row["status"] == "candidate"]
    correct = sum(
        gold[row["review_id"]]["decision"] == "single"
        and row["primary_category"] == gold[row["review_id"]]["primary_category"]
        for row in accepted
    )
    lower, upper = wilson_95(correct, len(accepted))
    return {
        "denominator": denominator,
        "accepted": len(accepted),
        "correct_unique_primary": correct,
        "coverage": len(accepted) / denominator if denominator else 0.0,
        "precision": correct / len(accepted) if accepted else None,
        "wilson_95_lower": lower,
        "wilson_95_upper": upper,
        "statuses": dict(Counter(row["status"] for row in rows)),
    }


def score(ledger: list[dict], annotations: list[dict]) -> dict:
    gold = {row["review_id"]: row for row in annotations}
    if len(gold) != len(ledger) or {row["review_id"] for row in ledger} != set(gold):
        raise ValueError("audit ledger and independent gold IDs differ")
    if any(row["decision"] == "unreviewed" for row in annotations):
        raise ValueError("final audit gold is incomplete")
    random = [row for row in ledger if row["split"] == "random"]
    diagnostic = [row for row in ledger if row["split"] == "model_stratified"]
    if len(random) != 200 or len(diagnostic) != 120:
        raise ValueError("random and biased audit denominators changed")
    random_metrics = _metrics(random, gold, denominator=200)
    diagnostics = _metrics(diagnostic, gold, denominator=120)
    paths = {}
    for name in ("source_text_only", "llm_final"):
        subset = [row for row in random if row["final_path"] == name]
        paths[name] = _metrics(subset, gold, denominator=len(subset))
    # Stage 5 emits evidence, not categories. LLM-after-website belongs only
    # to the LLM path above and is reported as a non-additive subgroup.
    website_llm = [
        row for row in random if row["final_path"] == "llm_final" and row["website_outcome"]
    ]
    paths["llm_after_website_subgroup"] = _metrics(website_llm, gold, denominator=len(website_llm))
    paths["website_evidence_only"] = {
        "denominator": sum(row["stage4_path"] == "website_evidence_candidate" for row in random),
        "accepted": 0,
        "correct_unique_primary": 0,
        "coverage": 0.0,
        "precision": None,
        "wilson_95_lower": 0.0,
        "wilson_95_upper": 1.0,
        "note": "current Stage 5 produces evidence but no categorical decision",
    }
    true_class_support = Counter(
        gold[row["review_id"]]["primary_category"]
        for row in random
        if gold[row["review_id"]]["decision"] == "single"
    )
    confusion = defaultdict(Counter)
    for row in random:
        label = gold[row["review_id"]]
        true = label["primary_category"] if label["decision"] == "single" else label["decision"]
        predicted = row["primary_category"] if row["status"] == "candidate" else "abstained"
        confusion[true][predicted] += 1
    promotable_paths = {
        name: value["accepted"] >= 30 and value["wilson_95_lower"] >= 0.90
        for name, value in paths.items()
        if name in {"source_text_only", "llm_final"}
    }
    overall_gate = random_metrics["coverage"] >= 0.50 and random_metrics["wilson_95_lower"] >= 0.90
    return {
        "rule": RULE,
        "random": random_metrics,
        "biased_diagnostic": diagnostics,
        "random_paths": paths,
        "random_true_single_support": dict(sorted(true_class_support.items())),
        "class_claim_eligible_support_only": sorted(
            name for name, count in true_class_support.items() if count >= 30
        ),
        "random_confusion": {
            name: dict(sorted(counts.items())) for name, counts in sorted(confusion.items())
        },
        "broad_promotion_gate": overall_gate and all(promotable_paths.values()),
        "overall_random_gate": overall_gate,
        "path_gates": promotable_paths,
        "note": "biased diagnostic is not a population estimate or per-class precision claim",
    }


def evaluate(
    audit_bundle: Path, ledger_path: Path, annotations_path: Path, taxonomy_path: Path
) -> dict:
    audit_manifest = json.loads((audit_bundle / "manifest.json").read_text())
    blind_path = audit_bundle / "blind-review.json"
    key_path = audit_bundle / "source-key.json"
    ledger_manifest = json.loads(
        ledger_path.with_suffix(ledger_path.suffix + ".manifest.json").read_text()
    )
    if (
        sha256_file(blind_path) != audit_manifest["file_sha256"]["blind-review.json"]
        or sha256_file(key_path) != audit_manifest["file_sha256"]["source-key.json"]
        or ledger_manifest["audit_manifest_sha256"] != sha256_file(audit_bundle / "manifest.json")
        or ledger_manifest["decision_rule"] != RULE
        or ledger_manifest["output_sha256"] != sha256_file(ledger_path)
        or ledger_manifest["ledger_code_sha256"]
        != sha256_file(Path(__file__).with_name("primary_final_audit_ledger.py"))
        or ledger_manifest["evaluator_code_sha256"] != sha256_file(Path(__file__))
    ):
        raise ValueError("frozen audit or prediction provenance changed")
    taxonomy = load_taxonomy(taxonomy_path)
    if taxonomy.sha256 != FROZEN_TAXONOMY_SHA:
        raise ValueError("frozen taxonomy changed")
    blind = json.loads(blind_path.read_text())
    key = json.loads(key_path.read_text())
    annotations = json.loads(annotations_path.read_text())
    split_by_id = {row["review_id"]: row["split"] for row in key}
    blinded = {"development": [], "holdout_random": [], "holdout_stratified": []}
    for row in blind:
        split = split_by_id[row["review_id"]]
        blinded["holdout_random" if split == "random" else "holdout_stratified"].append(row)
    validate_annotations(blinded, annotations, taxonomy)
    ledger = [json.loads(line) for line in ledger_path.read_text().splitlines()]
    result = score(ledger, annotations)
    result["provenance"] = {
        "audit_manifest_sha256": sha256_file(audit_bundle / "manifest.json"),
        "ledger_manifest_sha256": sha256_file(
            ledger_path.with_suffix(ledger_path.suffix + ".manifest.json")
        ),
        "annotations_sha256": sha256_file(annotations_path),
        "taxonomy_sha256": taxonomy.sha256,
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-bundle", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--annotations", type=Path, required=True)
    parser.add_argument("--taxonomy", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            evaluate(args.audit_bundle, args.ledger, args.annotations, args.taxonomy), indent=2
        )
    )


if __name__ == "__main__":
    main()
