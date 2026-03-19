#!/usr/bin/env python3
"""
build_call_graph.py -- Cross-program call graph from COBOL + JCL reports.

Aggregates COBOL CALL relationships from 03_Dependencies.yaml and JCL
EXEC PGM= relationships from jcl_summary.json across one or more report
directories. Writes a unified call graph to out/cross_program_calls.json
and optionally updates program_summary chunk metadata with called_by
and entry_type fields.

Usage:
    python3 build_call_graph.py
    python3 build_call_graph.py --report-dir out/report
    python3 build_call_graph.py --report-dir /cobol/reports --report-dir /jcl/reports
    python3 build_call_graph.py --report-dir out/report --no-update-chunks
"""

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import yaml

# Duplicated from jcl_parser.py to keep zero coupling.
_SYSTEM_PGMS = {"IEFBR14", "ICEMAN", "IDCAMS", "IEBGENER", "SORT", "PARM2SK"}


def normalize_program_name(name: str) -> str:
    """Strip COBOL file extensions and uppercase to get canonical bare name.

    Idempotent: calling twice yields the same result.
    Examples:
        TEST.CBL  -> TEST
        TEST.cbl -> TEST
        MYPROG    -> MYPROG
        hello.cob   -> HELLO
    """
    n = re.sub(r"\.[Cc][Bb][Ll]$", "", name)
    n = re.sub(r"\.[Cc][Oo][Bb]$", "", n)
    return n.upper()


def _report_dir_to_original_name(report_dir: Path) -> str:
    """Extract the original program/job name (with extension) from a report dir name.

    TEST.CBL.report -> TEST.CBL
    TEST.jcl.report -> TEST.jcl
    """
    dirname = report_dir.name
    if dirname.endswith(".report"):
        return dirname[: -len(".report")]
    return dirname


def discover_reports(report_dirs: list[Path]) -> tuple[list[Path], list[Path]]:
    """Find all COBOL and JCL report directories across all search paths.

    Returns (cobol_reports, jcl_reports) where each is a list of Path objects
    pointing to report directories that contain the expected artifacts.
    """
    seen = set()
    cobol_reports = []
    jcl_reports = []

    for base_dir in report_dirs:
        if not base_dir.is_dir():
            continue
        for subdir in sorted(base_dir.iterdir()):
            if not subdir.is_dir() or not subdir.name.endswith(".report"):
                continue
            resolved = subdir.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)

            deps_yaml = subdir / "knowledge_base" / "03_Dependencies.yaml"
            jcl_summary = subdir / "jcl_summary.json"

            if deps_yaml.is_file():
                cobol_reports.append(subdir)
            elif jcl_summary.is_file():
                jcl_reports.append(subdir)

    return cobol_reports, jcl_reports


def build_corpus_registry(
    cobol_reports: list[Path], jcl_reports: list[Path]
) -> dict[str, Path]:
    """Map canonical program/job names to their report directories."""
    corpus: dict[str, Path] = {}

    for report_dir in cobol_reports:
        original = _report_dir_to_original_name(report_dir)
        canonical = normalize_program_name(original)
        if canonical in corpus:
            print(
                f"  Warning: duplicate canonical name '{canonical}' "
                f"({corpus[canonical].name} and {report_dir.name})"
            )
        corpus[canonical] = report_dir

    for report_dir in jcl_reports:
        original = _report_dir_to_original_name(report_dir)
        # Strip .jcl extension for JCL jobs
        canonical = re.sub(r"\.[Jj][Cc][Ll]$", "", original).upper()
        if canonical in corpus:
            print(
                f"  Warning: duplicate canonical name '{canonical}' "
                f"({corpus[canonical].name} and {report_dir.name})"
            )
        corpus[canonical] = report_dir

    return corpus


def parse_cobol_calls(
    cobol_reports: list[Path], verbose: bool
) -> list[dict]:
    """Extract CALLS edges from all COBOL 03_Dependencies.yaml files.

    Returns list of {"source": str, "target": str, "edge_type": "CALLS"} dicts.
    Source and target are canonical (uppercase, no extension) names.
    """
    edges = []
    seen_pairs: set[tuple[str, str]] = set()

    for report_dir in cobol_reports:
        deps_path = report_dir / "knowledge_base" / "03_Dependencies.yaml"
        try:
            with open(deps_path, "r") as f:
                data = yaml.safe_load(f)
        except Exception as e:
            print(f"  Warning: could not read {deps_path}: {e}")
            continue

        if not data or not isinstance(data, dict):
            continue

        program = data.get("program", "")
        source = normalize_program_name(program)
        if not source:
            continue

        calls = data.get("calls") or []
        for call_entry in calls:
            if isinstance(call_entry, dict):
                target_raw = call_entry.get("target", "")
            elif isinstance(call_entry, str):
                target_raw = call_entry
            else:
                continue

            target = normalize_program_name(target_raw)
            if not target:
                continue

            pair = (source, target)
            if pair not in seen_pairs:
                seen_pairs.add(pair)
                edges.append(
                    {"source": source, "target": target, "edge_type": "CALLS"}
                )
                if verbose:
                    print(f"  CALLS: {source} -> {target}")

    return edges


