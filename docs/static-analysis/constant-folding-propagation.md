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
- Better flow-sensitive, per-CFG-node analysis later.
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

### External Review Corrections — 2026-05-18

Claude's review after Phase 3.2a accepted the source-preserving architecture but found a real soundness gap: the dataflow solver could seed propagated constants from expression or literal values without checking whether the target COBOL field can actually store that value. The local folding fact `folded_value_facts` is still acceptable because it is explicitly an expression fact, not a stored-value claim. The dataflow sidecar is different: `entry_constants` and `exit_constants` describe variable states, so they must be PICTURE-aware before this work can support accuracy claims or RAG facts.

Accepted blockers:

- Numeric storage gating: `MOVE`, folded `COMPUTE`, and expression-propagated numeric constants are emitted only when target PICTURE information proves the decimal value fits the target's integer digits, fractional digits, and sign. Otherwise, the solver omits the constant. This is complete for simple numeric PICTURE forms using `9`, `S`, and `V`; unsupported numeric PICTURE forms remain conservative false negatives.
- Size-error/rounding gating: `ROUNDED`, `ON SIZE ERROR`, and `NOT ON SIZE ERROR` may still allow a local expression fold, but now prevent dataflow seeding.
- Alphanumeric length gating: quoted `MOVE` constants must be placed into dataflow only when the receiving `PIC X(n)` field can hold the normalized value without truncation. This prevents wrong high-confidence `CALL` or CICS targets such as `MOVE "LONGERTHAN8" TO WS-PGM PIC X(8)`.
- Negative target tests: Phase 3 must prove it does not emit `path_sensitive_*` fields for static `CALL`s, literal CICS targets, output-only CICS statements, unsupported CICS argument names, or branch joins with conflicting target values.

Terminology correction: the JSON field names keep the committed `path_sensitive_*` prefix for compatibility, but the implementation is more precisely flow-sensitive or per-CFG-node. It stores one merged fact set per CFG node; it does not retain separate facts per distinct execution path after joins. Documentation and thesis prose should use "flow-sensitive/per-CFG-node" and explain that `path_sensitive_*` is the additive field prefix chosen for the dual-emission window.

Secondary cleanup items:

