# Primary-market taxonomy v1

`taxonomy/v1.json` freezes the independently reviewed **16 market definitions
and source-value map** for Stage 2 label collection. Its SHA-256 is
`3f160113db54be27e59eb9b366b656154525f1f0aa6cd6abb9da29d180ca8270`.
The prior `v1-candidate` and its audit remain as historical review evidence.
Changing a category boundary or mapping requires a new taxonomy version and a
new holdout reservation. This freeze does **not** validate Product Hunt tags as
product-level gold labels or establish classifier accuracy.

The final independent semantic review removed eight more source values whose
names do not determine a unique market. Original Product Hunt tags remain
untouched. Counts are source-tag assignments, **not distinct products**.

| Unmapped source value | Assignments | Counterexample to the former class |
| --- | ---: | --- |
| `events` | 3 | Event spaces and social ticketing are not necessarily business operations. |
| `messaging` | 12 | Customer-service APIs and workplace communications are not necessarily social networking. |
| `Messaging` | 3 | Case-equivalent to broad `messaging`. |
| `Video Streaming` | 2 | DubStream provides live dubbing; Slurp downloads media. Neither implies entertainment consumption. |
| `analytics` | 11 | Uptime/developer, marketing-traffic, and learning-quiz analytics serve different markets. |
| `Analytics` | 7 | Case-equivalent to broad `analytics`. |
| `A/B testing tools` | 369 | Bucket offers feature flags and Rule Engine serves business/developer experiments, not necessarily acquisition. |
| `File storage and sharing apps` | 1,268 | Pre-release music sharing and shared vaults do not imply personal productivity. |

The final freeze check also removed ten known low-count boundary cases (18
assignments). Each source phrase names a topic, medium, or format rather than
one decisive market; the inspected examples below explain the abstention.

| Unmapped source value | Assignments | Boundary example |
| --- | ---: | --- |
| `change-management` | 1 | Ark VCS is software version control, not organizational change management. |
| `Branding`, `branding` | 1, 1 | Visual identity work overlaps broader marketing strategy. |
| `Design`, `design` | 1, 3 | Surface Studio 2+ is hardware; AI Design Training is a course; other products perform design. |
| `intimacy` | 1 | FcukLog is a private journal, not necessarily healthcare. |
| `community` | 3 | Colrnx teaches; okexpert sells advice; StackShelf is a creator marketplace. |
| `Calendar`, `calendar` | 1, 3 | Impylse handles events; AppointHub books business appointments; Planting Calendar plans gardening. |
| `text-editors` | 3 | Locker is a secure editor while TechXcelerate is a Python IDE. |

`notes` (four assignments) remains mapped to personal productivity: the source
phrase names the act of capturing individual notes, whereas a product's
additional team or document workflow must be judged from its text. This is a
semantic precedence rule, not proof that each source tag labels its product
correctly.

These 18 values account for 1,693 assignments. The checked-in full-archive
audit of the 2026-10-15 source snapshot covers 575,622 products and 544
source-category values. The frozen map covers 275 values. Among the 94,036
products with source categories, 55,984 have one source-derived candidate,
19,226 have conflicting mapped categories, and 18,826 have no mapped tag.
Relative to the preceding candidate, 635 formerly unique mappings become
null and 646 conflicts become unique, a net unique coverage change of +11.
Coverage is not precision.

The unchanged, deliberately selected 109-product taxonomy-tuning set has 100
clear independent judgments and nine held ambiguous. On this frozen map, 64
clear choices agree with the source-derived candidate, 19 disagree, and 17
abstain. This is a diagnostic, **not a population estimate**. For a separate
deterministic transition check, rank the 646 new conflict-to-unique slugs by
SHA-256 of `stage1-freeze-transition:<slug>` and inspect the first 16 using
product text: ten are plausible, four clearly wrong (`Lodelian`→business,
`WebShopQa`→social, `PaperPlane`→design, `Second Brain`→business), and two
insufficient-text cases (`Hive`, `Lockboxy`). Source-derived labels remain
untrusted for training.

The ignored local `data/primary-label-v1-frozen-2026-10-16-r3/` bundle was
reserved under this exact taxonomy hash and source CSV SHA-256
`ade78b1994fc60d323e098c059e340270e81f369cc87cc06465af7a60e011dae`.
It excludes all 109 prior tuning slugs, all 1,221 pre-freeze candidate-bundle
slugs, and all 2,440 slugs from two superseded freeze drafts (3,770
distinct), then reserves 680 development, 200 random holdout, and 340
source-stratified holdout records. Blind files contain only product
text; original tags and strata stay in the ignored source key. Source strata
are **not true-label strata**. After the exclusions, `home_lifestyle` has zero
source-stratum records in development and the stratified holdout. All 1,220
annotations are unreviewed, so the training and evaluation gates are closed.
Stage 2 needs independent product-text discovery and resampling for home and
any other class without sufficient true-label support; weak source tags must
not be forced into gold. Stages 4–7 remain dependent work in issue #17.

## Supplemental home/lifestyle discovery

The frozen source map leaves no `home_lifestyle` records in the label bundle's
development or source-stratified holdout. `tools/primary_home_discovery.py`
reserves a separate, ignored product-text discovery bundle using four fixed
name/tagline query groups: living space, home improvement, food/gardening,
and family life. It reads no original source categories, exposes only product
text in blind files, and seals slugs and query groups in its local key. The
selection is deterministic by seed and refuses to overwrite a prior bundle.

The 2026-10-16 reservation is in ignored
`data/primary-home-discovery-v1-2026-10-16/`. It excludes all 4,990 earlier
review/sample slugs, then selects 40 development and 20 heldout candidates per
query group: 160 development, 80 heldout, all disjoint from the main frozen
bundle. The four post-exclusion candidate pools contain 350, 553, 1,472, and
441 products respectively. Its manifest records the frozen taxonomy/source
hashes, seed, exact queries, exclusions, selection counts, and file hashes.
The key contains **no source tags**. Its 240 annotations are unreviewed.
Query matches are candidate discovery, not true home labels, class support,
or population prevalence; the heldout records must stay sealed during model
work and cannot replace the original random holdout. An independent reviewer
must assign product-text labels before any of these records can support Stage 2.

To reproduce it against the ignored verified `data/products.csv` archive,
use a new empty output directory with the same seed and exclusions:

```bash
uv run python tools/primary_home_discovery.py \
  --taxonomy taxonomy/v1.json --products data/products.csv \
  --exclude-key data/taxonomy-review-v1/source-key.json \
  --exclude-key data/primary-label-v1-2026-10-16/source-key.json \
  --exclude-key data/primary-label-v1-frozen-2026-10-16/source-key.json \
  --exclude-key data/primary-label-v1-frozen-2026-10-16-r2/source-key.json \
  --exclude-key data/primary-label-v1-frozen-2026-10-16-r3/source-key.json \
  --output-dir data/primary-home-discovery-v1-2026-10-16 \
  --seed primary-home-discovery-v1-2026-10-16
```
