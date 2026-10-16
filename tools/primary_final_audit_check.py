"""Recompute a sealed Stage 7 audit reservation before blind annotation."""

import argparse
import json
from pathlib import Path

from ph_catalog.primary_final_audit_sample import check


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-mart", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--pilot-routes", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            check(args.source_mart, args.data_root, args.pilot_routes, args.bundle), indent=2
        )
    )


if __name__ == "__main__":
    main()