- Treat `FOLD_UNSAFE_SIZE_ERROR_SEMANTICS` as reserved until the folder has statement-level access to `ON SIZE ERROR`; do not claim it is emitted today.
- Extract the duplicated variable canonicalization rule from `StaticValueDataflowPass` and `PathSensitiveTargetResolver` when touching either class for the next implementation checkpoint.
- Document that `config.path_sensitive_targets_enabled` in `dataflow.json` is an analysis-mode/configuration flag; the actual `path_sensitive_*` facts live in CFG node metadata.
- Phase 3.2b changes the mode/status string to `flow_sensitive_call_cics_targets` so it does not imply only CICS targets when dynamic `CALL`, CICS targets, and CICS arguments are all active.
- Add known limitations for missed kill patterns such as `INSPECT ... TALLYING IN` and file record-buffer effects when `READ` has no explicit `INTO`.

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
| 2.8 | `DONE` | Add PIC-aware value gating for propagated numeric constants. | Dataflow does not seed or emit a `CONSTANT` for `MOVE`, folded `COMPUTE`, or expression propagation unless the target field's PICTURE makes the value provably representable; `ROUNDED` and `ON SIZE ERROR` block propagation seeding even if local expression folding still emits an expression fact. |
| 2.9 | `DONE` | Refuse subscripted and reference-modified propagation targets. | `subscript-refusal-phase29.cbl` proves `MOVE 5 TO WS-TBL(1)` does not create a whole-table `WS-TBL = 5` constant, `MOVE WS-TBL(2) TO WS-X` does not copy a stale table-cell value, `MOVE "ABC" TO WS-AREA(1:3)` does not create a full-field `WS-AREA = "ABC"` constant, and ordinary non-subscripted moves still propagate. |
| 2.10 | `DONE` | Add conservative `PERFORM` transitive kills. | `perform-kill-phase210.cbl` proves constants do not survive `PERFORM SUB-PARA` when the performed paragraph modifies the same variable, transitive `PERFORM SUB-A` -> `SUB-B` writes are killed at the caller, and no-write performed paragraphs preserve safe constants. |
| 2.11 | `DONE` | Expand negative hardening tests for unsupported output/kill cases. | `negative-hardening-phase211.cbl` and solver-level tests lock CALL metadata absence, READ record-buffer mutation, INSPECT TALLYING targets, SQL `RETURNING ... INTO`, multi-target MOVE, and SET 88-level condition-name parent kills. |
| 2.12 | `DONE` | Replace text-level dataflow expression parsing with grammar-backed evaluation. | `ComputeFlowNode.metadata()` now emits additive `dataflow_expression_facts` derived from the ANTLR arithmetic-expression tree; the dataflow pass evaluates those serialized expression trees against node `entry_constants` instead of reparsing `originalText`. |
| 3.0 | `DONE` | Write detailed Phase 3 pre-coding plan. | This document now defines the exact ordering, schemas, fixtures, tests, invariants, and risk controls for path-sensitive dynamic `CALL`/CICS facts. |
| 3.1a | `DONE` | Add quoted alphanumeric constants to the dataflow sidecar. | `MOVE "PROG-A" TO WS-PGM` and `MOVE WS-PGM TO WS-COPY` now carry `ALPHANUMERIC` constants through the same fixed-point solver; runtime, alias, and join kills still apply. Path-sensitive target fields remain disabled. |
| 3.1b | `DONE` | Add path-sensitive dynamic `CALL` metadata fields. | Dynamic `CALL WS-PGM` reads `WS-PGM` from node `entry_constants` and emits new `path_sensitive_call_*` fields without changing `resolved_call_target`, `call_target_source`, or `dynamic_call_resolution_confidence`. Runtime-killed identifiers emit an explicit path-sensitive unresolved status rather than reusing stale legacy literals. |
| 3.2a | `DONE` | Add path-sensitive CICS target metadata fields. | CICS identifier targets such as `PROGRAM(WS-CICS-PGM)` read proven entry constants and emit new `path_sensitive_cics_*` fields without changing legacy `resolved_cics_target`, `cics_target_source`, or `cics_dynamic_resolution_confidence`; runtime-killed identifiers stay path-sensitive unresolved. |
| 3.2b | `DONE` | Add path-sensitive CICS argument facts plus alphanumeric length gating. | Multiple CICS identifier arguments are reported in a new additive `path_sensitive_cics_arguments` array; existing `cics_arguments` stays unchanged; alphanumeric constants are not placed in dataflow if the target `PIC X(n)` cannot hold the literal without truncation. |
| 3.2c | `DONE` | Add Phase 3 negative and join-path tests. | Tests prove static `CALL`s, literal CICS targets, output-only CICS nodes, unsupported CICS argument names, overlength `PIC X(n)` values, runtime-killed identifiers, and conflicting branch joins do not emit false resolved `path_sensitive_*` facts. |
| 3.3 | `DONE` | Evaluate target-resolution accuracy. | The Phase 3 fixture now records exact legacy-vs-flow-sensitive counts: dynamic CALL improves from 2/4 reliable outcomes to 4/4, CICS targets improve from 4/6 to 6/6, and supported CICS selector arguments improve from 4/6 to 6/6 by refusing stale or unsafe resolved values. |
| 4.0 | `DONE` | Add screen-key synonym retrieval support. | Screen interaction chunks now emit explicit natural/exact key aliases such as `PF7=DFHPF7`; BM25 indexes `keywords` and `screen_key_aliases` as structured terms. The PDCBVC benchmark improved natural `PF7`/`PF8` retrieval from miss@10 to rank 1 and overall Hit@5 from 13/14 to 14/14. |
| 4.1 | `PENDING` | Add optional static-value RAG chunks. | Chunks may include only high-confidence storage-safe facts with provenance and no unsupported "always" wording; RAG remains off until explicitly implemented and evaluated. |
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
| 2026-05-18 | `DONE` | Added Phase 2.8 numeric PICTURE gating for stored-value constants. The dataflow pass now parses simple numeric PICTURE strings built from `S`, `9`, and `V`, and emits numeric `CONSTANT` facts only when the decimal value fits the target's integer digits, fractional digits, and sign. Unsupported PICTURE forms are treated as false negatives. `ROUNDED`, `ON SIZE ERROR`, and `NOT ON SIZE ERROR` still allow local expression facts but block dataflow seeding. The dataflow analysis version is now `1.6`. | Focused red/green check passed: `mvn -pl smojol-toolkit test -Dcheckstyle.skip=true -Dtest=JavaHardeningRegressionTest#dataflowEmitsNumericConstantsOnlyWhenTargetPictureCanRepresentThem`, 1 test, total time 7.211s. Targeted check passed: `mvn -pl smojol-toolkit test -Dcheckstyle.skip=true -Dtest=JavaHardeningRegressionTest`, 48 tests, total time 27.924s. Fixture metrics: `pic-gating-phase28.cbl` has 15 node states, 14 edges, 17 entry constants, 20 exit constants, 0 kill facts, 0 diagnostics, 0 alias sets, 1 paragraph summary, convergence in 2 iterations, a 17,559-byte pretty-printed sidecar, and a 29,390-byte pretty-printed CFG. Exact tests cover integer-scale refusal, fractional-fit success, fractional-overflow refusal, unsigned-negative refusal, signed-negative success, variable-copy overflow refusal, size-error blocking, and rounded blocking. |
| 2026-05-20 | `DONE` | Added Phase 2.9 subscript/reference-modification refusal for propagated stored constants. The dataflow pass now refuses to produce constants from statements whose raw data reference uses COBOL parenthesized reference syntax, so table-cell writes and slice writes can still kill old aliases but cannot become whole-field or whole-table facts. The dataflow analysis version is now `1.7`. | Focused check passed: `mvn -pl smojol-toolkit test -Dcheckstyle.skip=true -Dtest=JavaHardeningRegressionTest#dataflowRefusesSubscriptedAndReferenceModifiedConstants`, 1 test. Targeted check passed: `mvn -pl smojol-toolkit test -Dcheckstyle.skip=true -Dtest=JavaHardeningRegressionTest`, 51 tests, total time 31.474s. Broader check passed: `mvn -pl smojol-toolkit test -Dcheckstyle.skip=true`, 63 tests, 2 skipped, total time 31.780s. Fixture `subscript-refusal-phase29.cbl` proves `MOVE 5 TO WS-TBL(1)` creates no `WS-TBL` constant, `MOVE WS-TBL(2) TO WS-X` creates no stale `WS-X` constant, `MOVE "ABC" TO WS-AREA(1:3)` creates no full-field `WS-AREA` constant, and `MOVE 7 TO WS-NUM` still propagates normally. |
| 2026-05-20 | `DONE` | Added Phase 2.10 conservative `PERFORM` transitive kills. The dataflow pass now computes transitive modified variables from paragraph summaries for kill purposes and emits `PERFORM_TRANSITIVE_KILL` at the caller when a performed paragraph, or a paragraph it performs, may modify a currently known variable. The dataflow analysis version is now `1.8`. | Focused check passed: `mvn -pl smojol-toolkit test -Dcheckstyle.skip=true -Dtest=JavaHardeningRegressionTest#dataflowKillsConstantsModifiedByPerformedParagraphs`, 1 test. Targeted check passed: `mvn -pl smojol-toolkit test -Dcheckstyle.skip=true -Dtest=JavaHardeningRegressionTest`, 52 tests, total time 32.049s. Broader check passed: `mvn -pl smojol-toolkit test -Dcheckstyle.skip=true`, 64 tests, 2 skipped, total time 33.749s. Fixture `perform-kill-phase210.cbl` proves `PERFORM SUB-PARA` kills stale `WS-A`, transitive `PERFORM SUB-A` kills `WS-E` through `SUB-B`, and `PERFORM CLEAN-PARA` with no writes preserves `WS-C` so `MOVE WS-C TO WS-D` still propagates. Sidecar metrics: 31 nodes, 50 edges, 12 entry constants, 16 exit constants, 3 kills, 0 diagnostics, 5 paragraph summaries, convergence in 2 iterations. |
| 2026-05-20 | `DONE` | Added Phase 2.11 negative hardening for unsupported output and kill cases. The dataflow pass now has fallback `CALL USING` kills when structured `using_parameters` metadata is absent, conservative file-record-buffer kills for `READ` without explicit `INTO`, `INSPECT ... TALLYING` output kills, SQL `RETURNING ... INTO` host-variable kills, and parent-field kills for `SET <88-level> TO TRUE`. Multi-target `MOVE` remains supported when each target is storage-safe. The dataflow analysis version is now `1.9`. | Focused check passed: `mvn -pl smojol-toolkit test -Dcheckstyle.skip=true -Dtest=JavaHardeningRegressionTest#dataflowHardensKnownUnsupportedOutputAndConditionCases+dataflowKillsCallUsingReferenceWhenMetadataIsMissing+dataflowKillsSqlReturningIntoHostVariablesOutsideSelectFetch`, 3 tests. Fixture `negative-hardening-phase211.cbl` has 16 nodes, 15 edges, 5 entry constants, 7 exit constants, 3 kills, 0 diagnostics, 1 paragraph summary, and convergence in 2 iterations. |
| 2026-05-20 | `DONE` | Added Phase 2.12 grammar-backed expression propagation. `ComputeFlowNode.metadata()` now emits additive `dataflow_expression_facts` with a small serialized ANTLR expression tree. The dataflow pass evaluates only this tree, using proven numeric `entry_constants` for variables, instead of parsing `originalText`. The old `DataflowExpressionEvaluator` text parser was removed. The dataflow analysis version is now `1.10`. | Focused check passed: `mvn -pl smojol-toolkit test -Dcheckstyle.skip=true -Dtest=JavaHardeningRegressionTest#reportsVariableReferenceAsUnsupportedForPhaseOneFolding+dataflowPropagatesNumericMoveAndFoldedComputeFacts+dataflowMergesBranchesConservativelyAndAppliesAliasKills`, 3 tests. Fixture `constant-propagation-phase2.cbl` remains behaviorally stable: 17 nodes, 16 edges, 33 entry constants, 40 exit constants, 3 kills, 0 diagnostics, 1 alias set, 1 paragraph summary, convergence in 2 iterations, 32,403-byte dataflow sidecar, and 27,163-byte CFG with additive `dataflow_expression_facts`. |

### Phase 3 Checkpoints

