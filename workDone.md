# Work Done Log

Most recent entries first.

---

## 2026-04-16 — Fix Java level-88 condition export in data structures JSON

**File(s):** `smojol-core/src/main/java/org/smojol/common/vm/structure/Format1DataStructure.java`
**What changed:** Overrode `acceptScopedVisitor()` in `Format1DataStructure` to also walk `this.conditions` (level-88 entries stored in a separate list). The base class `CobolDataStructure.acceptScopedVisitor()` only walked `this.structures`, silently omitting all 88-level conditions from the exported `*-data.json` files.
**Why:** Bug — `cobol_structure_analyzer.py` and `chunk_pipeline.py` both tried to extract 88-level conditions from the data structures JSON but found zero entries in every program because the Java exporter never included them. This blocked the planned `business_rules` RAG chunk type and the `conditions_88` field in `cobol_structure.json`.

---

## 2026-04-15 — Fix RAG chunk accuracy: parse_quality, cics_calls metadata, SQL false positives, dedup

**File(s):** `chunk_pipeline.py`, `knowledge_base_builder.py`
**What changed:**
- `chunk_pipeline.py` `_compute_parse_quality()`: return `"full"` (not `"unknown"`) when `parse_diagnostics.json` is absent — absence means strict parse with zero errors.
- `chunk_pipeline.py` `generate_dependencies()`: load `cics_calls` from `03_Dependencies.yaml`, add CICS LINK/XCTL targets to chunk text and `cics_calls` metadata field.
- `chunk_pipeline.py` `_build_paragraph_subgraphs()`: skip `BEGIN DECLARE`, `END DECLARE`, `INCLUDE`, `WHENEVER` markers when extracting `sql_operations` — these are DATA DIVISION structural markers, not executable SQL.
- `knowledge_base_builder.py` `_build_dependencies()`: remove per-append `not in` guards on `cics_calls`; replace with a post-collection dedup pass keyed on `(command, target)` for consistency with other list deduplication.
**Why:** Evaluation of 370 report directories revealed that parse_quality was always "unknown" for clean programs, CICS call targets were invisible to metadata search, and DATA DIVISION SQL markers produced false positive sql_operations entries.

---

## 2026-04-05 — Update CLAUDE.md: comment_extractor filter, category rules, 03_Dependencies structure, 00_Executive_Summary warnings

**File(s):** `CLAUDE.md`
**What changed:** Updated `comment_extractor.py` entry to document the `_is_code_comment()` multi-layer filter. Updated Step 7b `CATEGORY_RULES` description to show actual priority order (`terminal_io` before `database_access`) and Ollama category override. Updated `03_Dependencies.yaml` artifact structure to include `cics_calls`, `using` params, `indirect_variable` source field, and note about `_ATOMIC_TYPES` guard. Updated `00_Executive_Summary.md` description to mention Validation Warnings section. Updated Step 7c table rows for all four KB files.
**Why:** CLAUDE.md must reflect the pipeline improvements made in this session.

---

## 2026-04-05 — Pipeline accuracy improvements: comment filter, CICS category, indirect targets, PERFORM bounds, dangling refs, CALL USING

**File(s):** `comment_extractor.py`, `comment_enricher.py`, `knowledge_base_builder.py`, `improvement_report.md`
**What changed:** Six generalizable improvements based on per-category audit of PDW0WS0.CBL and PDCBVC.CBL: (1) `_is_code_comment()` filter in comment_extractor strips commented-out COBOL code from `comments.json`; (2) `CATEGORY_RULES` reordered so `terminal_io` precedes `database_access` + added `link`/`xctl`/`routine` keywords + Ollama backend now applies keyword override post-LLM; (3) indirect CICS LINK/XCTL target resolution via `variable_values.json` + `_ATOMIC_TYPES` guard to prevent container-node over-extraction; (4) PERFORM VARYING bounds rendered in `01_Logic_Narrative.md`; (5) dangling paragraph reference validator writes Validation Warnings to `00_Executive_Summary.md`; (6) CALL USING parameters documented in `03_Dependencies.yaml`. Generated `improvement_report.md` with before/after metrics.
**Why:** Per-category accuracy audit found systematic gaps affecting the 1000+ program corpus: comment pollution blocked enrichment, CICS LINK paragraphs mis-categorized, indirect call targets missing, loop bounds absent, undefined paragraph refs undetected, CALL data contracts undocumented.

---

## 2026-04-05 — Update CLAUDE.md: step 7 renaming, Opus-MT, bilingual narrative, schema 1.2

**File(s):** `CLAUDE.md`
**What changed:** Updated all Step 7 documentation to reflect the new four-step split (7a extract, 7b enrich, 7c KB build, 7d structural). Updated Step 7b description to document Opus-MT as the default backend with COBOL term preservation and `CATEGORY_RULES`. Updated Step 7c to document bilingual blockquotes in `01_Logic_Narrative.md`. Added `section_summary` and `workflow` chunk types to the chunks reference, schema version changelog (1.1→1.2), and chunk type reference table. Updated `comments_enriched.json`, `logs/`, `cobol_structure.json` artifact descriptions. Updated design decisions and limitations sections to remove Ollama dependency claim for Step 7b.
**Why:** Documentation must reflect the new step ordering, Opus-MT default, bilingual narratives, and new chunk types introduced in this session.

---

## 2026-04-05 — Add workflow chunks to chunk_pipeline.py

**File(s):** `chunk_pipeline.py`
**What changed:** Added `generate_workflow_chunks()` that creates one `workflow` chunk per paragraph that PERFORMs 2+ other paragraphs and has 3+ local CFG nodes. Each chunk shows the orchestrating paragraph's English comment and a list of its callees with their translations. Wired into `run_pipeline()` after `apply_size_guard`. Bug fix: workflow generator was reading `calls_names` (set by Phase 2 enrichment) before it existed; changed to read the `calls` field (set by `generate_paragraph_logic`) and normalize with `_normalize_call_target`.
**Why:** Provides a "business process flow" retrieval unit between per-paragraph and program-summary chunks, requested in the chunking improvement plan.

---

## 2026-04-05 — Add section_summary chunks and fix _build_paragraph_section_map

**File(s):** `chunk_pipeline.py`
**What changed:** Fixed `_build_paragraph_section_map()` which was returning empty strings for all paragraphs due to a broken upward traversal. The real CFG path is `SECTION →STARTS_WITH→ SECTION_HEADER →FOLLOWED_BY→ PARAGRAPHS →(chain of FOLLOWED_BY)→ PARAGRAPH`; the fix uses a BFS upward walk over both reverse STARTS_WITH and reverse FOLLOWED_BY edges. Added `generate_section_summaries()` that creates one `section_summary` chunk per COBOL SECTION, aggregating paragraph names, English comment translations, and internal/external call relationships. Bumped `CHUNK_SCHEMA_VERSION` to `"1.2"`.
**Why:** Section-level grouping provides mid-level retrieval granularity between paragraph_logic and program_summary chunks; the section map fix also corrects the `section` metadata field on all paragraph_logic chunks.

---

## 2026-04-05 — Inject translated comments into logic narrative (knowledge_base_builder.py)

**File(s):** `knowledge_base_builder.py`
**What changed:** Added `_load_enriched_comments()` and `_format_comment_block()` methods. The logic narrative now renders bilingual blockquotes when `comments_enriched.json` is available: bold English translation on the first line, italic original Italian on the second. Falls back to raw Italian when enrichment was skipped or translation failed. Skips bilingual display when EN == IT (code-heavy comments that translate unchanged).
**Why:** The logic narrative was showing raw Italian comments while RAG chunks already used English translations — an inconsistency that made the human-readable document less useful.

---

## 2026-04-05 — Reorder analyze.py pipeline: extract comments before KB build

**File(s):** `analyze.py`
**What changed:** Split `step7_knowledge_base` into `step7a_extract_comments` (comment extraction only) and `step7c_knowledge_base` (KB build only). Renamed `step7b_comment_enrichment` to remain step7b and `step7c_structure_analysis` to `step7d_structure_analysis`. New execution order: `7a → 7b → 7c → 7d`. Updated `_total_steps` from 11 to 12.
**Why:** The KB builder now reads `comments_enriched.json` for bilingual narratives, which requires enrichment to have already run. The previous ordering (KB → enrich) made this impossible.

---

## 2026-04-05 — Add Helsinki-NLP/Opus-MT translation backend to comment_enricher.py

**File(s):** `comment_enricher.py`, `smojol_python/requirements.txt`
**What changed:** Added Opus-MT (`Helsinki-NLP/opus-mt-it-en`) as the new default translation backend. Key additions: `_ensure_opus_loaded()` (lazy model load with clear error on missing deps), `_protect_cobol_terms()` / `_restore_cobol_terms()` (Unicode marker-based COBOL identifier preservation during translation), `_translate_opus_mt()` (batched MarianMT translation), `_categorize_english()` (keyword-heuristic categorization using configurable `CATEGORY_RULES` dict), `enrich_comments_opus()` (full pipeline). Added `--backend` CLI flag (opus-mt/ollama, default: opus-mt). Updated `analyze.py` step7b to use opus-mt and removed the Ollama reachability gate. Added `transformers` and `sentencepiece` to requirements.txt.
**Why:** Ollama-based translation was slow, non-deterministic, and required a running server. Opus-MT is ~80 MB, runs locally in Python, is deterministic, and eliminates the external dependency.

---

## 2026-04-02 — Fix knowledge_base_builder: 7 bugs found during PDCBVC.CBL evaluation

**File(s):** `knowledge_base_builder.py`, `smojol_python/src/analysis/variable_static_values.py`
**What changed:** Fixed 7 bugs identified by evaluating generated KB documents against the PDCBVC.CBL source: (1) PIC clause extraction used wrong dict key (`rawText` vs `raw`), causing all 1346 variables to show `-`; (2) statement duplication in 01_Logic_Narrative.md — SENTENCE wrapper nodes and their children both rendered, doubling every bullet; (3) `_DIALECT_` garbage lines from DIALECT_CONTAINER wrapper nodes now filtered; (4) CICS LINK/XCTL program targets (PD1VOCI, PD1FS00, PD0UTI01, PDPRED) now extracted into `cics_calls:` in 03_Dependencies.yaml; (5) VALUE clause initializations in DATA DIVISION now tracked by `variable_static_values.py`, resolving the `PXRSEMAF` dynamic CALL from UNKNOWN to the correct target; (6) DATA DIVISION SQL markers (BEGIN/END DECLARE SECTION, INCLUDE, WHENEVER) filtered from procedure paragraph narrative; (7) Executive summary now renames DIALECT/DIALECT_CONTAINER nodes to human-readable labels and warns when GO TO count exceeds 10.
**Why:** PDCBVC.CBL evaluation revealed 02_Data_Dictionary.md had zero PIC clauses, 01_Logic_Narrative.md had every statement doubled with garbage lines, and 03_Dependencies.yaml was missing all CICS inter-program call targets.

---

## 2026-04-02 — Add progress bars to analyze.py and batch_runner.py

**File(s):** `analyze.py`, `batch_runner.py`
**What changed:** Added a Unicode block-character progress bar to `analyze.py` (printed before each pipeline step via `_print_progress`, showing step N/11 and steps remaining) and to `batch_runner.py` (printed after each file completes in both pass 1 and the retry pass, showing files N/total and remaining count). No external dependencies — pure stdlib.
**Why:** User requested visual progress indication so it is easy to see how far along the pipeline and batch run are.

---

## 2026-03-31 — Rerun RAG readiness evaluation

**File(s):** `rag_evaluation_report.md`
**What changed:** Re-evaluated the RAG pipeline against the current corpus (29 COBOL + 3 JCL, 426 chunks). All 6 bugs from the 2026-03-26 report remain unresolved. New findings: 50% of chunks are under 20 tokens (very thin for embedding), copybook manifest confirmed broken at source (null values), BROWSE-FASE1 missing called_by entries. validate_chunks.py passes all 426 structural checks. Overall score: 57/100 (was 58/100).
**Why:** User requested a fresh evaluation to verify whether issues had been fixed since the previous report.

---

## 2026-03-31 — CLAUDE.md update for post-2026-03-26 changes

