# Unknown Statement Soundness Audit

Date: 2026-06-11

Scope: Task 1 pre-merge hardening for source-preserving constant folding and CFG-based constant propagation.

## Method

The propagation pass reads `SerialisableCFGFlowNode.variablesModified`. The serializer stores an empty list as `null`, and the dataflow pass normalizes `null` to an empty list through `sortedStrings(...)`. Before this hardening pass, a node with no modeled modified variables and no special kill rule preserved the incoming constant map by default.

The new rule is deliberately narrower than "every empty node kills everything":

- If a node has no `variablesModified` entries,
- and the statement type is classified below as mutating but unmodeled or unknown,
- and the existing propagation rules did not already emit a direct variable kill,
- then the transfer function clears the current constant map at that node.

The emitted kill fact has:

- `code: UNMODELED_STATEMENT_KILL_ALL`
- `reason: unmodeled_statement`
- `kill_scope: all_constants`
- `confidence: conservative`
- `statement_type`, `statement_classification`, and source location when available

The same node also receives diagnostic:

- `code: DATAFLOW_UNMODELED_STATEMENT_KILL_ALL`
- `severity: warning`
- `category: soundness`
- `reason: unmodeled_statement`

This keeps structural CFG nodes from destroying facts, while executable statements that look like missing write semantics stop propagating stale constants.

## Full Classification

Classification key:

- `(a)` genuinely non-mutating for the current constant map, or handled by a more specific modeled rule.
- `(b)` mutating but unmodeled when `variablesModified` is empty and no direct kill was emitted.
- `(c)` unknown semantics.

