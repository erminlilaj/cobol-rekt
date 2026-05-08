# cobol-rekt RAG Output Improvement Plan

This plan tracks concrete changes needed in `cobol-rekt` so downstream RAG systems can answer analyst questions reliably across many COBOL programs. PDB305.CBL is only the first regression fixture used to reveal gaps; the output contract must support batch programs, CICS online programs, DB2 programs, copybook-heavy systems, mixed legacy code, and future report bundle versions.

## Scope

This plan is broader than one analyzed file. cobol-rekt RAG output should support:

- Many COBOL programs in one corpus.
- CICS and non-CICS programs.
- Batch file/dataset processing.
- DB2 SQL analysis.
- Static and dynamic external calls.
- Copybook resolution, usage, and impact analysis.
- Dead code, unused copy, unreachable code, and commented-out/inactive code.
- Analysis confidence, partial failures, parse degradation, and missing-analysis uncertainty.
- Stable machine-readable metadata plus complete human-readable chunk text.
- Schema evolution without breaking downstream RAG pipelines.

## Problem Summary

The PDB305.CBL RAG bundle contains useful information, but some important facts are either missing, hidden inside large JSON metadata, or not expressed as dedicated chunks. These are examples of general output-contract gaps.

Observed gaps:

- No first-class dead-code or unused-copybook chunk.
- External program calls are listed, but call parameters are not summarized in the high-level call chunk.
- DB2 tables, CICS datasets/files, queues, maps, mapsets, and transaction IDs are not fully separated for question answering.
- Forced/static values exist, but lack enough provenance for "for who?" style questions.
- Commented-out/inactive code is mentioned in the bundle instructions, but not indexed as a curated RAG chunk when detected.

## Research Audit - 2026-05-03

This audit compares the older proposal stack, the current implementation, the generated corpus under `out/report`, and the downstream RAG chat failures observed with PDB305.CBL.

Documents/code reviewed:

- `docs/proposals/0003-rag-readiness.md`
- `docs/proposals/rag_chunk_contract_v1_5.md`
- `docs/proposals/rag_output_improvement_plan.md`
- `chunk_pipeline.py`
- `validate_chunks.py`
- `test_chunk_pipeline.py`
- current generated reports under `out/report`
- downstream RAG chat behavior in `cobol-rag-pipeline`

Current corpus snapshot from local `out/report`:

- Report directories: 487
- Reports with `chunks/chunks_manifest.json`: 475
- Chunk files counted from manifests: 47,890
- Schema versions currently present:
  - `1.3`: 47,439 chunks
  - `1.1`: 371 chunks
  - `1.4`: 27 chunks
  - `1.5`: 52 chunks
  - `1.2`: 1 chunk
- New v1.5 chunk coverage in the existing generated corpus:
  - `external_program_calls`: 1 report
  - `datasets_tables_resources`: 1 report
  - `static_values`: 1 report, split into 2 chunks
  - `cics_operations`: 2 reports
  - `dead_code`: 0 reports
  - `unused_copybooks`: 0 reports
  - `commented_out_code`: 0 indexed chunks
- Supporting artifacts:
  - `copybook_manifest.json`: 446 reports
  - `commented_out_code.json`: 1 report

Interpretation:

- The v1.5 producer code exists, but the corpus is mostly stale. Full answer quality will not be visible until reports are regenerated with the current chunk pipeline.
- The pipeline still has many pre-v1.4 oversized/stale chunks in `out/report`, including a 27,969-character `section_summary` chunk from `NC2184.2.cbl`. This is stale output, not proof that the current splitter is broken.
- `clear_existing_chunks()` is implemented, so fresh regeneration should remove stale split-part files. Full corpus regeneration should still be performed on clean chunks directories and validated.
- The old 0003 findings F1/F2 are implemented in code: invalid CICS targets are filtered in `generate_cics_operations()`, and `cics_command_count` is present in metadata.

## Critical Review - 2026-05-03

This review was added after inspecting the current Python chunk work against the existing Java artifacts and a temporary regenerated sample under `/tmp`. It changes the execution order of the plan.

Findings:

- Current `out/report` still contains zero generated `copybook_mentions`, `copybook_fields`, `comments`, `commented_out_code`, `dead_code`, or `unused_copybooks` chunks. The new producer code has not improved the real downstream RAG index yet.
- The `dead_code` Python implementation is unsafe. A temporary regeneration of one existing report produced false dead-code candidates because it assumed the first JSON `PARAGRAPH` node was the execution entry. Real CFG paragraph order is not guaranteed to match execution entry order.
- Dead-code analysis should not be inferred from paragraph in-degree in Python. Java already resolves `PERFORM ... THRU ...` ranges into procedure targets and exposes richer control-flow metadata; dead/unreachable facts should be produced from that model or from a Java-exported reachability artifact.
- The `copybook_fields` Python regex extractor duplicates weaker parsing. Java already exports parser-built data structures in `data_structures/*-data.json` with recursive field hierarchy, raw declarations, data type, source section, redefinition status, and categories. The RAG chunk layer should package those facts instead of reparsing copybook text.
- Exact per-copybook field ownership is not fully represented in the current `*-data.json` schema. Before finalizing `copybook_fields`, Java should preserve copybook origin/source file/source line per data node, or the chunk should state that per-copybook ownership is uncertain.
- `unused_copybooks` currently reports `Status: produced` when copybooks are present but all field usage is uncertain because copybook files are missing/stubbed. That wording is too strong; it should be `incomplete` until usage was actually measurable.

Immediate decision:

- Do not proceed to Step 7 yet.
- Treat Step 6 as blocked until the dead-code and unused-copybook design is corrected.
- Treat Step 3 as useful prototype work, but not final enough for full corpus regeneration.
- Next work must be a design-fix and sample-regeneration gate, not another new chunk family.

## Heuristic Risk Review - 2026-05-03

This review classifies Python-side inference that can produce false confidence. These items must be fixed or explicitly marked unavailable before downstream RAG sync.

Critical / high findings:

- `copybook_fields` must not label derived PIC/VALUE facts as pure `java_data_structures` facts while Python still extracts `PIC` and `VALUE` from `rawText` with regex. Current Java `*-data.json` gives reliable parser-backed field hierarchy, names, levels, source sections, data types, redefines, and raw declarations; it does not yet expose structured `pictureClause`, `occursCount`, `usage`, byte offsets, or copybook origin.
- `copybook_fields` cannot answer "what fields does copybook X define?" until Java exports field origin. Listing included copybooks next to a flat program field list is dangerous unless the text clearly says the fields are program-level after copybook expansion and are not attributed to any included copybook.
- Raw copybook fallback must not silently run on degraded `*-data.json` sentinel output such as lenient/null fallback trees. If Java data structures are degraded or null, emit `analysis_status: unavailable` or `incomplete`; do not produce authoritative-looking field lists from raw copybook regex parsing.
- Static-value consumer inference uses fuzzy substring matching between variable names and CICS arguments. This can create false consumer relationships, for example a generic `CODE` root matching an unrelated `TRAN-CODE`. Replace with exact match plus narrowly justified prefix/commarea rules, and add negative tests.
- Static-value provenance currently depends on parsing generated `01_Logic_Narrative.md` `Known values:` lines. This is a brittle generated-text parse chain. Prefer `variable_values.json` plus Java/CFG statement provenance when available.
- CICS facts are currently recovered from generated markdown `**CICS:**` lines in `01_Logic_Narrative.md` for several chunk paths. This is brittle; chunks should read CFG/dialect node data or dedicated dependency artifacts directly.
- Paragraph `variables_read` / `variables_modified` metadata is inferred by Python regex over CFG `originalText`. This misses common COBOL constructs and multiple targets. Treat it as heuristic metadata only until Java exports read/write sets.

Immediate blockers before commit or regeneration:

- Rename or change `copybook_fields.field_source` so it does not imply structured Java PIC/VALUE extraction while Python regex is still used on `rawText`.
- Ensure copybook-field text never implies flat program fields belong to every included copybook.
- Disable raw fallback for null/degraded Java data-structure sentinel output unless the chunk clearly says fallback extraction is incomplete.
- Replace fuzzy `_variable_matches_cics_arg()` substring matching or remove consumer facts that depend on it.
- Keep `dead_code` and `unused_copybooks` disabled until Java-backed evidence exists.
- Commit `chunk_pipeline.py` and `validate_chunks.py` together whenever new chunk types are introduced, so producer and validator do not split-brain.

Implementation status matrix:

| Area | Status | Evidence | Remaining gap |
|---|---|---|---|
| v1.5 schema constants | Implemented in code | `CHUNK_SCHEMA_VERSION = "1.5"` and `PIPELINE_VERSION = "1.5"` | Full corpus still mostly schema `1.3` |
| Contract doc | Implemented | `rag_chunk_contract_v1_5.md` exists | Needs next contract revision when adding copybook/comment/dead-code chunks |
| Fresh chunk cleanup | Implemented | `clear_existing_chunks()` called at pipeline start | Need full corpus regeneration proof |
| `external_program_calls` | Partially implemented | CICS LINK/XCTL with PROGRAM/COMMAREA/LENGTH extracted | COBOL `CALL`, dynamic targets, RESP/RESP2, source line numbers missing |
| `datasets_tables_resources` | Partially implemented | DB2/CICS resources grouped for PDB305 | Batch SELECT/FD/DD files, VSAM access modes, inactive resources need broader coverage |
| `static_values` provenance | Heuristic prototype | Categories and paragraph provenance when `Known values:` exists | Markdown parsing and fuzzy CICS matching can false-positive; needs Java/dedicated artifact provenance |
| `cics_operations` | Implemented from 0003 | invalid targets filtered; `cics_command_count` present | Existing corpus not regenerated broadly |
| dead/unused evidence | Blocked | current Python `dead_code` prototype can false-positive on real CFG ordering; `unused_copybooks` status semantics too strong | Redesign around Java reachability/perform metadata and stricter incomplete status |
| comments/commented-out code | Implemented in code, not corpus-proven | `comments` and `commented_out_code` generators exist; corpus still has zero generated chunks of these types | Need controlled sample regeneration and RAG eval |
| copybook resolution chunks | Partially implemented, blocked for exact field ownership | `copybook_mentions` exists; `copybook_fields` can list Java-parsed program fields | Need Java structured PIC/OCCURS/usage/byte-size/copybook-origin export; avoid false per-copybook attribution |
| business summary | Weak | current `program_summary` is technical complexity summary | Need functional/business-purpose summary with uncertainty |
| golden evaluation | Not implemented for new v1.5 questions | manual PDB305 chat tests exist downstream | Need corpus-level golden fixtures |