**File(s):** `CLAUDE.md`
**What changed:** Updated CLAUDE.md to reflect changes made on 2026-03-27 and 2026-03-30: (1) Step 0.5 now documents `_pre_stub_from_source()` source-level pre-stubbing phase and expanded Italian prose stopword filter; (2) Step 1 documents batch-mode JVM merging optimization (`--skip-transpiler`); (3) Step 3 trigger updated to mention `--no-mermaid` skip; (4) Cleanup section documents SIGTERM handler for graceful batch timeout; (5) Batch Analysis section rewritten with full argparse CLI (`--workers`, `--timeout`, `--dry-run`, `--java-heap`, `--all`), process management details, and progress output format; (6) Section 3A.1 adds Java defensive fixes: comma-as-decimal handling, null/empty expression guards, index bounds safety, extended figurative constants (ALLSPACES/NULLS), user-defined class condition handling; (7) analyze.py CLI examples include `--skip-transpiler --no-mermaid`; (8) batch_runner.py repo structure entry updated.
**Why:** CLAUDE.md was last updated 2026-03-26. Five days of changes (batch optimization, Java robustness fixes) were not reflected.

---

## 2026-03-30 — Major update to Part 2 of thesis report (main.tex)

**File(s):** `main.tex`
**What changed:** Updated Part 2 (cobol-rekt Deep Technical Pipeline) to reflect the full scope of work done since the initial draft. Added 5 new sections: Pipeline Robustness and Error Recovery (lenient parsing, iterative copybook stubbing, per-variable resilience, task continue-on-failure, pre-flight checks), RAG Chunk Generation (5 chunk types, metadata design, confidence scoring, validation gate, JCL chunks), JCL Analysis and Cross-Program Integration (JCL parser, cross-referencing, call graph, corpus index), Batch Analysis and Enrichment (batch runner, comment enrichment, structural facts extraction). Updated existing sections: Knowledge Base generation (SQL JOIN/subquery support via sqlparse, dynamic CALL resolution, CICS dedup, 88-level/REDEFINES tables, paragraph idiom detection). Rewrote Conclusions to cover RAG evaluation results (58/100 readiness score), design tradeoffs, and remaining limitations. Expanded pipeline diagram to include RAG chunk layer and cross-program tools. Expanded artifact connectivity table from 8 to 14 entries.
**Why:** The report only covered parsing through knowledge base generation, missing the entire RAG preparation pipeline, JCL analysis, cross-program tools, and robustness engineering that constitute the majority of the implementation work.

---

## 2026-03-30 — Fix Java analysis bugs: comma decimal, null expressions, index bounds, unsupported COBOL extensions

**File(s):**
- `smojol-core/src/main/java/org/smojol/common/vm/expression/LiteralVisitor.java`
- `smojol-core/src/main/java/org/smojol/common/vm/structure/ConversionStrategy.java`
- `smojol-toolkit/src/main/java/org/smojol/toolkit/ast/MoveFlowNode.java`
- `smojol-toolkit/src/main/java/org/smojol/toolkit/ast/AddFlowNode.java`
- `smojol-toolkit/src/main/java/org/smojol/toolkit/ast/ComputeFlowNode.java`
- `smojol-toolkit/src/main/java/org/smojol/toolkit/ast/DivideFlowNode.java`
- `smojol-toolkit/src/main/java/org/smojol/toolkit/ast/MultiplyFlowNode.java`
- `smojol-toolkit/src/main/java/org/smojol/toolkit/analysis/graph/DataDependencyPairComputer.java`
- `smojol-toolkit/src/main/java/org/smojol/toolkit/transpiler/SetTranspilerNodeBuilder.java`
- `smojol-toolkit/src/main/java/org/smojol/toolkit/interpreter/interpreter/MoveOperation.java`
- `smojol-core/src/main/java/org/smojol/common/vm/structure/IndexProvider.java`
- `smojol-core/src/main/java/org/smojol/common/vm/memory/MemoryRegion.java`
- `smojol-core/src/main/java/org/smojol/common/vm/expression/FigurativeConstantMap.java`
- `smojol-core/src/main/java/org/smojol/common/vm/expression/ClassConditionBuilder.java`

**What changed:** Four groups of defensive fixes to handle Italian COBOL programs that were crashing batch analysis: (A) comma-as-decimal-separator in numeric literals (`.replace(',', '.')` before `Double.valueOf`); (B) null/empty expression fields in FlowNode subclasses initialized to `ImmutableList.of()` and guarded in callers; (C) `IndexProvider.next()` bounds check and `MemoryRegion.range()` guard for inverted indices; (D) `ALLSPACES`/`NULLS` added to `FigurativeConstantMap`, user-defined class conditions (`NOTALFANUM`) handled in `ClassConditionBuilder` as approximate alphabetic test.
**Why:** Batch analysis was failing on 23 COBOL programs due to these Java-side crashes. All fixes are purely defensive — the happy path is unchanged. Pre-existing `DataLayoutBuilderTest` failures (missing grammar types) are unrelated.

---

## 2026-03-27 — Batch Analysis: Merge JVM calls + raise timeout

**File(s):** `analyze.py`, `batch_runner.py`
**What changed:** (1) In batch mode (`--skip-transpiler`), step1 now runs step2's commands in the same JVM invocation so `BUILD_BASE_ANALYSIS` (parse + CFG) runs once instead of twice; step2 returns immediately. (2) `_pre_stub_from_source` sets `_all_copies_resolved=True` so `pre_validate` skips its JVM call. (3) Added `--no-mermaid` to skip `step3_mermaid`. Result: 1 JVM call in batch mode instead of 4. (4) Default timeout raised 300s → 600s. (5) Timeout path now reads manifest from disk for `CPY:found/needed` display.
**Why:** Files with 4–8 copybooks kept timing out at 300s because BUILD_BASE_ANALYSIS ran twice (once in step1, once in step2). Merging the calls plus raising the timeout ensures large enterprise programs complete reliably.

---

## 2026-03-27 — Batch Analysis: Fix Systemic 300s Timeout

**File(s):** `analyze.py`, `batch_runner.py`
**What changed:**
- **analyze.py**: Added `_pre_stub_from_source()` — scans COPY statements from source (fixed-format cols 8–72, handles `IN/OF` library syntax, skips col-7 comment lines) and stubs all missing copybooks before the first JVM invocation, collapsing up to 5 pre_validate iterations into 1.
- **analyze.py**: Added `--skip-transpiler` flag — omits `BUILD_TRANSPILER_FLOWGRAPH` from step2 command list for faster batch runs; knowledge base and all downstream Python steps are unaffected.
- **analyze.py**: Added SIGTERM handler in `run()` — writes `pipeline_report.json` explicitly before `cleanup()` so per-step timing is preserved even when the batch runner kills the process on timeout.
- **analyze.py**: Expanded copybook stub stopword filter in `pre_validate_and_stub` to exclude Italian prose words (CON, DI, E, COMPENSI, etc.) that were incorrectly stubbed as copybook names.
- **batch_runner.py**: Replaced hardcoded constants with `argparse` — `--workers` (default 2, down from 4), `--timeout` (default 300), `--dry-run` (scan COPY refs and file sizes without running analysis).
- **batch_runner.py**: Changed timeout handling from `subprocess.run(timeout=)` to `Popen + communicate(timeout=) + SIGTERM → 5s → SIGKILL`, giving analyze.py time to write `pipeline_report.json`.
- **batch_runner.py**: Added coverage % to batch output — reads `pipeline_report.json` (step completion %) and `parse_diagnostics.json` (parse coverage %) after each file; shows `steps:X% | parse:Y%` in the progress line.
- **batch_runner.py**: Added `CPY: found/needed` column — cross-references COPY statement scan against the manifest to show how many of the program's actual copybook dependencies were resolved vs total referenced (e.g. `CPY:3/5`). Also added to `batch_summary_report.json` per-file detail.
**Why:** Almost all COBOL files in the batch corpus were timing out at exactly 300s. Root causes: (1) pre_validate running up to 5 JVM round-trips without copybooks (~100–200s alone under 4-worker contention); (2) BUILD_TRANSPILER_FLOWGRAPH non-linear on complex enterprise COBOL; (3) 4 concurrent JVMs exhausting memory/CPU.

---

## 2026-03-26 — RAG Document Evaluation: Accuracy & Coverage Audit

**File(s):** `rag_evaluation_report.md`
**What changed:** Comprehensive ground-truth evaluation of RAG chunks across 3 COBOL programs (hello.cbl, cics.cbl, PDCBVC.CBL) and 1 JCL job (PDADDRE1.jcl). Identified 10 ranked issues including critical bugs (copybook manifest not in health chunks, parse_quality always "unknown"), high-priority problems (phantom TypedRecord inflation, structural patterns not propagated, EXEC SQL BEGIN false positives, XCTL targets missing from metadata), and medium-priority gaps (garbled dialect text, no logic chunks for non-paragraph programs). Overall RAG readiness scored 58/100.
**Why:** Ground-truth evaluation needed to quantify chunk accuracy and identify gaps before relying on chunks for RAG retrieval in the thesis.

---

## 2026-03-26 — Phase 4: Atomic JSON writes, JVM memory flags, cleanup

**File(s):** `chunk_pipeline.py`, `analyze.py`, `patch_chunk_pipeline.py` (deleted)

**What changed:**
- **Atomic writes:** Added `_atomic_write_json()` utility in `chunk_pipeline.py` — writes to `.tmp` then `os.replace()` to the final path. Applied to `write_chunk()` and manifest generation. Prevents half-written JSON files when the process is killed mid-write.
- **JVM memory flags:** Added `-Xmx{heap_size} -XX:+HeapDumpOnOutOfMemoryError -XX:HeapDumpPath="{report_dir}"` to `_build_smojol_cmd()` in `analyze.py`. Added `--java-heap=` CLI option (default "2g"). Large COBOL programs with deeply nested data structures can exhaust the default JVM heap.
- **Cleanup:** Deleted `patch_chunk_pipeline.py` — leftover hotfix file that was superseded by the chunk_pipeline.py improvements.

**Why:** Atomic writes prevent data corruption in RAG chunk files — a corrupted chunk manifest makes all chunks for that program unretrievable. JVM memory flags prevent silent OOM kills that appear as "Java process exited with code 137" with no other diagnostics. The heap dump enables post-mortem analysis of memory pressure.

**Business logic:** RAG retrieval systems index chunk files at ingest time. A half-written JSON file causes the indexer to skip or error on that program entirely, losing all analysis for it. Atomic writes ensure that every chunk file is either fully written or not present — never partially corrupted. The JVM heap flag is especially important for programs with large OCCURS tables (e.g., 10,000-element arrays) where data structure expansion can consume gigabytes of memory.

---

## 2026-03-26 — Final Phase 3 fixes: remaining bare except clauses

**File(s):** `analyze.py`, `validate_chunks.py`

**What changed:**
- `analyze.py` line 225: Changed `except Exception: pass` to `except OSError as e:` with warning message during copybook stub writing.
- `analyze.py` line 164: Changed `except Exception:` to `except (OSError, UnicodeDecodeError):` in dialect detection file read.
- `validate_chunks.py` line 34: Changed `except Exception:` to `except ImportError:` for tiktoken optional dependency fallback.

**Why:** Final cleanup of bare exception handlers. The copybook stub write could fail due to filesystem permissions or disk full — logging the error helps diagnose sandbox issues. The dialect detection read needs to handle encoding errors on binary files. The tiktoken fallback should only catch ImportError, not mask initialization bugs.

**Business logic:** When copybook stubbing silently fails, the parse attempt will fail too, but the error message points at the parse — not the underlying filesystem issue. Surfacing the stub write error lets operators diagnose the actual root cause (e.g., temp directory permissions, disk full) rather than chasing phantom parse errors.

---

## 2026-03-26 — Narrow bare except clauses across 5 utility scripts

**File(s):** `cobol_structure_analyzer.py`, `comment_enricher.py`, `jcl_cobol_report.py`, `build_corpus_index.py`, `validate_chunks.py`
**What changed:** Replaced all bare `except Exception` (and `except Exception as e` with no use) handlers with specific exception types: `json.JSONDecodeError`/`OSError` for JSON/file loading, `yaml.YAMLError`/`OSError` for YAML loading, `requests.RequestException`/`ConnectionError`/`TimeoutError` for HTTP calls, `KeyError`/`TypeError`/`ValueError` for data traversal. Added `print(..., file=sys.stderr)` warnings so failures are visible in logs instead of silently swallowed.
**Why:** Bare except clauses hide bugs by catching unexpected errors (e.g. TypeError, KeyboardInterrupt). Specific types ensure only anticipated failures are handled, and stderr warnings aid debugging.

---

## 2026-03-26 — Replace bare except Exception with specific exception types in knowledge_base_builder.py

