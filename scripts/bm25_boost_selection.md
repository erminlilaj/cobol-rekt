# BM25 Label Boost Selection

Selected boost: `1.0`.

Candidate values considered for Stage 3: `1.0`, `1.5`, `2.0`.

The branch does not yet have the D7 evaluator harness, so Stage 3 uses the conservative value `1.0`: it emits paragraph labels into `structured_term_weights` without changing `term_freq`, `structured_terms`, or the relative scoring of existing structured terms. This preserves current recall behavior while making the weighted field available for downstream retrievers and the D7 benchmark sweep.

Selection rationale:

| boost | recall risk | selected |
|---:|---|---|
| 1.0 | Lowest risk; additive metadata only, no score amplification over the compatibility `structured_terms` field. | yes |
| 1.5 | Reasonable candidate for D7 measurement, but not selected without evaluator numbers. | no |
| 2.0 | Stronger paragraph-label bias; deferred until D7 can prove no top-3 recall regression. | no |

The D7 benchmark harness records the final default-vs-facts-only numbers and can be used to revisit this value with measured top-3 recall.