| Date | Status | What changed | Verification |
|---|---|---|---|
| 2026-05-15 | `DONE` | Added Phase 3.1a alphanumeric constant propagation as a prerequisite for path-sensitive targets. The sidecar now represents quoted `MOVE` literals as `ALPHANUMERIC` constants, copies proven alphanumeric values through `MOVE <known-var> TO <target>`, and keeps runtime/input/output/alias kills kind-agnostic. It also bumps the dataflow analysis version to `1.2` and mode/status to `alphanumeric_constant_propagation`. No `path_sensitive_call_*` or `path_sensitive_cics_*` fields are emitted yet. | Targeted checks passed: `mvn -pl smojol-core test -Dcheckstyle.skip=true -Dtest=StaticValueTest`, 4 tests; `mvn -pl smojol-core install -Dcheckstyle.skip=true -DskipTests`; `mvn -pl smojol-toolkit test -Dcheckstyle.skip=true -Dtest=JavaHardeningRegressionTest`, 41 tests, total time 15.902s. Broader checks passed: `mvn -pl smojol-core test -Dcheckstyle.skip=true`, 100 tests, total time 5.258s; `mvn -pl smojol-toolkit test -Dcheckstyle.skip=true`, 53 tests, 2 skipped, total time 15.828s. Fixture metrics: `path-sensitive-targets-phase3.cbl` has 13 node states, 12 edges, 17 entry constants, 20 exit constants, 1 kill fact, 0 diagnostics, 0 alias sets, 1 paragraph summary, convergence in 2 iterations, and a 12,731-byte pretty-printed sidecar. |
| 2026-05-18 | `DONE` | Added Phase 3.1b path-sensitive dynamic `CALL` metadata. `WRITE_CFG` now builds `static_analysis/dataflow.json` before serializing the CFG, annotates only dynamic `CALL` nodes from proven alphanumeric entry constants, then writes the CFG and sidecar. The legacy resolver still emits `resolved_call_target`, `call_target_source`, and `dynamic_call_resolution_confidence` unchanged; new facts are strictly additive under the `path_sensitive_call_*` prefix. The dataflow analysis version is now `1.3` with mode/status `path_sensitive_call_targets`. | Targeted check passed: `mvn -pl smojol-toolkit test -Dcheckstyle.skip=true -Dtest=JavaHardeningRegressionTest`, 42 tests, total time 18.071s. Fixture metrics: `path-sensitive-targets-phase3.cbl` has 16 node states, 15 edges, 22 entry constants, 25 exit constants, 1 kill fact, 0 diagnostics, 0 alias sets, 1 paragraph summary, convergence in 2 iterations, a 15,517-byte pretty-printed sidecar, and a 25,392-byte pretty-printed CFG. Exact tests cover two path-sensitive resolved `CALL WS-PGM` nodes and one stale-legacy-but-path-sensitive-unresolved `CALL WS-KILLED` node. |
| 2026-05-18 | `DONE` | Added Phase 3.2a path-sensitive CICS target metadata. The same additive resolver now annotates CICS dialect nodes whose target identifier has a proven alphanumeric constant at node entry. It emits top-level `path_sensitive_cics_*` fields only; legacy `resolved_cics_target`, `cics_target_source`, `cics_dynamic_resolution_confidence`, nested `cics_operation`, and existing `cics_arguments` remain compatibility fields. The dataflow analysis version is now `1.4` with mode/status `path_sensitive_cics_targets`. | Targeted check passed: `mvn -pl smojol-toolkit test -Dcheckstyle.skip=true -Dtest=JavaHardeningRegressionTest`, 44 tests, total time 17.871s. Broader check passed: `mvn -pl smojol-toolkit test -Dcheckstyle.skip=true`, 56 tests, 2 skipped, total time 18.124s. Fixture metrics: `path-sensitive-targets-phase3.cbl` has 29 node states, 28 edges, 33 entry constants, 38 exit constants, 2 kill facts, 0 diagnostics, 0 alias sets, 1 paragraph summary, convergence in 2 iterations, a 23,746-byte pretty-printed sidecar, and a 55,569-byte pretty-printed CFG. Exact tests cover two CICS `LINK PROGRAM(WS-CICS-PGM)` nodes resolving to `CICSA` and `CICSB`, plus one `ACCEPT`-killed `WS-CICS-KILLED` node where legacy still reports `CICSKILL` but path-sensitive CICS metadata is unresolved. |
| 2026-05-18 | `DONE` | Added Phase 3.2b CICS argument facts and the first storage-safety gate for alphanumeric dataflow constants. The resolver now emits additive `path_sensitive_cics_arguments` entries for supported identifier arguments such as `QUEUE(WS-QUEUE)`, while leaving the existing `cics_arguments` array unchanged. The dataflow transfer now refuses quoted literals and copied alphanumeric constants when a known target `PIC X(n)` would truncate the normalized value. The dataflow analysis version is now `1.5` with mode/status `flow_sensitive_call_cics_targets`. | Targeted check passed: `mvn -pl smojol-toolkit test -Dcheckstyle.skip=true -Dtest=JavaHardeningRegressionTest`, 47 tests, total time 25.387s. Broader check passed: `mvn -pl smojol-toolkit test -Dcheckstyle.skip=true`, 59 tests, 2 skipped, total time 26.412s. Fixture metrics: `path-sensitive-targets-phase3.cbl` has 48 node states, 47 edges, 37 entry constants, 43 exit constants, 6 kill facts, 0 diagnostics, 0 alias sets, 1 paragraph summary, convergence in 2 iterations, a 31,579-byte pretty-printed sidecar, and a 98,071-byte pretty-printed CFG. Exact tests cover resolved `READQ TS QUEUE(WS-QUEUE)`, killed `QUEUE(WS-QUEUE-KILLED)`, output-only `RECEIVE INTO(WS-AREA)`, static `CALL "STATPROG"`, literal `LINK PROGRAM('LITPGM')`, and overlength `MOVE "LONGERTHAN8" TO WS-LONG-PGM PIC X(8)` refusing a high-confidence flow-sensitive target. |
| 2026-05-18 | `DONE` | Completed Phase 3.2c as a hardening-only checkpoint. The real CICS fixture now includes an unsupported `RESP(WS-RESP)` identifier argument; the resolver still reports the supported `PROGRAM(WS-CICS-PGM)` argument but does not add a `RESP` entry to `path_sensitive_cics_arguments`. A solver-level two-predecessor join test proves `MOVE "PROG-A" TO WS-PGM` on one predecessor and `MOVE "PROG-B" TO WS-PGM` on another predecessor leaves a later `CALL WS-PGM` path-sensitive unresolved and records the join diagnostic instead of guessing a target. | Focused check passed: `mvn -pl smojol-toolkit test -Dcheckstyle.skip=true -Dtest=JavaHardeningRegressionTest#pathSensitiveCicsArgumentsIgnoreUnsupportedArgumentNames+pathSensitiveDynamicCallStaysUnresolvedAfterConflictingJoin`, 2 tests, total time 9.546s. Targeted check passed: `mvn -pl smojol-toolkit test -Dcheckstyle.skip=true -Dtest=JavaHardeningRegressionTest`, 50 tests, total time 33.864s. Broader check passed: `mvn -pl smojol-toolkit test -Dcheckstyle.skip=true`, 62 tests, 2 skipped, total time 30.927s. Fixture metrics after adding the `RESP` case: `path-sensitive-targets-phase3.cbl` has 53 node states, 52 edges, 41 entry constants, 48 exit constants, 7 kill facts, 0 diagnostics, 0 alias sets, 1 paragraph summary, convergence in 2 iterations, a 35,073-byte pretty-printed sidecar, and a 110,187-byte pretty-printed CFG. |
| 2026-05-19 | `DONE` | Completed Phase 3.3 measurement without changing resolver behavior. The measured fixture treats stale values after runtime kills and unresolved overlength `PIC X(n)` values as reliability outcomes, not raw resolution counts. Flow-sensitive metadata resolves fewer cases than the legacy resolver, but all measured outcomes match the fixture's expected safe behavior because unsafe cases become explicit unresolved facts. | Documentation-only checkpoint. It reuses the passing Phase 3.2c verification: focused 2-test check, targeted `JavaHardeningRegressionTest` 50 tests, and broader `smojol-toolkit` 62 tests with 2 skipped. Measured fixture counts: 4 dynamic CALL identifier nodes, 6 CICS identifier target nodes, 6 supported CICS selector arguments, 14 legacy CICS identifier arguments total, 8 unsupported/output identifier arguments intentionally ignored by `path_sensitive_cics_arguments`, 35,073-byte dataflow sidecar, and 110,187-byte CFG. |

### Phase 4 Checkpoints

| Date | Status | What changed | Verification |
|---|---|---|---|
| 2026-05-20 | `DONE` | Added a narrow RAG retrieval improvement for screen function keys. `screen.pagination` and `screen.key_dispatch` chunks now include explicit aliases such as `PF7=DFHPF7`; `bm25_index.json` also indexes `keywords` and `screen_key_aliases` as structured terms. This does not add static-value chunks and does not change Java analysis artifacts. | Targeted checks passed: `python3 -m unittest test_chunk_pipeline.py`, 63 tests with 2 skipped; `python3 -m unittest test_bm25_index.py`, 5 tests. PDCBVC benchmark after regenerating current chunks: natural query `What happens for PF7 or PF8 key on the PDCBVC screen?` improved from v0 miss@10 to current rank 1; overall Hit@5 improved from 13/14 to 14/14; screen-flow Hit@5 improved from 2/3 to 3/3. |

### Remaining Propagation Hardening Plan

This section is the current plan after Claude's critical review of the constant folding and propagation work. It is intentionally explicit: no step should be treated as a black box, and each implementation step has a concrete source of evidence, file scope, and acceptance test.

