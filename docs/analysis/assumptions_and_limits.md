# Static Analysis Assumptions and Limits

This document records the conservative assumptions for the constant-folding and flow-sensitive propagation branch before merge.

## Semantics

- The analysis assumes default IBM-style COBOL behavior only at a broad source level. Compiler options such as `TRUNC`, `ARITH`, `NUMPROC`, sign handling, and packed/binary arithmetic edge cases are not modeled.
- `DECIMAL-POINT IS COMMA` is not modeled by the static expression folder. Some upstream literal extraction can preserve comma-bearing literals, but folding/propagation must not claim compiler-accurate decimal-comma arithmetic.
- PIC gating refuses unsafe constants. It does not truncate, round, or emit a value that would need target-size coercion to fit the receiving PIC.
- `USAGE COMP`, `COMP-3`, and DISPLAY storage are not simulated at the byte/arithmetic level. A value can be propagated only when the existing kind/PIC gates prove it safe at the source level.
- LINKAGE SECTION and DFHCOMMAREA-like externally supplied fields must not be treated as trusted initial constants unless a local statement proves a value at the CFG entry being analyzed.

## CFG Scope

- The propagation unit is one COBOL program/report at a time. The pass is intraprocedural: `CALL BY REFERENCE` arguments are conservatively killed, and no constants are propagated into or back from another program.
- Paragraph fall-through and ordinary CFG edges are represented by the Java CFG graph used by the dataflow pass. The analysis relies on those emitted edges; parse or CFG gaps are fact gaps.
- `PERFORM` target modification summaries are modeled conservatively enough to kill caller constants modified by performed paragraphs, including transitive performed targets.
- There is no PERFORM call-stack model. A `GO TO` out of a performed range is not modeled with COBOL runtime stack semantics; constants are killed/refused rather than justified through that path-sensitive behavior.
- DECLARATIVES do not have dedicated CFG exception/error edges in this pass.
- CICS `HANDLE CONDITION`, `HANDLE AID`, and ABEND/error transfer behavior may be parsed or preserved as metadata/text, but they are not modeled as CFG control-transfer edges.
- CICS command nodes are metadata-bearing DIALECT nodes. Unsupported or mutating CICS statements that lack modeled modified-variable metadata are treated conservatively by the unmodeled-statement kill-all fallback.

## Parsing and Copybooks

- COBOL parsing uses the repository's Java/ANTLR path backed by the Eclipse Che4z COBOL grammar submodule. Dialect is passed as `COBOL`; the pipeline does not auto-detect a more permissive dialect.
- Copybooks that are resolved before Java parsing are visible to the AST/CFG and alias analysis, including REDEFINES relationships present in the expanded source.
- Missing copybooks can be stubbed by the pipeline to keep analysis running. Stubbed copybooks hide any real fields, REDEFINES, VALUE clauses, and aliases that would have appeared in the original copybook.
- Facts from programs with detectable stubbed or missing copybooks should be treated as degraded confidence for aliasing, PIC gating, static values, and target attribution. The current artifacts do not upgrade those facts to high confidence merely because the program parsed.
- Parse failures and unsupported statements are soundness risks. The propagation pass now kills all current constants for executable unmodeled/unknown empty-modification statements and emits diagnostics, but a parse failure before CFG construction can still remove facts from the artifact set.

## Flow-Sensitive Targets

- Metadata field names containing `path_sensitive_*` are retained for compatibility. Their current semantics are flow-sensitive CFG entry-state resolution, recorded explicitly as `semantics: "flow-sensitive"` in new evidence artifacts.
- Dynamic CALL and CICS resource-target resolution only uses proven alphanumeric constants in the dataflow entry map for that CFG node.
- Declaration `VALUE` clauses are visible in static-value chunks, but they are not currently seeded as initial facts in the flow-sensitive dataflow entry map. Task 4 found this exact gap for PDCBVC `CALL PXRSEMAF`.
- The resolver preserves unresolved identifiers as low-confidence metadata; that is not the same as a proven propagated constant.

## Conservative Invariant

When analysis cannot prove a constant under these assumptions, it must refuse the propagation, kill the affected value when a mutating statement may invalidate it, and emit diagnostic/evidence where possible. Favorable metrics must not override this invariant.
