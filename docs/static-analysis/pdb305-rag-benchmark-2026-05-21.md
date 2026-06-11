# PDB305.CBL RAG Bundle Benchmark

This benchmark compares the preserved `knowledge-base_rag_v0` bundle with the current `knowledge-base_rag` bundle using deterministic sparse retrieval and fact-level retention checks.

## Scope

- Producer-side sparse retrieval only; no embeddings, vector database, reranker, or LLM answer grading.
- Hit criteria require expected chunk type plus required terms from the query specification.
- Fact retention compares structured chunk metadata and BM25 terms; it is stricter than file-count retention but still not a semantic proof.

## Bundle Metrics

| Metric | v0 | current |
|---|---:|---:|
| chunk_count | 393 | 471 |
| total_files | 423 | 502 |
| total_bytes | 12559259 | 13154730 |
| knowledge_base_files | 4 | 4 |
| artifact_files | 22 | 23 |

## Static Values Chunk Completeness

This row is separate from fact retention because `metadata.static_values` may be denormalized across chunk parts. A 100% set-union fact retention score does not imply every chunk part kept the same per-variable body text.

| Metric | v0 | current |
|---|---:|---:|
| chunk_count | 8 | 8 |
| chunks_with_static_values_metadata | 8 | 8 |
| unique_variables | 56 | 56 |
| metadata_variable_instances | 448 | 448 |
| min_variables_per_chunk | 56 | 56 |
| median_variables_per_chunk | 56.0 | 56.0 |
| max_variables_per_chunk | 56 | 56 |
| chunks_with_full_program_variable_set | 8 | 8 |

## Integrity

| Area | v0 files | current files | retention | byte-identical | differing files |
|---|---:|---:|---:|---|---|
| `knowledge_base` | 4 | 4 | 100.0% | False | 00_Executive_Summary.md, 02_Data_Dictionary.md, 03_Dependencies.yaml |
| `artifacts` | 22 | 23 | 100.0% | False | analysis_health.json, analysis_self_evaluation.json, cobol_structure.json, pipeline_report.json, variable_values.json |

## Fact Retention

| Fact family | v0 facts | current facts | retained | retention | Jaccard | changed | improved |
|---|---:|---:|---:|---:|---:|---:|---:|
| `bm25_terms` | 874 | 965 | 873 | 99.89% | 90.37% | 0 | 0 |
| `business_rules` | 0 | 65 | 0 | 100.0% | 0.0% | 0 | 0 |
| `chunk_ids` | 393 | 471 | 388 | 98.73% | 81.51% | 0 | 0 |
| `cics` | 50 | 78 | 50 | 100.0% | 64.1% | 1 | 1 |
| `copybooks` | 497 | 497 | 497 | 100.0% | 100.0% | 0 | 0 |
| `dataflow.sidecar` | 0 | 41 | 0 | 100.0% | 0.0% | 0 | 0 |
| `dataflow.variable` | 1078 | 1078 | 1078 | 100.0% | 100.0% | 0 | 0 |
| `paragraphs` | 760 | 762 | 760 | 100.0% | 99.74% | 0 | 0 |
| `path_sensitive` | 0 | 0 | 0 | 100.0% | 100.0% | 0 | 0 |
| `static_values` | 266 | 266 | 266 | 100.0% | 100.0% | 0 | 0 |

## Retrieval Summary

| Metric | v0 | current |
|---|---:|---:|
| total_query_count | 21 | 21 |
| query_count | 17 | 20 |
| skipped_query_count | 4 | 1 |
| positive_query_count | 16 | 17 |
| negative_query_count | 1 | 3 |
| hit_at_5 | 15 | 17 |
| hit_at_5_pct | 93.75 | 100.0 |
| expected_pass_at_5 | 16 | 20 |
| expected_pass_at_5_pct | 94.12 | 100.0 |
| negative_pass_at_5 | 1 | 3 |
| negative_pass_at_5_pct | 100.0 | 100.0 |
| mrr | 0.7778 | 0.8627 |
| avg_elapsed_ms | - | - |

