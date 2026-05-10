# Optimization and Compaction

cobol-rekt is a source-preserving reverse-engineering and retrieval-compaction tool. It does not implement compiler-style constant folding or general constant propagation. It extracts limited literal-assignment provenance for dynamic CALL/CICS target inference, surfaces dead-code candidates from CFG reachability, and compacts retrieval output via the chunk pipeline. Source-derived JSON artefacts (`cfg/cfg-*.json`, `unified_model/*.json`) are never rewritten or pruned.

## Support Matrix

| Technique | What was tried | What was implemented | What is deferred | Tested by |
|---|---|---|---|---|
| Constant folding | Reviewed Java expression and COMPUTE metadata paths. | No source or artifact rewrite. Existing literal-fact behavior is locked. | Metadata-only `folded_value` for closed literal COMPUTE expressions, gated on a concrete consumer. | `smojol-toolkit/src/test/java/org/smojol/toolkit/analysis/task/JavaHardeningRegressionTest.java` |
| Constant propagation | Reviewed Java latest-literal target inference and Python static-value extraction. | Limited literal-assignment provenance remains only provenance, not path-sensitive propagation. | Straight-line paragraph-scoped propagation facts with strict kill rules. | `smojol-toolkit/src/test/java/org/smojol/toolkit/analysis/task/JavaHardeningRegressionTest.java` |
| Dynamic CALL/CICS target inference | Boundary behavior was tested before compaction work. | Current medium/low confidence annotations are locked as contract. | Wider reaching-definitions analysis. | `smojol-toolkit/src/test/java/org/smojol/toolkit/analysis/task/JavaHardeningRegressionTest.java` |
| CICS dependency compaction | Repeated CICS overview lines in `dependencies` were grouped. | `dependencies` aggregates repeated `(command, target, type)` triples; HANDLE/IGNORE stay verbatim. | Removing or deduplicating canonical `cics.*` chunks. | `test_chunk_pipeline_cics.py` |
| BM25 paragraph-label compaction | Paragraph labels were moved into weighted index metadata. | `structured_term_weights` is additive; `term_freq` and `structured_terms` are unchanged. | Deprecating `structured_terms` or changing retrieval scoring defaults without evaluator numbers. | `test_bm25_index.py` |
| Facts-only profile | A compact retrieval profile was added. | `--profile facts-only` emits core fact chunks and records `chunks_manifest.json.profile`. | Replacing the default narrative profile. | `test_chunk_pipeline_profiles.py` |
| Benchmark harness | Public fixtures from `smojol-test-code/` were frozen by SHA-256. | `scripts/bench_compaction.py` measures default vs facts-only chunk metrics. | Private corpus benchmarking. | `test_bench_compaction.py` |

## What Shipped

- Stage 1 locked literal-fact gates and dynamic target inference in Java tests before any compaction code changed.
- Stage 2 compacted only the `dependencies` CICS overview text while preserving canonical CICS chunks.
- Stage 3 added BM25 `structured_term_weights` and the `--label-boost` CLI flag.
- Stage 5 added the opt-in `--profile facts-only` retrieval profile.
- Stage 6 added a deterministic benchmark harness and frozen public fixture/query files.

## Usage

Default chunk generation:

```bash
python3 chunk_pipeline.py out/report/MYPROGRAM.CBL.report
```

Facts-only profile:

```bash
python3 chunk_pipeline.py out/report/MYPROGRAM.CBL.report --profile facts-only
```

The facts-only profile emits `program_summary`, `dependencies`, `variable_group`, and COBOL analysis-health chunks. It is for lower-token machine retrieval surfaces, not a replacement for human-readable documentation or the default paragraph narrative chunks.

BM25 label boost:

```bash
python3 chunk_pipeline.py out/report/MYPROGRAM.CBL.report --label-boost 1.0
```

`--label-boost` controls values in `bm25_index.json` entry field `structured_term_weights`. It does not modify `term_freq` or `structured_terms`.

## Benchmarks

| fixture | profile | chunks | total_bpe_tokens | max_bpe_per_chunk | duplicate_hashes | bm25_entries |
|---|---:|---:|---:|---:|---:|---:|
| small-hello | default | 11 | 212 | 45 | 0 | 9 |
| small-hello | facts-only | 4 | 68 | 35 | 0 | 3 |
| medium-proxy-test-exp1 | default | 11 | 212 | 45 | 0 | 9 |
| medium-proxy-test-exp1 | facts-only | 4 | 68 | 35 | 0 | 3 |
| large-nist85 | default | 11 | 212 | 45 | 0 | 9 |
| large-nist85 | facts-only | 4 | 68 | 35 | 0 | 3 |
| aggregate | default | 33 | 636 | 45 | 0 | 27 |
| aggregate | facts-only | 12 | 204 | 35 | 0 | 9 |

## Future Work

- Metadata-only `folded_value` facts for closed literal COMPUTE expressions, only when a downstream consumer needs them.
- Straight-line paragraph-scoped propagation facts with strict kills on non-literal writes, CALL, EXEC SQL, EXEC CICS, READ, ACCEPT, or unknown side effects.
- Broader evaluator-derived recall checks on a larger public corpus.

## What This Is Not

This branch does not fold expressions, propagate constants globally, rewrite COBOL source, prune CFG or unified-model JSON, hide original comments, or replace deterministic knowledge-base documents with LLM output. It compacts retrieval-layer presentation while preserving source-derived artifacts.
