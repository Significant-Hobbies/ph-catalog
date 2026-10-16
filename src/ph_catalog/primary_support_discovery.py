"""Reserve a blind, biased support audit for five underfilled heldout classes.

Patterns use product titles only. They discover candidates; they are not labels
or model features, and this supplemental sample is not population-representative.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ph_catalog.primary_home_discovery import select_text_discovery
from ph_catalog.primary_label_protocol import write_bundle

PATTERNS = {
    "business_operations": (
        r"\b(?:project management|team management|employee scheduling|"
        r"inventory management|contract management|workflow management|"
        r"office management|business operations|staff management)\b"
    ),
    "health_wellness": (
        r"\b(?:mental health|health tracking|fitness tracker|workout planner|"
        r"sleep tracker|nutrition tracker|medical care|patient care|"
        r"medication reminder|therapy app)\b"
    ),
    "security_privacy": (
        r"\b(?:password manager|two.factor authentication|malware scanner|"
        r"privacy protection|security scanner|secure browsing|"
        r"vulnerability scanner|identity protection|vpn service)\b"
    ),
    "travel_local": (
        r"\b(?:trip planner|travel planner|flight booking|hotel booking|"
        r"travel itinerary|route planner|local guide|tour booking|"
        r"travel guide|public transit)\b"
    ),
    "work_careers": (
        r"\b(?:job search|job board|resume builder|cv builder|"
        r"career coach|career planning|recruitment platform|"
        r"applicant tracking|candidate sourcing|interview preparation)\b"
    ),
}


def select_support_discovery(
    products_csv: Path,
    taxonomy_path: Path,
    exclusion_keys: tuple[Path, ...],
    *,
    seed: str,
    heldout_per_group: int = 25,
):
    return select_text_discovery(
        products_csv,
        taxonomy_path,
        exclusion_keys,
        patterns=PATTERNS,
        protocol="heldout-support-text-discovery-v1",
        purpose=(
            "additional biased heldout support audit for five underfilled true-label classes; "
            "no model or threshold tuning"
        ),
        seed=seed,
        development_per_group=0,
        heldout_per_group=heldout_per_group,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--taxonomy", type=Path, required=True)
    parser.add_argument("--products", type=Path, required=True)
    parser.add_argument("--exclude-key", type=Path, action="append", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--seed", default="heldout-support-text-v1-2026-10-16")
    parser.add_argument("--heldout-per-group", type=int, default=25)
    args = parser.parse_args()
    blind, key, manifest = select_support_discovery(
        args.products,
        args.taxonomy,
        tuple(args.exclude_key),
        seed=args.seed,
        heldout_per_group=args.heldout_per_group,
    )
    write_bundle(args.output_dir, blind, key, manifest)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
