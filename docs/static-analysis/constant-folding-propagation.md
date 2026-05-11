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
          },
          "figurative": null,
          "type_context": null
        },
        "confidence": "high",
        "provenance_source": "java_static_value_folded_expression"
      }
    ],
    "folding_diagnostics": []
  }
}
```

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

Phase 2 includes:

- `static_analysis/dataflow.json`.
- Node entry and exit constants.
- Fixed-point worklist solver.
- Conservative merge rules.
- Conservative kill rules.
- Loop handling.
- Alias kills.
- Paragraph summaries.
- Diagnostics.

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
- `READ`, `ACCEPT`, CICS, and SQL outputs: runtime-dependent, killed or marked unknown.
- `REDEFINES`, group, OCCURS, and reference-modification ambiguity: conservative kill.

## 12. Before/After Improvement Table

| COBOL input | Before | After Phase 1 | After Phase 2 |
|---|---|---|---|
| `COMPUTE WS-A = 1 + 2` | no folded fact | folded value `3` | same |
| `COMPUTE WS-B = WS-A + 1` | no explanation | diagnostic: variable reference unsupported | may fold if `WS-A` proven constant |
| `COMPUTE WS-C = 1 / 0` | no explanation | diagnostic: divide by zero | same |
| `MOVE 7 TO WS-D` | assignment fact exists | unchanged | may become propagated entry/exit fact |
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

The tool includes constant propagation only if all of these are true:

- A `static_analysis/dataflow.json` artifact is emitted.
- The artifact has schema version and analysis version.
- Each CFG node can have entry and exit constants.
- A simple program works:

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
- Different values on different branches produce `UNKNOWN` with merge diagnostic.
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
       PROCEDURE DIVISION.
       MAIN-PARA.
           COMPUTE WS-A = 1 + 2
           COMPUTE WS-B = WS-A + 1
           COMPUTE WS-C = 1 / 0
           MOVE 7 TO WS-D
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

Phase 2 propagation stats should include:

- Number of CFG nodes analyzed.
- Number of variables tracked.
- Number of fixed-point iterations.
- Whether convergence was reached.
- Number of constants proven at node entry and exit.
- Number of values degraded to `UNKNOWN` at joins.
- Number of kills by reason.
- Runtime and memory overhead.

Accuracy evaluation should report:

- True folded facts on golden fixtures.
- Correct diagnostics for unsupported and unsafe expressions.
- No regressions in existing Java hardening tests.
- No behavior changes in dynamic `CALL` and CICS legacy fields until path-sensitive fields are explicitly added.
- For later phases, precision/recall of path-sensitive dynamic target resolution on a frozen fixture set.

Performance evaluation should report before/after timings on the same fixture set used by the benchmark harness when possible. If performance worsens, the implementation must explain the cost and provide a limit or configuration switch.
