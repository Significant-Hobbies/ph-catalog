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
candidate maps 340 values. The matching checked-in audit finds 94,036 products
with source categories: 54,880 have one source-derived candidate, 24,037 have
conflicting mapped categories, and 15,119 have no mapped category. These are
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

For independent product-text review, choose the dominant user workflow over
the domain, technology, delivery format, or secondary use. A real-estate
product belongs to `home_lifestyle` only when it helps someone find, care for,
plan, or improve a living space; property financing belongs to `finance`,
lead acquisition to `marketing_sales`, building analysis to `data_analytics`,
and property-business administration to `business_operations`. Acquisition-
specific campaign/advertising measurement belongs to `marketing_sales`;
general BI, research, and measurement belong to `data_analytics`. Marketing
copy belongs to `marketing_sales`, general public publishing to
`media_entertainment`, and private writing/editing to
`personal_productivity`. Workplace/customer operational communication belongs
to `business_operations`; general interpersonal networks and peer communities
belong to `social_community`. Finance-specific wage/payment/tax money flows
belong to `finance`; general staff and workflow administration belongs to
`business_operations`. Return null when the text does not resolve a dominant
workflow or the two uses are genuinely co-primary. These are review rules;
`primary_from_sources` still only maps original tags and does not inspect
product text.

Regenerate the review report from the ignored local archive:

```bash
uv run python tools/audit_primary_taxonomy.py \
  --taxonomy taxonomy/v1-candidate.json \
  --products data/products.csv \
  --output data/taxonomy-v1-candidate-report.json
```

The checked-in `primary-taxonomy-v1-candidate-audit.json` was regenerated from
the source archive above after the mapping review; its taxonomy SHA-256 matches
the candidate file. Generated product datasets stay in ignored `data/`. An
independent review of the category boundaries and remaining low-support source
values is still required before freezing `v1`. Product-level adjudication and
precision evidence are a separate gate before training or promoting labels.

## Product-text review before training

The source archive is not a product-level gold standard. A deterministic
64-product challenge found tags that clearly named the wrong market, including
a Mac battery utility tagged `Apps for kids`. A subsequent class-stratified
diagnostic found a scraping proxy tagged `Maps and GPS`. In the same archive,
148 of the 340 mapped source values occur on ten or fewer products. These
low-support mappings especially need direct product-text review.

For a **new** blinded diagnostic set from the verified `products.csv` (SHA-256
`ade78b1994fc60d323e098c059e340270e81f369cc87cc06465af7a60e011dae`),
use a new local output directory:

```bash
uv run python tools/sample_primary_taxonomy_review.py \
  --taxonomy taxonomy/v1-candidate.json \
  --products data/products.csv \
  --output-dir data/taxonomy-review-v1-after-unmapping
```

The default seed `taxonomy-review-v1-2026-10-16` requests up to five uniquely
mapped products per class and two products from source values with at most ten
assignments per class. The preserved 109-product review set was generated from
the **preceding** candidate (SHA-256
`d826b410a7143c1579f51ddfe27b7dceec9e6488fd8ade1197ea4382c8a0c5bd`)
and is kept unchanged in ignored `data/taxonomy-review-v1/` for comparison.
Annotators read `blind-review.json` first and choose a primary market from the
taxonomy boundaries or null, citing product-text evidence. `source-key.json`
keeps the original tags, proposed source mapping, and sample strata separate
until judgments are recorded. `manifest.json` records the seed and both source
hashes. All three generated files remain ignored in local `data/`, outside Git.
The generator refuses to overwrite existing review files so recorded judgments
are not lost.

An independent reviewer first labeled 24 clear records without the source key;
those 24 were then compared with the key. The reviewer next judged the
remaining 85 blind records before their key entries were compared. Across the
109 records, the reviewer selected 100 clear cases and held nine ambiguous
cases. Of the 100 clear choices, 72 agreed with the preceding source-derived
category and 28 disagreed. The sample deliberately balances classes and rare
source values, and the clear cases are selected after seeing product text:
**72/100 is not population precision**. The ignored local review folder
retains all verdicts and a joined diagnostic report. These are tuning
diagnostics, not held-out validation.

The review and a separate scan of source-category examples found 33 values
whose names describe a format, audience, subject, or cross-market workflow
rather than one primary market. The current candidate leaves them unmapped.
The assignment counts below count source tags, not distinct products; a
product may carry several tags.