## Category Hit@5

| Category | v0 | current |
|---|---:|---:|
| business_rule | hits 1/1 = 100.0%; passes 1/1 = 100.0%; skipped 0/1 | hits 1/1 = 100.0%; passes 1/1 = 100.0%; skipped 0/1 |
| cics_targets | hits 4/4 = 100.0%; passes 4/4 = 100.0%; skipped 0/4 | hits 4/4 = 100.0%; passes 4/4 = 100.0%; skipped 0/4 |
| controlflow | hits 1/1 = 100.0%; passes 1/1 = 100.0%; skipped 0/1 | hits 1/1 = 100.0%; passes 1/1 = 100.0%; skipped 0/1 |
| copybooks | hits 1/1 = 100.0%; passes 1/1 = 100.0%; skipped 0/1 | hits 1/1 = 100.0%; passes 1/1 = 100.0%; skipped 0/1 |
| error_path | hits 1/1 = 100.0%; passes 1/1 = 100.0%; skipped 0/1 | hits 1/1 = 100.0%; passes 1/1 = 100.0%; skipped 0/1 |
| external_calls | hits 1/1 = 100.0%; passes 1/1 = 100.0%; skipped 0/1 | hits 1/1 = 100.0%; passes 1/1 = 100.0%; skipped 0/1 |
| negative_canary | hits 0/0 = 100.0%; passes 1/1 = 100.0%; skipped 0/1 | hits 0/0 = 100.0%; passes 1/1 = 100.0%; skipped 0/1 |
| paragraphs | hits 2/2 = 100.0%; passes 2/2 = 100.0%; skipped 0/2 | hits 2/2 = 100.0%; passes 2/2 = 100.0%; skipped 0/2 |
| screen_flow | hits 1/2 = 50.0%; passes 1/2 = 50.0%; skipped 0/2 | hits 2/2 = 100.0%; passes 2/2 = 100.0%; skipped 0/2 |
| static_analysis | hits 0/0 = 100.0%; passes 0/0 = 100.0%; skipped 2/2 | hits 1/1 = 100.0%; passes 1/1 = 100.0%; skipped 1/2 |
| static_analysis_negative | hits 0/0 = 100.0%; passes 0/0 = 100.0%; skipped 2/2 | hits 0/0 = 100.0%; passes 2/2 = 100.0%; skipped 0/2 |
| variables | hits 2/2 = 100.0%; passes 2/2 = 100.0%; skipped 0/2 | hits 2/2 = 100.0%; passes 2/2 = 100.0%; skipped 0/2 |
| workflow | hits 1/1 = 100.0%; passes 1/1 = 100.0%; skipped 0/1 | hits 1/1 = 100.0%; passes 1/1 = 100.0%; skipped 0/1 |

## Per-Query Results