| Flow node type | Class | Propagation action |
| --- | --- | --- |
| `ACCEPT` | (b) | Direct target kill when parsed; otherwise kill-all fallback. |
| `ADD` | (b) | Normal modified-variable extraction when available; otherwise kill-all fallback. |
| `ALTER` | (b) | Kill-all fallback because it mutates control-flow state outside the value model. |
| `ATOMIC` | (c) | Kill-all fallback. |
| `AT_END_PHRASE` | (a) | Structural/control wrapper; no kill-all. |
| `BIND_RUN_UNIT` | (b) | Kill-all fallback. |
| `CALL` | (a) | `CALL USING BY REFERENCE` variables are modeled by `CALL_USING_REFERENCE_KILL`; no kill-all for a call with no local reference arguments. |
| `CANCEL` | (a) | External program state effect only; no current-program constant-map kill. |
| `CLOSE` | (b) | Kill-all fallback because file status/state effects are not mapped to variables. |
| `COMPOSITE` | (a) | Structural wrapper; no kill-all. |
| `COMPUTE` | (b) | Normal modified-variable extraction/expression propagation when available; otherwise kill-all fallback. |
| `CONDITION_CLAUSE` | (a) | Structural condition node; no kill-all. |
| `CONDITIONAL_STATEMENT` | (a) | Delegates to actual statement when available; wrapper itself has no kill-all. |
| `CONTINUE` | (a) | No-op statement; no kill-all. |
| `CONTROL_FLOW` | (a) | Control marker; no kill-all. |
| `DELETE` | (b) | Kill-all fallback because file status/state effects are not mapped to variables. |
| `DIALECT` | (b) | CICS/SQL output kills when modeled; otherwise kill-all fallback for unmodeled dialect statements. |
| `DIALECT_CONTAINER` | (a) | Structural dialect wrapper; no kill-all. |
| `DISPLAY` | (a) | Output-only for current program variables; no kill-all. |
| `DIVIDE` | (b) | Normal modified-variable extraction when available; otherwise kill-all fallback. |
| `DUMMY` | (a) | Placeholder node; no kill-all. |
| `EVALUATE` | (a) | Branching construct; no direct data mutation at wrapper node. |
| `EVALUATE_BRANCH` | (a) | Branch wrapper; no kill-all. |
| `EXIT` | (a) | Control termination/return marker; no kill-all. |
| `FINISH` | (b) | Kill-all fallback. |
| `GENERIC_PROCESSING` | (a) | Generated processing wrapper; no kill-all. |
| `GENERIC_STATEMENT` | (c) | Kill-all fallback. |
| `GOTO` | (a) | Control transfer; no local data mutation. |
| `IF_BRANCH` | (a) | Branching construct; no direct data mutation at wrapper node. |
| `IF_NO` | (a) | Branch label; no kill-all. |
| `IF_YES` | (a) | Branch label; no kill-all. |
| `INITIALIZE` | (b) | Direct target kill when parsed; otherwise kill-all fallback. |
| `INSPECT` | (b) | `REPLACING`/`TALLYING` kills when modeled; otherwise kill-all fallback. |
| `JSON` | (b) | Kill-all fallback for unmodeled JSON statement semantics. |
| `MERGE` | (b) | Kill-all fallback for unmodeled file/output effects. |
| `MOVE` | (b) | Normal modified-variable extraction/value propagation when available; otherwise kill-all fallback. |
| `MULTIPLY` | (b) | Normal modified-variable extraction when available; otherwise kill-all fallback. |
| `NEXT_SENTENCE` | (a) | Control transfer; no local data mutation. |
| `ON_CLAUSE` | (a) | Control/handler wrapper; no kill-all. |
| `ON_CLAUSE_ACTION` | (a) | Handler action wrapper; child actions carry data effects. |
| `OPEN` | (b) | Kill-all fallback because file status/state effects are not mapped to variables. |
| `PARAGRAPH` | (a) | Structural summary node; no kill-all. |
| `PARAGRAPH_NAME` | (a) | Label node; no kill-all. |
| `PARAGRAPHS` | (a) | Structural wrapper; no kill-all. |
| `PERFORM` | (a) | Node-local control transfer; performed paragraph mutations are modeled by `PERFORM_TRANSITIVE_KILL` when targets resolve. |
| `PERFORM_TEST` | (a) | Loop/control test; no direct data mutation. |
| `PROCEDURE_DIVISION_BODY` | (a) | Structural wrapper; no kill-all. |
| `READ` | (b) | `INTO` or record-buffer kills when modeled; otherwise kill-all fallback. |
| `RELEASE` | (b) | Kill-all fallback for unmodeled sort/file effects. |
| `RETURN` | (b) | Kill-all fallback for unmodeled file/record effects. |
| `REWRITE` | (b) | Kill-all fallback for unmodeled file/status effects. |
| `SEARCH` | (a) | Control/search wrapper; child statements carry data effects. |
| `SEARCH_WHEN` | (a) | Search branch wrapper; no kill-all. |
| `SECTION` | (a) | Structural node; no kill-all. |
| `SECTION_HEADER` | (a) | Label node; no kill-all. |
| `SENTENCE` | (a) | Structural wrapper; no kill-all. |
| `SET` | (b) | Condition-parent kill/value extraction when modeled; otherwise kill-all fallback. |
| `SORT` | (b) | Kill-all fallback for unmodeled sort/file effects. |
| `START` | (b) | Kill-all fallback for unmodeled file/status effects. |
| `STOP` | (a) | Program termination; no local data mutation after the node. |
| `STRING` | (b) | `INTO` target kill when parsed; otherwise kill-all fallback. |
| `SUBTRACT` | (b) | Normal modified-variable extraction when available; otherwise kill-all fallback. |
| `SYMBOL` | (a) | Label/symbol node; no kill-all. |
| `TRANSFER` | (b) | Kill-all fallback for unmodeled external/control transfer semantics. |
| `UNSTRING` | (b) | `INTO` target kill when parsed; otherwise kill-all fallback. |
| `WRITE` | (b) | Kill-all fallback for unmodeled file/status effects. |
| `XML_GENERATE` | (b) | Kill-all fallback for unmodeled XML output semantics. |
| `XML_PARSE` | (b) | Kill-all fallback for unmodeled XML parse/input semantics. |

Known boundary: `PERFORM` is not treated as an unknown statement. The pass uses resolved paragraph targets and paragraph modified-variable summaries to emit `PERFORM_TRANSITIVE_KILL`. If CFG target resolution is wrong or incomplete, that is a separate CFG/paragraph-summary soundness issue rather than the typed-statement empty-modification default fixed here.

## Real Program Empty-Modification Inventory

These counts come from the fresh CFG JSON files generated on 2026-06-11. CFG text and COBOL source were not rewritten.

| Type with empty/null `variablesModified` | PDB305.CBL | PDCBVC.CBL | Classification |
| --- | ---: | ---: | --- |
| `CALL` | 0 | 1 | (a), targeted `CALL USING` kills when applicable |
| `DIALECT` | 37 | 32 | (b), kill-all fallback when no CICS/SQL output kill exists |
| `DIALECT_CONTAINER` | 37 | 32 | (a) |
| `EXIT` | 16 | 15 | (a) |
| `GOTO` | 36 | 71 | (a) |
| `IF_BRANCH` | 17 | 21 | (a) |
| `IF_YES` | 17 | 21 | (a) |
| `INSPECT` | 0 | 1 | (b), kill-all fallback in this run |
| `PARAGRAPH` | 26 | 28 | (a) |
| `PARAGRAPH_NAME` | 56 | 69 | (a) |
| `PERFORM` | 26 | 33 | (a), transitive paragraph kills when targets resolve |
| `SENTENCE` | 109 | 116 | (a) |
| `STOP` | 1 | 1 | (a) |
| `SYMBOL` | 0 | 3 | (a) |

