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
| 2.6c | `PENDING` | Add broader transfer rules. | Tests cover variable-copy propagation and expression propagation from known variables only after runtime-output kill rules are in place. |
| 2.7 | `WORKING` | Record Phase 2 accuracy/performance stats. | Checkpoint stats are recorded after each propagation step; final Phase 2 report must include node count, variable count, iteration count, proven constants, unknown merges, kills by reason, runtime, and memory. |
| 3.1 | `PENDING` | Add path-sensitive dynamic CALL facts. | New `path_sensitive_*` fields coexist with unchanged legacy fields. |
| 3.2 | `PENDING` | Add path-sensitive CICS target facts. | New CICS path-sensitive fields coexist with unchanged legacy fields. |
| 3.3 | `PENDING` | Evaluate target-resolution accuracy. | Frozen fixtures report precision/recall or exact expected-target pass/fail counts versus legacy behavior. |
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

Phase 2 now has a committed sidecar with paragraph summaries, conservative alias-set summaries, conservative alias kill facts, a first narrow propagation solver, and runtime/input/output kill facts. This is not full COBOL constant propagation. It is a safe checkpoint that proves the artifact can carry node entry/exit constants and remove stale runtime-overwritten constants without changing CFG text, `assignment_facts`, dynamic CALL/CICS behavior, or RAG chunks.

The current Phase 2.5 solver supports only these value-producing rules:

- `MOVE <numeric-literal> TO <variable>` produces a numeric constant for the target.
- A folded numeric `COMPUTE` fact from Phase 1 produces a numeric constant for the target.
- Any modified variable that does not produce one of those safe constants is removed from the exit state.
- Alias kills from Phase 2.4 are applied before the node writes new constants.
- A join keeps a constant only when every predecessor exit has the same JSON value for that variable.

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

The current solver intentionally does not support variable-copy propagation, expression propagation from known variables, condition simplification, branch reachability pruning, interprocedural summaries, dynamic CALL/CICS path-sensitive fields, or RAG chunk generation.

Representative Phase 2.6b artifact shape, shortened from fixture outputs. The paragraph-summary, alias-summary, kill, and propagated-constant examples may come from different fixtures because the checkpoints verify these shapes independently.

```json
{
  "program": "<program>.cbl",
  "schema_version": "1.0",
  "analysis": "static_value_dataflow",
  "analysis_version": "0.7",
  "status": "output_kill_constant_propagation",
  "config": {
    "constant_propagation_enabled": true,
    "path_sensitive_targets_enabled": false,
    "paragraph_summaries_enabled": true,
    "alias_analysis_enabled": true,
    "alias_kills_enabled": true,
    "mode": "output_kill_constant_propagation",
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
      "diagnostics": []
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

Remaining Phase 2 work includes:

- Interprocedural paragraph/call summaries beyond direct `CALL USING` reference kills.
- Transfer rules for variable-copy propagation and expressions that use known variables.
- Diagnostics explaining constants lost at joins.
- Loop-specific diagnostics and limit tests beyond the current fixed-point convergence guard.

### Phase 3: Path-Sensitive Dynamic CALL/CICS Resolution

Phase 3 includes:

- Consume dataflow entry constants at `CALL` and CICS nodes.
- Add new `path_sensitive_*` fields only.
- Keep legacy dynamic `CALL` and CICS fields unchanged.
- No behavior replacement until proven safe.

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
- Folded numeric `COMPUTE` facts enter and exit the CFG state.
- Branch merges keep only constants proven equal on every incoming path.
- Alias kills remove stale constants before new facts are written.
- The solver converges deterministically or emits a limit diagnostic.
- Existing CFG, source, assignment facts, dynamic CALL/CICS fields, and RAG chunks remain unchanged.

The tool includes full Phase 2 constant propagation only when the basic checkpoint is extended so a simple variable-based program works:

```cobol
MOVE 10 TO WS-A
COMPUTE WS-B = WS-A + 5
```

Expected result:

```text
entry to COMPUTE: WS-A = 10
exit from COMPUTE: WS-B = 15
```

Additional criteria:

- Branch merges are conservative.
- Different values on different branches produce no constant at the join and, in the full phase, a merge diagnostic.
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

Current Phase 2.6b dataflow stats:

| Fixture | Node states | CFG edges | Entry constants | Exit constants | Kill facts | Diagnostics | Alias sets | Paragraph summaries | Iterations | Converged | Sidecar bytes |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|
| `output-kills-phase26b.cbl` | 49 | 48 | 6 | 6 | 15 | 0 | 0 | 1 | 2 | yes | 22,252 |
| `runtime-kills-phase26a.cbl` | 16 | 15 | 13 | 16 | 3 | 0 | 0 | 1 | 2 | yes | 16,235 |
| `constant-propagation-phase2.cbl` | 17 | 16 | 24 | 30 | 3 | 0 | 1 | 1 | 2 | yes | 26,028 |
| `constant-folding-phase1.cbl` | 18 | 17 | 45 | 52 | 0 | 0 | 0 | 1 | 2 | yes | 38,052 |

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
- `MOVE WS-A TO WS-C` does not produce `WS-C = 10`; variable-copy propagation is still pending.
- A branch that assigns `WS-D = 20` on one path and `WS-D = 30` on another path drops `WS-D` at the join.
- Writing `CHILD-A` applies `group_child:SOME-GROUP` alias kills before writing the direct `CHILD-A = 99` fact.

The `runtime-kills-phase26a.cbl` fixture proves the first runtime safety rules:

- `ACCEPT WS-A FROM DATE` kills the prior `WS-A = 10` fact.
- `MOVE WS-A TO WS-C` still does not produce `WS-C`, proving variable-copy propagation is deferred.
- `INITIALIZE WS-B` kills the prior `WS-B = 20` fact.
- `CALL "SUBPROG" USING WS-REF` kills `WS-REF` because default mode is `REFERENCE`.
- `BY CONTENT WS-CONTENT` and `BY VALUE WS-VALUE` preserve the caller-side constants.

Verification for this checkpoint:

| Command | Result |
|---|---|
| `mvn -pl smojol-toolkit test -Dcheckstyle.skip=true -Dtest=JavaHardeningRegressionTest` | 37 tests, build success, 13.650s |
| `mvn -pl smojol-toolkit test -Dcheckstyle.skip=true` | 49 tests, 2 skipped, build success, 13.875s |

Accuracy evaluation should report:

- True folded facts on golden fixtures.
- Correct diagnostics for unsupported and unsafe expressions.
- No regressions in existing Java hardening tests.
- No behavior changes in dynamic `CALL` and CICS legacy fields until path-sensitive fields are explicitly added.
- For later phases, precision/recall of path-sensitive dynamic target resolution on a frozen fixture set.

Performance evaluation should report before/after timings on the same fixture set used by the benchmark harness when possible. If performance worsens, the implementation must explain the cost and provide a limit or configuration switch.
