# Agent Handoff Log
_Shared between Claude Code, Antigravity, and Codex. Read before starting. Append after finishing._

---

agent: claude
task: Implement proposal 0005 Steps 1+0 — branch/tag safety infrastructure and corpus_baseline.py
files_changed: corpus_baseline.py, baselines/submodule_pins_pre_step1.txt, baselines/baseline_pre_integration.json, baselines/baseline_self_diff.log, workDone.md, docs/handoff.md
why: User asked Claude to implement from the reviewed 0005 proposal, starting with branch safety (Step 1) and corpus_baseline.py (Step 0). Stopping here for Codex sign-off before any Che4z cherry-pick.
status: done
what_was_done: |
  1. Created tag `snapshot/pre-integration` on feature/java-parse-hardening.
  2. Switched to new branch `feature/integration-research`.
  3. Recorded submodule pins to `baselines/submodule_pins_pre_step1.txt`.
  4. Implemented `corpus_baseline.py`:
     - Per-program extraction: pipeline status, parse diagnostics, analysis_self_evaluation,
       03_Dependencies.yaml, copybook_manifest, chunks directory, CFG construct detection.
     - Construct detection: has_evaluate (EVALUATE node type in CFG), has_exec_dli
       (EXEC DLI in originalText), has_dialect_nodes, has_dialect_dli_overlap.
     - --diff mode with regression detection (parse coverage drop, base_analysis_succeeded loss).
     - Exits 1 if regressions found, 0 if only improvements/additions.
  5. Generated `baselines/baseline_pre_integration.json` (486 programs, 433 with CFG, 474 with chunks).
  6. Verified self-diff reports zero changes and exit code 0.
  Key observed values (for Codex to verify against checklist):
    programs_with_evaluate: 108 (matches proposal assertion)
    programs_with_exec_dli: 4 (proposal says 7 — ABNDPROC, DBCRFUN, imsclaim not in CFG as EXEC DLI)
    programs_with_copy_replacing: 13 (proposal says 5 — cobol_structure.json has more)
    programs_with_dialect_dli_overlap: 3
  Note: baselines/ directory is at repo root (not under out/) as per user instruction.
next: Codex to run Step 0 review checklist from proposal 0005:
  python3 -m py_compile corpus_baseline.py
  python3 corpus_baseline.py --report-dir out/report --output baselines/baseline_pre_integration.json
  Run the inline Python assertion block from the checklist.
  python3 corpus_baseline.py --diff baselines/baseline_pre_integration.json baselines/baseline_pre_integration.json
  Note the DLI discrepancy (4 vs 7) and decide whether to update the checklist assertion or investigate further.
  Sign off on Step 0, then Claude will proceed to Step 1 (Che4z EVALUATE backport).
timestamp: 2026-04-30T08:30:00+02:00

---

agent: codex
task: Review and harden proposal 0005 with final decisions and explicit Codex gates
files_changed: docs/proposals/0005-integration-safe-plan.md, thesis-documentation/proposals/0005-integration-safe-plan.md, docs/handoff.md
why: User asked Codex to own all open decisions, inspect Che4z EVALUATE commits, fix source-resolution/rerun commands, add per-step Codex review checklists and stronger rollback rules, and mirror the proposal.
status: done
next: Claude should implement from docs/proposals/0005-integration-safe-plan.md exactly as reviewed. Key decisions: `595c7886f` IN and `c2ba1be4f` IN as a paired EVALUATE backport; IMS is metadata-only first with no `EXTRACT_IMS_DEPENDENCIES`; `cics_operations:` is a new YAML key while `cics:` remains backward-compatible; DB2 changes are deferred unless Step 3 evidence justifies Python sqlparse hardening.
timestamp: 2026-04-30T07:57:22+02:00

---

agent: codex
task: Create proposal 0005 — integration-safe Java-port plan for mapa-inspired IMS/CICS/DB2 work
files_changed: docs/proposals/0005-integration-safe-plan.md, thesis-documentation/proposals/0005-integration-safe-plan.md, docs/handoff.md
why: User changed the plan: mapa is reference-only, no external tool execution and no mapa_bridge.py. Codex researched mapa DLI/CICS/DB2 listeners and cobol-rekt Java extension points, then wrote a branch-safe staged proposal.
status: done
next: Give Claude this prompt: "Read docs/proposals/0005-integration-safe-plan.md and respond." Key recommendation: implement `corpus_baseline.py` first; port IMS/DLI as Java metadata under `DialectMetadataParser` before adding a standalone task; add structured `cics_operations` while preserving `cics:` as string list; defer DB2 changes until baseline evidence says Python sqlparse is insufficient.
timestamp: 2026-04-30T07:39:37+02:00

---

agent: codex
task: Research Che4z drift, mapa source, IMS/DLI corpus evidence, baseline design for discussion 0003
files_changed: docs/discussions/0003-upstream-drift-and-mapa-integration.md, thesis-documentation/discussions/0003-upstream-drift-and-mapa-integration.md, docs/handoff.md
why: User asked Codex to research upstream Che4z parser diffs, mapa source coverage/enrichment, EXEC DLI corpus presence, artifact snapshot dimensions, and woof/mojo-common details before appending a response to discussion 0003.
status: done
next: Prioritize a read-only `corpus_baseline.py` in the next session; then use it before any Che4z cherry-pick. Best immediate Che4z candidate is `c2ba1be4f` (tiny EVALUATE grammar fix; 108 CFGs contain EVALUATE). Defer full Che4z merge and copybook REPLACING fixes until after evaluation. mapa is most useful as an optional IMS/DLI/CICS/DB2 extraction complement, not a Che4z replacement.
timestamp: 2026-04-30T00:25:02+02:00

---

agent: claude
task: Open discussion 0003 — upstream submodule drift audit + mapa tool research
files_changed: |
  docs/discussions/0003-upstream-drift-and-mapa-integration.md,
  thesis-documentation/0005-upstream-drift-and-mapa-integration.md,
  AGENTS.md, CLAUDE.md (thesis-documentation submodule wiring),
  docs/handoff.md
why: User requested research on what upstream repos have committed that we don't, and a deep analysis of mapa tool. Claude audited all three submodules (mojo-common, woof, che-che4z) and ran a full mapa capability analysis. Discussion file written; Codex prompt below.
status: done
what_was_done: |
  Submodule audit findings:
  - mojo-common: in sync, we are 1 commit ahead (CICS_OPERATIONS type). Nothing to pull.
  - woof: exactly in sync at 3828ceb. Nothing to pull.
  - che-che4z: 487 commits behind upstream poc. High-value fixes missing:
      nested copybook REPLACING propagation, EVALUATE statement fix,
      CICS literals tolerance, APOST/QUOTE directives, floating comment fix.
      Merge DEFERRED until after thesis evaluation (was a deliberate freeze).
  mapa tool (github.com/cschneid-the-elder/mapa):
  - MIT-licensed ANTLR 4 + Java portfolio analysis tool.
  - Unique capabilities vs cobol-rekt: EXEC DLI/IMS grammar, free-form COBOL,
      broader CICS transaction type extraction, nested JCL PROC symbolic resolution,
      DB2 per-statement action classification, portfolio-scale CSV output.
  - No overlap on documentation, RAG, comment enrichment, visualization.
  - Integration plan: loose coupling via mapa_bridge.py (CSV → augmented JSON artifacts).
      Never modify core Java pipeline. Snapshot corpus before any integration.
  Full analysis + 4 questions for Codex in docs/discussions/0003-upstream-drift-and-mapa-integration.md
next: |
  Give Codex this prompt (see below for full text).
timestamp: 2026-04-30T00:30:00+02:00

---

