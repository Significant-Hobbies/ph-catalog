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
candidate maps 373 values. The matching checked-in audit finds 94,036 products
with source categories: 54,633 have one source-derived candidate, 27,611 have
conflicting mapped categories, and 11,792 have no mapped category. These are
coverage counts, not classifier accuracy or precision. Products without source
categories remain unlabeled.

In particular, `AI Chatbots`, `LLMs`, `AI Agents`, `Chrome Extensions`,
`Search`, and `Physical Products` are unmapped: their names do not establish
a unique product market. Review also removed `Productivity` and its lowercase
alias, `No-code Platforms` and its `No-Code`/`no-code` aliases,
`Newsletter platforms`, `Video hosting platforms`, `AI notetakers`,
`Microblogging platforms`, and `Figma Plugins`. A second independent semantic
pass removed 38 more broad or platform-only labels, including `AI Generative
Media`, `Books`, `sports`, `email`, `Newsletters`, and their relevant aliases.
Archive examples span several markets for these terms: `Books` includes a book
discovery catalogue and a marketing guide, while `AI Generative Media` includes
creative tools, a team workspace, and interview-answer software. These labels
cannot establish one primary market by themselves. The excluded values can
still accompany a more specific mapped category as original source evidence.
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

The checked-in `primary-taxonomy-v1-candidate-audit.json` was regenerated from
the source archive above after the mapping review; its taxonomy SHA-256 matches
the candidate file. Generated product datasets stay in ignored `data/`. A
separate low-support class and product-level precision audit is still required
before freezing `v1` and training the primary-category classifier.
