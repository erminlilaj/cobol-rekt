#!/usr/bin/env python3
"""
corpus_baseline.py — Read-only corpus snapshot for regression tracking.

Captures per-program parse quality, CFG metrics, dependency counts, and
construct presence from out/report, then diffs two snapshots to detect
regressions after Java parser changes or new extraction steps.

Usage:
    python3 corpus_baseline.py --report-dir out/report \
        --output baselines/baseline_pre_integration.json
    python3 corpus_baseline.py --diff baselines/baseline_a.json baselines/baseline_b.json
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

SCHEMA_VERSION = "1.0"

_REQUIRED_CHUNK_FIELDS = {"chunk_type", "chunk_id", "program", "schema_version"}


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def _git_sha(repo_path: str = ".") -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", repo_path, "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL,
        ).decode().strip()
    except Exception:
        return "unknown"


def _git_dirty(repo_path: str = ".") -> bool:
    try:
        out = subprocess.check_output(
            ["git", "-C", repo_path, "status", "--porcelain"],
            stderr=subprocess.DEVNULL,
        ).decode().strip()
        return bool(out)
    except Exception:
        return False


def _submodule_sha(submodule_name: str) -> str:
    try:
        line = subprocess.check_output(
            ["git", "submodule", "status", submodule_name],
            stderr=subprocess.DEVNULL,
        ).decode().strip()
        return line.lstrip(" -+").split()[0]
    except Exception:
        return "unknown"


# ---------------------------------------------------------------------------
# JSON / YAML readers (never raise)
# ---------------------------------------------------------------------------

def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _read_yaml(path: Path) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Per-program extractors
# ---------------------------------------------------------------------------

def _pipeline_info(report_dir: Path) -> dict:
    pr = _read_json(report_dir / "pipeline_report.json")
    if not pr:
        return {"overall_status": "unknown", "failed_steps": [], "step_statuses": {}}
    steps = pr.get("steps", [])
    return {
        "overall_status": pr.get("overall_status", "unknown"),
        "failed_steps": [s["name"] for s in steps if s.get("status") not in ("success", "skipped")],
        "step_statuses": {s["name"]: s.get("status", "unknown") for s in steps},
    }


def _parse_info(report_dir: Path) -> dict:
    pd = _read_json(report_dir / "parse_diagnostics.json")
    if not pd:
        return {
            "mode": "unknown",
            "source_lines": 0,
            "total_tree_nodes": 0,
            "coverage_percentage": 0.0,
            "error_count": 0,
            "affected_line_count": 0,
            "null_location_errors": 0,
            "error_summary": {},
            "data_structures_degraded": False,
        }
    return {
        "mode": pd.get("mode", "unknown"),
        "source_lines": pd.get("source_lines", 0),
        "total_tree_nodes": pd.get("total_tree_nodes", 0),
        "coverage_percentage": float(pd.get("coverage_percentage", 0.0)),
        "error_count": pd.get("error_summary", {}).get("total_errors", len(pd.get("errors", []))),
        "affected_line_count": pd.get("affected_lines", 0),
        "null_location_errors": pd.get("null_location_errors", 0),
        "error_summary": pd.get("error_summary", {}),
        "data_structures_degraded": bool(pd.get("data_structures_degraded", False)),
    }


def _self_eval_info(report_dir: Path) -> dict:
    se = _read_json(report_dir / "analysis_self_evaluation.json")
    if not se:
        return {
            "base_analysis_succeeded": None,
            "artifact_presence": {},
            "primary_failure": None,
            "cfg_node_count": 0,
            "cfg_edge_count": 0,
            "cfg_node_counts_by_type": {},
        }
    cfg = se.get("cfg_metrics", {})
    # primary_failure is surfaced as a warning with a diagnostic_code field
    primary_failure = None
    for w in se.get("warnings", []):
        if "diagnostic_code" in w or w.get("code", "").startswith("MISSING_") or w.get("code") == "BASE_MODEL_NULL_STRUCTURE":
            primary_failure = w
            break
    return {
        "base_analysis_succeeded": se.get("base_analysis_succeeded"),
        "artifact_presence": se.get("artifact_presence", {}),
        "primary_failure": primary_failure,
        "cfg_node_count": cfg.get("node_count", 0),
        "cfg_edge_count": cfg.get("edge_count", 0),
        "cfg_node_counts_by_type": cfg.get("node_counts_by_type", {}),
    }


def _dependencies_info(report_dir: Path) -> dict:
    deps = _read_yaml(report_dir / "knowledge_base" / "03_Dependencies.yaml")
    if not deps:
        return {
            "tables_read_count": 0,
            "tables_updated_count": 0,
            "sql_statement_count": 0,
            "cics_command_count": 0,
            "cics_operation_count": 0,
            "ims_dependency_count": 0,
            "call_count": 0,
            "copybook_count": 0,
        }
    db = deps.get("database") or {}
    return {
        "tables_read_count": len(db.get("tables_read") or []),
        "tables_updated_count": len(db.get("tables_updated") or []),
        "sql_statement_count": len(db.get("sql_statements") or []),
        "cics_command_count": len(deps.get("cics") or []),
        "cics_operation_count": len(deps.get("cics_operations") or []),
        "ims_dependency_count": len(deps.get("ims") or []),
        "call_count": len(deps.get("calls") or []),
        "copybook_count": 0,  # filled from manifest below
    }


def _copybook_info(report_dir: Path) -> dict:
    cm = _read_json(report_dir / "copybook_manifest.json")
    if not cm:
        return {"total": 0, "resolved": 0, "stubbed": 0, "resolution_pct": 0.0, "contains_replacing": False}
    summary = cm.get("summary", {})
    total = summary.get("total_copybooks", len(cm.get("copybooks", {})))
    resolved = summary.get("resolved", 0)
    stubbed = summary.get("stubbed", 0)
    resolution_pct = float(summary.get("resolved_percentage", 0.0))
    # Detect COPY REPLACING from cobol_structure.json
    cs = _read_json(report_dir / "cobol_structure.json")
    has_replacing = any(
        bool(stmt.get("replacing"))
        for stmt in cs.get("copy_statements", [])
    )
    return {
        "total": total,
        "resolved": resolved,
        "stubbed": stubbed,
        "resolution_pct": resolution_pct,
        "contains_replacing": has_replacing,
    }


def _chunks_info(report_dir: Path) -> dict:
    chunks_dir = report_dir / "chunks"
    empty = {
        "schema_version": "unknown",
        "total_chunks": 0,
        "type_counts": {},
        "oversized_count": 0,
        "thin_count": 0,
        "missing_required_metadata_count": 0,
    }
    if not chunks_dir.exists():
        return empty
    chunk_files = [f for f in chunks_dir.glob("*.json") if f.name != "bm25_index.json"]
    if not chunk_files:
        return empty

    type_counts: dict = {}
    oversized = thin = missing_meta = 0
    schema_version = "unknown"

    for cf in chunk_files:
        c = _read_json(cf)
        meta = c.get("metadata", {})
        if schema_version == "unknown":
            schema_version = meta.get("schema_version", "unknown")
        ct = meta.get("chunk_type", "unknown")
        type_counts[ct] = type_counts.get(ct, 0) + 1
        bpe = meta.get("token_count_bpe", 0) or 0
        if bpe > 512:
            oversized += 1
        if bpe > 0 and bpe < 20:
            thin += 1
        if not _REQUIRED_CHUNK_FIELDS.issubset(meta.keys()):
            missing_meta += 1

    return {
        "schema_version": schema_version,
        "total_chunks": len(chunk_files),
        "type_counts": type_counts,
        "oversized_count": oversized,
        "thin_count": thin,
        "missing_required_metadata_count": missing_meta,
    }


def _constructs_info(report_dir: Path) -> dict:
    cfg_dir = report_dir / "cfg"
    if not cfg_dir.exists():
        return {
            "has_evaluate": False,
            "has_exec_dli": False,
            "has_dialect_nodes": False,
            "has_dialect_dli_overlap": False,
        }
    has_evaluate = has_exec_dli = has_dialect_nodes = False
    for cf in cfg_dir.glob("*.json"):
        d = _read_json(cf)
        for node in d.get("nodes", []):
            ntype = node.get("type", "")
            orig = node.get("originalText", "")
            if ntype == "EVALUATE":
                has_evaluate = True
            if ntype == "DIALECT":
                has_dialect_nodes = True
            if "EXEC DLI" in orig:
                has_exec_dli = True
        if has_evaluate and has_exec_dli and has_dialect_nodes:
            break  # no need to scan further
    return {
        "has_evaluate": has_evaluate,
        "has_exec_dli": has_exec_dli,
        "has_dialect_nodes": has_dialect_nodes,
        "has_dialect_dli_overlap": has_dialect_nodes and has_exec_dli,
    }


# ---------------------------------------------------------------------------
# Program record assembly
# ---------------------------------------------------------------------------

def collect_program(report_dir: Path) -> dict:
    program_name = report_dir.name.removesuffix(".report")
    pipeline = _pipeline_info(report_dir)
    parse = _parse_info(report_dir)
    self_eval = _self_eval_info(report_dir)
    deps = _dependencies_info(report_dir)
    copybooks = _copybook_info(report_dir)
    deps["copybook_count"] = copybooks["total"]
    chunks = _chunks_info(report_dir)
    constructs = _constructs_info(report_dir)
    return {
        "program": program_name,
        "report_dir": str(report_dir),
        "pipeline": pipeline,
        "parse": parse,
        "self_evaluation": self_eval,
        "dependencies": deps,
        "copybooks": copybooks,
        "chunks": chunks,
        "constructs": constructs,
    }


# ---------------------------------------------------------------------------
# Baseline builder
# ---------------------------------------------------------------------------

def build_baseline(report_dir: Path, output: Path) -> dict:
    report_dirs = sorted(
        d for d in report_dir.iterdir() if d.is_dir() and d.name.endswith(".report")
    )

    programs = []
    for i, d in enumerate(report_dirs, 1):
        programs.append(collect_program(d))
        if i % 50 == 0:
            print(f"  {i}/{len(report_dirs)} ...", file=sys.stderr)

    # Artifact presence counts
    def _has_file(rel: str) -> int:
        return sum(1 for p in programs if (Path(p["report_dir"]) / rel).exists())

    def _has_cfg(p: dict) -> bool:
        cfg = Path(p["report_dir"]) / "cfg"
        return cfg.exists() and any(cfg.glob("*.json"))

    artifact_counts = {
        "parse_diagnostics": _has_file("parse_diagnostics.json"),
        "analysis_self_evaluation": _has_file("analysis_self_evaluation.json"),
        "dependencies_yaml": sum(
            1 for p in programs
            if (Path(p["report_dir"]) / "knowledge_base" / "03_Dependencies.yaml").exists()
        ),
        "chunks_manifest": sum(
            1 for p in programs if p["chunks"]["total_chunks"] > 0
        ),
        "cfg_json": sum(1 for p in programs if _has_cfg(p)),
    }

    # Aggregates
    parse_error_total = sum(p["parse"]["error_count"] for p in programs)
    programs_with_evaluate = sum(1 for p in programs if p["constructs"]["has_evaluate"])
    programs_with_exec_dli = sum(1 for p in programs if p["constructs"]["has_exec_dli"])
    programs_with_copy_replacing = sum(1 for p in programs if p["copybooks"]["contains_replacing"])
    programs_with_dialect_dli_overlap = sum(
        1 for p in programs if p["constructs"]["has_dialect_dli_overlap"]
    )

    agg_chunk_types: dict = {}
    for p in programs:
        for ct, cnt in p["chunks"]["type_counts"].items():
            agg_chunk_types[ct] = agg_chunk_types.get(ct, 0) + cnt

    agg_cfg_types: dict = {}
    for p in programs:
        for nt, cnt in p["self_evaluation"]["cfg_node_counts_by_type"].items():
            agg_cfg_types[nt] = agg_cfg_types.get(nt, 0) + cnt

    baseline = {
        "schema_version": SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "repo": {
            "cobol_rekt_commit": _git_sha("."),
            "che4z_commit": _submodule_sha("che-che4z-lsp-for-cobol-integration"),
            "mojo_common_commit": _submodule_sha("mojo-common"),
            "woof_commit": _submodule_sha("woof"),
            "dirty": _git_dirty("."),
        },
        "corpus": {
            "report_dir": str(report_dir),
            "program_count": len(programs),
            "artifact_counts": artifact_counts,
        },
        "programs": programs,
        "aggregate": {
            "parse_error_total": parse_error_total,
            "programs_with_evaluate": programs_with_evaluate,
            "programs_with_exec_dli": programs_with_exec_dli,
            "programs_with_copy_replacing": programs_with_copy_replacing,
            "programs_with_dialect_dli_overlap": programs_with_dialect_dli_overlap,
            "chunk_type_counts": agg_chunk_types,
            "cfg_node_counts_by_type": agg_cfg_types,
        },
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(baseline, indent=2), encoding="utf-8")
    print(
        f"Baseline written → {output}  ({len(programs)} programs, "
        f"{artifact_counts['cfg_json']} with CFG, "
        f"{artifact_counts['chunks_manifest']} with chunks)"
    )
    return baseline


# ---------------------------------------------------------------------------
# Diff engine
# ---------------------------------------------------------------------------

def diff_baselines(path_a: Path, path_b: Path) -> int:
    a = json.loads(path_a.read_text(encoding="utf-8"))
    b = json.loads(path_b.read_text(encoding="utf-8"))

    progs_a = {p["program"]: p for p in a.get("programs", [])}
    progs_b = {p["program"]: p for p in b.get("programs", [])}

    added = sorted(set(progs_b) - set(progs_a))
    removed = sorted(set(progs_a) - set(progs_b))
    changed = []

    for prog in sorted(set(progs_a) & set(progs_b)):
        pa, pb = progs_a[prog], progs_b[prog]
        diffs = []

        # Parse coverage (regression = decrease)
        cov_a = pa["parse"]["coverage_percentage"]
        cov_b = pb["parse"]["coverage_percentage"]
        if abs(cov_a - cov_b) > 0.01:
            direction = "REGRESSION" if cov_b < cov_a else "improvement"
            diffs.append(f"parse.coverage_percentage: {cov_a:.2f} -> {cov_b:.2f}  [{direction}]")

        # Parse errors (regression = increase)
        err_a = pa["parse"]["error_count"]
        err_b = pb["parse"]["error_count"]
        if err_a != err_b:
            direction = "REGRESSION" if err_b > err_a else "improvement"
            diffs.append(f"parse.error_count: {err_a} -> {err_b}  [{direction}]")

        # Base analysis succeeded (regression = false when was true)
        bsa_a = pa["self_evaluation"]["base_analysis_succeeded"]
        bsa_b = pb["self_evaluation"]["base_analysis_succeeded"]
        if bsa_a != bsa_b:
            direction = "REGRESSION" if (bsa_a is True and bsa_b is not True) else "change"
            diffs.append(f"base_analysis_succeeded: {bsa_a} -> {bsa_b}  [{direction}]")

        # CFG node count
        nc_a = pa["self_evaluation"]["cfg_node_count"]
        nc_b = pb["self_evaluation"]["cfg_node_count"]
        if nc_a != nc_b:
            diffs.append(f"cfg_node_count: {nc_a} -> {nc_b}")

        # IMS / CICS structured counts
        for field in ("ims_dependency_count", "cics_operation_count", "cics_command_count"):
            va = pa["dependencies"][field]
            vb = pb["dependencies"][field]
            if va != vb:
                diffs.append(f"dependencies.{field}: {va} -> {vb}")

        # Chunk count
        ca = pa["chunks"]["total_chunks"]
        cb = pb["chunks"]["total_chunks"]
        if ca != cb:
            diffs.append(f"chunks.total_chunks: {ca} -> {cb}")

        # Constructs
        for key in ("has_evaluate", "has_exec_dli", "has_dialect_nodes"):
            va = pa["constructs"][key]
            vb = pb["constructs"][key]
            if va != vb:
                diffs.append(f"constructs.{key}: {va} -> {vb}")

        if diffs:
            changed.append({"program": prog, "changes": diffs})

    # Aggregate diffs
    agg_a = a.get("aggregate", {})
    agg_b = b.get("aggregate", {})
    agg_diffs = []
    for key in (
        "parse_error_total",
        "programs_with_evaluate",
        "programs_with_exec_dli",
        "programs_with_copy_replacing",
        "programs_with_dialect_dli_overlap",
    ):
        va = agg_a.get(key, 0)
        vb = agg_b.get(key, 0)
        if va != vb:
            agg_diffs.append(f"{key}: {va} -> {vb}")

    # Regression summary (any parse coverage drop or base_analysis_succeeded loss)
    regressions = [
        item for item in changed
        if any("REGRESSION" in ch for ch in item["changes"])
    ]

    # Output
    print(f"Baseline diff: {path_a.name}  →  {path_b.name}")
    print(f"  Added programs:    {len(added)}")
    print(f"  Removed programs:  {len(removed)}")
    print(f"  Changed programs:  {len(changed)}")
    print(f"  Regressions:       {len(regressions)}")
    print()

    if added:
        print("Added programs:")
        for p in added:
            print(f"  + {p}")
        print()

    if removed:
        print("Removed programs:")
        for p in removed:
            print(f"  - {p}")
        print()

    if regressions:
        print("REGRESSIONS (parse coverage drop or base_analysis_succeeded loss):")
        for item in regressions:
            print(f"  {item['program']}:")
            for ch in item["changes"]:
                if "REGRESSION" in ch:
                    print(f"    *** {ch}")
        print()

    if changed:
        print("All changed programs:")
        for item in changed:
            print(f"  {item['program']}:")
            for ch in item["changes"]:
                print(f"    {ch}")
        print()

    if agg_diffs:
        print("Aggregate changes:")
        for d in agg_diffs:
            print(f"  {d}")
        print()

    total_changes = len(added) + len(removed) + len(changed)
    if total_changes == 0 and not agg_diffs:
        print("No changes detected.")

    return 1 if regressions else 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Corpus baseline snapshot and diff tool for cobol-rekt",
    )
    parser.add_argument(
        "--report-dir",
        default="out/report",
        help="Directory containing <program>.report/ subdirectories (default: out/report)",
    )
    parser.add_argument(
        "--output",
        help="Write baseline JSON to this path (required unless --diff is used)",
    )
    parser.add_argument(
        "--diff",
        nargs=2,
        metavar=("BASELINE_A", "BASELINE_B"),
        help="Diff two baseline JSON files and print a change report",
    )
    args = parser.parse_args()

    if args.diff:
        sys.exit(diff_baselines(Path(args.diff[0]), Path(args.diff[1])))

    if not args.output:
        parser.error("--output is required when not using --diff")

    build_baseline(Path(args.report_dir), Path(args.output))


if __name__ == "__main__":
    main()
