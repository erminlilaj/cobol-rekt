#!/usr/bin/env python3
"""
validate_chunks.py — Phase 1 gate: structural integrity checks for all generated chunks.

Checks:
  1. Required fields: schema_version, pipeline_version, analysis_timestamp, content_hash
  2. Hash determinism: sha256(text)[:16] matches stored content_hash
  3. Token limit: no chunk text exceeds --max-tokens (BPE if tiktoken available, else whitespace)
  4. Cross-reference integrity: every chunk_id in cross-ref fields resolves in some manifest
  5. Index consistency: corpus_index.json programs match directories with program_summary chunks

Exit code 0 = all checks pass. Exit code 1 = failures found.

Usage:
    python3 validate_chunks.py
    python3 validate_chunks.py --report-dir out/report --max-tokens 512 -v
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Token counter (same logic as chunk_pipeline.py)
# ---------------------------------------------------------------------------
try:
    import tiktoken as _tiktoken
    _BPE_ENC = _tiktoken.get_encoding("cl100k_base")
    def _count(text: str) -> int:
        return len(_BPE_ENC.encode(text))
    _COUNTER_LABEL = "BPE"
except ImportError:
    _BPE_ENC = None
    def _count(text: str) -> int:
        return len(text.split())
    _COUNTER_LABEL = "whitespace"


REQUIRED_FIELDS = {"schema_version", "pipeline_version", "analysis_timestamp", "content_hash"}
SUPPORTED_SCHEMA_VERSIONS = {"1.3", "1.4"}

# All known chunk types as of schema 1.3
VALID_COBOL_CHUNK_TYPES = {
    "program_summary", "dependencies", "paragraph_logic", "variable_group",
    "analysis_health", "cobol_analysis_health", "section_summary", "workflow",
    "business_rules", "sql_operation", "cics_operations", "static_values",
}
VALID_JCL_CHUNK_TYPES = {
    "job_flow", "step_detail",
    "jcl_cobol_overview", "jcl_cobol_step_relationship", "jcl_dataset_flow",
    "jcl_analysis_health", "jcl_condition_flow", "analysis_health",
    "condition_flow",
}
VALID_CHUNK_TYPES = VALID_COBOL_CHUNK_TYPES | VALID_JCL_CHUNK_TYPES

# Cross-reference fields that should contain chunk_ids (not bare strings)
XREF_FIELDS = {"parent_program_chunk", "calls", "related_cobol_chunks",
               "paragraph_chunks", "variable_group_chunks", "related_variable_groups"}


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def _load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"  [WARN] Failed to load JSON {path}: {e}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# Check helpers
# ---------------------------------------------------------------------------

def _check_required_fields(meta: dict, chunk_id: str, errors: list) -> None:
    for field in REQUIRED_FIELDS:
        if field not in meta:
            errors.append(f"  MISSING_FIELD  {chunk_id}: '{field}' absent from metadata")


def _check_hash(text: str, meta: dict, chunk_id: str, errors: list) -> None:
    stored = meta.get("content_hash")
    if stored is None:
        return  # already caught by required-fields check
    expected = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    if stored != expected:
        errors.append(f"  HASH_MISMATCH  {chunk_id}: stored={stored} expected={expected}")


def _check_chunk_type(meta: dict, chunk_id: str, warnings: list) -> None:
    ct = meta.get("chunk_type", "")
    if ct and ct not in VALID_CHUNK_TYPES:
        warnings.append(f"  UNKNOWN_TYPE   {chunk_id}: unrecognized chunk_type '{ct}'")


def _check_schema_version(meta: dict, chunk_id: str, warnings: list) -> None:
    version = meta.get("schema_version")
    if version and version not in SUPPORTED_SCHEMA_VERSIONS:
        warnings.append(f"  UNKNOWN_SCHEMA {chunk_id}: schema_version '{version}' not supported")


def _check_optional_self_eval_fields(meta: dict, chunk_id: str, warnings: list) -> None:
    if meta.get("chunk_type") == "cobol_analysis_health" and "confidence_score" not in meta:
        warnings.append(f"  MISSING_SELF_EVAL {chunk_id}: optional self-evaluation fields absent")


def _check_token_limit(text: str, max_tokens: int, chunk_id: str,
                       meta: dict, errors: list, warnings: list) -> int:
    tc = _count(text)
    if tc > max_tokens:
        msg = f"  OVER_LIMIT     {chunk_id}: {tc} tokens > {max_tokens}"
        if meta.get("indexable") is False:
            warnings.append(msg)
        else:
            errors.append(msg)
    return tc


def _collect_xrefs(meta: dict) -> list[str]:
    """Collect all values in cross-reference fields that look like chunk_ids (contain ':')."""
    refs = []
    for field in XREF_FIELDS:
        val = meta.get(field)
        if val is None:
            continue
        if isinstance(val, str) and ":" in val:
            refs.append(val)
        elif isinstance(val, list):
            for item in val:
                if isinstance(item, str) and ":" in item:
                    refs.append(item)
    return refs


# ---------------------------------------------------------------------------
# Main validation
# ---------------------------------------------------------------------------

def validate(report_dir: Path, corpus_index_path: Path, max_tokens: int, verbose: bool) -> dict:
    results = {
        "chunks_checked": 0,
        "required_field_errors": [],
        "hash_errors": [],
        "token_errors": [],
        "token_warnings": [],
        "unknown_type_warnings": [],
        "schema_warnings": [],
        "self_eval_warnings": [],
        "xref_errors": [],
        "index_errors": [],
        "max_token_count": 0,
        "max_token_chunk_id": "",
    }

    # --- Collect all manifests and build global chunk_id → file lookup ---
    all_chunk_ids: set[str] = set()
    program_summary_programs: set[str] = set()

    report_dirs = sorted(report_dir.glob("*.report"))

    for rd in report_dirs:
        manifest_path = rd / "chunks" / "chunks_manifest.json"
        manifest = _load_json(manifest_path)
        if manifest is None:
            continue
        for entry in manifest.get("chunks", []):
            fname = entry.get("file", "")
            chunk_path = rd / "chunks" / fname
            data = _load_json(chunk_path)
            if data is None:
                continue
            meta = data.get("metadata", {})
            chunk_id = meta.get("chunk_id", fname)
            all_chunk_ids.add(chunk_id)
            split_from = meta.get("split_from")
            if split_from:
                all_chunk_ids.add(split_from)
            if meta.get("chunk_type") == "program_summary":
                program_summary_programs.add(meta.get("program", ""))

    # --- Per-chunk checks ---
    for rd in report_dirs:
        manifest_path = rd / "chunks" / "chunks_manifest.json"
        manifest = _load_json(manifest_path)
        if manifest is None:
            continue
        for entry in manifest.get("chunks", []):
            fname = entry.get("file", "")
            chunk_path = rd / "chunks" / fname
            data = _load_json(chunk_path)
            if data is None:
                results["required_field_errors"].append(
                    f"  UNREADABLE     {rd.name}/{fname}"
                )
                continue

            text = data.get("text", "")
            meta = data.get("metadata", {})
            chunk_id = meta.get("chunk_id", fname)
            results["chunks_checked"] += 1

            _check_required_fields(meta, chunk_id, results["required_field_errors"])
            _check_hash(text, meta, chunk_id, results["hash_errors"])
            tc = _check_token_limit(
                text, max_tokens, chunk_id, meta,
                results["token_errors"], results["token_warnings"],
            )
            if tc > results["max_token_count"]:
                results["max_token_count"] = tc
                results["max_token_chunk_id"] = chunk_id
            _check_chunk_type(meta, chunk_id, results["unknown_type_warnings"])
            _check_schema_version(meta, chunk_id, results["schema_warnings"])
            _check_optional_self_eval_fields(meta, chunk_id, results["unknown_type_warnings"])

            # Cross-reference check
            for ref in _collect_xrefs(meta):
                if ref not in all_chunk_ids:
                    results["xref_errors"].append(
                        f"  DANGLING_XREF  {chunk_id}: references unknown chunk_id '{ref}'"
                    )

    # --- Index consistency ---
    if corpus_index_path.exists():
        index = _load_json(corpus_index_path)
        if index:
            index_programs = set(index.get("programs", {}).keys())
            # Programs in index but no program_summary chunk
            for prog in index_programs - program_summary_programs:
                results["index_errors"].append(
                    f"  INDEX_NO_CHUNK {prog}: in corpus_index.json but no program_summary chunk found"
                )
            # Programs with program_summary chunk but missing from index
            for prog in program_summary_programs - index_programs:
                results["index_errors"].append(
                    f"  CHUNK_NOT_IN_INDEX {prog}: has program_summary chunk but missing from corpus_index.json"
                )
    else:
        if verbose:
            print(f"  Note: {corpus_index_path} not found — skipping index consistency check")

    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Validate generated RAG chunks for structural integrity",
    )
    parser.add_argument(
        "--report-dir", type=Path, default=Path("out/report"),
        help="Root directory containing *.report subdirectories (default: out/report)",
    )
    parser.add_argument(
        "--corpus-index", type=Path, default=Path("out/corpus_index.json"),
        help="Path to corpus_index.json (default: out/corpus_index.json)",
    )
    parser.add_argument(
        "--max-tokens", type=int, default=512,
        help="Token limit for over-size warnings (default: 512)",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    if not args.report_dir.is_dir():
        print(f"Error: {args.report_dir} is not a directory")
        sys.exit(1)

    print(f"Validating chunks in {args.report_dir} (token counter: {_COUNTER_LABEL}, "
          f"max_tokens={args.max_tokens})")

    results = validate(
        report_dir=args.report_dir,
        corpus_index_path=args.corpus_index,
        max_tokens=args.max_tokens,
        verbose=args.verbose,
    )

    total = results["chunks_checked"]
    req_errors = results["required_field_errors"]
    hash_errors = results["hash_errors"]
    tok_errors = results["token_errors"]
    tok_warnings = results["token_warnings"]
    type_warnings = results["unknown_type_warnings"]
    schema_warnings = results["schema_warnings"]
    xref_errors = results["xref_errors"]
    index_errors = results["index_errors"]

    all_errors = req_errors + hash_errors + tok_errors + xref_errors + index_errors
    all_warnings = tok_warnings + type_warnings + schema_warnings

    print(f"\n{'='*60}")
    print(f"Chunks checked:          {total}")
    print(f"Required-field errors:   {len(req_errors)}")
    print(f"Hash mismatches:         {len(hash_errors)}")
    print(f"Over-token errors:       {len(tok_errors)}")
    print(f"Over-token warnings:     {len(tok_warnings)}")
    print(f"Max token count:         {results['max_token_count']} ({results['max_token_chunk_id']})")
    print(f"Unknown chunk types:     {len(type_warnings)}")
    print(f"Schema warnings:         {len(schema_warnings)}")
    print(f"Dangling cross-refs:     {len(xref_errors)}")
    print(f"Index consistency errors:{len(index_errors)}")
    print(f"{'='*60}")

    if args.verbose or all_errors:
        for section, label in [
            (req_errors, "REQUIRED FIELD ERRORS"),
            (hash_errors, "HASH MISMATCHES"),
            (tok_errors, "TOKEN LIMIT ERRORS"),
            (xref_errors, "DANGLING CROSS-REFERENCES"),
            (index_errors, "INDEX CONSISTENCY"),
        ]:
            if section:
                print(f"\n[{label}]")
                for msg in section:
                    print(msg)

    if args.verbose and tok_warnings:
        print(f"\n[OVER TOKEN LIMIT ({len(tok_warnings)} chunks)]")
        for msg in tok_warnings[:20]:
            print(msg)
        if len(tok_warnings) > 20:
            print(f"  ... and {len(tok_warnings) - 20} more")

    if args.verbose and type_warnings:
        print(f"\n[UNKNOWN CHUNK TYPES ({len(type_warnings)} chunks)]")
        for msg in type_warnings[:20]:
            print(msg)

    if args.verbose and schema_warnings:
        print(f"\n[SCHEMA WARNINGS ({len(schema_warnings)} chunks)]")
        for msg in schema_warnings[:20]:
            print(msg)

    if all_errors:
        print(f"\nFAIL — {len(all_errors)} error(s) found.")
        sys.exit(1)
    else:
        warn_parts = []
        if tok_warnings:
            warn_parts.append(f"{len(tok_warnings)} over-limit")
        if type_warnings:
            warn_parts.append(f"{len(type_warnings)} unknown-type")
        if schema_warnings:
            warn_parts.append(f"{len(schema_warnings)} schema")
        warn_suffix = f" ({', '.join(warn_parts)} warnings)" if warn_parts else ""
        print(f"\nPASS — all checks passed.{warn_suffix}")
        sys.exit(0)


if __name__ == "__main__":
    main()
