# Constant Folding and Constant Propagation in the COBOL Static Analyzer

## 1. Executive Summary

This document defines the planned constant folding and constant propagation work for cobol-rekt. The goal is not to rewrite COBOL source code and not to rewrite CFG text. The goal is to add source-preserving static-analysis facts beside existing artifacts, so downstream tools can see what the analyzer can prove without losing the original evidence.

Phase 1 implements local constant folding for safe closed numeric `COMPUTE` expressions. Phase 2 will implement CFG-based constant propagation as a separate dataflow artifact. The project must prioritize reliability over aggressive compiler-style optimization: an omitted fold is acceptable; an incorrect constant is not.

## 2. Background: What Is Constant Folding?

Constant folding means evaluating an expression at analysis time when the result is already known from the expression itself.

```cobol
COMPUTE WS-A = 1 + 2
```

The expression `1 + 2` can be evaluated statically as `3`. The analyzer should emit a fact saying that this expression folds to `3`. It should not rewrite the COBOL statement.

There are two different concepts:

| Concept | Meaning |
|---|---|
| Source code transformation | Replaces the program text or generated IR, for example rewriting `1 + 2` into `3`. |
| Static-analysis enrichment | Keeps source-derived text unchanged and adds a fact beside it. |

For this project, only static-analysis enrichment is allowed.

## 3. Background: What Is Constant Propagation?

Constant propagation means carrying proven constants through control flow.

```cobol
MOVE 10 TO WS-A
COMPUTE WS-B = WS-A + 5
```

If the analyzer can prove that `WS-A` is `10` at the entry of the `COMPUTE` node, then it can infer that `WS-B` becomes `15`.

Propagation is more complex than folding because it requires CFG analysis, branch merging, kill rules, loop handling, and conservative handling of runtime inputs such as `READ`, `ACCEPT`, `CALL`, `EXEC SQL`, and `EXEC CICS`. Propagation will be implemented after Phase 1.

## 4. Why This Matters For This Project

Constant folding and propagation can improve the COBOL static-analysis pipeline by producing better static facts without pretending to be an optimizing compiler.

Expected benefits:

- Better explanations of business logic.
- Better variable value facts.
- Better dynamic `CALL` target resolution later.
- Better CICS target resolution later.
- Better path-sensitive analysis later.
- Better RAG chunks later.
- Better diagnostics for unsupported or unsafe cases.
- Better distinction between values that are known, unknown, runtime-dependent, or unsupported.

The analyzer must never overclaim. For example, it must not say "this variable is always 3" unless that is globally proven. Local facts should be described as local facts, and propagated facts should include their CFG scope and provenance.

## 5. Current Behavior Before This Feature

Representative input:

```cobol
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CONSTFOLD.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-A PIC 9(4).
       01 WS-B PIC 9(4).
       01 WS-C PIC 9(4).
       01 WS-D PIC 9(4).
       PROCEDURE DIVISION.
       MAIN-PARA.
           COMPUTE WS-A = 1 + 2
           COMPUTE WS-B = WS-A + 1
           COMPUTE WS-C = 1 / 0
           MOVE 7 TO WS-D
           GOBACK.
```

Before this feature:

- `COMPUTE WS-A = 1 + 2` does not emit a folded value fact.
- `COMPUTE WS-A = 1 + 2` should still not emit `assignment_facts`; current Java tests lock that behavior.
- `MOVE 7 TO WS-D` emits the existing literal `assignment_facts`.
- CFG text and `originalText` remain the source statement.
- No static diagnostic explains why `WS-B = WS-A + 1` was not folded.
- No diagnostic explains unsafe `1 / 0`.

Representative before snippet:

```json
{
  "originalText": "COMPUTE WS-A = 1 + 2",
  "metadata": {}
}
```

For the `MOVE`:

```json
{
  "originalText": "MOVE 7 TO WS-D",
  "metadata": {
    "assignment_facts": [
      {
        "target_variable": "WS-D",
        "source_value": "7",
        "source_kind": "literal",
        "statement_type": "MOVE",
        "provenance_source": "java_move_literal"
      }
    ]
  }
}
```

## 6. Expected Behavior After Phase 1: Local Constant Folding

For:

```cobol
COMPUTE WS-A = 1 + 2
```

Expected added metadata:

```json
{
  "metadata": {
    "folded_value_facts": [
      {
        "schema_version": "1.0",
        "fact_type": "folded_expression",
        "status": "folded",
        "statement_type": "COMPUTE",
        "target_variable": "WS-A",
        "original_expression": "1 + 2",
        "folded_expression": "3",
        "value": {
          "state": "CONSTANT",
          "kind": "NUMERIC",
          "raw_lexeme": "3",
          "normalized_value": "3",
          "display_value": "3",
          "numeric": {
            "decimal": "3",
            "scale": 0,
            "precision": 1,
            "sign": "POSITIVE"
          }
        },
        "confidence": "high",
        "provenance_source": "java_static_value_folded_expression"
      }
    ],
    "folding_diagnostics": []
  }
}
```

The current CFG writer uses Gson without `serializeNulls()`, so optional payloads such as `figurative` and `type_context` are omitted when they are not present.

For:

```cobol
COMPUTE WS-B = WS-A + 1
```

Expected diagnostic:

```json
{
  "code": "FOLD_UNSUPPORTED_VARIABLE_REFERENCE",
  "severity": "info",
  "category": "unsupported",
  "message": "Expression contains variable WS-A; Phase 1 folds only closed literal expressions.",
  "construct": "WS-A"
}
```

For:

```cobol
COMPUTE WS-C = 1 / 0
```

Expected diagnostic:

```json
{
  "code": "FOLD_UNSAFE_DIVIDE_BY_ZERO",
  "severity": "warning",
  "category": "unsafe",
  "message": "Division by zero cannot be folded safely."
}
```

For:

```cobol
MOVE 7 TO WS-D
```

Expected behavior:

- Existing `assignment_facts` remain unchanged.
- No folding diagnostic is emitted.
- No folded value fact is emitted by Phase 1.

## 7. Expected Behavior After Phase 2: Constant Propagation

Propagation is a later phase and should not be part of PR 1.

Example:

```cobol
MOVE 10 TO WS-A
COMPUTE WS-B = WS-A + 5
```

Expected future dataflow result:

```json
{
  "node_states": {
    "node-compute-ws-b": {
      "entry_constants": {
        "WS-A": {
          "state": "CONSTANT",
          "kind": "NUMERIC",
          "normalized_value": "10"
        }
      },
      "exit_constants": {
        "WS-B": {
          "state": "CONSTANT",
          "kind": "NUMERIC",
          "normalized_value": "15"
        }
      }
    }
  }
}
```

This belongs in:

```text
static_analysis/dataflow.json
```

Propagation facts are sidecar facts. They do not rewrite source, CFG text, or assignment facts.

## 8. Implementation Plan

### Status Flags

This plan is a living implementation ledger. Every step below must carry one of these flags:

| Flag | Meaning |
|---|---|
| `DONE` | Completed and committed. |
| `WORKING` | Actively being implemented on the current branch. |
| `PENDING` | Planned but not started. |
| `BLOCKED` | Cannot proceed until a named blocker is resolved. |
| `SKIPPED` | Deliberately not implemented; reason must be recorded. |

### Living Documentation Rule

This document is part of the implementation contract. It must be updated whenever any of the following changes:

- Scope changes for a phase or PR.
- A planned step moves from `PENDING` to `WORKING`, `DONE`, `BLOCKED`, or `SKIPPED`.
- A diagnostic code is added, removed, or renamed.
- A JSON schema field is added, removed, or renamed.
- A supported or unsupported COBOL construct changes status.
- A safety rule, kill rule, merge rule, or alias rule changes.
- Accuracy or performance measurements are produced.
- A benchmark, golden fixture, or acceptance criterion changes.
- An implementation decision contradicts this document.

If implementation discovers that this document is wrong, the documentation must be corrected and committed before the code that depends on the corrected decision is merged. No phase is considered complete until the document status and measured results match the implementation.

### Grand Plan Status Ledger

| Step | Flag | Deliverable | Acceptance Check |
|---|---|---|---|
| 0.1 | `DONE` | Source-preserving strategy agreed in discussion 0006. | Discussion resolved with Claude/Codex agreement. |
| 0.2 | `DONE` | Human-readable strategy document committed. | `docs/static-analysis/constant-folding-propagation.md` exists in git history. |
| 0.3 | `DONE` | Final Phase 1 scope pinned. | PR 1 scope and non-goals listed in this document. |
| 0.4 | `DONE` | Accuracy/performance reporting requirement added. | Section 20 defines metrics to record during implementation. |
| 1.1 | `DONE` | Add `StaticValue` model and payload records. | Unit tests prove states, kinds, exact decimal representation, and code inspection verifies no `Double` use in `org.smojol.common.staticanalysis`. |
| 1.2 | `DONE` | Add `StaticValueLiteralExtractor`. | Tests parse dot-decimal numeric literals and reject decimal comma, invalid numeric text, nonnumeric literals, and unsupported figuratives. |
| 1.3 | `DONE` | Add `StaticExpressionFolder` for closed numeric expressions. | Tests fold addition, subtraction, multiplication, unary signs, parentheses, decimal addition, and exact division. |
| 1.4 | `DONE` | Emit `folded_value_facts` from `ComputeFlowNode.metadata()`. | Golden fixture has folded facts for `COMPUTE WS-A = 1 + 2`, `(1 + 2) * -3`, `1.20 + 2.30`, `1 / 4`, and `10 - 3`. |
| 1.5 | `DONE` | Emit `folding_diagnostics` for considered unsupported/unsafe `COMPUTE` statements. | Golden fixture emits exact diagnostics for variable reference, divide by zero, non-terminating division, figurative constant, and exponentiation. |
| 1.6 | `DONE` | Preserve existing artifacts and behavior. | Tests prove `assignment_facts`, statement text, CFG node/edge count, and dynamic CALL/CICS legacy behavior are unchanged; no RAG/chunk code changed in Phase 1. |
| 1.7 | `DONE` | Record Phase 1 accuracy/performance stats. | Report includes inspected/folded/skipped counts, diagnostic counts, Java target-suite wall-clock, and additive CFG size delta. |
| 2.1 | `DONE` | Add `static_analysis/dataflow.json` skeleton. | `WRITE_CFG` emits a sidecar artifact with schema version, analysis version, disabled propagation config, summary counts, empty diagnostics, empty alias/paragraph sections, and one empty node state per CFG node. |
| 2.2 | `DONE` | Add paragraph summaries. | Dataflow artifact records one summary per CFG `PARAGRAPH`: contained node IDs, direct read/write sets, paragraph calls, called programs, external side effects, unsupported/deferred constructs, cycle flag, and conservative transitive summary status. |
| 2.3 | `DONE` | Add syntax-derived alias-set builder. | `static_analysis/dataflow.json` records deterministic conservative alias sets for `REDEFINES`, group/child storage, and `OCCURS` storage. |
| 2.4 | `DONE` | Apply alias sets as conservative per-node kill facts. | Direct executable writes emit deterministic `ALIAS_CONSERVATIVE_KILL` entries for overlapping group, `REDEFINES`, and `OCCURS` members; entry/exit constants remain empty. |
| 2.5 | `DONE` | Add basic fixed-point numeric CFG propagation. | Entry/exit states converge deterministically for numeric literal `MOVE` facts and folded numeric `COMPUTE` facts; branch joins keep only constants proven equal on every incoming path; alias kills invalidate overlapping storage before new facts are written. |
| 2.6a | `DONE` | Add first dataflow-local runtime/input kill rules. | Tests prove `ACCEPT` targets, `CALL USING` reference arguments, and `INITIALIZE` targets remove prior constants; `BY CONTENT` and `BY VALUE` call arguments remain unchanged; `MOVE WS-A TO WS-C` is still not propagated. |
| 2.6b | `DONE` | Add remaining runtime-output kills. | Tests cover `READ INTO`, `STRING INTO`, `UNSTRING INTO`, `INSPECT`, CICS output arguments such as `RECEIVE INTO`, and SQL `SELECT/FETCH ... INTO` host-variable outputs. |
| 2.6c | `DONE` | Add safe variable-copy transfer rule. | Tests prove `MOVE <known-variable> TO <target>` copies a proven numeric entry constant after runtime/input/output kills, and prove killed source values are not copied. Expression propagation from known variables remains pending. |
| 2.6d | `DONE` | Add safe numeric expression transfer rule. | Tests prove `COMPUTE <target> = <known-variable> + <numeric-literal>` produces a target constant when all referenced variables are proven numeric at node entry; unsupported or unsafe expressions still produce no propagation fact. |
| 2.6e | `DONE` | Add join diagnostics for conflicting predecessor constants. | Solver-level tests prove a real multi-predecessor join drops `WS-D` when incoming predecessors prove `20` and `30`, and emits exact `DATAFLOW_CONSTANT_DROPPED_AT_JOIN` evidence without changing the joined entry state. |
| 2.6f | `DONE` | Add loop-carried constant diagnostics for CFG cycles. | Solver-level tests prove a variable modified inside a CFG cycle is not propagated after the loop and emits exact `DATAFLOW_LOOP_CARRIED_CONSTANT_NOT_INFERRED` evidence while the solver still converges. |
| 2.7 | `DONE` | Record Phase 2 accuracy/performance stats. | This document now consolidates the Phase 2 examples, fixture metrics, supported transfer rules, diagnostics, limitations, and reproducibility commands. Memory profiling remains deferred to a corpus benchmark because the current Java hardening tests do not expose stable per-fixture heap measurements. |
| 3.0 | `DONE` | Write detailed Phase 3 pre-coding plan. | This document now defines the exact ordering, schemas, fixtures, tests, invariants, and risk controls for path-sensitive dynamic `CALL`/CICS facts. |
| 3.1a | `DONE` | Add quoted alphanumeric constants to the dataflow sidecar. | `MOVE "PROG-A" TO WS-PGM` and `MOVE WS-PGM TO WS-COPY` now carry `ALPHANUMERIC` constants through the same fixed-point solver; runtime, alias, and join kills still apply. Path-sensitive target fields remain disabled. |
| 3.1b | `DONE` | Add path-sensitive dynamic `CALL` metadata fields. | Dynamic `CALL WS-PGM` reads `WS-PGM` from node `entry_constants` and emits new `path_sensitive_call_*` fields without changing `resolved_call_target`, `call_target_source`, or `dynamic_call_resolution_confidence`. Runtime-killed identifiers emit an explicit path-sensitive unresolved status rather than reusing stale legacy literals. |
| 3.2a | `DONE` | Add path-sensitive CICS target metadata fields. | CICS identifier targets such as `PROGRAM(WS-CICS-PGM)` read proven entry constants and emit new `path_sensitive_cics_*` fields without changing legacy `resolved_cics_target`, `cics_target_source`, or `cics_dynamic_resolution_confidence`; runtime-killed identifiers stay path-sensitive unresolved. |
| 3.2b | `PENDING` | Add path-sensitive CICS argument facts. | Multiple CICS identifier arguments can be reported in a new additive `path_sensitive_cics_arguments` array; existing `cics_arguments` stays unchanged. |
| 3.3 | `PENDING` | Evaluate target-resolution accuracy. | Frozen fixtures report exact expected-target pass/fail counts and legacy-vs-path-sensitive deltas before any RAG integration claims are allowed. |
| 4.1 | `PENDING` | Add optional static-value RAG chunks. | Chunks include only high-confidence facts with provenance and no unsupported "always" wording. |
| 4.2 | `PENDING` | Evaluate retrieval and token impact. | Benchmark reports chunk count, token count, recall, and retrieval-ranking deltas. |
| 5.1 | `PENDING` | Publish final implementation documentation update. | This document records final schemas, measured results, known limitations, and any skipped work. |