The PDCBVC `INSPECT` gap is concrete:

`INSPECT PDRUTI01-F04-IMPOX11 CONVERTING ' ' TO '_'`

Before this task, `INSPECT ... CONVERTING` had no direct target kill because the existing rule only modeled `REPLACING` and `TALLYING`. It now clears the current constant map and emits `unmodeled_statement` evidence at that node.

## Before/After Propagation Metrics

Baseline source: pre-task compact summaries in `static_analysis/dataflow_rag_summary.json`, analysis version `1.10`, dated 2026-05-21 in the report directories.

After source: fresh `static_analysis/dataflow.json` sidecars generated on 2026-06-11 with analysis version `1.11`.

`propagated constant facts` is defined here as `entry_constant_count + exit_constant_count`, because the sidecar does not have a separate propagated-count summary field.

| Program | Version | Propagated constant facts | Entry facts | Exit facts | Kill facts | Diagnostics | Alias sets | Converged |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| PDB305.CBL before | 1.10 | 47 | 5 | 42 | 4,168,734 | 55 | 220 | true |
| PDB305.CBL after | 1.11 | 47 | 5 | 42 | 4,168,761 | 82 | 220 | true |
| PDB305.CBL delta | - | 0 | 0 | 0 | +27 | +27 | 0 | - |
| PDCBVC.CBL before | 1.10 | 196 | 67 | 129 | 4,656,979 | 64 | 177 | true |
| PDCBVC.CBL after | 1.11 | 200 | 67 | 133 | 7,191,753 | 87 | 201 | true |
| PDCBVC.CBL delta | - | +4 | 0 | +4 | +2,534,774 | +23 | +24 | - |

Explicit new kill-all evidence counts:

| Program | `UNMODELED_STATEMENT_KILL_ALL` facts | `DATAFLOW_UNMODELED_STATEMENT_KILL_ALL` diagnostics | Statement types |
| --- | ---: | ---: | --- |
| PDB305.CBL | 27 | 27 | 27 `DIALECT` |
| PDCBVC.CBL | 23 | 23 | 22 `DIALECT`, 1 `INSPECT` |

The propagated constant counts did not collapse for either program. PDCBVC's aggregate `kill_count` increased much more than the 23 explicit kill-all facts because the fresh after-run also has more alias sets than the baseline compact summary. Treat the aggregate kill count as an observed report metric, not as an isolated measure of the new fallback rule.

## Commands Run

```bash
mvn -pl smojol-toolkit clean test -Dcheckstyle.skip=true -Dtest=JavaHardeningRegressionTest
mvn -pl smojol-cli -am clean package -Dcheckstyle.skip=true -Dmaven.test.skip=true
java -cp smojol-cli/target/smojol-cli.jar org.smojol.cli.MultiCommandCLI --help
python3 analyze.py /home/eri/workspace/sapienza/master-thesis/cobol-rag-optimized/legacy-program-analysis/artifacts/final/final_scripts/input/PDB305/PDB305.CBL --no-graphviz --no-comment-enrichment --skip-transpiler --no-mermaid --java-heap=6g
python3 analyze.py /home/eri/workspace/sapienza/master-thesis/cobol-rag-optimized/legacy-program-analysis/artifacts/final/final_scripts/input/PDCBVC/PDCBVC.CBL --no-graphviz --no-comment-enrichment --skip-transpiler --no-mermaid --java-heap=6g
jq -r '.nodes[] | select((.variablesModified == null) or (.variablesModified|length==0)) | .type' out/report/PDB305.CBL.report/cfg/cfg-PDB305.CBL.json | sort | uniq -c
jq -r '.nodes[] | select((.variablesModified == null) or (.variablesModified|length==0)) | .type' out/report/PDCBVC.CBL.report/cfg/cfg-PDCBVC.CBL.json | sort | uniq -c
```

Note: two earlier rerun attempts used generated `.../_generated_program_packages/.../cobol/*.CBL` paths and failed copybook resolution because `analyze.py` derives copybooks from the input file's parent directory. The successful evidence runs above used the packaged `input/PDB305/PDB305.CBL` and `input/PDCBVC/PDCBVC.CBL` paths with sibling copybooks.
