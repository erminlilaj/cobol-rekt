# Work Done — Change Log

Per `CLAUDE.md` §0 Change Log Policy. Append new entries at the top (most recent first). Do not edit or delete existing entries.

---

## 2026-05-15 — Phase 2.6e join diagnostics for dropped constants

**File(s):** `smojol-toolkit/src/main/java/org/smojol/toolkit/analysis/staticvalue/StaticValueDataflowPass.java`, `smojol-toolkit/src/test/java/org/smojol/toolkit/analysis/task/JavaHardeningRegressionTest.java`, `docs/static-analysis/constant-folding-propagation.md`, `workDone.md`
**What changed:** Added source-preserving node-level diagnostics for real multi-predecessor joins where all incoming paths prove a variable constant but disagree on the value. The sidecar now uses analysis version `1.0` and status `join_diagnostics_constant_propagation`; `DATAFLOW_CONSTANT_DROPPED_AT_JOIN` records predecessor IDs and incoming values without changing entry/exit constants.
**Why:** The propagation solver already dropped conflicting constants safely; this checkpoint makes that conservative decision auditable for humans and downstream tools without rewriting source, CFG text, assignment facts, dynamic CALL/CICS fields, or RAG chunks.

---

## 2026-05-15 — Phase 2.6d numeric expression constant propagation

**File(s):** `smojol-toolkit/src/main/java/org/smojol/toolkit/analysis/staticvalue/StaticValueDataflowPass.java`, `smojol-toolkit/src/test/java/org/smojol/toolkit/analysis/task/JavaHardeningRegressionTest.java`, `smojol-toolkit/test-code/flow-ast/constant-propagation-phase2.cbl`, `docs/static-analysis/constant-folding-propagation.md`, `workDone.md`
**What changed:** Added source-preserving numeric expression propagation for `COMPUTE` nodes when every variable reference is already proven numeric at node entry. The sidecar now uses analysis version `0.9` and status `expression_constant_propagation`; the evaluator is intentionally limited to numeric literals, proven numeric variables, parentheses, unary signs, addition, subtraction, multiplication, and exact division.
**Why:** This is the next safe transfer rule after runtime/input/output kills and variable-copy propagation. It proves useful facts like `COMPUTE WS-E = WS-A + 5 -> WS-E = 15` without rewriting CFG text, source text, `assignment_facts`, dynamic CALL/CICS fields, or RAG chunks.

---

## 2026-05-14 — Phase 2.6c variable-copy constant propagation

**File(s):** `smojol-toolkit/src/main/java/org/smojol/toolkit/analysis/staticvalue/StaticValueDataflowPass.java`, `smojol-toolkit/src/test/java/org/smojol/toolkit/analysis/task/JavaHardeningRegressionTest.java`, `docs/static-analysis/constant-folding-propagation.md`, `workDone.md`
**What changed:** Added source-preserving variable-copy propagation for `MOVE <known-variable> TO <target>` using proven numeric entry constants plus existing CFG `variablesRead()`/`variablesModified()` evidence. The sidecar now uses analysis version `0.8` and status `variable_copy_constant_propagation`; expression inference from known variables remains pending, and `assignment_facts` are unchanged.
**Why:** Runtime/input/output kill rules are now in place, so this safe checkpoint can copy constants only when the source value survived those kills. It proves useful propagation without rewriting source, CFG text, legacy dynamic CALL/CICS fields, or RAG chunks.

---

## 2026-05-14 — Phase 2.6b runtime-output kill facts

**File(s):** `smojol-toolkit/src/main/java/org/smojol/toolkit/analysis/staticvalue/StaticValueDataflowPass.java`, `smojol-toolkit/src/test/java/org/smojol/toolkit/analysis/task/JavaHardeningRegressionTest.java`, `smojol-toolkit/test-code/flow-ast/output-kills-phase26b.cbl`, `docs/static-analysis/constant-folding-propagation.md`, `workDone.md`
**What changed:** Added dataflow-local runtime-output kill facts without enabling variable-copy propagation. The sidecar now uses analysis version `0.7` and status `output_kill_constant_propagation`; `READ INTO`, `STRING INTO`, `UNSTRING INTO`, `INSPECT`, CICS output arguments, and SQL `SELECT/FETCH ... INTO` host variables remove prior constants at node exit.
**Why:** This completes the kill-rule safety checkpoint required before propagating constants from known variables. It prevents stale runtime-output values from being reused while keeping CFG text, `assignment_facts`, legacy dynamic CALL/CICS fields, and RAG behavior unchanged.

