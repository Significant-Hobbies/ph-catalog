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
products from the eligible `data/products.csv` rows after 3,770 prior-review
exclusions for a random holdout; up to 20 per provisional
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
independently reviewed. The `check` gate requires a frozen taxonomy,
completed development labels, at least 30 true
single-label development examples per class, at least 20 true single-label
stratified-holdout examples per class, and a 200-record random holdout before
evaluation. These are conservative local readiness floors, not measured model
quality. The later combined development gate passed and a classifier was
frozen, but the original targeted heldout support gate remains closed. Mapping
coverage must never be substituted for independently reviewed labels. If the
taxonomy changes, version it and reserve new holdouts under the new hash.

The supplemental text-only home discovery protocol has 160 independently
reviewed development records, including 80 true single home labels, and an
independently reviewed 80-record heldout. Main plus home development support was short
for social (21) and data (27), so a second text-only discovery protocol reserves
160 development/80 independently reviewed heldout social/data candidates disjoint from every
earlier sample. Its 160 development records have independent product-text
labels: 144 single, 10 co-primary, 6 null. Combined true single-label support
across all three development bundles now reaches at least 30 in all 16
categories (35 minimum), and a combined gate and slug-split protocol were
completed before training. All 700 heldouts were independently reviewed after
the model and predictions were frozen. Both
protocols and their biased-sample limits are documented in
`docs/primary-taxonomy-v1.md`. Source tags and keyword matches are sampling
aids only; neither is an independent product label. New holdouts must remain
sealed until their predictions are fixed.

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
labels informed this choice. Predictions from that frozen artifact were fixed
before independent review of the 700 reserved heldouts (642 single, 14
co-primary, 44 null). The
500 targeted records had true single support below 20 in five classes:
business operations 18, health/wellness 18, security/privacy 19, travel/local
18, and work/careers 18. No model metrics were computed while this label gate
was closed. The original random 200 must estimate coverage in its eligible
archived CSV population separately from biased supplemental samples. Stages
4–7 remain dependent work.

`tools/primary_heldout.py predict` is the frozen candidate's inference path.
It pins the taxonomy, development export, candidate manifest, model, and
threshold file hashes before loading the joblib artifact. It verifies all
three bundle manifest, source-key, blind-file, annotation, split, and disjoint
slug contracts, requires all heldout verdict fields blank, then reads only
the 700 blind product texts for prediction. It writes nullable categories,
confidence, runner-up, margin, and exact text hashes to an ignored local
prediction file. The source tags and discovery groups are never model inputs.
Its output must be fixed before independent heldout annotation begins.
The current ignored prediction file is
`data/primary-model-v1/heldout-predictions-v1.json`, SHA-256
`e97a8c855d09bcf53a607ca4965e63c177a326132f40668b9143c55e2403eef3`;
two clean runs produced identical bytes. This fixes 700 predictions, not their
correctness. Independent first, second, and adjudication passes produced the
final 700-label ignored artifact before any model metrics were computed.

`tools/primary_heldout.py evaluate` requires completed independent labels and
replays the pinned model on the same texts. It rejects predictions that differ
from that replay. The registered label gate needs the original random 200 and
at least 20 true single-label examples for **each** taxonomy class across the
500 targeted records. If support is short, it reports shortfalls without
metrics. When open, the report separates original random, source-stratified
main, supplemental home, supplemental sparse, and combined targeted results.
Only the original random set supports coverage estimates for the eligible
archived CSV population after 3,770 prior-review exclusions; targeted and
supplemental precision/recall are sample-specific diagnostics.
All outputs and annotations stay under ignored `data/`, never in Git.