def parse_jcl_executes(
    jcl_reports: list[Path], verbose: bool
) -> tuple[list[dict], list[dict]]:
    """Extract EXECUTES edges and job metadata from all JCL reports.

    Returns (edges, jcl_jobs) where:
      edges: list of {"source": str, "target": str, "edge_type": "EXECUTES"}
      jcl_jobs: list of {"job_name": str, "steps": [str], "programs_invoked": [str]}
    """
    edges = []
    jcl_jobs = []
    seen_pairs: set[tuple[str, str]] = set()

    for report_dir in jcl_reports:
        summary_path = report_dir / "jcl_summary.json"
        steps_path = report_dir / "jcl_steps.json"

        try:
            with open(summary_path, "r") as f:
                summary = json.load(f)
        except Exception as e:
            print(f"  Warning: could not read {summary_path}: {e}")
            continue

        job_name = summary.get("job_name", "").upper()
        if not job_name:
            continue

        programs_invoked = summary.get("programs_invoked") or []
        programs_upper = [p.upper() for p in programs_invoked if p not in _SYSTEM_PGMS]

        # Read step names from jcl_steps.json
        step_names = []
        try:
            with open(steps_path, "r") as f:
                steps_data = json.load(f)
            step_names = [s.get("step_name", "") for s in steps_data if isinstance(s, dict)]
        except Exception:
            pass

        jcl_jobs.append(
            {
                "job_name": job_name,
                "steps": step_names,
                "programs_invoked": programs_upper,
            }
        )

        for pgm in programs_upper:
            pair = (job_name, pgm)
            if pair not in seen_pairs:
                seen_pairs.add(pair)
                edges.append(
                    {"source": job_name, "target": pgm, "edge_type": "EXECUTES"}
                )
                if verbose:
                    print(f"  EXECUTES: {job_name} -> {pgm}")

    return edges, jcl_jobs


def build_call_graph(
    cobol_edges: list[dict],
    jcl_edges: list[dict],
    jcl_jobs: list[dict],
    corpus: dict[str, Path],
    report_dirs: list[Path],
) -> dict:
    """Merge edges and compute reverse lookups.

    Returns the full cross_program_calls.json structure.
    """
    all_edges = cobol_edges + jcl_edges

    # Deduplicate edges by (source, target, edge_type)
    seen = set()
    unique_edges = []
    for e in all_edges:
        key = (e["source"], e["target"], e["edge_type"])
        if key not in seen:
            seen.add(key)
            unique_edges.append(e)

    # Seed programs with all in-corpus entries
    all_programs: dict[str, dict] = {}
    for canonical in corpus:
        all_programs[canonical] = {
            "name": canonical,
            "in_corpus": True,
            "calls": [],
            "called_by": [],
        }

    # Add programs from edges that aren't in corpus
    for e in unique_edges:
        for name in (e["source"], e["target"]):
            if name not in all_programs:
                all_programs[name] = {
                    "name": name,
                    "in_corpus": name in corpus,
                    "calls": [],
                    "called_by": [],
                }

    # Build forward and reverse maps
    for e in unique_edges:
        src, tgt, etype = e["source"], e["target"], e["edge_type"]
        if tgt not in all_programs[src]["calls"]:
            all_programs[src]["calls"].append(tgt)
        all_programs[tgt]["called_by"].append(
            {"source": src, "edge_type": etype}
        )

    # Classify entry_type
    for prog in all_programs.values():
        edge_types_targeting = {cb["edge_type"] for cb in prog["called_by"]}
        if "CALLS" in edge_types_targeting and "EXECUTES" in edge_types_targeting:
            prog["entry_type"] = "both"
        elif "EXECUTES" in edge_types_targeting:
            prog["entry_type"] = "jcl_only"
        elif "CALLS" in edge_types_targeting:
            prog["entry_type"] = "call_only"
        else:
            prog["entry_type"] = "none"

    # External targets
    external_targets = sorted(
        name for name, p in all_programs.items() if not p["in_corpus"]
    )

    # Summary counts
    cobol_count = sum(1 for e in unique_edges if e["edge_type"] == "CALLS")
    jcl_count = sum(1 for e in unique_edges if e["edge_type"] == "EXECUTES")
    in_corpus_count = sum(1 for p in all_programs.values() if p["in_corpus"])

    programs_list = sorted(all_programs.values(), key=lambda p: p["name"])

    return {
        "generated": datetime.now().isoformat(timespec="seconds"),
        "report_dirs": [str(d) for d in report_dirs],
        "programs": programs_list,
        "edges": unique_edges,
        "jcl_jobs": jcl_jobs,
        "external_targets": external_targets,
        "summary": {
            "total_programs": len(all_programs),
            "in_corpus": in_corpus_count,
            "external": len(external_targets),
            "cobol_call_edges": cobol_count,
            "jcl_exec_edges": jcl_count,
            "total_edges": len(unique_edges),
        },
    }


