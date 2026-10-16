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

## Product-text review before training

The source archive is not a product-level gold standard. A deterministic
64-product challenge found tags that clearly named the wrong market, including
a Mac battery utility tagged `Apps for kids`. A subsequent class-stratified
diagnostic found a scraping proxy tagged `Maps and GPS`. In the same archive,
167 of the 373 mapped source values occur on ten or fewer products. These
low-support mappings especially need direct product-text review.

Generate a blinded diagnostic set from the verified `products.csv` (SHA-256
`ade78b1994fc60d323e098c059e340270e81f369cc87cc06465af7a60e011dae`):

```bash
uv run python tools/sample_primary_taxonomy_review.py \
  --taxonomy taxonomy/v1-candidate.json \
  --products data/products.csv \
  --output-dir data/taxonomy-review-v1
```

The default seed `taxonomy-review-v1-2026-10-16` selects five uniquely mapped
products per class and two products from source values with at most ten
assignments per class. The current set has 109 distinct products after overlap.
Annotators read `blind-review.json` first and choose a primary market from the
taxonomy boundaries or null, citing product-text evidence. `source-key.json`
keeps the original tags, proposed source mapping, and sample strata separate
until judgments are recorded. `manifest.json` records the seed and both source
hashes. All three generated files remain ignored in local `data/`, outside Git.
The generator refuses to overwrite existing review files so recorded judgments
are not lost.

An independent blind reviewer labeled 24 clear cases from this set before
opening the source key. Twenty agreed with the proposed source mapping and
four disagreed: `Career Switch To Coding` (career versus social), `XYLO`
(personal productivity versus data analytics), `The Commons` (community versus
design), and `Zoomyear` (game/media versus education). The reviewer skipped
ambiguous products, so 20/24 is **not** a precision estimate. These cases
show that product-level source tags can be wrong even when the tag-to-market
mapping is semantically reasonable. They are tuning diagnostics, not held-out
validation.

This is a taxonomy-tuning set, **not** a classifier validation set. It cannot
establish population precision. After adjudicating it and documenting any
mapping changes, reserve a fresh random and stratified sample for Stage 2 and
another independent sample for Stage 7 promotion. The taxonomy remains
unfrozen until those gates are met.