To address the five support shortfalls without changing the classifier,
`tools/primary_support_discovery.py` reserves 25 name/tagline matches per
class, zero development examples, and no random examples. Its fixed seed and
seven prior source-key exclusions remove 5,470 distinct previously sampled
slugs. The 125 blind records omit query groups and source tags; the ignored
key and manifest retain reproducible selection evidence. The release archive
SHA-256 matches the three frozen bundles. This is a deliberately biased
supplement, so its class outcomes and performance cannot estimate population
precision. The supplemental manifest SHA-256 is
`d76f2a9233590585b6a699ff0945e801644bee1b08f001f1d26866a2c5b17cc2`.
`tools/primary_augmented_heldout.py predict-support` replayed the same frozen
candidate on all 125 still-sealed texts, producing ignored predictions SHA-256
`456ba7200a937116ac17edce043ab1220b51d28771e5e4500008575a24b63642`.
Independent labeling must follow this pinned output. Its augmented evaluator
replays both prediction sets and holds every metric until all 16 classes have
at least 20 true single labels across 625 targeted records; if open, it
reports the original random 200 separately from each biased stratum.

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

The candidate router in `tools/primary_confidence_routing.py` reads the
existing analytics mart's `product_facts` text, website URL, NER entity
count when available, and trusted-label count. It loads the pinned v1
classifier and thresholds, accepts a strong result with usable copy locally,
and marks
abstentions, explicit placeholder/duplicated/short copy, or strong
tagline-versus-description model disagreement for later evidence. A lack of
NER/other labels only adds context to an already abstained product; technology
mentions never imply a market category. A routed record with an external URL
is a website-evidence candidate; Stage 5 must validate that URL before
fetching. One without an external URL remains unresolved for non-web review.
The router emits candidate decisions and reasons to ignored JSONL; it does
not publish a primary category. Routed rows keep the model suggestion only as
`candidate_category`; `primary_category` is null until accepted. Both the
library entrypoint and rehearsal command require all four pinned
development/holdout bundles as slug exclusions, so independent
evaluation examples cannot influence routing rules. Spam and taxonomy-level
label/category conflict checks remain open rather than inferred from weak NER
signals. A three-product synthetic run with the pinned model accepted clear
developer copy, routed placeholder copy, and abstained on technology-only
copy. Stage 4 promotion waits for the independent Stage 2 audit.

## Stage 5 — Selective website evidence

Status: a provisional routed-only evidence fetcher is implemented
in `tools/primary_website_evidence.py`; no live product-site run or category
promotion has occurred. It consumes a hash-checked Stage 4 JSONL/manifest,
rejects altered routes and all four reserved review/holdout bundles, and
refuses to overwrite prior output. The actual TCP backend pins a freshly
resolved global address, with HTTPX redirects disabled and every redirect URL
rechecked. Robots parsing uses patched Protego >=0.6.2 for RFC 9309 rule
matching; the fetcher handles robots status, the RFC's five-redirect minimum
for robots even when the page-redirect cap is lower, 24-hour cache,
Retry-After, persistent denial, 2 RPS, request/page/byte/redirect/time caps,
and HTML Content-Type before streaming body. It requests identity encoding and
rejects unexpected compressed responses before reading them, so the byte cap
applies to the decoded body without unbounded decompression. It extracts ordered structured,
social, standard, and short section fields, and fetches at most one obvious
same-origin about/features/product page when the first page yields no fields;
that secondary page's redirects cannot leave the primary page's origin.
Its ignored JSONL keeps each field's page role, source URL, fetch time,
response hash, and outcome. It never updates Product Hunt source fields.
Live product-site validation and a combined evidence classification view
remain open before Stage 5 acceptance.

A bounded 2026-10-16 live pilot used five hand-picked weak-copy products from
the verified `catalog-handoff-v1` analytics mart. A five-row mini-mart kept
the original `product_facts` text, URLs, and auxiliary counts; frozen routing
excluded all 1,825 development/holdout slugs. All five routed to public HTTPS
sites. The fetcher made ten requests including robots, fetched five HTML pages
with HTTP 200, and retained 6, 4, 1, 2, and 1 fields respectively. Robots
returned 4xx, which allowed these requests under the protocol. The routed
output SHA-256 is `8c9c450167f072e9e3412ff3a85e6aae5bc27486affd96ae4e04643ee64d3460`;
the ignored evidence output SHA-256 is
`338030a328afdb73227495ebfade30658f1e47f647d289d239564e589d9162e9`.
This selected pilot validates the fetch path only; title-only pages remain
weak evidence and no classifier or category was promoted.

