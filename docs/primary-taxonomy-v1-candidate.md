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
candidate maps 293 values. The matching checked-in audit finds 94,036 products
with source categories: 55,973 have one source-derived candidate, 19,872 have
conflicting mapped categories, and 18,191 have no mapped category. These are
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
120 of the 293 mapped source values occur on ten or fewer products. These
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

The first product-text review and a separate scan of source-category examples found 33 values
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

The first 33 values account for 10,371 source-tag assignments in the archive. This
is **not** the number of newly unlabeled products: another mapped tag may
still classify the same product. In that first pass, 3,256
previously unique mappings became null, while 3,503 conflicting mappings
became unique after removal of a competing broad tag; 71 conflicts became
unmapped. The net unique count rose by 247. `home_lifestyle` then had only four
uniquely source-mapped products, down from 284. It is not a trainable class
from source tags alone and needs separately adjudicated product labels or a
taxonomy revision before Stage 2. Specific source values such as `Payment
processors` and `Professional networking platforms` remain mapped despite
individual product-level mistags; those need label cleaning rather than a
wrong semantic unmap. The taxonomy stays `v1-candidate` and unfrozen.

Against the same 100 clear blind choices, that first-pass candidate agrees on 68,
disagrees on 19, and abstains on 13; nine of those abstentions remove a former
disagreement and four remove a former agreement. This selected set is still
not an accuracy estimate. The 3,503 conflict-to-unique transitions also need
review before any training use: a deterministic 16-record spot check against
that first-pass candidate (lowest SHA-256 of `transition-review-v1:<slug>`) found
clear remaining wrong labels. For example, `Scriboryx` transcribes interviews
and meetings but becomes developer tools from `LLM Developer Tools`; `Rkiez`
is a study/work productivity timer but becomes health/wellness from `Mental
Health`; and `Safes` provides digital parental controls but becomes
health/wellness from `Family Care`. The transition cohort is **not** clean training data merely
because a broad competing tag was unmapped.

## Independent semantic follow-up

A separate read-only reviewer examined the remaining mapped source names
against original product text without opening the preserved blind-review key.
The 28 values below name a subject, medium, host, or workflow spanning markets;
the source value alone cannot assign a primary category. Original tags remain
in the archive. Counts are source-tag assignments, not distinct products.

| Unmapped source value | Assignments | Boundary evidence |
| --- | ---: | --- |
| `Maps and GPS` | 613 | Travel navigation and geospatial/dispatch tools have different workflows. |
| `Spreadsheets` | 459 | Row Zero is team BI; spreadsheets also serve personal planning. |
| `spreadsheets` | 1 | Case-equivalent to broad `Spreadsheets`. |
| `Video and Voice calling` | 512 | Calls can be interpersonal, workplace, customer support, or an API. |
| `Messaging apps` | 1,322 | Messaging spans personal chat, business operations, and developer APIs. |
| `Community management` | 1,496 | Newsepick supports peer learning; other products manage customers or organizations. |
| `bitcoin` | 1 | Bitcoin Deaths is a visualization/media product, not money management. |
| `ethereum` | 1 | A Web3 events catalog does not itself provide finance. |
| `Crypto`, `crypto` | 1, 4 | Dexzbitz is an exchange; Signet is a wallet API. |
| `photo-video` | 2 | BOOKD is a location marketplace; Diloo creates photos. |
| `audio` | 7 | Eadlyn creates voices; Pocket Coach keeps notes; Podttr transcribes. |
| `Funny`, `funny` | 3, 3 | Tone does not imply entertainment; Netra is a Mac focus utility. |
| `global-nomad`, `Global Nomad` | 3, 1 | REMOTE is news; Finance Jobs lists jobs; FreshRemote reports salaries. |
| `outdoors` | 1 | PermitPal handles permits; outdoors is a subject, not a workflow. |
| `maps`, `gps` | 1, 1 | Rightroute routes property viewings; Asterism manages fleets. |
| `Freelance`, `freelance` | 2, 3 | Bedrok lists work; Quillbill handles invoicing. |
| `couples` | 2 | TMap tracks people; Wings is a relationship journal. |
| `kids-parenting` | 1 | FableSprout is a storytelling product. |
| `quantified-self` | 2 | Hooplog records NBA game activity, not health. |
| `Home`, `home` | 1, 7 | Interior planning and property job/permit workflows share the subject. |
| `fashion` | 3 | Parivesh is a shop; StrikkeTavla organizes knitting recipes. |
| `Jewelry` | 1 | A commodity noun spans retail and creation/design. |

This pass removes 4,454 source-tag assignments from deterministic mapping.
Relative to the first-pass candidate, 915 formerly unique products become
unlabeled, 1,410 conflicting products become unique after a competing broad
tag is removed, and 10 conflicts become unlabeled. Unique source-derived
coverage rises by 495, from 54,880 to 55,375; this is **not a precision gain**.
`home_lifestyle` now has only two uniquely source-mapped products. The same
100 selected clear blind judgments give 67 agreements, 19 disagreements,
14 abstentions, and nine held ambiguous records. This remains a tuning
diagnostic, not population accuracy. A deterministic 16-record spot check of
the 1,410 new conflict-to-unique cases (lowest SHA-256 of
`semantic-review-v2:<slug>`) found six clear wrong labels, four ambiguous or
co-primary cases, and six plausible matches. MirrorFly CPaaS becomes
media/entertainment from `Live streaming platforms` despite being an API;
corpX becomes developer tools from `Cloud Computing Platforms` despite being
professional networking. This selected transition sample is diagnostic, not
population precision. Source tags need product-level cleaning.