Current claim boundary:

- Constant folding is implemented for closed numeric `COMPUTE` expressions. It is source-preserving and safe to claim with the documented scope.
- Constant propagation is implemented as scoped intraprocedural, flow-sensitive CFG facts with conservative kills for the documented subset. This is now strong enough to claim "intraprocedural flow-sensitive constant propagation with conservative kills" when the limitations below are stated.
- It is still not full production COBOL constant propagation. Phase 2.12 removes the old text-parser blocker, but RAG static-value chunks still require explicit Phase 4.1 implementation and evaluation before propagated constants are exposed to retrieval.

#### Phase 2.9: Subscript and Reference-Modification Refusal

Problem:

```cobol
MOVE 5 TO WS-TBL(1)
MOVE WS-TBL(2) TO WS-X
```

The analyzer must not interpret the first statement as `WS-TBL = 5` for the whole table. A single occurrence write proves only one cell, and the current dataflow lattice does not track per-index constants. The safe behavior is a false negative: kill affected aliases if possible, but emit no stored constant for `WS-TBL`, `WS-TBL(1)`, or later `WS-X` reads that rely on a different occurrence.

The same rule applies to reference modification:

```cobol
MOVE "ABC" TO WS-AREA(1:3)
```

This writes a slice of a field, not the whole field. The analyzer must not emit `WS-AREA = "ABC"` as a full-field constant.

Implementation plan:

- Add a helper in `StaticValueDataflowPass.java`, for example `hasSubscriptOrReferenceModification(String text)`.
- Use the helper before any dataflow constant is produced by `addAssignmentConstant`, `addMoveCopyConstants`, and `addComputeExpressionConstants`.
- The helper should reject targets or source identifiers whose raw text contains COBOL reference syntax such as `(`, `)`, or `:`. This is intentionally conservative; it does not try to parse indices.
- Existing alias kills should still be allowed to fire. The rule is: a subscripted/sliced write may kill old constants, but it must not create a new constant.
- Do not change `folded_value_facts`. Local expression folding is separate and does not claim storage for table cells or slices.

Tests:

- Add fixture `smojol-toolkit/test-code/flow-ast/subscript-refusal-phase29.cbl`.
- Add exact assertions in `JavaHardeningRegressionTest.java`:
  - `MOVE 5 TO WS-TBL(1)` leaves `WS-TBL`, `WS-TBL(1)`, and `WS-TBL(2)` absent from `exit_constants`.
  - `MOVE WS-TBL(2) TO WS-X` does not create `WS-X = 5`.
  - `MOVE "ABC" TO WS-AREA(1:3)` leaves `WS-AREA` absent from `exit_constants`.
  - Existing alias/kill facts for the write still appear when the data-structure model exposes the table or group relationship.

Acceptance:

- Status: `DONE`.
- The dataflow analysis version is now `1.7`.
- Focused check passed: `mvn -pl smojol-toolkit test -Dcheckstyle.skip=true -Dtest=JavaHardeningRegressionTest#dataflowRefusesSubscriptedAndReferenceModifiedConstants`, 1 test.
- Targeted check passed: `mvn -pl smojol-toolkit test -Dcheckstyle.skip=true -Dtest=JavaHardeningRegressionTest`, 51 tests.
- Broader check passed: `mvn -pl smojol-toolkit test -Dcheckstyle.skip=true`, 63 tests with 2 skipped.
- New fixture: `smojol-toolkit/test-code/flow-ast/subscript-refusal-phase29.cbl`.
- Exact behavior now locked:
  - `MOVE 5 TO WS-TBL(1)` leaves `WS-TBL`, `WS-TBL(1)`, and `WS-TBL(2)` absent from `exit_constants`.
  - The same subscripted table write still emits conservative alias kills when the data-structure model exposes `WS-TABLE`/`WS-TBL` group and `OCCURS` relationships.
  - `MOVE WS-TBL(2) TO WS-X` does not create `WS-X = 5`.
  - `MOVE "ABC" TO WS-AREA(1:3)` leaves `WS-AREA` absent from `exit_constants`.
  - `MOVE WS-AREA TO WS-AREA-COPY` does not copy a partial-slice write as a full-field constant.
  - `MOVE 7 TO WS-NUM` still emits a normal numeric constant, proving Phase 2.9 is a refusal gate rather than a global propagation shutdown.

#### Phase 2.10: PERFORM Transitive Kill

Problem:

```cobol
MOVE 10 TO WS-A
PERFORM SUB-PARA
MOVE WS-A TO WS-B

SUB-PARA.
    MOVE 99 TO WS-A
```

If the CFG explicitly routes execution through `SUB-PARA` before returning, the solver may already see the `MOVE 99 TO WS-A` node and kill `WS-A`. If the CFG models `PERFORM SUB-PARA` as a call-like node followed directly by the next statement, the callee write is invisible and `WS-A = 10` can survive incorrectly. The plan must not depend on an undocumented CFG-shape assumption.

Implementation:

- `StaticValueDataflowPass.java` now builds paragraph summaries before propagation and computes an internal map of paragraph name to transitive modified variables.
- The transitive map uses direct `variables_modified_direct` plus `calls_paragraphs` and reaches a deterministic fixed point over the paragraph-call graph.
- At a `PERFORM <paragraph>` node, the solver emits `PERFORM_TRANSITIVE_KILL` for every variable in the performed paragraph's transitive modified set.
- These kills only remove constants. They do not propagate constants through paragraph summaries.
- Existing paragraph-summary JSON remains source-preserving and conservative: transitive summary fields for paragraphs with performed targets are not rewritten into a completed summary. Phase 2.10 uses the same evidence internally for kills but does not pretend paragraph summaries are complete interprocedural summaries.

Tests:

- Add fixture `smojol-toolkit/test-code/flow-ast/perform-kill-phase210.cbl`.
- Add exact assertions in `JavaHardeningRegressionTest.java`:
  - `MOVE 10 TO WS-A; PERFORM SUB-PARA; MOVE WS-A TO WS-B` does not propagate `WS-A = 10` past the `PERFORM` when `SUB-PARA` writes `WS-A`.
  - Transitive case: `MAIN` performs `SUB-A`, `SUB-A` performs `SUB-B`, and `SUB-B` writes `WS-E`; the `PERFORM SUB-A` site kills `WS-E`.
  - No-write case: if the performed paragraph does not modify `WS-C`, `WS-C = 20` survives.
  - Paragraph-call cycles are handled by the same monotone fixed-point union of modified variables. Phase 2.10 does not emit a separate recursion diagnostic yet.

Acceptance:

- Status: `DONE`.
- The dataflow analysis version is now `1.8`.
- Focused check passed: `mvn -pl smojol-toolkit test -Dcheckstyle.skip=true -Dtest=JavaHardeningRegressionTest#dataflowKillsConstantsModifiedByPerformedParagraphs`, 1 test.
- Targeted check passed: `mvn -pl smojol-toolkit test -Dcheckstyle.skip=true -Dtest=JavaHardeningRegressionTest`, 52 tests.
- Broader check passed: `mvn -pl smojol-toolkit test -Dcheckstyle.skip=true`, 64 tests with 2 skipped.
- New fixture: `smojol-toolkit/test-code/flow-ast/perform-kill-phase210.cbl`.
- Exact behavior now locked:
  - `MOVE 10 TO WS-A; PERFORM SUB-PARA; MOVE WS-A TO WS-B` emits `PERFORM_TRANSITIVE_KILL@WS-A`, clears `WS-A`, and does not create `WS-B = 10`.
  - `MOVE 30 TO WS-E; PERFORM SUB-A; MOVE WS-E TO WS-F`, where `SUB-A` performs `SUB-B` and `SUB-B` writes `WS-E`, emits `PERFORM_TRANSITIVE_KILL@WS-E` and does not create `WS-F = 30`.
  - `MOVE 20 TO WS-C; PERFORM CLEAN-PARA; MOVE WS-C TO WS-D`, where `CLEAN-PARA` has no writes, emits no perform kill and still propagates `WS-D = 20`.

