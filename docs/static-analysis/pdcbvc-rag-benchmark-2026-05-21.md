# PDCBVC.CBL RAG Bundle Benchmark

This benchmark compares the preserved `knowledge-base_rag_v0` bundle with the current `knowledge-base_rag` bundle using deterministic sparse retrieval and fact-level retention checks.

## Scope

- Producer-side sparse retrieval only; no embeddings, vector database, reranker, or LLM answer grading.
- Hit criteria require expected chunk type plus required terms from the query specification.
- Fact retention compares structured chunk metadata and BM25 terms; it is stricter than file-count retention but still not a semantic proof.

## Bundle Metrics

| Metric | v0 | current |
|---|---:|---:|
| chunk_count | 545 | 732 |
| total_files | 575 | 763 |
| total_bytes | 12589514 | 13880362 |
| knowledge_base_files | 4 | 4 |
| artifact_files | 22 | 23 |

## Static Values Chunk Completeness

This row is separate from fact retention because `metadata.static_values` may be denormalized across chunk parts. A 100% set-union fact retention score does not imply every chunk part kept the same per-variable body text.

| Metric | v0 | current |
|---|---:|---:|
| chunk_count | 11 | 11 |
| chunks_with_static_values_metadata | 11 | 11 |
| unique_variables | 63 | 63 |
| metadata_variable_instances | 693 | 693 |
| min_variables_per_chunk | 63 | 63 |
| median_variables_per_chunk | 63 | 63 |
| max_variables_per_chunk | 63 | 63 |
| chunks_with_full_program_variable_set | 11 | 11 |

## Integrity

| Area | v0 files | current files | retention | byte-identical | differing files |
|---|---:|---:|---:|---|---|
| `knowledge_base` | 4 | 4 | 100.0% | False | 00_Executive_Summary.md |
| `artifacts` | 22 | 23 | 100.0% | False | analysis_health.json, analysis_self_evaluation.json, cobol_structure.json, pipeline_report.json, variable_values.json |

## Fact Retention

| Fact family | v0 facts | current facts | retained | retention | Jaccard | changed | improved |
|---|---:|---:|---:|---:|---:|---:|---:|
| `bm25_terms` | 934 | 1072 | 933 | 99.89% | 86.95% | 0 | 0 |
| `business_rules` | 0 | 155 | 0 | 100.0% | 0.0% | 0 | 0 |
| `chunk_ids` | 545 | 732 | 543 | 99.63% | 73.98% | 0 | 0 |
| `cics` | 34 | 50 | 34 | 100.0% | 68.0% | 0 | 0 |
| `copybooks` | 435 | 435 | 435 | 100.0% | 100.0% | 0 | 0 |
| `dataflow.sidecar` | 0 | 91 | 0 | 100.0% | 0.0% | 0 | 0 |
| `dataflow.variable` | 1741 | 1741 | 1741 | 100.0% | 100.0% | 0 | 0 |
| `paragraphs` | 976 | 977 | 976 | 100.0% | 99.9% | 0 | 0 |
| `path_sensitive` | 0 | 0 | 0 | 100.0% | 100.0% | 0 | 0 |
| `static_values` | 351 | 351 | 351 | 100.0% | 100.0% | 0 | 0 |

## Retrieval Summary

| Metric | v0 | current |
|---|---:|---:|
| total_query_count | 20 | 20 |
| query_count | 16 | 19 |
| skipped_query_count | 4 | 1 |
| positive_query_count | 15 | 16 |
| negative_query_count | 1 | 3 |
| hit_at_5 | 15 | 16 |
| hit_at_5_pct | 100.0 | 100.0 |
| expected_pass_at_5 | 16 | 19 |
| expected_pass_at_5_pct | 100.0 | 100.0 |
| negative_pass_at_5 | 1 | 3 |
| negative_pass_at_5_pct | 100.0 | 100.0 |
| mrr | 0.8389 | 0.8854 |
| avg_elapsed_ms | - | - |

## Category Hit@5

| Category | v0 | current |
|---|---:|---:|
| business_rule | hits 1/1 = 100.0%; passes 1/1 = 100.0%; skipped 0/1 | hits 1/1 = 100.0%; passes 1/1 = 100.0%; skipped 0/1 |
| cics_targets | hits 3/3 = 100.0%; passes 3/3 = 100.0%; skipped 0/3 | hits 3/3 = 100.0%; passes 3/3 = 100.0%; skipped 0/3 |
| controlflow | hits 1/1 = 100.0%; passes 1/1 = 100.0%; skipped 0/1 | hits 1/1 = 100.0%; passes 1/1 = 100.0%; skipped 0/1 |
| copybooks | hits 1/1 = 100.0%; passes 1/1 = 100.0%; skipped 0/1 | hits 1/1 = 100.0%; passes 1/1 = 100.0%; skipped 0/1 |
| error_path | hits 1/1 = 100.0%; passes 1/1 = 100.0%; skipped 0/1 | hits 1/1 = 100.0%; passes 1/1 = 100.0%; skipped 0/1 |
| external_calls | hits 1/1 = 100.0%; passes 1/1 = 100.0%; skipped 0/1 | hits 1/1 = 100.0%; passes 1/1 = 100.0%; skipped 0/1 |
| negative_canary | hits 0/0 = 100.0%; passes 1/1 = 100.0%; skipped 0/1 | hits 0/0 = 100.0%; passes 1/1 = 100.0%; skipped 0/1 |
| paragraphs | hits 2/2 = 100.0%; passes 2/2 = 100.0%; skipped 0/2 | hits 2/2 = 100.0%; passes 2/2 = 100.0%; skipped 0/2 |
| screen_flow | hits 2/2 = 100.0%; passes 2/2 = 100.0%; skipped 0/2 | hits 2/2 = 100.0%; passes 2/2 = 100.0%; skipped 0/2 |
| static_analysis | hits 0/0 = 100.0%; passes 0/0 = 100.0%; skipped 2/2 | hits 1/1 = 100.0%; passes 1/1 = 100.0%; skipped 1/2 |
| static_analysis_negative | hits 0/0 = 100.0%; passes 0/0 = 100.0%; skipped 2/2 | hits 0/0 = 100.0%; passes 2/2 = 100.0%; skipped 0/2 |
| variables | hits 2/2 = 100.0%; passes 2/2 = 100.0%; skipped 0/2 | hits 2/2 = 100.0%; passes 2/2 = 100.0%; skipped 0/2 |
| workflow | hits 1/1 = 100.0%; passes 1/1 = 100.0%; skipped 0/1 | hits 1/1 = 100.0%; passes 1/1 = 100.0%; skipped 0/1 |

