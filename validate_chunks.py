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


def _check_token_limit(text: str, max_tokens: int, chunk_id: str, warnings: list) -> None:
    tc = _count(text)
    if tc > max_tokens:
        warnings.append(f"  OVER_LIMIT     {chunk_id}: {tc} tokens > {max_tokens}")


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
        "token_warnings": [],
        "xref_errors": [],
        "index_errors": [],
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
            _check_token_limit(text, max_tokens, chunk_id, results["token_warnings"])

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
    tok_warnings = results["token_warnings"]
    xref_errors = results["xref_errors"]
    index_errors = results["index_errors"]

    all_errors = req_errors + hash_errors + xref_errors + index_errors

    print(f"\n{'='*60}")
    print(f"Chunks checked:          {total}")
    print(f"Required-field errors:   {len(req_errors)}")
    print(f"Hash mismatches:         {len(hash_errors)}")
    print(f"Over-token-limit chunks: {len(tok_warnings)}")
    print(f"Dangling cross-refs:     {len(xref_errors)}")
    print(f"Index consistency errors:{len(index_errors)}")
    print(f"{'='*60}")

    if args.verbose or all_errors:
        for section, label in [
            (req_errors, "REQUIRED FIELD ERRORS"),
            (hash_errors, "HASH MISMATCHES"),
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

    if all_errors:
        print(f"\nFAIL — {len(all_errors)} error(s) found.")
        sys.exit(1)
    else:
        warn_suffix = f" ({len(tok_warnings)} over-token-limit warnings)" if tok_warnings else ""
        print(f"\nPASS — all checks passed.{warn_suffix}")
        sys.exit(0)


if __name__ == "__main__":
    main()