`tools/primary_stage5_handoff.py` joins the pinned routing and website
artifacts into another immutable, ignored JSONL/manifest. It passes only
non-web routes and website routes with a completed fetch, marks each as
provisionally unresolved with a reason, and pins the evidence-row hash. It
rejects altered manifests or field provenance; unfetched website routes stay
queued for Stage 5. The pilot handoff contains five unresolved rows, output
SHA-256 `e812ea367dcec1cbed799298b0c6452a90fa7969db1573c765393105ec83d540`.
Stage 6 may use this as an input gate after its own schema, citation, and
model-evaluation checks; this handoff is not a category decision.

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

Status: `tools/primary_local_fallback.py` implements a bounded, category-only
local candidate behind the pinned unresolved handoff. It rechecks the routing,
website, handoff, source-mart, taxonomy, model, and reservation hashes before
reading source product text. It batches two to four products, allows null,
requires one or two exact field-ID citations for each proposed category, and
fails malformed batches to null/error rows. The local Ollama digest, prompt
version/hash, input hash, taxonomy hash, and cited source URL/response hash
are retained in immutable ignored output; the pipeline artifact does not store
raw prompts, responses, reasoning, or generated labels. The model's confidence
is uncalibrated.
No label generation is enabled until a versioned label vocabulary exists.

The same five selected Stage 5 pilot products were tested locally on
2026-10-16 with two installed models and the same v2 prompt/schema, which
explicitly treats PH and website fields as untrusted data. Qwen3.5 9B
produced five fail-closed errors from inexact citations or invalid null
fields (output SHA-256 `226f2edcc45025c4debff3c876b76c0ec38ee02e4c5906e3cbd08a7d955dbe74`);
Qwen3.5 27B produced five schema-valid, exactly cited category candidates
and no errors (output SHA-256
`d40f6e7bbf97fd47b00ee7fcece3604c204a08d347c4e41c237d9ef4d3f9662d`).
This is a protocol smoke test on five hand-picked products, with no
independent gold labels, calibrated confidence, or quality estimate.
Promotion and wider Stage 6 evaluation remain open.

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

Status: a new, sealed independent audit reservation exists locally; no audit
labels or precision result exist. `tools/primary_final_audit_sample.py` first
excluded all eight earlier tuning/development/holdout source-key bundles and
the five Stage 5/6 pilot slugs: 5,600 distinct reserved slugs, of which 31
are absent from the archived analytics mart. It then ranked the full mart
by a fixed seed. Of 574,752 mart products, 5,569 excluded slugs are present,
leaving a 569,183-product random denominator. It reserved 200 random products
regardless of routing outcome. A separate disjoint 5,000-product screen was
run through the frozen Stage 4 model and yielded 120 model-stratified audit
records selected by category (or explicit abstention), confidence band, and
Stage 4 path. These 120 are a biased diagnostic, not part of the random
denominator. The 320 text-only blind records and private source/stratum key
are ignored; all 320 annotation templates remain `unreviewed`. The
recomputation check `tools/primary_final_audit_check.py` verifies the population,
exclusions, deterministic selection, source text, route hashes, and seal.
Blind SHA-256: `f4eb461c92dd4dede831646a72986d7387830ca01c5da03d29735ff6df5843e4`.
Ignored reservation manifest SHA-256: `f8c3fc478236acd898a9929063fb56af4d108c036a98e1de1a5a2c277870479d`.
It pins sampler code SHA-256 `1a9f213fb4a2637316165179d108dc892842d72204e558ed0e1a0a64bfaa9318`;
changing the selector requires a new sealed reservation before annotation.

