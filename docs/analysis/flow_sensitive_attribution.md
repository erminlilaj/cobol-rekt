# Flow-Sensitive Target Attribution

This report enumerates dynamic CALL targets and CICS resource arguments that the flow-sensitive resolver considered in PDB305 and PDCBVC.

The JSON artifacts are also written to each report directory at `static_analysis/flow_sensitive_attribution.json`. Field names retain the historical `path_sensitive_*` compatibility wording in source metadata, but the semantics are flow-sensitive CFG entry-state resolution.

## Cause Distribution

| Program | Sites | Cause | Count |
|---|---:|---|---:|
| `PDB305.CBL` | 1 | `no_assignment_found` | 1 |
| `PDCBVC.CBL` | 1 | `missing_cfg_metadata` | 1 |

## Site Table

| Program | Line | Kind | Operation | Argument | Identifier | Status | Cause | Evidence |
|---|---:|---|---|---|---|---|---|---|
| `PDB305.CBL` | 3094 | `cics_resource_argument` | `WRITEQ` | `QUEUE` | `TWCOB-TS-CODA` | `unresolved` | `no_assignment_found` | No entry constant and no static VALUE/assignment evidence for this identifier was found in the report artifacts. Node transfer kills after entry: UNMODELED_STATEMENT_KILL_ALL. |
| `PDCBVC.CBL` | 2861 | `dynamic_call_target` | `CALL` | `CALL_TARGET` | `PXRSEMAF` | `unresolved` | `missing_cfg_metadata` | Static-value chunks show a declaration/static value, but the flow-sensitive entry map does not seed that value at this CFG node. Static values: 'PXRSEMAF'. Node transfer kills after entry: CALL_USING_REFERENCE_KILL. |

## Summary

- PDB305 has one CICS QUEUE variable site, `TWCOB-TS-CODA`, at line 3094. It has no entry constant and no static assignment evidence; the dominant cause is `no_assignment_found`.
- PDCBVC has one dynamic CALL target identifier, `PXRSEMAF`, at line 2861 in the generated CFG. Static-value chunks show `VALUE 'PXRSEMAF'`, but the flow-sensitive dataflow entry map does not seed declaration VALUE constants, so the cause is `missing_cfg_metadata`.
- No site in these two programs is currently classified as `resolved`, `killed_by(...)`, `conflicting_join(values)`, `pic_rejected(...)`, `unsupported_expression`, or `loop_carried`.