Current downstream RAG problems traced to producer output:

- "What is the program about?" gets a technical summary because `program_summary` does not yet emit a functional/business purpose.
- "What parameters do you get from copybooks?" cannot be answered because no copybook field/parameter chunk exists.
- "In which lines are copybooks mentioned?" cannot be answered because copybook mention line numbers are not emitted.
- "What comments does this program have?" cannot be answered because comments/commented-out blocks are not emitted as indexed chunks.
- "Is there unused code/copy?" correctly returns uncertainty because no dead-code or unused-copy analysis chunk exists.
- "Forced values, for who?" returns variables and categories, but not full downstream consumer provenance.

Scale risks for a corpus with thousands of COBOL files:

- Mixed schema versions will produce inconsistent retrieval unless full regeneration or schema-aware loaders are enforced.
- Exact identifiers are common and similar across programs; BM25/hybrid indexes must remain per bundle or include program filters to avoid cross-program leakage.
- Copybook-heavy systems will duplicate the same fields and comments across many programs; global duplicate reporting is needed, but write-time deletion is unsafe.
- Batch programs need file/DD/SELECT/FD chunks; CICS-only chunks will not cover the corpus.
- Dynamic calls and dynamic resource names must be represented as unresolved expressions, not dropped.
- Missing copybooks can make parse quality look acceptable while semantic answers are incomplete; copybook coverage must be visible in every summary.
- Regeneration must be idempotent and resumable; stale chunks from older schemas are dangerous.
- Golden evaluation must sample program families, not just PDB305-style CICS/DB2 online programs.

## Design Rules

1. Every common analyst question should have a curated chunk that directly answers it.
2. Chunk text must be human-readable and complete enough for RAG without requiring large metadata.
3. Metadata can contain rich structures for tools, but the chunk text must include the most important facts.
4. Active logic and commented-out/inactive code must never be mixed as the same kind of evidence.
5. Every generated fact should include provenance when possible: paragraph, statement, source line, or analysis phase.
6. No chunk design should depend on a specific program name, domain, or one-off report folder layout.
7. If an analysis is incomplete or unavailable, emit an explicit uncertainty chunk/fact instead of silently omitting it.
8. Chunk schemas should be versioned and documented so RAG tools can adapt safely.

## Phase 0: General RAG Output Contract

Status: Done

Define a versioned RAG output contract for all generated bundles.

Every curated chunk should include:

- complete `text`
- stable `chunk_type`
- stable `chunk_id`
- `program`
- `source_program_path`, when available
- `schema_version`
- `pipeline_version`
- `parse_quality`
- `indexable`
- `thin_chunk`
- `analysis_status`
- provenance fields when available

Required bundle files:

- `manifest.json`
- `chunks/chunks_manifest.json`
- curated chunks as JSON
- optional `chunks/bm25_index.json`
- optional `artifacts/` for large diagnostics
- optional `knowledge_base/` for human report pages

Acceptance checks:

- A downstream RAG tool can index only `chunks/` and answer common questions.
- Important answer facts are present in chunk `text`, not only nested metadata.
- Schema changes increment `schema_version` and are documented.

Progress:

- Added `docs/proposals/rag_chunk_contract_v1_5.md`.
- Bumped chunk and pipeline schema constants to `1.5`.
- Updated `validate_chunks.py` to recognize schema `1.5`.

## Phase 1: External Program Calls With Parameters

Status: Done

Create a first-class chunk:

- `chunk_type`: `external_program_calls`
- `chunk_id`: `<program>:external_program_calls`

Text should include one row per call:

- command: `LINK`, `XCTL`, dynamic call, static call
- COBOL `CALL`, if present
- target kind: `PROGRAM`
- target program
- paragraph
- section, if available
- source statement
- COMMAREA, if present
- LENGTH, if present
- RESP/RESP2, if present
- whether target is literal or dynamic
- unresolved target expression, if dynamic target cannot be resolved

Example text:

```text
External program calls for PDB305.CBL:
- LINK PD0GCODA in LINK-CODA: COMMAREA WPDRGCODA, LENGTH PDRGCODA-LUNGH.
- LINK PD0UTI01 in LINK-PD0UTI01: COMMAREA WPDRUTI01, LENGTH PDRUTI01-LUNG-COMMA.
- LINK PD1AC in LINK-PD1AC: COMMAREA WPD1AC, LENGTH PD1AC-LUNGH.
- LINK PD3SORT in LINK-SELE: COMMAREA WPDRSELE, LENGTH PDRSELE-LUNG-COMMA.
- XCTL PDPRED in XCTL-MAIN.
- LINK TE0CDUMP in ABEND00: COMMAREA WABEND-CODE, LENGTH 4.
```

Structured metadata:

```json
{
  "chunk_type": "external_program_calls",
  "calls": [
    {
      "command": "LINK",
      "target": "PD0GCODA",
      "target_kind": "PROGRAM",
      "paragraph": "LINK-CODA",
      "commarea": "WPDRGCODA",
      "length": "PDRGCODA-LUNGH",
      "target_source": "literal"
    }
  ]
}
```

Acceptance checks:

- The chunk lists all LINK/XCTL program targets.
- The chunk lists COBOL CALL targets for batch/non-CICS programs.
- It does not list maps, queues, transactions, or datasets as external programs.
- It includes COMMAREA/LENGTH where present.
- Dynamic unresolved calls are represented as unresolved, not dropped.

Progress:

- Added initial `external_program_calls` chunk generation from `03_Dependencies.yaml`.
- Added parameter enrichment from active CICS statements in `01_Logic_Narrative.md` for `PROGRAM`, `COMMAREA`, and `LENGTH`.
- Added regression coverage for CICS LINK/XCTL calls with parameters.

## Phase 2: Datasets, Tables, And CICS Resources

Status: In Progress

Create a first-class chunk:

- `chunk_type`: `datasets_tables_resources`
- `chunk_id`: `<program>:datasets_tables_resources`

Text should group:

- DB2 tables read
- DB2 tables updated/inserted/deleted
- CICS datasets/files read
- CICS datasets/files written
- CICS datasets/files browsed
- CICS datasets/files deleted/rewritten
- batch files opened/read/written
- DD names and SELECT/FD names when available
- CICS queues
- CICS maps/mapsets
- CICS transaction IDs

For a CICS program like PDB305.CBL, the chunk should distinguish:

- DB2 table: `DUAL`
- CICS queue: `TWCOB-TS-CODA`
- CICS map: `PDB3051`
- CICS mapset: `PDB305M`, if available from SEND/RECEIVE statements
- transaction ID: `PRED`
- CICS dataset/file references such as `PDKTELR` only if active, not commented-out

Acceptance checks:

- Dataset/table questions can be answered from one chunk.
- Inactive/commented dataset references are marked inactive or excluded from active resources.
- DB2 tables are not mixed with CICS datasets.
- Batch files are represented even when no CICS is present.
- Access mode is captured when available: read, write, update, browse, delete.

Progress:

- Added initial `datasets_tables_resources` chunk generation.
- The chunk separates DB2 tables, SQL operations, CICS files/datasets, queues, maps, mapsets, and transaction IDs.
- Added regression coverage for mixed DB2 and CICS resources.

## Phase 3: Forced And Static Values With Provenance

Status: In Progress

Improve existing `static_values` chunk.

For each value, include:

- variable
- values
- paragraph(s)
- source statement(s)
- category
- target role, if inferable

Suggested categories:

- initialization
- parameter setup
- abend code
- screen/map field
- CICS control value
- separator/literal formatting value
- business constant
- SQL parameter
- file key/setup value
- external-call parameter

Example text:

```text
Forced/static values for PDB305.CBL:
- PDRGCODA-FUNZIONE = '01' in LINK-CODA, category parameter setup, used before LINK PD0GCODA.
- PDRUTI01-FUNZIONE = '04' in MUOVI-DATI-010/PREPARA-MAP-030, category parameter setup, used before LINK PD0UTI01.
- PDRUTI01-FUNZIONE = '20' in COMPATTA-NOME, category parameter setup, used before LINK PD0UTI01.
- WABEND-CODE = 'UT$$' in LINK-PD0UTI01, category abend code.
```

Acceptance checks:

- "Is there any forced value, and for who?" can be answered from this chunk.
- Values are exact COBOL literals and figurative constants.
- Provenance includes paragraph names.
- The chunk works for any program, even if no static values are found; in that case it should explicitly say no static-value analysis results were produced or no values were detected.

Progress:

- Added initial paragraph-level provenance from `Known values:` lines in `01_Logic_Narrative.md`.
- Added coarse categories such as `external-call parameter`, `abend code`, `screen/map field`, and `CICS control value`.
- Added regression coverage for static values with paragraph provenance.

## Phase 4: Dead Code, Unused Code, And Unused Copybooks

Status: Blocked

Create first-class chunks:

- `dead_code`
- `unused_copybooks`
- `commented_out_code`

Dead-code analysis should separate:

- unreachable paragraphs
- paragraphs with no incoming edges
- labels never performed or branched to
- unused variables
- unused copybooks
- commented-out COBOL blocks
- inactive SQL/CICS found inside comments
- code excluded by compiler directives, if detected
- unreachable branches, if control-flow analysis supports them

Important rule:

Missing analysis is not the same as no dead code. If the analysis is unavailable, emit an explicit uncertainty note.

Example text:

```text
Dead-code analysis for PDB305.CBL:
Status: incomplete.
No first-class unreachable paragraph analysis was produced.
Commented-out COBOL blocks were detected in commented_out_code.json.
Unused copybook analysis was not produced.
```

Acceptance checks:

- If analysis is incomplete, the chunk says so.
- RAG can answer "not enough evidence" instead of "no unused code".
- Commented-out code is never reported as active logic.
- Programs with no detected dead code should emit explicit negative evidence only if the analysis actually ran.

## Phase 5: Copybook Resolution And Usage

Status: Partially Implemented, Blocked For Exact Usage/Ownership

Improve copybook chunks with two separate concepts:

- copybooks included by source
- copybooks actually referenced by active logic

Create or improve:

- `copybook_resolution`
- `copybook_usage`

Text should include:

- total copybooks found in source
- resolved copybooks
- stubbed copybooks
- missing copybooks
- copybooks included but not referenced
- copybooks referenced by active statements
- copybooks referenced only in commented/inactive code
- known system copybooks
- copybook impact notes
- search paths used by resolver
- duplicate copybook names or shadowing, if detected

Acceptance checks:

- "How many copybooks are inside?"
- "How many are found/resolved?"
- "Which are stubbed?"
- "Which copybooks are unused?"

## Java Export Requirements

These changes remove the Python heuristic layer for field and usage facts.

Data-structure export should add, where available:

- Done: `pictureClause`
- Done: `usage`
- Done: `occursCount` and `occursDependingOn`
- Done: byte size and byte offset when memory layout is available
- Done: source line/source column/source name when parser token location is available
- Still blocked: copybook/source origin for each field. The current Java data-structure model carries source section and parser token location, but not the originating copybook file for expanded copybook fields.

CFG or dependency export should add, where available:

- paragraph-level `variablesRead`
- paragraph-level `variablesModified`
- structured CICS statements and arguments by paragraph
- static assignment statement provenance by variable
- Java-backed reachability/dead-code facts, or an explicit unavailable status

Python chunk generation should then:

- package Java-exported facts into RAG text
- avoid reparsing generated markdown for primary facts
- avoid regex parsing COBOL `rawText` except as a clearly labeled fallback
- emit uncertainty instead of silently downgrading to weaker evidence

Each question should be answerable from copybook chunks without reading all paragraph chunks.

## Phase 6: Program Architecture And Business Summary

Status: Done

Improve high-level summary chunks so they work across program types.

Create or improve:

- `program_summary`
- `architecture_summary`
- `business_logic_summary`
- `control_flow_summary`

Text should include:

- program type: CICS online, batch, subprogram, utility, mixed, unknown
- main entry/exit behavior
- major sections/paragraph groups
- key external dependencies
- key data inputs/outputs
- main business responsibility, when inferable from comments/names/statements
- limitations and confidence

Acceptance checks:

- "What is the program about?" gets a concise answer from summary chunks.
- If business purpose cannot be inferred, the chunk says so instead of inventing one.
- Batch and CICS programs both get useful summary text.

## Phase 7: RAG Manifest Contract

Status: Done

Document the bundle contract for downstream RAG tools.

Required files:

- `manifest.json`
- `chunks/chunks_manifest.json`
- curated chunks as JSON
- optional `chunks/bm25_index.json`

Each curated chunk should include:

```json
{
  "text": "Human-readable complete chunk text.",
  "metadata": {
    "chunk_type": "external_program_calls",
    "chunk_id": "PDB305.CBL:external_program_calls",
    "program": "PDB305.CBL",
    "indexable": true,
    "thin_chunk": false,
    "schema_version": "1.5",
    "pipeline_version": "1.5",
    "parse_quality": "degraded"
  }
}
```

Metadata can contain richer nested structures, but the `text` field must contain the important facts for RAG.

Acceptance checks:

- RAG tools can index only `chunks/` and answer common analyst questions.
- No required answer depends only on nested metadata.
- The manifest lists supported chunk types and schema version.

## Phase 8: Golden-Question Evaluation

Status: Planned

Add a golden evaluation corpus. PDB305.CBL should be one fixture, not the whole benchmark.

Minimum fixture types:

- CICS online program with DB2.
- Batch file/dataset program.
- Program with copybook failures/stubs.
- Program with no external calls.
- Program with commented-out CICS/SQL.
- Program with dynamic calls or unresolved targets.
- Program with incomplete parse/analysis.

Questions:

- What is the program about?
- Which copybooks are included/resolved/stubbed/unused?
- Which DB tables and datasets are used?
- Which outside programs are called and with which parameters?
- Which forced/static values exist and what are they for?
- Is there unused/dead/commented-out code?
- What is the analysis confidence and what failed?
- Which variables or constants control external calls/resources?

Each expected answer should list:

- required chunk type
- required facts
- forbidden facts
- confidence/limitation notes

Acceptance checks:

- Regenerating a bundle should not regress these golden answers.
- If an analysis is unavailable, the expected output should say "not enough evidence" or "analysis not produced".
- Tests should validate required chunk types, required facts, forbidden facts, and uncertainty wording.

## Capability Audit — 2026-05-03

A structured audit of what analyst questions the current pipeline output can and cannot answer. Based on direct inspection of generated reports under `out/report/` across four representative programs: `BNK1DAC.cbl` (CICS online, full parse), `BNK1CCS.cbl` (CICS online, all copybooks stubbed, degraded), `BANKDATA.cbl` (batch + DB2), `NC1074.2.cbl` (large Italian batch, GOTO-heavy, degraded).

### Chunk types in the current corpus (schema 1.3, widely generated)

| Chunk type | What it contains |
|---|---|
| `program_summary` | Complexity score, node counts, top node types, confidence label, stubbed copybook list. Purely technical — no functional description. |
| `dependencies` | CICS command list (names only), LINK/XCTL target names, DB2 tables read/updated, CALL targets. No CICS map/transaction/dataset/queue details. |
| `paragraph_logic` | Statement sequence with inline CICS/SQL text, calls, heuristic variables_read/modified. For programs with stubbed copybooks this contains `_DIALECT_` tokens and Unicode garbage. |
| `variable_group` | PIC clause, level structure, data type, section, static value list from variable_values.json. No copybook attribution. |
| `business_rules` | 88-level condition names and their controlling variable. Good structural proxy for business rule flags. |
| `section_summary` | Section name, paragraph list, first-level call profile. Thin text. |
| `workflow` | Entry paragraph → direct callee names only, no context. Very thin. |
| `cobol_analysis_health` | Parse mode, coverage %, stubbed copybook names with impact notes. Solid. |
| `sql_operation` | Full SQL statement text per operation (DB2 programs only). |

Chunk types implemented in code but **not yet in corpus** (schema 1.5): `cics_operations`, `external_program_calls`, `static_values`, `datasets_tables_resources`, `copybook_mentions`, `copybook_fields`, `comments`, `commented_out_code`. Only 1–2 report directories each.

### Question coverage map

Technical questions:

| Question | Can answer? | Source | Gap |
|---|---|---|---|
| What is the cyclomatic complexity? | Yes | program_summary | — |
| What CICS commands does it use? | Yes (names only) | dependencies | Arguments, map names, transaction IDs, datasets not extracted |
| What DB2 tables does it read/write? | Yes | dependencies | — |
| What programs does it call via LINK/XCTL? | Yes | dependencies | COMMAREA/LENGTH only in raw paragraph text |
| What 88-level conditions exist? | Yes | business_rules | — |
| What variables are declared? Types? | Yes | variable_group | No copybook attribution |
| What parse quality was achieved? | Yes | cobol_analysis_health | — |
| Which copybooks were stubbed? | Yes | cobol_analysis_health | — |
| What does paragraph X do? | Yes (if good parse) | paragraph_logic | Degraded programs have unreadable garbage text |
| What is the entry point / main flow? | Partial | workflow + section_summary | Workflow text is bare callee list only |
| What external call parameters (COMMAREA/LENGTH) are used? | Partial | paragraph_logic inline text | Not extracted to a dedicated field |
| What static/forced values are set? | Partial | variable_group metadata | No consumer or context in text |
| What CICS maps/screens does it use? | No | Buried in paragraph_logic raw text | MAP/MAPSET literal arguments not extracted |
| What CICS transaction IDs are involved? | No | Buried in paragraph_logic raw text | RETURN TRANSID literal not extracted |
| What CICS datasets/files does it access? | No | Buried in paragraph_logic raw text | Not extracted to any dedicated field |
| What copybook fields/parameters exist? | No | Not in corpus | copybook_fields not generated |
| Are there REDEFINES structures? | Partial | variable_group text per variable | Count not in any chunk text |
| Is there commented-out code? | No | Not in corpus | commented_out_code not generated |
| What COBOL comments are there? | No | Not in corpus | comments not generated |

Business questions:

| Question | Can answer? | Gap |
|---|---|---|
| What is the business purpose? | No | program_summary is purely technical. No functional summary exists. |
| What business rules does it implement? | Partial | 88-level condition names are a proxy. Real rules are in comments and paragraph names. |
| What business event / transaction triggers it? | No | Transaction ID buried in paragraph text, not extracted. |
| What data does it maintain? | Partial | DB2 tables yes. CICS files/datasets no. |
| What other systems does it interact with? | Partial | External program names yes. CICS resources no. |
| What error handling does it do? | Partial | Visible in ABEND paragraph chunks if RAG retrieves them. No aggregated summary. |

Cross-program questions:

| Question | Can answer? | Gap |
|---|---|---|
| Which programs call this program? | No (in RAG) | called_by data is in cross_program_calls.json and in program_summary metadata but NOT in chunk text. RAG cannot retrieve it. |
| Which programs does this call? | Yes | dependencies chunk text |
| Which DB2 tables are used across the corpus? | No (in RAG) | corpus_index.json has inverted table→programs map but is not in any chunk |
| Which programs share copybooks? | No | Not produced |

### Root causes of the gaps

1. **CICS arguments are raw text, not extracted fields.** MAP, MAPSET, TRANSID, DATASET, QUEUE literal arguments are in the Java-produced `originalText` of CFG EXEC_CICS nodes. They are reproduced verbatim in `paragraph_logic` chunk text, but are not indexed as dedicated fields. The `cics_operations` and `datasets_tables_resources` schema 1.5 chunks address this — but the corpus is not regenerated.

2. **`called_by` is in metadata but not in chunk text.** `cross_program_calls.json` has caller data for 77 programs. This data is sometimes already in `program_summary` metadata. The `text` field (what RAG indexes) does not mention it. A one-line change to the summary text generator fixes this.

3. **No functional summary.** `program_summary` text is entirely structural. For programs with no comments there is no route to a business-purpose answer.

4. **Schema 1.5 chunks are not in the corpus.** The new chunk generators exist in code but the corpus has never been regenerated with them.

### Concrete improvements — safe and clean

All five items below require no new heuristics, no regex over generated markdown, and no Java changes.

**I1 — Add `called_by` to `program_summary` text.**
Data is already in `cross_program_calls.json`. The `program_summary` generator reads a metadata dict; add one conditional: if `called_by` is non-empty, append `"Called by: X, Y, Z."` to the text. Zero new parsing.

**I2 — Add structural facts line to `program_summary` text.**
`cobol_structure.json` already exists in every report. Read `len(paragraph_profiles)`, `len(conditions_88)`, `len(redefines)`, section count. Append one line: `"Paragraphs: N in M sections. 88-level conditions: X. REDEFINES relationships: Y."` No new parsing.

**I3 — Extract CICS literal arguments (MAP, MAPSET, TRANSID, DATASET, QUEUE, PROGRAM) into `dependencies` chunk text.**
Source: `cfg-*.json` `originalText` field of EXEC_CICS nodes. Regex over the Java-produced structured JSON (not over generated markdown). Pattern: `MAP\('([^']+)'\)`, `MAPSET\('([^']+)'\)`, `TRANSID\('([^']+)'\)`, `DATASET\('([^']+)'\)`, `QUEUE\('([^']+)'\)`, `PROGRAM\('([^']+)'\)`. Collect unique literals, add to dependencies text as "CICS resources: MAP BNK1DA, MAPSET BNK1DAM, TRANSID OMEN." This answers questions 6, 7, 8 in a single small addition.

**I4 — Fix B1–B4 blockers and regenerate corpus.**
Described in Pre-6A section. After fixes: commit, run 20-program sample, validate, then full corpus. This activates all schema 1.5 chunks across the entire corpus.

**I5 — Enrich `workflow` chunk text with CICS commands per callee.**
Currently: `"A010 orchestrates: POPULATE-TIME-DATE, ABEND-THIS-TASK"`. After: for each callee, append the CICS commands that paragraph uses (from `paragraph_logic` metadata `cics_commands` field). No new analysis — the data is already in chunk metadata.

### What NOT to add

- Business/functional summary via LLM inference — non-deterministic, unverifiable.
- Dead code analysis — correctly blocked.
- Copybook field → paragraph cross-reference — requires Java export of variablesRead/variablesModified.
- Per-SQL-table line numbers — marginal gain for significant complexity.
- Any generator that parses generated Markdown as its primary data source.

## Detailed Next Execution Plan

This section is the concrete implementation sequence from the current state. It assumes the codebase stays Python-first for RAG output improvements and does not require a Java parser upgrade unless explicitly stated.

### Step 0: Freeze A Baseline Before More Chunk Changes

Status: Done

Goal: make sure future changes can be measured across the existing corpus.

Tasks:

- Run `corpus_baseline.py` against `out/report` before changing chunk semantics.
- Store a baseline JSON outside generated report directories.
- Record:
  - report count
  - manifest count
  - chunk type counts
  - schema version counts
  - parse coverage distribution
  - copybook coverage distribution
  - reports missing `copybook_manifest.json`
  - reports missing `chunks_manifest.json`
  - reports with stale schema versions
- Add a short "baseline snapshot" section to this plan after the run.

Commands:

```bash
python3 corpus_baseline.py --report-dir out/report --output baselines/rag_output_before_gap_closure.json
python3 validate_chunks.py --report-dir out/report --max-tokens 512
```

Acceptance checks:

- Done: baseline file exists at `baselines/rag_output_before_gap_closure.json`.
- Done: the baseline run did not mutate reports.
- Done: known stale schema/index/token-limit state is documented below instead of confused with current-code failure.

Baseline snapshot - 2026-05-03:

- Command run: `python3 corpus_baseline.py --report-dir out/report --output baselines/rag_output_before_gap_closure.json`
- Result: succeeded, writing `baselines/rag_output_before_gap_closure.json`.
- Corpus size: 487 report directories, 434 reports with CFG data, 475 reports with chunks.
- Aggregate parse errors currently recorded by reports: 52,528.
- Dialect/feature coverage markers: 108 programs with `EVALUATE`, 4 with `EXEC DLI`, 13 with `COPY REPLACING`, 3 with DLI/dialect overlap.
- Chunk volume by main type: `paragraph_logic` 31,339; `variable_group` 9,499; `workflow` 3,963; `section_summary` 1,001; `dependencies` 430; `program_summary` 430; `cobol_analysis_health` 434; `sql_operation` 215; JCL chunk types 480 combined; `business_rules` 52.
- New v1.5 chunk coverage in the current generated corpus is still tiny: `cics_operations` 2, `external_program_calls` 1, `static_values` 2, `datasets_tables_resources` 1.
- Validation command run: `python3 validate_chunks.py --report-dir out/report --max-tokens 512`
- Validation result: failed against the existing corpus, as expected for the pre-fix baseline.
- Validation summary: 47,890 chunks checked; 0 required-field errors; 0 hash mismatches; 8,082 chunks over 512 tokens; max chunk size 14,741 tokens; 432 unknown chunk types; 372 schema warnings; 22 dangling cross-references; 37 index consistency errors.
- Interpretation: this confirms the next safe work is not broad feature expansion yet; first make regeneration/idempotency and chunk-size/schema gates reliable enough for thousands of COBOL files.

### Step 1: Regeneration Safety Gate

Status: Done

Goal: make full-corpus regeneration safe before adding more chunk types.

Tasks:

- Done: verified `run_pipeline()` calls `clear_existing_chunks()` before writing current chunks.
- Done: added `test_run_pipeline_removes_stale_chunks_before_regeneration` to prove stale old-schema chunk files and stale split parts disappear on rerun while non-JSON notes are left alone.
- Done: added `audit_chunk_regeneration.py`, a read-only helper for "which reports need regeneration" based on manifest schema, chunk metadata schema, missing manifests, missing chunks dirs, unreadable JSON, and manifest/chunk file mismatches.
- Done: documented that full regeneration should only happen after this read-only audit and should use `run_pipeline()` cleanup, not manual partial overwrites.

Acceptance checks:

- Done: running `run_pipeline()` on a report with stale schema `1.3` chunk JSON removes obsolete chunk files before writing new chunks.
- Done: regenerated chunk JSON files in the test contain only the current `CHUNK_SCHEMA_VERSION`.
- Done: `bm25_index.json` and `chunks_manifest.json` are regenerated after cleanup in the test path.
- Done: the real corpus can be audited before mass regeneration with `python3 audit_chunk_regeneration.py --report-dir out/report --limit 50`.

Verification - 2026-05-03:

- Command: `python3 test_chunk_pipeline.py`
- Result: passed, 23 tests run, 2 skipped.
- Scope: unit/regression safety only; this did not mutate the real `out/report` corpus.

Additional verification - 2026-05-03:

- Command: `python3 -m unittest test_audit_chunk_regeneration test_chunk_pipeline`
- Result: passed, 25 tests run, 2 skipped.
- Command: `python3 audit_chunk_regeneration.py --report-dir out/report --limit 10`
- Result: read-only audit completed; 487 reports checked, 486 need regeneration.
- Current regeneration reasons: 474 reports with stale manifest schema, 523 stale chunk-schema groups, 12 missing chunks directories, 12 missing chunk manifests.
- Interpretation: Step 1 safety gates are in place. The next implementation step can start `copybook_mentions`, but a real full-corpus regeneration should be treated as a separate controlled operation because almost all current generated reports are stale.

### Step 2: `copybook_mentions` Chunk With Source Lines

Status: Done

Goal: answer "in which lines are copybooks mentioned?"

New chunk:

- `chunk_type`: `copybook_mentions`
- `chunk_id`: `<program>:copybook_mentions`

Text should include:

```text
Copybook mentions for PDB305.CBL:
- COPY PDRTELR at source line 12, resolved: yes, path: copybooks/PDRTELR.cpy.
- COPY SQLCA at source line 48, resolved: no/stubbed, reason: missing or generated stub.
```

Metadata should include:

```json
{
  "chunk_type": "copybook_mentions",
  "mentions": [
    {
      "copybook": "PDRTELR",
      "source_line": 12,
      "statement": "COPY PDRTELR.",
      "resolved": true,
      "stubbed": false,
      "path": "..."
    }
  ],
  "mention_count": 15
}
```

Implementation notes:

- Done: implemented `generate_copybook_mentions()` in `chunk_pipeline.py`.
- Done: wired `copybook_mentions` into `run_pipeline()` after `dependencies`.
- Done: registered `copybook_mentions` as a valid chunk type in `validate_chunks.py`.
- Done: line-safe splitting treats `copybook_mentions` like the other structured fact chunks.
- Done: uses `cobol_structure.json.copy_statements` as the primary source for 1-based source line numbers.
- Done: cross-checks `copybook_manifest.json` for resolved/stubbed status and copybook file names.
- Done: reconstructs the COPY statement when the original source statement text is unavailable in the report.
- Done: emits an explicit no-mentions chunk when no COPY statements are present.
- Limitation: current reports do not preserve the original source file path or copied source text, so v1 uses the structured COPY statement data rather than exact source text. Add source-path/source-line preservation upstream later if exact statement fidelity becomes mandatory.
- Guardrail: this chunk reports mention/resolution facts only; it does not infer unused copybooks or dead code.

Tests:

- Done: simple `COPY FOO.` line emits `source_line`.
- Done: `COPY FOO REPLACING ==A== BY ==B==.` is captured.
- Done: stubbed copybook status is copied from manifest.
- Done: a program with no copybook mentions emits an explicit no-mentions chunk.

Acceptance checks:

- Done at producer level: the generated chunk text contains copybook names, COPY statements, source lines, resolved/stubbed status, and file names where available.
- Done at producer level: the answer does not require paragraph chunks.
- Partial: multiple mentions are not collapsed, but true same-name/different-path provenance needs upstream manifest paths because current `copybook_manifest.json` only stores file names.

Verification - 2026-05-03:

- Command: `python3 -m unittest test_chunk_pipeline test_audit_chunk_regeneration`
- Result: passed, 27 tests run, 2 skipped.
- Scope: fixture/unit coverage only; real `out/report` was not regenerated.

### Step 3: `copybook_fields` / Copybook Parameters Chunk

Status: Blocked For Exact Copybook Field Answers

Goal: answer "what parameters/fields do you get from copybooks?"

New chunk:

- `chunk_type`: `copybook_fields`
- `chunk_id`: `<program>:copybook_fields`

Text should group by copybook:

```text
Copybook fields for PDB305.CBL:
- PDRGCODA: PDRGCODA-FUNZIONE, PDRGCODA-KOST, PDRGCODA-LUNGH, ...
- PDRUTI01: PDRUTI01-FUNZIONE, PDRUTI01-RETURN, PDRUTI01-LUNG-COMMA, ...
```

Metadata should include:

```json
{
  "copybooks": [
    {
      "copybook": "PDRGCODA",
      "resolved": true,
      "fields": [
        {"name": "PDRGCODA-FUNZIONE", "level": "05", "picture": "X(02)", "line": 10}
      ]
    }
  ]
}
```

Implementation notes:

- Done: implemented `generate_copybook_fields()` in `chunk_pipeline.py`.
- Done: wired `copybook_fields` into `run_pipeline()` after `copybook_mentions`.
- Done: registered `copybook_fields` as a valid COBOL chunk type in `validate_chunks.py`.
- Done: line-safe splitting treats `copybook_fields` like the other structured fact chunks.
- Done: added report-local `copybooks/` snapshot support in `analyze.py` for future analyses.
- Done: `copybook_manifest.json` now records relative `path` values such as `copybooks/PDRGCODA.cpy` when future analyses preserve copybooks.
- Done: `knowledge-base_rag/artifacts/copybooks/` is populated when report-local copybooks exist.
- Done: conservative extractor captures:
  - level numbers `01`-`49`, `66`, `77`, `88`
  - field names
  - `PIC`/`PICTURE`
  - `VALUE` / `VALUES`
  - `REDEFINES`
  - line number inside copybook
- Done: stubbed and missing copybook files produce explicit limitations instead of invented fields.
- Guardrail: v1 does not try to fully parse every COBOL data-description clause. It extracts useful field facts and stays honest when evidence is unavailable.
- Later: cross-reference fields to paragraph usage when variable usage data is reliable.

Critical review:

- The current implementation reparses copybook text in Python with regex. This is weaker than the Java ANTLR/data-structure export and creates two parsing paths for the same COBOL facts.
- Existing Java `data_structures/*-data.json` already contains recursive hierarchy, `rawText`, `dataType`, `sourceSection`, redefinition flags, and categories. This should become the primary source for field chunks.
- Current `*-data.json` does not clearly preserve copybook origin for every field. If per-copybook ownership is required, extend the Java export first with `source_file`, `source_line`, and `copybook`/origin metadata.
- Fixed after review: current Java `*-data.json` export now exposes structured `pictureClause`, `usage`, `occursCount`, `occursDependingOn`, `byteSize`, `byteOffset`, `sourceLine`, `sourceColumn`, and `sourceName` when available.
- A flat Java data-structure field list is a program-level data namespace after copybook expansion. It must not be presented as the fields of each included copybook.
- If `*-data.json` is a degraded/null fallback tree, raw copybook fallback must be treated as incomplete/unavailable and must not create authoritative-looking copybook-field facts.
- Python `copybook_fields` no longer parses Java `rawText` for `PIC` / `VALUE`; it renders only structured fields exported by Java. The raw copybook parser remains as an explicitly labeled fallback only when Java data structures are absent and not degraded.
- Remaining blocker: exact field-to-copybook ownership still requires Java/source-map support for copybook origin.

Redesign tasks:

- Use Java data-structure output as the primary source for hierarchy, field names, levels, data type, source section, and redefines.
- Done: add structured Java exports for `pictureClause`, `occursCount`, `occursDependingOn`, `usage`, byte size/offset, and source token location when available.
- Done: Python uses structured Java fields and labels the Java path as `field_source: java_structured_fields`.
- Until Java exports field origin, emit program-level "fields after copybook expansion" with explicit uncertainty, not per-copybook field ownership.
- Disable raw copybook fallback for degraded/null Java data-structure sentinel outputs, or emit only an incomplete/unavailable status.
- Keep `_extract_copybook_fields()` only as a named fallback for diagnostics, not as the default answer path for RAG.

Tests:

- Done: extracts basic fields with level and PIC.
- Done: extracts 88 condition names.
- Done: preserves line numbers.
- Done: stubbed copybook reports no real fields and a limitation.
- Done: missing report-local copybook file reports a limitation.
- Done: large copybook-field chunks split line-safely under token limit.

Acceptance checks:

- Blocked: exact "fields by copybook" requires Java field-origin metadata.
- Producer may emit program-level Java-parsed fields after copybook expansion, but must explicitly state that copybook ownership is unavailable.
- Resolved fields must be separated from stubbed/missing copybook limitations without implying ownership that is not present in artifacts.
- Partial for existing corpus: old reports do not contain report-local `copybooks/`, so they will need regeneration before this chunk contains real field lists.
- Blocked for corpus gate: field extraction must be redesigned around Java `*-data.json` or Java-origin metadata before broad regeneration.
- Done for structured field facts: Java exports structured field details and Python consumes them without regexing Java `rawText`.
- Still blocked for exact per-copybook grouping: Java does not yet export field origin/copybook ownership.

Verification - 2026-05-03:

- Command: `python3 -m unittest test_chunk_pipeline test_audit_chunk_regeneration`
- Result: passed, 30 tests run, 2 skipped.
- Command: `PYTHONPYCACHEPREFIX=/tmp/cobol-rekt-pycache python3 -m py_compile analyze.py chunk_pipeline.py validate_chunks.py audit_chunk_regeneration.py test_chunk_pipeline.py test_audit_chunk_regeneration.py`
- Result: passed.
- Scope: fixture/unit coverage only; real `out/report` was not regenerated.

Additional verification - 2026-05-03:

- Command: `mvn -pl smojol-toolkit test -Dtest=WriteDataStructuresTaskRegressionTest -Dsurefire.failIfNoSpecifiedTests=false`
- Result: passed, 2 tests run.
- Command: `python3 -m unittest test_chunk_pipeline test_audit_chunk_regeneration`
- Result: passed, 46 tests run, 2 skipped.
- Command: `PYTHONPYCACHEPREFIX=/tmp/cobol-rekt-pycache python3 -m py_compile chunk_pipeline.py validate_chunks.py test_chunk_pipeline.py`
- Result: passed.
- Generated test artifact confirmed `CUSTOMER-ID` includes `pictureClause: 9(5)`, `usage: COMP-3`, `byteSize`, `byteOffset`, and source location; `ITEM-TABLE` includes `occursCount: 3` and `occursDependingOn: ITEM-COUNT`.

### Step 4: Static Value Consumer Provenance

Status: Implemented Prototype, Needs Hardening

Goal: answer "forced value, and for who?" with consumers, not just categories.

Current state:

- `static_values` has variable/value/category.
- Paragraph provenance exists only when `Known values:` lines are present.
- Consumer role is inferred only roughly by variable name/category.
- Step 4 adds first-pass consumer evidence to the existing `static_values` chunk when available.

Tasks:

- Done: for each static assignment, preserve paragraph provenance when `Known values:` lines identify it.
- Done: detect same-paragraph CICS consumers when report narrative contains active `EXEC CICS` evidence.
- Done: identify consumer roles for:
  - COMMAREA
  - LENGTH
  - TRANSID
  - MAP/MAPSET screen fields
  - QUEUE/QNAME
  - FILE/DATASET
  - abend/error handling
- Problem: current variable-to-CICS-argument matching is still too fuzzy and can false-positive through substring/root matching. Replace with exact matching plus narrowly justified copybook/commarea rules and negative tests.
- Done: add structured `consumers` metadata to each `static_values` entry.
- Done: render a `Consumer:` phrase in the chunk text.
- Done: missing consumer evidence is represented as `Consumer: unknown`.
- Limitation: source line and exact assignment statement are still unavailable unless upstream artifacts preserve them. This step does not invent them.
- Limitation: "nearest following" statement is approximated by same-paragraph active CICS evidence because current artifacts do not preserve statement ordering with source line numbers.
- Limitation: paragraph provenance is currently recovered from generated `01_Logic_Narrative.md` `Known values:` lines. This should move to `variable_values.json` plus statement/paragraph provenance from Java or a dedicated artifact.
- Limitation: same-paragraph CICS evidence is currently parsed from generated markdown `**CICS:**` lines. This should read CFG/dialect nodes or structured dependency artifacts directly.
- Add text like:

```text
- PDRGCODA-FUNZIONE = '01' in LINK-CODA; used before LINK PD0GCODA as call parameter.
- WABEND-CODE = 'UT$$' in LINK-PD0UTI01; used by ABEND00/TE0CDUMP handling.
```

Tests:

- Done: assignment evidence before `EXEC CICS LINK` identifies an external-call COMMAREA consumer.
- Done: abend variable in `COMMAREA(WABEND-CODE)` identifies the TE0CDUMP consumer.
- Done: missing consumer is represented as `Consumer: unknown`, not invented.
- Partial: screen/map field consumer logic exists for same-paragraph `SEND`/`RECEIVE`, but needs a dedicated fixture test when Step 5/next test pass expands comment/map evidence.

Acceptance checks:

- Done at producer level: `static_values` text and metadata now include paragraph and consumer role when same-paragraph CICS evidence exists.
- Blocked for corpus gate: consumer facts must not use fuzzy substring matching.
- Blocked for corpus gate: generated markdown should not be the only source for CICS consumer evidence.
- Partial for existing corpus: old generated chunks must be regenerated before downstream RAG sees this richer text.

Verification - 2026-05-03:

- Command: `python3 -m unittest test_chunk_pipeline test_audit_chunk_regeneration`
- Result: passed, 32 tests run, 2 skipped.
- Command: `PYTHONPYCACHEPREFIX=/tmp/cobol-rekt-pycache python3 -m py_compile analyze.py chunk_pipeline.py validate_chunks.py audit_chunk_regeneration.py test_chunk_pipeline.py test_audit_chunk_regeneration.py`
- Result: passed.
- Scope: fixture/unit coverage only; real `out/report` was not regenerated.

### Step 5: `comments` And `commented_out_code` Chunks

Status: Done

Goal: answer comments and inactive-code questions without hallucination.

New or improved chunks:

- `comments`
- `commented_out_code`

Text should separate:

- ordinary source comments
- commented-out COBOL statements
- commented-out CICS/SQL/datasets/calls
- inactive compiler-directive regions, if detectable

Important rule:

Commented-out code must never be emitted as active dependencies/resources.

Implementation notes:

- Done: added `comments` chunk generation from `comments.json`.
- Done: added `commented_out_code` chunk generation from `commented_out_code.json`.
- Done: wired both chunks into `run_pipeline()` for COBOL reports.
- Done: registered both chunk types in `validate_chunks.py`.
- Done: line-safe splitting treats both chunks as structured evidence chunks.
- Done: comments chunks emit explicit status:
  - `produced` with comment evidence
  - `produced` with no ordinary comments detected
  - `not_produced` when `comments.json` is missing
- Done: commented-out-code chunks emit explicit status:
  - `produced` with inactive evidence
  - `produced` with no inactive code detected
  - `not_produced` when `commented_out_code.json` is missing
- Done: inactive blocks are classified conservatively as:
  - commented-out CICS
  - commented-out SQL
  - commented-out DLI/IMS
  - commented-out call/transfer
  - commented-out COPY
  - commented-out file/dataset
- Done: chunk text says inactive/commented-out evidence explicitly, so downstream RAG should not report it as active logic.
- Existing generic source scanner support:
  - fixed format column 7 `*` or `/`
  - free-form comment markers if supported
  - contiguous comment block ranges
- Limitation: existing `comments.json` stores ordinary prose comments mostly as text grouped by paragraph. Line ranges are included in the chunk only when the input artifact contains line numbers. `commented_out_code.json` already preserves block line ranges.
- Guardrail: inactive chunks are evidence for inactive/commented code only; active dependency/resource chunks must continue to use active-analysis sources.

Tests:

- Done: ordinary comments produce `comments`.
- Done: no ordinary comments emits explicit no-comment evidence when scanner output exists.
- Done: missing comment scanner output emits `Status: not produced`.
- Done: commented-out `EXEC CICS LINK`/`DATASET` evidence appears in `commented_out_code` with inactive categories.
- Done: commented-out SQL table appears as `commented-out SQL`.
- Done: no commented-out code emits explicit no-inactive-code evidence when scanner output exists.

Acceptance checks:

- Done at producer level: RAG can retrieve one `comments` chunk for "what comments does this program have?"
- Done at producer level: RAG can retrieve one `commented_out_code` chunk for "is there commented-out code?"
- Done at producer level: inactive/commented evidence is separated from active resource chunks.
- Partial for existing corpus: old generated reports must be regenerated before downstream RAG sees these chunks broadly.

Verification - 2026-05-03:

- Command: `python3 -m unittest test_chunk_pipeline`
- Result: passed, 36 tests run, 2 skipped.
- Command: `PYTHONPYCACHEPREFIX=/tmp/cobol-rekt-pycache python3 -m py_compile chunk_pipeline.py validate_chunks.py test_chunk_pipeline.py`
- Result: passed.
- Scope: fixture/unit coverage only; real `out/report` was not regenerated.

### Step 6: `dead_code` And `unused_copybooks`

Status: Blocked / Prototype Unsafe

Goal: answer unused/dead code questions with explicit evidence.

New chunks:

- `dead_code`
- `unused_copybooks`

Minimum v1 analysis:

- `dead_code`:
  - analysis status: produced/incomplete/not produced
  - paragraphs with zero incoming active CFG edges, excluding entry points and known dispatch targets
  - paragraphs never called/performed/branched to, if control-flow data supports it
  - unreachable branch facts only when reliable
- `unused_copybooks`:
  - included copybooks
  - referenced copybook fields
  - copybooks with no active field references
  - copybooks only referenced in comments/inactive blocks
  - uncertainty when usage cannot be measured because copybook is missing/stubbed

Important rule:

If analysis cannot run, emit uncertainty:

```text
Dead-code analysis for PROGRAM.CBL:
Status: not produced.
The bundle does not contain enough evidence to determine whether unused code exists.
```

Tests:

- Synthetic uncalled paragraph is reported.
- Entry paragraph is not falsely reported dead.
- Missing CFG emits `Status: not produced`.
- Copybook included but no fields referenced is reported as unused only when field extraction ran.
- Stubbed copybook produces uncertainty, not a false unused/used classification.

Acceptance checks:

- RAG can answer unused/dead-code questions without relying on normal chunks.
- "No unused code detected" appears only when analysis actually ran and found none.

Historical prototype finding:

- Removed/disabled: an earlier Python `generate_dead_code()` prototype was unsafe and must not be used as a basis for downstream RAG.
- Removed/disabled: an earlier Python `generate_unused_copybooks()` prototype was unsafe/incomplete and must not be used as a basis for downstream RAG.
- Removed/disabled: `dead_code` and `unused_copybooks` are no longer wired into `run_pipeline()` for positive evidence generation.
- Removed/disabled: `dead_code` and `unused_copybooks` are not currently registered as valid produced chunk types in `validate_chunks.py`.
- Removed/disabled: synthetic tests that asserted the unsafe prototype behavior were removed.
- Problem: `dead_code` can false-positive on real CFG output because it assumes JSON paragraph order implies execution entry and still relies on Python graph heuristics.
- Problem: `unused_copybooks` can say `Status: produced` when all copybooks are uncertain because fields are missing/stubbed.
- Problem: synthetic tests passed but did not cover real CFG ordering, `PERFORM THRU`, section-to-paragraph nesting, or regenerated sample behavior.

Required redesign before enabling:

- Dead code:
  - Use Java-exported reachability or instruction-level control-flow facts, not Python paragraph in-degree.
  - Consume Java `perform_targets`, `perform_start`, `perform_end`, and `perform_through` metadata for `PERFORM THRU`.
  - Treat unknown entry points, dispatcher patterns, and incomplete CFG as `Status: incomplete`, not as dead-code evidence.
  - Emit "No dead code detected" only when Java reachability analysis ran and found no unreachable procedure nodes.
- Unused copybooks:
  - Use redesigned `copybook_fields` from Java data structures/origin metadata.
  - Set `Status: incomplete` when field extraction or active usage measurement is unavailable for any included copybook.
  - Emit "No unused copybook candidates detected" only when every included copybook has measurable fields and active usage evidence.