### Phase 1 Checkpoints

| Date | Status | What changed | Verification |
|---|---|---|---|
| 2026-05-11 | `WORKING` | Added the sealed `StaticValue` model, closed numeric expression folder, additive `folded_value_facts`/`folding_diagnostics` emission from `ComputeFlowNode.metadata()`, and the first golden fixture. | `mvn -pl smojol-core install -Dcheckstyle.skip=true -DskipTests`; `mvn -pl smojol-toolkit test -Dcheckstyle.skip=true -Dtest=JavaHardeningRegressionTest` passed, 19 tests. |
| 2026-05-11 | `WORKING` | Added exact decimal payload tests, preserved BigDecimal scale in `StaticValue`, extended the fixture to cover parentheses, unary minus, decimal addition, exact division, subtraction, non-terminating division, figurative constants, and exponentiation. | Targeted checks passed: `StaticValueTest` 3 tests and `JavaHardeningRegressionTest` 21 tests. Broader checks passed: `mvn -pl smojol-core test -Dcheckstyle.skip=true` 94 tests; `mvn -pl smojol-toolkit test -Dcheckstyle.skip=true` 33 tests, 2 skipped. Code inspection found no `Double`, `double`, `Float`, `float`, or `TypedRecord` usage in the new static-analysis package. |
| 2026-05-12 | `DONE` | Completed Phase 1 with literal-extractor unit tests, unary plus coverage, source/CFG preservation assertions, and fixture-level accuracy/size/runtime measurements. | Targeted checks passed: `StaticValueTest` + `StaticValueLiteralExtractorTest` 8 tests; `JavaHardeningRegressionTest` 22 tests. Broader checks passed: `mvn -pl smojol-core test -Dcheckstyle.skip=true` 99 tests; `mvn -pl smojol-toolkit test -Dcheckstyle.skip=true` 34 tests, 2 skipped. Metrics: 11 inspected `COMPUTE`s, 6 folded facts, 5 exact diagnostics, 18 CFG nodes, 17 edges, +4,387 minified bytes of additive folding metadata, target Java hardening suite wall-clock 13.723s. |

### Phase 2 Checkpoints

