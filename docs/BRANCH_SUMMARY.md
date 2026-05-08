# Integration Research — Branch Summary

## Overview

This branch focused on two parallel goals: hardening the accuracy and completeness of the COBOL static analysis pipeline, and improving the quality and coverage of the RAG chunk output that downstream retrieval systems consume. The work proceeded by identifying concrete gaps in analysis fidelity, fixing those gaps, and validating the fixes with corpus-wide regression runs.

---

## Issues Found

### Control flow representation

- Multi-way conditionals (EVALUATE) had no individual branch nodes in the control flow graph — all branches collapsed to a single opaque node, making it impossible to distinguish which condition led to which code path.
- Program termination variants were all classified identically, regardless of whether control returned to a caller, exited the current PERFORM, or terminated the entire process.
- CICS error-handling bindings had no outgoing edges in the graph, so handler targets were invisible to reachability and dependency analysis.

### Data structure handling

- Stubbed system copybooks (e.g., SQLCA, DFHAID) caused data structure analysis to degrade for the entire program, not just the missing copybook — affecting all variable metadata derived from it.
- The data dictionary silently omitted entire data sections (LINKAGE, FILE DESCRIPTOR) due to a section-name mismatch between what the code expected and what the JSON artifacts stored.
- A single variable declaration with a malformed PIC clause could abort extraction for all subsequent variables in the same program.

### RAG chunk quality

- Oversized chunks (exceeding embedding model context limits) and near-empty chunks coexisted in the output with no validation gate to catch them before corpus ingestion.
- Approximately 1,500 near-duplicate chunks inflated corpus counts and degraded retrieval precision.
- Commented-out COBOL source was ingested as active program logic, producing false dependencies and incorrect narrative text in retrieved results.
- No dedicated chunk type existed for CICS operations, resource accesses, or inter-program transfers — CICS content was buried in general-purpose chunks.

### Pipeline correctness

- Comment translation backend selection was silently broken: the flag passed at runtime had no effect, and the default backend was always used regardless of the argument.
- The control-flow quality metric in the evaluator was computed at the wrong abstraction layer, making its scores invalid as thesis benchmark data.
- JCL artifact-to-knowledge-base conversion was completely non-functional, with a 0% conversion rate despite JCL analysis producing correct intermediate output.

### Retrieval quality

- CICS content scored approximately 19% Recall@1 despite the content being fully present in the corpus. The failure is architectural: the retrieval layer cannot surface CICS-specific content for CICS-specific queries.
- Cross-program call context (which programs invoke a given program) was absent from chunk metadata, preventing call-graph-aware retrieval.

---

## Improvements Delivered

### Control flow

- Multi-way conditionals now produce individual branch nodes in the control flow graph, each carrying condition text and branch classification, enabling path-level analysis.
- Program termination is now classified into typed variants: return to caller, exit to PERFORM, and process termination. Reachability queries can now distinguish between them.
- Source file line and column is attached to every control flow node and every edge, enabling precise traceability back to source.

### Variable and data flow

- Variable read and write sites are tracked across each program, providing a lightweight dataflow layer.
- Dynamic CALL and CICS targets are now resolved: when a variable is assigned a literal value and later used as a program name, the resolved target is recorded with a confidence label, making previously opaque dynamic dispatch visible.

### CICS analysis

- CICS operations, program transfers (LINK/XCTL), resource accesses, and error handlers each have their own dedicated chunk type with structured metadata.
- Inactive and commented-out CICS handlers are tracked separately with an `active: false` flag, preserving them as historical evidence without contaminating active control flow analysis.

### Pipeline reliability

- Structural parse failures now emit named diagnostic codes instead of generic errors, making root causes machine-readable without log parsing.
- Data structure extraction is now resilient at the per-variable level: a single bad variable no longer aborts extraction for the entire program.
- Comment translation backend selection works correctly.
- Commented-out COBOL source is detected and excluded from the active narrative and chunk content.

### Knowledge base correctness

- The data dictionary now covers all data sections including LINKAGE and FILE DESCRIPTOR, which were previously silently omitted.
- Multi-branch conditional statement text is preserved in full in the logic narrative (previously truncated at an arbitrary character limit).
- Statement type coverage in the logic narrative was expanded to include previously missing categories.

### Chunk quality and validation

- BPE token counting replaces whitespace splitting for accurate chunk sizing against embedding model limits.
- Analysis health information — parse coverage percentage, stubbed copybook count, degraded data structure flag — is now surfaced in chunk metadata, making quality signals available to downstream retrieval systems.
- A validation gate catches schema violations, hash mismatches, and oversized chunks before they enter the corpus.

---

## Open Items

### Blocks thesis benchmarks

- Retrieval quality for CICS queries is poor despite content presence. Requires a hybrid BM25 + metadata-filter retrieval architecture; vector similarity alone cannot distinguish between CICS-specific and general-purpose content.
- The control-flow evaluator metric must be redesigned before use in thesis comparisons. The current metric scores at the wrong abstraction level and will produce misleading results.
- Oversized, thin, and duplicate chunks still exist in the corpus. A chunk splitting and deduplication pass is needed before the corpus can be considered retrieval-ready.
- JCL artifact-to-knowledge-base conversion remains at 0%. JCL analysis produces correct intermediate output but it never reaches the knowledge base documents.

### Medium priority

- Cross-program call context (`called_by`) is not yet injected into chunk metadata, preventing call-graph-aware retrieval filtering.
- IMS/DLI extraction is not implemented. Four programs in the current corpus use IMS/DLI constructs that are not captured.
- Copybook field ownership is not resolved at the per-field level: the analysis identifies which copybooks are included but not which specific fields originate from which copybook.

### Deferred decisions

- **Upstream parser drift**: the upstream COBOL parser dependency is 487 commits behind. Do not merge upstream changes before establishing a corpus baseline and validating that the baseline is preserved. Only specific, verified fixes should be cherry-picked.
- **Mapa tool integration**: the architectural decision has been made (port relevant extraction logic into the existing Java pipeline rather than bridging to an external tool). No implementation timeline is committed.
- **Full interprocedural dataflow**: the current implementation tracks read/write sites per program but does not perform reaching-definitions or cross-procedure dataflow analysis.

---

## Quality Metrics Snapshot

Content preservation — how well the analysis artifacts feed through to the knowledge base:

| Dimension | Coverage |
|---|---|
| CICS | ~99% |
| External program calls | ~100% |
| Program structure | ~97% |
| DB2 / SQL | ~95% |
| Data and variables | ~95% |
| Comments | ~82% |
| Copybooks | ~63% |
| Control flow | not valid — metric methodology broken (see Open Items) |

Retrieval quality — Recall@1 / Recall@5 in the last evaluator run:

| Query category | Recall@1 | Recall@5 |
|---|---|---|
| JCL | 100% | 100% |
| Program structure | ~55% | ~85% |
| DB2 SQL | ~45% | ~89% |
| Comments | ~41% | ~75% |
| External calls | ~29% | ~70% |
| CICS | ~19% | ~89% |

The CICS row is the most important signal: Recall@5 is high (content is in the corpus) but Recall@1 is very low (the retrieval layer cannot surface it on the first result). This confirms the problem is retrieval architecture, not content coverage.

Corpus size at last full run: approximately 47,800 chunks across 400+ COBOL programs and 41 JCL jobs.
