# feature/optimization Branch Summary

This branch made cobol-rekt better at preserving static facts and producing smaller retrieval outputs. It did **not** turn cobol-rekt into an optimizing compiler. The safest short description is:

> cobol-rekt remains a source-preserving COBOL reverse-engineering tool. This branch hardens literal-fact extraction and dynamic target inference, then compacts RAG retrieval output without rewriting source-derived artifacts.

## What We Set Out To Answer

The starting question was whether cobol-rekt supports classic compiler optimizations such as constant folding and constant propagation, and whether those ideas could help reduce output size.

The answer after the research and implementation work is:

| Question | Answer |
|---|---|
| Does cobol-rekt now have constant folding? | No. |
| Does cobol-rekt now have general constant propagation? | No. |
| Did this branch make useful progress near those areas? | Yes: it locked literal-fact behavior, improved confidence around dynamic CALL/CICS target inference, and added retrieval compaction. |
| Did this branch rewrite `cfg-*.json`, `flow_ast/*.json`, or `unified_model/*.json`? | No. Source-derived artifacts stay source-preserving. |

## Constant Folding: What We Do And Do Not Do

Constant folding means evaluating an expression at analysis time, for example treating:

```cobol
COMPUTE WS-TOTAL = 1 + 2
```

as if the generated artifact contained:

```text
WS-TOTAL = 3
```

This branch does **not** do that.

The Java behavior is now explicitly tested: `COMPUTE WS-COMP-X = 1 + 2` must not emit an `assignment_facts` entry. The current implementation only exports assignment facts for a bare numeric literal on the right-hand side, such as:

```cobol
COMPUTE WS-TOTAL = 42
```

So the accurate claim is:

> cobol-rekt extracts selected literal assignment facts, but it does not fold arithmetic expressions.

Possible future work is a metadata-only `folded_value` fact for closed literal expressions. That would still preserve the original expression text and would only add an extra fact. It is not implemented on this branch.

## Constant Propagation: What We Do And Do Not Do

Constant propagation means safely carrying a known value through later code, across assignments and control flow, for example knowing that a variable still equals a literal at a later use.

This branch does **not** implement general constant propagation.

What cobol-rekt already has, and what this branch tested more carefully, is limited literal-assignment provenance. That means the Java CFG export can sometimes infer dynamic program targets from a recent literal assignment:

```cobol
MOVE 'PAYPROG' TO WS-CALL-TARGET.
CALL WS-CALL-TARGET.
```

In that case, cobol-rekt can annotate the dynamic call as likely targeting `PAYPROG`, with medium confidence.

That is useful, but it is not full propagation. The current inference is not path-sensitive. It does not prove correctness across IF/EVALUATE joins, PERFORM boundaries, SQL, CICS, file reads, calls, or unknown side effects. The tests intentionally lock both the working cases and the weak cases, including cases where the resolver cannot infer a target and records a low-confidence unresolved identifier instead.

So the accurate claim is:

> cobol-rekt uses limited literal-assignment provenance for dynamic CALL/CICS target inference; it does not perform general constant propagation.

## What The Branch Actually Shipped

### Stage 1: Locked Existing Literal And Dynamic-Target Behavior

New Java tests were added before changing chunk behavior. They prove exact current behavior for:

- `COMPUTE` with arithmetic RHS: no assignment fact.
- Figurative constants such as `SPACES` and `ZEROS`: currently emitted as literal assignment facts.
- `SET` to an 88-level condition: no literal assignment fact.
- Dynamic CALL target inference after literal assignments.
- Dynamic CALL cases that remain unresolved.
- CICS XCTL target inference after literal assignments.

This was hardening work. It prevents future compaction or retrieval changes from accidentally changing Java analysis semantics.

### Stage 2: Compacted Repeated CICS Lines In The Dependencies Chunk

The `dependencies` chunk used to repeat similar CICS operation lines when the same command/resource appeared in multiple paragraphs.

This branch now aggregates repeated CICS overview lines by `(command, target, type)`:

```text
EXEC CICS WRITEQ TS QUEUE('Q1') - used in 3 paragraph(s): PARA-A, PARA-B, PARA-C.
```