| Date | Status | What changed | Verification |
|---|---|---|---|
| 2026-05-12 | `DONE` | Added the first `static_analysis/dataflow.json` sidecar. It is intentionally a skeleton: every CFG node has an empty `entry_constants`, `exit_constants`, `kills`, and `diagnostics` container, while propagation, alias analysis, paragraph summaries, and path-sensitive targets remain disabled. | Targeted check passed: `mvn -pl smojol-toolkit test -Dcheckstyle.skip=true -Dtest=JavaHardeningRegressionTest`, 24 tests. Broader check passed: `mvn -pl smojol-toolkit test -Dcheckstyle.skip=true`, 36 tests, 2 skipped. Fixture metrics: 18 node states for 18 CFG nodes, 17 CFG edges recorded in the summary, 0 entry constants, 0 exit constants, 0 kills, 0 diagnostics, 0 alias sets, 0 paragraph summaries, 3,453 bytes for the pretty-printed sidecar, target suite wall-clock 20.078s. |
| 2026-05-12 | `DONE` | Added paragraph summaries to the sidecar without starting propagation. Summaries now report contained CFG node IDs, direct read/write variables, called paragraphs, called programs, external side effects, and a conservative transitive status. When a paragraph performs another paragraph, transitive read/write lists remain empty and an explicit deferred diagnostic is stored under that paragraph's `unsupported_constructs`. | Targeted check passed: `mvn -pl smojol-toolkit test -Dcheckstyle.skip=true -Dtest=JavaHardeningRegressionTest`, 26 tests. Broader check passed: `mvn -pl smojol-toolkit test -Dcheckstyle.skip=true`, 38 tests, 2 skipped. Fixture metrics: `constant-folding-phase1.cbl` has 1 paragraph summary, 15 contained node IDs, 1 direct read variable, 12 direct modified variables, 0 paragraph calls, 0 side effects, 5,239-byte pretty-printed sidecar, target suite wall-clock 13.467s. `metadata-features.cbl` has 4 paragraph summaries; `MAIN-PARA` records `LOOP-PARA`, called programs `DYNPROG` and `SUBPROG`, side effects `ACCEPT`, `CALL`, `CLOSE`, `OPEN`, `READ`, `WRITE`, and deferred transitive expansion. |
| 2026-05-12 | `DONE` | Added conservative alias-set summaries to the sidecar without starting propagation. The builder records `group_child:*`, `occurs:*`, and `redefines:*` entries using the Java data-structure model, collapses duplicate table expansions deterministically, and stores syntax-derived evidence such as level number, parent, redefines target, occurs count, data type, and source line. Byte-offset/byte-size layout evidence is deliberately deferred because the expanded table/redefinition model can recurse through layout sizing on the stress fixture. | Targeted check passed: `mvn -pl smojol-toolkit test -Dcheckstyle.skip=true -Dtest=JavaHardeningRegressionTest`, 28 tests. Broader check passed: `mvn -pl smojol-toolkit test -Dcheckstyle.skip=true`, 40 tests, 2 skipped. Fixture metrics: `data-structures.cbl` has 16 alias sets, 0 entry constants, 0 exit constants, 0 kills, 0 diagnostics, 19,394-byte pretty-printed sidecar. `constant-folding-phase1.cbl` remains at 0 alias sets and a 5,230-byte pretty-printed sidecar. Target suite wall-clock: 14.059s; broader suite wall-clock: 15.582s. |
| 2026-05-12 | `DONE` | Applied alias sets as conservative kill facts without starting propagation. Direct executable writes now populate per-node `kills` arrays with `ALIAS_CONSERVATIVE_KILL` entries; paragraph/container nodes do not emit duplicate aggregate kills. The checkpoint covers group-child writes, group writes, `REDEFINES` writes, and subscripted `OCCURS` writes. | Targeted check passed: `mvn -pl smojol-toolkit test -Dcheckstyle.skip=true -Dtest=JavaHardeningRegressionTest`, 30 tests. Broader check passed: `mvn -pl smojol-toolkit test -Dcheckstyle.skip=true`, 42 tests, 2 skipped. Fixture metrics: `alias-kills-phase2.cbl` has 10 node states, 9 edges, 4 alias sets, 12 kill facts, 0 entry constants, 0 exit constants, 0 diagnostics, and a 14,449-byte pretty-printed sidecar. `constant-folding-phase1.cbl` remains at 0 alias sets, 0 kills, and a 5,257-byte pretty-printed sidecar. Target suite wall-clock: 13.957s; broader suite wall-clock: 16.618s. |
| 2026-05-14 | `DONE` | Added the first safe propagation solver. It is deliberately narrow: a deterministic fixed-point pass propagates numeric literal `MOVE` facts and folded numeric `COMPUTE` facts, joins branches by keeping only exactly equal constants from every predecessor, applies alias kills before writing new facts, and drops constants for modified variables that do not produce a safe numeric fact. It does not propagate `MOVE WS-A TO WS-C`, does not simplify `IF` or `EVALUATE`, does not infer values from known variables inside expressions, and does not affect dynamic CALL/CICS or RAG behavior. | Targeted check passed: `mvn -pl smojol-toolkit test -Dcheckstyle.skip=true -Dtest=JavaHardeningRegressionTest`, 32 tests. Broader check passed: `mvn -pl smojol-toolkit test -Dcheckstyle.skip=true`, 44 tests, 2 skipped, total time 21.228s. Fixture metrics: `constant-propagation-phase2.cbl` has 17 node states, 16 edges, 24 entry constants, 30 exit constants, 3 kill facts, 0 diagnostics, 1 alias set, 1 paragraph summary, convergence in 2 iterations, and a 26,014-byte pretty-printed sidecar. `constant-folding-phase1.cbl` has 18 node states, 17 edges, 45 entry constants, 52 exit constants, 0 kills, 0 diagnostics, 0 alias sets, 1 paragraph summary, convergence in 2 iterations, and a 38,038-byte pretty-printed sidecar. |
| 2026-05-14 | `DONE` | Added the first runtime/input kill checkpoint without changing CFG node `variablesModified()`. The dataflow sidecar now emits direct kill facts for `ACCEPT` targets parsed from statement text, `CALL USING` arguments in `REFERENCE` mode, and `INITIALIZE` targets from existing node metadata. The transfer step consumes those kills before producing constants, so runtime-overwritten values do not survive into later nodes. `BY CONTENT` and `BY VALUE` call arguments are preserved, and variable-copy propagation remains disabled. | Targeted check passed: `mvn -pl smojol-toolkit test -Dcheckstyle.skip=true -Dtest=JavaHardeningRegressionTest`, 35 tests, total time 14.312s. Broader check passed: `mvn -pl smojol-toolkit test -Dcheckstyle.skip=true`, 47 tests, 2 skipped, total time 14.340s. Fixture metrics: `runtime-kills-phase26a.cbl` has 16 node states, 15 edges, 13 entry constants, 16 exit constants, 3 kill facts, 0 diagnostics, 0 alias sets, 1 paragraph summary, convergence in 2 iterations, and a 16,235-byte pretty-printed sidecar. |
| 2026-05-14 | `DONE` | Added runtime-output kill facts without enabling variable-copy propagation. The dataflow sidecar now emits `READ_INTO_KILL`, `STRING_OUTPUT_KILL`, `UNSTRING_OUTPUT_KILL`, `INSPECT_TARGET_KILL`, `CICS_OUTPUT_KILL`, and `SQL_OUTPUT_KILL` on the relevant CFG nodes. CICS kills are extracted from existing `cics_arguments` metadata; SQL kills are limited to `SELECT`/`FETCH` statements with `INTO` host variables. The exact node-level tests assert that prior constants are present at node entry and absent at node exit. | Targeted check passed: `mvn -pl smojol-toolkit test -Dcheckstyle.skip=true -Dtest=JavaHardeningRegressionTest`, 37 tests, total time 13.650s. Broader check passed: `mvn -pl smojol-toolkit test -Dcheckstyle.skip=true`, 49 tests, 2 skipped, total time 13.875s. Fixture metrics: `output-kills-phase26b.cbl` has 49 node states, 48 edges, 6 entry constants, 6 exit constants, 15 kill facts, 0 diagnostics, 0 alias sets, 1 paragraph summary, convergence in 2 iterations, and a 22,252-byte pretty-printed sidecar. SQL dialect parsing currently emits several CFG dialect nodes for the same SQL statement, so this checkpoint treats the exact source-location node behavior as the contract instead of using aggregate `kill_count` as a correctness assertion. |
| 2026-05-14 | `DONE` | Added safe variable-copy propagation without adding expression inference. `MOVE <known-variable> TO <target>` now copies a proven numeric entry constant into the target when the source survived the earlier kill rules. The implementation uses existing CFG `variablesRead()` and `variablesModified()` evidence rather than changing `assignment_facts`; source text, CFG text, legacy dynamic CALL/CICS fields, and RAG chunks remain unchanged. | Targeted check passed: `mvn -pl smojol-toolkit test -Dcheckstyle.skip=true -Dtest=JavaHardeningRegressionTest`, 37 tests, total time 42.032s. Broader check passed: `mvn -pl smojol-toolkit test -Dcheckstyle.skip=true`, 49 tests, 2 skipped, total time 14.615s. Fixture metrics: `constant-propagation-phase2.cbl` has 17 node states, 16 edges, 33 entry constants, 40 exit constants, 3 kill facts, 0 diagnostics, 1 alias set, 1 paragraph summary, convergence in 2 iterations, and a 32,395-byte pretty-printed sidecar. `runtime-kills-phase26a.cbl` proves `ACCEPT WS-A` removes `WS-A = 10` before `MOVE WS-A TO WS-C`, so no stale `WS-C` constant is emitted after the runtime input. |
| 2026-05-15 | `DONE` | Added safe numeric expression propagation for `COMPUTE` nodes. The sidecar now evaluates only a small arithmetic subset from source text: proven numeric variables from node entry, numeric literals, parentheses, unary signs, addition, subtraction, multiplication, and exact division. The evaluator refuses missing variables, unsupported syntax, divide by zero, and non-terminating division by emitting no constant. No CFG metadata, `assignment_facts`, source text, dynamic CALL/CICS fields, or RAG chunks are changed. | Targeted check passed: `mvn -pl smojol-toolkit test -Dcheckstyle.skip=true -Dtest=JavaHardeningRegressionTest`, 37 tests, total time 13.497s. Broader check passed: `mvn -pl smojol-toolkit test -Dcheckstyle.skip=true`, 49 tests, 2 skipped, total time 14.660s. Fixture metrics: `constant-propagation-phase2.cbl` has 17 node states, 16 edges, 33 entry constants, 40 exit constants, 3 kill facts, 0 diagnostics, 1 alias set, 1 paragraph summary, convergence in 2 iterations, and a 32,401-byte pretty-printed sidecar. `constant-folding-phase1.cbl` now has 56 entry constants and 64 exit constants because `COMPUTE WS-B = WS-A + 1` can use the earlier proven `WS-A = 3`. |
| 2026-05-15 | `DONE` | Added join diagnostics after fixed-point convergence. The solver still drops conflicting constants at joins, but now emits a node-level `DATAFLOW_CONSTANT_DROPPED_AT_JOIN` diagnostic when real CFG predecessors prove different constants for the same variable. This checkpoint also bumps the dataflow analysis version to `1.0` and mode to `join_diagnostics_constant_propagation`. | Targeted check passed: `mvn -pl smojol-toolkit test -Dcheckstyle.skip=true -Dtest=JavaHardeningRegressionTest`, 38 tests, total time 15.119s. Broader check passed: `mvn -pl smojol-toolkit test -Dcheckstyle.skip=true`, 50 tests, 2 skipped, total time 14.806s. Solver-level metrics: the synthetic join test has 3 node states, 2 edges, 1 join diagnostic, `WS-D` absent at join entry, and incoming values `20` and `30` recorded. Fixture metrics remain source-preserving: `constant-propagation-phase2.cbl` has 17 node states, 16 edges, 33 entry constants, 40 exit constants, 3 kill facts, 0 diagnostics, 1 alias set, 1 paragraph summary, convergence in 2 iterations, and a 32,413-byte pretty-printed sidecar. |
| 2026-05-15 | `DONE` | Added loop-carried constant diagnostics for CFG cycles. The solver now detects strongly connected components after fixed-point convergence and emits `DATAFLOW_LOOP_CARRIED_CONSTANT_NOT_INFERRED` when a variable is modified inside a cycle. This is explanatory only: the variable remains absent after the loop unless another safe transfer rule proves it. The dataflow analysis version is now `1.1` and mode is `loop_diagnostics_constant_propagation`. | Targeted check passed: `mvn -pl smojol-toolkit test -Dcheckstyle.skip=true -Dtest=JavaHardeningRegressionTest`, 39 tests, total time 13.351s. Broader check passed: `mvn -pl smojol-toolkit test -Dcheckstyle.skip=true`, 51 tests, 2 skipped, total time 14.507s. Solver-level metrics: the synthetic loop test has 3 node states, 3 edges, 1 loop diagnostic, `WS-A` absent inside and after the loop, `WS-B` not propagated from stale `WS-A`, convergence true, and `max_iterations` 1000 recorded. Fixture metrics remain source-preserving: `constant-propagation-phase2.cbl` has 17 node states, 16 edges, 33 entry constants, 40 exit constants, 3 kill facts, 0 diagnostics, 1 alias set, 1 paragraph summary, convergence in 2 iterations, and a 32,413-byte pretty-printed sidecar. |
| 2026-05-15 | `DONE` | Completed the Phase 2.7 evaluation cleanup. The implementation scope is now described in plain language with examples for literal propagation, variable-copy propagation, expression propagation, runtime kills, joins, loops, and alias kills. The document also records what the tool still does not support, so the project does not overclaim full compiler-style constant propagation. | Documentation-only checkpoint. It reuses the last passed implementation verification: targeted `JavaHardeningRegressionTest`, 39 tests, 13.351s; broader `smojol-toolkit` suite, 51 tests, 2 skipped, 14.507s. Reproducibility commands are listed in Section 20. |

### Phase 3 Checkpoints

| Date | Status | What changed | Verification |
|---|---|---|---|
| 2026-05-15 | `DONE` | Added Phase 3.1a alphanumeric constant propagation as a prerequisite for path-sensitive targets. The sidecar now represents quoted `MOVE` literals as `ALPHANUMERIC` constants, copies proven alphanumeric values through `MOVE <known-var> TO <target>`, and keeps runtime/input/output/alias kills kind-agnostic. It also bumps the dataflow analysis version to `1.2` and mode/status to `alphanumeric_constant_propagation`. No `path_sensitive_call_*` or `path_sensitive_cics_*` fields are emitted yet. | Targeted checks passed: `mvn -pl smojol-core test -Dcheckstyle.skip=true -Dtest=StaticValueTest`, 4 tests; `mvn -pl smojol-core install -Dcheckstyle.skip=true -DskipTests`; `mvn -pl smojol-toolkit test -Dcheckstyle.skip=true -Dtest=JavaHardeningRegressionTest`, 41 tests, total time 15.902s. Broader checks passed: `mvn -pl smojol-core test -Dcheckstyle.skip=true`, 100 tests, total time 5.258s; `mvn -pl smojol-toolkit test -Dcheckstyle.skip=true`, 53 tests, 2 skipped, total time 15.828s. Fixture metrics: `path-sensitive-targets-phase3.cbl` has 13 node states, 12 edges, 17 entry constants, 20 exit constants, 1 kill fact, 0 diagnostics, 0 alias sets, 1 paragraph summary, convergence in 2 iterations, and a 12,731-byte pretty-printed sidecar. |
| 2026-05-18 | `DONE` | Added Phase 3.1b path-sensitive dynamic `CALL` metadata. `WRITE_CFG` now builds `static_analysis/dataflow.json` before serializing the CFG, annotates only dynamic `CALL` nodes from proven alphanumeric entry constants, then writes the CFG and sidecar. The legacy resolver still emits `resolved_call_target`, `call_target_source`, and `dynamic_call_resolution_confidence` unchanged; new facts are strictly additive under the `path_sensitive_call_*` prefix. The dataflow analysis version is now `1.3` with mode/status `path_sensitive_call_targets`. | Targeted check passed: `mvn -pl smojol-toolkit test -Dcheckstyle.skip=true -Dtest=JavaHardeningRegressionTest`, 42 tests, total time 18.071s. Fixture metrics: `path-sensitive-targets-phase3.cbl` has 16 node states, 15 edges, 22 entry constants, 25 exit constants, 1 kill fact, 0 diagnostics, 0 alias sets, 1 paragraph summary, convergence in 2 iterations, a 15,517-byte pretty-printed sidecar, and a 25,392-byte pretty-printed CFG. Exact tests cover two path-sensitive resolved `CALL WS-PGM` nodes and one stale-legacy-but-path-sensitive-unresolved `CALL WS-KILLED` node. |
| 2026-05-18 | `DONE` | Added Phase 3.2a path-sensitive CICS target metadata. The same additive resolver now annotates CICS dialect nodes whose target identifier has a proven alphanumeric constant at node entry. It emits top-level `path_sensitive_cics_*` fields only; legacy `resolved_cics_target`, `cics_target_source`, `cics_dynamic_resolution_confidence`, nested `cics_operation`, and existing `cics_arguments` remain compatibility fields. The dataflow analysis version is now `1.4` with mode/status `path_sensitive_cics_targets`. | Targeted check passed: `mvn -pl smojol-toolkit test -Dcheckstyle.skip=true -Dtest=JavaHardeningRegressionTest`, 44 tests, total time 17.871s. Broader check passed: `mvn -pl smojol-toolkit test -Dcheckstyle.skip=true`, 56 tests, 2 skipped, total time 18.124s. Fixture metrics: `path-sensitive-targets-phase3.cbl` has 29 node states, 28 edges, 33 entry constants, 38 exit constants, 2 kill facts, 0 diagnostics, 0 alias sets, 1 paragraph summary, convergence in 2 iterations, a 23,746-byte pretty-printed sidecar, and a 55,569-byte pretty-printed CFG. Exact tests cover two CICS `LINK PROGRAM(WS-CICS-PGM)` nodes resolving to `CICSA` and `CICSB`, plus one `ACCEPT`-killed `WS-CICS-KILLED` node where legacy still reports `CICSKILL` but path-sensitive CICS metadata is unresolved. |

### Fool-Proof Execution Rules

1. Do not start a later step while an earlier required safety step is `PENDING` or `BLOCKED`.
2. Do not mark a step `DONE` unless its acceptance check is covered by an exact test, committed artifact, or measured report.
3. Do not silently expand scope. New supported COBOL constructs require this document to be updated first.
4. Do not silently drop scope. Skipped work must be marked `SKIPPED` with a reason.
5. Do not merge implementation if this ledger says `WORKING`, `PENDING`, or `BLOCKED` for the same deliverable.
6. Do not claim full production-ready constant propagation until `static_analysis/dataflow.json`, fixed-point CFG propagation, conservative merge rules, loop handling, alias kills, and runtime-input kill rules are all `DONE`. Until then, describe the current solver as a scoped checkpoint and list its exact supported transfer rules.
7. Do not claim dynamic CALL/CICS improvement until path-sensitive fields and accuracy measurements are `DONE`.
8. Do not claim RAG improvement until retrieval and token metrics are `DONE`.

### Phase 1: Local Closed Numeric COMPUTE Folding

