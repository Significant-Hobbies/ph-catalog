# Primary taxonomy v1 candidate

This is a review candidate, not a frozen training taxonomy or a promoted
product-level classification. The canonical source mapping is
`taxonomy/v1-candidate.json`. Its 16 top-level market categories have explicit
boundaries, a common mapping rationale, and an exact list of original Product
Hunt category strings covered by that rationale. No original source value is
rewritten. The source map is deliberately partial: broad technology, delivery
format, platform, and generic AI tags remain unmapped.

The 2026-10-15 `catalog-state` source archive (SHA-256
`39cc62acf1c8927363fb47abad5032362b08fe99e9b6bc549ad4d770f7955ded`)
contains 575,622 products and 544 distinct source-category values. The current
candidate maps 411 values. Product-level coverage has not been recalculated
after the mapping review; the checked-in audit still describes the earlier
421-value candidate and must not be used as a current coverage or precision
estimate. Products without source categories remain unlabeled.

In particular, `AI Chatbots`, `LLMs`, `AI Agents`, `Chrome Extensions`,
`Search`, and `Physical Products` are unmapped: their names do not establish
a unique product market. Review also removed `Productivity` and its lowercase
alias, `No-code Platforms` and its `No-Code`/`no-code` aliases,
`Newsletter platforms`, `Video hosting platforms`, `AI notetakers`,
`Microblogging platforms`, and `Figma Plugins`. These can span multiple markets
or describe a technology, content format, or plug-in surface rather than a
unique market.
`uncategorized` may be used by a presentation but is never stored as a primary
category. A product with two mapped categories in different markets has a null
primary training label; it is not arbitrarily assigned by source order.

Regenerate the review report from the ignored local archive:

```bash
uv run python tools/audit_primary_taxonomy.py \
  --taxonomy taxonomy/v1-candidate.json \
  --products data/products.csv \
  --output data/taxonomy-v1-candidate-report.json
```

The checked-in `primary-taxonomy-v1-candidate-audit.json` is a stale validation
report from the prior map, retained as review evidence. Regenerate it from the
source archive before using its counts. Generated product datasets stay in
ignored `data/`. Independent review of the mapping and its low-support classes
is required before renaming this `v1` and training the primary-category
classifier.