Important guardrail: canonical CICS chunks are not deduplicated away. `cics.operation`, `cics.resource`, and `cics.program_transfer` remain the detailed evidence. Also, `HANDLE` and `IGNORE` CICS commands are preserved one-per-occurrence because paragraph attribution is meaningful error-handler evidence.

### Stage 3: Added BM25 Structured Term Weights

The BM25 side index now emits a new additive field:

```json
"structured_term_weights": {
  "PROCESS-MAIN": 1.0
}
```

This lets retrieval systems boost structured labels such as paragraph names without inflating chunk text with repeated labels.

Compatibility guardrails:

- `term_freq` is unchanged.
- `structured_terms` is unchanged and still present.
- `--label-boost` controls the new weights.
- The default boost is conservative: `1.0`.

### Stage 5: Added A Facts-Only Retrieval Profile

The new profile:

```bash
python3 chunk_pipeline.py out/report/MYPROGRAM.CBL.report --profile facts-only
```

emits a smaller set of fact-oriented chunks:

- `program_summary`
- `dependencies`
- `variable_group`
- COBOL analysis health

It intentionally omits narrative-heavy chunks such as `paragraph_logic`, `section_summary`, and `workflow`.

This is useful for lower-token machine retrieval surfaces. It is not a replacement for the default profile when a user wants human-readable paragraph explanations.

### Stage 6: Added A Benchmark Harness

The branch added:

- `scripts/bench_fixtures.json`
- `scripts/bench_queries.json`
- `scripts/bench_compaction.py`
- `scripts/bench_results.json`
- `scripts/bench_results.md`

The benchmark uses public fixtures from `smojol-test-code/` and records deterministic default vs facts-only measurements.

Current benchmark table:

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

Interpretation: on the benchmark fixture surface, facts-only reduces aggregate chunks from 33 to 12 and aggregate token count from 636 to 204.

Caveat: the harness currently uses synthetic report fixtures and runs the chunk pipeline with whitespace token counting. The column is named `total_bpe_tokens`, so either the harness should be changed to true BPE counting or the column should be renamed before using these numbers as thesis-grade BPE results. The direction is still useful: the facts-only profile is clearly smaller on the frozen benchmark surface.

### Stage 7: Added Human-Readable Optimization Documentation

`docs/optimization-and-compaction.md` explains the source-preserving design, support matrix, shipped changes, usage, benchmark table, and future work.

## What Changed For Users

Users can still run the default chunk pipeline exactly as before:

```bash
python3 chunk_pipeline.py out/report/MYPROGRAM.CBL.report
```

They can now request a smaller fact-oriented retrieval surface:

```bash
python3 chunk_pipeline.py out/report/MYPROGRAM.CBL.report --profile facts-only
```

They can also control BM25 paragraph-label weights:

```bash
python3 chunk_pipeline.py out/report/MYPROGRAM.CBL.report --label-boost 1.0
```

The generated manifest now records the selected profile:

```json
"profile": "default"
```

or:

```json
"profile": "facts-only"
```

## What Did Not Change

This branch does not:

- Rewrite COBOL source.
- Rewrite source-derived CFG, Flow AST, or unified-model JSON.
- Fold arithmetic expressions.
- Propagate constants globally.
- Remove canonical CICS evidence chunks.
- Replace deterministic knowledge-base documents with LLM output.
- Make facts-only the default profile.

## Final Wording To Use

Use this:

> On `feature/optimization`, cobol-rekt gained safer literal-fact tests and retrieval compaction features. It still does not implement compiler-style constant folding or general constant propagation. It preserves source-derived artifacts and adds smaller, better-indexed retrieval outputs.

Avoid this:

> cobol-rekt now optimizes COBOL with constant folding and propagation.

That would overclaim what the branch actually does.

## Verification

The branch was verified with:

```bash
python3 -m unittest test_chunk_pipeline_cics.py test_chunk_pipeline.py test_pipeline_hardening.py test_bm25_index.py test_chunk_pipeline_profiles.py test_bench_compaction.py
```

Result: 88 tests, 2 skipped.

```bash
mvn -pl smojol-toolkit test -Dcheckstyle.skip=true
```

Result: BUILD SUCCESS, 27 tests, 0 failures, 0 errors, 2 skipped.