Phase 1 includes:

- Java 21 sealed `StaticValue` model.
- `BigDecimal`-only numeric arithmetic.
- ANTLR arithmetic expression traversal.
- `folded_value_facts` in `ComputeFlowNode.metadata()`.
- `folding_diagnostics` for unsupported or unsafe `COMPUTE` expressions.
- No source rewriting.
- No CFG rewriting.
- No propagation.
- No RAG changes.

### Phase 2: CFG-Based Constant Propagation

Phase 2 now has a committed sidecar with paragraph summaries, conservative alias-set summaries, conservative alias kill facts, a first narrow propagation solver, runtime/input/output kill facts, variable-copy propagation, expression propagation, join diagnostics, and loop-carried constant diagnostics. This is not full COBOL constant propagation. It is a safe checkpoint that proves the artifact can carry node entry/exit constants, remove stale runtime-overwritten constants, and explain some conservative drops without changing CFG text, `assignment_facts`, dynamic CALL/CICS behavior, or RAG chunks.

The current Phase 2.6f solver supports only these value-producing rules:

- `MOVE <numeric-literal> TO <variable>` produces a numeric constant for the target.
- `MOVE <known-variable> TO <variable>` copies the source numeric constant from the node entry state when the source survived all kill rules.
- A folded numeric `COMPUTE` fact from Phase 1 produces a numeric constant for the target.
- `COMPUTE <target> = <numeric-expression>` can produce a target constant when the expression contains only proven numeric entry constants, numeric literals, parentheses, unary signs, `+`, `-`, `*`, and exact `/`.
- Any modified variable that does not produce one of those safe constants is removed from the exit state.
- Alias kills from Phase 2.4 are applied before the node writes new constants.
- A join keeps a constant only when every predecessor exit has the same JSON value for that variable.
- When a real multi-predecessor join drops a constant because predecessor paths prove different values, the join node receives a `DATAFLOW_CONSTANT_DROPPED_AT_JOIN` diagnostic with predecessor IDs and incoming values.
- When a variable is modified inside a CFG cycle, the modifying node receives a `DATAFLOW_LOOP_CARRIED_CONSTANT_NOT_INFERRED` diagnostic. The solver does not infer final loop values.

Phase 2.6a adds these kill rules:

- `ACCEPT <identifier>` emits `RUNTIME_INPUT_KILL` for the accepted target.
- `CALL ... USING <identifier>` and `CALL ... USING BY REFERENCE <identifier>` emit `CALL_USING_REFERENCE_KILL`.
- `CALL ... USING BY CONTENT <identifier>` and `CALL ... USING BY VALUE <identifier>` do not kill the caller variable.
- `INITIALIZE <identifier>` emits `INITIALIZE_TARGET_KILL`.

Phase 2.6b adds these kill rules:

- `READ <file> INTO <identifier>` emits `READ_INTO_KILL`.
- `STRING ... INTO <identifier>` emits `STRING_OUTPUT_KILL`.
- `UNSTRING ... INTO <identifier>` emits `UNSTRING_OUTPUT_KILL`.
- `INSPECT <identifier> ...` emits `INSPECT_TARGET_KILL`.
- `EXEC CICS ... INTO(<identifier>)` and other known CICS output arguments emit `CICS_OUTPUT_KILL`.
- `EXEC SQL SELECT/FETCH ... INTO :<host-variable>` emits `SQL_OUTPUT_KILL`.

The current solver intentionally does not support function calls, string expressions, subscripts, reference modification, `ROUNDED`, size-error semantics, target PIC truncation/storage semantics, condition simplification, branch reachability pruning, interprocedural summaries, dynamic CALL/CICS path-sensitive fields, or RAG chunk generation.

Join diagnostics are deliberately narrow in Phase 2.6e. They describe a real dataflow merge where a node has at least two CFG predecessors and every predecessor proves the same variable to a different constant. They do not yet repair or reinterpret CFG shapes where branch bodies are nested under an `IF_BRANCH` node but are not direct predecessors of the following statement. In that shape, the current solver still behaves conservatively by not carrying the branch-local value forward.

Use-case example for the join diagnostic:

```cobol
MOVE 20 TO WS-D
    *> predecessor path A
MOVE 30 TO WS-D
    *> predecessor path B
CONTINUE
    *> real CFG join of path A and path B
```

At the `CONTINUE` join, `WS-D` is not present in `entry_constants` because the two incoming paths disagree. The sidecar now explains the loss with `DATAFLOW_CONSTANT_DROPPED_AT_JOIN` and records both incoming values, `20` and `30`. This is intentionally more honest than emitting either value, and more useful than silently dropping the fact.

Loop diagnostics are also narrow in Phase 2.6f. They explain a real CFG cycle and a variable modified inside that cycle; they do not compute trip counts, final loop values, `PERFORM VARYING` bounds, or `UNTIL` reachability. For example:

```cobol
MOVE 1 TO WS-A
PERFORM UNTIL WS-A > 5
    ADD 1 TO WS-A
END-PERFORM
MOVE WS-A TO WS-B
```

The analyzer should not claim `WS-A = 6` unless it implements full COBOL loop semantics. The current safe behavior is to keep `WS-A` absent after the loop-carried modification, not propagate `WS-B` from stale `WS-A`, and emit `DATAFLOW_LOOP_CARRIED_CONSTANT_NOT_INFERRED` on the loop modification evidence.

Representative Phase 2.6f artifact shape, shortened from fixture outputs and solver-level tests. The paragraph-summary, alias-summary, kill, propagated-constant, join-diagnostic, and loop-diagnostic examples may come from different checks because the checkpoints verify these shapes independently.

```json
{
  "program": "<program>.cbl",
  "schema_version": "1.0",
  "analysis": "static_value_dataflow",
  "analysis_version": "1.1",
  "status": "loop_diagnostics_constant_propagation",
  "config": {
    "constant_propagation_enabled": true,
    "path_sensitive_targets_enabled": false,
    "paragraph_summaries_enabled": true,
    "alias_analysis_enabled": true,
    "alias_kills_enabled": true,
    "mode": "loop_diagnostics_constant_propagation",
    "max_iterations": 1000
  },
  "summary": {
    "node_count": 17,
    "edge_count": 16,
    "entry_constant_count": 24,
    "exit_constant_count": 30,
    "kill_count": 3,
    "diagnostic_count": 0,
    "alias_set_count": 1,
    "paragraph_summary_count": 1,
    "iteration_count": 2,
    "max_iterations": 1000,
    "converged": true
  },
  "node_states": {
    "<cfg_node_id>": {
      "entry_constants": {
        "WS-A": {
          "state": "CONSTANT",
          "kind": "NUMERIC",
          "raw_lexeme": "10",
          "normalized_value": "10",
          "display_value": "10",
          "numeric": {
            "decimal": "10",
            "scale": 0,
            "precision": 2,
            "sign": "POSITIVE"
          }
        }
      },
      "exit_constants": {
        "WS-A": {
          "state": "CONSTANT",
          "kind": "NUMERIC",
          "raw_lexeme": "10",
          "normalized_value": "10",
          "display_value": "10",
          "numeric": {
            "decimal": "10",
            "scale": 0,
            "precision": 2,
            "sign": "POSITIVE"
          }
        },
        "WS-B": {
          "state": "CONSTANT",
          "kind": "NUMERIC",
          "raw_lexeme": "3",
          "normalized_value": "3",
          "display_value": "3",
          "numeric": {
            "decimal": "3",
            "scale": 0,
            "precision": 1,
            "sign": "POSITIVE"
          }
        }
      },
      "kills": [
        {
          "code": "RUNTIME_INPUT_KILL",
          "variable": "WS-A",
          "reason": "runtime_accept",
          "kill_scope": "direct_variable",
          "confidence": "conservative",
          "statement_type": "ACCEPT",
          "statement_text": "ACCEPT WS-A FROM DATE",
          "source_line": 14,
          "source_column": 11,
          "provenance_source": "java_static_value_dataflow"
        }
      ],
      "diagnostics": [
        {
          "code": "DATAFLOW_CONSTANT_DROPPED_AT_JOIN",
          "severity": "info",
          "category": "merge",
          "variable": "WS-D",
          "reason": "conflicting_predecessor_constants",
          "predecessor_node_ids": ["<move_20_node_id>", "<move_30_node_id>"],
          "incoming_values": [
            {
              "predecessor_node_id": "<move_20_node_id>",
              "present": true,
              "state": "CONSTANT",
              "kind": "NUMERIC",
              "normalized_value": "20",
              "display_value": "20"
            },
            {
              "predecessor_node_id": "<move_30_node_id>",
              "present": true,
              "state": "CONSTANT",
              "kind": "NUMERIC",
              "normalized_value": "30",
              "display_value": "30"
            }
          ],
          "message": "Constant for WS-D was dropped at CFG join because predecessor paths prove different values.",
          "provenance_source": "java_static_value_dataflow"
        },
        {
          "code": "DATAFLOW_LOOP_CARRIED_CONSTANT_NOT_INFERRED",
          "severity": "info",
          "category": "loop",
          "variable": "WS-A",
          "reason": "modified_inside_cfg_cycle",
          "component_node_ids": ["<add_in_loop_node_id>"],
          "statement_type": "ADD",
          "statement_text": "ADD 1 TO WS-A",
          "message": "Loop-carried constant for WS-A is not inferred because the variable is modified inside a CFG cycle.",
          "provenance_source": "java_static_value_dataflow"
        }
      ]
    }
  },
  "alias_sets": {
    "redefines:SOMETEXT": {
      "alias_set_id": "redefines:SOMETEXT",
      "alias_kind": "REDEFINES_OVERLAP",
      "base_variable": "SOMETEXT",
      "members": ["NUMERIC-SOMETEXT", "REDEF-SOMETEXT", "SOMETEXT"],
      "kill_scope": "all_overlapping_members",
      "confidence": "conservative",
      "layout": {
        "layout_source": "java_data_structure_layout"
      },
      "evidence": [
        {
          "variable": "SOMETEXT",
          "alias_kind": "REDEFINES_OVERLAP",
          "level_number": 1,
          "data_type": "NUMBER",
          "source_line": 24
        }
      ],
      "summary_source": "java_static_value_dataflow"
    }
  },
  "paragraph_summaries": {
    "MAIN-PARA": {
      "paragraph": "MAIN-PARA",
      "paragraph_node_id": "<cfg_paragraph_node_id>",
      "node_ids": ["<contained_cfg_node_id>"],
      "variables_read_direct": ["WS-A"],
      "variables_modified_direct": ["WS-A", "WS-B"],
      "variables_read_transitive": ["WS-A"],
      "variables_modified_transitive": ["WS-A", "WS-B"],
      "calls_paragraphs": [],
      "called_programs": [],
      "external_side_effects": [],
      "unsupported_constructs": [],
      "cycle_detected": false,
      "transitive_summary_status": "complete_no_paragraph_calls",
      "summary_source": "java_static_value_dataflow"
    }
  },
  "diagnostics": []
}
```

For paragraphs that `PERFORM` another paragraph, Phase 2.2 does not compute a transitive closure yet. In that case `variables_read_transitive` and `variables_modified_transitive` stay empty, `transitive_summary_status` is `not_computed_perform_targets_present`, and `unsupported_constructs` contains a machine-readable `PARAGRAPH_TRANSITIVE_SUMMARY_NOT_COMPUTED` entry. This is deliberate: the analyzer records the risk instead of pretending the transitive summary is complete.

Alias sets are analysis facts. Phase 2.4 emits kill facts from them, and Phase 2.5 now uses those kills to remove stale constants before writing new facts.

- `GROUP_CHILD_STORAGE`: writing a group or child may invalidate the group and its descendants.
- `OCCURS_STORAGE`: writing a table or indexed occurrence may invalidate all occurrences and descendants.
- `REDEFINES_OVERLAP`: writing any redefined view may invalidate all overlapping members.

The Phase 2.3/2.4 builder is syntax-derived and deterministic. It intentionally does not yet use byte-offset/byte-size layout evidence because the existing expanded table/redefinition model can recurse through layout sizing on `data-structures.cbl`; using names, parent relationships, `REDEFINES`, and `OCCURS` clauses is the reliable checkpoint. Offset-based overlap refinement remains future work.

Deferred beyond the current Phase 2 checkpoint:

- Interprocedural paragraph/call summaries beyond direct `CALL USING` reference kills.
- Broader transfer rules beyond the current narrow numeric subset.
- More join diagnostics, including constants lost because one predecessor lacks a binding.
- More loop diagnostics for real COBOL `PERFORM VARYING`/`PERFORM UNTIL` CFG shapes and explicit max-iteration limit tests.

