# Raw Dataflow Sidecar Redesign Audit

Task 2 validates and fixes the raw `static_analysis/dataflow.json` size problem without changing the compact `static_analysis/dataflow_rag_summary.json` schema.

## Finding

The raw sidecar was dominated by materialized kill records. Each killed variable emitted a full JSON object at the CFG node, repeating the same statement metadata, source location, reason code, alias-set id, alias kind, and kill scope for every alias member.

| Program | CFG nodes | Materialized kills before redesign | Dominant duplicated code |
| --- | ---: | ---: | --- |
| PDB305 | 636 | 4,168,761 | `ALIAS_CONSERVATIVE_KILL` = 4,168,571 |
| PDCBVC | 922 | 7,191,753 | `ALIAS_CONSERVATIVE_KILL` = 7,191,491 |

The user-provided pre-Task-1 baseline was PDB305 at about 4.17M kills and PDCBVC at about 4.66M kills. After Task 1's conservative unmodeled-statement kill-all behavior, PDCBVC rose to 7.19M kills because the new sound fallback correctly kills many aliased variables instead of preserving constants.

## Redesign

The full raw sidecar is now opt-in behind `--emit-full-dataflow`; default analysis writes only `static_analysis/dataflow_rag_summary.json` and deletes any stale `static_analysis/dataflow.json`.

When enabled, the raw sidecar uses:

- `storage_model: "kill_rule_compacted"`
- top-level `kill_rules`: one rule per unique statement/reason/source/alias scope
- top-level `alias_sets`: alias-set members stored once
- per-node `kill_rule_refs`: references to shared rules, not materialized per-variable kill objects
- `materialized_kill_count`: the original logical kill count retained for audits
- unchanged compact summary fields: `schema_version`, `analysis_version`, `source_artifact`, `summary`, `node_states`, `rag_compacted`

For alias kills, rules use `killed_alias_set_id` instead of repeating the alias member list. Non-alias rules that kill specific variables use `killed_variables`.

## Size Results

Measured on 2026-06-11 after rebuilding `smojol-cli` and running the real programs with `--emit-full-dataflow`.

| Program | Heap | Raw sidecar | Compact summary | Materialized kills | Kill rules | Alias sets | Result |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| PDB305 | 6g | 22,920,872 bytes | 155,690 bytes | 4,168,761 | 5,436 | 220 | under 50 MB |
| PDCBVC | 10g | 20,406,702 bytes | 262,890 bytes | 7,191,753 | 9,890 | 201 | under 50 MB |

PDCBVC full-sidecar emission failed with `OutOfMemoryError: Java heap space` at 6g and completed at 10g. This only affects the opt-in raw sidecar measurement path; the default raw-off path avoids this storage expansion.

## Rule Distribution

| Program | `ALIAS_CONSERVATIVE_KILL` rules | Other rules |
| --- | ---: | --- |
| PDB305 | 5,372 | `PERFORM_TRANSITIVE_KILL` 27, `UNMODELED_STATEMENT_KILL_ALL` 27, `SQL_OUTPUT_KILL` 10 |
| PDCBVC | 9,818 | `PERFORM_TRANSITIVE_KILL` 37, `UNMODELED_STATEMENT_KILL_ALL` 23, `SQL_OUTPUT_KILL` 10, `CALL_USING_REFERENCE_KILL` 1, `INITIALIZE_TARGET_KILL` 1 |

## Regression Coverage

`JavaHardeningRegressionTest` now asserts:

- default `WRITE_CFG` suppresses raw `dataflow.json`
- compact `dataflow_rag_summary.json` remains present by default
- full dataflow uses `kill_rule_refs` instead of per-node `kills`
- raw sidecar `summary` equals compact summary `summary`
- `materialized_kill_count` equals logical `summary.kill_count`