Examples:

```cobol
MOVE 10 TO WS-A
PERFORM SUB-PARA
MOVE WS-A TO WS-B

SUB-PARA.
    MOVE 99 TO WS-A.
```

The `PERFORM SUB-PARA` node now records `PERFORM_TRANSITIVE_KILL@WS-A`. `WS-A = 10` is present at the `PERFORM` entry, absent at its exit, and therefore cannot be copied into `WS-B`.

```cobol
MOVE 30 TO WS-E
PERFORM SUB-A
MOVE WS-E TO WS-F

SUB-A.
    PERFORM SUB-B.
SUB-B.
    MOVE 77 TO WS-E.
```

The kill is transitive: `SUB-A` itself only performs `SUB-B`, but `SUB-B` writes `WS-E`, so `PERFORM SUB-A` removes `WS-E` and `WS-F` is not inferred.

```cobol
MOVE 20 TO WS-C
PERFORM CLEAN-PARA
MOVE WS-C TO WS-D

CLEAN-PARA.
    DISPLAY "NO WRITE".
```

No `PERFORM_TRANSITIVE_KILL` is emitted because the performed paragraph does not modify `WS-C`; the known value survives and `WS-D = 20` can still be propagated.

#### Phase 2.11: Negative Hardening Matrix

Purpose:

These are not broad new propagation features. They lock known refusals and conservative kills so a future change cannot accidentally turn an unsupported COBOL construct into a wrong constant.

Required negative tests:

| Case | Expected behavior |
|---|---|
| `CALL` node with USING variables but missing `using_parameters` metadata | `DONE`: parse the raw `USING` phrase as a fallback, kill default/BY REFERENCE arguments, and preserve BY CONTENT/BY VALUE arguments. |
| `READ file` without explicit `INTO` | `DONE`: conservatively kill file-descriptor record-buffer variables so stale record constants cannot be copied after the read. |
| `INSPECT ... TALLYING WS-N ...` | `DONE`: kill the tallying output variable; `INSPECT ... REPLACING` still kills the inspected target. |
| EXEC SQL forms outside `SELECT/FETCH ... INTO` | `DONE`: SQL `RETURNING ... INTO :HOST-VAR` now kills host variables. Other SQL output forms remain documented future work unless their output syntax is explicitly recognized. |
| Multi-target `MOVE` forms | `DONE`: `MOVE 7 TO WS-MULTI-A WS-MULTI-B` emits both constants when each target is storage-safe. Multi-target `COMPUTE` remains a conservative non-feature unless folded facts are emitted per target. |
| `SET condition-name TO TRUE` for 88-levels | `DONE`: condition-name parent fields are killed using data-structure condition evidence; no stale parent value survives. |

Acceptance:

- Status: `DONE`.
- The dataflow analysis version is now `1.9`.
- Focused check passed: `mvn -pl smojol-toolkit test -Dcheckstyle.skip=true -Dtest=JavaHardeningRegressionTest#dataflowHardensKnownUnsupportedOutputAndConditionCases+dataflowKillsCallUsingReferenceWhenMetadataIsMissing+dataflowKillsSqlReturningIntoHostVariablesOutsideSelectFetch`, 3 tests.
- New fixture: `smojol-toolkit/test-code/flow-ast/negative-hardening-phase211.cbl`.
- Exact behavior now locked:
  - `READ IN-FILE` kills the file descriptor record `IN-REC`; `MOVE IN-REC TO WS-REC-COPY` does not copy stale `"AA"`.
  - `INSPECT WS-TEXT TALLYING WS-TALLY FOR ALL "A"` emits `INSPECT_TALLYING_KILL@WS-TALLY`; `MOVE WS-TALLY TO WS-TALLY-COPY` does not copy stale `3`.
  - A synthetic `EXEC SQL UPDATE ... RETURNING ... INTO :WS-SQL-RETURN` node emits `SQL_OUTPUT_KILL@WS-SQL-RETURN`; later copies do not propagate stale `4`.
  - `SET FLAG-ON TO TRUE` emits `SET_CONDITION_PARENT_KILL@WS-FLAG`; `MOVE WS-FLAG TO WS-FLAG-COPY` does not copy stale `"N"`.
  - A synthetic `CALL "SUBPROG" USING WS-REF BY CONTENT WS-CONTENT` node with missing structured metadata kills `WS-REF` by fallback parsing and preserves `WS-CONTENT`.
  - `MOVE 7 TO WS-MULTI-A WS-MULTI-B` emits constants for both targets.

Examples:

```cobol
MOVE "AA" TO IN-REC
READ IN-FILE
MOVE IN-REC TO WS-REC-COPY
```

The `READ` has no `INTO`, so the file record buffer may be overwritten. Phase 2.11 emits `READ_RECORD_BUFFER_KILL@IN-REC`; the later copy does not infer `WS-REC-COPY = "AA"`.

```cobol
MOVE 3 TO WS-TALLY
INSPECT WS-TEXT TALLYING WS-TALLY FOR ALL "A"
MOVE WS-TALLY TO WS-TALLY-COPY
```

The tallying variable is an output of `INSPECT`, so Phase 2.11 emits `INSPECT_TALLYING_KILL@WS-TALLY` and refuses the stale `WS-TALLY-COPY = 3` conclusion.

```cobol
MOVE "N" TO WS-FLAG
SET FLAG-ON TO TRUE
MOVE WS-FLAG TO WS-FLAG-COPY
```

`FLAG-ON` is an 88-level condition on `WS-FLAG`. Phase 2.11 kills the parent field with `SET_CONDITION_PARENT_KILL@WS-FLAG`; it does not try to synthesize the exact parent storage value for the condition.

#### Phase 2.12: Grammar-Backed Expression Propagation

Status: `DONE`.

Problem closed:

Before Phase 2.12, expression propagation used a small private parser over `originalText`. It was intentionally narrow and usually fail-closed, but it was still the wrong evidence source: formatting, continuation lines, and end phrases are source-text concerns, not expression-semantics concerns.

Implementation:

- `ComputeFlowNode.metadata()` now serializes a grammar-derived expression model into `dataflow_expression_facts`.
- The model is built from the same ANTLR `ArithmeticExpressionContext` used by local folding.
- The dataflow pass evaluates only this serialized model against node `entry_constants`.
- The old `DataflowExpressionEvaluator` text parser has been removed.
- `assignment_facts`, `folded_value_facts`, `folding_diagnostics`, `originalText`, CFG nodes, CFG edges, dynamic CALL/CICS metadata, and RAG chunks are unchanged except for the new additive metadata field.

Example metadata for:

```cobol
COMPUTE WS-E = WS-A + 5
```

Representative additive CFG metadata:

```json
{
  "dataflow_expression_facts": [
    {
      "schema_version": "1.0",
      "fact_type": "dataflow_expression",
      "statement_type": "COMPUTE",
      "target_variable": "WS-E",
      "original_expression": "WS-A+5",
      "expression": {
        "kind": "binary",
        "operator": "ADD",
        "left": {
          "kind": "variable",
          "name": "WS-A",
          "source_text": "WS-A"
        },
        "right": {
          "kind": "numeric_literal",
          "raw_lexeme": "5",
          "normalized_value": "5",
          "source_text": "5"
        },
        "source_text": "+5"
      },
      "provenance_source": "java_antlr_arithmetic_expression"
    }
  ]
}
```

Runtime use:

```cobol
MOVE 10 TO WS-A
COMPUTE WS-E = WS-A + 5
```

At the `COMPUTE` node, the solver reads `WS-A = 10` from `entry_constants`, evaluates the ANTLR-derived expression tree, checks that `WS-E` can represent `15`, and emits `WS-E = 15` in `exit_constants`.

Safety behavior:

- If `WS-A` is absent, killed, non-numeric, or branch-conflicted, no constant is emitted.
- If the expression tree contains a subscript, reference modification, function call, special register, exponentiation, unsupported literal, divide by zero, or non-terminating exact division, no dataflow expression fact is emitted or no constant is produced.
- `ROUNDED`, `ON SIZE ERROR`, and `NOT ON SIZE ERROR` still block propagation seeding.
- Target PIC gating still applies after expression evaluation.