### Phase 3: Path-Sensitive Dynamic CALL/CICS Resolution

Phase 3 uses the constants proven in `static_analysis/dataflow.json` to add path-sensitive target facts beside the legacy dynamic `CALL` and CICS fields. It must not replace the old resolver. The legacy resolver in `SerialisableCFGGraphCollector.annotateDynamicCallResolution()` is order-based and writes fields such as `resolved_call_target`, `call_target_source`, `dynamic_call_resolution_confidence`, `resolved_cics_target`, `cics_target_source`, and `cics_dynamic_resolution_confidence`. Phase 3 adds new fields with a `path_sensitive_` prefix so downstream consumers can compare both views during a dual-emission window.

The plan is deliberately split into small checkpoints because dynamic target resolution is user-visible and easy to overclaim.

#### Phase 3 Invariants

- Existing COBOL source text remains unchanged.
- Existing CFG text, node IDs, edge IDs, and edge structure remain unchanged.
- Existing `assignment_facts` remain unchanged.
- Existing legacy dynamic `CALL` fields remain unchanged:
  - `resolved_call_target`
  - `call_target_source`
  - `dynamic_call_resolution_confidence`
  - `dynamic_call_resolution_note`
  - `call_target_identifier`
- Existing legacy CICS fields remain unchanged:
  - `resolved_cics_target`
  - `cics_target_source`
  - `cics_dynamic_resolution_confidence`
  - `cics_dynamic_resolution_note`
  - `cics_target_identifier`
  - `cics_operation`
  - `cics_arguments`
- New facts are additive and start with `path_sensitive_`.
- A path-sensitive fact may only be emitted from a `CONSTANT` value in the target node's dataflow `entry_constants`.
- If a runtime kill, alias kill, branch merge, or loop cycle removes the constant before the target node, the path-sensitive target must be unresolved.
- No RAG chunk changes are allowed in Phase 3.
- No dependency-chunk behavior changes are allowed in Phase 3.

#### Why Alphanumeric Dataflow Is A Phase 3 Prerequisite

Phase 2 intentionally focused on numeric constants. Dynamic program names and CICS resource names are usually alphanumeric:

```cobol
MOVE "SUBPROG" TO WS-PGM
CALL WS-PGM

MOVE "CUSTOMERQ" TO WS-QUEUE
EXEC CICS READQ TS QUEUE(WS-QUEUE) INTO(WS-AREA)
```

Without an `ALPHANUMERIC` constant in `entry_constants`, Phase 3 would have to fall back to the old order-based literal scan. That would defeat the purpose of path-sensitive resolution. Therefore Phase 3.1a first adds a narrow alphanumeric transfer rule:

- `MOVE "literal" TO VAR` produces a `CONSTANT` with `kind: "ALPHANUMERIC"`.
- `MOVE 'literal' TO VAR` behaves the same.
- `MOVE KNOWN-ALPHANUMERIC-VAR TO OTHER-VAR` copies the proven alphanumeric value.
- Existing runtime/input/output kills remove alphanumeric constants the same way they remove numeric constants.
- Branch joins keep alphanumeric constants only when all predecessors prove the exact same normalized value.
- Loop diagnostics and alias kills still apply.
- No string expression folding, concatenation, `STRING`, `UNSTRING`, reference modification, or figurative constant expansion is added in Phase 3.1a.

Planned alphanumeric JSON payload:

```json
{
  "state": "CONSTANT",
  "kind": "ALPHANUMERIC",
  "raw_lexeme": "\"SUBPROG\"",
  "normalized_value": "SUBPROG",
  "display_value": "SUBPROG"
}
```

`ConstantStaticValue.toJsonMap()` still has nullable payload slots internally, but the current Gson writer omits null map values in emitted artifacts. The committed `dataflow.json` shape therefore omits `numeric`, `figurative`, and `type_context` for alphanumeric constants.

Normalization rule for Phase 3.1a: strip one matching pair of single or double quotes and uppercase the value for target resolution. Preserve the unquoted value in `display_value`. COBOL-specific quote escaping, national literals, hex literals, figurative constants, and case-sensitive external names remain out of scope until tested.

#### Phase 3.1a: Alphanumeric Constant Dataflow

Files expected to change:

- `smojol-core/src/main/java/org/smojol/common/staticanalysis/value/ConstantStaticValue.java`
- `smojol-toolkit/src/main/java/org/smojol/toolkit/analysis/staticvalue/StaticValueDataflowPass.java`
- `smojol-toolkit/src/test/java/org/smojol/toolkit/analysis/task/JavaHardeningRegressionTest.java`
- A new fixture, likely `smojol-toolkit/test-code/flow-ast/path-sensitive-targets-phase3.cbl`
- This document and `workDone.md`

Implementation rules:

1. Add a helper such as `ConstantStaticValue.alphanumeric(String rawLexeme, String normalizedValue)`.
2. Teach the dataflow transfer step to produce alphanumeric constants from quoted literal `MOVE` assignment facts.
3. Broaden variable-copy propagation from numeric-only constants to any `CONSTANT` with supported kind `NUMERIC` or `ALPHANUMERIC`.
4. Keep arithmetic `COMPUTE` propagation numeric-only.
5. Keep runtime/input/output kills kind-agnostic; killed variables disappear regardless of whether the value was numeric or alphanumeric.
6. Keep joins exact: two alphanumeric constants merge only if `state`, `kind`, `normalized_value`, and `display_value` match.

Acceptance tests:

- `MOVE "PROG-A" TO WS-PGM` gives `WS-PGM` an `ALPHANUMERIC` exit constant with `normalized_value: "PROG-A"`.
- `MOVE WS-PGM TO WS-COPY` copies the alphanumeric constant only when `WS-PGM` is present at entry.
- `ACCEPT WS-PGM` kills the alphanumeric constant.
- Conflicting branch values such as `"PROG-A"` and `"PROG-B"` are dropped at a real join.
- Existing numeric propagation tests still pass unchanged.

Committed Phase 3.1a example:

```cobol
MOVE "PROG-A" TO WS-PGM
CALL WS-PGM
MOVE WS-PGM TO WS-COPY
MOVE 'PROG-C' TO WS-SINGLE
MOVE "PROG-D" TO WS-KILLED
ACCEPT WS-KILLED
MOVE WS-KILLED TO WS-AFTER-KILL
```

Expected and tested behavior:

- `MOVE "PROG-A" TO WS-PGM` emits `WS-PGM` as an `ALPHANUMERIC` exit constant.
- `CALL WS-PGM` sees `WS-PGM = "PROG-A"` in `entry_constants`, but no `path_sensitive_call_target` is emitted yet.
- `MOVE WS-PGM TO WS-COPY` copies the proven alphanumeric constant.
- Single-quoted `MOVE 'PROG-C' TO WS-SINGLE` produces the same kind of alphanumeric fact.
- `ACCEPT WS-KILLED` removes the prior `WS-KILLED = "PROG-D"` fact.
- `MOVE WS-KILLED TO WS-AFTER-KILL` does not emit a stale `WS-AFTER-KILL` constant after the runtime kill.

#### Phase 3.1b: Path-Sensitive Dynamic CALL Facts

Current legacy input:

- `CallFlowNode.metadata()` emits:
  - `call_target`
  - `program_reference_type`
  - `dynamic_call`
  - `using_parameters`
- `SerialisableCFGGraphCollector.annotateDynamicCallResolution()` currently annotates:
  - static calls with `resolved_call_target`, `call_target_source: "literal"`, confidence `high`
  - dynamic calls with `call_target_identifier`
  - dynamic calls resolved from the latest prior literal assignment with confidence `medium`
  - unresolved dynamic calls with the identifier itself and confidence `low`

Phase 3.1b does not change that behavior. It adds a second view.

Implemented fields on dynamic `CALL` node metadata:

```json
{
  "path_sensitive_call_resolution_status": "resolved",
  "path_sensitive_call_target": "PROG-A",
  "path_sensitive_call_target_identifier": "WS-PGM",
  "path_sensitive_call_target_source": "static_analysis.dataflow.entry_constants",
  "path_sensitive_call_confidence": "high",
  "path_sensitive_call_evidence": {
    "node_id": "node-123",
    "entry_variable": "WS-PGM",
    "value_state": "CONSTANT",
    "value_kind": "ALPHANUMERIC",
    "dataflow_artifact": "static_analysis/dataflow.json"
  }
}
```

Unresolved dynamic calls should be explicit but compact:

```json
{
  "path_sensitive_call_resolution_status": "unresolved",
  "path_sensitive_call_target_identifier": "WS-PGM",
  "path_sensitive_call_target_source": "static_analysis.dataflow.entry_constants",
  "path_sensitive_call_confidence": "none",
  "path_sensitive_call_resolution_note": "No proven alphanumeric constant for WS-PGM at CALL node entry."
}
```

Implemented shape:

1. Build the dataflow result before serializing the CFG JSON in `WriteControlFlowGraphTask`.
2. Run a new additive resolver over `cfgGraphCollector.nodes()` and the dataflow result.
3. Only after the additive resolver runs, serialize the CFG JSON and then serialize the dataflow sidecar.
4. Keep `DataflowAnalysisResult.config.path_sensitive_targets_enabled` set to `true` once the resolver is active.
5. Do not call `annotateCallResolution()` from the path-sensitive resolver, because that method writes legacy fields.

Implemented class:

```text
smojol-toolkit/src/main/java/org/smojol/toolkit/analysis/staticvalue/PathSensitiveTargetResolver.java
```

Implemented API:

```text
void annotateTargets(List<SerialisableCFGFlowNode> nodes, DataflowAnalysisResult dataflow)
```

Resolution algorithm:

1. Build `node_id -> DataflowNodeState`.
2. For every node of type `CALL` where `metadata.dynamic_call == true`:
   - Determine identifier from `call_target_identifier` if present, else `call_target`.
   - Canonicalize the identifier with the same rule used by `StaticValueDataflowPass`.
   - Look up that identifier in the node state's `entry_constants`.
   - If the value is `state: CONSTANT` and `kind: ALPHANUMERIC`, emit resolved `path_sensitive_call_*` fields.
   - Otherwise emit unresolved `path_sensitive_call_*` fields.
3. Do nothing for static calls except preserve legacy fields.

Committed Phase 3.1b example:

```cobol
MOVE "PROG-A" TO WS-PGM
CALL WS-PGM
MOVE "PROG-B" TO WS-PGM
CALL WS-PGM
MOVE WS-PGM TO WS-COPY
MOVE 'PROG-C' TO WS-SINGLE
MOVE "PROG-D" TO WS-KILLED
ACCEPT WS-KILLED
CALL WS-KILLED
MOVE WS-KILLED TO WS-AFTER-KILL
```

The first dynamic call keeps the legacy medium-confidence fields and adds the path-sensitive high-confidence view:

```json
{
  "call_target": "WS-PGM",
  "program_reference_type": "DYNAMIC",
  "dynamic_call": true,
  "call_target_identifier": "WS-PGM",
  "resolved_call_target": "PROG-A",
  "call_target_source": "inferred_literal_assignment",
  "dynamic_call_resolution_confidence": "medium",
  "path_sensitive_call_resolution_status": "resolved",
  "path_sensitive_call_target": "PROG-A",
  "path_sensitive_call_target_identifier": "WS-PGM",
  "path_sensitive_call_target_source": "static_analysis.dataflow.entry_constants",
  "path_sensitive_call_confidence": "high",
  "path_sensitive_call_evidence": {
    "entry_variable": "WS-PGM",
    "value_state": "CONSTANT",
    "value_kind": "ALPHANUMERIC",
    "dataflow_artifact": "static_analysis/dataflow.json"
  }
}
```

The second `CALL WS-PGM` sees the later `MOVE "PROG-B" TO WS-PGM` in its dataflow entry state and emits `path_sensitive_call_target: "PROG-B"`. This proves the new resolver reads per-node entry constants rather than one global latest assignment.

The killed-target example is intentionally different from the legacy result. After `MOVE "PROG-D" TO WS-KILLED`, `ACCEPT WS-KILLED` removes the proven entry constant before `CALL WS-KILLED`. The old order-based resolver still reports `resolved_call_target: "PROG-D"` with `call_target_source: "inferred_literal_assignment"` and confidence `medium`; the new path-sensitive view reports:

```json
{
  "path_sensitive_call_resolution_status": "unresolved",
  "path_sensitive_call_target_identifier": "WS-KILLED",
  "path_sensitive_call_target_source": "static_analysis.dataflow.entry_constants",
  "path_sensitive_call_confidence": "none",
  "path_sensitive_call_resolution_note": "No proven alphanumeric constant for WS-KILLED at CALL node entry."
}
```

This is the safety property for Phase 3.1b: path-sensitive metadata may disagree with legacy metadata when dataflow proves the legacy global assignment is stale, but it does so only in additive fields. No old `CALL` metadata key is removed or rewritten.

#### Phase 3.2a: Path-Sensitive CICS Target Facts

Current legacy input:

- `DialectMetadataParser` emits CICS metadata such as:
  - `cics_command`
  - `cics_target_kind`
  - `cics_target`
  - `cics_target_source`
  - `cics_arguments`
  - `cics_operation`
- `SerialisableCFGGraphCollector.annotateCicsResolution()` currently mutates legacy fields such as:
  - `resolved_cics_target`
  - `cics_target_source`
  - `cics_dynamic_resolution_confidence`
  - nested `cics_operation.target`
  - nested `cics_arguments[*].resolved_value` for selected identifier arguments

Phase 3.2a leaves those legacy fields unchanged and adds top-level path-sensitive fields.

Implemented top-level metadata fields:

```json
{
  "path_sensitive_cics_resolution_status": "resolved",
  "path_sensitive_cics_target": "PAYPGM",
  "path_sensitive_cics_target_identifier": "WS-CICS-PGM",
  "path_sensitive_cics_target_kind": "PROGRAM",
  "path_sensitive_cics_target_source": "static_analysis.dataflow.entry_constants",
  "path_sensitive_cics_confidence": "high",
  "path_sensitive_cics_evidence": {
    "node_id": "node-456",
    "entry_variable": "WS-CICS-PGM",
    "value_state": "CONSTANT",
    "value_kind": "ALPHANUMERIC",
    "target_kind": "PROGRAM",
    "dataflow_artifact": "static_analysis/dataflow.json"
  }
}
```

Unresolved CICS identifier target:

```json
{
  "path_sensitive_cics_resolution_status": "unresolved",
  "path_sensitive_cics_target_identifier": "WS-CICS-PGM",
  "path_sensitive_cics_target_kind": "PROGRAM",
  "path_sensitive_cics_target_source": "static_analysis.dataflow.entry_constants",
  "path_sensitive_cics_confidence": "none",
  "path_sensitive_cics_resolution_note": "No proven alphanumeric constant for WS-CICS-PGM at CICS node entry."
}
```

Committed test fixture:

```cobol
MOVE "CICSA" TO WS-CICS-PGM
EXEC CICS LINK PROGRAM(WS-CICS-PGM)
     COMMAREA(WS-COPY)
END-EXEC
MOVE "CICSB" TO WS-CICS-PGM
EXEC CICS LINK PROGRAM(WS-CICS-PGM)
     COMMAREA(WS-COPY)
END-EXEC
```

Expected:

- The first CICS `LINK` emits `path_sensitive_cics_target: "CICSA"`.
- The second CICS `LINK` emits `path_sensitive_cics_target: "CICSB"`.
- `path_sensitive_cics_target_identifier: "WS-CICS-PGM"`
- `path_sensitive_cics_target_kind: "PROGRAM"`
- Legacy `resolved_cics_target`, `cics_target_source`, and `cics_dynamic_resolution_confidence` remain unchanged.

The fixture includes `COMMAREA(WS-COPY)` because the existing accepted parser shape for CICS `LINK` in this codebase includes a `COMMAREA` argument. This keeps the test focused on path-sensitive target resolution rather than dialect grammar expansion.

Runtime-kill negative case:

```cobol
MOVE "CICSKILL" TO WS-CICS-KILLED
ACCEPT WS-CICS-KILLED
EXEC CICS LINK PROGRAM(WS-CICS-KILLED)
     COMMAREA(WS-COPY)
END-EXEC
```

Expected:

- CICS node is unresolved path-sensitively.
- No stale `CICSKILL` path-sensitive target is emitted.
- Legacy CICS metadata still reports `resolved_cics_target: "CICSKILL"` with `cics_target_source: "inferred_literal_assignment"` and `cics_dynamic_resolution_confidence: "medium"`; the new path-sensitive fields are the safer dataflow-based view.

Representative resolved metadata:

```json
{
  "resolved_cics_target": "CICSA",
  "cics_target_source": "inferred_literal_assignment",
  "cics_dynamic_resolution_confidence": "medium",
  "path_sensitive_cics_resolution_status": "resolved",
  "path_sensitive_cics_target": "CICSA",
  "path_sensitive_cics_target_identifier": "WS-CICS-PGM",
  "path_sensitive_cics_target_kind": "PROGRAM",
  "path_sensitive_cics_target_source": "static_analysis.dataflow.entry_constants",
  "path_sensitive_cics_confidence": "high",
  "path_sensitive_cics_evidence": {
    "node_id": "node-456",
    "entry_variable": "WS-CICS-PGM",
    "value_state": "CONSTANT",
    "value_kind": "ALPHANUMERIC",
    "target_kind": "PROGRAM",
    "dataflow_artifact": "static_analysis/dataflow.json"
  }
}
```

Representative killed-target metadata:

```json
{
  "resolved_cics_target": "CICSKILL",
  "cics_target_source": "inferred_literal_assignment",
  "cics_dynamic_resolution_confidence": "medium",
  "path_sensitive_cics_resolution_status": "unresolved",
  "path_sensitive_cics_target_identifier": "WS-CICS-KILLED",
  "path_sensitive_cics_target_kind": "PROGRAM",
  "path_sensitive_cics_target_source": "static_analysis.dataflow.entry_constants",
  "path_sensitive_cics_confidence": "none",
  "path_sensitive_cics_resolution_note": "No proven alphanumeric constant for WS-CICS-KILLED at CICS node entry."
}
```

#### Phase 3.2b: Path-Sensitive CICS Argument Facts

CICS statements can contain more than one identifier argument. Mutating legacy `cics_arguments` would make compatibility harder, so Phase 3.2b adds a separate array.

Planned field:

```json
{
  "path_sensitive_cics_arguments": [
    {
      "name": "QUEUE",
      "identifier": "WS-QUEUE",
      "resolved_value": "CUSTOMERQ",
      "value_kind": "ALPHANUMERIC",
      "source": "static_analysis.dataflow.entry_constants",
      "confidence": "high"
    }
  ]
}
```

Supported argument names in the first checkpoint:

- `PROGRAM`
- `FILE`
- `DATASET`
- `QUEUE`
- `QNAME`
- `MAP`
- `MAPSET`
- `TRANSID`

Required test:

```cobol
MOVE "CUSTOMERQ" TO WS-QUEUE
EXEC CICS READQ TS QUEUE(WS-QUEUE) INTO(WS-AREA)
```

Expected:

- `path_sensitive_cics_arguments[0].name: "QUEUE"`
- `path_sensitive_cics_arguments[0].identifier: "WS-QUEUE"`
- `path_sensitive_cics_arguments[0].resolved_value: "CUSTOMERQ"`
- Existing `cics_arguments` array remains byte-for-byte equivalent except for unrelated pre-existing legacy fields.

#### Phase 3.3: Accuracy And Performance Evaluation

Phase 3.3 is the first point where the project may claim improved dynamic target resolution. The evaluation must be explicit.

Metrics to record:

- Number of dynamic `CALL` nodes.
- Number of legacy-resolved dynamic `CALL` nodes.
- Number of path-sensitive-resolved dynamic `CALL` nodes.
- Number of path-sensitive unresolved dynamic `CALL` nodes.
- Number of CICS identifier target nodes.
- Number of path-sensitive-resolved CICS target nodes.
- Number of CICS identifier arguments.
- Number of path-sensitive-resolved CICS arguments.
- Count of cases where legacy and path-sensitive target disagree.
- Count of cases where path-sensitive resolution refuses a stale value after a kill.
- CFG JSON byte delta.
- `static_analysis/dataflow.json` byte delta.
- Targeted Java test runtime.
- Broader `smojol-toolkit` test runtime.

Minimum acceptance criteria:

- Every expected dynamic `CALL` in the Phase 3 fixture has the exact expected `path_sensitive_call_*` result.
- Every expected CICS identifier target/argument in the Phase 3 fixture has the exact expected `path_sensitive_cics_*` result.
- At least one negative runtime-kill case proves no stale path-sensitive target is emitted.
- Existing Stage 1 legacy dynamic `CALL` and CICS tests still pass without changing their expected legacy values.
- Existing Phase 2 dataflow tests still pass.
- No RAG chunk tests are changed in Phase 3.
- No dependency chunk output is changed in Phase 3.
- `path_sensitive_targets_enabled` is `true` only after the path-sensitive annotator is active.

#### Phase 3 Fixture Sketch

The likely fixture is `smojol-toolkit/test-code/flow-ast/path-sensitive-targets-phase3.cbl`:

```cobol
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PTHSENS.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-PGM       PIC X(8).
       01 WS-CICS-PGM  PIC X(8).
       01 WS-QUEUE     PIC X(8).
       01 WS-AREA      PIC X(20).
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE "PROG-A" TO WS-PGM
           CALL WS-PGM
           MOVE "PROG-B" TO WS-PGM
           CALL WS-PGM
           MOVE "PROG-C" TO WS-PGM
           ACCEPT WS-PGM
           CALL WS-PGM
           MOVE "PAYPGM" TO WS-CICS-PGM
           EXEC CICS LINK PROGRAM(WS-CICS-PGM)
           MOVE "CUSTOMERQ" TO WS-QUEUE
           EXEC CICS READQ TS QUEUE(WS-QUEUE) INTO(WS-AREA)
           GOBACK.
```

This fixture intentionally includes:

- Two dynamic calls with the same identifier but different proven entry constants.
- One dynamic call after runtime input, which must be unresolved path-sensitively.
- One CICS program transfer target.
- One CICS queue argument.
- A CICS `INTO` output argument that must still behave as a kill, not as a target.

#### Phase 3 Stop Points

Each checkpoint should be committed separately and stop for user approval:

1. `3.1a`: alphanumeric dataflow constants only.
2. `3.1b`: path-sensitive dynamic `CALL` fields only.
3. `3.2a`: path-sensitive CICS top-level target fields only.
4. `3.2b`: path-sensitive CICS argument array only.
5. `3.3`: metrics and documentation only.

Do not combine `3.1a` and `3.1b` unless the first checkpoint cannot be tested independently. Do not start CICS until dynamic `CALL` fields are proven additive and legacy-safe.

### Phase 4: RAG Integration

Phase 4 includes:

- Optional static value chunks.
- High-confidence facts only.
- No "always" wording unless globally proven.
- Provenance included in chunk text.

## 9. StaticValue Design

Planned classes:

```text
StaticValue
StaticValueState
StaticValueKind
ConstantStaticValue
UnknownStaticValue
NonConstantStaticValue
UnsupportedStaticValue
UninitializedStaticValue
NumericStaticValue
FigurativeStaticValue
TypeContext
```

`StaticValue` must be separate from runtime `TypedRecord`. Runtime evaluation currently uses `Double` in places, and binary floating point is not acceptable for static numeric facts. Static folding must use `BigDecimal` and preserve exact decimal text.

Important terms:

| Field | Meaning |
|---|---|
| raw lexeme | Source literal or emitted folded text as it appeared or was derived, for example `1,20` or `3`. |
| normalized value | Canonical value, for example `1.20`. |
| display value | Human-readable form for docs or chunks. |
| numeric decimal value | Exact decimal value represented with `BigDecimal` semantics. |
| type context | Optional PIC, usage, sign, scale, precision, or layout context. |

Phase 1 evaluates expression value only. It does not compute final COBOL storage bytes and does not apply target PIC truncation.

## 10. Supported And Unsupported Cases

Phase 1 supported cases:

- Closed numeric literal `COMPUTE` expressions.
- Signed numeric literals.
- Decimal literals with dot notation.
- Parentheses.
- Unary plus and unary minus.
- Addition.
- Subtraction.
- Multiplication.
- Exact safe division.

Unsupported in Phase 1:

- Variable references.
- String folding.
- Function calls.
- Reference modification.
- Subscripts and indexes.
- `IF` and `EVALUATE` condition simplification.
- Class and sign tests.
- Figurative constants such as `ZERO`, `SPACES`, `HIGH-VALUE`, `LOW-VALUE`, `QUOTE`, and `NULL`.
- `ROUNDED`.
- `ON SIZE ERROR`.
- Target PIC truncation.
- COMP and COMP-3 storage semantics.
- Dynamic `CALL` and CICS resolution.
- Propagation.