---

## 2026-05-14 — Phase 2.6a runtime/input kill facts

**File(s):** `smojol-toolkit/src/main/java/org/smojol/toolkit/analysis/staticvalue/StaticValueDataflowPass.java`, `smojol-toolkit/src/test/java/org/smojol/toolkit/analysis/task/JavaHardeningRegressionTest.java`, `smojol-toolkit/test-code/flow-ast/runtime-kills-phase26a.cbl`, `docs/static-analysis/constant-folding-propagation.md`, `workDone.md`
**What changed:** Added dataflow-local kill facts for runtime/input overwrites without changing CFG node `variablesModified()`: `ACCEPT` targets emit `RUNTIME_INPUT_KILL`, `CALL USING` reference arguments emit `CALL_USING_REFERENCE_KILL`, and `INITIALIZE` targets emit `INITIALIZE_TARGET_KILL`. The dataflow sidecar now uses analysis version `0.6` and status `runtime_kill_constant_propagation`; variable-copy propagation remains disabled.
**Why:** Claude's pre-coding audit confirmed runtime/input kills are required before any propagation that reads entry constants. This checkpoint prevents stale constants from surviving runtime overwrites while preserving source/CFG artifacts.

---

## 2026-05-14 — Phase 2.5 basic numeric constant propagation

**File(s):** `smojol-toolkit/src/main/java/org/smojol/toolkit/analysis/staticvalue/StaticValueDataflowPass.java`, `smojol-toolkit/src/test/java/org/smojol/toolkit/analysis/task/JavaHardeningRegressionTest.java`, `smojol-toolkit/test-code/flow-ast/constant-propagation-phase2.cbl`, `docs/static-analysis/constant-folding-propagation.md`, `workDone.md`
**What changed:** Added the first safe fixed-point propagation solver in `static_analysis/dataflow.json`, with analysis version `0.5`, status `basic_constant_propagation`, and deterministic entry/exit constants for numeric literal `MOVE` facts and folded numeric `COMPUTE` facts. Branch joins now keep only constants proven equal on every predecessor, alias kills invalidate overlapping storage before direct writes, and modified variables without a safe numeric fact are removed from exit state. Variable-copy propagation, condition simplification, runtime-input modeling, dynamic CALL/CICS path-sensitive fields, and RAG changes remain out of scope.
**Why:** User asked to proceed with the safe alternative and keep the human-readable documentation updated; this checkpoint adds useful propagation facts without overclaiming full COBOL constant propagation.

---

## 2026-05-12 — Phase 2.4 alias kill facts in dataflow sidecar

**File(s):** `smojol-toolkit/src/main/java/org/smojol/toolkit/analysis/staticvalue/StaticValueDataflowPass.java`, `smojol-toolkit/src/test/java/org/smojol/toolkit/analysis/task/JavaHardeningRegressionTest.java`, `smojol-toolkit/test-code/flow-ast/alias-kills-phase2.cbl`, `docs/static-analysis/constant-folding-propagation.md`, `workDone.md`
**What changed:** Applied alias sets as conservative per-node kill facts in `static_analysis/dataflow.json`, with analysis version `0.4`, status `alias_kill_skeleton`, and deterministic `ALIAS_CONSERVATIVE_KILL` entries for group/child, `REDEFINES`, and `OCCURS` writes. Entry and exit constants remain empty, and fixed-point propagation is still not implemented.
**Why:** User asked to proceed safely; this checkpoint adds the alias invalidation safety layer required before propagation can make reliable constant claims.

---