The work/careers boundary now excludes skills training, matching the existing
`Sales training` education mapping. `Music Generation` remains mapped to
design/creative, whose boundary includes audio creative production. This
semantic pass did not freeze the ontology: 125 low-support mapped values and
other boundary cases remained to review. Product-level label cleaning and a
fresh independent gold sample are separate gates before training.

## Broader workflow review

A second independent read-only source-map review found 19 more labels whose
meanings span product markets. The candidate now leaves these source values
unmapped; their original tags remain in the archive. Counts are assignments,
not distinct products. The examples show why the tag alone cannot determine
the dominant workflow, regardless of the quality of any individual tag.

| Unmapped source value | Assignments | Counterexample to the old mapping |
| --- | ---: | --- |
| `Scheduling software` | 1,386 | Neou supports personal ADHD focus, outside business operations. |
| `Meeting software` | 749 | Get-Offer.me supports job seeking, outside business operations. |
| `Survey and form builders` | 524 | Waitly uses forms for customer acquisition, outside business operations. |
| `Family Care` | 432 | Giftron supports gift shopping and Heart-Venture is a relationship journal, outside medical care. |
| `Video conferencing` | 274 | Amazon Chime supports workplace meetings, outside interpersonal social networking. |
| `Live streaming platforms` | 418 | Ebay Live supports commerce and MirrorFly provides communications infrastructure. |
| `Virtual events` | 270 | TFH covers competitive sport and Guide covers candidate interviews. |
| `Event software` | 564 | Curated Festivals '26 helps discover travel and entertainment. |
| `Fundraising resources` | 586 | High Output Founders' Library is educational content; Launching Next publishes startup news. |
| `Website analytics` | 721 | Seodar measures SEO and Stanza Systems monitors developer reliability. |
| `Screenshots and screen recording apps` | 596 | Vidyard serves sales and BrandBird serves marketing design. |
| `Browser Automation` | 151 | Calyro automates Instagram DMs, outside developer tooling. |
| `Digital whiteboards` | 249 | ALLO serves team work and GaleristA plans a home layout. |
| `Transcription` | 205 | Callvix serves business communications; Voxy is a voice agent. |
| `task-management` | 8 | Ariso serves a team; the tag need not imply personal productivity. |
| `Task Management` | 3 | Case-equivalent to `task-management`; Tweek is a personal calendar. |
| `Customer Success` | 1 | WorkHub Connect provides workplace conferencing, not evidence of customer support or retention. |
| `customer-success` | 1 | LiveFox supports team engagement and education; the phrase spans support operations and lifecycle retention. |
| `customer-communication` | 3 | AppointHub handles appointments; Oystro handles meetings; Media Jobs lists work. The tag does not distinguish support from promotion. |

These removals affect 7,141 source-tag assignments. `Customer loyalty
platforms` moves from `business_operations` to `marketing_sales` (405
assignments) because retention is a marketing lifecycle workflow, illustrated
by Browse Booster. The category boundaries now explicitly distinguish
customer retention from general operations and medical caregiving from
everyday family-life planning.

Relative to the preceding candidate, 2,030 formerly unique source mappings
become null, 2,650 conflicts become unique, 117 conflicts become null, and
22 formerly unique mappings become conflicts. Unique source-derived coverage
rises by 598. Among the same 100 deliberately selected clear blind choices,
65 now agree, 19 disagree, and 16 abstain; nine other cases remain held
ambiguous. This is a tuning diagnostic, **not population precision**.
The current map still has 120 values with at most ten source assignments and
only two uniquely source-mapped `home_lifestyle` products. Source-derived
coverage cannot satisfy the Stage 2 product-label and class-support gates.
For a deterministic transition check, rank the 2,650 new conflict-to-unique
slugs by SHA-256 of `stage1-review-v3:<slug>` and inspect the first 16 against
name, tagline, and description. Eleven are plausible matches, two are clearly
wrong (`LawnManage` becomes finance despite being landscaping-business
software; `Hustle X` becomes social/community despite being advice videos),
and three have insufficient or co-primary evidence (`Ramen`, `Emstrata`,
`Paperglide`). Another newly unique case, `Oystro`, becomes social/community
from a generic messaging tag despite scheduling workplace meetings. This is a
targeted diagnostic, not a population estimate or
training-label validation. The ontology and source map remain `v1-candidate`;
independent product-level adjudication, including sparse classes, is still
required before any classifier training or promotion.

This is a taxonomy-tuning set, **not** a classifier validation set. It cannot
establish population precision. After adjudicating it and documenting any
mapping changes, reserve a fresh random and stratified sample for Stage 2 and
another independent sample for Stage 7 promotion. The taxonomy remains
unfrozen until those gates are met.