Unsupported or unsafe cases emit machine-readable diagnostics when they occur in a `COMPUTE` expression considered by the folder.

Initial Phase 1 diagnostic codes include:

```text
FOLD_UNSUPPORTED_VARIABLE_REFERENCE
FOLD_UNSUPPORTED_FUNCTION
FOLD_UNSUPPORTED_SUBSCRIPT
FOLD_UNSUPPORTED_REFERENCE_MODIFICATION
FOLD_UNSUPPORTED_DECIMAL_COMMA_MODE_UNKNOWN
FOLD_UNSUPPORTED_FIGURATIVE_CONSTANT
FOLD_UNSUPPORTED_SPECIAL_REGISTER
FOLD_UNSUPPORTED_NON_NUMERIC_LITERAL
FOLD_UNSUPPORTED_EXPONENTIATION
FOLD_UNSUPPORTED_DIALECT_NODE
FOLD_UNSAFE_DIVIDE_BY_ZERO
FOLD_UNSAFE_NON_TERMINATING_DIVISION
FOLD_UNSAFE_SIZE_ERROR_SEMANTICS
FOLD_INVALID_NUMERIC_LITERAL
```

## 11. Conservative Rules And Safety Policy

The analyzer must prefer these outcomes over unsafe conclusions:

```text
UNKNOWN
UNSUPPORTED
NON_CONSTANT
diagnostic
```

Examples:

- Variable reference in Phase 1: unsupported.
- Division by zero: unsafe.
- Non-terminating decimal division: unsafe.
- Decimal comma without `DECIMAL-POINT IS COMMA` support: unsupported.
- Figurative constants in Phase 1: unsupported.
- `CALL USING` argument in propagation: killed unless safe parameter mode is proven.
- `READ`, `ACCEPT`, CICS, SQL, `STRING`, `UNSTRING`, and `INSPECT` outputs: runtime-dependent, killed or marked unknown.
- `REDEFINES`, group, OCCURS, and reference-modification ambiguity: conservative kill.

## 12. Before/After Improvement Table

| COBOL input | Before | After Phase 1 | After Phase 2 |
|---|---|---|---|
| `COMPUTE WS-A = 1 + 2` | no folded fact | folded value `3` | same |
| `COMPUTE WS-B = WS-A + 1` | no explanation | diagnostic: variable reference unsupported | may fold if `WS-A` proven constant |
| `COMPUTE WS-C = 1 / 0` | no explanation | diagnostic: divide by zero | same |
| `MOVE 7 TO WS-D` | assignment fact exists | unchanged | Phase 2.5 propagates numeric literal entry/exit facts |
| `MOVE WS-A TO WS-C` when `WS-A` is proven `10` | no propagated fact | unchanged | Phase 2.6c propagates `WS-C = 10` if `WS-A` was not killed |
| real CFG join where one predecessor has `WS-D = 20` and another has `WS-D = 30` | no sidecar explanation | unchanged | `WS-D` is absent at the join and Phase 2.6e emits `DATAFLOW_CONSTANT_DROPPED_AT_JOIN` |
| loop that modifies `WS-A`, then `MOVE WS-A TO WS-B` after the loop | no sidecar explanation | unchanged | `WS-A` is not treated as a final loop value; Phase 2.6f emits `DATAFLOW_LOOP_CARRIED_CONSTANT_NOT_INFERRED` and does not propagate stale `WS-B` |
| dynamic `CALL WS-PGM` | legacy resolution only | unchanged | may get `path_sensitive_call_target` if `WS-PGM` proven |

## 13. How We Evaluate Whether Constant Folding Is Included

The tool includes constant folding only if all of these are true:

- Running the analyzer on the golden fixture produces `folded_value_facts`.
- `COMPUTE WS-A = 1 + 2` produces folded numeric value `3`.
- `COMPUTE WS-B = WS-A + 1` produces `FOLD_UNSUPPORTED_VARIABLE_REFERENCE`.
- `COMPUTE WS-C = 1 / 0` produces `FOLD_UNSAFE_DIVIDE_BY_ZERO`.
- `MOVE 7 TO WS-D` remains unchanged and emits no folding diagnostic.
- Existing `assignment_facts` are not rewritten.
- Existing `originalText` is unchanged.
- Existing CFG edges are unchanged.
- No dynamic `CALL` or CICS behavior changes.
- No RAG chunks change.
- Tests prove `BigDecimal` is used and `double`/`float` are not used for static numeric folding.

## 14. How We Evaluate Whether Constant Propagation Is Included

The tool includes a basic constant-propagation checkpoint when all of these are true:

- A `static_analysis/dataflow.json` artifact is emitted.
- The artifact has schema version and analysis version.
- Each CFG node can have entry and exit constants.
- Numeric literal `MOVE` facts enter and exit the CFG state.
- Variable-copy `MOVE` statements can copy a proven numeric entry constant to the target after kill rules have run.
- Folded numeric `COMPUTE` facts enter and exit the CFG state.
- Branch merges keep only constants proven equal on every incoming path.
- Real multi-predecessor joins emit `DATAFLOW_CONSTANT_DROPPED_AT_JOIN` when predecessor constants conflict.
- Variables modified inside CFG cycles emit `DATAFLOW_LOOP_CARRIED_CONSTANT_NOT_INFERRED` and are not propagated as final loop values.
- Alias kills remove stale constants before new facts are written.
- The solver converges deterministically or emits a limit diagnostic.
- Existing CFG, source, assignment facts, dynamic CALL/CICS fields, and RAG chunks remain unchanged.

The Phase 2.6d variable-expression checkpoint includes this simple variable-based case:

```cobol
MOVE 10 TO WS-A
COMPUTE WS-B = WS-A + 5
```

Expected result:

```text
entry to COMPUTE: WS-A = 10
exit from COMPUTE: WS-B = 15
```

The tool should still not be described as full production-ready propagation until these additional criteria are complete:

- Branch merges are conservative.
- Different values on real multi-predecessor joins produce no constant at the join and emit a merge diagnostic.
- Runtime inputs like `ACCEPT`, `READ`, CICS, and SQL kill affected values.
- `CALL USING` kills arguments unless safe parameter mode is proven.
- Loops converge safely or emit limit diagnostics.
- Existing CFG, source, and assignment artifacts remain unchanged.
- Propagation facts are source-preserving sidecar facts, not source rewrites.

## 15. Testing Plan

Required tests:

- `StaticValue` unit tests.
- Numeric literal parsing tests.
- `BigDecimal` arithmetic tests.
- Expression folding tests.
- Unsupported expression tests.
- Unsafe expression tests.
- Diagnostic code tests.
- Golden CFG output tests.
- Regression tests proving existing `assignment_facts` unchanged.
- Regression tests proving CFG edges unchanged.
- Later dataflow tests.
- Later alias kill tests.
- Later `CALL`/CICS path-sensitive tests.

Golden fixture:

```cobol
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CONSTFOLD.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-A PIC 9(4).
       01 WS-B PIC 9(4).
       01 WS-C PIC 9(4).
       01 WS-D PIC 9(4).
       01 WS-E PIC S9(4).
       01 WS-F PIC 9(4)V99.
       01 WS-G PIC 9(4)V99.
       01 WS-H PIC 9(4)V99.
       01 WS-I PIC 9(4).
       01 WS-J PIC 9(4).
       01 WS-K PIC 9(4).
       01 WS-L PIC 9(4).
       PROCEDURE DIVISION.
       MAIN-PARA.
           COMPUTE WS-A = 1 + 2
           COMPUTE WS-B = WS-A + 1
           COMPUTE WS-C = 1 / 0
           MOVE 7 TO WS-D
           COMPUTE WS-E = (1 + 2) * -3
           COMPUTE WS-F = 1.20 + 2.30
           COMPUTE WS-G = 1 / 4
           COMPUTE WS-H = 1 / 3
           COMPUTE WS-I = ZERO + 1
           COMPUTE WS-J = 2 ** 3
           COMPUTE WS-K = 10 - 3
           COMPUTE WS-L = +4
           GOBACK.
```

## 16. Risks And Mitigations

| Risk | Mitigation |
|---|---|
| Overclaiming constants | Only emit proven facts; use diagnostics for uncertainty; avoid "always" unless globally proven. |
| Incorrect decimal arithmetic | `BigDecimal` only; no `double`/`float`; exact division only; no target PIC truncation in Phase 1. |
| Breaking existing artifacts | Additive metadata only; golden regression tests; `assignment_facts`, `originalText`, and CFG edges unchanged. |
| COBOL aliasing issues | Conservative kill rules; treat `REDEFINES`, OCCURS, and reference modification carefully; no alias-based propagation until tested. |
| Artifact bloat | Diagnostics only for considered `COMPUTE` statements in PR 1; no diagnostics for every non-`COMPUTE` statement; optional flags later. |
| Misleading RAG chunks | RAG integration deferred; include provenance and scope; do not say "always" unless proven. |

## 17. Suggestions And Recommended Engineering Decisions

- Keep Phase 1 very small. Only closed numeric `COMPUTE` folding should be implemented first.
- Do not implement propagation in the same PR as folding. Propagation requires CFG fixed-point analysis and many kill rules.
- Treat diagnostics as a first-class feature. A skipped fold with a clear reason is valuable.
- Keep all new behavior additive. Do not modify old fields, old CFG edges, or old assignment facts.
- Prefer false negatives over false positives. It is better to miss a fold than to emit an incorrect constant.
- Do not use runtime evaluation infrastructure. Static folding must not rely on `TypedRecord`, `Double`, or runtime COBOL value simulation.
- Make before/after output part of the documentation. This lets humans verify the feature without reading code.
- Commit the documentation before implementation. The documentation should act as the contract for PR 1 and later phases.

## 18. Out Of Scope For PR 1

PR 1 does not include:

- Constant propagation.
- `IF` or `EVALUATE` simplification.
- Dynamic `CALL` or CICS improvements.
- RAG chunk changes.
- Target PIC truncation.
- COMP or COMP-3 storage simulation.
- Group move expansion.
- Alias propagation.
- Loop reasoning.
- Interprogram propagation.
- Rewriting COBOL source.
- Rewriting CFG text.
- Changing `assignment_facts`.

## 19. Deliverables

The documentation commit includes:

- This Markdown documentation file.
- Before/after examples.
- Acceptance criteria for folding.
- Acceptance criteria for propagation.
- Explicit PR 1 scope.
- Explicit PR 1 non-goals.
- Risks and mitigations.
- Suggested implementation phases.

The first implementation PR should include:

- `StaticValue` value model.
- Closed numeric `COMPUTE` folding.
- `folded_value_facts`.
- `folding_diagnostics`.
- Golden fixture and exact JUnit tests.
- No propagation, no dynamic target changes, and no RAG changes.

## 20. Accuracy And Performance Measurement

During implementation and at the end of each phase, the project should record accuracy and performance stats. The goal is to know whether the feature improved the analyzer and whether it made the pipeline slower or larger.

Phase 1 folding stats should include:

- Number of `COMPUTE` statements inspected.
- Number of expressions folded.
- Number of expressions skipped by diagnostic code.
- Number of unsafe expressions, such as divide by zero.
- Number of existing `assignment_facts` changed, expected to be zero.
- Number of CFG edge changes, expected to be zero.
- Runtime overhead for Java `WRITE_CFG`.
- CFG JSON size delta.

Current Phase 1 golden-fixture stats, measured on `smojol-toolkit/test-code/flow-ast/constant-folding-phase1.cbl`:

| Metric | Before Phase 1 | Current Phase 1 |
|---|---:|---:|
| `COMPUTE` statements inspected by the folder | 0 | 11 |
| Folded closed numeric `COMPUTE` expressions | 0 | 6 |
| Unsupported variable-reference diagnostics | 0 | 1 |
| Unsafe divide-by-zero diagnostics | 0 | 1 |
| Unsafe non-terminating-division diagnostics | 0 | 1 |
| Unsupported figurative-constant diagnostics | 0 | 1 |
| Unsupported exponentiation diagnostics | 0 | 1 |
| Existing `MOVE 7 TO WS-D` assignment facts changed | 0 | 0 |
| CFG nodes | unchanged by folding metadata | 18 |
| CFG edges | unchanged by folding metadata | 17 |
| Minified CFG JSON bytes with folding metadata removed | 18,895 | n/a |
| Minified CFG JSON bytes with folding metadata present | n/a | 23,282 |
| Additive folding metadata bytes | 0 | 4,387 |
| Target Java hardening suite wall-clock | no comparable pre-Phase 1 fixture baseline | 13.723s |
| Dynamic `CALL`/CICS behavior changed | 0 | 0 |
| Constant propagation facts emitted | 0 | 0 |

