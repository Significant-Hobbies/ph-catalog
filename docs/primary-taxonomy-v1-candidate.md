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
contains 575,622 products and 544 distinct source-category values. The map
covers 421 values. Of 94,036 products with at least one source category,
53,894 have exactly one market category after mapping. Another 32,980 have
mapped values in more than one market category and are excluded from
source-supervised training. The remaining 7,162 categorized products have no
unambiguous mapped value. The 481,586 products without source categories also
remain unlabeled. These are coverage figures, not precision estimates.

In particular, `AI Chatbots`, `LLMs`, `AI Agents`, `Chrome Extensions`,
`Search`, and `Physical Products` are unmapped: their names do not establish
a unique product market. `uncategorized` may be used by a presentation but is
never stored as a primary category. A product with two mapped categories in
different markets has a null primary training label; it is not arbitrarily
assigned by source order.

Regenerate the review report from the ignored local archive:

```bash
uv run python tools/audit_primary_taxonomy.py \
  --taxonomy taxonomy/v1-candidate.json \
  --products data/products.csv \
  --output data/taxonomy-v1-candidate-report.json
```

The checked-in `primary-taxonomy-v1-candidate-audit.json` is a validation
report. Generated product datasets stay in ignored `data/`. Independent review
of the mapping and its low-support classes is required before renaming this
`v1` and training the primary-category classifier.