The random 200 contain 61 Stage 4 local source-text accept candidates, 120
website-evidence routes, and 19 non-web routes; the separate 120 stratified
records contain 94, 19, and 7 respectively. These are routing counts, not
correctness or final path rates. Final reporting must keep the random sample
as the representative coverage/precision denominator and show separate
source-text-only, website-evidence, and LLM candidate slices. If Stage 6 is
used after website evidence, report it in the LLM slice with a website-evidence
subgroup; never count it twice as a website-only decision. No Stage 5 HTML or
Stage 6 output for these 320 has been used to choose the sample, and their
labels must stay sealed until all relevant outputs, model/prompt versions, and
decision rules are fixed. The 1,825 frozen development/heldout rows and
five-product pilot are excluded from this final audit. Completing website and
LLM candidate paths, independent annotation/QA, and Stage 7 confusion and
precision analysis remain open; do not tune frozen decisions on these labels.

This reservation is not a promotion audit result. The 120 diagnostic records
were selected using predicted category and have at most three records per
category/confidence/path cell; they cannot estimate true-category recall or
population precision. Before opening any of the 320 labels, produce immutable
Stage 4/5/6 outputs or explicit null/error outcomes for every reserved record,
pin their hashes and decision rules, and pre-register acceptance thresholds.
Fetches must select the reserved website-route subset rather than the first
website routes in the 5,200-product screening file. The random 200 alone form
the representative precision and coverage frame; report its accepted count
and uncertainty interval. Stage 6 confidence is uncalibrated and must not be
pooled with the Stage 4 confidence bands. The current frozen model's earlier
random heldout precision remains below a broad publication bar, so no category
is promoted by this reservation.

Pre-registered decision rule for this audit, fixed before any labels open:
an accepted categorical decision is correct only when it exactly equals the
independent unique-primary gold category. A category on a gold co-primary or
null record is counted wrong; abstention, fetch denial, timeout, malformed
model output, and missing path output remain uncovered and stay in the random
200 denominator. Report accepted/correct counts, coverage, and the 95% Wilson
precision interval over accepted random records. Broad publication requires
at least 50% random coverage and a Wilson lower precision bound of at least
90%. Each path admitted to publication additionally needs at least 30
accepted random decisions and the same 90% lower bound; a class-specific
claim requires at least 30 independently true-class records in the random
sample. Report source-text-only, website-evidence-only, and LLM-final paths
separately, with LLM-after-website as a subgroup, and count each product once.
The 120 biased diagnostic records can reveal errors but cannot replace these
population gates or establish class precision. A failed gate remains a
reported limitation of #17, not an automatic new task or a reason to tune on
this audit.

Candidate decision mapping is fixed before gold: a Stage 4 `candidate_accept`
uses its pinned `primary_category`; routed website evidence alone makes no
categorical decision, so website-only accepted count is zero under the current
implementation. A Stage 6 schema-valid cited `candidate` is a final audit
category regardless of its uncalibrated numeric confidence. Stage 6 `null`,
`error`, or an explicitly unattempted record is uncovered. A website route
subsequently classified by Stage 6 belongs only to the LLM-final path, with a
website-evidence subgroup. This mapping assesses current candidates; it does
not authorize publication if any promotion gate fails.

Protocol provenance: the first 25 selected unresolved products were run with
the prior v2 local prompt while gold labels were still sealed. Six products
failed closed on null formatting: the validator required zero confidence and
empty citations for null, while the prompt had not explicitly said so. The
v2 first-25 output is retained as a failed diagnostic, excluded from the
final candidate ledger. The v3 prompt states the null format rule; its first
25 rerun yielded 21 schema-valid category candidates, four nulls, and zero
format errors. This was an unlabeled schema repair informed by selected audit
inputs, so the Stage 6 path is not a fully untouched holdout. No correctness
labels were inspected or used to tune either prompt, and v3 prompt/model
hashes must be pinned before independent labels open.

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