## 2026-05-12 — Phase 2.3 alias-set summaries in dataflow sidecar

**File(s):** `smojol-toolkit/src/main/java/org/smojol/toolkit/analysis/staticvalue/AliasSetSummary.java`, `smojol-toolkit/src/main/java/org/smojol/toolkit/analysis/staticvalue/DataflowAnalysisResult.java`, `smojol-toolkit/src/main/java/org/smojol/toolkit/analysis/staticvalue/StaticValueDataflowPass.java`, `smojol-toolkit/src/main/java/org/smojol/toolkit/analysis/task/analysis/WriteControlFlowGraphTask.java`, `smojol-toolkit/src/main/java/org/smojol/toolkit/task/SmojolTasks.java`, `smojol-toolkit/src/test/java/org/smojol/toolkit/analysis/task/JavaHardeningRegressionTest.java`, `docs/static-analysis/constant-folding-propagation.md`, `workDone.md`
**What changed:** Added deterministic conservative alias-set summaries to `static_analysis/dataflow.json` for group/child storage, `OCCURS` storage, and `REDEFINES` overlap. The sidecar now carries analysis version `0.3`, status `alias_summary_skeleton`, and syntax-derived alias evidence, while entry/exit constants, kills, and propagation remain empty.
**Why:** User asked to proceed and document all work; this checkpoint prepares alias facts needed by later propagation without applying any kill rules or overclaiming constant propagation.

---

## 2026-05-12 — Phase 2.2 paragraph summaries in dataflow sidecar

**File(s):** `smojol-toolkit/src/main/java/org/smojol/toolkit/analysis/staticvalue/ParagraphSummary.java`, `smojol-toolkit/src/main/java/org/smojol/toolkit/analysis/staticvalue/DataflowAnalysisResult.java`, `smojol-toolkit/src/main/java/org/smojol/toolkit/analysis/staticvalue/StaticValueDataflowPass.java`, `smojol-toolkit/src/test/java/org/smojol/toolkit/analysis/task/JavaHardeningRegressionTest.java`, `docs/static-analysis/constant-folding-propagation.md`, `workDone.md`
**What changed:** Added paragraph summaries to `static_analysis/dataflow.json`, including contained CFG node IDs, direct read/write variables, called paragraphs, called programs, external side effects, unsupported/deferred constructs, and conservative transitive status. PERFORM transitive expansion is explicitly deferred with a machine-readable unsupported construct instead of being overclaimed.
**Why:** User asked to proceed with the next phase and document everything; this checkpoint prepares the summary data needed by later propagation while keeping entry/exit constants and solver logic unimplemented.

---

## 2026-05-12 — Phase 2.1 dataflow skeleton sidecar

**File(s):** `smojol-toolkit/src/main/java/org/smojol/toolkit/analysis/staticvalue/DataflowAnalysisResult.java`, `smojol-toolkit/src/main/java/org/smojol/toolkit/analysis/staticvalue/DataflowNodeState.java`, `smojol-toolkit/src/main/java/org/smojol/toolkit/analysis/staticvalue/StaticValueDataflowPass.java`, `smojol-toolkit/src/main/java/org/smojol/toolkit/analysis/pipeline/SerialisableCFGGraphCollector.java`, `smojol-toolkit/src/main/java/org/smojol/toolkit/analysis/task/analysis/WriteControlFlowGraphTask.java`, `smojol-toolkit/src/test/java/org/smojol/toolkit/analysis/task/JavaHardeningRegressionTest.java`, `docs/static-analysis/constant-folding-propagation.md`, `workDone.md`
**What changed:** Added the source-preserving `static_analysis/dataflow.json` skeleton emitted alongside `WRITE_CFG`. The sidecar records schema/version/config/summary fields and one empty per-node state for each CFG node, with propagation, alias analysis, paragraph summaries, and path-sensitive target resolution explicitly disabled.
**Why:** User approved starting Phase 2 and asked for human-readable documentation of what was done, while keeping the first step conservative and stopping before real propagation logic.

---

