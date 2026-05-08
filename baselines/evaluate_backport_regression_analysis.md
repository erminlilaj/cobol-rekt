# EVALUATE Backport Regression Analysis
**Date:** 2026-04-30
**Commits:** 595c7886f (Stricter END-EVALUATE) + c2ba1be4f (EVALUATE recovery fix)
**Baseline diff:** baseline_pre_integration.json → baseline_after_evaluate_backport.json

## Summary
The diff tool reported 9 regressions (exit code 1). Investigation shows NONE are caused by the EVALUATE grammar backport. All 9 are environmental/copybook-resolver artifacts from changed analysis paths.

## Regression Breakdown

### Category A — BMS map file resolved as COBOL copybook (5 programs)
Programs: lgtestp1.cbl, lgtestp2.cbl, lgtestp3.cbl, lgtestp4.cbl, lgtestc1.cbl

**Error:** `Syntax error on 'DFHMSD'` in copybook SSMAP (line 6 of ssmap.bms)

**Root cause:** The case-insensitive copybook resolver searches all files in the copybooks directory,
including `.bms` extension files. The cics-genapp `ssmap.bms` (688 lines) contains BMS map macros
(`DFHMSD`, `DFHMDI`) and is resolved as the SSMAP copybook instead of the correct COBOL data map
from che-che4z test_files (612 lines, pure COBOL data definitions).

In the April 16 pre-baseline run, lgtestp1-4/lgtestc1 had no `parse_diagnostics.json` (strict
parse succeeded). This was because the April 16 analysis was run from a different working directory
without access to codefiles/external/, so SSMAP was either stubbed or resolved from the Che4z
copy. Today's rerun finds codefiles/external/ and resolves SSMAP to the BMS file.

**EVALUATE-related:** NO. ssmap.bms does not contain EVALUATE.

### Category B — COBOL program included as copybook (4 programs)
Programs: BNK1CCA.cbl, BNK1DAC.cbl, CRECUST.cbl, INQACCCU.cbl

**Error:** `Recursive copybook declaration for: INQCUST/INQACCCU/INQACC` and
`Syntax error on 'CBL'` inside the recursively-included copybook.

**Root cause:** The copybook resolver finds INQACCCU.cbl, INQACC.cbl, INQCUST.cbl (full COBOL
programs) as copybooks for `COPY INQACCCU`, `COPY INQACC`, `COPY INQCUST` statements. These
programs in turn COPY each other, creating recursive declarations. The `Syntax error on 'CBL'` is
the CBL compiler directive at the start of the included program.

Pre-baseline had 1-2 errors for these programs; now 4-12 because more recursive loops are resolved.
The INQCUST copybook is in the same codefiles/external/ directory as BNK1CCA — the resolver finds
it as a copybook candidate.

**EVALUATE-related:** NO. These are recursive COPY resolution errors.

## Genuine Positive Changes
- SAM1.cbl: 376 → 320 CFG nodes (EVALUATE branches now parsed more accurately)
- SAM2.cbl: 112 → 108 CFG nodes (same)
- 60+ programs gained `base_analysis_succeeded: True` and CFG data (were not analyzed before)
- `programs_with_evaluate` remains 108 (stable)
- `programs_with_exec_dli` remains 4 (stable)

## Decision for Codex
The 9 regressions are environmental, not caused by the EVALUATE grammar change.
Two options:
1. **Accept regressions** — they are pre-existing copybook resolver issues exposed by analyzing from
   codefiles/external/. Document acceptance. Proceed with commit.
2. **Investigate copybook resolver** — fix .bms extension filter and recursive COBOL program
   detection before proceeding. This would eliminate the false positives.

The EVALUATE grammar change itself is safe per all evidence.