**File(s):** `knowledge_base_builder.py`
**What changed:** Replaced 6 bare `except Exception` patterns with specific exception types: `(json.JSONDecodeError, OSError)` for file/JSON loading, `(json.JSONDecodeError, KeyError, TypeError)` for cobol_structure.json content access, `(ValueError, TypeError, AttributeError)` for sqlparse processing. Changed verbose-only warnings in `_load_cfg`, `_load_data_structures`, and `_load_comments` to always print to stderr. Added `import sys`.
**Why:** Improve error handling specificity — bare `except Exception` can mask unexpected bugs by silently swallowing unrelated errors.

---

## 2026-03-26 — Narrow bare except clauses in analyze.py

**File(s):** `analyze.py`
**What changed:** Replaced two bare `except Exception` handlers with specific exception types: `except OSError` in `_write_copybook_manifest` (line ~383) and `except (json.JSONDecodeError, OSError)` with a warning message in `_log_parse_diagnostics` (line ~513).
**Why:** Overly broad exception handling can mask unexpected errors. Narrowing to specific types improves debuggability.

---

## 2026-03-26 — Replace bare except Exception with specific exception types in chunk_pipeline.py

**File(s):** `chunk_pipeline.py`
**What changed:** Replaced four bare `except Exception` handlers with specific types: `ImportError` for tiktoken import, `(json.JSONDecodeError, OSError)` for JSON loads, `(yaml.YAMLError, OSError)` for YAML loads, and added warning messages to stderr for the load/parse failures.
**Why:** Overly broad exception handlers mask real bugs; narrowing to expected exception types improves debuggability.

---

## 2026-03-26 — P4+P5: Stderr capture + Java signal integration

**File(s):** `analyze.py`, `chunk_pipeline.py`, `knowledge_base_builder.py`

**What changed:**
- **P4:** Extended `run_command()` with `capture_to` parameter. When `check=False` and a command fails, stderr/stdout are captured to a log file under `<report>/logs/`. Applied to Step 2 (`step2_stderr.log`) and Step 7c (`step7c_stderr.log`). Previously, stderr from failed `check=False` commands was silently discarded — the only evidence of failure was missing output files.
- **P5 (chunk_pipeline.py):** Updated `_compute_parse_quality()` to check `data_structures_degraded` flag and `skipped_variables` array from Java's new `parse_diagnostics.json` fields (added in J1). A program with degraded data structures now correctly gets quality="degraded" even if parse error count is low.
- **P5 (knowledge_base_builder.py):** Added `_load_parse_diagnostics()` method. When generating `02_Data_Dictionary.md`, checks for `data_structures_degraded` and `skipped_variables` — inserts warning banners at the top of the document so readers know the dictionary may be incomplete.

**Why:** P4 addresses the "silent failure" pattern where Step 2 and Step 7c run with `check=False` but discard all error output. Without captured stderr, debugging why the unified model or structural facts are missing requires re-running the pipeline manually. P5 closes the loop from the J1 Java change — the new diagnostic signals are now consumed by downstream Python tools.

**Business logic:** The data dictionary is the primary reference document for data migration teams. A dictionary that appears complete but is actually missing variables (because the data structure builder degraded) is worse than one with an explicit warning. The skipped variables note tells analysts exactly which variables to look up manually in the source. For RAG chunks, the parse quality label determines how much weight retrieval systems should give to a program's chunks — a "degraded" chunk should rank lower than a "full" one.

---

## 2026-03-26 — P3: Pre-flight validation

**File(s):** `analyze.py`

**What changed:**
- Added `pre_flight_check()` method called at the very start of `run()`, before sandbox setup.
- Validates 5 prerequisites: (1) `smojol-cli.jar` exists, (2) `dialect-idms.jar` exists, (3) target file exists and is non-empty, (4) file extension is `.cbl`/`.cob` (warn-only), (5) output directory is writable.
- Failures on items 1-3 and 5 call `sys.exit(1)` with a clear error message telling the user exactly what to do (e.g., "Run: mvn clean verify").
- All check results are recorded in `pipeline_report.json` under `pre_flight` field.

**Why:** Previously, if `smojol-cli.jar` didn't exist (common after a fresh clone without running Maven), the pipeline would fail deep in Step 1 with a cryptic Java error. If the target file was empty (e.g., wrong path, encoding issue), the ANTLR parser would produce an unhelpful error. Pre-flight checks fail fast with actionable messages.

**Business logic:** In enterprise environments, COBOL analysis is often triggered by CI/CD or automated scripts. A missing JAR file or wrong file path should produce a clear, immediate error — not a stack trace 30 seconds into the pipeline. The pre-flight check also serves as documentation of the pipeline's runtime dependencies.

---

## 2026-03-26 — P1+P2: Pipeline execution report + sandbox try-finally

**File(s):** `analyze.py`

**What changed:**
- Added `PipelineReport` class that tracks each step's name, status (success/failed/warning), duration in seconds, and diagnostics messages.
- Integrated `PipelineReport` into `AnalysisPipeline.__init__()` and all steps via `_run_step()` wrapper that automatically calls `start_step()`/`end_step()` with exception handling.
- Wrapped `run()` body in try-finally so `cleanup()` always executes — even if a step calls `sys.exit(1)` or throws an unhandled exception. Previously, if Step 1 failed via `sys.exit(1)`, the sandbox temp directory was never cleaned up.
- Added `self._cleaned_up` guard flag to prevent double-cleanup.
- `pipeline_report.json` is written as the first action in `cleanup()`, before sandbox removal, so it's always available even if the sandbox cleanup itself fails.
- New output artifact: `out/report/<TARGET>.report/pipeline_report.json` with fields: program, timestamp, overall_status, pre_flight, steps[].

**Why:** When the pipeline failed mid-run, there was no record of what happened — which steps completed, which failed, how long each took. The only output was a console error message that was lost if running in batch mode. With the pipeline report, every run produces a machine-readable execution trace. The try-finally wrapper prevents sandbox temp directory leaks (each leaked sandbox wastes ~50MB of disk space on enterprise COBOL programs with many copybooks).

**Business logic:** In enterprise environments, COBOL analysis pipelines run in batch over hundreds of programs. When 5% of programs fail, operations teams need a structured way to triage: which step failed? Was it a parse failure (Step 1) or a downstream analysis issue (Step 2+)? How long did successful steps take (performance regression detection)? The `pipeline_report.json` enables automated dashboards and alerting, replacing manual log-grepping.

---

## 2026-03-26 — J7: blockContaining() crash fix in transpiler task

**File(s):** `mojo-common/.../task/StructuredProgramTheoremFormTranspilerTask.java`

**What changed:**
- Replaced `.findFirst().get()` with `.findFirst().orElse(null)` in `blockContaining()` and the jump edge lookup. Previously, if a transpiler node couldn't be matched to any basic block (orphaned GOTO target, unreachable code eliminated during optimization), the `.get()` threw `NoSuchElementException` crashing the entire `BUILD_TRANSPILER_FLOWGRAPH` task.
- Added null checks at call sites: if/then/else blocks use "ORPHANED" as the block ID; jump edges without targets produce a descriptive fallback string.

**Why:** `BUILD_TRANSPILER_FLOWGRAPH` is part of Step 2 in `analyze.py`, which bundles 5 tasks with `check=False`. When this task crashed, all subsequent tasks in the bundle (`ATTACH_COMMENTS`, `BUILD_PROGRAM_DEPENDENCIES`, `EXPORT_UNIFIED_TO_JSON`, `FLOW_TO_GRAPHML`) were also lost due to the stream-based execution (now fixed by J3). Even with J3's continue-on-failure, this crash still meant the transpiler output was entirely lost. Programs with complex GOTO structures (irreducible control flow, dead code after GO TO) were the most common trigger.

**Business logic:** The structured program theorem transformation converts arbitrary GOTO-based control flow into structured if/while/sequence constructs. This is valuable for: (1) generating readable pseudo-code from COBOL, (2) identifying natural loop boundaries for modernization, (3) detecting dead code. Enterprise COBOL programs with GO TO statements are extremely common (estimated 40-60% of production COBOL). A crash on these programs meant the most complex and hardest-to-understand programs — exactly the ones that need transpiler analysis most — got no output.

**Regression test:** 3 GOTO-heavy programs (simple-goto, improper-goto, simple-nonreducible-perform-with-goto) — all pass.

---

## 2026-03-26 — J6: Level 66 RENAME — preserve variable name

**File(s):** `smojol-core/.../structure/CobolDataStructureBuilder.java`

**What changed:**
- Replaced the silent skip of Level 66 RENAME entries with a `DetachedDataStructure` node added to the root. The variable name is extracted and preserved in the data structure tree, so it appears in data dictionaries and JSON exports.
- Uses the existing `DetachedDataStructure` class (already in the codebase at `smojol-core/.../vm/reference/DetachedDataStructure.java`) rather than creating a new class.

**Why:** Level 66 RENAME in COBOL creates an alias that spans a range of previously declared variables — it's essentially a "view" over a contiguous memory region. The old code silently discarded these entries. While full RENAME semantics (range tracking between THROUGH variables) are not implemented, preserving the variable name ensures: (1) the name appears in the data dictionary, (2) COBOL source references to the RENAME alias can be correlated, and (3) the existence of RENAME patterns is visible in the analysis output.

**Business logic:** RENAME is used in enterprise COBOL to create alternative groupings of record fields — for example, renaming a set of date fields (YEAR, MONTH, DAY) as a single DATE-FULL field for bulk operations. During modernization, knowing these aliases exist is critical for understanding which code paths access which data representations. A missing RENAME alias in the data dictionary means analysts won't know that two seemingly different variable references point to the same memory.

**Regression test:** No programs in the test corpus use Level 66. Verified simple-redef.cbl (which has REDEFINES but no RENAMES) produces byte-identical output.

---

## 2026-03-26 — J5: Handle OCCURS DEPENDING ON and UNBOUNDED

**File(s):** `smojol-toolkit/.../interpreter/structure/DefaultFormat1DataStructureBuilder.java`

**What changed:**
- Added null check for `integerLiteral()` before calling `Integer.parseInt()`. Previously, `OCCURS UNBOUNDED` (where the grammar rule matches the `UNBOUNDED` token instead of `integerLiteral`) caused an NPE because `integerLiteral()` returns null.
- For `OCCURS UNBOUNDED`: uses count=1 as a minimum estimate and logs a warning.
- For `OCCURS x TO y DEPENDING ON z`: checks `dataOccursTo()` and uses the maximum value (y) instead of the minimum (x) for static memory allocation. This is the correct behavior because the data structure needs to allocate enough memory for the maximum possible array size.

**Why:** COBOL `OCCURS DEPENDING ON` declares variable-length arrays where the actual count is determined at runtime by another variable. `OCCURS UNBOUNDED` declares arrays with no upper limit. Both are common in enterprise COBOL (e.g., variable-length records, dynamic tables). The old code crashed with NPE on `UNBOUNDED` and used the minimum count for `DEPENDING ON`, under-allocating memory and potentially truncating array data in the data dictionary.

**Business logic:** Variable-length arrays are used extensively in COBOL for: (1) transaction records with variable numbers of line items, (2) communication areas with dynamically-sized buffers, (3) report lines with varying detail counts. For data migration and ETL, knowing the maximum array size is essential for target schema design. Using the minimum instead of the maximum means the target system's column definitions would be too small, causing data truncation during migration.

**Regression test:** 5 programs with OCCURS clauses (occurs-test, table-indexing, table-redef, PAYROL00, interpreter-test) — all structurally identical to baseline.

---

## 2026-03-26 — J4: Fix null location coverage inflation in parse diagnostics

**File(s):** `smojol-toolkit/.../task/analysis/CodeTaskRunner.java`

**What changed:**
- Added null-safety checks for `range`, `range.getStart()`, and `range.getEnd()` in the error location extraction loop. Previously, errors with null ranges could cause NPEs, and errors with null `getEnd()` would silently skip the entire error line range.
- Added `nullLocationErrors` counter tracking errors that have no location information at all.
- Added heuristic coverage penalty: each null-location error is assumed to affect 3 source lines (conservative estimate). This prevents coverage inflation where a program with 10 null-location errors would previously report 100% coverage.
- Added `null_location_errors` field to `parse_diagnostics.json` output.

