# Catalogue analytics and enrichment plan

## Objective

Deliver useful internal analytics and a browsable catalogue immediately, while
incrementally improving one `primary_category` and a unified `labels` array.
Expensive network or model work must be routed only to uncertain products.

## Canonical analytical shape

```json
{
  "slug": "example-product",
  "primary_category": {
    "value": "developer_tools",
    "confidence": 0.91,
    "method": "local_classifier",
    "taxonomy_version": "v1"
  },
  "labels": [
    {
      "value": "python",
      "kind": "technology",
      "confidence": 0.95,
      "method": "gliner_small_v2_1",
      "evidence": "Built with Python"
    }
  ],
  "source_categories": [
    {"value": "Developer Tools", "source": "producthunt"}
  ]
}
```

Rules:

- `primary_category` is outside `labels` and is null when evidence is weak.
- A product has no more than one primary category per taxonomy version.
- Tags and NER entities share `labels`; `kind` preserves their semantics.
- Original Product Hunt categories are unchanged source evidence.
- Every derived value retains method, confidence, taxonomy version, and optional
  evidence.

## Stage 0 — Existing-data product

Status: implemented as a reproducible DuckDB analytics mart.

Ship without new crawling or model inference:

- Catalogue composition from 574,752 complete products.
- Product Hunt category analytics for 93,184 categorized products.
- Existing trusted label analytics for 247,788 products.
- 709,644 product-to-launch relationships and relaunch multiplicity.
- Domain/host concentration and distribution-channel analysis.
- Text clusters, keyword prevalence, boilerplate, spam, and anomaly detection.
- Search/category/collection discovery-surface coverage.
- Static browsing pages and individual product details.

Build the internal mart from the rich crawler database and the audited trusted
label file:

```bash
uv run python tools/build_analytics.py \
  --catalog-db data/producthunt.duckdb \
  --trusted-labels data/analytics/product-tags-v1-trusted.parquet \
  --output data/analytics/catalog-analytics.duckdb \
  --summary-output data/analytics/catalog-analytics-summary.json
```

After the full NER output passes a fresh audit, include it without changing the
base catalogue by adding:

```text
--entities data/ner-v1/product-entities.parquet
```

The mart includes `product_facts`, normalized category/label/entity/launch
tables, domain and relaunch summaries, co-occurrences, and 20 relative launch
cohorts. `label_relative_trends` compares the earliest and latest quarter of
products by first post ID and reports both raw catalogue share and share among
products that received any trusted label, controlling for changing label
coverage. It is useful for directional exploration but is explicitly not a
calendar-time series.

Boundaries:

- The portable archive has no verified launch date.
- Product and post IDs provide relative order, not calendar dates.
- Votes and comment counts are not present.

## Stage 1 — Freeze a primary taxonomy

Define approximately 12–18 mutually exclusive top-level market categories.
Map the 540 original Product Hunt category values into that taxonomy. Review the
mapping independently before it becomes training data. Keep `uncategorized` as
a presentation value while storing genuine uncertainty as null.

Acceptance gate:

- Every mapped source category has a documented rationale.
- Ambiguous Product Hunt categories can remain unmapped.
- The taxonomy is versioned and frozen before model training.

## Stage 2 — Primary-category classifier

Train a local multiclass text classifier using name, tagline, and description
from the approximately 93,000 source-categorized products. Use deterministic
train/validation/test splits by slug. Calibrate confidence and class-margin
thresholds and abstain below them.

Outputs:

```text
slug, primary_category, confidence, runner_up, margin,
method, taxonomy_version, evidence_hash
```

Acceptance gate:

- Report macro precision/recall and per-category confusion.
- Audit a fresh random sample and a stratified sample per category.
- Do not infer a primary category merely from implementation technology.

### Product-label gate before training

