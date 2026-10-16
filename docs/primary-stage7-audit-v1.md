# Primary category Stage 7 audit, v1

The frozen candidate **fails the pre-registered publication gate**. In the
deterministic random sample of 200 eligible archived-mart products, it emitted
153 categories, 126 of which matched an independently adjudicated unique
primary label. Coverage was **76.5%**; precision among emitted categories was
**82.35%** (95% Wilson interval **75.54–87.58%**). The rule required at least
50% coverage **and a 90% Wilson lower bound**. No category or path is approved
for publication, and no model, threshold, or prompt has been tuned on these
labels. [The pipeline plan](analytics-pipeline-plan.md) holds the protocol and
pre-registered decision rules; [issue #17](https://github.com/Significant-Hobbies/ph-catalog/issues/17)
remains open for acceptance review.

| Audit slice | Accepted / eligible | Exact unique-primary matches / accepted | Precision | 95% Wilson lower bound |
| --- | ---: | ---: | ---: | ---: |
| Random, all paths | 153 / 200 | 126 / 153 | 82.35% | 75.54% |
| Random, Stage 4 source text only | 61 / 61 | 51 / 61 | 83.61% | 72.39% |
| Random, Stage 6 LLM final | 92 / 139 | 75 / 92 | 81.52% | 72.39% |
| Random, LLM after website attempt (subgroup) | 81 / 120 | 64 / 81 | 79.01% | 68.93% |
| Separate model-stratified diagnostic | 112 / 120 | 83 / 112 | 74.11% | 65.29% |

The LLM-after-website row is **inside**, not in addition to, the LLM row.
“Website attempt” includes fetch denials and no-metadata outcomes. Stage 5
produces evidence, not a category, so website-only accepted **0 / 120** random
website routes. The 120 model-stratified records were selected by predicted
category/confidence/path; their 74.11% is an error diagnostic, **not** a
population estimate or a basis for per-category claims.

Among the random 200, 30 Stage 6 outcomes failed closed on citation validation
and 17 were explicit nulls, leaving 47 uncovered. Of 27 wrong accepted
categories, 19 disagreed with a unique-primary gold category, five were
emitted on gold-null products, and three on gold co-primary products. The
source-only path contributed 10 wrong categories; the LLM path 17. All 16
classes had fewer than 30 true single-primary records in the random sample
(maximum 24), so none meets the pre-registered class-specific support gate.
The complete confusion matrix and per-class support remain in the ignored
`score-v1.json`; these counts do not justify choosing a new threshold from
this audit.

Independent labelers saw only 320 product-text records and frozen category
definitions. The first pass yielded 287 single, four co-primary, and 29
null labels. A second reviewer labeled the 32 IDs selected by the fixed
`stage7-qa-v1:<review_id>` hash rule: 29 category agreements and three
disagreements. A blind third reviewer agreed with the second on all three;
those three decisions and evidence spans replaced the first pass before any
prediction join. The final labels comprise 286 single, four co-primary, and
30 null. All 320 final rows passed ID, schema, category, and exact
product-text evidence checks. The scorer reproduced the saved JSON exactly.

The first 25 selected audit inputs exposed a null-output schema defect in the
Stage 6 v2 prompt **before gold labels opened**. Its failed output is retained
but excluded; the v3 prompt repaired the null format and was frozen before
annotation. Thus the LLM path is **not a pristine untouched holdout**, even
though no correctness label informed the repair. The 33 citation failures
among the 165 v3 Stage 6 outputs remained fail-closed; this audit did not
retry or change the prompt after seeing gold.

Generated data and label files stay ignored under
`data/primary-final-audit-v1-2026-10-16/`. The immutable inputs and results
are identified by SHA-256:

| Artifact | SHA-256 |
| --- | --- |
| Audit reservation manifest | `f8c3fc478236acd898a9929063fb56af4d108c036a98e1de1a5a2c277870479d` |
| Blind text | `f4eb461c92dd4dede831646a72986d7387830ca01c5da03d29735ff6df5843e4` |
| Frozen candidate ledger | `d2ed7b26c778f8efb561eac7e5f2d3fdbe7d6c995f3b2fc27f2e420027a1f17a` |
| Candidate ledger manifest | `ad383ac4ca894aed57512c592c4dd51600d5544feebe4e749d894f4c57b8d3f9` |
| Primary / second / third annotation passes | `8e284c6caae8c9f650346863e7baf8e4e319832cf32149e13e12f233ce64e0f0` / `7e614272f520ba4e3895cbee88962dc0f1514721ac3dd64641662741ff8be43a` / `0a10ae599d552b014cf0af629ac9b451c0bc0bcd2332b6df45fa8e79e926ef0c` |
| Adjudication log / final gold | `d9e96686efc12135c473e1dea5ede119f1d9486c8f806125df34d5b743b39ad6` / `42052234c74b37f84f4ecae770fde9cc34a4dd326b12c7406fabb745b8507d5d` |
| Frozen score / local evidence manifest | `db5a116d08b264d204c5a7a010530d818cd8f0acfe1068f7c8a4586e2ca6feec` / `79dae1d569f073552b9f6f6a0b466eb109a4caa6a446060f28091165a46cb148` |

This is one bounded audit of the frozen candidate on the eligible archived
mart, with the random 200 kept separate from biased diagnostics. It does not
establish correctness across the full source archive or qualify any future
model version. Further acceptance decisions belong to #17; these gold labels
must not be reused to tune and then validate the same candidate.
