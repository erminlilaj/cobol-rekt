#!/usr/bin/env python3
"""Read-only audit for reports that need chunk regeneration.

This does not mutate report directories. It only inspects each *.report/chunks
folder and explains why a report should be regenerated before indexing.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import chunk_pipeline


SKIP_CHUNK_JSON = {"chunks_manifest.json", "bm25_index.json"}


def _load_json(path: Path) -> tuple[object | None, str | None]:
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"unreadable_json:{path.name}:{exc}"


def audit_report(report_dir: Path, expected_schema: str) -> dict:
    """Return regeneration status for one *.report directory."""
    chunks_dir = report_dir / "chunks"
    reasons: list[str] = []
    chunk_files: list[Path] = []

    if not chunks_dir.is_dir():
        reasons.append("missing_chunks_dir")
    else:
        chunk_files = sorted(
            path for path in chunks_dir.glob("*.json")
            if path.name not in SKIP_CHUNK_JSON
        )
        if not chunk_files:
            reasons.append("no_chunk_json")

    manifest_path = chunks_dir / "chunks_manifest.json"
    manifest = None
    if not manifest_path.is_file():
        reasons.append("missing_chunks_manifest")
    else:
        manifest, error = _load_json(manifest_path)
        if error:
            reasons.append(error)
        elif isinstance(manifest, dict):
            schema = str(manifest.get("schema_version", "missing"))
            if schema != expected_schema:
                reasons.append(f"stale_manifest_schema:{schema}")
        else:
            reasons.append("invalid_manifest_shape")

    if isinstance(manifest, dict):
        for entry in manifest.get("chunks", []) or []:
            if not isinstance(entry, dict):
                reasons.append("invalid_manifest_entry")
                continue
            file_name = entry.get("file")
            if file_name and not (chunks_dir / str(file_name)).is_file():
                reasons.append(f"manifest_missing_chunk_file:{file_name}")

    stale_chunk_schemas = Counter()
    unreadable_chunks = 0
    for chunk_file in chunk_files:
        data, error = _load_json(chunk_file)
        if error:
            unreadable_chunks += 1
            continue
        if not isinstance(data, dict):
            unreadable_chunks += 1
            continue
        metadata = data.get("metadata", {})
        schema = "missing"
        if isinstance(metadata, dict):
            schema = str(metadata.get("schema_version", "missing"))
        if schema != expected_schema:
            stale_chunk_schemas[schema] += 1

    for schema, count in sorted(stale_chunk_schemas.items()):
        reasons.append(f"stale_chunk_schema:{schema}:{count}")
    if unreadable_chunks:
        reasons.append(f"unreadable_chunk_json:{unreadable_chunks}")

    return {
        "report": report_dir.name,
        "path": str(report_dir),
        "needs_regeneration": bool(reasons),
        "chunk_file_count": len(chunk_files),
        "reasons": reasons,
    }


def audit_reports(report_root: Path, expected_schema: str) -> list[dict]:
    return [
        audit_report(report_dir, expected_schema)
        for report_dir in sorted(report_root.glob("*.report"))
        if report_dir.is_dir()
    ]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only audit of report chunk regeneration needs.",
    )
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=Path("out/report"),
        help="Directory containing *.report folders.",
    )
    parser.add_argument(
        "--schema",
        default=chunk_pipeline.CHUNK_SCHEMA_VERSION,
        help="Expected chunk schema version.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print full JSON instead of a compact text report.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum report rows to print in text mode. Use 0 for all rows.",
    )
    args = parser.parse_args()

    results = audit_reports(args.report_dir, args.schema)
    needing = [item for item in results if item["needs_regeneration"]]

    if args.json:
        print(json.dumps({
            "report_dir": str(args.report_dir),
            "expected_schema": args.schema,
            "reports_checked": len(results),
            "reports_needing_regeneration": len(needing),
            "reports": results,
        }, indent=2))
        return 0

    reason_counts = Counter(
        reason.split(":", 1)[0]
        for item in needing
        for reason in item["reasons"]
    )
    print(f"Reports checked: {len(results)}")
    print(f"Need regeneration: {len(needing)}")
    if reason_counts:
        print("Reasons:")
        for reason, count in sorted(reason_counts.items()):
            print(f"- {reason}: {count}")
    if needing:
        print("\nReports:")
        shown = needing if args.limit == 0 else needing[:args.limit]
        for item in shown:
            print(f"- {item['report']}: {', '.join(item['reasons'])}")
        hidden = len(needing) - len(shown)
        if hidden > 0:
            print(f"... {hidden} more. Use --limit 0 or --json for the full list.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