Source tags are weak sampling strata, not gold labels. A blinded local protocol
reserves three disjoint slug sets before annotation: 200 lowest SHA-256-ranked
products from the full archive for a random holdout; up to 20 per provisional
source category plus conflicting/no-map strata for a separate holdout; and up
to 40 per stratum for development. The previous 109 taxonomy-tuning slugs,
1,221 pre-freeze candidate-bundle slugs, and 2,440 slugs in two superseded
freeze drafts are excluded from all three. Selection
is independent of CSV row order. Blind
files contain only name, tagline, and description; the local key keeps slugs,
original tags, provisional source mapping, and strata separate. The random
set includes sparse and uncategorized products so coverage claims can include
abstention on the real archive, not only easy classified products.

```bash
uv run python tools/primary_label_protocol.py sample \
  --taxonomy taxonomy/v1.json \
  --products data/products.csv \
  --previous-tuning-key data/taxonomy-review-v1/source-key.json \
  --exclude-key data/primary-label-v1-2026-10-16/source-key.json \
  --exclude-key data/primary-label-v1-frozen-2026-10-16/source-key.json \
  --exclude-key data/primary-label-v1-frozen-2026-10-16-r2/source-key.json \
  --output-dir data/primary-label-v1-frozen-2026-10-16-r3 \
  --seed primary-label-v1-frozen-2026-10-16-r3

uv run python tools/primary_label_protocol.py check \
  --taxonomy taxonomy/v1.json \
  --bundle data/primary-label-v1-frozen-2026-10-16-r3 \
  --annotations data/primary-label-v1-frozen-2026-10-16-r3/annotations-template.json
```

Annotators fill a separate copy of the annotations template without opening
the source key. `single` requires exactly one taxonomy category and an exact
product-text evidence span. `co_primary` requires at least two categories and
an evidence span for each; it stays null for training. `null` requires one of
`insufficient_text`, `underdetermined`, or `outside_taxonomy`. Every decision
records a reviewer ID. `check` validates the blind-file hashes and decisions
without opening the source key. Once development annotations are complete,
`export-development` may join only their slugs after checking the private key
hash; its output contains labels and text hashes, never source tags or product
text. Holdout annotations remain sealed until the taxonomy, model, and
thresholds are fixed. Generated data and annotations stay ignored outside Git.

The `evaluate` command accepts a frozen local-classifier prediction file,
model artifact, and threshold file. Each prediction names a heldout slug, a
nullable category, runner-up, confidence, margin, and SHA-256 hash of the
name/tagline/description input. The top-level prediction document names the
taxonomy, model, and threshold hashes. Evaluation checks every heldout slug,
all hashes, and the independent true-label support gate before writing a
report. It reports random-sample coverage and abstention separately from
stratified macro/per-category precision, recall, and confusion. Null and
co-primary judgments are ground-truth abstentions; predicting a class for
them is a false positive. No `evaluate` report exists for the frozen taxonomy
because its product-label gate is closed.

The frozen `v1` mapping and audit are documented in
`docs/primary-taxonomy-v1.md`. On the 2026-10-15 archive, its new local bundle
excludes all 109 previous taxonomy-tuning slugs, all 1,221 slugs from the
pre-freeze candidate bundle, and 2,440 from two superseded freeze drafts.
Those old bundles remain protocol rehearsals, not final evaluation evidence.
The disjoint frozen-hash bundle
reserves 680 development, 200 random-holdout, and 340 source-stratified-
holdout records. After 3,770 exclusions, zero source-derived `home_lifestyle`
records remain for development or stratified holdout. Independent product-text
review and a 64-record development QA have completed the 680 development
labels: 605 single, 14 co-primary, 61 null. The 540 main holdouts remain
unreviewed. The `check` gate requires a frozen taxonomy,
completed development labels, at least 30 true
single-label development examples per class, at least 20 true single-label
stratified-holdout examples per class, and a 200-record random holdout before
evaluation. These are conservative local readiness floors, not measured model
quality. The training and evaluation gates remain closed despite the frozen
ontology. Additional product-text discovery, resampling, and independent
adjudication are needed for `home_lifestyle`; mapping coverage must never be
substituted for that evidence. If the taxonomy changes, version it and reserve
new holdouts under the new hash.