## 2026-05-12 — Phase 1 constant folding completion checkpoint

**File(s):** `smojol-core/src/main/java/org/smojol/common/staticanalysis/folding/StaticValueLiteralExtractor.java`, `smojol-core/src/test/java/org/smojol/common/staticanalysis/folding/StaticValueLiteralExtractorTest.java`, `smojol-toolkit/src/test/java/org/smojol/toolkit/analysis/task/JavaHardeningRegressionTest.java`, `smojol-toolkit/test-code/flow-ast/constant-folding-phase1.cbl`, `docs/static-analysis/constant-folding-propagation.md`, `workDone.md`
**What changed:** Completed Phase 1 coverage by adding direct literal-extractor tests, unary plus fixture coverage, preservation assertions for statement text and CFG shape, and fixture-level accuracy/size/runtime measurements. The living plan now marks Phase 1 steps 1.1 through 1.7 as done while keeping propagation pending, with broader Java verification recorded.
**Why:** User asked to proceed with Phase 1 only, keep discussion 0006 and the committed documentation synchronized, commit after the important step, and stop before Phase 2.

---

## 2026-05-11 — Phase 1 constant folding coverage checkpoint

**File(s):** `smojol-core/src/main/java/org/smojol/common/staticanalysis/value/NumericStaticValue.java`, `smojol-core/src/test/java/org/smojol/common/staticanalysis/value/StaticValueTest.java`, `smojol-toolkit/src/test/java/org/smojol/toolkit/analysis/task/JavaHardeningRegressionTest.java`, `smojol-toolkit/test-code/flow-ast/constant-folding-phase1.cbl`, `docs/static-analysis/constant-folding-propagation.md`, `workDone.md`
**What changed:** Preserved exact BigDecimal scale in numeric static values, added exact payload tests, expanded the Phase 1 golden fixture to cover decimal addition, subtraction, multiplication, unary signs, parentheses, exact division, non-terminating division, figurative constants, and exponentiation, and recorded fixture-level folding stats plus broader Java verification in the implementation plan.
**Why:** User asked to proceed carefully, keep discussion 0006 and the committed documentation synchronized, and stop for a commit after each important implementation step.

---

## 2026-05-11 — Phase 1 constant folding implementation checkpoint

**File(s):** `smojol-core/src/main/java/org/smojol/common/staticanalysis/value/*`, `smojol-core/src/main/java/org/smojol/common/staticanalysis/folding/*`, `smojol-toolkit/src/main/java/org/smojol/toolkit/ast/ComputeFlowNode.java`, `smojol-toolkit/src/test/java/org/smojol/toolkit/analysis/task/JavaHardeningRegressionTest.java`, `smojol-toolkit/test-code/flow-ast/constant-folding-phase1.cbl`, `docs/static-analysis/constant-folding-propagation.md`, `workDone.md`
**What changed:** Added the Phase 1 source-preserving constant-folding checkpoint: a sealed `StaticValue` value model, BigDecimal-based closed numeric expression folding, machine-readable folding diagnostics, additive `folded_value_facts` and `folding_diagnostics` on `COMPUTE` CFG node metadata, and a golden fixture/test coverage for foldable `COMPUTE`, unsupported variable reference, unsafe divide by zero, and unchanged `MOVE` assignment facts.
**Why:** User asked to proceed carefully with the agreed discussion 0006 plan, keep the committed documentation synchronized, and stop to commit after each important step before continuing.

---

## 2026-05-11 — Final pre-implementation contract for folding PR 1

**File(s):** `docs/discussions/0006-constant-folding-propagation-strategy.md`, `documentation-wip/discussions/0006-constant-folding-propagation-strategy.md`, `workDone.md`
**What changed:** Reopened discussion 0006 with a final pre-implementation contract for Claude review, pinning Java package/class names, sealed `StaticValue` API shape, JSON naming rules, `ComputeFlowNode.metadata()` attachment point, Phase 1 numeric folding rules, diagnostics policy, deterministic ordering, the first golden fixture, PR 1 defaults, and forbidden changes.
**Why:** User asked to write the last strategy clarifications and ask Claude one final time whether the plan is acceptable before coding.

