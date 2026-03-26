#!/usr/bin/env python3
"""
build_corpus_index.py — Aggregate per-program/job metadata into a single
corpus_index.json for cross-program lookup and RAG tier-0 filtering.

Walks all *.report directories under --report-dir, reads each program's
chunks_manifest.json (for chunk counts) and knowledge_base/03_Dependencies.yaml
(for SQL tables, CICS commands, called programs), and optionally merges
cross_program_calls.json for called_by / entry_type fields.

Output structure:
{
  "generated": "<ISO-8601 timestamp>",
  "programs": {
    "MYPROG.CBL": {
      "report_dir": "out/report/MYPROG.CBL.report/",
      "complexity": 42,
      "node_count": 200,
      "variable_count": 150,
      "sql_tables_read": ["ORDERS", "CUSTOMERS"],
      "sql_tables_updated": ["ORDERS"],
      "cics_commands": ["READ", "WRITE"],
      "calls": ["SUBPROG"],
      "called_by": [],
      "entry_type": "none",
      "paragraph_count": 20,
      "chunk_count": 30
    }
  },
  "jobs": {
    "MYJOB": {
      "report_dir": "out/report/MYJOB.jcl.report/",
      "steps": ["STEP1", "STEP2"],
      "programs_invoked": ["MYPROG"]
    }
  },
  "tables": {
    "ORDERS": {
      "read_by": ["MYPROG.CBL"],
      "updated_by": ["MYPROG.CBL"]
    }
  }
}

Usage:
    python3 build_corpus_index.py
    python3 build_corpus_index.py --report-dir out/report --output out/corpus_index.json
    python3 build_corpus_index.py --cross-program out/cross_program_calls.json -v
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml


# =============================================================================
# Loaders
# =============================================================================

def _load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"  [WARN] Failed to load JSON {path}: {e}", file=sys.stderr)
        return None


def _load_yaml(path: Path):
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError) as e:
        print(f"  [WARN] Failed to load YAML {path}: {e}", file=sys.stderr)
        return None


# =============================================================================
# Per-directory extraction
# =============================================================================

def _extract_cobol(report_dir: Path) -> dict | None:
    """Extract program metadata from a COBOL *.report directory.

    Returns a dict ready for the 'programs' index, or None if the directory
    does not look like a COBOL report.
    """
    if not (report_dir / "cfg").is_dir():
        return None

    program = report_dir.name.replace(".report", "")

    # --- chunk counts from manifest ---
    manifest = _load_json(report_dir / "chunks" / "chunks_manifest.json") or {}
    type_counts = manifest.get("type_counts", {})
    chunk_count = manifest.get("total_chunks", 0)
    paragraph_count = type_counts.get("paragraph_logic", 0)

    # --- complexity / metrics from program_summary chunk ---
    complexity = 0
    node_count = 0
    variable_count = 0
    summary_chunk_path = report_dir / "chunks" / f"{program}__program_summary.json"
    if summary_chunk_path.exists():
        sc = _load_json(summary_chunk_path) or {}
        meta = sc.get("metadata", {})
        complexity = meta.get("complexity_score", 0)
        node_count = meta.get("node_count", 0)
        variable_count = meta.get("variable_count", 0)

    # --- dependencies from 03_Dependencies.yaml ---
    deps_path = report_dir / "knowledge_base" / "03_Dependencies.yaml"
    deps = _load_yaml(deps_path) or {}
    db = deps.get("database") or {}
    sql_tables_read = db.get("tables_read") or []
    sql_tables_updated = db.get("tables_updated") or []
    calls_raw = deps.get("calls") or []
    calls = [
        c["target"] if isinstance(c, dict) else str(c)
        for c in calls_raw
        if c
    ]
    cics_commands = deps.get("cics") or []

    return {
        "report_dir": str(report_dir) + "/",
        "complexity": complexity,
        "node_count": node_count,
        "variable_count": variable_count,
        "sql_tables_read": sql_tables_read,
        "sql_tables_updated": sql_tables_updated,
        "cics_commands": cics_commands,
        "calls": calls,
        "called_by": [],       # filled in from cross_program_calls.json if available
        "entry_type": "none",  # overridden below if cross-program data present
        "paragraph_count": paragraph_count,
        "chunk_count": chunk_count,
    }


def _extract_jcl(report_dir: Path) -> dict | None:
    """Extract job metadata from a JCL *.report directory."""
    summary_path = report_dir / "jcl_summary.json"
    if not summary_path.exists():
        return None

    summary = _load_json(summary_path) or {}
    job_name = summary.get("job_name") or report_dir.name.replace(".report", "")

    steps_raw: list = []
    # Enumerate step names from step_detail chunk filenames
    chunks_dir = report_dir / "chunks"
    if chunks_dir.is_dir():
        for f in sorted(chunks_dir.glob("*__step_detail__*.json")):
            step = f.stem.split("__step_detail__", 1)[-1]
            if step and step not in steps_raw:
                steps_raw.append(step)

    # Fall back to jcl_summary.json if no chunks exist yet
    if not steps_raw:
        steps_raw = list(summary.get("steps", []))

    programs_invoked = list(summary.get("programs_invoked") or [])

    return {
        "job_name": job_name,
        "report_dir": str(report_dir) + "/",
        "steps": steps_raw,
        "programs_invoked": programs_invoked,
    }


# =============================================================================
# Cross-program merge
# =============================================================================

def _merge_cross_program(programs: dict, cross_path: Path, verbose: bool) -> None:
    """Merge called_by / entry_type from cross_program_calls.json into programs dict."""
    data = _load_json(cross_path)
    if data is None:
        if verbose:
            print(f"  Warning: could not load {cross_path}")
        return

    prog_list = data.get("programs") or []
    for item in prog_list:
        name = item.get("name", "")
        # Try exact key match first, then prefix match ignoring extension
        if name in programs:
            key = name
        else:
            key = next(
                (k for k in programs if k.upper().startswith(name.upper())), None
            )
        if key:
            programs[key]["called_by"] = item.get("called_by", [])
            programs[key]["entry_type"] = item.get("entry_type", "none")

    if verbose:
        print(f"  Merged cross-program data ({len(prog_list)} entries)")


# =============================================================================
# Table index builder
# =============================================================================

def _build_table_index(programs: dict) -> dict:
    """Invert sql_tables_read / sql_tables_updated into a tables cross-reference."""
    tables: dict[str, dict] = {}
    for prog, info in programs.items():
        for tbl in info.get("sql_tables_read", []):
            if tbl:
                tables.setdefault(tbl, {"read_by": [], "updated_by": []})
                tables[tbl]["read_by"].append(prog)
        for tbl in info.get("sql_tables_updated", []):
            if tbl:
                tables.setdefault(tbl, {"read_by": [], "updated_by": []})
                tables[tbl]["updated_by"].append(prog)
    return tables


# =============================================================================
# Main builder
# =============================================================================

def build_corpus_index(
    report_dir: Path,
    output: Path,
    cross_program: Path | None,
    verbose: bool,
) -> dict:
    programs: dict = {}
    jobs: dict = {}

    report_dirs = sorted(report_dir.glob("*.report"))
    if not report_dirs:
        print(f"Warning: no *.report directories found under {report_dir}")

    for rd in report_dirs:
        cobol_data = _extract_cobol(rd)
        if cobol_data is not None:
            prog_name = rd.name.replace(".report", "")
            programs[prog_name] = cobol_data
            if verbose:
                print(f"  COBOL  {prog_name} ({cobol_data['chunk_count']} chunks, "
                      f"complexity={cobol_data['complexity']})")
            continue  # a dir is either COBOL or JCL, not both

        jcl_data = _extract_jcl(rd)
        if jcl_data is not None:
            job_name = jcl_data.pop("job_name")
            jobs[job_name] = jcl_data
            if verbose:
                print(f"  JCL    {job_name} ({len(jcl_data['steps'])} steps)")

    if cross_program and cross_program.exists():
        _merge_cross_program(programs, cross_program, verbose)

    tables = _build_table_index(programs)

    index = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "programs": programs,
        "jobs": jobs,
        "tables": tables,
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n",
                      encoding="utf-8")
    return index


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Build corpus_index.json — cross-program metadata index",
    )
    parser.add_argument(
        "--report-dir", type=Path, default=Path("out/report"),
        help="Root directory containing *.report subdirectories (default: out/report)",
    )
    parser.add_argument(
        "--output", type=Path, default=Path("out/corpus_index.json"),
        help="Output path for corpus_index.json (default: out/corpus_index.json)",
    )
    parser.add_argument(
        "--cross-program", type=Path, default=None,
        help="Path to cross_program_calls.json for called_by/entry_type enrichment "
             "(default: out/cross_program_calls.json if it exists)",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    if not args.report_dir.is_dir():
        print(f"Error: {args.report_dir} is not a directory")
        sys.exit(1)

    # Auto-detect cross_program_calls.json if not specified
    cross_program = args.cross_program
    if cross_program is None:
        default_cross = args.report_dir.parent / "cross_program_calls.json"
        if default_cross.exists():
            cross_program = default_cross
            if args.verbose:
                print(f"Auto-detected cross-program data: {cross_program}")

    if args.verbose:
        print(f"Scanning: {args.report_dir}")

    index = build_corpus_index(
        report_dir=args.report_dir,
        output=args.output,
        cross_program=cross_program,
        verbose=args.verbose,
    )

    prog_count = len(index["programs"])
    job_count = len(index["jobs"])
    table_count = len(index["tables"])
    print(f"Done. {prog_count} programs, {job_count} jobs, {table_count} SQL tables → {args.output}")


if __name__ == "__main__":
    main()