#### Claim Gates

The project may use these claim levels:

| Claim | Allowed now? | Required wording |
|---|---|---|
| "The tool has constant folding." | Yes | "Closed numeric `COMPUTE` expression folding, source-preserving, BigDecimal-safe." |
| "The tool has scoped flow-sensitive constant facts." | Yes | "Intraprocedural CFG entry/exit constants with conservative kills and known limitations." |
| "The tool has COBOL constant propagation." | Partially | Allowed only with scoped wording: "intraprocedural flow-sensitive constant propagation with conservative kills for the documented subset." Do not call it full production COBOL propagation or interprocedural propagation. |
| "The RAG layer can safely summarize propagated constants." | Not yet | Blocked by explicit Phase 4.1 RAG chunk implementation/evaluation. |
| "The tool does compiler-style optimization." | No | Out of scope; the tool does not rewrite COBOL or CFG text. |

### Fool-Proof Execution Rules

1. Do not start a later step while an earlier required safety step is `PENDING` or `BLOCKED`.
2. Do not mark a step `DONE` unless its acceptance check is covered by an exact test, committed artifact, or measured report.
3. Do not silently expand scope. New supported COBOL constructs require this document to be updated first.
4. Do not silently drop scope. Skipped work must be marked `SKIPPED` with a reason.
5. Do not merge implementation if this ledger says `WORKING`, `PENDING`, or `BLOCKED` for the same deliverable.
6. Do not claim full production-ready constant propagation until `static_analysis/dataflow.json`, fixed-point CFG propagation, conservative merge rules, loop handling, alias kills, runtime-input kill rules, subscript/reference-modification refusal, `PERFORM` transitive kills, the Phase 2.11 negative hardening matrix, and grammar-backed expression propagation are all `DONE`. These are now complete for the documented subset, but the correct public wording remains intraprocedural flow-sensitive constant propagation with conservative kills, not full interprocedural or compiler-style COBOL optimization.
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

The current Phase 2.10 solver supports only these value-producing rules:

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

Phase 2.11 adds these hardening kills and refusals:

- `CALL ... USING ...` without structured `using_parameters` metadata falls back to raw-text parsing; default/BY REFERENCE arguments emit `CALL_USING_REFERENCE_KILL`, while BY CONTENT/BY VALUE arguments remain unchanged.
- `READ <file>` without explicit `INTO` emits `READ_RECORD_BUFFER_KILL` for file-descriptor record variables.
- `INSPECT ... TALLYING <identifier> ...` emits `INSPECT_TALLYING_KILL`.
- `EXEC SQL ... RETURNING ... INTO :<host-variable>` emits `SQL_OUTPUT_KILL`.
- `SET <88-level-condition> TO TRUE` emits `SET_CONDITION_PARENT_KILL` for the condition's parent field.
- `MOVE <literal> TO <target-a> <target-b>` emits one storage-safe constant per target; unsupported multi-target forms remain conservative non-features.

The current solver intentionally does not support function calls, string expressions, condition simplification, branch reachability pruning, interprocedural summaries, or RAG chunk generation. Phase 2.8 adds a conservative stored-value gate for simple numeric PICTURE forms (`S`, `9`, and `V`) and blocks propagation seeding for `ROUNDED` and size-error phrases. It still does not simulate COBOL rounding/truncation, edited numeric fields, `P` scaling, `COMP`, or `COMP-3`; unsupported storage forms produce no propagated numeric constant.

The former subscript/reference-modification blocker is now closed by Phase 2.9. For example:

```cobol
MOVE 5 TO WS-TBL(1)
MOVE WS-TBL(2) TO WS-X
MOVE "ABC" TO WS-AREA(1:3)
MOVE WS-AREA TO WS-AREA-COPY
MOVE 7 TO WS-NUM
```

The first statement may emit alias kills for `WS-TABLE`/`WS-TBL`, but it does not emit `WS-TBL = 5`, `WS-TBL(1) = 5`, or `WS-TBL(2) = 5`. The second statement therefore cannot copy a stale table-cell fact into `WS-X`. The third statement writes only a slice, so it does not emit `WS-AREA = "ABC"` and the fourth statement does not copy that partial write into `WS-AREA-COPY`. The final non-subscripted statement still emits `WS-NUM = 7`, proving the rule is a targeted safety refusal rather than a shutdown of ordinary propagation.

The former `PERFORM` transitive-write blocker is now closed by Phase 2.10. For example:

```cobol
MOVE 10 TO WS-A
PERFORM SUB-PARA
MOVE WS-A TO WS-B

SUB-PARA.
    MOVE 99 TO WS-A.
```

`PERFORM SUB-PARA` now emits a direct sidecar kill fact with `code: "PERFORM_TRANSITIVE_KILL"`, `variable: "WS-A"`, `kill_scope: "paragraph_transitive"`, and `performed_paragraph: "SUB-PARA"`. That removes `WS-A = 10` before the following `MOVE WS-A TO WS-B`, so the analyzer refuses the stale `WS-B = 10` conclusion.

The same rule follows paragraph-call chains:

```cobol
MOVE 30 TO WS-E
PERFORM SUB-A
MOVE WS-E TO WS-F

SUB-A.
    PERFORM SUB-B.
SUB-B.
    MOVE 77 TO WS-E.
```

Because `SUB-B` modifies `WS-E`, `SUB-A` is treated as transitively modifying `WS-E`, and the caller-side `PERFORM SUB-A` kills the old `WS-E = 30` fact. If the performed paragraph has no writes, no perform kill is emitted and ordinary propagation continues.

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

Historical Phase 2.6f artifact shape, shortened from fixture outputs and solver-level tests. The paragraph-summary, alias-summary, kill, propagated-constant, join-diagnostic, and loop-diagnostic examples may come from different checks because the checkpoints verify these shapes independently. Current reports use the latest analysis version and status from the most recent committed checkpoint; this example is kept only to explain the Phase 2.6f shape.

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

### Phase 3: Flow-Sensitive Dynamic CALL/CICS Resolution

Phase 3 uses the constants proven in `static_analysis/dataflow.json` to add flow-sensitive, per-CFG-node target facts beside the legacy dynamic `CALL` and CICS fields. It must not replace the old resolver. The legacy resolver in `SerialisableCFGGraphCollector.annotateDynamicCallResolution()` is order-based and writes fields such as `resolved_call_target`, `call_target_source`, `dynamic_call_resolution_confidence`, `resolved_cics_target`, `cics_target_source`, and `cics_dynamic_resolution_confidence`. Phase 3 keeps the committed `path_sensitive_` JSON prefix so downstream consumers can compare both views during a dual-emission window, but the analysis is not fully path-sensitive in the formal compiler sense because branch joins still merge facts into one node state.

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
- A flow-sensitive target fact may only be emitted from a `CONSTANT` value in the target node's dataflow `entry_constants`.
- If a runtime kill, alias kill, branch merge, or loop cycle removes the constant before the target node, the additive target fact must be unresolved.
- A high-confidence target fact may not be emitted from a dataflow constant that would be truncated by the target field PICTURE.
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
    "node_id": "node-123",
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

This is the safety property for Phase 3.1b: the additive flow-sensitive metadata may disagree with legacy metadata when dataflow proves the legacy global assignment is stale, but it does so only in new fields. No old `CALL` metadata key is removed or rewritten.

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

CICS statements can contain more than one identifier argument. Mutating legacy `cics_arguments` would make compatibility harder, so Phase 3.2b adds a separate array. The field prefix remains `path_sensitive_*` for compatibility with earlier checkpoints, but these facts are flow-sensitive/per-CFG-node facts backed by the merged `entry_constants` for the CICS node.

Phase 3.2b also closes the alphanumeric truncation gap before emitting new resolved argument values. The implementation point is the dataflow transfer rule for quoted `MOVE` literals and variable copies: do not store an `ALPHANUMERIC` `CONSTANT` in `entry_constants` or `exit_constants` if the receiving field has a known `PIC X(n)` and the normalized literal length is greater than `n`. The resolver then naturally sees no proven value and emits an unresolved dynamic target/argument rather than a wrong high-confidence target.