## Per-Query Results

| Query | Category | Expected hit | v0 rank | current rank | v0 status | current status | current top-1 |
|---|---|---|---:|---:|---|---|---|
| `cics_map_pdcvbc1` | cics_targets | True | 3 | 3 | True | True | `paragraph_logic:PDCBVC.CBL:paragraph_logic:RECEIVE-PDCBVC1` |
| `cics_link_pd1voci` | cics_targets | True | 2 | 3 | True | True | `cics_operations:PDCBVC.CBL:cics_operations` |
| `cics_xctl_pdpred` | cics_targets | True | 1 | 1 | True | True | `paragraph_logic:PDCBVC.CBL:paragraph_logic:XCTL-MAIN` |
| `external_pd1fs00_commarea` | external_calls | True | 1 | 1 | True | True | `external_program_calls:PDCBVC.CBL:external_program_calls` |
| `variable_twcob_funzione` | variables | True | 1 | 1 | True | True | `dataflow.variable:PDCBVC.CBL:dataflow.variable:PXCSEMAF-STATUS:part:1` |
| `variable_static_prog_liv5` | variables | True | 1 | 1 | True | True | `variable_group:PDCBVC.CBL:variable_group:FILLER_2` |
| `paragraph_selection_flow` | paragraphs | True | 1 | 1 | True | True | `screen.selection:PDCBVC.CBL:screen.selection:part:2` |
| `paragraph_prep_riga` | paragraphs | True | 1 | 1 | True | True | `dataflow.variable:PDCBVC.CBL:dataflow.variable:RIGA-MAPPA:part:2` |
| `copybook_pdrtwa2_twcob_fase` | copybooks | True | 1 | 1 | True | True | `copybook_fields:PDCBVC.CBL:copybook_fields:part:23` |
| `workflow_browse_phase2` | workflow | True | 1 | 2 | True | True | `business_rule:PDCBVC.CBL:business_rule:71` |
| `error_no_selection` | error_path | True | 1 | 1 | True | True | `error_path:PDCBVC.CBL:error_path:27` |
| `business_rule_selection` | business_rule | True | 1 | 1 | True | True | `business_rule:PDCBVC.CBL:business_rule:54` |
| `controlflow_pf7_logic` | controlflow | True | 2 | 1 | True | True | `controlflow.cfg:PDCBVC.CBL:controlflow.cfg:BROWSE-FASE2` |
| `screen_pf7_pf8_dispatch` | screen_flow | True | 4 | 1 | True | True | `screen.key_dispatch:PDCBVC.CBL:screen.key_dispatch:part:1` |
| `screen_dfhpf7_dfhpf8_exact` | screen_flow | True | 1 | 1 | True | True | `controlflow.cfg:PDCBVC.CBL:controlflow.cfg:BROWSE-FASE2` |
| `static_analysis_node_scoped_constants` | static_analysis | True | miss | 1 | skipped | True | `static_value.propagation:PDCBVC.CBL:static_value.propagation:0f0eb33e-42dc-4420-9e63-84202582aa85` |
| `static_analysis_flow_sensitive_targets` | static_analysis | True | miss | miss | skipped | skipped | `:` |
| `negative_static_analysis_nonexistent_constant_pd9xxxx` | static_analysis_negative | False | miss | miss | skipped | True | `static_values:PDCBVC.CBL:static_values:part:5` |
| `negative_static_analysis_always_claim` | static_analysis_negative | False | miss | miss | skipped | True | `static_value.propagation:PDCBVC.CBL:static_value.propagation:0f0eb33e-42dc-4420-9e63-84202582aa85` |
| `negative_nonexistent_program_pd9xxxx` | negative_canary | False | miss | miss | True | True | `cics_operations:PDCBVC.CBL:cics_operations` |

## Missing Fact Samples

### `bm25_terms`

- `COMMANDS`

### `chunk_ids`

- `call_contract|PDCBVC.CBL:CALL_CONTRACT:PD1VOCI:5`
- `dataflow.variable|PDCBVC.CBL:DATAFLOW.VARIABLE:WKERR2`

## Changed Fact Samples

## Interpretation

A 100% expected-pass score means this fixed sparse query suite found no top-5 regression and the negative canary queries missed as expected. Queries gated by `requires_any_chunk_type` are skipped until the requested chunk family exists, so skipped static-analysis queries are not evidence of improvement. Fact-retention rows above show where chunk compaction changed the granularity or wording of facts.