agent: claude
task: Share committed 2026-04-29 batch to Codex — schema 1.4 pipeline hardening
files_changed: |
  chunk_pipeline.py, validate_chunks.py, rag_kb_evaluator.py, knowledge_base_builder.py,
  analysis/sandbox_manager.py,
  smojol-toolkit/.../AnalysisSelfEvaluationWriter.java,
  test_chunk_pipeline.py, test_knowledge_base_builder.py, test_rag_kb_evaluator.py,
  .gitignore, .gitmodules, woof (submodule), mojo-common (submodule),
  smojol-core/src/test/test-code/flow-ast/*.cbl
why: All changes from the 2026-04-29 session are committed. Summarizing for Codex pickup.
status: done
what_was_done: |
  Six commits landed on 2026-04-29 (see git log for exact hashes):

  1. feat(rag) schema 1.4 — chunk_pipeline.py + validate_chunks.py
     - Bump CHUNK_SCHEMA_VERSION / PIPELINE_VERSION to 1.4
     - New `cics_operations` chunk type: dedicated CICS command + LINK/XCTL target chunk;
       cics_command_count in metadata; +100 boost for CICS queries in evaluator
     - Universal BPE splitting: `split_bpe_text()` + `apply_universal_size_guard()` post-gen pass;
       oversized chunks split with overlap before manifest/BM25 write
     - Thin-chunk indexability: `mark_indexability()` sets thin_chunk/indexable flags at write boundary;
       non-indexable over-limit chunks demoted to warnings (not errors) in validate_chunks.py
     - Figurative constant filter: `_COBOL_FIGURATIVE_CONSTANTS` + `_is_valid_program_target()`
       prevent SPACES/ZEROS propagating as CICS targets
     - Analysis health enriched from `analysis_self_evaluation.json` fields
     - Within-report and global duplicate content hash counts tracked in stats

  2. feat(rag) evaluator v2 — rag_kb_evaluator.py
     - Control-flow scoring replaced: verbatim CFG-text (2.79%) → composite metric
       (paragraph heading coverage 0.50 + statement type set coverage 0.40 + branch marker 0.10);
       legacy score retained for one transition cycle
     - JCL `artifact_to_knowledge_base` marked `not_applicable` instead of 0%
     - Unevaluable programs (base_analysis_succeeded=false) isolated in their own section
     - Duplicate hash reporting split: within_report vs global (legacy key retained)
     - `chunks` field excluded from semantic top-defects table; dedicated chunk-quality section added

  3. feat(kb) narrative hardening — knowledge_base_builder.py
     - LINKAGE section filter fixed: match 'LINKAGE' (actual JSON value) not 'LINKAGE_SECTION'
     - Narrator dispatch expanded: MULTIPLY, DIVIDE, SET, READ, INITIALIZE
     - EXIT handling: bare EXIT skipped silently; EXIT PERFORM/PARAGRAPH/SECTION rendered
     - STOP RUN rendered as **STOP RUN**
     - EVALUATE: short blocks verbatim, long blocks as WHEN bullet list
     - Analysis Quality section added to 00_Executive_Summary.md: parse coverage %,
       copybook resolution ratio, confidence label (High/Medium/Low), stubbed copybook table

  4. fix(sandbox) BFS copybook resolution — analysis/sandbox_manager.py
     - Replaced recursive DFS with BFS for nested COPY chains to prevent infinite loops
       in programs where copybooks include other copybooks

  5. test suites — test_chunk_pipeline.py (14), test_knowledge_base_builder.py (26), test_rag_kb_evaluator.py (7)
     - All tests use skipTest when local corpus artifacts are absent (clean CI)

  6. chore: .gitignore expanded; woof / mojo-common submodules bumped;
     three missing COBOL test fixtures added (missing-copybook.cbl, etc.)

next: |
  Suggested next tasks for Codex:
  1. Run `python3 test_chunk_pipeline.py test_knowledge_base_builder.py test_rag_kb_evaluator.py`
     and confirm all pass against the local corpus.
  2. Re-run `python3 rag_kb_evaluator.py --report-dir out/report` against the expanded corpus
     and update rag_kb_evaluation_report.md / .json / .csv.
  3. Check if `chunk_pipeline.py --report-dir out/report` needs to be re-run to regenerate
     schema-1.4 chunks with `cics_operations` type and `indexable` flags.
  4. Review whether `analysis_self_evaluation.json` is present for all 443+ program reports;
     if not, identify which programs need a fresh Java analysis pass.
timestamp: 2026-04-29T23:45:00+02:00

---

agent: claude
task: Analyze 44 pending external COBOL files and append RAG KB evaluator review
files_changed: |
  rag_kb_evaluation_report.md, rag_kb_evaluation.json, rag_kb_evaluation.csv,
  docs/discussions/0002-rag-kb-evaluator-review.md, workDone.md, docs/handoff.md
why: User requested external corpus completed and evaluator re-run; Claude review appended to discussion file.
status: done
what_was_done: |
  1. Ran batch_runner.py across 8 pending source groups from codefiles/external/ (44 files).
  2. Generated RAG chunks for all new reports via chunk_pipeline.py.
  3. Re-ran rag_kb_evaluator.py on full expanded corpus.
  4. Appended methodological review to docs/discussions/0002-rag-kb-evaluator-review.md.
next: |
  Priority issues for next session:
  1. Fix chunk quality: split oversized (>512 BPE), deduplicate 1,559 duplicate hashes, filter thin (<20 tokens).
  2. Fix control-flow scoring in rag_kb_evaluator.py: replace per-node verbatim matching with paragraph
     heading coverage + statement type set coverage + branch density ratio.
  3. Separate `chunks` field from semantic top-defects table in evaluator.
  4. Fix JCL KB-stage: report not_applicable instead of 0% for artifact_to_knowledge_base.
  5. Add `cics_operations` chunk type to improve CICS Recall@1 from 18.54%.
  See docs/discussions/0002-rag-kb-evaluator-review.md for full priority list.
timestamp: 2026-04-27T17:00:00+02:00

---

agent: codex
task: Open Claude review discussion for RAG KB evaluator
files_changed: docs/discussions/0002-rag-kb-evaluator-review.md, workDone.md, docs/handoff.md
why: User asked Codex to open a discussion with Claude covering all implemented evaluator work, findings, possible improvements, and a prompt for Claude.
status: done
next: |
  Give Claude this prompt:
  "Read docs/discussions/0002-rag-kb-evaluator-review.md and add your response."
timestamp: 2026-04-27T15:21:25+02:00

---

agent: codex
task: Implement percentage-based RAG knowledge-base evaluator and generate corpus baseline
files_changed: rag_kb_evaluator.py, test_rag_kb_evaluator.py, rag_kb_evaluation_report.md, rag_kb_evaluation.json, rag_kb_evaluation.csv, workDone.md, docs/handoff.md
why: User requested the plan implemented so every major pipeline field/stage is evaluated with numerator, denominator, percentage, confidence, and retrieval percentages.
status: done
what_was_done: |
  1. Added `rag_kb_evaluator.py`, a read-only evaluator for `out/report`.
  2. Evaluator reads CFG/data/cobol_structure/copybook manifest/KB/chunks/JCL/comments artifacts and scores:
     source_to_artifact, artifact_to_knowledge_base, knowledge_base_to_chunks,
     chunk_metadata, and retrieval_at_5.
  3. Field families: program_structure, control_flow, data, copybooks, external_calls,
     cics, db2_sql, vsam_file_io, jcl, comments, chunks.
  4. Added deterministic retrieval benchmark over chunks with recall@1, recall@5, MRR,
     answerable-query percentage by category.
  5. Added `test_rag_kb_evaluator.py` with exact synthetic COBOL/JCL/chunk tests and
     a real PDCBVC golden check.
  6. Generated current outputs:
     - `rag_kb_evaluation_report.md`
     - `rag_kb_evaluation.json`
     - `rag_kb_evaluation.csv`
validation: |
  - `python3 test_rag_kb_evaluator.py` passed: 4 tests.
  - `python3 -m py_compile rag_kb_evaluator.py test_rag_kb_evaluator.py` passed.
  - Full corpus run completed against `out/report`: 443 reports, 44,195 chunks.
  - Current chunk baseline: 5,262 oversized chunks (11.91%), 4,772 thin chunks (10.80%),
    max token count 14,741, 4 missing required metadata fields.
next: |
  Ask Claude to review the evaluator methodology and the generated report. Important review points:
  (1) whether source-derived facts from `cobol_structure.json` should count as Source evidence when raw source
      is not discoverable,
  (2) whether chunk-family facts should be excluded from "top defects" because they are quality signals,
  (3) whether retrieval benchmark queries should sample more than 5 facts/category for final thesis charts.
timestamp: 2026-04-27T15:15:24+02:00

---

agent: claude-code
task: Analysis Quality section in 00_Executive_Summary.md + Codex phase-2 small fixes
files_changed: knowledge_base_builder.py, test_knowledge_base_builder.py, workDone.md
why: Codex verified proposal 0002 bullet counts, audited figurative constants, and recommended EXIT/STOP formatting and the Analysis Quality section. All recommendations applied.
status: done
what_was_done: |
  1. Added ## Analysis Quality section to 00_Executive_Summary.md — parse coverage %, copybook
     resolution ratio, confidence label (High/Medium/Low), stubbed copybook table with system
     and impact sourced from copybook_manifest.json + cobol_structure.json.
  2. Added QUOTE/QUOTES to _COBOL_FIGURATIVE_CONSTANTS (confirmed in FigurativeConstantMap.java).
  3. Added internal-space guard to _is_valid_target ('MY PROG' → False).
  4. Added EXIT/STOP dispatch: bare EXIT skipped silently; EXIT PERFORM/PARAGRAPH/SECTION
     rendered as **EXIT PERFORM** etc.; STOP RUN rendered as **STOP RUN**.
  5. Replaced brittle hardcoded PDCBVC bullet count (==298) with semantic assertions
     (68 GO TO, 1 STOP RUN) so future statement-type additions don't break the test.
  8 new tests; all 26 pass.
next: |
  Remaining hardening items (from Codex priority list in 0002-hardening-kb-phase1.md):
  1. BPE-aware chunk size enforcement in chunk_pipeline.py + validate_chunks.py (Decision 6)
  2. Split oversized section_summary chunks hierarchically (Decision 7)
  3. Restore Opus-MT comment_enricher.py pipeline (Decision 1)
  4. Second narrative pass: GOBACK, remaining invisible statement types
timestamp: 2026-04-27

---

agent: claude-code
task: Fix three knowledge_base_builder.py correctness bugs (LINKAGE mismatch, EVALUATE truncation, SPACES false-positive) + 18 tests
files_changed: knowledge_base_builder.py, test_knowledge_base_builder.py, docs/proposals/0002-hardening-kb-phase1.md, workDone.md
why: Codex audit (0001) identified these as the highest-priority correctness defects. All three are now fixed and regression-tested. 18/18 tests pass.
status: done
next: Read docs/proposals/0002-hardening-kb-phase1.md for the design rationale and the three questions addressed to Codex at the bottom (bullet count verification, figurative constant completeness, EXIT/STOP formatting). Deferred items: Opus-MT comment_enricher restore (Decision 1), Analysis Quality section in executive summary (Decision 3), BPE size guard in chunk_pipeline (Decision 6), section summary splitting (Decision 7).
timestamp: 2026-04-25

---

agent: claude-code
task: Codex audit — fix three bugs in hardening batch + enforce testing-first rule
files_changed: AGENTS.md, smojol-toolkit/src/main/java/org/smojol/toolkit/analysis/task/analysis/AnalysisSelfEvaluationWriter.java, smojol-toolkit/src/main/java/org/smojol/toolkit/task/SmojolTasks.java, workDone.md, docs/handoff.md
why: User asked Claude to audit all Codex changes for flaws and enforce a testing-first development priority.
status: done
what_was_done: |
  Full audit of all Codex-changed files since the hardening batch. Three bugs fixed:
  1. AnalysisSelfEvaluationWriter.cfgMetrics() line 110: originalText.contains("HANDLE") matched
     paragraphs/variables with "HANDLE" in the name (e.g., ERROR-HANDLER), generating false
     CICS_HANDLE_UNPARSED warnings. Fixed to: type == "DIALECT" && originalText.contains("EXEC CICS HANDLE").
  2. AnalysisSelfEvaluationWriter.walkData() line 229: counted root data-section container node as a
     variable (it has a "name" field but no levelNumber). Added levelNumber.isEmpty() guard so only
     actual COBOL data items are counted. Variable count was inflated by 1 for every program.
  3. SmojolTasks.run() lines 88/95: abort-on-base-failure used i==0 (positional) instead of checking
     commandLineAnalysisTasks.get(i) == BUILD_BASE_ANALYSIS. Fixed to identity check.
  AGENTS.md: Added "Development Priority Rule" section — harden and test before inventing new features;
  ban on permissive tests that only check absence of errors.
  Tests: 8/8 pass. CLI jar rebuilt.
next: |
  Gaps identified but not yet fixed (no test fixtures exist):
  - MISSING_PARSE_TREE, MISSING_DATA_STRUCTURES, MISSING_FLOW_ROOT, BASE_MODEL_NULL_STRUCTURE all
    lack dedicated test fixtures. They are backstop codes that are hard to trigger synthetically.
  - Pending items from prior sessions: chunk_pipeline.py on fresh corpus reports, cross-program
    call graph, exit_kinds propagation for large programs.
timestamp: 2026-04-25

---

agent: claude-code
task: Implement MISSING_IDENTIFICATION_DIVISION diagnostic and tighten regression test
files_changed: smojol-toolkit/src/main/java/org/smojol/toolkit/analysis/task/analysis/BuildBaseModelTask.java, smojol-toolkit/src/test/java/org/smojol/toolkit/analysis/task/JavaHardeningRegressionTest.java, workDone.md, docs/handoff.md, docs/discussions/0001-java-pipeline-general-hardening.md, docs/progress/2026-04-25-missing-identification-division.md
why: Claude's review of discussion 0001 identified the zBANK gap: programs starting with PROGRAM-ID without IDENTIFICATION DIVISION produced the misleading MISSING_PROCEDURE_DIVISION_BODY diagnostic, and the test only checked for absence of NPE strings rather than asserting a named code.
status: done
what_was_done: |
  1. Added a pre-check in BuildBaseModelTask.run() before the procedure-body check. Uses
     navigator.findByCondition(root, IdentificationDivisionContext.class) — the existing
     CobolEntityNavigator Class<T> overload. If the result is null or has exception != null
     (ANTLR error recovery set it), throws BaseModelValidationException("MISSING_IDENTIFICATION_DIVISION").
  2. Tightened writesHealthForMissingIdentificationDivisionInLenientMode: now asserts
     base_analysis_succeeded == false, primary_failure.diagnostic_code == "MISSING_IDENTIFICATION_DIVISION"
     in both analysis_health.json and analysis_self_evaluation.json, and that the warnings array
     contains the code. Old "no NPE strings" guards removed.
  Root cause confirmed: the fixture has PROCEDURE DIVISION, but ANTLR lenient error recovery
  for missing IDENTIFICATION DIVISION confuses the parse tree so procedureDivisionBody() returns
  null — which previously produced MISSING_PROCEDURE_DIVISION_BODY. The new check fires earlier.
  3. Rebuilt smojol-cli.jar. Ran full toolkit test suite.
validation: |
  - mvn -pl smojol-toolkit -Dtest=JavaHardeningRegressionTest test -Dcheckstyle.skip=true
    passed: 8 tests, 0 failures, 0 errors (incl. tightened lenient-mode test)
  - mvn -pl smojol-toolkit test -Dcheckstyle.skip=true
    passed: 17 tests, 0 failures, 0 errors, 2 skipped
  - Rebuilt smojol-cli.jar
  - Before: diagnostic_code = "MISSING_PROCEDURE_DIVISION_BODY" (misleading, test was permissive)
  - After:  diagnostic_code = "MISSING_IDENTIFICATION_DIVISION" (correct, test is specific)
  - Runtime: baseline 8.69s → after 8.07s (one additional O(n) tree search, negligible on 30-node tree)
performance: |
  The check adds one findByCondition() traversal before the existing procedureDivisionBody() call.
  Both are O(n) in parse tree nodes. For the 9-line test fixture (30 nodes), the added traversal
  terminates immediately at the root's first child. For large programs, IdentificationDivisionContext
  is always near the root and found in the first few levels. Measured: -0.6s on the 8-test suite
  (within noise). Effectively zero marginal cost.
next: |
  All three named structural diagnostics are now anchored by hard assertions:
    MISSING_PROCEDURE_DIVISION_BODY  → reportsStructuredDiagnosticForMissingProcedureBody
    MISSING_IDENTIFICATION_DIVISION  → writesHealthForMissingIdentificationDivisionInLenientMode (tightened)
    no-section transpiler           → transpilerHandlesParagraphsWithoutSections
  Next hardening layer (optional): move more diagnostics into ParsePipeline/data-structure
  construction. No current blocking gap.
timestamp: 2026-04-25T16:40:00+02:00

---

agent: codex
task: Implement generalized Java structural hardening and diagnostics
files_changed: smojol-toolkit/src/main/java/org/smojol/toolkit/intermediate/SectionParagraphMap.java, smojol-toolkit/src/main/java/org/smojol/toolkit/analysis/error/BaseModelValidationException.java, smojol-toolkit/src/main/java/org/smojol/toolkit/analysis/task/analysis/BuildBaseModelTask.java, smojol-toolkit/src/main/java/org/smojol/toolkit/analysis/task/analysis/CodeTaskRunner.java, smojol-toolkit/src/main/java/org/smojol/toolkit/analysis/task/analysis/AnalysisSelfEvaluationWriter.java, smojol-toolkit/src/test/java/org/smojol/toolkit/analysis/task/JavaHardeningRegressionTest.java, smojol-toolkit/test-code/flow-ast/no-section-transpiler.cbl, smojol-toolkit/test-code/flow-ast/missing-procedure-body.cbl, smojol-toolkit/test-code/flow-ast/missing-identification-division.cbl, docs/discussions/0001-java-pipeline-general-hardening.md, workDone.md, docs/handoff.md
why: User asked to implement the general Java hardening plan and explicitly avoid one-file-specific fixes. The implementation removes a section/paragraph null assumption, converts base-model structural failures into stable diagnostics, and anchors behavior with synthetic fixtures representing structural classes.
status: done
what_was_done: |
  1. Hardened `SectionParagraphMap.nextParagraph()` so paragraphs without section mappings or empty section paragraph lists return `Optional.empty()` instead of throwing.
  2. Added `BaseModelValidationException` with stable diagnostic code and analysis stage fields.
  3. Added explicit base-model checks for missing parse tree, missing `PROCEDURE DIVISION` body, missing data-structure root, and missing flow root. Remaining base-model NPEs are wrapped as `BASE_MODEL_NULL_STRUCTURE` diagnostics.
  4. Exported base-model diagnostic fields in `analysis_health.json` and copied primary failure diagnostics into `analysis_self_evaluation.json` warnings.
  5. Added general regression fixtures/tests for no-section procedure layouts, missing procedure body, and missing `IDENTIFICATION DIVISION` under lenient mode.
  6. Opened `docs/discussions/0001-java-pipeline-general-hardening.md` for Claude review of the broader strategy.
validation: |
  - `mvn -pl smojol-toolkit -Dtest=JavaHardeningRegressionTest test -Dcheckstyle.skip=true` passed: 8 tests, 0 failures, 0 errors.
  - `mvn -pl smojol-toolkit test -Dcheckstyle.skip=true` passed: 17 tests, 0 failures, 0 errors, 2 skipped.
  - `mvn -pl smojol-cli -am package -Dcheckstyle.skip=true -Dmaven.test.skip=true -q` rebuilt `smojol-cli/target/smojol-cli.jar` (74 MB, Apr 25 15:37).
next: |
  Ask Claude to review the discussion thread using: "Read docs/discussions/0001-java-pipeline-general-hardening.md and add your response."
  Possible next hardening layer: move more structured diagnostics into `ParsePipeline` and data-structure construction so lenient malformed inputs produce fewer internal raw null warnings before the task-level base-model diagnostic catches them.
timestamp: 2026-04-25T15:37:37+02:00

---

agent: claude-code
task: Review Codex's generalized Java hardening pass (discussion 0001) and add response
files_changed: docs/discussions/0001-java-pipeline-general-hardening.md, workDone.md, docs/handoff.md
why: Codex opened discussion 0001 asking whether the outer diagnostic contract is the right next hardening layer before going deeper into ParsePipeline and data-structure builder.
status: done
what_was_done: |
  Reviewed SectionParagraphMap.java, BuildBaseModelTask.java, CodeTaskRunner.primaryFailure(),
  AnalysisSelfEvaluationWriter.java, and JavaHardeningRegressionTest.java (new tests at line 135+).
  - SectionParagraphMap.nextParagraph() guards (null section, null/empty list, indexOf==-1) are correct
    and complete. Directly fixes COCRDLIC Step 2 parasForSection NPE.
  - BuildBaseModelTask MISSING_* diagnostic codes and NullPointerException backstop are correct.
  - AnalysisSelfEvaluationWriter warning logic and scoring formula are production-ready.
  - Named-diagnostic tests for missing-procedure-body and no-section-transpiler are structural-class tests.
  - The writesHealthForMissingIdentificationDivisionInLenientMode test is too permissive: it asserts
    absence of NPE strings but not a specific diagnostic code. zBANK case still falls to the NPE backstop.
  Recommended next step in discussion: add MISSING_IDENTIFICATION_DIVISION diagnostic in BuildBaseModelTask,
  tighten that test to assert the exact code. No changes needed to outer contract or SelfEvaluationWriter.
next: |
  Codex to implement MISSING_IDENTIFICATION_DIVISION diagnostic and tighten the lenient-mode test.
  No other blocking issues in the outer contract layer.
timestamp: 2026-04-25T16:15:00+02:00

---

agent: codex
task: Restore CICS LINK regression coverage, fix COCRDLIC expression-description NPEs, and run external corpus/RAG validation
files_changed: smojol-core/src/main/java/org/smojol/common/vm/expression/RelationExpression.java, smojol-core/src/main/java/org/smojol/common/vm/expression/IdmsExpression.java, smojol-toolkit/src/test/java/org/smojol/toolkit/analysis/task/JavaHardeningRegressionTest.java, smojol-toolkit/test-code/flow-ast/cics-handle.cbl, workDone.md, docs/handoff.md
why: User asked for the next Java validation/hardening plan. LINK/SEND support needed to be rechecked after Claude's correction, and COCRDLIC.cbl had real Java NPEs in condition/dialect expression description paths that prevented WRITE_FLOW_AST/WRITE_CFG from completing.
status: done
what_was_done: |
  1. Added `EXEC CICS LINK PROGRAM('PAYPGM') COMMAREA(WS-MSG) END-EXEC` back to `cics-handle.cbl` and restored assertions for `cics_command=LINK` and `cics_target_program=PAYPGM`.
  2. Tried adding `EXEC CICS SEND MAP('MAINMAP') END-EXEC` to the strict fixture, but `mvn -pl smojol-toolkit test -Dcheckstyle.skip=true` proved the fixture still fails strict parse with `Extraneous input 'SEND'`. Removed SEND from the strict fixture; real corpus runs still confirm SEND metadata on lenient programs (`COCRDLIC.cbl`: 3 SEND nodes, `BNK1CCS.cbl`: 5 SEND nodes).
  3. Fixed `RelationExpression.description()` null `relationalOperation` by emitting `UNKNOWN_RELATION` and fixed null RHS with `<missing-rhs>`.
  4. Fixed `IdmsExpression.description()` null parse tree by emitting `<missing-expression>`.
  5. Replaced `taskResults.getFirst()` in `JavaHardeningRegressionTest` with `taskResults.get(0)` to avoid Java-version-sensitive test code.
validation: |
  - Ran stale-bytecode cleanup for smojol-core/smojol-toolkit/smojol-cli target class directories.
  - `mvn -pl smojol-toolkit -am compile -Dcheckstyle.skip=true -q` passed.
  - `mvn -pl smojol-toolkit test -Dcheckstyle.skip=true` passed: 14 tests, 0 failures, 0 errors, 2 skipped.
  - `mvn -pl smojol-cli -am package -Dcheckstyle.skip=true -Dmaven.test.skip=true -q` rebuilt `smojol-cli.jar` at Apr 25 14:33.
  - Stale bytecode checks for `MultiCommand.class` and `DialectStatementFlowNode.class` both returned 0 `Unresolved compilation` strings.
  - `cics-handle.cbl` strict analysis produced CFG metadata for LINK plus HANDLE CONDITION/AID/ABEND; the only failure in that smoke run was unrelated `EXPORT_GRAPHVIZ` because `dot` is not installed.
  - `COCRDLIC.cbl` now completes WRITE_FLOW_AST/WRITE_CFG: 762 CFG nodes, 9 EVALUATE, 33 EVALUATE_BRANCH, 18 DIALECT, 0 GENERIC_STATEMENT, 19 exit-kind nodes. A separate Step 2 transpiler NPE remains: `parasForSection` is null in BUILD_TRANSPILER_FLOWGRAPH.
  - External smoke runs completed for cics-genapp `lgapvs01.cbl`, CBSA `BNK1CCS.cbl`, z/OS Connect `claimci0.cbl`, db2-samples `client.cbl`, zopeneditor `SAM1.cbl`, and zBANK `CICS.COB_ZBANK3_.cbl`.
  - zBANK `CICS.COB_ZBANK3_.cbl` remains a base-analysis failure: source starts at `PROGRAM-ID` without `IDENTIFICATION DIVISION`, lenient coverage 99.29%, but base task fails with null `astNode`.
  - Ran `chunk_pipeline.py` on fresh `COCRDLIC`, `BNK1CCS`, and `cics-handle` reports. Handler metadata appears in chunks for BNK1CCS/cics-handle; exit metadata appears in cics-handle chunks but is not consistently surfaced for large programs.
next: |
  Recommended next Java fixes:
  - Fix the COCRDLIC Step 2 transpiler NPE (`parasForSection` null) separately from the already-fixed WRITE_CFG/WRITE_FLOW_AST NPEs.
  - Add a parser/base-model recovery path for programs missing `IDENTIFICATION DIVISION` (zBANK style) or at least emit an explicit unsupported-structure diagnostic instead of null `astNode`.
  - Keep SEND out of strict Java fixture until the CICS grammar accepts the fixture form; rely on real lenient corpus tests for SEND metadata meanwhile.
  - Python/RAG follow-up: paragraph chunks do not consistently propagate `exit_kinds` for large programs even though Java CFG metadata contains them.
timestamp: 2026-04-25T14:39:02+02:00

---

agent: claude-code
task: Fix ECJ stale class files, validate test suite, rebuild JAR, run external corpus analysis, fix sandbox bug
files_changed: smojol-toolkit/src/test/java/org/smojol/toolkit/analysis/task/JavaHardeningRegressionTest.java, analysis/sandbox_manager.py, workDone.md, docs/handoff.md
why: Context from previous session: ECJ stale .class files in smojol-core/target/test-classes, smojol-toolkit/target/test-classes, smojol-toolkit/target/classes, and smojol-cli/target/classes caused persistent "Unresolved compilation problem" errors across tests and the CLI JAR. The cics-handle.cbl fixture had EXEC CICS LINK/SEND removed (poc-branch grammar doesn't support them), so test assertions checking for cics_command=LINK etc. were invalid.
status: done
what_was_done: |
  1. Removed 3 invalid assertions from JavaHardeningRegressionTest.exportsCicsHandleBindingsAsMetadata (lines 80-82: LINK/SEND metadata). The 4 HANDLE binding assertions (lines 76-79) remain and pass.
  2. Deleted stale .class files from all 4 module target directories; recompiled each cleanly. All 14 smojol-toolkit tests pass (2 skipped, 0 failures, 0 errors).
  3. Rebuilt smojol-cli/target/smojol-cli.jar (Apr 25 11:15, 74 MB, no stale bytecode).
  4. Ran analyze.py on 6 programs from external corpora:
     - CBACT01C.cbl (carddemo, strict, 348 nodes, 2 CALL nodes w/targets, 0 DIALECT)
     - CBTRN01C.cbl (carddemo, strict, 384 nodes)
     - BNK1CCS.cbl (cbsa, lenient, 958 nodes, 54 DIALECT nodes — ASSIGN/LINK/RETURN/SEND/ABEND/FORMATTIME/ASKTIME/HANDLE/INQUIRE/RECEIVE/WRITE)
     - lgapvs01.cbl (cics-genapp, strict, 83 nodes, 7 DIALECT nodes — LINK/RETURN/WRITE/ASKTIME/FORMATTIME)
     - lgicus01.cbl (cics-genapp, strict, 78 nodes, 9 DIALECT nodes)
     - BNK1DCS.cbl (cbsa, after sandbox fix)
  5. Fixed pre-existing RuntimeError in analysis/sandbox_manager.py: _setup_copybooks() modified a set while iterating it during transitive copybook discovery. Replaced with explicit pending/seen work-queue pattern.
  All fresh reports include: analysis_health.json, analysis_self_evaluation.json, CALL/GOTO/PERFORM metadata, typed statement nodes, dialect metadata for CICS.
next: |
  No known blocking issues remain. Possible next tasks:
  - Investigate COCRDLIC.cbl failure (NullPointerException in relationalOperation.mnemonic() and expression.getText()) — these are pre-existing NPEs in the Flow AST/CFG for certain comparison expression constructs. Worth a targeted fix if more programs hit the same pattern.
  - Run chunk_pipeline.py on fresh external corpus reports to generate RAG chunks.
  - Build corpus index and cross-program call graph across all external programs.
  - The 90 older reports (April 17) predate analysis_health.json — delete and reanalyze if fresh health artifacts are needed for all programs.
  - Consider adding --copybooks support to batch_runner.py for external corpus runs.
timestamp: 2026-04-25T13:45:00+02:00

---

agent: claude-code
task: Set up multi-agent co-working environment for Codex ↔ Claude Code
files_changed: AGENTS.md, docs/proposals/README.md, docs/handoff.md
why: User is adding Codex CLI alongside Claude Code. Needed to (1) point Codex at CLAUDE.md as authoritative deep reference, (2) add a proposal/discussion protocol so the two agents can "talk" via files, (3) add branch-hygiene rules to avoid races on the shared `develop` branch, (4) add Codex-specific operational notes.
status: done
next: Codex's first session — paste the intro prompt (provided separately by the user), have Codex confirm it read AGENTS.md + CLAUDE.md, and optionally smoke-test the proposal flow via a trivial handshake file. No open proposals yet.
timestamp: 2026-04-24

---

agent: codex
task: Implement remaining Java hardening batch for metadata exports, typed statements, dialect metadata, self-evaluation artifact, and external corpus manifest
files_changed: smojol-core/src/main/java/org/smojol/common/vm/expression/SimpleConditionExpression.java, smojol-core/src/main/java/org/smojol/common/vm/expression/ConditionVisitor.java, smojol-core/src/main/java/org/smojol/common/vm/expression/AdditionalConditionVisitor.java, mojo-common/src/main/java/com/mojo/algorithms/domain/FlowNodeType.java, smojol-toolkit/src/main/java/org/smojol/toolkit/ast/CallFlowNode.java, smojol-toolkit/src/main/java/org/smojol/toolkit/ast/GoToFlowNode.java, smojol-toolkit/src/main/java/org/smojol/toolkit/ast/PerformProcedureFlowNode.java, smojol-toolkit/src/main/java/org/smojol/toolkit/ast/TypedStatementFlowNode.java, smojol-toolkit/src/main/java/org/smojol/toolkit/ast/CobolFlowNodeFactory.java, smojol-toolkit/src/main/java/org/smojol/toolkit/ast/DialectMetadataParser.java, smojol-toolkit/src/main/java/org/smojol/toolkit/ast/DialectStatementFlowNode.java, smojol-toolkit/src/main/java/org/smojol/toolkit/analysis/task/analysis/AnalysisSelfEvaluationWriter.java, smojol-toolkit/src/main/java/org/smojol/toolkit/analysis/task/analysis/CodeTaskRunner.java, smojol-toolkit/src/test/java/org/smojol/toolkit/analysis/task/JavaHardeningRegressionTest.java, smojol-toolkit/test-code/flow-ast/metadata-features.cbl, smojol-toolkit/test-code/flow-ast/cics-handle.cbl, workDone.md, docs/handoff.md, /home/eri/workspace/sapienza/master-thesis/codefiles/external/CORPUS_MANIFEST.md
why: User requested the remaining Java hardening plan. This batch exposes existing Java truth in metadata, reduces GENERIC_STATEMENT blind spots, adds metadata-first CICS/SQL dialect visibility, writes a Java-owned self-evaluation artifact for every report, and sets up the external corpus manifest needed for broad gap evaluation.
status: partial
next: Validation is blocked before the new regression tests can run cleanly. `mvn -pl smojol-toolkit -am test -Dcheckstyle.skip=true` fails in the sandboxed Che4z tests because Mockito inline cannot self-attach on this JDK. `mvn -pl smojol-toolkit -am test -Dcheckstyle.skip=true -DskipTests` reaches smojol-toolkit but then hits the broader pre-existing parser-type mismatch set (`CobolParser.*` versus `org.eclipse.lsp.cobol.core.CobolParser.*`) across files such as `SmojolInterpreter`, `DivideFlowNode`, `DefaultFormat1DataStructureBuilder`, and `EvaluateFlowNode`. Fix that branch-wide parser-type drift first, then rerun the metadata/self-evaluation regression tests and rebuild `smojol-cli` before corpus analysis. External corpora are cloned under `/home/eri/workspace/sapienza/master-thesis/codefiles/external/`; do not reclone unless the manifest needs refreshing.
timestamp: 2026-04-25T00:52:49+02:00

---

agent: codex
task: Write Java-first COBOL analysis audit memo with corpus-backed findings
files_changed: docs/java-first-cobol-audit-2026-04-24.md, workDone.md, docs/handoff.md
why: User requested an in-depth audit of the COBOL analysis pipeline with the Java parser/CFG/data-structure layer treated as the main truth source before reviewing Python and RAG quality. The memo documents current strengths, critical truth gaps, and a phased recommendation path grounded in both code inspection and the existing report corpus.
status: done
next: Use the memo as the basis for deciding whether to fix Java truth first (`EVALUATE`, CICS HANDLE, quality metadata, partial-tree hardening) or to spin out smaller implementation tasks. Re-run the older RAG evaluation only after deciding which upstream Java fixes will land first, because some historical downstream findings are already resolved in the current tree.
timestamp: 2026-04-24

---

agent: codex
task: Correct progress folder state and summarize general COBOL analysis improvements
files_changed: docs/progress/2026-04-25-stale-classes-corpus-validation.md, docs/progress/README.md, workDone.md, docs/handoff.md
why: User asked whether the progress folder was correct and what the broader COBOL-analysis improvements are. The progress docs still contained some mid-debug/superseded conclusions, so I updated them to match the latest validated state before summarizing.
status: done
next: Progress docs now distinguish restored LINK coverage, SEND strict-fixture sensitivity, fixed COCRDLIC FLOW_AST/CFG NPEs, and remaining Java gaps. Next technical follow-ups remain the Step 2 transpiler NPE, missing-division/base-model resilience, and any RAG surfacing gaps for EVALUATE branch metadata.
timestamp: 2026-04-25T14:50:17+02:00

---

agent: codex
task: Implement first Java hardening batch for task aborts, health output, EVALUATE branches, exit metadata, statement typing, and CICS HANDLE metadata
files_changed: mojo-common/src/main/java/com/mojo/algorithms/transpiler/FlowNodeLike.java, mojo-common/src/main/java/com/mojo/algorithms/domain/FlowNodeType.java, smojol-core/src/main/java/org/smojol/common/ast/SerialisableCFGFlowNode.java, smojol-core/src/main/java/org/smojol/common/ast/SerialisableASTFlowNode.java, smojol-core/src/main/java/org/smojol/common/ast/SyntaxIdentity.java, smojol-toolkit/src/main/java/org/smojol/toolkit/task/SmojolTasks.java, smojol-toolkit/src/main/java/org/smojol/toolkit/analysis/task/analysis/BuildBaseModelTask.java, smojol-toolkit/src/main/java/org/smojol/toolkit/analysis/task/analysis/CodeTaskRunner.java, smojol-toolkit/src/main/java/org/smojol/toolkit/ast/EvaluateFlowNode.java, smojol-toolkit/src/main/java/org/smojol/toolkit/ast/EvaluateBranchFlowNode.java, smojol-toolkit/src/main/java/org/smojol/toolkit/ast/ExitFlowNode.java, smojol-toolkit/src/main/java/org/smojol/toolkit/ast/DialectStatementFlowNode.java, smojol-toolkit/src/main/java/org/smojol/toolkit/ast/CicsBlockFlowNode.java, smojol-toolkit/src/main/java/org/smojol/toolkit/ast/CobolFlowNodeFactory.java, smojol-toolkit/src/main/java/org/smojol/toolkit/ast/StringFlowNode.java, smojol-toolkit/src/main/java/org/smojol/toolkit/ast/UnstringFlowNode.java, smojol-toolkit/src/main/java/org/smojol/toolkit/ast/AlterFlowNode.java, smojol-toolkit/src/main/java/org/smojol/toolkit/ast/CicsHandleBindingParser.java, smojol-toolkit/src/test/java/org/smojol/toolkit/analysis/task/JavaHardeningRegressionTest.java, smojol-toolkit/test-code/flow-ast/hardening-features.cbl, smojol-toolkit/test-code/flow-ast/cics-handle.cbl, smojol-toolkit/test-code/flow-ast/missing-copybook.cbl, workDone.md, docs/handoff.md
why: User asked to implement the Java-first hardening plan. This batch fixes the clean-abort behavior after base-analysis failure, adds a stable Java-owned `analysis_health.json` contract, exports real `EVALUATE_BRANCH` nodes plus `exit_kind`/`ALTER`/CICS HANDLE metadata, and adds regression fixtures/tests to anchor the new output shape.
status: partial
next: The code is saved, but validation is blocked by pre-existing reactor problems on the shared branch: `smojol-core` checkstyle already fails in `ClassConditionBuilder.java`, and even with checkstyle skipped the current tree hits broader parser-type compile mismatches across `smojol-toolkit`. Before refining this batch further, compare my changes against Claude’s current Java work and decide whether to (1) fix the branch-wide compile breakage first, then rerun `mvn -pl smojol-toolkit -am -Dtest=JavaHardeningRegressionTest,WriteFlowASTTaskRegressionTest test -Dcheckstyle.skip=true -Dsurefire.failIfNoSpecifiedTests=false`, or (2) split this into smaller commits after reconciling the parser-type drift.
timestamp: 2026-04-24

---

agent: claude-code
task: Review and fix Codex’s Java hardening batch — resolve reactor compile blocker, fix test infrastructure bugs, make all 4 regression tests pass
files_changed: smojol-toolkit/src/main/java/org/smojol/toolkit/ast/ExitFlowNode.java, smojol-toolkit/src/main/java/org/smojol/toolkit/ast/DialectStatementFlowNode.java, smojol-toolkit/src/test/java/org/smojol/toolkit/analysis/task/JavaHardeningRegressionTest.java, smojol-toolkit/src/test/java/org/smojol/toolkit/analysis/task/TestTaskRunner.java, smojol-toolkit/test-code/flow-ast/cics-handle.cbl, docs/audit-discussion-2026-04-24.md, workDone.md, docs/handoff.md
why: Codex’s batch had a diamond type-inference error in ExitFlowNode that cascaded to 20+ false compile errors. Three additional bugs (JUnit version, TestTaskRunner hardcoded index, invalid CICS fixture syntax) prevented the regression tests from running. A fifth bug (DialectStatementFlowNode missing metadata() for HANDLE AID/ABEND) was exposed once parsing was fixed.
status: done
bugs_fixed:
  - ExitFlowNode SyntaxIdentity<ParseTree> type parameter (reactor compile blocker)
  - assertInstanceOf -> assertTrue instanceof (JUnit 5.6.0 compat)
  - TestTaskRunner.get(1) -> get(size-1) (abort-path robustness)
  - cics-handle.cbl PF3() empty parens removed (parse failure)
  - DialectStatementFlowNode.metadata() added (HANDLE AID/ABEND metadata was missing)
test_result: 4/4 JavaHardeningRegressionTest pass; all pre-existing smojol-toolkit tests still pass (clean build)
next: The hardening batch is now fully validated. Next steps for Codex or Claude: (1) integrate analysis_health.json consumption into chunk_pipeline.py to replace the Python-side quality heuristics; (2) verify EVALUATE_BRANCH edges appear correctly in CFG for multi-branch programs in the corpus; (3) address the DialectStatementFlowNode.buildInternalFlow() global-lookup root cause (tagged TODO in the file).
timestamp: 2026-04-24

---

agent: claude-code
task: Corpus verification of hardening batch, chunk_pipeline.py integration, DialectStatementFlowNode global-lookup fix
files_changed: chunk_pipeline.py, smojol-toolkit/src/main/java/org/smojol/toolkit/ast/DialectStatementFlowNode.java, docs/audit-discussion-2026-04-24.md, workDone.md, docs/handoff.md
why: User requested corpus-wide verification of all 7 hardening features before more implementation work, then integration of analysis_health.json into the chunk pipeline, and the DialectStatementFlowNode global-lookup fix.
status: done
verification_results:
  EVALUATE_BRANCH: "confirmed — test-evaluate-without-through.cbl: 1 EVALUATE → 3 BRANCH nodes with STARTS_WITH edges; rich metadata including condition_expression"
  exit_kind: "confirmed — EXIT PARAGRAPH → EXIT_PARAGRAPH, GOBACK → GOBACK on EXIT-typed nodes"
  STRING_UNSTRING_ALTER_types: "confirmed — not GENERIC_STATEMENT; ALTER has dynamic_control_hazard metadata"
  CICS_HANDLE_real_programs: "confirmed — all three HANDLE variants on cics-real-test.cbl"
  analysis_health_scenarios: "confirmed — strict success, base failure, partial success (base OK + WRITE_CFG failed)"
java_fix:
  file: smojol-toolkit/src/main/java/org/smojol/toolkit/ast/DialectStatementFlowNode.java
  change: "navigator.findByCondition(executionContext, ...) — scoped to current execution context"
  effect: "DIALECT_CONTAINER nodes now emit correct per-block handler_bindings; was always returning first container's data"
  null_guard: "added — returns early with WARNING log if no DialectContainerNode found under executionContext"
chunk_pipeline_changes:
  - "_get_analysis_health() helper added"
  - "_compute_parse_quality() returns 'unknown' when base_analysis_succeeded=false"
  - "generate_cobol_analysis_health() enriched with base_analysis_succeeded, analysis_mode, completed_tasks, failed_tasks, primary_failure_task/message, confidence='none' label"
  - "_build_paragraph_subgraphs() extracts exit_kinds/handler_bindings/alter_hazards from node metadata"
  - "enrich_paragraph_chunks() propagates exit_kinds→metadata, cics_handler_bindings→metadata+text, alter_hazards→metadata+text"
test_result: 4/4 JavaHardeningRegressionTest pass; full smojol-toolkit suite passes (13 run, 0 fail, 2 skip)
next: |
  - Re-run chunk_pipeline.py on the full corpus after re-analyzing programs with the new JAR to populate exit_kinds/handler_bindings/alter_hazards in the RAG index.
  - The EVALUATE_BRANCH fix now emits condition_expression strings (full AST-level type annotation). Consider whether the RAG chunks should also surface EVALUATE branch structure (currently only paragraph-level is captured).
  - COTRN02C WRITE_CFG fails with NullPointerException in EvaluateFlowNode/condition evaluation — a null expression guard is needed. Root cause: SimpleConditionExpression.getComparison() returns null for complex EVALUATE conditions. This is a pre-existing issue, not introduced by the hardening batch.
timestamp: 2026-04-24

---

agent: codex
task: Audit Python knowledge-base pipeline and open proposal 0001
files_changed: docs/proposals/0001-knowledge-base-python-audit.md, workDone.md, docs/handoff.md
why: User requested an evidence-based audit of knowledge-base completeness, chunking strategy, Italian comment handling, and output formats. The proposal records source-level findings, real output examples, token distribution data, and concrete reviewer decisions for Claude Code.
status: done
next: Claude should review `docs/proposals/0001-knowledge-base-python-audit.md` and answer the numbered decisions. Highest-risk findings to address first are the current `comment_enricher.py`/`analyze.py` API mismatch, data dictionary dropping real `LINKAGE` sections, and chunk validation allowing thousands of over-512 BPE chunks.
timestamp: 2026-04-25T17:14:43+02:00

---

agent: codex
task: Verify KB phase-1 bullet counts and answer proposal 0002 follow-up questions
files_changed: test_knowledge_base_builder.py, docs/proposals/0002-hardening-kb-phase1.md, workDone.md, docs/handoff.md
why: User asked for a grounded follow-up audit of Claude's phase-1 KB hardening work: verify the exact PDCBVC narrative counts from real traversal, review figurative-constant coverage, decide how EXIT/STOP should surface in the knowledge base, and prioritize the next hardening pass.
status: done
next: The exact PDCBVC counts are now anchored: 297 narrative bullets and 68 GO TO bullets, so the integration test was tightened from permissive `>=` to exact `==`. Proposal 0002 now contains Codex's recommendations: add `QUOTE`/`QUOTES` to the figurative-constant guard, reject targets containing spaces, do not impose a blanket 8-char limit on all CALL targets, skip bare `EXIT` but render qualified `EXIT` and `STOP RUN`, and prioritize executive-summary quality surfacing plus BPE-aware chunk sizing next.
timestamp: 2026-04-25T18:05:00+02:00

---

agent: codex
task: Review Claude's latest knowledge-base hardening changes
files_changed: docs/handoff.md
why: User asked for an evaluation of Claude's latest local changes and whether any follow-up work remains. I reviewed the current `knowledge_base_builder.py` and `test_knowledge_base_builder.py` diff, reran the KB tests, and checked the new Analysis Quality behavior against existing report artifacts.
status: done
next: No blocking issues found in Claude's latest KB patch. The code and tests are in good shape. Remaining worthwhile work is the previously deferred hardening list: BPE-aware chunk size enforcement, oversized `section_summary` splitting, Opus-MT comment pipeline restoration, and a small optional robustness pass to let the executive summary use `analysis_health.json` as a fallback when `parse_diagnostics.json` is absent.
timestamp: 2026-04-27T00:00:00+02:00

---

agent: codex
task: Implement proposal 0003 RAG readiness phases A-G
files_changed: chunk_pipeline.py, rag_kb_evaluator.py, validate_chunks.py, test_chunk_pipeline.py, test_rag_kb_evaluator.py, docs/proposals/0003-rag-readiness.md, workDone.md, docs/handoff.md
why: User approved the Phase A-G implementation plan for evaluator methodology fixes, BPE-aware universal splitting, thin chunk policy, cics_operations chunks, health enrichment, duplicate reporting, and schema 1.4 validation.
status: done
next: Full 486-report chunk regeneration was intentionally not run. The approved four-report samples under /tmp show oversized chunks reduced to 0 and max BPE 512, but full-corpus pass criteria that require regenerated chunks still need a deliberate corpus regeneration/evaluator run later. I also observed existing chunk_pipeline reruns on an already-generated chunks directory can leave stale split-part files; use fresh output dirs or add cleanup before full regeneration.
timestamp: 2026-04-28T23:20:22+02:00

---

agent: claude-code
task: Post-implementation verification of Codex Phase A-G (proposal 0003)
files_changed: chunk_pipeline.py, docs/proposals/0003-rag-readiness.md, workDone.md, docs/handoff.md
why: User asked me to independently verify Codex's Phase A-G implementation, run all test suites, re-derive key baseline numbers, and write a verification report to the proposal. I also fixed two non-blocking gaps found during verification.
status: done
findings: |
  - All 47 tests pass (7 evaluator + 14 chunk-pipeline + 26 KB builder)
  - control_flow.composite = 75.68% corpus-level (pass target ≥50%)
  - control_flow.legacy_verbatim = 2.79% (preserved for one cycle)
  - JCL jcl:artifact_to_knowledge_base = not_applicable (41 programs)
  - Unevaluable programs = 12
  - chunks field excluded from top_defects; appears only in chunk_quality_defects
  - 4-report sample: 924 chunks, max BPE = 512, 2 cics_operations chunks emitted
  - F1 FIXED: generate_cics_operations() now filters figurative constants (SPACES etc.) from cics_calls
  - F2 FIXED: cics_command_count added to cics_operations metadata
  - F3 informational: branch_marker_coverage = 0% for PDCBVC (IF_BRANCH not rendered in KB; weight=0.10; composite unaffected)
  - F4/F5 informational: idempotency stale-file issue and range-based (not exact) bullet count test
next: |
  - Full 486-report corpus regeneration: run chunk_pipeline.py on fresh chunks/ dirs for all reports
  - After regeneration: re-run rag_kb_evaluator.py to measure CICS Recall@1 with cics_operations chunks in place
  - Proposal 0004-cics-dependencies-deprecation: strip CICS from dependencies chunk after one evaluator cycle confirms gain
  - IDMS guard manual backport (DialectIntegratorListener.java + ParsePipeline.java, no cherry-pick of 756ee536)
timestamp: 2026-04-29T00:00:00+02:00

agent: codex
task: Close proposal 0003 and open 0004 chunking strategy review
files_changed: docs/proposals/0003-rag-readiness.md, docs/proposals/0004-chunking-strategy-review.md, workDone.md, docs/handoff.md
why: User requested proposal 0003 closeout and a no-implementation design review of chunking/retrieval alternatives before any further architecture changes.
status: done
next: Claude Code should read docs/proposals/0004-chunking-strategy-review.md and answer the Option A/B design questions, especially metadata-rich retrieval and call-chain expansion. Tests run: python3 test_chunk_pipeline.py && python3 test_rag_kb_evaluator.py && python3 test_knowledge_base_builder.py; all 47 passed (14 + 7 + 26).
timestamp: 2026-04-29T08:42:13+02:00

agent: codex
task: Test failed COBOL files and compare old vs current reports
files_changed: docs/failed-files-comparison-2026-04-29.md, workDone.md, docs/handoff.md
why: User asked to test the three COBOL files in codefiles/failed files, generate current reports without deleting the old reports, and compare the reports across multiple areas.
status: done
next: Old reports were left untouched. Fresh reports live under /tmp/cobol_rekt_failed_compare.katmp7/out/report. Main caveat: current isolated rerun had no real copybooks, so all COPYs were stubbed; semantic/data completeness should be retested with the original copybook roots if parity with old reports matters.
timestamp: 2026-04-29T08:55:35+02:00

agent: codex
task: Document real-codebase RAG readiness gaps and test checklist
files_changed: docs/failed-files-comparison-2026-04-29.md, workDone.md, docs/handoff.md
why: User asked to record where the COBOL/RAG tool is still lacking for a 1M+ line, 1500+ file estate and add future test checklists for each gap.
status: done
next: Use the new "Real-Codebase Readiness Gaps" section as the backlog for hardening before claiming production-scale readiness. No code or tests were run; documentation-only update.
timestamp: 2026-04-29T09:28:52+02:00

agent: codex
task: Restore lost tracked Python changes after accidental hard reset
files_changed: analysis/sandbox_manager.py, chunk_pipeline.py, validate_chunks.py, knowledge_base_builder.py, test_chunk_pipeline.py, test_knowledge_base_builder.py, test_rag_kb_evaluator.py, workDone.md, docs/handoff.md
why: User reported that four tracked Python files reverted to committed state while the untracked tests/evaluator were safe; re-implemented the schema 1.4 RAG readiness changes, KB hardening, recursive copybook BFS fix, validation updates, and sanitized real program names in tests.
status: done
next: Recovery artifacts were not found in unreachable blobs or stash. Tests run: python3 test_chunk_pipeline.py && python3 test_rag_kb_evaluator.py && python3 test_knowledge_base_builder.py; all passed (14 with 2 skipped, 7 with 1 skipped, 26 with real-report-dependent cases skipped after placeholder sanitization).
timestamp: 2026-04-29T16:20:00+02:00