---

## 2026-05-11 — Codex response to constant folding discussion 0006

**File(s):** `docs/discussions/0006-constant-folding-propagation-strategy.md`, `documentation-wip/discussions/0006-constant-folding-propagation-strategy.md`, `workDone.md`
**What changed:** Responded to Claude's follow-up questions and marked the discussion resolved. Finalized the design direction: `folded_value_facts` as additive CFG node metadata, `static_analysis/dataflow.json` for propagation entry/exit state, alias sets and paragraph summaries persisted in the dataflow sidecar, and dual-emitted path-sensitive CALL/CICS fields alongside legacy serial-order provenance.
**Why:** User asked for a reliable long-term plan for constant folding and propagation, with Claude/Codex discussion before implementation.

---

## 2026-05-11 — Constant folding and propagation strategy discussion

**File(s):** `docs/discussions/0006-constant-folding-propagation-strategy.md`, `documentation-wip/discussions/0006-constant-folding-propagation-strategy.md`, `workDone.md`
**What changed:** Added a detailed discussion document for Claude review on how cobol-rekt could implement source-preserving constant folding and constant propagation, including current code evidence, value-model requirements, dataflow design, kill rules, artifact shape, and staged tests.
**Why:** User asked for honest long-term research and an inter-agent discussion before proceeding with any implementation.

---

## 2026-05-11 — Human-readable feature/optimization branch summary

**File(s):** `docs/feature-optimization-branch-summary.md`, `workDone.md`
**What changed:** Added a human-readable summary of what the `feature/optimization` branch did, including the explicit no/yes evaluation for constant folding and constant propagation, the shipped compaction features, benchmark interpretation, user-facing commands, and verification status.
**Why:** User asked for a plain explanatory document before proceeding, so reviewers can understand that the branch improves static-fact confidence and retrieval compaction without claiming compiler-style optimization.

---

## 2026-05-10 — Stage 8: D10 final verification and wrap-up

**File(s):** `workDone.md`
**What changed:** Recorded final verification for Stages 3–7. Python suite passed with `python3 -m unittest test_chunk_pipeline_cics.py test_chunk_pipeline.py test_pipeline_hardening.py test_bm25_index.py test_chunk_pipeline_profiles.py test_bench_compaction.py` (88 tests, 2 skipped). Java suite passed with `mvn -pl smojol-toolkit test -Dcheckstyle.skip=true` (27 tests, 0 failures, 0 errors, 2 skipped, BUILD SUCCESS). Draft PR title: `feat: optimization and compaction — Stages 3–8 (D4, D6–D10)`.
**Why:** Stage 8 of proposal 0006 — finalize local verification and leave the branch ready for review without pushing or merging.

---

## 2026-05-10 — Stage 7: D8+D9 optimization documentation

**File(s):** `docs/optimization-and-compaction.md`, `CLAUDE.md`, `workDone.md`
**What changed:** Added human-readable optimization and compaction documentation with the source-preserving problem statement, support matrix, usage examples for `--profile facts-only` and `--label-boost`, future-work boundaries, and the benchmark table copied from `scripts/bench_results.md`. Updated CLAUDE.md with schema 1.6 wording for `structured_term_weights` and manifest `profile`, a `bm25_index.json` reference, and a source-preserving compaction design decision pointing to the new doc.
**Why:** Stage 7 of proposal 0006 — document what the branch shipped, what remains deferred, and how to use the new retrieval compaction controls without overclaiming compiler-style optimization.

---

## 2026-05-10 — Stage 6: D7 benchmark harness