These are fixture-level accuracy and size stats, not corpus-wide performance numbers. There is no exact historical runtime baseline for this fixture because it was introduced with Phase 1; the recorded wall-clock is the current targeted Java hardening suite runtime after Phase 1. Broader performance comparison should be done on frozen corpus fixtures before Phase 2 changes are evaluated.

Phase 2 propagation stats should include:

- Number of CFG nodes analyzed.
- Number of variables tracked.
- Number of fixed-point iterations.
- Whether convergence was reached.
- Number of constants proven at node entry and exit.
- Number of values degraded to `UNKNOWN` at joins.
- Number of kills by reason.
- Runtime and memory overhead.

Current Phase 2.6f dataflow stats:

| Fixture | Node states | CFG edges | Entry constants | Exit constants | Kill facts | Diagnostics | Alias sets | Paragraph summaries | Iterations | Converged | Sidecar bytes |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|
| `output-kills-phase26b.cbl` | 49 | 48 | 6 | 6 | 15 | 0 | 0 | 1 | 2 | yes | 22,262 |
| `runtime-kills-phase26a.cbl` | 16 | 15 | 13 | 16 | 3 | 0 | 0 | 1 | 2 | yes | 16,243 |
| `constant-propagation-phase2.cbl` | 17 | 16 | 33 | 40 | 3 | 0 | 1 | 1 | 2 | yes | 32,413 |
| `constant-folding-phase1.cbl` | 18 | 17 | 56 | 64 | 0 | 0 | 0 | 1 | 2 | yes | 45,673 |

The `output-kills-phase26b.cbl` fixture proves the remaining runtime-output safety rules:

- `READ IN-FILE INTO WS-READ` kills the prior `WS-READ = 10` fact.
- `STRING "12" ... INTO WS-STRING` kills the prior `WS-STRING = 20` fact.
- `UNSTRING WS-SOURCE ... INTO WS-UNSTRING` kills the prior `WS-UNSTRING = 30` fact.
- `INSPECT WS-INSPECT ...` kills the prior `WS-INSPECT = 40` fact.
- `EXEC CICS RECEIVE INTO(WS-CICS)` kills the prior `WS-CICS = 50` fact using existing CICS argument metadata.
- `EXEC SQL SELECT ... INTO :WS-SQL` kills the prior `WS-SQL = 60` fact using existing SQL host-variable metadata.

SQL dialect parsing currently emits several CFG `DIALECT` nodes for the same SQL source statement. The correctness contract for Phase 2.6b is therefore node-local: the exact source-location node that follows `MOVE 60 TO WS-SQL` must show `WS-SQL = 60` at entry and no `WS-SQL` at exit. The aggregate `summary.kill_count` includes duplicate SQL dialect nodes and is recorded as a metric, not used as the pass/fail criterion for SQL correctness.

The `constant-propagation-phase2.cbl` fixture proves the deliberately narrow behavior:

- `MOVE 10 TO WS-A` produces `WS-A = 10` at node exit.
- `COMPUTE WS-B = 1 + 2` produces `WS-B = 3` from the existing folded fact.
- `MOVE WS-A TO WS-C` now produces `WS-C = 10` when `WS-A = 10` is proven at node entry.
- `COMPUTE WS-E = WS-A + 5` now produces `WS-E = 15` when `WS-A = 10` is proven at node entry.
- A branch-shaped CFG that nests the yes/no bodies under an `IF_BRANCH` does not carry branch-local `WS-D` forward to the following statement; this remains conservative, but is not yet modeled as a real multi-predecessor join.
- Writing `CHILD-A` applies `group_child:SOME-GROUP` alias kills before writing the direct `CHILD-A = 99` fact.

The `constant-folding-phase1.cbl` fixture also proves expression propagation after local folding: after `COMPUTE WS-A = 1 + 2` produces `WS-A = 3`, the later `COMPUTE WS-B = WS-A + 1` can produce `WS-B = 4` in the dataflow sidecar. This is still a sidecar fact only; the original `COMPUTE` metadata and `assignment_facts` remain unchanged.

The solver-level join diagnostic test proves the use case that the current COBOL fixture CFG does not expose directly: two predecessor nodes produce `WS-D = 20` and `WS-D = 30`, a join node keeps `WS-D` absent from `entry_constants`, and the join node records one `DATAFLOW_CONSTANT_DROPPED_AT_JOIN` diagnostic with both incoming values. This is an accuracy improvement in explanation, not an increase in propagated constants.

The solver-level loop diagnostic test proves the loop safety use case directly: `MOVE 1 TO WS-A` enters a self-cycle where `ADD 1 TO WS-A` modifies `WS-A`, then a later `MOVE WS-A TO WS-B` receives no stale `WS-A` fact. The loop node records one `DATAFLOW_LOOP_CARRIED_CONSTANT_NOT_INFERRED` diagnostic and the solver still converges. This is also an explanation improvement, not a claim that final loop values are known.

The `runtime-kills-phase26a.cbl` fixture proves the first runtime safety rules:

- `ACCEPT WS-A FROM DATE` kills the prior `WS-A = 10` fact.
- `MOVE WS-A TO WS-C` after `ACCEPT WS-A FROM DATE` still does not produce `WS-C`, proving killed source values are not copied.
- `INITIALIZE WS-B` kills the prior `WS-B = 20` fact.
- `CALL "SUBPROG" USING WS-REF` kills `WS-REF` because default mode is `REFERENCE`.
- `BY CONTENT WS-CONTENT` and `BY VALUE WS-VALUE` preserve the caller-side constants.

Verification for this checkpoint:

| Command | Result |
|---|---|
| `mvn -pl smojol-toolkit test -Dcheckstyle.skip=true -Dtest=JavaHardeningRegressionTest` | 39 tests, build success, 13.351s |
| `mvn -pl smojol-toolkit test -Dcheckstyle.skip=true` | 51 tests, 2 skipped, build success, 14.507s |

### Phase 2.7 Evaluation Summary

At this point the tool has a scoped, source-preserving constant propagation sidecar. It does not have full compiler-style COBOL constant propagation. The honest claim is narrower: `static_analysis/dataflow.json` can now carry proven numeric constants through selected safe transfer rules, can erase those constants at known unsafe runtime or alias boundaries, and can explain some conservative drops through diagnostics.

Implemented Phase 2 behavior:

- `static_analysis/dataflow.json` is emitted as a separate artifact, not as rewritten COBOL or rewritten CFG text.
- Every analyzed CFG node can have deterministic `entry_constants`, `exit_constants`, `kills`, and `diagnostics`.
- Numeric literal `MOVE` can prove a target constant.
- Folded numeric `COMPUTE` facts from Phase 1 can seed the dataflow state.
- `MOVE <known-variable> TO <target>` can copy a proven numeric constant if the source survives all prior kills.
- Narrow numeric `COMPUTE` expressions can use proven numeric entry constants, numeric literals, parentheses, unary signs, addition, subtraction, multiplication, and exact division.
- `ACCEPT`, `CALL USING` by reference, `INITIALIZE`, `READ INTO`, `STRING INTO`, `UNSTRING INTO`, `INSPECT`, CICS output arguments, SQL `SELECT/FETCH ... INTO`, and alias-overlapping writes kill affected constants.
- Real branch joins drop conflicting constants and emit `DATAFLOW_CONSTANT_DROPPED_AT_JOIN`.
- CFG cycles with modified variables emit `DATAFLOW_LOOP_CARRIED_CONSTANT_NOT_INFERRED` instead of inventing final loop values.

Still not implemented:

- Full COBOL loop trip-count reasoning or final loop-value inference.
- `IF`/`EVALUATE` condition simplification or branch reachability pruning.
- Alphanumeric/string constant propagation.
- Group move expansion into child fields.
- Target `PIC`, edited numeric, `COMP`, or `COMP-3` storage semantics.
- Interprocedural propagation through called programs.
- Path-sensitive dynamic `CALL` or CICS target fields.
- RAG chunks that summarize propagated constants.
- Corpus-level precision/recall or heap-memory benchmarking.

Example: proven literal and variable-copy propagation:

```cobol
MOVE 10 TO WS-A
MOVE WS-A TO WS-C
```

After Phase 2.6c, the first node proves `WS-A = 10` at exit. The second node sees `WS-A = 10` at entry and emits `WS-C = 10` at exit. This fact exists only in `static_analysis/dataflow.json`; the source statement and existing `assignment_facts` remain unchanged.

Example: expression propagation from a proven variable:

```cobol
MOVE 10 TO WS-A
COMPUTE WS-E = WS-A + 5
```

After Phase 2.6d, the `COMPUTE` node can prove `WS-E = 15` because every variable in the expression is known at node entry and the arithmetic subset is supported. If any variable is missing, the solver emits no propagated constant.

Example: runtime input prevents stale propagation:

```cobol
MOVE 10 TO WS-A
ACCEPT WS-A FROM DATE
MOVE WS-A TO WS-C
```

`ACCEPT WS-A` kills the old `WS-A = 10` fact because runtime input overwrites the field. The later `MOVE WS-A TO WS-C` therefore does not infer `WS-C = 10`. This is a deliberate false-negative preference: missing a possible value is safer than emitting a stale one.

Example: conflicting branch values are explained, not guessed:

```cobol
IF WS-FLAG = 1
    MOVE 20 TO WS-D
ELSE
    MOVE 30 TO WS-D
END-IF
```

At a real multi-predecessor join, `WS-D` is absent because incoming paths disagree. The join diagnostic records the predecessor values `20` and `30` so humans can see why the constant was dropped.

Example: loop-carried values are not inferred:

```cobol
MOVE 1 TO WS-A
PERFORM UNTIL WS-A > 5
    ADD 1 TO WS-A
END-PERFORM
MOVE WS-A TO WS-B
```

The solver does not claim `WS-A = 6`, because that would require full COBOL loop semantics. It records `DATAFLOW_LOOP_CARRIED_CONSTANT_NOT_INFERRED` for the cycle and does not propagate a stale `WS-A` into `WS-B`.

Example: alias kills protect overlapping storage:

```cobol
01 SOME-GROUP.
   05 CHILD-A PIC 9(2).
   05 CHILD-B PIC 9(2).

MOVE 99 TO CHILD-A
```

The write to `CHILD-A` emits alias kill facts for overlapping group-child relationships before writing the direct `CHILD-A = 99` fact. This keeps older facts about `SOME-GROUP` or sibling storage from surviving incorrectly.

Repeatable metric commands:

```bash
mvn -pl smojol-toolkit test -Dcheckstyle.skip=true -Dtest=JavaHardeningRegressionTest
mvn -pl smojol-toolkit test -Dcheckstyle.skip=true
jq '{node_states:(.node_states|length), edges:.summary.edge_count, entry:.summary.entry_constant_count, exit:.summary.exit_constant_count, kills:.summary.kill_count, diagnostics:.summary.diagnostic_count, aliases:.summary.alias_set_count, paragraphs:.summary.paragraph_summary_count, iterations:.summary.iteration_count, converged:.summary.converged}' smojol-toolkit/test-code/out/constant-propagation-phase2.cbl.report/static_analysis/dataflow.json
wc -c smojol-toolkit/test-code/out/constant-propagation-phase2.cbl.report/static_analysis/dataflow.json
```

Phase 2.7 conclusion: the implementation is useful for documented numeric facts and for explaining why unsafe facts are not propagated. It improves analysis transparency and some value precision, but it is not yet enough to claim improved dynamic target resolution or RAG accuracy. Those claims require Phase 3 path-sensitive fields and Phase 4 retrieval evaluation.

Accuracy evaluation should report:

- True folded facts on golden fixtures.
- Correct diagnostics for unsupported and unsafe expressions.
- No regressions in existing Java hardening tests.
- No behavior changes in dynamic `CALL` and CICS legacy fields until path-sensitive fields are explicitly added.
- For later phases, precision/recall of path-sensitive dynamic target resolution on a frozen fixture set.

Performance evaluation should report before/after timings on the same fixture set used by the benchmark harness when possible. If performance worsens, the implementation must explain the cost and provide a limit or configuration switch.
