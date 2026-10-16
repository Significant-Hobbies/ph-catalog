"""Reserve blinded product-text candidates for sparse social and data labels.

Patterns are discovery aids, not category labels or representative strata.
The source-category column is never read by this sampler.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ph_catalog.primary_home_discovery import select_text_discovery
from ph_catalog.primary_label_protocol import write_bundle

PATTERNS = {
    "peer_networks": (
        r"\b(?:social network(?:ing)?|make (?:new )?friends|friendship app|"
        r"meet (?:new )?people|connect with like-minded|dating app|find (?:a )?partner)\b"
    ),
    "community_spaces": (
        r"\b(?:online communit(?:y|ies)|community platform|join (?:a|the) community|"
        r"group chat|chat with friends|social app|social platform|community app)\b"
    ),
    "business_intelligence": (
        r"\b(?:business intelligence|(?:business|data|product) dashboard|BI dashboard|"
        r"data visualization|visualiz(?:e|ing) data|analytics dashboard|"
        r"reporting dashboard)\b"
    ),
    "measurement_insights": (
        r"\b(?:data analy(?:sis|tics)|analyz(?:e|ing) (?:your |business )?data|"
        r"(?:business|product) metrics|insights from data|"
        r"track (?:business|product) (?:metrics|KPIs)|monitor (?:your )?metrics)\b"
    ),
}


def select_sparse_discovery(
    products_csv: Path,
    taxonomy_path: Path,
    exclusion_keys: tuple[Path, ...],
    *,
    seed: str,
    development_per_group: int = 40,
    heldout_per_group: int = 20,
):
    return select_text_discovery(
        products_csv,
        taxonomy_path,
        exclusion_keys,
        patterns=PATTERNS,
        protocol="sparse-text-discovery-v1",
        purpose="supplemental social/data development support; groups are not true labels",
        seed=seed,
        development_per_group=development_per_group,
        heldout_per_group=heldout_per_group,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--taxonomy", type=Path, required=True)
    parser.add_argument("--products", type=Path, required=True)
    parser.add_argument("--exclude-key", type=Path, action="append", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--seed", default="sparse-text-discovery-v1-2026-10-16")
    parser.add_argument("--development-per-group", type=int, default=40)
    parser.add_argument("--heldout-per-group", type=int, default=20)
    args = parser.parse_args()
    blind, key, manifest = select_sparse_discovery(
        args.products,
        args.taxonomy,
        tuple(args.exclude_key),
        seed=args.seed,
        development_per_group=args.development_per_group,
        heldout_per_group=args.heldout_per_group,
    )
    write_bundle(args.output_dir, blind, key, manifest)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