| Query | Category | Expected hit | v0 rank | current rank | v0 status | current status | current top-1 |
|---|---|---|---:|---:|---|---|---|
| `cics_map_pdb3051` | cics_targets | True | 2 | 3 | True | True | `paragraph_logic:PDB305.CBL:paragraph_logic:RECEIVE-PDB3051` |
| `cics_link_pd0gcoda` | cics_targets | True | 2 | 3 | True | True | `cics_operations:PDB305.CBL:cics_operations` |
| `cics_link_pd3sort` | cics_targets | True | 2 | 2 | True | True | `cics_operations:PDB305.CBL:cics_operations` |
| `cics_xctl_pdpred` | cics_targets | True | 1 | 1 | True | True | `paragraph_logic:PDB305.CBL:paragraph_logic:XCTL-MAIN` |
| `external_pd1ac_commarea` | external_calls | True | 1 | 1 | True | True | `call_contract:PDB305.CBL:call_contract:PD1AC:3` |
| `variable_twcob_funzione` | variables | True | 1 | 1 | True | True | `static_values:PDB305.CBL:static_values:part:8` |
| `variable_static_prog_pf2` | variables | True | 1 | 1 | True | True | `variable_group:PDB305.CBL:variable_group:FILLER_2` |
| `paragraph_tastoer` | paragraphs | True | 1 | 1 | True | True | `error_path:PDB305.CBL:error_path:12` |
| `paragraph_prepara_map` | paragraphs | True | 1 | 1 | True | True | `paragraph_logic:PDB305.CBL:paragraph_logic:BROWSE-FASE2-ENTER-010` |
| `copybook_pdrtwa2_twcob_fase` | copybooks | True | 1 | 1 | True | True | `copybook_fields:PDB305.CBL:copybook_fields:part:24` |
| `workflow_prepara_map` | workflow | True | 2 | 2 | True | True | `screen.row_build:PDB305.CBL:screen.row_build:part:2` |
| `error_tastoer_message` | error_path | True | 1 | 1 | True | True | `error_path:PDB305.CBL:error_path:13` |
| `business_rule_wctpag` | business_rule | True | 1 | 1 | True | True | `business_rule:PDB305.CBL:business_rule:12` |
| `controlflow_pf7_logic` | controlflow | True | 3 | 1 | True | True | `controlflow.cfg:PDB305.CBL:controlflow.cfg:BROWSE-FASE2` |
| `screen_pf7_pf8_dispatch` | screen_flow | True | 9 | 1 | False | True | `screen.pagination:PDB305.CBL:screen.pagination:part:1` |
| `screen_row_build` | screen_flow | True | 1 | 1 | True | True | `screen.row_build:PDB305.CBL:screen.row_build:part:2` |
| `static_analysis_node_scoped_constants` | static_analysis | True | miss | 1 | skipped | True | `static_value.propagation:PDB305.CBL:static_value.propagation:06465835-f9cb-4fa1-9ac2-001cde669a0c` |
| `static_analysis_flow_sensitive_targets` | static_analysis | True | miss | miss | skipped | skipped | `:` |
| `negative_static_analysis_nonexistent_constant_pd9xxxx` | static_analysis_negative | False | miss | miss | skipped | True | `static_values:PDB305.CBL:static_values:part:8` |
| `negative_static_analysis_always_claim` | static_analysis_negative | False | miss | miss | skipped | True | `static_value.propagation:PDB305.CBL:static_value.propagation:06465835-f9cb-4fa1-9ac2-001cde669a0c` |
| `negative_nonexistent_program_pd9xxxx` | negative_canary | False | miss | miss | True | True | `cics_operations:PDB305.CBL:cics_operations` |

## Missing Fact Samples

### `bm25_terms`

- `COMMANDS`

### `chunk_ids`

- `call_contract|PDB305.CBL:CALL_CONTRACT:PD0UTI01:4`
- `dataflow.variable|PDB305.CBL:DATAFLOW.VARIABLE:KTEST1A`
- `dataflow.variable|PDB305.CBL:DATAFLOW.VARIABLE:KTEST3A`
- `dataflow.variable|PDB305.CBL:DATAFLOW.VARIABLE:PDRGCODA-FUNZIONE`
- `dataflow.variable|PDB305.CBL:DATAFLOW.VARIABLE:PDRGCODA-PD40-CODDIP-MATR`

## Changed Fact Samples

### `cics`

- `cics.operation|WRITEQ|QUEUE_WRITE|QUEUE|TWCOB-TS-CODA|arg|QUEUE|TWCOB-TS-CODA|IDENTIFIER|value_changed|<blank>|TWCOB-TS-CODA`

## Interpretation

A 100% expected-pass score means this fixed sparse query suite found no top-5 regression and the negative canary queries missed as expected. Queries gated by `requires_any_chunk_type` are skipped until the requested chunk family exists, so skipped static-analysis queries are not evidence of improvement. Fact-retention rows above show where chunk compaction changed the granularity or wording of facts.
