# PDCBVC.CBL RAG Bundle Benchmark

This benchmark compares the preserved `knowledge-base_rag_v0` bundle with the current `knowledge-base_rag` bundle using deterministic sparse retrieval and fact-level retention checks.

## Scope

- Producer-side sparse retrieval only; no embeddings, vector database, reranker, or LLM answer grading.
- Hit criteria require expected chunk type plus required terms from the query specification.
- Fact retention compares structured chunk metadata and BM25 terms; it is stricter than file-count retention but still not a semantic proof.

## Bundle Metrics

| Metric | v0 | current |
|---|---:|---:|
| chunk_count | 545 | 571 |
| total_files | 575 | 603 |
| total_bytes | 12589514 | 29995194 |
| knowledge_base_files | 4 | 4 |
| artifact_files | 22 | 24 |

## Static Values Chunk Completeness

This row is separate from fact retention because `metadata.static_values` may be denormalized across chunk parts. A 100% set-union fact retention score does not imply every chunk part kept the same per-variable body text.

| Metric | v0 | current |
|---|---:|---:|
| chunk_count | 11 | 4 |
| chunks_with_static_values_metadata | 11 | 4 |
| unique_variables | 63 | 63 |
| metadata_variable_instances | 693 | 252 |
| min_variables_per_chunk | 63 | 63 |
| median_variables_per_chunk | 63 | 63.0 |
| max_variables_per_chunk | 63 | 63 |
| chunks_with_full_program_variable_set | 11 | 4 |

## Integrity

| Area | v0 files | current files | retention | byte-identical | differing files |
|---|---:|---:|---:|---|---|
| `knowledge_base` | 4 | 4 | 100.0% | False | 00_Executive_Summary.md, 02_Data_Dictionary.md |
| `artifacts` | 22 | 24 | 100.0% | False | analysis_health.json, analysis_self_evaluation.json, cobol_structure.json, copybook_manifest.json, copybooks/PDCBVCM.cpy, pipeline_report.json, variable_values.json |

## Fact Retention

| Fact family | v0 facts | current facts | retained | retention | Jaccard | changed | improved |
|---|---:|---:|---:|---:|---:|---:|---:|
| `bm25_terms` | 934 | 1212 | 908 | 97.22% | 73.34% | 0 | 0 |
| `business_rules` | 0 | 155 | 0 | 100.0% | 0.0% | 0 | 0 |
| `chunk_ids` | 545 | 571 | 317 | 58.17% | 39.67% | 0 | 0 |
| `cics` | 34 | 50 | 34 | 100.0% | 68.0% | 0 | 0 |
| `copybooks` | 435 | 485 | 419 | 96.32% | 83.63% | 0 | 0 |
| `dataflow.sidecar` | 0 | 93 | 0 | 100.0% | 0.0% | 0 | 0 |
| `dataflow.variable` | 1741 | 1741 | 1722 | 98.91% | 97.84% | 0 | 0 |
| `paragraphs` | 976 | 923 | 893 | 91.5% | 88.77% | 0 | 0 |
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
| `cics_xctl_pdpred` | cics_targets | True | 1 | 1 | True | True | `paragraph_logic:PDCBVC.CBL:paragraph_logic:XCTL-LIV5` |
| `external_pd1fs00_commarea` | external_calls | True | 1 | 1 | True | True | `external_program_calls:PDCBVC.CBL:external_program_calls` |
| `variable_twcob_funzione` | variables | True | 1 | 1 | True | True | `dataflow.variable:PDCBVC.CBL:dataflow.variable:PXCSEMAF-STATUS` |
| `variable_static_prog_liv5` | variables | True | 1 | 1 | True | True | `variable_group:PDCBVC.CBL:variable_group:FILLER_1` |
| `paragraph_selection_flow` | paragraphs | True | 1 | 1 | True | True | `screen.selection:PDCBVC.CBL:screen.selection` |
| `paragraph_prep_riga` | paragraphs | True | 1 | 1 | True | True | `screen.row_build:PDCBVC.CBL:screen.row_build` |
| `copybook_pdrtwa2_twcob_fase` | copybooks | True | 1 | 1 | True | True | `copybook_fields:PDCBVC.CBL:copybook_fields:part:17` |
| `workflow_browse_phase2` | workflow | True | 1 | 2 | True | True | `business_rule:PDCBVC.CBL:business_rule:71` |
| `error_no_selection` | error_path | True | 1 | 1 | True | True | `error_path:PDCBVC.CBL:error_path:27` |
| `business_rule_selection` | business_rule | True | 1 | 1 | True | True | `business_rule:PDCBVC.CBL:business_rule:54` |
| `controlflow_pf7_logic` | controlflow | True | 2 | 1 | True | True | `controlflow.cfg:PDCBVC.CBL:controlflow.cfg:BROWSE-FASE2` |
| `screen_pf7_pf8_dispatch` | screen_flow | True | 4 | 1 | True | True | `screen.pagination:PDCBVC.CBL:screen.pagination` |
| `screen_dfhpf7_dfhpf8_exact` | screen_flow | True | 1 | 1 | True | True | `controlflow.cfg:PDCBVC.CBL:controlflow.cfg:BROWSE-FASE2` |
| `static_analysis_node_scoped_constants` | static_analysis | True | miss | 1 | skipped | True | `static_value.propagation:PDCBVC.CBL:static_value.propagation:06f898c6-ce78-4d80-834f-fba6e18087c5` |
| `static_analysis_flow_sensitive_targets` | static_analysis | True | miss | miss | skipped | skipped | `:` |
| `negative_static_analysis_nonexistent_constant_pd9xxxx` | static_analysis_negative | False | miss | miss | skipped | True | `static_values:PDCBVC.CBL:static_values:part:2` |
| `negative_static_analysis_always_claim` | static_analysis_negative | False | miss | miss | skipped | True | `static_value.propagation:PDCBVC.CBL:static_value.propagation:06f898c6-ce78-4d80-834f-fba6e18087c5` |
| `negative_nonexistent_program_pd9xxxx` | negative_canary | False | miss | miss | True | True | `cics_operations:PDCBVC.CBL:cics_operations` |