Implemented resolved field shape:

```json
{
  "path_sensitive_cics_arguments": [
    {
      "name": "QUEUE",
      "identifier": "WS-QUEUE",
      "resolution_status": "resolved",
      "resolved_value": "CUSTOMERQ",
      "value_kind": "ALPHANUMERIC",
      "source": "static_analysis.dataflow.entry_constants",
      "confidence": "high",
      "evidence": {
        "node_id": "<cfg-node-id>",
        "argument_name": "QUEUE",
        "entry_variable": "WS-QUEUE",
        "value_state": "CONSTANT",
        "value_kind": "ALPHANUMERIC",
        "dataflow_artifact": "static_analysis/dataflow.json"
      }
    }
  ]
}
```

Implemented unresolved field shape:

```json
{
  "path_sensitive_cics_arguments": [
    {
      "name": "QUEUE",
      "identifier": "WS-QUEUE-KILLED",
      "resolution_status": "unresolved",
      "source": "static_analysis.dataflow.entry_constants",
      "confidence": "none",
      "resolution_note": "No proven alphanumeric constant for WS-QUEUE-KILLED at CICS node entry."
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
- `path_sensitive_cics_arguments[0].resolution_status: "resolved"`
- `path_sensitive_cics_arguments[0].resolved_value: "CUSTOMERQ"`
- Existing `cics_arguments` array remains byte-for-byte equivalent except for unrelated pre-existing legacy fields.

Implemented negative tests through Phase 3.2c:

- Static `CALL "SUBPROG"` emits no `path_sensitive_call_*` fields.
- Literal CICS target such as `EXEC CICS LINK PROGRAM("LITPGM")` emits no `path_sensitive_cics_*` fields because no identifier needs dataflow resolution.
- Output-only CICS nodes such as `EXEC CICS RECEIVE INTO(WS-AREA)` are treated as kills, not target facts.
- A killed argument identifier, for example `MOVE "CUSTOMERQ" TO WS-QUEUE` followed by `ACCEPT WS-QUEUE` before `EXEC CICS READQ TS QUEUE(WS-QUEUE)`, does not emit a stale resolved argument.
- An overlength alphanumeric assignment such as `MOVE "LONGERTHAN8" TO WS-PGM` where `WS-PGM PIC X(8)` does not produce a high-confidence target or argument value.
- Unsupported CICS argument names such as `RESP(WS-RESP)` are ignored by `path_sensitive_cics_arguments` even when `WS-RESP` has a proven alphanumeric constant.
- A real two-predecessor dataflow join where one incoming path proves `WS-PGM = "PROG-A"` and another proves `WS-PGM = "PROG-B"` leaves the later `CALL WS-PGM` unresolved and emits `DATAFLOW_CONSTANT_DROPPED_AT_JOIN`.

Unsupported CICS argument example:

```cobol
MOVE "CICSRSP" TO WS-CICS-PGM
MOVE "RESPVAL" TO WS-RESP
EXEC CICS LINK PROGRAM(WS-CICS-PGM)
     RESP(WS-RESP)
END-EXEC
```

Expected result:

- `PROGRAM(WS-CICS-PGM)` can produce a resolved `path_sensitive_cics_target`.
- `path_sensitive_cics_arguments` can include `PROGRAM`.
- `RESP(WS-RESP)` remains only in the legacy `cics_arguments` evidence and is not copied into `path_sensitive_cics_arguments`, because `RESP` is an output/status field rather than a resource selector.

Conflicting join example:

```cobol
*> Path A
MOVE "PROG-A" TO WS-PGM

*> Path B
MOVE "PROG-B" TO WS-PGM

*> Join
CALL WS-PGM
```

Expected result:

- The joined `CALL WS-PGM` entry state does not contain `WS-PGM`.
- The join node records `DATAFLOW_CONSTANT_DROPPED_AT_JOIN` with incoming values `PROG-A` and `PROG-B`.
- The CALL metadata has `path_sensitive_call_resolution_status: "unresolved"` and no `path_sensitive_call_target`.

Committed Phase 3.2b examples:

```cobol
MOVE "CUSTOMERQ" TO WS-QUEUE
EXEC CICS READQ TS QUEUE(WS-QUEUE)
     INTO(WS-AREA)
END-EXEC
```

The CICS node now has both the legacy resolver's nested argument data and the new flow-sensitive argument view:

```json
{
  "path_sensitive_cics_target": "CUSTOMERQ",
  "path_sensitive_cics_arguments": [
    {
      "name": "QUEUE",
      "identifier": "WS-QUEUE",
      "resolution_status": "resolved",
      "resolved_value": "CUSTOMERQ",
      "value_kind": "ALPHANUMERIC",
      "source": "static_analysis.dataflow.entry_constants",
      "confidence": "high"
    }
  ],
  "cics_arguments": [
    {
      "name": "QUEUE",
      "value": "WS-QUEUE",
      "value_source": "identifier",
      "resolved_value": "CUSTOMERQ",
      "resolved_value_source": "inferred_literal_assignment"
    },
    {
      "name": "INTO",
      "value": "WS-AREA",
      "value_source": "identifier"
    }
  ]
}
```

The `INTO(WS-AREA)` argument is not placed in `path_sensitive_cics_arguments` because it is an output location, not a target/resource selector. The runtime-output kill rule still removes any prior `WS-AREA` constant at the `RECEIVE`/`READQ` exit.

Killed argument example:

```cobol
MOVE "KILLQ" TO WS-QUEUE-KILLED
ACCEPT WS-QUEUE-KILLED
EXEC CICS READQ TS QUEUE(WS-QUEUE-KILLED)
     INTO(WS-AREA)