The supplemental text-only home discovery protocol has 160 independently
reviewed development records, including 80 true single home labels, and an
untouched 80-record heldout. Main plus home development support is still short
for social (21) and data (27), so a second text-only discovery protocol reserves
160 development/80 sealed heldout social/data candidates disjoint from every
earlier sample. Its 160 development records have independent product-text
labels: 144 single, 10 co-primary, 6 null. Combined true single-label support
across all three development bundles now reaches at least 30 in all 16
categories (35 minimum), but training still requires an explicit combined
gate and slug-split protocol. All 700 heldouts remain unreviewed. Both
protocols and their biased-sample limits are documented in
`docs/primary-taxonomy-v1.md`. Source tags and keyword matches are sampling
aids only; neither is an independent product label. Do not open any heldout
until model and thresholds are fixed.

### Combined development gate and local candidate

`tools/primary_combined_development.py` rechecks all three ignored bundle
manifests, blind-file hashes, frozen taxonomy and archive SHA, complete
development annotations, disjoint slugs, and sealed heldout annotations. It
hash-checks heldout blind files without parsing their text, and exports only
slug, product text, decision, and text hash after every class reaches 30 true
single development labels. The current combined export has 1,000 development
rows (885 single, 29 co-primary, 86 null) and preserves the 700 heldouts,
including the original 200 random records. The local classifier rechecks the
source bundles against this export before fitting; it rejects stale or
modified annotation and sample provenance.

The optional `classifier` dependency installs scikit-learn only for local
training. Two fixed sparse linear candidates use either word TF-IDF or word
plus character TF-IDF, balanced logistic regression, and internal 3-fold
sigmoid probability calibration. Five deterministic slug folds produce
out-of-fold development predictions. A fixed threshold grid chooses the
largest non-null OOF coverage with at least 85% observed precision and 30
predictions; null and co-primary development records count as true abstentions.
The word-plus-character candidate selected 34.1% OOF coverage at 85.9%
observed non-null precision, 85.2% null/co-primary abstention, and 0.856/0.333
macro precision/recall. Word-only gave 26.7% coverage at 85.8% precision.
These are **optimistic development tuning diagnostics**, not independent
accuracy estimates. Business and finance OOF recall are especially weak;
broad promotion is not justified by this candidate.

The chosen local artifact is pinned by model SHA-256
`a561cb0d70129e25f56893abc6c4ee853391c6a9169d12aec20d308030f8b847`
and threshold SHA-256
`6bf58337cf258cd889c908914831b38f39a77dc7cb7e16f7bf56202681ae9aa3`.
Feature configuration, fold seed, development export hash, and OOF report are
in the ignored candidate manifest. A repeat run reproduced identical OOF and
final development probabilities, though serialized joblib bytes differed; use
the pinned artifact for subsequent inference. No heldout product text or
labels informed this choice. Before Stage 2 can pass, generate predictions
from that frozen artifact and independently label/evaluate the 700 reserved
heldouts. The original random 200 must estimate archive-level coverage
separately from biased supplemental class-discovery samples. The 340
source-stratified main holdouts may have insufficient true per-class support,
especially home; add a new disjoint class-targeted heldout without retuning if
the registered support gate fails. Stages 4–7 remain dependent work.

## Stage 3 — Concrete local NER labels

Status: implemented and benchmarked.

The Apache-2.0 GLiNER Small v2.1 pipeline extracts concrete evidence for
technology, platform mentions, operating system, file format, hardware,
audience, and explicit industry phrases. It writes atomic 10,000-product shards
and resumes by skipping complete shards.

