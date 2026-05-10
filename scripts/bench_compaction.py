#!/usr/bin/env python3
"""Deterministic chunk compaction benchmark harness for proposal 0006."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURES = REPO_ROOT / "scripts" / "bench_fixtures.json"
DEFAULT_QUERIES = REPO_ROOT / "scripts" / "bench_queries.json"
DEFAULT_OUTPUT_JSON = REPO_ROOT / "scripts" / "bench_results.json"
DEFAULT_OUTPUT_MD = REPO_ROOT / "scripts" / "bench_results.md"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _source_stats(source_path: Path) -> dict:
    text = source_path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    return {
        "line_count": len(lines),
        "has_cics": "EXEC CICS" in text.upper(),
        "has_sql": "EXEC SQL" in text.upper(),
    }


def _write_synthetic_report(root: Path, source_path: Path) -> Path:
    program = source_path.name
    stats = _source_stats(source_path)
    report_dir = root / f"{program}.report"
    kb_dir = report_dir / "knowledge_base"
    cfg_dir = report_dir / "cfg"
    ds_dir = report_dir / "data_structures"
    kb_dir.mkdir(parents=True)
    cfg_dir.mkdir()
    ds_dir.mkdir()

    complexity = max(1, stats["line_count"] // 75)
    (kb_dir / "00_Executive_Summary.md").write_text(
        "| Metric | Value |\n"
        "|---|---|\n"
        f"| Total CFG Nodes | {stats['line_count']} |\n"
        f"| Total Edges | {max(1, stats['line_count'] - 1)} |\n"
        "| Variables Defined | 2 |\n"
        f"| Complexity Score | {complexity} |\n",
        encoding="utf-8",
    )
    (kb_dir / "01_Logic_Narrative.md").write_text(
        "## Program Overview\n"
        f"Synthetic benchmark report for {program} with {stats['line_count']} source lines.\n\n"
        "## PROCESS-MAIN\n"
        "- `PERFORM PROCESS-DETAIL.`\n"
        "PROCESS-MAIN coordinates benchmark control flow and preserves enough "
        "retrieval text for default profile paragraph logic.\n\n"
        "## PROCESS-DETAIL\n"
        "- `DISPLAY WS-FIELD.`\n"
        "PROCESS-DETAIL records deterministic fixture facts for benchmark retrieval.\n",
        encoding="utf-8",
    )
    deps = ["program: " + program]
    if stats["has_sql"]:
        deps.append("database:\n  tables_read:\n    - BENCH_TABLE\n  tables_updated: []\n  sql_statements:\n    - SELECT")
    else:
        deps.append("database:\n  tables_read: []\n  tables_updated: []\n  sql_statements: []")
    deps.append("calls: []")
    if stats["has_cics"]:
        deps.append("cics:\n  - HANDLE\n  - LINK")
    else:
        deps.append("cics: []")
    (kb_dir / "03_Dependencies.yaml").write_text("\n".join(deps) + "\n", encoding="utf-8")
    nodes = [
        {"id": "p1", "type": "PARAGRAPH", "name": "PROCESS-MAIN"},
        {"id": "p2", "type": "PARAGRAPH", "name": "PROCESS-DETAIL"},
        {"id": "s1", "type": "STATEMENT", "name": "PERFORM", "originalText": "PERFORM PROCESS-DETAIL"},
        {"id": "s2", "type": "STATEMENT", "name": "DISPLAY", "originalText": "DISPLAY WS-FIELD"},
    ]
    if stats["has_cics"]:
        nodes.append({
            "id": "c1",
            "type": "DIALECT",
            "originalText": "EXEC CICS HANDLE CONDITION ERROR(PROCESS-DETAIL)",
            "metadata": {
                "cics_command": "HANDLE",
                "cics_operation_type": "error_handler",
                "paragraph": "PROCESS-MAIN",
            },
        })
    edges = [
        {"fromNodeID": "p1", "toNodeID": "s1", "edgeType": "STARTS_WITH"},
        {"fromNodeID": "s1", "toNodeID": "p2", "edgeType": "JUMPS_TO", "toLabel": "PROCESS-DETAIL", "evidence": "PERFORM PROCESS-DETAIL"},
        {"fromNodeID": "p2", "toNodeID": "s2", "edgeType": "STARTS_WITH"},
    ]
    (cfg_dir / f"cfg-{program}.json").write_text(
        json.dumps({"nodes": nodes, "edges": edges}, indent=2),
        encoding="utf-8",
    )
    (ds_dir / f"{program}-data.json").write_text(
        json.dumps({
            "children": [
                {
                    "levelNumber": 1,
                    "name": "BENCH-REC",
                    "sourceSection": "WORKING_STORAGE",
                    "children": [
                        {"levelNumber": 5, "name": "WS-FIELD", "rawText": "05 WS-FIELD PIC X(10)."}
                    ],
                }
            ]
        }, indent=2),
        encoding="utf-8",
    )
    return report_dir


def _run_chunk_pipeline(report_dir: Path, profile: str, label_boost: float) -> None:
    subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "chunk_pipeline.py"),
            str(report_dir),
            "--profile",
            profile,
            "--label-boost",
            str(label_boost),
            "--token-counter",
            "whitespace",
        ],
        cwd=REPO_ROOT,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _measure(chunks_dir: Path) -> dict:
    manifest = json.loads((chunks_dir / "chunks_manifest.json").read_text(encoding="utf-8"))
    bm25_path = chunks_dir / "bm25_index.json"
    bm25 = json.loads(bm25_path.read_text(encoding="utf-8"))
    token_counts = []
    for chunk_file in sorted(chunks_dir.glob("*.json")):
        if chunk_file.name in {"chunks_manifest.json", "bm25_index.json"}:
            continue
        chunk = json.loads(chunk_file.read_text(encoding="utf-8"))
        token_counts.append(len(str(chunk.get("text", "")).split()))
    return {
        "chunk_count": int(manifest["total_chunks"]),
        "total_bpe_tokens": int(sum(token_counts)),
        "max_bpe_per_chunk": int(max(token_counts) if token_counts else 0),
        "duplicate_content_hash_count": int(manifest.get("duplicate_content_hashes", 0)),
        "bm25_index_entry_count": int(len(bm25.get("entries", []))),
    }


def _benchmark_fixture(fixture: dict, label_boost: float) -> dict:
    source_path = REPO_ROOT / fixture["source_path"]
    expected_hash = fixture["sha256"]
    actual_hash = _sha256(source_path)
    if actual_hash != expected_hash:
        raise SystemExit(
            f"Fixture checksum drift for {fixture['source_path']}: "
            f"expected {expected_hash}, got {actual_hash}"
        )

    profiles = {}
    with tempfile.TemporaryDirectory(prefix="cobol-rekt-bench-") as td:
        temp_root = Path(td)
        for profile in ("default", "facts-only"):
            report_dir = _write_synthetic_report(temp_root / profile, source_path)
            _run_chunk_pipeline(report_dir, profile, label_boost)
            profiles[profile] = _measure(report_dir / "chunks")
    return {
        "name": fixture["name"],
        "source_path": fixture["source_path"],
        "size_class": fixture["size_class"],
        "profiles": profiles,
    }


def _assert_no_chunk_count_increase(fixtures: list[dict], results: list[dict]) -> None:
    fixture_by_name = {fixture["name"]: fixture for fixture in fixtures}
    for result in results:
        expected = fixture_by_name[result["name"]].get("baseline_expectations", {})
        for profile, metrics in result["profiles"].items():
            baseline = expected.get(profile, {}).get("chunk_count")
            if baseline is None:
                continue
            if metrics["chunk_count"] > baseline:
                raise SystemExit(
                    f"{result['name']} {profile} chunk_count increased: "
                    f"{metrics['chunk_count']} > {baseline}"
                )


def _aggregate(results: list[dict], profile: str) -> dict:
    keys = [
        "chunk_count",
        "total_bpe_tokens",
        "max_bpe_per_chunk",
        "duplicate_content_hash_count",
        "bm25_index_entry_count",
    ]
    aggregate = {key: 0 for key in keys}
    for result in results:
        metrics = result["profiles"][profile]
        for key in keys:
            if key == "max_bpe_per_chunk":
                aggregate[key] = max(aggregate[key], metrics[key])
            else:
                aggregate[key] += metrics[key]
    return aggregate


def _markdown_table(results: list[dict]) -> str:
    rows = [
        "| fixture | profile | chunks | total_bpe_tokens | max_bpe_per_chunk | duplicate_hashes | bm25_entries |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for result in results:
        for profile in ("default", "facts-only"):
            metrics = result["profiles"][profile]
            rows.append(
                f"| {result['name']} | {profile} | {metrics['chunk_count']} | "
                f"{metrics['total_bpe_tokens']} | {metrics['max_bpe_per_chunk']} | "
                f"{metrics['duplicate_content_hash_count']} | {metrics['bm25_index_entry_count']} |"
            )
    for profile in ("default", "facts-only"):
        metrics = _aggregate(results, profile)
        rows.append(
            f"| aggregate | {profile} | {metrics['chunk_count']} | "
            f"{metrics['total_bpe_tokens']} | {metrics['max_bpe_per_chunk']} | "
            f"{metrics['duplicate_content_hash_count']} | {metrics['bm25_index_entry_count']} |"
        )
    return "\n".join(rows) + "\n"


def run_benchmark(fixtures_path: Path, queries_path: Path,
                  output_json: Path, output_md: Path,
                  label_boost: float) -> dict:
    fixtures_data = json.loads(fixtures_path.read_text(encoding="utf-8"))
    queries_data = json.loads(queries_path.read_text(encoding="utf-8"))
    fixtures = fixtures_data["fixtures"]
    results = [_benchmark_fixture(fixture, label_boost) for fixture in fixtures]
    _assert_no_chunk_count_increase(fixtures, results)
    output = {
        "baseline_branch": fixtures_data["baseline_branch"],
        "baseline_sha": fixtures_data["baseline_sha"],
        "label_boost": float(label_boost),
        "query_count": len(queries_data["queries"]),
        "results": results,
    }
    _atomic_write(output_json, json.dumps(output, indent=2, sort_keys=True) + "\n")
    _atomic_write(output_md, _markdown_table(results))
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Run proposal 0006 compaction benchmark")
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    parser.add_argument("--queries", type=Path, default=DEFAULT_QUERIES)
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--output-md", type=Path, default=DEFAULT_OUTPUT_MD)
    parser.add_argument("--label-boost", type=float, default=1.0)
    args = parser.parse_args()
    run_benchmark(args.fixtures, args.queries, args.output_json, args.output_md, args.label_boost)
    print(args.output_md.read_text(encoding="utf-8"), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
