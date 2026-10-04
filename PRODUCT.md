# PH Catalog / Atlas

PH Catalog helps developers and product researchers import, verify, snapshot
and inspect a local catalogue with explicit provenance. Python normalizes
product records into DuckDB and Parquet; Atlas is the read-only local analytics
interface described in `site/README.md`. Missing evidence and relative launch
order remain explicit. Real catalogue data and analytical marts stay local.

The public `landing/` tree demonstrates the parser's actual evidence shape with
three original fictional products. It is a static experiment/reference
surface, without live market data or a hosted analytics app. Its next actions
are inspecting fictional evidence, reading the source and following the
documented local workflow. The source fixtures under `samples/` remain intact.

The shared footer retains real native routes, external AI question handoff,
the existing consented PH Catalog newsletter and optional studio discovery.
These utilities do not turn fictional evidence into real products or make
claims about update frequency, market freshness or analytical completeness.
The private loopback app is outside this public-footer release.

Implementation and product truth: `README.md`, `site/README.md`,
`docs/internal-analytics.md`, `landing/index.html` and `tests/test_landing.py`.