```bash
uv sync --extra ner

uv run --extra ner python tools/ner_enrich.py \
  --source producthunt-full.parquet \
  --output-dir data/ner-v1 \
  --device auto --batch-size 32 --shard-size 10000

uv run --extra ner python tools/ner_filter.py \
  --parts-dir data/ner-v1/parts \
  --output data/ner-v1/product-entities-v3.parquet \
  --audit-output data/ner-v1/audit-sample.json

uv run python tools/ner_audit_sample.py \
  --entities data/ner-v1/product-entities-v3.parquet \
  --products producthunt-full.parquet \
  --output data/ner-v1/stratified-audit.json \
  --per-type 10 --rare-per-type 5
```

The audit generator samples each retained entity type independently, adds a
separate low-support tail stratum, and embeds the relevant product text. Fill
its verdict fields manually; do not tune rules on that sample and then reuse it
as final quality evidence.

The completed run processed 572,993 products with at least 40 characters of
tagline/description text. It produced 58 atomic raw shards and 278,610 raw
candidates. Frozen precision filter v3 retained 115,504 assignments for 75,713
products. The untouched 100-assignment final sample included 10 random
assignments per entity type plus up to five assignments with support of five or
fewer products. Manual review found 97/100 correct types and 100/100 relevant
mentions. Hardware was the weakest type at 13/15; the three failures remain in
the audit evidence and were not used for post-audit tuning.

## Stage 4 — Confidence routing

Combine classifier confidence, disagreement, text-quality flags, and NER
evidence. Accept high-confidence products immediately. Route only products with
one or more of these conditions:

- No primary category above threshold.
- Small margin between the two most likely categories.
- Product Hunt tagline and description contradict one another.
- Boilerplate, placeholder, spam, or unusually short copy.
- No useful labels or a strong label/category conflict.
- A destination type known to carry better structured metadata.

## Stage 5 — Selective website evidence

Fetch only public pages for routed products. Respect robots directives,
Retry-After, persistent denial, and the existing global request cap. Do not
download media or bypass access controls.

Extract, in order:

1. JSON-LD Product, SoftwareApplication, and Organization fields.
2. Open Graph title and description.
3. Standard title and meta description.
4. Main heading and short feature/value-proposition sections.
5. At most one obvious about, features, or product page when justified.

Store evidence text, URL, field type, fetch time, content hash, and outcome.
Never overwrite Product Hunt source text; reclassify from a combined evidence
view.

## Stage 6 — Local 8B/27B fallback

Run only on products still unresolved after website enrichment. Batch multiple
products per prompt and require schema-constrained output. Do not store verbose
reasoning. Store the selected category, labels, confidence, short cited evidence
spans, model identifier, prompt version, and input hash.

Use the larger model for:

- Primary-category arbitration.
- Abstract themes and use cases that NER cannot extract.
- Resolving conflicts between Product Hunt and website evidence.
- Proposing labels from the frozen vocabulary.

The model must be allowed to return null/unknown.

## Stage 7 — Validation and promotion

Every taxonomy/model/prompt version produces immutable candidate outputs. It is
promoted only after:

- A new deterministic random audit not used for tuning.
- A stratified audit by primary category and confidence band.
- Separate checks for source-only, website-enriched, and LLM-fallback records.
- Confusion/error analysis and documented exclusions.
- Coverage and precision reported independently.

Do not tune on an audit sample and then reuse it as evidence for accuracy.

## Distribution to another machine

The private GitHub Release `catalog-state` already contains:

```text
ph-catalog-full.tar.zst
producthunt-full.parquet
```

Fresh-machine setup:

```bash
git clone https://github.com/sarthakagrawal927/ph-catalog
cd ph-catalog
gh release download catalog-state -p producthunt-full.parquet
uv sync --extra ner
```

Generated datasets stay in Release assets or local storage, not Git history.
Source code, schemas, validation reports, and the plan remain version-controlled.