## Missing Fact Samples

### `bm25_terms`

- `BYTE`
- `COLLABOR`
- `COMMANDS`
- `COPYBOOK-OWNED`
- `DEAD`
- `DRUTI01`
- `DRVC-CESS-PROVV-NUM`
- `IGLA-OPER`
- `MARKS`
- `MEDIUM`

### `chunk_ids`

- `copybook_fields|PDCBVC.CBL:COPYBOOK_FIELDS:PART:22`
- `copybook_fields|PDCBVC.CBL:COPYBOOK_FIELDS:PART:23`
- `copybook_fields|PDCBVC.CBL:COPYBOOK_FIELDS:PART:24`
- `copybook_fields|PDCBVC.CBL:COPYBOOK_FIELDS:PART:25`
- `copybook_fields|PDCBVC.CBL:COPYBOOK_FIELDS:PART:26`
- `copybook_fields|PDCBVC.CBL:COPYBOOK_FIELDS:PART:27`
- `copybook_fields|PDCBVC.CBL:COPYBOOK_FIELDS:PART:28`
- `copybook_fields|PDCBVC.CBL:COPYBOOK_FIELDS:PART:29`
- `copybook_fields|PDCBVC.CBL:COPYBOOK_FIELDS:PART:30`
- `copybook_fields|PDCBVC.CBL:COPYBOOK_FIELDS:PART:31`

### `copybooks`

- `copybook_fields|copybook|DFHAID|status|STUBBED`
- `copybook_fields|copybook|DFHAID|stubbed|TRUE`
- `copybook_fields|copybook|DFHBMSCA|status|STUBBED`
- `copybook_fields|copybook|DFHBMSCA|stubbed|TRUE`
- `copybook_fields|copybook|PDIABEND|status|STUBBED`
- `copybook_fields|copybook|PDIABEND|stubbed|TRUE`
- `copybook_fields|copybook|PDPSQLER|status|STUBBED`
- `copybook_fields|copybook|PDPSQLER|stubbed|TRUE`
- `copybook_fields|copybook|PDSAVTW2|status|STUBBED`
- `copybook_fields|copybook|PDSAVTW2|stubbed|TRUE`

### `dataflow.variable`

- `M0AMBO|origin_group|`
- `M1DATAO|origin_group|`
- `M1MSGL|origin_group|`
- `M1MSGO|origin_group|`
- `M1PF7A|origin_group|`
- `M1PF8A|origin_group|`
- `M1SYSO|origin_group|`
- `MCOGO|origin_group|`
- `MDESCO|origin_group|`
- `MDSESSO|origin_group|`

### `paragraphs`

- `paragraph_logic|BROWSE-FASE2-SEL-20|copybooks_used|DFHAID`
- `paragraph_logic|BROWSE-FASE2-SEL-20|copybooks_used|DFHBMSCA`
- `paragraph_logic|BROWSE-FASE2-SEL-20|copybooks_used|PD1FS00`
- `paragraph_logic|BROWSE-FASE2-SEL-20|copybooks_used|PD1VOCI`
- `paragraph_logic|BROWSE-FASE2-SEL-20|copybooks_used|PDCBVCM`
- `paragraph_logic|BROWSE-FASE2-SEL-20|copybooks_used|PDIABEND`
- `paragraph_logic|BROWSE-FASE2-SEL-20|copybooks_used|PDRTIP01`
- `paragraph_logic|BROWSE-FASE2-SEL-20|copybooks_used|PDRTWA2`
- `paragraph_logic|BROWSE-FASE2-SEL-20|copybooks_used|PDRUTI01`
- `paragraph_logic|BROWSE-FASE2-SEL-20|copybooks_used|PDRVC`

## Changed Fact Samples

## Interpretation

A 100% expected-pass score means this fixed sparse query suite found no top-5 regression and the negative canary queries missed as expected. Queries gated by `requires_any_chunk_type` are skipped until the requested chunk family exists, so skipped static-analysis queries are not evidence of improvement. Fact-retention rows above show where chunk compaction changed the granularity or wording of facts.