**File(s):** `scripts/bench_fixtures.json`, `scripts/bench_queries.json`, `scripts/bench_compaction.py`, `scripts/bench_results.json`, `scripts/bench_results.md`, `test_bench_compaction.py`, `workDone.md`
**What changed:** Added frozen public fixtures from `smojol-test-code/` with SHA-256 checksums, `baseline_branch: "main"`, and `baseline_sha`. Added five proposal-specific benchmark queries with required tags. Added a deterministic benchmark harness that synthesizes report fixtures, calls `chunk_pipeline.py` for default and facts-only profiles, measures chunk count, token totals, max tokens, duplicate content hashes, and BM25 entry counts, and writes JSON/Markdown outputs. Added three unittest cases covering harness execution, deterministic JSON output, and baseline SHA metadata.
**Why:** Stage 6 of proposal 0006 — provide a reproducible compaction benchmark surface for the branch without depending on private corpus files or mutating source-derived JSON artifacts.

---

## 2026-05-10 — Stage 5: D6 facts-only chunk profile

**File(s):** `chunk_pipeline.py`, `test_chunk_pipeline_profiles.py`, `workDone.md`
**What changed:** Added `--profile {default,facts-only}` to `chunk_pipeline.py`. The default profile keeps the existing chunk generation path; the facts-only profile emits only core fact chunks (`program_summary`, `dependencies`, `variable_group`, and COBOL analysis health) before BM25 indexing and manifest generation. Added `profile` to `chunks_manifest.json`. Added five exact unittest cases covering default paragraph_logic emission, facts-only omission of paragraph_logic/section_summary/workflow, program_summary and variable_group presence, and manifest profile tagging.
**Why:** Stage 5 of proposal 0006 — provide an opt-in retrieval profile for fact-focused chunk sets while leaving default human-readable chunk generation unchanged.

---

## 2026-05-10 — Stage 3: D4 BM25 structured term weights

**File(s):** `chunk_pipeline.py`, `test_bm25_index.py`, `scripts/bm25_boost_selection.md`, `workDone.md`
**What changed:** Added additive `structured_term_weights` maps to every BM25 index entry, sourced from existing `structured_terms` plus `metadata.search_boost.paragraph_labels`, with a configurable `--label-boost` CLI flag defaulting to `1.0`. Added paragraph-label search boost metadata for paragraph_logic, controlflow.cfg, section_summary, and workflow chunks, and stripped only redundant standalone label lines while keeping the first mention. Added five Stage 3 unittest cases covering field emission, paragraph-label weights, unchanged `term_freq`, unchanged `structured_terms`, and the CLI flag. Documented the conservative `1.0` boost selection in `scripts/bm25_boost_selection.md`.
**Why:** Stage 3 of proposal 0006 — expose paragraph labels as weighted retrieval metadata without mutating the existing BM25 term-frequency shape or deprecating `structured_terms`.

---

## 2026-05-10 — Stage 2: D3 CICS presentation-level dedup in `dependencies` chunk

**File(s):** `chunk_pipeline.py`, `validate_chunks.py`, `test_chunk_pipeline_cics.py`, `test_chunk_pipeline.py`, `CLAUDE.md`, `docs/proposals/0006-optimization-and-compaction-plan.md`, `documentation-wip/proposals/0006-optimization-and-compaction-plan.md`, `workDone.md`
**What changed:** Added `_HANDLE_IGNORE_CMDS` constant and `_aggregate_cics_for_deps_text()` helper in `chunk_pipeline.py`. Modified `generate_dependencies()` to use the aggregated CICS text: repeated `(command, target, operation_type)` triples are collapsed to one line per group listing up to 5 paragraphs (with `... +M more` suffix for N > 5); `HANDLE` and `IGNORE` commands bypass aggregation and appear one-per-occurrence to preserve error-handler evidence. Bumped `CHUNK_SCHEMA_VERSION` and `PIPELINE_VERSION` from `"1.5"` to `"1.6"` (both move together). Added `"1.6"` to `validate_chunks.SUPPORTED_SCHEMA_VERSIONS`. Added 6 contract tests in `test_chunk_pipeline_cics.py` covering aggregation, cap-at-5, HANDLE preservation, cics.operation-unchanged, schema version, and validate_chunks acceptance. Updated the one hardcoded `"1.5"` in `test_chunk_pipeline.py` to `"1.6"`. Updated CLAUDE.md §4 schema changelog. All 75 tests green.
**Why:** Stage 2 of proposal 0006 — reduce CICS token bloat in the `dependencies` chunk by collapsing repeated `(command, target, type)` triples across paragraphs into a single aggregate line, while preserving error-handler evidence (HANDLE/IGNORE) verbatim.