**Why:** Parse errors from ANTLR error recovery or copybook-related issues often have null location information (the error is real but the parser can't determine which source line it maps to). The old code simply ignored these errors in the coverage calculation — a program could have 50 parse errors but report 100% coverage if none had location data. This gave analysts false confidence in the parse quality.

**Business logic:** Coverage percentage is the primary quality signal that downstream consumers (RAG chunk pipeline, knowledge base builder, JCL-COBOL report) use to assess whether an analysis output is trustworthy. An inflated coverage percentage means analysts accept degraded outputs as high-quality, leading to incorrect data dictionaries, wrong dependency graphs, and unreliable documentation being fed to LLMs or embedded in retrieval systems. Accurate coverage enables informed decisions about which programs need manual review.

**Regression test:** Only affects programs analyzed in lenient mode. No data structure changes. Build verified.

---

## 2026-03-26 — J3: Task execution continue-on-failure

**File(s):** `smojol-toolkit/.../task/SmojolTasks.java`

**What changed:**
- Replaced stream-based task execution (`tasks().map(AnalysisTask::run).toList()`) with an explicit for-loop with per-task try-catch. Previously, the Java Stream API's `.map().toList()` would short-circuit on the first exception — if task #3 of 8 threw, tasks #4–#8 were never attempted, and their outputs were lost entirely.
- `BUILD_BASE_ANALYSIS` (always task #0) is treated specially: if it fails, remaining tasks are aborted since they all depend on `baseModel` (navigator, data structures, flow root). But if any subsequent task fails, the error is captured as `AnalysisTaskResult.ERROR` and the loop continues with the next task.

**Why:** The Java CLI runs multiple analysis tasks per invocation (e.g., `WRITE_RAW_AST WRITE_FLOW_AST WRITE_CFG WRITE_DATA_STRUCTURES`). When `BUILD_TRANSPILER_FLOWGRAPH` crashes (common on programs with complex GOTO structures), the stream-based execution lost ALL subsequent task outputs — even tasks like `WRITE_DATA_STRUCTURES` that had no dependency on the transpiler. This was especially wasteful because Step 2 of `analyze.py` bundles 5 tasks together with `check=False`, meaning it expected partial results.

**Business logic:** In enterprise COBOL modernization, different analysis consumers need different artifacts. A data migration team needs the data dictionary (`WRITE_DATA_STRUCTURES`) but doesn't care about the transpiler flowgraph. A control flow analyst needs the CFG (`WRITE_CFG`) but not the Mermaid export. With continue-on-failure, each consumer gets whatever artifacts can be produced, rather than losing everything because one unrelated task crashed. The pipeline report (upcoming P1) will document which tasks succeeded and which failed.

**Regression test:** 5 programs including GOTO-heavy and DB2 programs — all structurally identical to baseline.

---

## 2026-03-26 — J2: PIC clause error tracking

**File(s):** `smojol-core/.../vm/memory/DataLayoutBuilder.java`

**What changed:**
- Added `PicParseResult` record containing the parse tree and a list of error messages.
- Added `parseSpecWithDiagnostics()` method that re-adds custom `BaseErrorListener` instances to both the lexer and parser. Previously, `parseSpec()` called `removeErrorListeners()` on both ANTLR components, making invalid PIC clauses silently produce incomplete/wrong parse trees — leading to incorrect memory sizes, wrong byte offsets, and corrupted data dictionaries with no indication of the problem.
- Updated `size()` to use `parseSpecWithDiagnostics()` instead of `parseSpec()`. When PIC parse errors are detected, they are logged as warnings. The parse tree is still returned (ANTLR error recovery provides a best-effort tree), so the variable remains in the data structure but with potentially incorrect sizing — which is better than silent corruption.

**Why:** The PIC clause (`PICTURE IS ...`) defines every variable's type and byte size in COBOL. When a PIC clause has a syntax error (e.g., `PIC X(ABC)`, unusual vendor extensions, or truncated copybook content), the old code silently produced a wrong parse tree. This meant: (1) the variable got a wrong byte size, (2) all subsequent variables' byte offsets were wrong (since COBOL memory layout is sequential), and (3) there was no way to detect this from the output. Now, PIC parse errors are logged and can be correlated with the J1 per-variable skip mechanism.

**Business logic:** In COBOL, every variable's memory position depends on the cumulative byte sizes of all preceding variables. A single wrong PIC clause doesn't just affect one variable — it shifts the calculated memory offset of every variable that follows it in the same record group. For data migration, ETL, and interface analysis, knowing that a PIC clause failed to parse is critical because it means the byte-level layout for that entire record group may be unreliable.

**Regression test:** 8 programs with diverse PIC clauses (REDEFINES, OCCURS, COMP-1, alphanumeric, numeric) — all structurally identical to baseline.

---

## 2026-03-26 — J1: Per-variable resilient data structure building + diagnostics export

**File(s):** `smojol-core/.../structure/SkippedVariable.java` (new), `smojol-core/.../structure/CobolDataStructureBuilder.java`, `smojol-toolkit/.../pipeline/ParsePipeline.java`, `smojol-toolkit/.../task/analysis/CodeTaskRunner.java`

**What changed:**
- Created `SkippedVariable` record to capture variable name, error message, and source section when a variable fails processing.
- Wrapped each variable's processing in `CobolDataStructureBuilder.extractFrom()` with per-variable try-catch. Previously, a single bad variable (e.g., invalid PIC clause, corrupt level number, or broken parent-child chain) threw a RuntimeException that killed the ENTIRE data structure tree — causing a fallback to `NullDataStructure` and losing all 500+ variables in the program. Now, only the offending variable is skipped; all others are preserved.
- Wrapped `expandTables()` and `calculateMemoryRequirements()` in `build()` with individual try-catches. These post-processing steps iterate all variables in the tree — if one OCCURS expansion or memory calculation fails, the rest still complete.
- Added `skippedDataStructures` and `dataStructureDegraded` fields to `ParsePipeline` with getters. The builder reference is stored before calling `DataStructureValidation.run()` so skipped variables can be read after build completes.
- Extended `CodeTaskRunner.writeParseDiagnostics()` to include `skipped_variables` array and `data_structures_degraded` boolean in `parse_diagnostics.json`. Downstream Python consumers (`chunk_pipeline.py`, `knowledge_base_builder.py`) can now detect partial data structure trees.

**Why:** The worst data loss pattern in the pipeline — one bad variable destroying the entire data dictionary. Enterprise COBOL programs with 500+ variables and complex PIC clauses, REDEFINES chains, or OCCURS DEPENDING ON constructs are especially vulnerable. This change preserves the maximum amount of variable information while recording exactly what was lost and why.

**Business logic:** In enterprise COBOL modernization, the data dictionary is the most valuable artifact for understanding what a program does. Variables define the program's interface (LINKAGE), internal state (WORKING-STORAGE), and file formats (FILE SECTION). Losing the entire dictionary because of one incompatible PIC clause means the analysis output is essentially useless for that program. With per-variable resilience, analysts and RAG systems get 499 out of 500 variables even when one is unparseable — and the `parse_diagnostics.json` tells them exactly which variable was lost and why, enabling targeted manual inspection.

**Regression test:** All 29 data structure JSON files are structurally identical to baseline (only UUID differences). Zero regressions across the full corpus.

---

## 2026-03-26 — Comprehensive CLAUDE.md update

**File(s):** `CLAUDE.md`
**What changed:** Major rewrite of CLAUDE.md to reflect all features added since initial authoring. Added: Section 3A (COBOL Analysis Deep Dive — Java 6-stage parse pipeline, 14 commands, error modes, parse diagnostics, 41 Flow AST node types, CFG edge types), Section 3B (JCL Analysis Deep Dive — 3-phase JCL parser, JCL-COBOL cross-referencing, call graph construction, corpus indexing). Updated: pipeline diagram (added steps 7b/7c), Step 0 (copybook_manifest.json), Step 0.5 (max_retries 3→5), Step 1 (lenient auto-retry logic), Step 7 (sqlparse + dynamic CALL resolution). Added 8 new scripts to repo structure, 12 new output artifacts, 5 new design decisions, 7 new known limitations, 5 new glossary terms, standalone script commands, and recommended end-to-end workflow.
**Why:** CLAUDE.md was ~65% accurate — missing JCL pipeline, RAG chunk pipeline, comment enrichment, structural analysis, lenient mode, and all cross-program tools. Needed comprehensive update to serve as accurate developer/agent reference.

---

## 2026-03-23 — Fourth batch (Phase 4): R8.2, R8.4, R7.3, R7.5, R6.1

**File(s):** `jcl_parser.py`, `jcl_cobol_report.py`, `chunk_pipeline.py`, `knowledge_base_builder.py`, `analyze.py`
**What changed:** Implemented all Phase 4 robustness and completeness items:
- **R8.2** (`jcl_parser.py`, `jcl_cobol_report.py`): `DISP=MOD` now classified as `'append'` (distinct from `'write'`). Propagated through all dataset access checks and step chunk text.
- **R8.4** (`jcl_cobol_report.py`, `chunk_pipeline.py`): Added `_interpret_cond()` that inverts JCL COND= skip-if-true logic into human-readable "runs only if …" form. Handles single/multi-condition, EVEN, ONLY modifiers. Applied to step_detail and jcl_condition_flow chunk text.
- **R7.3** (`chunk_pipeline.py`): Added `_compute_confidence_score()` — 5-factor weighted score (parse_quality 0.30, copybook_coverage 0.25, data_dictionary_coverage 0.20, dependency_completeness 0.15, narrative_quality 0.10). Wired into `generate_program_summary()`: result stored in `metadata["confidence"]` and appended as text to the chunk body.
- **R7.5** (`analyze.py`): Increased `pre_validate_and_stub()` default `max_retries` from 3 to 5, allowing deeper transitive copybook chains to resolve.
- **R6.1** (`knowledge_base_builder.py`): Added `_IDIOM_RULES` table (10 rules) and `_detect_paragraph_idiom()`. Called per-paragraph in `_generate_logic_narrative()`; appends `*Idiom: <label>*` before the statement list when a pattern matches.
- **R5.6** and **R6.2** deferred: R5.6 (known-copybook library) replaced by planned `cpy_analyzer` tool. R6.2 (variable name NL) needs smarter corpus-driven approach.
**Why:** Phase 4 requirements from `report_plan.md`.

---

## 2026-03-23 — Third batch (Phase 3): R5.1, R5.2, R5.3, R5.4, R8.1, R2.1, R2.2, R2.3, R2.5, R3.1

**File(s):** `chunk_pipeline.py`, `knowledge_base_builder.py`
**What changed:** Implemented all Phase 3 text quality and extraction improvements:
- **R5.1** (`knowledge_base_builder.py`): Replaced single-regex SQL extraction with sqlparse token walker in `_extract_tables_sqlparse()`; handles JOINs, subqueries, CTEs; falls back to regex `_extract_tables_regex()` if sqlparse unavailable. Added `_is_dynamic_sql()` to flag PREPARE/EXECUTE IMMEDIATE and set `dynamic_sql: true` in `03_Dependencies.yaml`.
- **R5.2** (`knowledge_base_builder.py`): Dynamic CALL target resolution — when `CALL <variable>` found and no literal target extracted, looks up the variable in `variable_values.json`; adds `{target, source: "dynamic", variable}` entries for each known value, or `{target: "UNKNOWN", ...}` if variable has no known values.
- **R5.3** (`chunk_pipeline.py`): Added `_collect_88_conditions()` helper that recursively finds level-88 entries in data structure children and formats them as `"COND-NAME means PARENT = VALUE"` lines appended to variable_group text under a "Condition names (88-level):" header.
- **R5.4** (`chunk_pipeline.py`): Added `_build_redefines_explanation()` helper that checks `rawText` for REDEFINES clause on the level-01 record or its direct children; appends a human-readable explanation sentence to variable_group text.
- **R8.1** (`chunk_pipeline.py`): Added `_build_perform_loop_info()` that scans CFG nodes for PERFORM VARYING patterns using regex `_PERFORM_VARYING_RE`; extracts variable/from/by/until and nested AFTER clauses; returns `{called_paragraph: [loop_info]}`. `enrich_paragraph_chunks()` now stamps `loop_info` metadata and appends a narrative annotation `(loop: VAR from X by Y until Z)` to the chunk text.
- **R2.1** (`chunk_pipeline.py`): Added `enrich_variable_group_usage()` post-processing pass that inverts the `variables_modified`/`variables_read` sets from paragraph chunks to build a paragraph-usage summary; appends "Used in paragraphs: PARA1 (FIELD modified), PARA2 (FIELD read)" to each variable_group chunk text.
- **R2.2** (`chunk_pipeline.py`): Added `_build_program_nl_summary()` that reads `03_Dependencies.yaml` to detect CICS/batch mode and DB2 usage, then prepends a one-sentence natural language description to `program_summary` text: "This is a [complexity]-complexity [CICS online/batch] program [with DB2 access]."
- **R2.3** (`chunk_pipeline.py`): `generate_step_details()` now computes step position (first/intermediate/final/sole) from 1-based index; appends "This is the [position] step in job [JOB_NAME]." to each step_detail text. Adds `step_index` and `total_steps` to metadata.
- **R2.5** (`chunk_pipeline.py`): Added `_load_all_variable_names()` and `_build_variable_usage_from_cfg()` functions that scan paragraph subgraph `originalText` for known variable names using write/read regex patterns (MOVE ... TO, COMPUTE, ADD ... TO, etc.); stamps `variables_modified` and `variables_read` on each paragraph_logic chunk metadata. Note: the unified model's MODIFIES/ACCESSES edges use TypedRecord names rather than variable names and were not usable; this CFG-text heuristic is the fallback.
- **R3.1** (`chunk_pipeline.py`): Added `enrich_related_variable_groups()` post-processing pass that builds a `{variable_name: variable_group_chunk_id}` map from variable_group `field_names` metadata, then links each paragraph's `variables_modified`/`variables_read` to the containing variable group chunks via `related_variable_groups: [chunk_id, ...]`.
**Why:** Phase 3 of report_plan.md — improve semantic richness of chunk text fields and fix data extraction accuracy (SQL multi-table, dynamic CALLs, loop bounds, 88-level conditions, REDEFINES) to make chunks more useful for RAG retrieval and LLM context.

---

## 2026-03-23 — Second batch (Phase 1 gate + Phase 2): R7.7, validate_chunks.py, R7.1, R7.2, R7.4, R2.4, R2.6, R3.2, R3.3

**File(s):** `chunk_pipeline.py`, `validate_chunks.py` (new)
**What changed:** Completed the remaining Phase 1 item and all Phase 2 metadata/cross-reference items:

- **R7.7** — Added `content_hash` (sha256 of chunk text, first 16 hex chars) to every chunk via `write_chunk` and `_write_chunk`. Also fixed all post-generation paths that mutate chunk text (`enrich_paragraph_chunks`, `apply_size_guard` merge/split passes, `_split_if_needed`) to recompute the hash via new `_refresh_hash(data)` helper so the stored hash stays consistent.
- **validate_chunks.py** (new) — Phase 1 gate script. Checks: required fields (`schema_version`, `pipeline_version`, `analysis_timestamp`, `content_hash`), hash determinism, token-limit compliance, dangling cross-references, and corpus-index/chunk consistency. Exit 0 = PASS. Verified: 0 hash mismatches on freshly generated PDCBVC chunks.
- **R7.1** — Added `_CURRENT_PARSE_QUALITY` module global (set by `run_pipeline` from `parse_diagnostics.json`) and stamped `parse_quality` into every chunk in `write_chunk`. Added `_compute_parse_quality()` and `_get_parse_diagnostics()` helpers.
- **R7.2** — `parse_coverage_pct` added to `program_summary` metadata from `parse_diagnostics.json`. Omitted when diagnostics file is absent.
- **R7.4** — New `generate_cobol_analysis_health()` function producing one `cobol_analysis_health` chunk per COBOL program. Contains parse coverage, stubbed copybook list, quality flags, and a deterministic confidence label (high/medium/low). Calls `copybook_manifest.json`.
- **R2.4** — New `enrich_called_by()` post-processing: builds reverse call index from all paragraph `calls` lists and stamps `called_by: [...]` onto each target paragraph chunk. Called in `run_pipeline` after size-guard.
- **R2.6** — Added `datasets` field (deduped union of `input_datasets` + `output_datasets`) to `step_detail` chunk metadata in `generate_step_details`.
- **R3.2** — New `enrich_calls_chunk_ids()` post-processing: resolves bare paragraph names in `calls` to full chunk_ids (`prog:paragraph_logic:PARA`). Keeps original bare names in `calls_names` for backward compat.
- **R3.3** — New `enrich_program_summary_links()` post-processing: adds `paragraph_chunks` and `variable_group_chunks` lists to `program_summary` metadata after all child chunks are finalized.

**Why:** Completes Phase 1 structural foundation (hash determinism, validation gate) and Phase 2 metadata layer (parse provenance, cross-references, navigability). After these changes every chunk is self-describing — consumers can assess parse quality, navigate call graphs, and detect staleness without reading multiple artifact files.

---

## 2026-03-23 — Report plan first batch (P0): R2.7, R4.1, R4.2, R1.1
First batch (P0) — completed
R2.7 — pipeline_version + analysis_timestamp (chunk_pipeline.py, jcl_cobol_report.py)

Added PIPELINE_VERSION = "1.2" constant to both files.
write_chunk / _write_chunk now stamp every chunk metadata with pipeline_version and analysis_timestamp (ISO-8601 UTC, set at generation time).
Business: Enables detecting stale chunks after a pipeline upgrade or re-analysis.
R4.1 — tiktoken BPE token counting (chunk_pipeline.py)

token_count() now uses tiktoken cl100k_base (GPT-4 / text-embedding-3 tokenizer) with a whitespace-split fallback when tiktoken is absent.
set_token_counter("bpe"|"whitespace") lets callers switch modes.
Manifest entries gain token_count_bpe alongside legacy token_count.
Business: Fixes ~10–15% silent tail truncation when chunks are fed to small embedding models; also corrects cost estimates for paid API usage by ~30%.
R4.2 — configurable chunk size limits (chunk_pipeline.py)

New CLI flags: --max-tokens (default 512), --min-tokens (default 20), --overlap-tokens (default 50), --token-counter.
Flags override the module-level constants before the pipeline runs.
Business: Different embedding models have very different optimal chunk sizes; 384 for all-mpnet-base-v2, 8191 for text-embedding-3-large.
R1.1 — build_corpus_index.py (build_corpus_index.py) — new file

Walks all *.report directories, builds a corpus_index.json with programs, jobs, and tables sections.
Merges called_by/entry_type from cross_program_calls.json automatically.
Business: Tier-0 metadata index — "which programs write to table X?" is now a direct JSON key lookup, no embeddings required.
**File(s):** `chunk_pipeline.py`, `jcl_cobol_report.py`, `build_corpus_index.py` (new)
**What changed:** Implemented the four P0 tasks from `report_plan.md`:

- **R2.7** — Added `PIPELINE_VERSION = "1.2"` constant and stamped `pipeline_version` + `analysis_timestamp` (ISO-8601 UTC) into every chunk via `write_chunk` / `_write_chunk`. `analysis_timestamp` is set at chunk generation time, not baked in as a constant. `datetime` import added to `chunk_pipeline.py` (already present in `jcl_cobol_report.py`).
- **R4.1** — Replaced `len(text.split())` with a tiktoken BPE counter (`cl100k_base` encoding). Falls back to whitespace splitting when tiktoken is not installed. `set_token_counter(mode)` function allows switching at runtime. Manifest entries now also include `token_count_bpe` alongside the legacy `token_count` field when tiktoken is available.
- **R4.2** — Added `--max-tokens`, `--min-tokens`, `--overlap-tokens`, `--token-counter` CLI flags to `chunk_pipeline.py`. Flags override the module-level `MAX_CHUNK_TOKENS`, `MIN_CHUNK_TOKENS`, `OVERLAP_TOKENS` constants before `run_pipeline()` is called.
- **R1.1** — Created `build_corpus_index.py`: walks `*.report` directories, extracts COBOL program metrics (complexity, node/variable counts, SQL tables, CICS commands, calls) and JCL job structure (steps, programs invoked), optionally merges `called_by`/`entry_type` from `cross_program_calls.json`, and writes `out/corpus_index.json`. CLI: `python3 build_corpus_index.py [--report-dir] [--output] [--cross-program] [-v]`.

**Why:** Phase 1 structural foundation from `report_plan.md`. R2.7 enables stale-chunk detection. R4.1/R4.2 fix silent BPE truncation (~10–15% tail loss for small embedding models) and unlock correct cost estimation for paid APIs. R1.1 provides the tier-0 metadata index for cross-program queries without any embedding infrastructure.

---

## 2026-03-23 — Java-side CFG/Flow AST investigation for 7 COBOL constructs

**File(s):** `java_cfg_investigation.md` (new), `report_plan.md` (updated)
**What changed:** Created investigation document analyzing how 7 COBOL constructs are handled across the ANTLR grammar, Flow AST node type mapping, and CFG edge construction layers. Documented two critical issues (EVALUATE branches invisible in CFG output; CICS HANDLE creates no handler edges), two partial issues (EXIT PARAGRAPH/SECTION missing jump-to-exit edges; STRING/UNSTRING lumped under GENERIC_STATEMENT), two correctly handled constructs (GO TO DEPENDING ON; PERFORM VARYING), and one acceptable limitation (ALTER). Also audited 13 unsafe access patterns in visitor classes that would NPE on partial parse trees in lenient mode. Updated `report_plan.md`: added R8.7 (EVALUATE fix) to Step R8 and Phase 4; updated R8.5/R8.6 in Future Work with investigation results; added 5 new Future Work entries for CICS HANDLE, EXIT edges, STRING/UNSTRING types, ALTER warning, and defensive visitor NPEs.
**Why:** Needed to understand Java-side behavior before improving Python-side knowledge base generation and data flow analysis. Key finding: EVALUATE WHEN branches are completely missing from CFG JSON output due to `EvaluateFlowNode.acceptUnvisited()` not visiting branch child nodes (unlike IF and SEARCH which do this correctly).

---

## 2026-03-22 — Restructure report_plan.md: scoped to RAG input generation, 5-phase plan

**File(s):** `report_plan.md`
**What changed:** Major restructuring of the implementation roadmap:
- Scoped plan to RAG input file generation only — removed retrieval code (R1.2–R1.6), embedding infrastructure (R4.3), query routing, and `ask.py`. Q7–Q15 analysis kept as context for future work.
- Reorganized into 5 phases: Phase 1 (P0, structural foundation: R1.1, R4.1, R4.2, R7.7, R2.7 + validation script), Phase 2 (P1, metadata & cross-refs), Phase 3 (P1, text quality & extraction), Phase 4 (P1/P2, robustness & completeness), Phase 5 (future work/known limitations).
- Added new Phase 1 Validation Script (`validate_chunks.py`) with 5 structural integrity checks and regression gates after each phase.
- Moved 14 low-priority/infrastructure items to Future Work section (R6.3, R5.5, R7.8, R8.3, R8.5, R8.6, R3.4, R3.5, R2.8, R6.4, R7.6, R7.9, R7.10, R7.11).
- Updated priority tags, Answers Summary table (Q7–Q15 → "Context only — retrieval not in scope"), and Implementation Order section.
**Why:** User-requested scope refinement to focus on chunk/artifact quality rather than retrieval infrastructure.

---

## 2026-03-21 — Implement Step 7b: RAG Chunk Quality Improvements

**File(s):** `jcl_cobol_report.py`, `chunk_pipeline.py`
**What changed:** Implemented substeps 7b.1–7b.9 and 7b.11 (10 of 11 substeps; 7b.10 tiktoken is optional/deferred):
- **7b.1**: Generate step chunks for ALL JCL steps, not just analyzed ones. PDADDRE1 now produces 7 step_relationship chunks (was 0). Non-analyzed steps marked `"analysis_status": "missing"`.
- **7b.2**: Added stable `chunk_id` to all chunk types (format: `<program>:<chunk_type>:<discriminator>`). Both JCL and COBOL chunks.
- **7b.3**: Added cross-reference fields: `related_cobol_chunks` on JCL step chunks, `parent_program_chunk` on paragraph_logic and variable_group chunks.
- **7b.4**: New `jcl_dataset_flow` chunk type — one chunk per dataset with producer/consumer/flow_type/is_temporary metadata.
- **7b.5**: Fixed paragraph_logic duplicate content — stripped reverse CFG walk section while preserving PERFORM metadata extraction from full body before stripping.
- **7b.6**: Filtered FILLER from variable_group `field_names` metadata; added `filler_count` field instead.
- **7b.7**: Normalized excess whitespace in THRU ranges within paragraph_logic `calls` metadata.
- **7b.8**: New `jcl_analysis_health` chunk type — coverage %, missing programs, quality flags per program.
- **7b.9**: New `jcl_condition_flow` chunk type — describes conditional execution logic per job.
- **7b.11**: Natural language flow narration added to `jcl_cobol_overview` chunk text.
- Also fixed DD filtering to exclude `dsn="(none)"` entries from input/output dataset lists.
- Manifest cleanup now removes all 5 JCL chunk types on re-run for idempotency.

**Verified on:** PDADDRE1 (25 chunks, all 7 steps), PDASCO01 (6 chunks), PDCAFIN2 (35 chunks), PDCBVC.CBL (61 chunks, FILLER filtered, chunk_ids correct), PAYROL00.cbl (3 chunks).
**Why:** Chunk quality improvements required before embedding into vector store (Step 8). Addresses the 52% end-to-end RAG readiness score identified in the evaluation.

---

## 2026-03-21 — RAG Output Evaluation & Step 7b Added to ongoingPlan

**File(s):** `ongoingPlan.md`
**What changed:** Conducted detailed evaluation of all jcl_cobol_report and chunk_pipeline outputs for RAG suitability. Scored end-to-end RAG readiness at 52%. Identified 11 concrete improvements across 4 phases (chunk quality fixes, new chunk types, token counting, flow narration). Added Step 7b to ongoingPlan.md with all substeps, self-evaluation accuracy tables (per-step, inter-file relationships, chunk quality metrics), and updated ordering constraints to gate Step 8 (vector store) on Step 7b completion.
**Why:** Chunks must be quality-improved before embedding into a vector store. Key gaps: non-analyzed JCL steps produce 0 chunks (PDADDRE1 has 7 steps but 0 step_relationship chunks), no dataset flow or condition flow chunks exist, no cross-references between JCL and COBOL chunks, paragraph_logic chunks contain duplicate forward+reverse narrative, variable_group metadata polluted with FILLER entries.

---

## 2026-03-20 — Fix Lenient Mode: Expression Resolution NPE on Partial Trees

**File(s):** `BuildBaseModelTask.java`, `ParsePipeline.java`, `analyze.py`
**What changed:** Wrapped `flowRoot.resolve()` in BuildBaseModelTask.run() with a
try-catch for lenient mode. On partial parse trees, expression resolution crashes with
NPE (e.g., `AdditionalConditionVisitor.getRelationalOperation()` gets null from
`SimpleConditionExpression.getComparison()` for malformed conditions). In lenient mode,
the crash is now caught and the structural model (AST, CFG, flow nodes) is returned
with unresolved expressions. Also added `@Getter` to `ParsePipeline.lenient` field so
BuildBaseModelTask can check the lenient flag. Made steps 3 and 3b in analyze.py use
`check=False` to prevent Python-side crashes on non-critical steps.
**Why:** After fixing the data structure validation crash, the next crash point was
`resolve()` which traverses every AST node resolving expressions. On partial trees,
some IF conditions are incomplete, causing NPEs. Since BUILD_BASE_ANALYSIS is prepended
to every task list, this blocked ALL Java CLI invocations (steps 1-3b).

---

## 2026-03-20 — Fix Lenient Mode: Data Structure Validation Crash

**File(s):** `ParsePipeline.java`
**What changed:** Wrapped `dataStructureValidation.run()` (line 180) in a try-catch
for lenient mode. When data structure validation crashes (e.g., `NoSuchElementException`
from `Format1DataStructure.spec()` calling `List.getFirst()` on an empty list due to
incomplete data definitions in ANTLR-recovered partial trees), lenient mode now catches
the exception and falls back to `NullDataStructure("LENIENT_FALLBACK")` instead of
crashing the entire pipeline. This fixes ALL downstream Java CLI invocations (steps 2,
3, 3b) which re-parse the file and hit the same crash point.
**Why:** The previous fix made `ParsePipeline.parse()` skip the throw for parse errors
in lenient mode, but the data structure validation at line 180 still crashed on partial
trees. Every Java CLI invocation (step 1, 2, 3, 3b) re-parses the file, so this crash
blocked the entire pipeline even though `parse_diagnostics.json` was successfully written.

---

## 2026-03-20 — Fix Lenient Mode: Partial Success Detection

**File(s):** `analyze.py`

**What changed:** Added `_check_lenient_partial_success()` to detect when the
Java CLI exits with code 1 but DID write `parse_diagnostics.json`. This happens
because lenient parsing succeeds (ANTLR recovers from errors) but a downstream
task like WRITE_CFG crashes on the partial tree with `NoSuchElementException`.
The Java try-catch writes diagnostics before returning, but `processResults()`
in MultiCommand sees the ERROR result and exits with code 1. Python now checks
for `parse_diagnostics.json` before treating a non-zero exit as failure — if the
file exists, the pipeline continues with whatever output was produced.

**Why:** The Java CLI's exit code conflates "parse failed" with "parse succeeded
but a task failed on partial tree". Both return exit code 1. Python needs to
distinguish them to avoid aborting when partial analysis IS available.

---

## 2026-03-20 — Fix Lenient Mode Crash: Task Execution + Stderr Parsing

**File(s):** `CodeTaskRunner.java`, `analyze.py`

**What changed:** Two fixes after testing the --lenient flow end-to-end:

1. **Java — `CodeTaskRunner.runForProgram()`**: Wrapped `pipelineTasks.run()`
   in try-catch for `RuntimeException` when lenient mode is active. Previously,
   even though `ParsePipeline` successfully produced a partial parse tree in
   lenient mode, downstream tasks (WRITE_CFG, WRITE_DATA_STRUCTURES etc.) could
   throw `NullPointerException` or similar on the partial tree, crashing before
   `writeParseDiagnostics()` was reached. Now the exception is caught, logged,
   and `parse_diagnostics.json` is still written. Non-lenient mode re-throws
   as before — backward compatible.

2. **Python — `_parse_stderr_errors()`**: The regex `\b(ERROR|WARNING|INFO|HINT)\b`
   matched every Java log line (e.g., `[INFO] Calculating type spec...`),
   producing 603 false-positive "errors" in the failure report. Rewritten to
   only capture lines containing `SyntaxError`, `ParseDiagnostic`, `Exception`,
   or `severity=ERROR` — the patterns that indicate actual parse errors. Also
   added extraction of the `suggestion` field from SyntaxError log entries.

**Why:** The first real-world test showed that lenient parsing succeeded (ANTLR
recovered from 2 comment errors at lines 1062 and 3559) but then a task crashed
on the partial tree, and the Python-side failure report was unusable due to 603
false-positive entries from normal INFO log lines.

---

## 2026-03-20 — Fix --lenient Flag + Smart Parse Diagnostics & Coverage Evaluation

**File(s):** `ParsePipeline.java`, `CodeTaskRunner.java`, `analyze.py`, `jcl_cobol_report.py`

**What changed:** Fixed the --lenient flag to produce actual analysis output
for COBOL files with parse errors, added smart error diagnostics that explain
what went wrong and where, and added self-evaluation coverage percentages for
both the main program and its copybooks.

**Why:** Enterprise COBOL files frequently have minor parse issues (unmatched
quotes in comments, vendor-specific extensions, truncated lines) that caused
the entire analysis to fail. The user has hundreds of such files that cannot
be modified. The tool needed to degrade gracefully and transparently report
what it could and couldn't analyze.

### Detailed Implementation Notes

#### Sub-step 1 — Root cause analysis of the --lenient failure
- Traced the exception path from ParsePipeline.parse() through
  BuildBaseModelTask, SmojolTasks, and CodeTaskRunner
- Business logic: ANTLR's DefaultErrorStrategy already builds a
  near-complete parse tree via token insertion/deletion/resync
  even when errors occur — the tree is available at line 134 of
  ParsePipeline but the unconditional throw at line 139 discards it
- Business logic: the --lenient flag only suppressed the re-throw
  at CodeTaskRunner line 111 (TaskRunnerMode.LENIENT_MODE.run()),
  but by that point no tasks had run and the results map was empty
- Result: strict mode = crash with exit code 1, lenient mode =
  exit code 0 but zero output files — both equally useless

#### Sub-step 2 — ParsePipeline.java: lenient mode with error collection
- Added `private boolean lenient` field with setter — uses setter
  pattern instead of constructor parameter to avoid modifying all
  existing call sites (ValidateTaskRunner, tests, etc.)
- Added `@Getter parseErrors` list to store errors when lenient
  mode skips the throw — downstream code can access what was skipped
- Added `@Getter totalTreeNodes` computed after tree building via
  recursive node counting — enables coverage estimation
- Added `@Getter sourceLineCount` from the source text — denominator
  for line-based coverage percentage
- Business logic: in lenient mode, after logging each error, the
  method continues to line 142 where it processes the tree normally;
  the navigator, data structures, and all other artifacts are built
  from the ANTLR-recovered partial tree
- Business logic: coverage is estimated as
  (source_lines - error_affected_lines) / source_lines * 100;
  this is a line-based metric, not a node-based one, because
  the user cares about "how much of my source was understood"

#### Sub-step 3 — CodeTaskRunner.java: threading the flag + diagnostics output
- Modified runForProgram() to accept boolean lenient parameter
- After ParsePipeline construction, calls pipeline.setLenient(lenient)
- Derives lenient from TaskRunnerMode identity comparison:
  `runnerMode == TaskRunnerMode.LENIENT_MODE` — valid because
  TaskRunnerMode uses singleton instances (static final fields)
- After tasks complete, if lenient mode had errors, writes
  parse_diagnostics.json to the report directory
- Business logic: diagnostics JSON includes per-error records with
  line/column (converted from 0-based to 1-based for human readability),
  severity (ERROR/WARNING/INFO/HINT), error source (PARSING/PREPROCESSING/
  COPYBOOK/DIALECT), human-readable suggestion, and copybook ID
  (identifies if error originated in a copybook, not main source)
- Business logic: error summary aggregates by severity and source type
  to help identify systemic patterns (e.g., all errors from one copybook)
- Business logic: affected_lines is a Set<Integer> of unique error lines,
  not the sum of error ranges — prevents double-counting overlapping errors

#### Sub-step 4 — analyze.py: copybook manifest generation
- After sandbox setup (copybooks resolved + stubs created), writes
  copybook_manifest.json listing every copybook with its status
- Business logic: status is "resolved" (found on disk and copied to
  sandbox) or "stubbed" (missing or broken, replaced with minimal
  COBOL comment stub); this distinction matters because stubbed
  copybooks mean the variables/structures they define are absent
  from the data dictionary and any COPY-included logic is missing
- Business logic: line count per copybook is the raw file line count
  before inlining — gives a rough measure of how much code comes
  from each copybook (a 500-line stubbed copybook is worse than
  a 5-line stubbed copybook)
- Business logic: resolved_percentage is
  (total - stubbed) / total * 100 — a quick health metric for
  whether the program's copybook dependencies were satisfiable

#### Sub-step 5 — analyze.py: smart step1 with auto-retry and failure diagnostics
- Root cause: run_command() used check=True → sys.exit(1) on failure,
  killing the pipeline before _log_parse_diagnostics() could execute.
  Also didn't capture stderr, losing all structured error info from Java CLI.
- Added run_command_captured() — same as run_command() but returns
  CompletedProcess with captured stdout/stderr, never calls sys.exit()
- Added _count_parse_errors() — counts SyntaxError/ParseDiagnostic
  patterns in Java CLI output for reporting to user
- Business logic: step1 now tries strict parse first. If it fails,
  it auto-retries with --lenient (same pattern as jcl_cobol_report.py's
  _run_cobol_analysis). This means the user doesn't need to know about
  --lenient — the tool handles it automatically.
- Business logic: when auto-retrying, self.options['lenient'] is set
  to True so all subsequent smojol commands (step2, step3, etc.)
  also run with --lenient, ensuring consistency.
- Added _parse_stderr_errors() — extracts line numbers, severity,
  copybook names, and error messages from Java CLI stderr using
  regex patterns. This is a best-effort fallback when Java doesn't
  write parse_diagnostics.json (because it crashed before reaching
  that code path).
- Added _write_parse_failure_report() — writes parse_failure_report.json
  when even --lenient fails. Contains extracted errors + raw stderr
  tail (last 20 lines) for debugging. This ensures there is ALWAYS
  a diagnostic artifact, even for total failures.
- Added _print_stderr_summary() — prints structured error summary
  to console before exit, showing first 10 errors with line numbers
  and copybook attribution. Falls back to raw stderr tail if no
  structured errors were parseable.
- Business logic: _log_parse_diagnostics() now always runs after
  a successful parse (strict or lenient), reading the Java-written
  parse_diagnostics.json. This is the high-quality diagnostic path.
  _write_parse_failure_report() is the low-quality fallback path
  when Java itself crashes.

#### Sub-step 5b — analyze.py: diagnostics console logging (now reachable)
- After step 1 completes successfully, reads parse_diagnostics.json
- Prints colored summary: "[LENIENT] Parse coverage: 99.94%
  (2 error(s) affecting 2/3559 lines)"
- Prints each error with its source type, line number, and suggestion
- Business logic: this was already implemented but never executed
  because sys.exit(1) killed the process first. Now it executes
  because step1 uses run_command_captured() instead of run_command().

#### Sub-step 6 — jcl_cobol_report.py: health check integration
- In _check_program_artifacts(), reads parse_diagnostics.json from
  each COBOL report directory
- Adds quality flag with coverage percentage and error count
- Lists individual parse errors as sub-flags for detailed inspection
- Reads copybook_manifest.json and adds quality flags for stub rates
- Business logic: programs analyzed with lenient mode are flagged
  but NOT downgraded to "partial" status unless they're also
  missing expected output artifacts — a 99.9% coverage lenient
  analysis is better than no analysis at all
- Business logic: stubbed copybook names are listed (up to 10)
  so the user knows which copybooks to obtain if they want to
  improve coverage
- Business logic: the coverage percentage flows through to the
  JCL-COBOL relationship report markdown, giving the user a
  per-program confidence score alongside the SQL/CALL/CICS data

#### Sub-step 7 — Backward compatibility verification
- Default lenient=false preserves all existing behavior:
  ParsePipeline throws as before, CodeTaskRunner catches as before,
  no diagnostics files are written
- No changes to BuildBaseModelTask, SmojolTasks, TaskRunnerMode,
  or the CLI flag definition in MultiCommand
- No changes to the ANTLR grammar or Che4z submodule
- The two new JSON artifacts (parse_diagnostics.json,
  copybook_manifest.json) are additive — existing downstream
  tools ignore files they don't know about

---

## 2026-03-19 — JCL-to-COBOL Relationship Report Generator

**File(s):** `jcl_cobol_report.py`

**What changed:** New standalone script that generates a comprehensive
relationship report between a JCL job and the COBOL programs it invokes.
Produces 4 output artifacts per JCL report directory: JSON model, Markdown
report, Mermaid diagram, and RAG chunks.

**Why:** No existing tool provided a per-JCL view that cross-references
JCL steps with COBOL program internals (dependencies, complexity, call chains).
`build_call_graph.py` gives a corpus-wide flat graph; this script gives a
detailed, single-job perspective with diagnostics and health checks.

### Detailed Implementation Notes

#### Step 1 — CLI and Data Loading
- Accepts a JCL report directory (must already contain jcl_summary.json,
  jcl_steps.json, jcl_datasets.json from jcl_parser.py)
- Loads all 3 JSON artifacts into memory
- Reuses `normalize_program_name()` from build_call_graph.py for
  case-insensitive, extension-stripped program matching
- Default report search path: parent of the JCL report directory

#### Step 2 — COBOL Report Discovery
- For each program in `jcl_summary["programs_invoked"]`, searches
  the report root for a matching `.report` directory
- Uses `build_corpus_registry()` to build canonical-name -> report-dir map
- Filters system utilities (IDCAMS, IEFBR14, ICEMAN, IEBGENER, SORT,
  PARM2SK) using `_SYSTEM_PGMS` from build_call_graph.py
- Business logic: programs are matched by canonical uppercase name
  with COBOL extensions stripped; PDHM730B matches any of
  PDHM730B.CBL.report, PDHM730B.cbl.report, PDHM730B.cob.report

#### Step 3 — COBOL Dependency Extraction
- For each found COBOL report, loads:
  - 03_Dependencies.yaml -> SQL tables (read/updated), CALL targets, CICS commands
  - 00_Executive_Summary.md -> complexity score (parsed from metrics table)
  - data_structures/*-data.json -> variable count, FILE SECTION presence
- Business logic: complexity is parsed from the "Complexity Score" row of the
  executive summary markdown table using regex; if unparseable, defaults to -1
- Business logic: SQL tables are split into read vs updated based on the
  YAML structure (tables_read vs tables_updated lists)

#### Step 4 — Step Relationship Building
- For each step in jcl_steps.json, creates a StepRelationship record
- Links step's program to its COBOL dependencies (if in corpus)
- Classifies each DD statement by role:
  - JOBLIB/STEPLIB -> library_override
  - SYSIN -> program_input (control cards)
  - SYSPRINT/SYSOUT/SYSERR -> system_output
  - SYSUDUMP/SYSABEND -> diagnostic_dump
  - Others -> data (input or output based on DISP and access field)
- Business logic: DD access classification uses jcl_parser's access field
  (read/write/pass/special); additionally checks DISP status for "special":
  SHR/OLD -> read, CATLG/KEEP -> write, PASS -> pass
- Extracts DSN handling all forms: plain string, PDS member dict,
  GDG dict, temporary dict, null dataset

#### Step 5 — Dataset Flow Analysis
- Builds a flow graph from jcl_datasets.json
- For each dataset, determines:
  - External input: read_by is non-empty but written_by is empty within the job
  - Inter-step flow: written_by step X and read_by step Y
  - Final output: written_by is non-empty but not read_by any step
  - Temporary: DSN starts with && or has {"temporary": true}
- Also scans step DD mappings for temporary datasets not tracked in
  jcl_datasets.json (&&NAME intermediaries only visible in step DDs)
- Business logic: temporary datasets are included in inter-step flows
  (they represent pipeline data) but flagged separately in output

#### Step 6 — Transitive Call Chain Computation
- Uses `parse_cobol_calls()` to get all COBOL CALLS edges across the corpus
- For each JCL-invoked program, walks forward through the call graph
- Depth limit: 5 levels to prevent runaway traversal
- Cycle detection: maintains a visited set per chain
- Business logic: external programs (not in corpus) appear as leaf nodes
  in the chain with a "(not in corpus)" annotation

#### Step 7 — JSON Model Output (`jcl_cobol_relationship.json`)
- Contains: steps[], dataset_flows[], program_health{}, summary{}, logs[]
- Each step includes: DD mappings, COBOL metrics (complexity, nodes, edges,
  variables), SQL tables, CALL targets, CICS commands, transitive chain
- All names are canonical (uppercase, no extension)
- Timestamps use ISO 8601

#### Step 8 — Markdown Report Output (`jcl_cobol_relationship.md`)
- Sections: Job Overview, Execution Flow Diagram, Step-by-Step Breakdown,
  Analysis Health Check, Dataset Flow Table, Transitive Call Chains,
  Data Contract Summary, Analysis Log
- Business logic: steps are presented in execution order (array index)
- Business logic: system utility steps get a condensed format (no COBOL
  details, just DD/dataset info)
- Business logic: the Health Check table uses status indicators
  (COMPLETE / PARTIAL / MISSING) and lists specific missing artifacts
- Includes actionable recommendations for missing programs

#### Step 9 — Mermaid Diagram Output (`mermaid/jcl_cobol_flow.md`)
- Steps as boxes, datasets as parallelograms
- Color coding via CSS classes: green (analyzed), gray (utility), red (missing)
- Dashed arrows for COBOL CALL relationships between programs
- Temporary datasets use yellow color class
- Business logic: diagram truncates at 50 dataset nodes with a note if exceeded

#### Step 10 — RAG Chunks
- Two new chunk types: jcl_cobol_overview, jcl_cobol_step_relationship
- Merges with existing chunks_manifest.json preserving existing chunks
- Business logic: only steps with analyzed COBOL programs get
  step_relationship chunks (system utilities and missing programs
  are covered in the overview chunk only)

#### Step 10b — Diagnostics and Health Check
- Console logging: [INFO], [FOUND], [MISSING], [WARN] per program
- Per-program artifact inventory: checks 7 expected files/directories
- Quality flags: empty CFG, missing dependencies, no SQL/CALL/CICS,
  high complexity (>50)
- Coverage score: "N/M programs analyzed (X%)"
- Full analysis log embedded in both JSON and Markdown output

---

## 2026-03-17 — Step 7: build_call_graph.py cross-program call graph

**File:** `build_call_graph.py`
**What changed:** New script that aggregates COBOL CALL edges (from `03_Dependencies.yaml`) and JCL EXECUTES edges (from `jcl_summary.json`) across all report directories into a unified `out/cross_program_calls.json`. Supports multiple `--report-dir` values so JCL and COBOL report directories at different paths are both discoverable. Also updates `program_summary` chunk metadata with `called_by` and `entry_type` fields.
**Why:** Step 7 of the pre-RAG roadmap. Enables cross-program impact analysis and enriches RAG metadata with caller relationships.

---

## 2026-03-16 — chunk_pipeline.py improvements: merge strategy, variable values, complexity fix

**File:** `chunk_pipeline.py`
**What changed:** Three improvements found during post-implementation testing:

1. **EXIT-to-parent merge strategy** — COBOL EXIT paragraphs (1-3 tokens: just `GO TO` or empty) are now merged into their parent paragraph (e.g. `INIZ-PARAM-EXIT` → `INIZ-PARAM`). Previously, consecutive-only merge missed isolated small chunks scattered across the file. Added a 3-pass merge: EXIT-to-parent → consecutive small → orphan-into-previous. Result: 81 → 63 chunks, 0 chunks under 20 tokens.

2. **`variable_values.json` enrichment** — The 40 static value assignments (e.g. `WABEND-CODE: ['GET1','BR00','FS00']`) were not used in any chunk. Now injected into both `paragraph_logic` chunks (appended as "Known values: VAR = val1, val2" for richer embedding) and `variable_group` chunks (appended as "Static assignments:" section). This gives the embedding model concrete data semantics, not just type declarations.

3. **Complexity calculation fix** — The original approach used STARTS_WITH containment to find paragraph subgraphs, but the CFG links paragraph content via FOLLOWED_BY chains instead. Switched to BFS from PARAGRAPH_NAME via FOLLOWED_BY edges, then counts decision nodes (IF_BRANCH, EVALUATE, SEARCH) + 1. The classical McCabe formula (E-N+2) doesn't work on open subgraphs where most JUMPS_TO edges leave the paragraph.

**Why:** Testing revealed all complexity_local values were 1 (broken CFG traversal), 22/81 chunks had fewer than 20 tokens (EXIT paragraphs not merged), and variable_values.json was unused data that would improve embedding quality.

**Test results:** 69/69 paragraphs covered, 0 under-20-token chunks, 0 over-512-token chunks, complexity range 1-9 with 7 unique values, 37 paragraphs enriched with static values, 8 variable groups enriched.

---

## 2026-03-16 — Build chunk_pipeline.py (Step 5)

**File:** `chunk_pipeline.py` (new)
**What changed:** Created standalone chunking pipeline that splits monolithic knowledge-base documents and JCL parser output into fine-grained JSON retrieval units for RAG.

**Why — the RAG problem this solves:**
The existing knowledge base produces four large documents per COBOL program (executive summary, logic narrative with all 69+ paragraphs, data dictionary with 1300+ variables, dependency YAML). These are useful for human reading but are poor retrieval units: when a RAG query asks "what does paragraph BROWSE-FASE1 do?", the embedding search would need to match against a 25KB narrative containing all paragraphs. The same applies to JCL reports — a single `jcl_steps.json` covers all steps in one file.

Chunking solves this by creating one JSON file per retrieval unit, each with:
- `text` — the content that gets embedded (paragraph logic, variable definitions, step details)
- `metadata` — structured fields enabling pre-filtering without embedding search (program name, paragraph name, chunk type, complexity score, etc.)

**Design decisions and business logic:**

1. **Six chunk types** — four for COBOL, two for JCL — each at a different granularity:
   - `program_summary` (1/program): metrics + node type distribution. Answers "how complex is this program?"
   - `paragraph_logic` (1/paragraph): statement-level logic + enriched English comment. Answers "what does this paragraph do?"
   - `variable_group` (1/level-01 record): field definitions with PIC clauses. Answers "what data does this group hold?"
   - `dependencies` (1/program): SQL tables, CALL targets, CICS commands. Answers "what external systems does this touch?"
   - `job_flow` (1/JCL job): step sequence, programs invoked, datasets. Answers "what does this batch job do?"
   - `step_detail` (1/JCL step): program, condition, input/output datasets. Answers "what does step X execute?"

2. **Comment enrichment integration** — For `paragraph_logic` chunks, the English translation from `comments_enriched.json` (produced by Step 3 / Step 4) is prepended to the paragraph text. This means the embedding model sees developer intent ("Start of browse phase") alongside algorithmic description ("MOVE LOW-VALUE TO PDCBVC1I"), placing both in the same vector space. This is critical for Italian-codebase RAG: without it, queries like "initialization logic" would miss paragraphs whose only intent signal is an Italian comment.

3. **CFG metadata enrichment** — After generating paragraph chunks, the pipeline traverses the CFG to compute per-paragraph local complexity (McCabe: internal edges - nodes + 2 within the STARTS_WITH containment subtree). This is injected into chunk metadata as `complexity_local`, enabling queries like "find the most complex paragraphs" via metadata filtering rather than embedding search.

4. **Chunk size guard** — Two passes:
   - *Merge*: consecutive paragraphs with <20 tokens are merged (e.g., trivial EXIT paragraphs). Preserves all paragraph names in metadata. PDCBVC produced 4 merges (8→4 chunks).
   - *Split*: paragraphs exceeding 512 tokens are split with 50-token overlap. No splits were needed for PDCBVC, but this protects against programs with unusually large paragraphs.

5. **Dual-mode detection** — Accepts either COBOL (`cfg/` directory present) or JCL (`jcl_summary.json` present) reports. Both can be true for future cross-artifact reports.

6. **Schema versioning** — Every chunk carries `schema_version: "1.0"` in metadata. This enables future `ingest_chunks.py` to detect stale chunks and trigger re-embedding when the schema changes.

7. **DSN dict handling** — JCL DD statements can have DSN as a dict (`{"dsn": "MY.LIB", "member": "MEMBER"}`) for PDS member references. The pipeline normalizes these to `MY.LIB(MEMBER)` string format for chunk text.

8. **Optional by design** — The pipeline is a standalone script, not wired into `analyze.py`. This enables comparing RAG with and without chunking (monolithic documents vs. fine-grained chunks) for the thesis evaluation.

**Test results:**
- PDCBVC.CBL: 81 chunks (1 program_summary, 1 dependencies, 65 paragraph_logic, 14 variable_group). 69 paragraphs enriched with CFG complexity. 4 small paragraph merges.
- PDADDRE1.jcl: 8 chunks (1 job_flow, 7 step_detail). All step details include correct program names and dataset classifications.
- PDASCO01.jcl: 2 chunks (1 job_flow, 1 step_detail).
- PDCAFIN2.jcl: 10 chunks (1 job_flow, 9 step_detail).
- PAYROL00.cbl: 3 chunks (1 program_summary, 1 dependencies, 1 variable_group). 0 paragraph_logic — correct, as PAYROL00 has no named paragraphs.

---

## 2026-03-16 — Wire comment_enricher into analyze.py (Step 4)

**File:** `analyze.py`
**What changed:** Added `import comment_enricher`, a `--no-comment-enrichment` CLI flag, a `step7b_comment_enrichment()` pipeline method, and wired it into `run()` after `step7_knowledge_base()`. Reuses `comment_enricher.check_ollama()` for reachability gating; failure is non-fatal (warning only).
**Why:** Step 4 of the pre-RAG roadmap — `comment_enricher.py` should run automatically when Ollama is available, producing `comments_enriched.json` in the report directory.

---

## 2026-03-15 — Step 2 & 3: LLM test verification with granite-code:8b

**File(s):** `run_llm_documentation.py`, `comment_enricher.py`
**What changed:** Tested both scripts end-to-end with `granite-code:8b`. Step 2: generated `llm_input/` for `hello.cbl` from its `.dot` graphviz file, ran `run_llm_documentation.py` — first run produced Markdown + `structured.json` (33.6s); second run was 0.00s from cache. `structured.json` has non-empty `summary`, `business_rules`, `external_calls`. Step 3: ran `comment_enricher.py` on `PDCBVC.CBL.report/comments.json` — 21 entries processed (19 translated, 2 fallback), all written to `comments_enriched.json`; second run reported "All paragraphs already enriched" instantly.
**Why:** End-to-end verification of Step 2 and Step 3 substeps with actual LLM model.

---

## 2026-03-15 — Step 3: comment_enricher.py (3.1–3.6)

**File(s):** `comment_enricher.py` (new)
**What changed:** New standalone script that reads `comments.json`, translates Italian COBOL comments to English via Ollama, and writes `comments_enriched.json`. Implements all substeps: (3.1) CLI with argparse and Ollama health check; (3.2) core `_enrich_batch()` with batch LLM call and JSON extraction (direct parse → regex fallback); (3.3) batched processing at 15 paragraphs/call; (3.4) JSON validation with single retry using stricter prompt, then per-entry fallback with `translation_failed: true`; (3.5) incremental caching — skips paragraphs already present in `comments_enriched.json`; (3.6) `_PROGRAM_SUMMARY` handled with dedicated prompt. Also includes `--auto-model` flag (prefers `qwen2.5:3b`/`llama3.2:3b` over `granite-code:8b` for translation tasks). LLM test deferred until model download completes.
**Why:** Step 3 of pre-RAG roadmap — Italian source comments are a retrieval liability; English translation + category label makes them high-value RAG signals.

---

## 2026-03-14 — Step 1b: JCL parser complete (1b.1–1b.12)

**File(s):** `jcl_parser.py`, `test_jcl_parser.py`
**What changed:** Hand-written IBM JCL parser producing 3 JSON artifacts per job (`jcl_summary.json`, `jcl_steps.json`, `jcl_datasets.json`). Covers: column-based tokenizer with continuation collection, informal comment trimming, inline data mode (DD `*`/`DATA`); JOB/EXEC/DD/PROC/PEND/OUTPUT/SET/IF/THEN/ELSE/ENDIF/JCLLIB/INCLUDE parsers; instream PROC expansion with symbol resolution (`&SYM.`, `&SYM1&SYM2`, SET fallback); DCB backreference, GDG, PDS member, DUMMY, temporary dataset (`&&`) handling; nameless-statement detection for JCLLIB/IF/ELSE/ENDIF/SET. Verified against PDASCO01.JCL (1 step cataloged PROC, job_cond=(0,LT)), PDADDRE1.JCL (7 steps instream PROC, symbols ANNO/TIPO/CATEG resolved), PDCAFIN2.JCL (9 steps, 3 OUTPUT defs, DCB backreference, PDS member DSN, REGION=6M). 36/36 tests pass.
Step 2 is done. Summary of changes to run_llm_documentation.py:

Substep	Change
2.1 Caching	_cache_key(chunk, model) → SHA-256 hash; <stem>.cache.json per file in output dir; cached chunks skip Ollama entirely; second run is near-instant
2.2 Prompt trim	DEFAULT_PROMPT cut from 6 sections (~440 tokens) to 3 — Summary, Business Rules, External Dependencies (~150 tokens); old prompt kept as FULL_PROMPT; --full-prompt flag to opt in
2.3 Structured extraction	_extract_structured() regex post-processor writes <stem>.structured.json alongside each Markdown doc with summary, business_rules, external_calls fields
2.4 Chunk size	MAX_CHUNK_LINES 100 → 200; halves total LLM call count for large programs

**Why:** Step 1b of pre-RAG roadmap — JCL execution context required for cross-artifact RAG queries ("what job runs PDCBVC?", "what datasets does it need?").

---

## 2026-03-14 — Step 1.7: end-to-end regression on PDCBVC.CBL

**File(s):** `out/report/PDCBVC.CBL.report/knowledge_base/` (regenerated, not committed)
**What changed:** Saved pre-change KB as baseline, regenerated with all 1.1–1.6 fixes, diffed all 4 documents. Results: `00_Executive_Summary.md` identical; `01_Logic_Narrative.md` truncations 14→2; `03_Dependencies.yaml` sql_statements 9×SELECT→1, cics 11 raw→10 unique sorted, tables_read unchanged (PDCBVC uses only SELECT FROM DUAL, no JOINs); PERFORM THRU paragraphs correctly show both names.
**Why:** Step 1.7 regression gate — confirms all five defect fixes produce only the expected changes with no regressions.

## 2026-03-14 — Step 1.4–1.6: knowledge_base_builder dependency extraction fixes

**File(s):** `knowledge_base_builder.py`
**What changed:** (1.4) Added `deps['cics'] = sorted(set(...))` dedup in `_generate_dependencies()`. (1.5) Added same dedup for `sql_statements`. Also changed `tables_read`/`tables_updated` dedup to use `sorted(set(...))` for consistent ordering. (1.6) Extended `_extract_tables()` FROM clause from `re.search` to `re.findall` and added `re.findall` for JOIN clauses so multi-table queries capture all referenced tables.
**Why:** Defects from Step 1 of pre-RAG roadmap. CICS and sql_statements were emitting one entry per occurrence rather than unique values. JOIN tables were silently dropped from the dependency map.

## 2026-03-14 — Step 1.1–1.3: knowledge_base_builder quality fixes

**File(s):** `knowledge_base_builder.py`
**What changed:** (1.1) Removed dead `decisions` and `loops` variables from `_calculate_complexity()` — never read, McCabe formula was already correct. (1.2) Raised `_clean_statement()` truncation limit from 100 to 300 chars (and tail from 97/`...` to 297/`...`). (1.3) Updated `_extract_perform_target()` regex to capture `PERFORM X THRU Y` and `PERFORM X THROUGH Y` as a single target string; single-paragraph PERFORM unchanged.
**Why:** Defects from Step 1 of pre-RAG roadmap. Dead code in 1.1 was misleading; truncation in 1.2 cut off SQL/CICS statements mid-statement in the logic narrative; missing THRU in 1.3 emitted only the first paragraph name for range performs, losing the end boundary.

## 2026-03-14 — Step 0: Corpus audit, batch_runner fixes, variable_static_values crash fix

**File(s):** `batch_runner.py`, `smojol_python/src/analysis/variable_static_values.py`, `ongoingPlan.md`
**What changed:** (1) Fixed `batch_runner.py` success check from `visualize_graphs.html` to `knowledge_base/` dir existence; added `--no-graphviz` flag (Graphviz not installed). (2) Removed dead code line 25 in `variable_static_values.py` that raised `IndexError` on programs with no MOVE-literal statements. (3) Ran baseline corpus audit: 28/32 pass, 4 skip (3 parse-failure-silent + 1 timeout). (4) Updated `ongoingPlan.md` statuses (0.1–0.3, 0.5 → done) and appended corpus audit findings to Notes log.
**Why:** Step 0 of pre-RAG roadmap. The HTML check bug caused all files to appear as "not generated" even when analysis succeeded. The `variable_static_values.py` IndexError was a crash-causing dead code bug that caused analyze.py to exit 1 for any program with no MOVE-literal assignments (17/32 test files).

## 2026-03-14 — Expand ongoingPlan.md Step 1b with comprehensive enterprise JCL edge case catalog

**File:** `ongoingPlan.md`
**What changed:** Expanded Step 1b (JCL Parser) with the full IBM JCL parameter catalog to cover all enterprise patterns beyond just the 3 test files. Added: full JOB card parameter list (NOTIFY, USER, TIME, TYPRUN, RESTART, ADDRSPC, ACCT, resource limits, programmer name positional field); full EXEC parameter list (RD=, EVEN/ONLY COND modifiers, REGION=, TIME=, DYNAMNBR=, ACCT=, PROC override vs keyword param disambiguation); full DD parameter list (VOL with SER/REF/multi-volume/RETAIN/PRIVATE, UNIT, LABEL, inline data DD*/DD DATA/DLM=, NULLFILE/DUMMY, concatenated DDs, full DISP values including UNCATLG, DCB sub-params, SPACE with CONTIG/ROUND); expanded JCL column rules (80-column records, cols 73–80 sequence field, embedded quotes doubling, inline data protection from JCL parsing, continuation with blank operands); new substep 1b.12 (Resilience — unknown statement type handling); 25+ synthetic edge case tests added to Test section.
**Why:** User stated the 3 real JCL files are examples only — the actual codebase is large and contains all enterprise JCL patterns. The parser must handle any valid JCL without crashing, even on patterns not seen in the test files.

---

## 2026-03-14 — Update ongoingPlan.md Step 1b with real JCL file findings

**File:** `ongoingPlan.md`
**What changed:** Expanded Step 1b (JCL Parser) based on analysis of the 3 real JCL files in `master-thesis/codefiles/`. Updated "What to parse" table, "What to flag but not fail on" section, JCL column rules, and all substeps 1b.2 through 1b.9. Added new substep 1b.8b (OUTPUT statement parsing). Renamed 1b.6 to cover PROC parameter override resolution as the primary symbolic resolution mechanism. Updated Suggestions and Test sections to reference the real files.
**Why:** 15 patterns found in real JCL files (PDADDRE1.JCL, PDASCO01.JCL, PDCAFIN2.JCL) were not covered by the original Step 1b design. Key gaps: OUTPUT statement type, multi-line EXEC parameter continuation, symbolic params via PROC overrides (not SET), JOB card multi-line with embedded comments, PDS member references in DSN.

---

## 2026-03-14 — Fix missing `self.verbose` in `AnalysisPipeline.__init__`

**File:** `analyze.py`
**What changed:** Added `self.verbose = options.get('verbose', False)` to `AnalysisPipeline.__init__`.
**Why:** Running `analyze.py` on `PDCBVC.CBL` produced `Warning: Comment extraction failed: 'AnalysisPipeline' object has no attribute 'verbose'` at Step 7. The attribute was used at line 315 but never initialized, causing the comment extraction step to silently fail.