| Removed source value | Assignments | Why it cannot set one primary market |
| --- | ---: | --- |
| `Marketplace sites` | 1,437 | WayUp is jobs; BeatStars is music; Filter Plus is an ecommerce plugin. |
| `Apps for kids` | 706 | MathMaze is a game; Doll Feeding is a toy; Earlybean is finance/learning. |
| `Real estate` | 492 | ChatRealtor sells leads; PEAK measures buildings; Safely Finance funds renters. |
| `Time tracking apps` | 1,205 | SleepCycler is health; Timeneye manages team work; Pomodify is personal focus. |
| `Furniture` | 190 | Al Sultan Furnishings is a bed retailer, not a home/lifestyle workflow. |
| `Writing assistants` | 2,466 | CopyPartner creates marketing blogs; DiagramMatic creates diagrams. |
| `Legal services` | 582 | Immplify serves immigrants; Lexi manages legal teams; WPsigner signs documents. |
| `Music` | 10 | Nada creates music, while music consumption belongs to media. |
| `Meetings` | 2 | Effects SDK is developer infrastructure for calls. |
| `Writing` | 6 | Contenfy is an SEO content service. |
| `Education` | 8 | Reactor Atlas is a research/map dataset with an educational use. |
| `sales` | 9 | An inventory/POS app is business operations despite a sales tag. |
| `advertising` | 5 | A step-by-step publishing guide teaches advertising instead of running ads. |
| `delivery` | 1 | CargoLab plans freight loads rather than retail shopping. |
| `books` | 2 | A reading journal and a storytelling app have different workflows. |
| `cookbooks` | 1 | Recipe Witch organizes recipes for a food community. |
| `Art` | 1 | CloakMan NFT spans art generation and collectible commerce. |
| `art` | 2 | Case-equivalent to broad `Art`. |
| `education` | 31 | Case-equivalent to broad `Education`. |
| `meetings` | 1 | Case-equivalent to broad `Meetings`. |
| `music` | 6 | Case-equivalent to broad `Music`. |
| `writing` | 9 | Case-equivalent to broad `Writing`. |
| `Advertising` | 1 | Case-equivalent to broad `advertising`. |
| `Sales` | 5 | Case-equivalent to broad `sales`. |
| `legal` | 4 | Broad alias of `Legal services`; not specifically organization operations. |
| `time-tracking` | 3 | Broad alias of `Time tracking apps`; purpose spans health, teams, and personal focus. |
| `Payroll software` | 130 | Frappe HR and Zenefits focus on staff operations; digital-wallet and PCB Calculator handle money or tax flows. |
| `Blogging platforms` | 878 | Platen.ai writes marketing copy rather than general published media. |
| `CRM software` | 1,204 | 1stContact.ai sells through CRM; 2meters.app manages visitor flow. |
| `crm` | 2 | Case-equivalent to broad `CRM software`. |
| `Shopify Apps` | 557 | Admetrics Data Studio measures ad performance; Age Guard verifies age; the host platform does not define retail workflow. |
| `Twitter apps` | 251 | Anewstip finds journalists; #AmazonCart supports shopping; the host platform does not define social workflow. |
| `NFT creation tools` | 164 | avamaker creates avatars; 3mint mints and sells collectibles; creation does not define a finance workflow. |

The 33 values account for 10,371 source-tag assignments in the archive. This
is **not** the number of newly unlabeled products: another mapped tag may
still classify the same product. Relative to the preceding candidate, 3,256
previously unique mappings became null, while 3,503 conflicting mappings
became unique after removal of a competing broad tag; 71 conflicts became
unmapped. The net unique count rose by 247. `home_lifestyle` now has only four
uniquely source-mapped products, down from 284. It is not a trainable class
from source tags alone and needs separately adjudicated product labels or a
taxonomy revision before Stage 2. Specific source values such as `Payment
processors` and `Professional networking platforms` remain mapped despite
individual product-level mistags; those need label cleaning rather than a
wrong semantic unmap. The taxonomy stays `v1-candidate` and unfrozen.

Against the same 100 clear blind choices, the revised candidate agrees on 68,
disagrees on 19, and abstains on 13; nine of those abstentions remove a former
disagreement and four remove a former agreement. This selected set is still
not an accuracy estimate. The 3,503 conflict-to-unique transitions also need
review before any training use: a deterministic 16-record spot check against
this final candidate (lowest SHA-256 of `transition-review-v1:<slug>`) found
clear remaining wrong labels. For example, `Scriboryx` transcribes interviews
and meetings but becomes developer tools from `LLM Developer Tools`; `Rkiez`
is a study/work productivity timer but becomes health/wellness from `Mental
Health`; and `Safes` provides digital parental controls but becomes
health/wellness from `Family Care`. The transition cohort is **not** clean training data merely
because a broad competing tag was unmapped.

The map cannot yet be frozen as a semantic ontology solely on these product
label diagnostics. Remaining mapped source names still need boundary review:
`Maps and GPS` (613 assignments) can mean travel navigation or a
geospatial/data tool; `Spreadsheets` (459) can serve personal planning or BI;
`Video and Voice calling` (512) can be social communication or team operations;
`Messaging apps` (1,322) spans personal messaging, privacy tools, and
messaging APIs; and `Community management` (1,496) spans peer interaction and
household/organizational chores. `Payroll software` (130) was removed because
it spans staff administration and finance-specific money flow. `Music
Generation` remains mapped to design/creative; that boundary now explicitly
includes creative audio production as well as visual production. The 148 mapped
values with at most ten assignments also need a recorded independent semantic
pass. This is distinct
from product-level label cleaning: a well-mapped tag may still be attached to
the wrong product.

This is a taxonomy-tuning set, **not** a classifier validation set. It cannot
establish population precision. After adjudicating it and documenting any
mapping changes, reserve a fresh random and stratified sample for Stage 2 and
another independent sample for Stage 7 promotion. The taxonomy remains
unfrozen until those gates are met.