END-EXEC
```

The legacy metadata can still report the stale order-based literal `KILLQ`, but the new flow-sensitive view refuses to reuse it:

```json
{
  "resolved_cics_target": "KILLQ",
  "path_sensitive_cics_resolution_status": "unresolved",
  "path_sensitive_cics_arguments": [
    {
      "name": "QUEUE",
      "identifier": "WS-QUEUE-KILLED",
      "resolution_status": "unresolved",
      "source": "static_analysis.dataflow.entry_constants",
      "confidence": "none"
    }
  ]
}
```

Alphanumeric length-gate example:

```cobol
01 WS-LONG-PGM PIC X(8).
...
MOVE "LONGERTHAN8" TO WS-LONG-PGM
CALL WS-LONG-PGM
```

The string literal has 11 characters and the target field has `PIC X(8)`. Phase 3.2b therefore does not put `WS-LONG-PGM` in `exit_constants`, and the later `CALL WS-LONG-PGM` receives no proven entry constant:

```json
{
  "resolved_call_target": "LONGERTHAN8",
  "path_sensitive_call_resolution_status": "unresolved",
  "path_sensitive_call_resolution_note": "No proven alphanumeric constant for WS-LONG-PGM at CALL node entry."
}
```

#### Phase 3.3: Accuracy And Performance Evaluation

Phase 3.3 is the first point where the project may claim improved dynamic target resolution. Numeric PICTURE gating is complete for simple `S`/`9`/`V` PICTUREs as of Phase 2.8, the alphanumeric `PIC X(n)` length gate is complete as of Phase 3.2b, and the Phase 3 negative/join-path tests are complete as of Phase 3.2c. This checkpoint is measurement-only: it does not add resolver behavior.

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

- `2.8` PIC-aware numeric value gating is complete.
- `3.2b` alphanumeric length gating and CICS argument facts are complete.
- `3.2c` negative and join-path tests are complete.
- Every expected dynamic `CALL` in the Phase 3 fixture has the exact expected `path_sensitive_call_*` result.
- Every expected CICS identifier target/argument in the Phase 3 fixture has the exact expected `path_sensitive_cics_*` result.
- At least one negative runtime-kill case proves no stale path-sensitive target is emitted.
- At least one overlength `PIC X(n)` case proves no truncated target is emitted as a high-confidence path-sensitive value.
- At least one numeric target-PICTURE mismatch proves no non-representable numeric constant is emitted in `exit_constants`.
- Existing Stage 1 legacy dynamic `CALL` and CICS tests still pass without changing their expected legacy values.
- Existing Phase 2 dataflow tests still pass.
- No RAG chunk tests are changed in Phase 3.
- No dependency chunk output is changed in Phase 3.
- `path_sensitive_targets_enabled` is `true` only after the path-sensitive annotator is active.

Measured fixture: `smojol-toolkit/test-code/flow-ast/path-sensitive-targets-phase3.cbl`.

Accuracy results:

| Surface | Measured nodes | Legacy behavior | Flow-sensitive behavior | Reliability result |
|---|---:|---|---|---|
| Dynamic `CALL` identifier targets | 4 | Resolves all 4, including 2 unsafe cases: one runtime-killed identifier and one overlength `PIC X(8)` literal. | Resolves the 2 proven calls and marks the 2 unsafe calls unresolved. | Legacy reliable outcomes: 2/4. Flow-sensitive reliable outcomes: 4/4. |
| CICS identifier targets | 6 | Resolves all 6, including 2 runtime-killed stale targets. | Resolves the 4 proven CICS targets and marks the 2 killed targets unresolved. | Legacy reliable outcomes: 4/6. Flow-sensitive reliable outcomes: 6/6. |
| Supported CICS selector arguments | 6 | Resolves all 6 selector identifiers, including the same 2 runtime-killed stale selectors. | Emits 6 additive argument entries: 4 resolved and 2 unresolved. | Legacy reliable outcomes: 4/6. Flow-sensitive reliable outcomes: 6/6. |
| Static/literal/output negative cases | 3 categories | Static `CALL`, literal CICS target, and output-only CICS node stay in legacy metadata. | Emits 0 flow-sensitive fields for static `CALL`, 0 for literal CICS target, and 0 target/argument fields for output-only `RECEIVE INTO`. | No over-resolution observed. |
| Unsupported/output CICS identifier arguments | 8 legacy identifier arguments | Legacy `cics_arguments` keeps the evidence for `COMMAREA`, `INTO`, and `RESP`. | `path_sensitive_cics_arguments` ignores all 8 because they are not resource selectors. | No unsupported argument is promoted to a high-confidence target fact. |

Artifact and runtime results:

| Measurement | Phase 3.2b | Phase 3.2c/3.3 fixture | Delta | Interpretation |
|---|---:|---:|---:|---|
| Dataflow sidecar size | 31,579 bytes | 35,073 bytes | +3,494 bytes | Not an apples-to-apples overhead figure: the fixture gained the `RESP(WS-RESP)` CICS case. |
| CFG JSON size | 98,071 bytes | 110,187 bytes | +12,116 bytes | Mostly from the added CICS node and additive metadata needed to test ignored `RESP`. |
| Targeted `JavaHardeningRegressionTest` runtime | 25.387s, 47 tests | 33.864s, 50 tests | +8.477s | Includes three additional exact regression tests and a longer fixture. |
| Broader `smojol-toolkit` runtime | 26.412s, 59 tests, 2 skipped | 30.927s, 62 tests, 2 skipped | +4.515s | Test-suite level signal only; not a standalone analyzer benchmark. |

Interpretation:

- The flow-sensitive fields intentionally resolve fewer raw targets than the legacy resolver.
- The improvement is reliability, not aggressive resolution count. Unsafe stale or storage-truncated values become explicit unresolved facts instead of high-confidence targets.
- Legacy fields remain useful compatibility evidence, but they are not safe enough for later RAG claims without the new flow-sensitive fields and provenance.
- Phase 4 RAG may now start from the high-confidence resolved flow-sensitive facts, but it must still exclude unresolved facts from "known target" wording and must include provenance.

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
4. `3.2b`: path-sensitive CICS argument array plus alphanumeric `PIC X(n)` length gating.
5. `3.2c`: negative and join-path tests for CALL/CICS target over-resolution.
6. `2.8`: numeric target-PICTURE and `ROUNDED`/size-error propagation gating before accuracy claims.
7. `3.3`: metrics and documentation only, blocked until `3.2c` is done.

Do not combine `3.1a` and `3.1b` unless the first checkpoint cannot be tested independently. Do not start CICS until dynamic `CALL` fields are proven additive and legacy-safe.

### Phase 4: RAG Integration

Phase 4 includes:

- Screen-key synonym support for natural terms such as `PF7`/`PF8` alongside exact CICS constants such as `DFHPF7`/`DFHPF8`.
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

`FOLD_UNSAFE_SIZE_ERROR_SEMANTICS` is currently reserved. The Phase 1 folder sees the arithmetic expression, not the full statement suffix, so statement-level `ON SIZE ERROR` handling must be implemented before this diagnostic can be claimed as emitted.

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
| Incorrect stored-value constants | Before Phase 3.3 or RAG, gate all dataflow constants by target PICTURE; if scale, integer digits, sign, or alphanumeric length are not provably safe, emit no `CONSTANT`. |
| Conditional arithmetic semantics | `ROUNDED`, `ON SIZE ERROR`, and `NOT ON SIZE ERROR` may still have local expression facts but must not seed variable propagation until COBOL storage semantics are modeled. |
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
- Numeric stored-value facts are gated by simple target PICTUREs built from `S`, `9`, and `V`; values that would require truncation, rounding, sign loss, or scale loss are not emitted.
- `ACCEPT`, `CALL USING` by reference, `INITIALIZE`, `READ INTO`, `STRING INTO`, `UNSTRING INTO`, `INSPECT`, CICS output arguments, SQL `SELECT/FETCH ... INTO`, and alias-overlapping writes kill affected constants.
- Real branch joins drop conflicting constants and emit `DATAFLOW_CONSTANT_DROPPED_AT_JOIN`.
- CFG cycles with modified variables emit `DATAFLOW_LOOP_CARRIED_CONSTANT_NOT_INFERRED` instead of inventing final loop values.

Example: PICTURE-gated numeric constants:

```cobol
01 WS-INT     PIC 9.
01 WS-FIT-DEC PIC 9V9.
01 WS-SIGNED  PIC S9(2).
...
COMPUTE WS-INT = 7 / 2
COMPUTE WS-FIT-DEC = 7 / 2
COMPUTE WS-SIGNED = 0 - 1
```

The local folding layer can still report that `7 / 2` is the expression value `3.5`. The dataflow layer is stricter: it does not put `WS-INT = 3.5` in `exit_constants` because `PIC 9` cannot represent the fractional digit. It does put `WS-FIT-DEC = 3.5` in `exit_constants` because `PIC 9V9` can represent one integer digit and one fractional digit. It also allows `WS-SIGNED = -1` because `S9(2)` is signed, while the same value into an unsigned `PIC 9(2)` is refused.

Size-error and rounding phrases are also propagation blockers:

```cobol
COMPUTE WS-SIZE = 1 + 2
    ON SIZE ERROR
        MOVE 0 TO WS-SIZE
END-COMPUTE
COMPUTE WS-ROUNDED ROUNDED = 1 / 4
```

These statements may still carry local expression facts, but Phase 2.8 does not seed stored-value constants from them because final storage depends on COBOL size-error or rounding semantics that are not modeled yet.

Still not implemented:

- Full COBOL loop trip-count reasoning or final loop-value inference.
- `IF`/`EVALUATE` condition simplification or branch reachability pruning.
- General string expression propagation. Narrow quoted alphanumeric `MOVE` and variable-copy propagation exists for Phase 3 target resolution and is now length-gated when the receiving field has a known `PIC X(n)`, but COBOL string functions, reference modification, figurative expansion, and national/hex literals remain unsupported.
- Group move expansion into child fields.
- Edited numeric, `P` scaling, `COMP`, or `COMP-3` storage semantics. Simple display numeric PICTURE fit-gating exists, but the analyzer still does not simulate COBOL storage conversion.
- Interprocedural propagation through called programs.
- Full formal path-sensitive analysis that keeps distinct facts per execution path after joins. The current `path_sensitive_*` fields are additive flow-sensitive/per-CFG-node facts.
- Some kill patterns, including `INSPECT ... TALLYING IN` output variables and file record buffers modified by `READ` without explicit `INTO`.
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