Temporary safety decision:

- Done as safety fix: disabled generation of `dead_code` and `unused_copybooks` from `run_pipeline()` until the redesign is implemented.
- Done as safety fix: removed the unsafe prototype chunk types from validation registration and removed the synthetic tests that asserted unsafe behavior.
- Before any sample/full corpus regeneration for downstream RAG, keep these chunks disabled or make them emit only `Status: not produced` until the redesign is implemented.

Verification:

- Passed: `PYTHONPYCACHEPREFIX=/tmp/cobol-rekt-pycache python3 -m py_compile chunk_pipeline.py validate_chunks.py test_chunk_pipeline.py comment_extractor.py test_comment_extractor.py test_audit_chunk_regeneration.py`
- Passed: `PYTHONPYCACHEPREFIX=/tmp/cobol-rekt-pycache python3 -m unittest test_comment_extractor test_chunk_pipeline test_audit_chunk_regeneration`
- Review finding: test pass is insufficient; temporary regeneration of an existing report showed false dead-code candidates. This step is not accepted.
- Safety verification: temporary regeneration after disabling produced no `dead_code` or `unused_copybooks` chunks.

### Pre-6A Blocker Fixes

Status: Done (2026-05-03)

Goal: fix the four confirmed code correctness blockers identified in the 2026-05-03 critical review before Step 6A sample regeneration begins. These fixes are prerequisites for the Step 6A acceptance checks at lines `copybook_fields.field_source`, null-sentinel guard, fuzzy matching, and split-brain commit.

Background: the critical review inspected `chunk_pipeline.py`, `validate_chunks.py`, `test_chunk_pipeline.py`, Java `SerialisableCobolDataStructure.java`, and generated artifacts under `out/report`. Four issues were confirmed in committed code that will produce misleading metadata or false facts in any regenerated corpus.

#### B1 — Misleading `field_source: "java_data_structures"` label

File: `chunk_pipeline.py`, line 1205 and verbose print at line 1220.

Problem: `generate_copybook_fields()` labels extracted field data as `field_source: "java_data_structures"` but `_load_java_data_structure_fields()` at lines 1252-1253 immediately calls `_extract_copybook_picture(raw_text)` and `_extract_copybook_value(raw_text)` — Python regex over `rawText` — on every field returned from Java. Confirmed by inspecting `SerialisableCobolDataStructure.java`: the Java export does not include structured `pictureClause`, `occursCount`, `usage`, `byteSize`, or `offset`; only `rawText`, `dataType`, `sourceSection`, redefinition flags, and categories. So `picture` and `value` in every `copybook_fields` chunk are regex-derived from `rawText`, not structured Java output.

Fix: rename `field_source` value from `"java_data_structures"` to `"java_rawtext_regex"`. Update the verbose print at line 1220 to match. No logic changes.

#### B2 — Null/degraded Java data-structure sentinel silently falls through to raw copybook parser

File: `chunk_pipeline.py`, `_load_java_data_structure_fields()` starting at line 1226.

Problem: when the Java pipeline fails in lenient mode and falls back to `NullDataStructure`, `*-data.json` is written as `{"name": "NULL[LENIENT_FALLBACK]", "levelNumber": -99, "children": []}`. Confirmed on `PDB305.CBL-data.json`. The current function checks `isinstance(data, dict)` at line 1234 but not the sentinel value. It then walks `children` (empty array), returns `[]`, and `generate_copybook_fields()` continues to the raw copybook fallback path — producing an authoritative-looking field list from Python regex on copybook files, with no indication in the chunk that data structures were degraded.

Fix: after the `isinstance(data, dict)` guard, add a sentinel check: if `data.get("levelNumber") == -99` or `data.get("name", "").startswith("NULL[")`, return `None` instead of `[]` to signal degraded state. In `generate_copybook_fields()`, handle the `None` return by setting `analysis_status: "unavailable"` and emitting a degradation note in the chunk text instead of proceeding to raw copybook fallback.

#### B3 — Fuzzy substring matching in `_variable_matches_cics_arg()` produces false consumer relationships

File: `chunk_pipeline.py`, `_variable_matches_cics_arg()` at line 1931.

Problem: line 1936 uses `var_u in arg_u or arg_u in var_u` substring tests. Confirmed false positive: `WS-CODE` matches `TRAN-CODE` because `"CODE" in "TRAN-CODE"` after splitting on `-` in the root-prefix path at line 1938. This creates false `consumers` entries in `static_values` chunks, attributing values to CICS arguments they have no relationship to.

Fix: remove `var_u in arg_u` and `arg_u in var_u` from line 1936. Keep only exact case-insensitive match `var_u == arg_u`. Keep the existing root-prefix rules at lines 1938-1941 but tighten the root minimum from `len(root) >= 5` to `len(root) >= 7` and add a negative test asserting `WS-CODE` does not match `TRAN-CODE`. The commarea/W-prefix rule is acceptable because it is narrowly scoped to the `W` + 7-char root pattern used by Italian COBOL naming conventions.

#### B4 — `validate_chunks.py` and `chunk_pipeline.py` Step 5 must be committed together

File: `validate_chunks.py` (working tree, uncommitted); `chunk_pipeline.py` Step 5 additions (committed in `8a2f10c2`).

Problem: `chunk_pipeline.py` generates `comments` and `commented_out_code` chunks (committed). `validate_chunks.py` only accepts those types if the working-tree update is committed. If `validate_chunks.py` is committed separately or later, any intermediate state where the producer runs against the old validator will produce `432 unknown chunk types` errors in validation output. This is the split-brain confirmed by the corpus baseline validation run.

Fix: commit B1+B2+B3 fixes to `chunk_pipeline.py` in a single commit together with the `validate_chunks.py` working-tree changes. Do not commit `validate_chunks.py` alone first.

#### Execution order

1. Apply B1 fix to `chunk_pipeline.py`.
2. Apply B2 fix to `chunk_pipeline.py`.
3. Apply B3 fix to `chunk_pipeline.py` and add negative test to `test_chunk_pipeline.py`.
4. Confirm current `validate_chunks.py` working-tree diff is limited to registering `comments` and `commented_out_code` as valid chunk types.
5. Run `python3 -m unittest test_chunk_pipeline test_audit_chunk_regeneration` and `python3 -m py_compile chunk_pipeline.py validate_chunks.py`.
6. Commit `chunk_pipeline.py`, `validate_chunks.py`, and `test_chunk_pipeline.py` together in a single commit.

#### Acceptance checks

- `copybook_fields` metadata has `field_source: "java_rawtext_regex"` not `"java_data_structures"`.
- When `*-data.json` contains the `levelNumber: -99` sentinel, `generate_copybook_fields()` emits `analysis_status: "unavailable"` with a degradation note and does not produce a field list from raw copybook regex.
- `_variable_matches_cics_arg("WS-CODE", "TRAN-CODE")` returns `False`.
- `validate_chunks.py` accepts `comments` and `commented_out_code` chunk types.
- All unit tests pass after the commit.
- To resume mid-implementation, run `grep -n "field_source" chunk_pipeline.py` and `grep -n "var_u in arg_u" chunk_pipeline.py` to confirm which fixes are already applied.

### Step 6A: Controlled Sample Regeneration And Evaluation Gate

Status: Done For 20-Report Sample (2026-05-03)

Goal: prove Steps 0-5 and the redesigned Step 3/6 behavior on real reports before adding more chunk families.

Why this moved earlier:

- The current corpus has hundreds of stale schema `1.3` chunks and zero generated chunks for the new copybook/comment/dead-code families.
- Unit tests alone did not reveal the unsafe dead-code behavior.
- Downstream RAG quality cannot improve until producer chunks exist in a regenerated index.

Scope:

- Select a diverse sample of about 20 reports:
  - CICS + DB2
  - batch/no-CICS
  - copybook-heavy
  - missing/stubbed copybooks
  - dynamic calls/resources
  - comments and commented-out code
  - small/simple programs
  - degraded/partial parse cases
- Regenerate the sample in a separate temporary or sample output location.
- Validate chunk schema, token limits, and chunk-type coverage.
- Run manual or scripted RAG questions against the sample before touching the full corpus.

Acceptance checks:

- Sample has current schema chunks only.
- New copybook/comment chunks exist where evidence exists.
- `copybook_fields.field_source` does not claim structured Java data for values that were extracted by Python regex from `rawText`.
- Copybook field text does not imply a flat program field belongs to an included copybook unless Java origin metadata proves it.
- Null/degraded Java data-structure sentinel output does not trigger authoritative raw-copybook field facts.
- Static-value consumer facts do not use fuzzy substring matching.
- CICS and static-value provenance is either sourced from structured artifacts or explicitly marked heuristic/incomplete.
- No `dead_code` or `unused_copybooks` chunk emits positive "unused/dead" facts unless redesigned evidence supports it.
- No "No unused/dead code detected" text appears for incomplete analysis.
- At least one sample question retrieves each intended chunk family.
- Any failed or uncertain analysis is explicit in chunk text.

Commands to define before execution:

```bash
python3 -m unittest test_comment_extractor test_chunk_pipeline test_audit_chunk_regeneration
python3 corpus_baseline.py --report-dir out/report --output baselines/before_sample_regen.json
# TODO: add a non-destructive sample regeneration command that writes outside out/report
python3 validate_chunks.py --report-dir <sample-report-dir> --max-tokens 512
```

Verification - 2026-05-03:

- Research checks confirmed the B1/B2/B3/B4 blockers before code changes:
  - `field_source` still used `java_data_structures`.
  - `_variable_matches_cics_arg()` still used substring matching.
  - `_load_java_data_structure_fields()` had no null-sentinel guard.
  - `validate_chunks.py` had the expected uncommitted `comments` / `commented_out_code` registration.
- One research expectation was corrected: `BNK1DAC.cbl` itself has no `called_by` entry in `out/cross_program_calls.json`; the `called_by` gap is still real because 77 other programs have callers and zero existing `program_summary` texts mention `Called by`.
- Code fixes implemented:
  - `copybook_fields.field_source` for Java-backed field listings is now `java_rawtext_regex`.
  - Java null/degraded data-structure sentinel output emits `analysis_status: unavailable` with `field_source: none`.
  - fuzzy substring matching was removed from CICS consumer matching; root-prefix matching now requires a root length of at least 7.
  - dependencies chunks now extract literal CICS `MAP`, `MAPSET`, `TRANSID`, `DATASET`, `QUEUE`, and `PROGRAM` arguments from CFG `originalText`.
  - `program_summary` text now includes `Called by` when cross-program caller data exists.
  - `program_summary` text and metadata now include paragraph, section, level-88 condition, and `REDEFINES` counts from `cobol_structure.json`.
  - workflow chunks now append up to three CICS commands for each callee when the matching paragraph chunk metadata has `cics_commands`.
  - the line-safe splitter now handles a single oversized static-value evidence line without producing an over-token part.
- Unit/compile verification:
  - `python3 -m unittest test_chunk_pipeline test_audit_chunk_regeneration` passed: 46 tests, 2 skipped.
  - `PYTHONPYCACHEPREFIX=/tmp/cobol-rekt-pycache python3 -m py_compile chunk_pipeline.py validate_chunks.py test_chunk_pipeline.py` passed.
- Non-destructive sample regeneration:
  - sample root: `/tmp/cobol-rekt-step6a`
  - reports regenerated: `BNK1DAC.cbl`, `BANKDATA.cbl`, `BNK1CCS.cbl`, `COTRTLIC.cbl`, `CREACC.cbl`, `DBCRFUN.cbl`, `DELACC.cbl`, `INQACC.cbl`, `COBTUPDT.cbl`, `CBACT04C.cbl`, `CBEXPORT.cbl`, `CBIMPORT.cbl`, `COACTVWC.cbl`, `COADM01C.cbl`, `COBIL00C.cbl`, `COPAUS0C.cbl`, `ABCD.cbl`, `CBSTM03A.CBL`, `NC1074.2.cbl`, `NC2184.2.cbl`.
  - initial candidate `BNK1DCS.cbl.report` was rejected because it has neither `cfg/` nor `jcl_summary.json`; it was replaced with `COBTUPDT.cbl.report`.
- Sample validation:
  - command: `python3 validate_chunks.py --report-dir /tmp/cobol-rekt-step6a/out/report --corpus-index /tmp/cobol-rekt-step6a/out/corpus_index.json --max-tokens 512 --verbose`
  - result: PASS.
  - chunks checked: 2,804.
  - required-field errors: 0.
  - hash mismatches: 0.
  - over-token errors: 0.
  - schema warnings: 0.
  - dangling cross-references: 0.
  - index consistency errors: 0.
  - warnings: 6 `MISSING_SELF_EVAL` optional health-field warnings.
- Manual checks:
  - `BNK1DAC.cbl`: `program_summary` has structural facts; dependencies text contains `MAP BNK1DA` and `TRANSID OMEN`; comments chunk exists with `comment_count: 0`.
  - `BANKDATA.cbl`: `program_summary` has structural facts; comments chunk has `comment_count: 8`; `copybook_fields` emits `analysis_status: unavailable`, `field_source: none`, `degradation_reason: java_data_structures_null_sentinel`.
  - `NC1074.2.cbl`: `program_summary` has structural facts; regenerated static-value chunks validate under 512 tokens.
  - `ABCD.cbl`: `program_summary` includes `Called by: IF-TEST.` and null-sentinel copybook fields are unavailable rather than falling back to raw regex extraction.

### Step 7: Functional Program Summary

Status: Planned

Goal: improve "what is this program about?" beyond technical complexity.

New or improved chunks:

- `program_summary`
- `architecture_summary`
- `business_logic_summary`
- `control_flow_summary`

Text should include:

- technical classification: CICS online, batch, subprogram, utility, mixed, unknown
- primary inputs: maps, queues, DB2 tables, files, linkage/copybook structures
- primary outputs: maps, queues, files, external calls
- main flow: receive/read, validate, call subprograms, send/write/return
- business terms inferred from comments, names, map names, table names, and paragraph descriptions
- confidence and limitations

Important rule:

If business purpose is not inferable, say so explicitly:

```text
Business purpose: not confidently inferable from indexed comments/names.
```

Tests:

- CICS online program summary names maps/transactions/resources.
- Batch program summary names files/DDs.
- Program with no comments does not invent business purpose.
- Degraded copybook coverage is included as a limitation.

Acceptance checks:

- RAG can answer "what is the program about?" with useful functional context.
- Summary still works when CICS/DB2 are absent.

### Step 8: Batch Files, DD Names, VSAM, And Non-CICS Coverage

Status: Planned

Goal: make the schema work for large mixed portfolios, not only CICS online programs.

Tasks:

- Extend `datasets_tables_resources` to extract:
  - `SELECT ... ASSIGN TO ...`
  - FD names
  - OPEN modes
  - READ/WRITE/REWRITE/DELETE/START statements
  - DD names when JCL relationship data is available
  - VSAM/KSDS/ESDS hints, when available
- Link COBOL programs to JCL steps when the report bundle contains JCL relationship artifacts.

Tests:

- Batch program with input/output files emits read/write groups.
- Program with no CICS still emits useful datasets/files chunk.
- JCL-linked DD names are included when available and omitted with uncertainty when unavailable.

Acceptance checks:

- Dataset/table questions work for batch programs.
- No-CICS programs do not look empty just because CICS chunks are absent.

### Step 9: Golden Corpus Evaluation

Status: Planned

Goal: convert manual chat checks into repeatable producer-side regression checks.

Create fixture definitions under a new evaluation folder, for example:

```text
eval/rag_cases/
  pdb305.yaml
  batch_files.yaml
  no_cics.yaml
  copybook_stubs.yaml
  commented_out_code.yaml
  dynamic_calls.yaml
```

Each case should define:

- report path or fixture generator
- question
- required chunk types
- required text fragments
- forbidden text fragments
- expected uncertainty wording

Initial cases from PDB305:

- program overview
- copybook counts/stubbed
- copybook names
- external calls with parameters
- COMMAREA call filtering
- DB2/CICS resources
- static values with categories/provenance
- dead-code uncertainty
- copybook parameter safe refusal until `copybook_fields`
- copybook line safe refusal until `copybook_mentions`
- comments safe refusal until `comments`

Acceptance checks:

- Producer-side chunks contain required facts before downstream RAG is run.
- Failed cases identify producer gap vs RAG retrieval gap.

### Step 10: Full Corpus Regeneration And Scale Gate

Status: Planned After Step 6A

Goal: prove the output contract works across hundreds now and thousands later.

Recommended sequence:

1. Run unit tests.
2. Capture baseline.
3. Complete Step 6A sample regeneration and evaluation in a separate location.
4. Fix any producer/output-contract issues found in sample.
5. Regenerate full corpus with current schema.
6. Validate full corpus.
7. Diff baseline.
8. Run golden cases over full corpus.
9. Only then sync broad outputs into downstream RAG.

Commands:

```bash
python3 -m py_compile chunk_pipeline.py validate_chunks.py test_chunk_pipeline.py
python3 test_chunk_pipeline.py
python3 corpus_baseline.py --report-dir out/report --output baselines/before_full_regen.json
python3 validate_chunks.py --report-dir out/report --max-tokens 512
```

Scale acceptance gates:

- 100% regenerated chunks use the current schema version.
- 0 indexable chunks exceed token limit.
- No active dependency/resource chunk includes commented-out-only evidence.
- No blocked prototype chunk emits positive facts into the corpus.
- Every generated report has `program_summary` or an explicit unevaluable health chunk.
- Every COBOL report with copybook data has copybook resolution evidence.
- Every important missing analysis has an explicit uncertainty chunk.
- Golden cases pass across at least:
  - CICS + DB2
  - batch files
  - copybook-heavy degraded parse
  - no external calls
  - commented-out code
  - dynamic/unresolved calls
  - incomplete/failed analysis

### Step 11: Downstream RAG Integration Gate

Status: Planned

Goal: avoid pushing producer changes that RAG cannot consume.

Tasks:

- Update `cobol-rag-pipeline` intent routing only after producer chunk types exist.
- Keep metadata scalar-safe downstream.
- Add RAG eval cases that mirror producer golden cases.
- Sync a regenerated multi-program corpus into a separate Chroma collection for testing.

Acceptance checks:

- RAG answers use the intended chunk type first.
- RAG refuses safely when producer marks analysis as unavailable.
- No metadata-too-large errors.
- Multi-program questions do not leak facts across programs without an explicit program filter.

## Done Criteria

cobol-rekt output is RAG-ready when:

- Common analyst questions map to explicit curated chunks.
- Chunk text includes the important facts without requiring large metadata.
- Active, inactive, and commented-out facts are clearly separated.
- Program calls include parameters.
- Static values include provenance and purpose category.
- Dead-code and unused-copybook uncertainty is explicit when analysis is incomplete.
- The same schema works for CICS, batch, DB2, copybook-heavy, and partially parsed programs.
- A multi-program golden corpus passes without one-off program-specific code.