---

## 2026-05-08 — Stage 1: D1+D2 contract-locking JUnit tests on `feature/optimization`

**File(s):** `smojol-toolkit/src/test/java/org/smojol/toolkit/analysis/task/JavaHardeningRegressionTest.java`, `smojol-toolkit/test-code/flow-ast/optimization-stage1.cbl`, `docs/proposals/0006-optimization-and-compaction-plan.md`, `documentation-wip/proposals/0006-optimization-and-compaction-plan.md`, `workDone.md`
**What changed:** Added six contract-locking JUnit tests in `JavaHardeningRegressionTest` covering the literal-fact gates (D1) and dynamic CALL/CICS resolution (D2): `exportsNoAssignmentFactsForLiteralArithmeticCompute`, `exportsAssignmentFactsForFigurativeConstantsAsLiterals`, `exportsNoAssignmentFactsForSetEightyEightCondition`, `exportsChainedCallResolutionEachUsingItsPrecedingMoveLiteralWithMediumConfidence`, `exportsCallTargetSourceUnresolvedWhenWalkOrderHasNoPriorLiteralForTarget`, `exportsChainedXctlResolutionEachUsingItsPrecedingMoveLiteralWithMediumConfidence`. New fixture `optimization-stage1.cbl` covers the cases not already exercised by existing fixtures. Zero edits under `smojol-toolkit/src/main/`. Full class result: `Tests run: 15, Failures: 0, Errors: 0`. Plan revision 4 records two empirical findings that contradicted prior plan assumptions: figurative constants `SPACES`/`ZEROS` are treated as literals by `MoveFlowNode` and DO emit `assignment_facts`; dynamic CALL resolution is driven by CFG emission order, not source order or control flow, so a CALL after a same-paragraph MOVE+EXEC SQL is annotated `unresolved_identifier conf=low`. Tests lock the actual current behaviour.
**Why:** Stage 1 of proposal 0006 — lock the current literal-fact and dynamic call resolution behaviour before any compaction stage (Stage 2 onward) can change adjacent code. Empirical findings replace plan assumptions; locking actual behaviour means any future drift is forced to be a deliberate, reviewed decision.

---

## 2026-05-08 — Stage 0: optimization branch plan finalized and mirrored

**File(s):** `docs/proposals/0006-optimization-and-compaction-plan.md`, `documentation-wip/proposals/0006-optimization-and-compaction-plan.md`, `workDone.md`
**What changed:** Created proposal 0006 (optimization-and-compaction implementation plan) and applied two rounds of Codex review fixes: schema bumps from `1.5` → `1.6` (both `CHUNK_SCHEMA_VERSION` and `PIPELINE_VERSION` together); root-level `python3 -m unittest` test layout (no `tests/` package); CICS dedup key `(command, target/resource, category)` aggregating paragraphs with HANDLE/IGNORE preservation guard; BM25 adds new additive `structured_term_weights` field, leaves `term_freq` and `structured_terms` untouched; BM25 boost sweep `{1.0, 1.5, 2.0}`; D5 (`pruned_paragraphs.json`) deferred unless re-justified; benchmark baseline pinned to a frozen `baseline_sha`; bench query set primarily derived from `rag_kb_evaluator.py:_build_queries()` with a labelled supplement; `structured_terms` retained indefinitely on this branch. Mirrored to `documentation-wip/proposals/0006-...`. Recreated `workDone.md` (was missing).
**Why:** Discussion `docs/discussions/0005-optimization-techniques.md` resolved with the conclusion that cobol-rekt should remain source-preserving (no constant folding, no general constant propagation). Plan turns that conclusion into a staged, test-first implementation on branch `feature/optimization`. Two Codex review passes pinned each design decision to repo state and CLAUDE.md rules.

---
