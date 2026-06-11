# GnuCOBOL Differential Soundness

This fixture-only harness instruments generated CFG node entry/exit constant facts with COBOL `DISPLAY` probes, compiles with `cobc`, runs the fixture, and compares runtime values to emitted constants.

CICS and DB2/SQL programs are out of scope because GnuCOBOL does not provide the CICS/DB2 runtime semantics required by those fixtures.

- Status: `skipped`
- `cobc`: `not found`
- Fixture candidates: 11
- Passed fixtures: 0
- Failed fixtures: 0
- Compile-failed fixtures: 0
- Skipped fixtures: 11
- Probe mismatches: 0

## Skip Reason

`cobc` is not installed in this environment. `apt-cache policy gnucobol` reports an installable candidate, but `sudo apt-get install -y gnucobol` could not run here because sudo requires a password.

To run locally after installing GnuCOBOL:

```bash
python3 scripts/gnucobol_differential.py
```
