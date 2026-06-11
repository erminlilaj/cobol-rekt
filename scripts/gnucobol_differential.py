#!/usr/bin/env python3
"""Differentially check emitted dataflow constants against GnuCOBOL fixtures."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


EXCLUDED_MARKERS = ("EXEC CICS", "EXEC SQL")
PROBE_PREFIX = "__CFP_PROBE__"


@dataclass(frozen=True)
class Probe:
    node_id: str
    phase: str
    variable: str
    kind: str
    expected: str
    source_line: int
    source_end_line: int


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def canonical(value: Any) -> str:
    return str(value or "").strip().upper()


def fixture_report(source: Path, report_root: Path) -> Path:
    return report_root / f"{source.name}.report"


def report_source(report: Path, source_root: Path) -> Path:
    return source_root / report.name.removesuffix(".report")


def has_excluded_runtime(source: Path) -> bool:
    text = source.read_text(encoding="utf-8", errors="replace").upper()
    return any(marker in text for marker in EXCLUDED_MARKERS)


def small_fixture(source: Path, max_lines: int) -> bool:
    return sum(1 for _ in source.open(encoding="utf-8", errors="replace")) <= max_lines


def discover_fixtures(source_root: Path, report_root: Path, max_lines: int) -> list[Path]:
    result = []
    for source in sorted(source_root.glob("*.cbl")):
        report = fixture_report(source, report_root)
        if not (report / "static_analysis" / "dataflow_rag_summary.json").exists():
            continue
        if not (report / "cfg" / f"cfg-{source.name}.json").exists():
            continue
        if has_excluded_runtime(source):
            continue
        if not small_fixture(source, max_lines):
            continue
        result.append(source)
    return result


def display_literal(value: str) -> str:
    return value.replace('"', '""')


def probes_for(source: Path, report_root: Path) -> list[Probe]:
    report = fixture_report(source, report_root)
    cfg = load_json(report / "cfg" / f"cfg-{source.name}.json")
    dataflow = load_json(report / "static_analysis" / "dataflow_rag_summary.json")
    node_lines = {
        node["id"]: (
            int(node.get("sourceLine") or 0),
            int(node.get("sourceEndLine") or node.get("sourceLine") or 0),
        )
        for node in cfg.get("nodes", [])
        if node.get("id") and node.get("sourceLine")
    }
    probes: list[Probe] = []
    for node_id, state in (dataflow.get("node_states") or {}).items():
        if node_id not in node_lines:
            continue
        start, end = node_lines[node_id]
        for phase, key, line in (("entry", "entry_constants", start), ("exit", "exit_constants", end)):
            for variable, value in sorted((state.get(key) or {}).items()):
                kind = canonical(value.get("kind"))
                if kind not in {"NUMERIC", "ALPHANUMERIC"}:
                    continue
                expected = str(value.get("display_value") or value.get("normalized_value") or "")
                if not expected:
                    continue
                probes.append(Probe(node_id, phase, variable, kind, expected, start, end))
    return probes


def probe_line(probe: Probe) -> str:
    label = "|".join([
        PROBE_PREFIX,
        probe.node_id,
        probe.phase,
        probe.variable,
        probe.kind,
        display_literal(probe.expected),
    ])
    return f'           DISPLAY "{label}|" {probe.variable}\n'


def instrument_source(source: Path, probes: list[Probe], output: Path) -> None:
    lines = source.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    before: dict[int, list[Probe]] = {}
    after: dict[int, list[Probe]] = {}
    for probe in probes:
        before.setdefault(probe.source_line, []).append(probe)
        after.setdefault(probe.source_end_line, []).append(probe)
    result: list[str] = []
    for index, line in enumerate(lines, start=1):
        for probe in before.get(index, []):
            result.append(probe_line(probe))
        result.append(line)
        for probe in after.get(index, []):
            result.append(probe_line(probe))
    output.write_text("".join(result), encoding="utf-8")


def normalize_runtime(value: str, kind: str) -> str:
    value = value.strip()
    if kind == "ALPHANUMERIC":
        return value.strip().upper()
    try:
        decimal = Decimal(value)
    except InvalidOperation:
        return value
    normalized = format(decimal.normalize(), "f")
    return normalized.rstrip("0").rstrip(".") if "." in normalized else normalized


def normalize_expected(value: str, kind: str) -> str:
    if kind == "ALPHANUMERIC":
        return value.strip().upper()
    try:
        decimal = Decimal(value.strip())
    except InvalidOperation:
        return value.strip()
    normalized = format(decimal.normalize(), "f")
    return normalized.rstrip("0").rstrip(".") if "." in normalized else normalized


def parse_probe_output(output: str) -> list[dict[str, Any]]:
    rows = []
    pattern = re.compile(rf"^{re.escape(PROBE_PREFIX)}\\|([^|]+)\\|([^|]+)\\|([^|]+)\\|([^|]+)\\|([^|]*)\\|(.*)$")
    for line in output.splitlines():
        match = pattern.match(line.rstrip("\n"))
        if not match:
            continue
        node_id, phase, variable, kind, expected, observed = match.groups()
        rows.append({
            "node_id": node_id,
            "phase": phase,
            "variable": variable,
            "kind": kind,
            "expected": expected,
            "observed": observed,
            "passed": normalize_runtime(observed, kind) == normalize_expected(expected, kind),
        })
    return rows


def run_fixture(source: Path, report_root: Path, cobc: str, work_dir: Path) -> dict[str, Any]:
    probes = probes_for(source, report_root)
    if not probes:
        return {"fixture": str(source), "status": "skipped", "reason": "no entry/exit constant probes emitted", "probe_count": 0}
    instrumented = work_dir / source.name
    executable = work_dir / source.stem
    instrument_source(source, probes, instrumented)
    compile_cmd = [cobc, "-x", str(instrumented), "-o", str(executable)]
    compile_result = subprocess.run(compile_cmd, text=True, capture_output=True, timeout=30, check=False)
    if compile_result.returncode != 0:
        return {
            "fixture": str(source),
            "status": "compile_failed",
            "probe_count": len(probes),
            "compile_stdout": compile_result.stdout[-4000:],
            "compile_stderr": compile_result.stderr[-4000:],
        }
    run_result = subprocess.run([str(executable)], text=True, capture_output=True, timeout=30, check=False)
    rows = parse_probe_output(run_result.stdout)
    mismatches = [row for row in rows if not row["passed"]]
    return {
        "fixture": str(source),
        "status": "failed" if mismatches else "passed",
        "probe_count": len(probes),
        "observed_probe_count": len(rows),
        "mismatch_count": len(mismatches),
        "mismatches": mismatches[:50],
        "run_returncode": run_result.returncode,
        "run_stderr": run_result.stderr[-4000:],
    }


def render_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# GnuCOBOL Differential Soundness",
        "",
        "This fixture-only harness instruments generated CFG node entry/exit constant facts with COBOL `DISPLAY` probes, compiles with `cobc`, runs the fixture, and compares runtime values to emitted constants.",
        "",
        "CICS and DB2/SQL programs are out of scope because GnuCOBOL does not provide the CICS/DB2 runtime semantics required by those fixtures.",
        "",
        f"- Status: `{result['status']}`",
        f"- `cobc`: `{result.get('cobc') or 'not found'}`",
        f"- Fixture candidates: {result.get('candidate_count', 0)}",
        f"- Passed fixtures: {result.get('passed_count', 0)}",
        f"- Failed fixtures: {result.get('failed_count', 0)}",
        f"- Compile-failed fixtures: {result.get('compile_failed_count', 0)}",
        f"- Skipped fixtures: {result.get('skipped_count', 0)}",
        f"- Probe mismatches: {result.get('mismatch_count', 0)}",
        "",
    ]
    if result["status"] == "skipped":
        lines.extend([
            "## Skip Reason",
            "",
            result["skip_reason"],
            "",
            "To run locally after installing GnuCOBOL:",
            "",
            "```bash",
            "python3 scripts/gnucobol_differential.py",
            "```",
            "",
        ])
        return "\n".join(lines)

    lines.extend([
        "## Fixture Results",
        "",
        "| Fixture | Status | Probes | Observed | Mismatches |",
        "|---|---|---:|---:|---:|",
    ])
    for row in result["fixtures"]:
        lines.append(
            f"| `{Path(row['fixture']).name}` | `{row['status']}` | {row.get('probe_count', 0)} | "
            f"{row.get('observed_probe_count', 0)} | {row.get('mismatch_count', 0)} |"
        )
    failed = [row for row in result["fixtures"] if row.get("mismatches")]
    if failed:
        lines.extend(["", "## Mismatches", ""])
        for row in failed:
            lines.append(f"### `{Path(row['fixture']).name}`")
            for mismatch in row["mismatches"][:20]:
                lines.append(
                    f"- `{mismatch['phase']}` `{mismatch['variable']}` at `{mismatch['node_id']}`: "
                    f"expected `{mismatch['expected']}`, observed `{mismatch['observed']}`"
                )
            lines.append("")
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Any]:
    cobc = shutil.which("cobc")
    candidates = discover_fixtures(args.source_root, args.report_root, args.max_lines)
    base = {
        "schema_version": "1.0",
        "source_root": str(args.source_root),
        "report_root": str(args.report_root),
        "candidate_count": len(candidates),
        "excluded_scope": "CICS/DB2 fixtures are excluded because GnuCOBOL cannot execute EXEC CICS or EXEC SQL semantics.",
        "cobc": cobc,
    }
    if cobc is None:
        base.update({
            "status": "skipped",
            "skip_reason": (
                "`cobc` is not installed in this environment. `apt-cache policy gnucobol` reports an installable "
                "candidate, but `sudo apt-get install -y gnucobol` could not run here because sudo requires a password."
            ),
            "fixtures": [{"fixture": str(path), "status": "skipped", "reason": "cobc not installed"} for path in candidates],
            "passed_count": 0,
            "failed_count": 0,
            "compile_failed_count": 0,
            "skipped_count": len(candidates),
            "mismatch_count": 0,
        })
        return base

    with tempfile.TemporaryDirectory(prefix="cobol-diff-") as tmp:
        rows = [run_fixture(path, args.report_root, cobc, Path(tmp)) for path in candidates]
    mismatch_count = sum(row.get("mismatch_count", 0) for row in rows)
    base.update({
        "status": "failed" if mismatch_count else "passed",
        "fixtures": rows,
        "passed_count": sum(1 for row in rows if row["status"] == "passed"),
        "failed_count": sum(1 for row in rows if row["status"] == "failed"),
        "compile_failed_count": sum(1 for row in rows if row["status"] == "compile_failed"),
        "skipped_count": sum(1 for row in rows if row["status"] == "skipped"),
        "mismatch_count": mismatch_count,
    })
    return base


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=Path("smojol-toolkit/test-code/flow-ast"))
    parser.add_argument("--report-root", type=Path, default=Path("smojol-toolkit/test-code/out"))
    parser.add_argument("--json-out", type=Path, default=Path("docs/analysis/differential_soundness.json"))
    parser.add_argument("--md-out", type=Path, default=Path("docs/analysis/differential_soundness.md"))
    parser.add_argument("--max-lines", type=int, default=250)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = run(args)
    write_json(args.json_out, result)
    args.md_out.parent.mkdir(parents=True, exist_ok=True)
    args.md_out.write_text(render_markdown(result), encoding="utf-8")
    print(f"Wrote {args.json_out}")
    print(f"Wrote {args.md_out}")
    return 1 if result["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
