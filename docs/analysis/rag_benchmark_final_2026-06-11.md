# Final RAG Benchmark - 2026-06-11

Benchmarks compare `knowledge-base_rag_v0` with regenerated bundles after Tasks 1-3. Default mode excludes `static_value.propagation` and `flow_sensitive.target` chunks; static mode uses `--include-static-analysis-rag`.

## Retrieval Summary

| Program/mode | chunks | original current pass@5 | original current hit@5 | added static current pass@5 | added static current hit@5 | skipped current |
|---|---:|---:|---:|---:|---:|---:|
| PDB305 default | 334 | 17/17 | 16/16 | 0/0 | 0/0 | 4 |
| PDB305 static | 376 | 17/17 | 16/16 | 3/3 | 1/1 | 1 |
| PDCBVC default | 473 | 16/16 | 15/15 | 0/0 | 0/0 | 4 |
| PDCBVC static | 571 | 16/16 | 15/15 | 3/3 | 1/1 | 1 |

## Baseline Original Query Set

| Program/mode | original v0 pass@5 | original v0 hit@5 | added static v0 active/skipped |
|---|---:|---:|---:|
| PDB305 default | 16/17 | 15/16 | 0 active, 4 skipped |
| PDB305 static | 16/17 | 15/16 | 0 active, 4 skipped |
| PDCBVC default | 16/16 | 15/15 | 0 active, 4 skipped |
| PDCBVC static | 16/16 | 15/15 | 0 active, 4 skipped |

## Fact Retention Highlights

| Program/mode | CICS retained | CICS changed/improved | static_values retained | dataflow.sidecar current facts | path_sensitive current facts |
|---|---:|---:|---:|---:|---:|
| PDB305 default | 50/50 (100.0%) | 1/1 | 266/266 (100.0%) | 41 | 0 |
| PDB305 static | 50/50 (100.0%) | 1/1 | 266/266 (100.0%) | 41 | 0 |
| PDCBVC default | 34/34 (100.0%) | 0/0 | 351/351 (100.0%) | 93 | 0 |
| PDCBVC static | 34/34 (100.0%) | 0/0 | 351/351 (100.0%) | 93 | 0 |

## Notes

- Fixed-original query results exclude `static_analysis` and `static_analysis_negative` categories.
- Added static-analysis query results include only those categories and may have skipped rows when a required opt-in chunk type is absent.
- PDB305 static mode keeps CICS retention at 50/50 with one changed/improved WRITEQ QUEUE value (`<blank>` to `TWCOB-TS-CODA`), matching the Task 3 comparator fix.
- `flow_sensitive.target` remains absent in these regenerated bundles because Task 4 found no resolved dynamic target sites in PDB305/PDCBVC.