def update_program_summary_chunks(
    graph: dict, corpus: dict[str, Path], verbose: bool
) -> int:
    """Add called_by and entry_type to program_summary chunk metadata.

    Returns count of updated chunks.
    """
    updated = 0
    programs_by_name = {p["name"]: p for p in graph["programs"]}

    for canonical, report_dir in corpus.items():
        prog = programs_by_name.get(canonical)
        if not prog:
            continue

        chunks_dir = report_dir / "chunks"
        if not chunks_dir.is_dir():
            if verbose:
                print(f"  Skip chunk update for {canonical}: no chunks/ directory")
            continue

        # Derive original name from report dir to find the chunk file
        original_name = _report_dir_to_original_name(report_dir)
        # Strip .jcl for JCL reports
        if original_name.lower().endswith(".jcl"):
            continue  # JCL reports don't have program_summary chunks

        chunk_file = chunks_dir / f"{original_name}__program_summary.json"
        if not chunk_file.is_file():
            if verbose:
                print(f"  Skip chunk update for {canonical}: {chunk_file.name} not found")
            continue

        try:
            with open(chunk_file, "r") as f:
                chunk_data = json.load(f)
        except Exception as e:
            print(f"  Warning: could not read {chunk_file}: {e}")
            continue

        metadata = chunk_data.get("metadata", {})
        metadata["called_by"] = prog["called_by"]
        metadata["entry_type"] = prog["entry_type"]
        chunk_data["metadata"] = metadata

        try:
            with open(chunk_file, "w") as f:
                json.dump(chunk_data, f, indent=2, ensure_ascii=False)
                f.write("\n")
        except Exception as e:
            print(f"  Warning: could not write {chunk_file}: {e}")
            continue

        updated += 1
        if verbose:
            print(
                f"  Updated {chunk_file.name}: "
                f"entry_type={prog['entry_type']}, "
                f"called_by={len(prog['called_by'])} entries"
            )

    return updated


def write_output(graph: dict, output_path: Path, verbose: bool) -> None:
    """Write cross_program_calls.json."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(graph, f, indent=2, ensure_ascii=False)
        f.write("\n")
    if verbose:
        print(f"  Wrote {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Build cross-program call graph from COBOL + JCL reports",
    )
    parser.add_argument(
        "--report-dir",
        type=Path,
        action="append",
        dest="report_dirs",
        default=None,
        help="Report directory to scan (repeatable; default: out/report)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("out/cross_program_calls.json"),
        help="Output file path (default: out/cross_program_calls.json)",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument(
        "--no-update-chunks",
        action="store_true",
        help="Skip updating program_summary chunks",
    )
    args = parser.parse_args()

    if args.report_dirs is None:
        args.report_dirs = [Path("out/report")]

    # Validate directories exist
    for d in args.report_dirs:
        if not d.is_dir():
            print(f"Error: {d} is not a directory", file=sys.stderr)
            sys.exit(1)

    # Discovery
    print("Discovering reports...")
    cobol_reports, jcl_reports = discover_reports(args.report_dirs)
    print(f"  Found {len(cobol_reports)} COBOL reports, {len(jcl_reports)} JCL reports")

    if not cobol_reports and not jcl_reports:
        print("No reports found. Writing empty graph.")
        empty_graph = {
            "generated": datetime.now().isoformat(timespec="seconds"),
            "report_dirs": [str(d) for d in args.report_dirs],
            "programs": [],
            "edges": [],
            "jcl_jobs": [],
            "external_targets": [],
            "summary": {
                "total_programs": 0,
                "in_corpus": 0,
                "external": 0,
                "cobol_call_edges": 0,
                "jcl_exec_edges": 0,
                "total_edges": 0,
            },
        }
        write_output(empty_graph, args.output, args.verbose)
        return

    # Build corpus registry
    corpus = build_corpus_registry(cobol_reports, jcl_reports)
    if args.verbose:
        print(f"  Corpus: {len(corpus)} programs/jobs registered")

    # Parse COBOL calls
    print("Parsing COBOL dependencies...")
    cobol_edges = parse_cobol_calls(cobol_reports, args.verbose)
    print(f"  {len(cobol_edges)} CALLS edges")

    # Parse JCL executes
    print("Parsing JCL steps...")
    jcl_edges, jcl_jobs = parse_jcl_executes(jcl_reports, args.verbose)
    print(f"  {len(jcl_edges)} EXECUTES edges, {len(jcl_jobs)} jobs")

    # Build graph
    print("Building call graph...")
    graph = build_call_graph(
        cobol_edges, jcl_edges, jcl_jobs, corpus, args.report_dirs
    )

    # Write output
    write_output(graph, args.output, args.verbose)

    # Update chunks
    if not args.no_update_chunks:
        print("Updating program_summary chunks...")
        updated = update_program_summary_chunks(graph, corpus, args.verbose)
        print(f"  Updated {updated} chunks")

    # Print summary
    s = graph["summary"]
    print(
        f"\nCall graph: {s['total_programs']} programs, {s['total_edges']} edges "
        f"({s['cobol_call_edges']} CALLS + {s['jcl_exec_edges']} EXECUTES)"
    )
    print(f"In corpus: {s['in_corpus']}  |  External: {s['external']}")
    print(f"Output: {args.output}")


if __name__ == "__main__":
    main()
