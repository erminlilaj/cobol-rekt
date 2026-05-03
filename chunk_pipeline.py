#!/usr/bin/env python3
"""
Chunk Pipeline — Splits analysis report artifacts into fine-grained
retrieval units for RAG.

Accepts either a COBOL report directory or a JCL report directory (or both).
Each chunk is a JSON file with {"text": "...", "metadata": {...}}.

Usage:
    python3 chunk_pipeline.py out/report/TEST.CBL.report [--verbose]
    python3 chunk_pipeline.py out/report/MYJOB.jcl.report  [--verbose]
"""

import argparse
import hashlib
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

# =============================================================================
# Constants
# =============================================================================

CHUNK_SCHEMA_VERSION = "1.5"
PIPELINE_VERSION = "1.5"

# CFG JSON field names (NOT source/target/label as CLAUDE.md incorrectly states)
EDGE_SOURCE = "fromNodeID"
EDGE_TARGET = "toNodeID"
EDGE_TYPE = "edgeType"

# Chunk size thresholds — overridable via CLI flags (--min-tokens / --max-tokens / --overlap-tokens).
# When tiktoken is active the unit is BPE tokens; otherwise whitespace tokens.
MIN_CHUNK_TOKENS = 20
MAX_CHUNK_TOKENS = 512
OVERLAP_TOKENS = 50

ALWAYS_INDEXABLE_THIN_TYPES = frozenset({
    "cobol_analysis_health",
    "analysis_health",
    "jcl_analysis_health",
    "static_values",
    "external_program_calls",
    "datasets_tables_resources",
    "copybook_mentions",
    "copybook_fields",
    "comments",
    "commented_out_code",
})
NEGATIVE_EVIDENCE_TYPES = frozenset({
    "dependencies",
    "cobol_analysis_health",
    "analysis_health",
    "jcl_analysis_health",
    "external_program_calls",
    "datasets_tables_resources",
    "comments",
    "commented_out_code",
})

_COBOL_FIGURATIVE_CONSTANTS = frozenset({
    "SPACE", "SPACES", "ZERO", "ZEROS", "ZEROES", "NULL", "NULLS",
    "LOW-VALUE", "LOW-VALUES", "HIGH-VALUE", "HIGH-VALUES",
    "QUOTE", "QUOTES",
})

# Parse quality for the current program being chunked.
# Set by run_pipeline() from parse_diagnostics.json before any write_chunk() call.
_CURRENT_PARSE_QUALITY: str = "unknown"

# Analysis run timestamp for the current program (from pipeline_report.json).
# Set by run_pipeline() before any write_chunk() call; stamped into every chunk.
_CURRENT_SOURCE_MTIME: str | None = None


# =============================================================================
# Utilities
# =============================================================================

# Tiktoken BPE counter (cl100k_base = GPT-4 / text-embedding-3 tokenizer).
# Falls back to whitespace splitting if tiktoken is not installed.
try:
    import tiktoken as _tiktoken
    _BPE_ENCODING = _tiktoken.get_encoding("cl100k_base")
    def _bpe_count(text: str) -> int:
        return len(_BPE_ENCODING.encode(text))
    _TIKTOKEN_AVAILABLE = True
except Exception:
    _BPE_ENCODING = None
    _TIKTOKEN_AVAILABLE = False

# Active counter — can be overridden by --token-counter flag via set_token_counter()
_USE_BPE: bool = _TIKTOKEN_AVAILABLE


def set_token_counter(mode: str) -> None:
    """Select token counting strategy: 'bpe' (default) or 'whitespace'."""
    global _USE_BPE
    if mode == "bpe":
        if not _TIKTOKEN_AVAILABLE:
            print("Warning: tiktoken not installed; falling back to whitespace counting.")
        _USE_BPE = _TIKTOKEN_AVAILABLE
    else:
        _USE_BPE = False


def token_count(text: str) -> int:
    """Count tokens using BPE (cl100k_base) if available, else whitespace split."""
    if _USE_BPE:
        return _bpe_count(text)
    return len(text.split())


def token_ids(text: str) -> list[int] | None:
    """Return BPE token ids when the active counter supports them."""
    if _USE_BPE and _BPE_ENCODING is not None:
        return _BPE_ENCODING.encode(text)
    return None


def _decode_token_ids(ids: list[int]) -> str:
    if _BPE_ENCODING is not None:
        return _BPE_ENCODING.decode(ids)
    return ""


def _is_valid_program_target(value: str) -> bool:
    target = str(value or "").strip().strip("'\"").upper()
    if len(target) < 2:
        return False
    if target in _COBOL_FIGURATIVE_CONSTANTS:
        return False
    if target.isdigit():
        return False
    if any(ch.isspace() for ch in target):
        return False
    return bool(re.match(r"^[A-Z][A-Z0-9_-]*$", target))


def mark_indexability(text: str, metadata: dict) -> dict:
    """Set thin_chunk/indexable flags from chunk type and token size."""
    chunk_type = metadata.get("chunk_type", "")
    thin = token_count(text) < MIN_CHUNK_TOKENS
    if chunk_type in ALWAYS_INDEXABLE_THIN_TYPES:
        metadata["thin_chunk"] = False
        metadata["indexable"] = True
    elif thin:
        metadata["thin_chunk"] = True
        metadata["indexable"] = chunk_type in NEGATIVE_EVIDENCE_TYPES
    else:
        metadata["thin_chunk"] = False
        metadata.setdefault("indexable", True)
    return metadata


def split_whitespace_text(text: str, max_tokens: int, overlap: int = OVERLAP_TOKENS) -> list[str]:
    words = text.split()
    if len(words) <= max_tokens:
        return [text]
    parts: list[str] = []
    start = 0
    step_overlap = max(0, min(overlap, max_tokens - 1))
    while start < len(words):
        end = min(start + max_tokens, len(words))
        parts.append(" ".join(words[start:end]))
        if end >= len(words):
            break
        start = end - step_overlap
    return parts


def split_bpe_text(text: str, max_tokens: int, overlap: int = OVERLAP_TOKENS) -> list[str]:
    ids = token_ids(text)
    if ids is None:
        return split_whitespace_text(text, max_tokens, overlap)
    if len(ids) <= max_tokens:
        return [text]
    parts: list[str] = []
    start = 0
    step_overlap = max(0, min(overlap, max_tokens - 1))
    while start < len(ids):
        end = min(start + max_tokens, len(ids))
        parts.append(_decode_token_ids(ids[start:end]).strip())
        if end >= len(ids):
            break
        start = end - step_overlap
    return [p for p in parts if p]


def _atomic_write_json(path: Path, data):
    """Write JSON atomically via temp file + rename."""
    import os
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
    os.replace(str(tmp), str(path))


def write_chunk(chunks_dir: Path, filename: str, text: str, metadata: dict):
    """Write a single chunk JSON file."""
    metadata = mark_indexability(text, metadata)
    metadata["schema_version"] = CHUNK_SCHEMA_VERSION
    metadata["pipeline_version"] = PIPELINE_VERSION
    metadata["analysis_timestamp"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    metadata["content_hash"] = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    metadata["parse_quality"] = _CURRENT_PARSE_QUALITY
    if _CURRENT_SOURCE_MTIME:
        metadata["analysis_run_timestamp"] = _CURRENT_SOURCE_MTIME
    chunk = {"text": text, "metadata": metadata}
    _atomic_write_json(chunks_dir / filename, chunk)


def clear_existing_chunks(chunks_dir: Path) -> int:
    """Remove generated chunk JSON files before a fresh chunk pipeline run."""
    removed = 0
    if not chunks_dir.exists():
        return 0
    for path in chunks_dir.glob("*.json"):
        path.unlink()
        removed += 1
    return removed


def load_json(path: Path) -> dict | list | None:
    """Load a JSON file, return None on failure."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"  [WARN] Could not load {path.name}: {e}", file=sys.stderr)
        return None


def load_yaml(path: Path) -> dict | None:
    """Load a YAML file, return None on failure."""
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError) as e:
        print(f"  [WARN] Could not load {path.name}: {e}", file=sys.stderr)
        return None



def _load_cobol_structure(report_dir: Path) -> dict:
    path = report_dir / "cobol_structure.json"
    if path.exists():
        return load_json(path) or {}
    return {}

# =============================================================================
# Parse quality helpers (R7.1, R7.2)
# =============================================================================

def _get_parse_diagnostics(report_dir: Path) -> dict:
    """Load parse_diagnostics.json. Returns empty dict if absent."""
    path = report_dir / "parse_diagnostics.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"  [WARN] Corrupt parse_diagnostics.json: {e}", file=sys.stderr)
        return {}


def _get_analysis_health(report_dir: Path) -> dict:
    path = report_dir / "analysis_health.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"  [WARN] Corrupt analysis_health.json: {e}", file=sys.stderr)
        return {}


def _get_analysis_self_evaluation(report_dir: Path) -> dict:
    path = report_dir / "analysis_self_evaluation.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"  [WARN] Corrupt analysis_self_evaluation.json: {e}", file=sys.stderr)
        return {}


def _get_source_mtime(report_dir: Path) -> str | None:
    """Return the analysis run timestamp from pipeline_report.json, or None if unavailable."""
    pr_path = report_dir / "pipeline_report.json"
    if pr_path.exists():
        try:
            pr = json.loads(pr_path.read_text(encoding="utf-8"))
            ts = pr.get("timestamp")
            if ts:
                return ts
        except (json.JSONDecodeError, OSError):
            pass
    return None


def _compute_parse_quality(diag: dict, health: dict | None = None) -> str:
    """Map parse diagnostics to a quality label: full / partial / degraded / unknown."""
    if health and health.get("base_analysis_succeeded") is False:
        return "degraded"
    if not diag:
        return "full"  # absent diagnostics = strict parse succeeded with zero errors
    if diag.get("data_structures_degraded", False):
        return "degraded"
    skipped = diag.get("skipped_variables", [])
    errors = diag.get("error_summary", {}).get("total_errors", 0)
    if errors == 0 and not skipped:
        return "full"
    if errors <= 5 and len(skipped) <= 3:
        return "partial"
    return "degraded"


def _compute_parse_coverage(diag: dict) -> float | None:
    """Return coverage_percentage from diagnostics, or None if unavailable."""
    if not diag:
        return None
    cov = diag.get("coverage_percentage")
    if cov is not None:
        return float(cov)
    # Derive from line counts if coverage_percentage absent
    total = diag.get("source_lines", 0)
    affected = diag.get("affected_lines", 0)
    if total > 0:
        return round((total - affected) / total * 100, 2)
    return None


# =============================================================================
# Mode detection
# =============================================================================

def detect_mode(report_dir: Path) -> tuple[bool, bool]:
    """Return (is_cobol, is_jcl) based on directory contents."""
    is_cobol = (report_dir / "cfg").is_dir()
    is_jcl = (report_dir / "jcl_summary.json").exists()
    return is_cobol, is_jcl


# =============================================================================
# Group B — program_summary + dependencies
# =============================================================================

def generate_program_summary(report_dir: Path, chunks_dir: Path,
                             program: str, verbose: bool) -> int:
    """Parse 00_Executive_Summary.md and emit a program_summary chunk.
    Returns 1 if chunk was written, 0 otherwise.
    """
    summary_path = report_dir / "knowledge_base" / "00_Executive_Summary.md"
    if not summary_path.exists():
        if verbose:
            print(f"  Skipping program_summary: {summary_path.name} not found")
        return 0

    text = summary_path.read_text(encoding="utf-8")

    # Parse metrics table: "| Metric | Value |" rows
    metrics = {}
    for m in re.finditer(
        r"^\|\s*(.+?)\s*\|\s*(.+?)\s*\|", text, re.MULTILINE
    ):
        key, val = m.group(1).strip(), m.group(2).strip()
        if key in ("Metric", "------", "--------"):
            continue
        metrics[key] = val

    # Extract numeric values
    node_count = _parse_int(metrics.get("Total CFG Nodes", "0"))
    edge_count = _parse_int(metrics.get("Total Edges", "0"))
    variable_count = _parse_int(metrics.get("Variables Defined", "0"))
    complexity_raw = metrics.get("Complexity Score", "0")
    # Handle "High (435)" format
    cm = re.search(r"(\d+)", complexity_raw)
    complexity_score = int(cm.group(1)) if cm else 0

    # R2.2 — build a one-sentence NL description from dependency artifacts
    nl_summary = _build_program_nl_summary(report_dir, program, complexity_score)

    # Build human-readable text — NL summary first, then metrics
    chunk_text = (
        f"{nl_summary} "
        f"Program {program} has {node_count} CFG nodes, {edge_count} edges, "
        f"and {variable_count} variables defined. "
        f"McCabe cyclomatic complexity: {complexity_score}."
    )

    # Append node type distribution if present
    type_lines = []
    in_dist = False
    for line in text.splitlines():
        if "Node Type Distribution" in line:
            in_dist = True
            continue
        if in_dist and line.startswith("|") and "Type" not in line and "---" not in line:
            parts = [p.strip() for p in line.split("|") if p.strip()]
            if len(parts) == 2:
                type_lines.append(f"{parts[0]}: {parts[1]}")
        elif in_dist and not line.startswith("|") and line.strip():
            break
    if type_lines:
        chunk_text += "\nTop node types: " + ", ".join(type_lines) + "."

    struct = _load_cobol_structure(report_dir)
    structural_counts: dict[str, int] = {}
    if struct:
        structural_counts = {
            "paragraph_count": len(struct.get("paragraph_profiles", {}) or {}),
            "section_count": len(struct.get("sections", {}) or {}),
            "condition_count": len(struct.get("conditions_88", {}) or {}),
            "redefines_count": len(struct.get("redefines", []) or []),
        }
        chunk_text += (
            f"\nParagraphs: {structural_counts['paragraph_count']} "
            f"in {structural_counts['section_count']} sections. "
            f"88-level conditions: {structural_counts['condition_count']}. "
            f"REDEFINES: {structural_counts['redefines_count']}."
        )

    # Append Program Overview from narrative if available
    overview_text = _extract_program_overview(report_dir)
    if overview_text:
        chunk_text += "\n" + overview_text

    # Parse coverage from diagnostics (R7.2)
    diag = _get_parse_diagnostics(report_dir)
    parse_coverage_pct = _compute_parse_coverage(diag)

    # R7.3 — confidence score
    confidence = _compute_confidence_score(report_dir)

    metadata = {
        "chunk_type": "program_summary",
        "chunk_id": f"{program}:program_summary",
        "program": program,
        "node_count": node_count,
        "edge_count": edge_count,
        "variable_count": variable_count,
        "complexity_score": complexity_score,
        "confidence": confidence,
    }
    if structural_counts:
        metadata.update(structural_counts)
    if struct:
        copy_stmts = struct.get("copy_statements", [])
        if copy_stmts:
            metadata["copybooks_used"] = list(dict.fromkeys(
                cs["copybook"] for cs in copy_stmts
            ))
        if struct.get("known_system_copybooks"):
            metadata["known_system_copybooks"] = struct["known_system_copybooks"]
    if parse_coverage_pct is not None:
        metadata["parse_coverage_pct"] = parse_coverage_pct

    called_by = _load_program_called_by(report_dir, program)
    if called_by:
        metadata["called_by"] = called_by
        chunk_text += "\nCalled by: " + ", ".join(called_by) + "."

    # Append confidence label to text
    chunk_text += (
        f"\nAnalysis confidence: {confidence['label']} ({confidence['score']:.2f})."
    )
    if confidence.get("flags"):
        chunk_text += " Notes: " + "; ".join(confidence["flags"]) + "."

    write_chunk(chunks_dir, f"{program}__program_summary.json", chunk_text, metadata)
    if verbose:
        print(f"  program_summary: complexity={complexity_score}, "
              f"nodes={node_count}, vars={variable_count}, "
              f"confidence={confidence['label']} ({confidence['score']:.2f})")
    return 1


def _load_program_called_by(report_dir: Path, program: str) -> list[str]:
    cross_calls_path = report_dir.parent.parent / "cross_program_calls.json"
    if not cross_calls_path.exists():
        return []
    try:
        data = load_json(cross_calls_path)
    except Exception:
        return []
    if not isinstance(data, dict):
        return []

    target = _normalise_program_lookup_name(program)
    for entry in data.get("programs", []) or []:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name") or entry.get("program")
        if _normalise_program_lookup_name(str(name or "")) != target:
            continue
        callers = []
        seen = set()
        for caller in entry.get("called_by", []) or []:
            if isinstance(caller, dict):
                caller_name = str(caller.get("source") or caller.get("program") or "").strip()
            else:
                caller_name = str(caller or "").strip()
            if caller_name and caller_name.upper() not in seen:
                seen.add(caller_name.upper())
                callers.append(caller_name)
        return callers
    return []


def _normalise_program_lookup_name(program: str) -> str:
    name = Path(str(program or "")).name.upper()
    for suffix in (".CBL", ".COB", ".CPY"):
        if name.endswith(suffix):
            return name[:-len(suffix)]
    return name


def _extract_program_overview(report_dir: Path) -> str:
    """Extract '## Program Overview' section from 01_Logic_Narrative.md."""
    narrative_path = report_dir / "knowledge_base" / "01_Logic_Narrative.md"
    if not narrative_path.exists():
        return ""
    text = narrative_path.read_text(encoding="utf-8")
    # Find ## Program Overview section
    m = re.search(
        r"^## Program Overview\s*\n(.*?)(?=\n## |\Z)",
        text, re.MULTILINE | re.DOTALL,
    )
    if not m:
        return ""
    content = m.group(1).strip()
    # Clean blockquote markers and horizontal rules
    content = re.sub(r"^>\s*", "", content, flags=re.MULTILINE)
    content = re.sub(r"^---\s*$", "", content, flags=re.MULTILINE)
    return content.strip()


def _compute_confidence_score(report_dir: Path) -> dict:
    """R7.3 — Compute a weighted confidence score for a COBOL analysis.

    Returns {"score": float, "label": str, "sub_scores": dict, "flags": list[str]}.

    Sub-scores (each 0.0–1.0):
      parse_quality (0.30) — from parse_diagnostics.json
      copybook_coverage (0.25) — resolved / total from copybook_manifest.json
      data_dictionary_coverage (0.20) — fields with PIC / total fields in data_structures
      dependency_completeness (0.15) — no dynamic SQL / no UNKNOWN calls
      narrative_quality (0.10) — paragraphs with comments / total paragraphs
    """
    flags: list[str] = []

    # --- parse_quality sub-score ---
    diag = _get_parse_diagnostics(report_dir)
    pq = _compute_parse_quality(diag)
    parse_score = {"full": 1.0, "partial": 0.6, "degraded": 0.2, "unknown": 0.8}[pq]
    if pq == "degraded":
        flags.append("degraded parse quality")
    elif pq == "partial":
        flags.append("partial parse quality")

    # --- copybook_coverage sub-score ---
    cpb_path = report_dir / "copybook_manifest.json"
    if cpb_path.exists():
        cpb = load_json(cpb_path) or {}
        s = cpb.get("summary", {})
        total_cpb = s.get("total_copybooks", 0)
        resolved_cpb = s.get("resolved", 0)
        stub_count = total_cpb - resolved_cpb
        cpb_score = (resolved_cpb / total_cpb) if total_cpb > 0 else 1.0
        if stub_count > 0:
            flags.append(f"{stub_count} copybook(s) stubbed")
    else:
        cpb_score = 1.0  # no copybooks required
        stub_count = 0

    # --- data_dictionary_coverage sub-score ---
    ds_dir = report_dir / "data_structures"
    dd_score = 0.8  # default if file absent
    if ds_dir.is_dir():
        ds_files = list(ds_dir.glob("*-data.json"))
        if ds_files:
            ds_data = load_json(ds_files[0])
            if ds_data:
                total_fields = 0
                typed_fields = 0
                def _count(node: dict) -> None:
                    nonlocal total_fields, typed_fields
                    name = node.get("name", "")
                    if name and name not in ("FILLER", "[ROOT]") and node.get("levelNumber", 0) > 0:
                        total_fields += 1
                        if node.get("dataType") and node.get("dataType") != "OBJECT":
                            typed_fields += 1
                    for c in node.get("children", []):
                        _count(c)
                for r in ds_data.get("children", []):
                    _count(r)
                dd_score = (typed_fields / total_fields) if total_fields > 0 else 1.0

    # --- dependency_completeness sub-score ---
    deps_path = report_dir / "knowledge_base" / "03_Dependencies.yaml"
    dep_score = 1.0
    if deps_path.exists():
        deps = load_yaml(deps_path)
        if deps:
            db = deps.get("database", {})
            if db.get("dynamic_sql"):
                dep_score -= 0.2
                flags.append("dynamic SQL detected")
            calls = deps.get("calls", [])
            unknown_calls = [c for c in calls if c.get("target") == "UNKNOWN"]
            if unknown_calls:
                dep_score -= 0.15 * min(len(unknown_calls), 2)
                flags.append(f"{len(unknown_calls)} unresolved dynamic CALL target(s)")
    dep_score = max(0.0, dep_score)

    # --- narrative_quality sub-score ---
    comments_path = report_dir / "comments.json"
    narr_score = 0.5  # default with no comments file
    if comments_path.exists():
        comments_data = load_json(comments_path)
        if isinstance(comments_data, dict):
            total_paras = len(comments_data)
            commented = sum(1 for v in comments_data.values() if v)
            narr_score = (commented / total_paras) if total_paras > 0 else 0.5
        elif isinstance(comments_data, list):
            narr_score = 0.7 if comments_data else 0.3

    # --- Weighted composite ---
    score = (
        0.30 * parse_score
        + 0.25 * cpb_score
        + 0.20 * dd_score
        + 0.15 * dep_score
        + 0.10 * narr_score
    )
    score = round(min(1.0, max(0.0, score)), 3)

    if score >= 0.85:
        label = "high"
    elif score >= 0.65:
        label = "medium"
    else:
        label = "low"

    return {
        "score": score,
        "label": label,
        "sub_scores": {
            "parse_quality": round(parse_score, 3),
            "copybook_coverage": round(cpb_score, 3),
            "data_dictionary_coverage": round(dd_score, 3),
            "dependency_completeness": round(dep_score, 3),
            "narrative_quality": round(narr_score, 3),
        },
        "flags": flags,
    }


def _build_program_nl_summary(report_dir: Path, program: str,
                              complexity_score: int) -> str:
    """R2.2 — Derive a one-sentence natural language description of the program.

    Combines: complexity tier, CICS/batch mode, DB2 usage.
    """
    # Complexity label
    if complexity_score < 10:
        complexity_label = "low-complexity"
    elif complexity_score < 30:
        complexity_label = "moderate-complexity"
    elif complexity_score < 100:
        complexity_label = "high-complexity"
    else:
        complexity_label = "very-high-complexity"

    # Load 03_Dependencies.yaml for CICS / DB2 signals
    deps_path = report_dir / "knowledge_base" / "03_Dependencies.yaml"
    is_cics = False
    has_db2 = False
    if deps_path.exists():
        deps = load_yaml(deps_path)
        if deps:
            cics = deps.get("cics", [])
            is_cics = bool(cics)
            db = deps.get("database", {})
            has_db2 = bool(db.get("tables_read") or db.get("tables_updated")
                           or db.get("sql_statements") or db.get("dynamic_sql"))

    prog_type = "CICS online program" if is_cics else "batch program"
    db_suffix = " with DB2 database access" if has_db2 else ""
    return f"This is a {complexity_label} {prog_type}{db_suffix}."


def generate_dependencies(report_dir: Path, chunks_dir: Path,
                          program: str, verbose: bool) -> int:
    """Parse 03_Dependencies.yaml and emit a dependencies chunk."""
    deps_path = report_dir / "knowledge_base" / "03_Dependencies.yaml"
    if not deps_path.exists():
        if verbose:
            print(f"  Skipping dependencies: {deps_path.name} not found")
        return 0

    deps = load_yaml(deps_path)
    if not deps:
        return 0

    db = deps.get("database", {})
    tables_read = db.get("tables_read", []) or []
    tables_updated = db.get("tables_updated", []) or []
    sql_stmts = db.get("sql_statements", []) or []
    calls = [c.get("target", "") for c in (deps.get("calls", []) or [])]
    cics = deps.get("cics", []) or []
    cics_calls = deps.get("cics_calls", []) or []
    cics_operations = deps.get("cics_operations", []) or []
    cics_resources = _summarize_cics_resources(cics_operations)
    cfg_cics_literals = _extract_cics_literal_arguments_from_cfg(report_dir)

    # Build human-readable text
    lines = [f"External dependencies for program {program}:"]
    if tables_read:
        lines.append(f"Database tables read: {', '.join(tables_read)}.")
    if tables_updated:
        lines.append(f"Database tables updated: {', '.join(tables_updated)}.")
    if sql_stmts:
        lines.append(f"SQL operations: {', '.join(sql_stmts)}.")
    if calls:
        lines.append(f"Called programs: {', '.join(calls)}.")
    if cics:
        lines.append(f"CICS commands: {', '.join(cics)}.")
    if cics_calls:
        targets = [c.get("target", "?") for c in cics_calls]
        lines.append(f"CICS program transfers (LINK/XCTL): {', '.join(targets)}.")
    if cics_resources:
        rendered = [
            f"{resource['target_kind']} {resource['target']}"
            for resource in cics_resources
        ]
        lines.append(f"CICS resources: {', '.join(rendered)}.")
    cics_resource_parts = []
    for label, key in [
        ("MAP", "MAP"),
        ("MAPSET", "MAPSET"),
        ("TRANSID", "TRANSID"),
        ("PROGRAM", "PROGRAM"),
    ]:
        cics_resource_parts.extend(
            f"{label} {value}" for value in cfg_cics_literals.get(key, [])
        )
    if cics_resource_parts:
        lines.append(f"CICS resources: {', '.join(cics_resource_parts)}.")
    if cfg_cics_literals.get("DATASET"):
        lines.append(f"CICS files/datasets: {', '.join(cfg_cics_literals['DATASET'])}.")
    if cfg_cics_literals.get("QUEUE"):
        lines.append(f"CICS queues: {', '.join(cfg_cics_literals['QUEUE'])}.")
    if not any([
        tables_read, tables_updated, sql_stmts, calls, cics, cics_calls,
        cics_resources, cics_resource_parts, cfg_cics_literals.get("DATASET"),
        cfg_cics_literals.get("QUEUE"),
    ]):
        lines.append("No external dependencies detected.")

    metadata = {
        "chunk_type": "dependencies",
        "chunk_id": f"{program}:dependencies",
        "program": program,
        "sql_tables_read": tables_read,
        "sql_tables_updated": tables_updated,
        "sql_statements": sql_stmts,
        "calls": calls,
        "cics_commands": cics,
        "cics_calls": [{"command": c.get("command"), "target": c.get("target")} for c in cics_calls],
        "cics_operations": cics_operations,
        "cics_resources": cics_resources,
        "cics_maps": cfg_cics_literals.get("MAP", []),
        "cics_mapsets": cfg_cics_literals.get("MAPSET", []),
        "cics_transids": cfg_cics_literals.get("TRANSID", []),
        "cics_datasets": cfg_cics_literals.get("DATASET", []),
        "cics_queues": cfg_cics_literals.get("QUEUE", []),
        "cics_programs": cfg_cics_literals.get("PROGRAM", []),
    }
    struct = _load_cobol_structure(report_dir)
    if struct:
        copy_stmts = struct.get("copy_statements", [])
        if copy_stmts:
            metadata["copybooks_used"] = list(dict.fromkeys(
                cs["copybook"] for cs in copy_stmts
            ))
    write_chunk(
        chunks_dir, f"{program}__dependencies.json",
        "\n".join(lines), metadata,
    )
    if verbose:
        print(f"  dependencies: tables_r={len(tables_read)}, "
              f"calls={len(calls)}, cics={len(cics)}")
    return 1


def _summarize_cics_resources(cics_operations: list[dict]) -> list[dict]:
    """Return non-program CICS targets for dependency/resource questions."""
    resources = []
    seen = set()
    for op in cics_operations:
        if not isinstance(op, dict):
            continue
        target = str(op.get("target", "")).strip()
        target_kind = str(op.get("target_kind", "")).strip().upper()
        if not target or not target_kind or target_kind in {"PROGRAM", "UNKNOWN"}:
            continue
        key = (target_kind, target.upper())
        if key in seen:
            continue
        seen.add(key)
        entry = {
            "target_kind": target_kind,
            "target": target,
        }
        target_source = op.get("target_source")
        if target_source:
            entry["target_source"] = target_source
        resources.append(entry)
    return resources


def _extract_cics_literal_arguments_from_cfg(report_dir: Path) -> dict[str, list[str]]:
    """Extract literal CICS arguments from Java CFG metadata, with text fallback for stale reports."""
    result = {
        "MAP": [],
        "MAPSET": [],
        "TRANSID": [],
        "DATASET": [],
        "QUEUE": [],
        "PROGRAM": [],
    }
    cfg_dir = report_dir / "cfg"
    if not cfg_dir.is_dir():
        return result
    cfg_files = sorted(cfg_dir.glob("cfg-*.json"))
    if not cfg_files:
        return result

    patterns = {
        key: re.compile(rf"\b{key}\s*\(\s*'([^']+)'\s*\)", re.IGNORECASE)
        for key in result
    }
    patterns["FILE"] = re.compile(r"\bFILE\s*\(\s*'([^']+)'\s*\)", re.IGNORECASE)
    seen = {key: set() for key in result}

    def add_value(key: str, value: object) -> None:
        target_key = "DATASET" if key == "FILE" else key
        if target_key not in result:
            return
        value_text = str(value).strip()
        value_u = value_text.upper()
        if value_u and value_u not in seen[target_key]:
            seen[target_key].add(value_u)
            result[target_key].append(value_text)

    for cfg_file in cfg_files:
        data = load_json(cfg_file)
        if not isinstance(data, dict):
            continue
        for node in data.get("nodes", []) or []:
            if not isinstance(node, dict):
                continue
            original = str(node.get("originalText") or "")
            node_type = str(node.get("type") or "").upper()
            if "EXEC CICS" not in original.upper() and node_type not in {"DIALECT", "EXEC_CICS"}:
                continue
            metadata = node.get("metadata") if isinstance(node.get("metadata"), dict) else {}
            for argument in metadata.get("cics_arguments", []) or []:
                if not isinstance(argument, dict):
                    continue
                if str(argument.get("value_source", "")).lower() != "literal":
                    continue
                add_value(str(argument.get("name", "")).upper(), argument.get("value"))
            for key, pattern in patterns.items():
                for match in pattern.findall(original):
                    add_value(key, match)
    return result


def generate_copybook_mentions(report_dir: Path, chunks_dir: Path,
                               program: str, verbose: bool) -> int:
    """Generate COPY statement mentions with source lines and resolution status."""
    struct = _load_cobol_structure(report_dir)
    copy_stmts = struct.get("copy_statements", []) if struct else []
    manifest = _load_copybook_manifest(report_dir)

    mentions: list[dict] = []
    for stmt in copy_stmts:
        if not isinstance(stmt, dict):
            continue
        copybook = str(stmt.get("copybook", "")).strip()
        if not copybook:
            continue
        manifest_info = manifest.get(copybook.upper(), {})
        mention = {
            "copybook": copybook,
            "source_line": stmt.get("line"),
            "statement": _format_copy_statement(stmt),
            "division": stmt.get("division"),
            "section": stmt.get("section"),
            "replacing": stmt.get("replacing"),
            "resolved": manifest_info.get("status") == "resolved",
            "stubbed": bool(manifest_info.get("is_stub", False)),
            "status": manifest_info.get("status", "unknown"),
        }
        if stmt.get("impact"):
            mention["impact"] = stmt.get("impact")
        if manifest_info.get("file"):
            mention["file"] = manifest_info.get("file")
        if manifest_info.get("path"):
            mention["path"] = manifest_info.get("path")
        mentions.append(mention)

    lines = [f"Copybook mentions for {program}:"]
    if mentions:
        for mention in mentions:
            line = (
                f"- {mention['statement']} at source line "
                f"{mention.get('source_line', 'unknown')}"
            )
            status = mention.get("status", "unknown")
            if status == "resolved":
                line += ", resolved: yes"
            elif mention.get("stubbed"):
                line += ", resolved: no, stubbed: yes"
            else:
                line += f", resolved: {status}"
            if mention.get("file"):
                line += f", file: {mention['file']}"
            if mention.get("division"):
                line += f", division: {mention['division']}"
            if mention.get("section"):
                line += f", section: {mention['section']}"
            if mention.get("impact"):
                line += f", impact: {mention['impact']}"
            lines.append(line + ".")
    else:
        lines.append("No COPY statements were found in the indexed COBOL structure.")

    metadata = {
        "chunk_type": "copybook_mentions",
        "chunk_id": f"{program}:copybook_mentions",
        "program": program,
        "mention_count": len(mentions),
        "copybooks": [mention["copybook"] for mention in mentions],
        "mentions": mentions,
    }
    write_chunk(
        chunks_dir,
        f"{program}__copybook_mentions.json",
        "\n".join(lines),
        metadata,
    )
    if verbose:
        print(f"  copybook_mentions: mentions={len(mentions)}")
    return 1


def _load_copybook_manifest(report_dir: Path) -> dict[str, dict]:
    manifest_path = report_dir / "copybook_manifest.json"
    if not manifest_path.exists():
        return {}
    data = load_json(manifest_path) or {}
    if not isinstance(data, dict):
        return {}
    copybooks = data.get("copybooks", {}) or {}
    if not isinstance(copybooks, dict):
        return {}
    return {str(name).upper(): info for name, info in copybooks.items() if isinstance(info, dict)}


def _format_copy_statement(stmt: dict) -> str:
    raw_statement = str(stmt.get("statement", "")).strip()
    if raw_statement:
        return raw_statement if raw_statement.endswith(".") else raw_statement + "."
    copybook = str(stmt.get("copybook", "")).strip()
    replacing = stmt.get("replacing")
    if replacing:
        text = f"COPY {copybook} REPLACING {replacing}"
    else:
        text = f"COPY {copybook}"
    return text if text.endswith(".") else text + "."


def generate_comments(report_dir: Path, chunks_dir: Path,
                      program: str, verbose: bool) -> int:
    """Generate a curated comments chunk from extracted COBOL prose comments."""
    comments_path = report_dir / "comments.json"
    produced = comments_path.exists()
    comments_data = load_json(comments_path) if produced else None
    blocks = _normalize_comment_blocks(comments_data)

    lines = [f"Source comments for {program}:"]
    if not produced:
        lines.append(
            "Status: not produced. Comment extraction did not produce comments.json."
        )
    elif not blocks:
        lines.append("Status: produced. No ordinary source comments were detected.")
    else:
        lines.append("Status: produced.")
        for block in blocks:
            loc = _format_line_range(block.get("line_start"), block.get("line_end"))
            prefix = f"- {block['target']}"
            if loc:
                prefix += f" at {loc}"
            rendered_comments = " / ".join(block["comments"])
            lines.append(f"{prefix}: {rendered_comments}.")

    metadata = {
        "chunk_type": "comments",
        "chunk_id": f"{program}:comments",
        "program": program,
        "analysis_status": "produced" if produced else "not_produced",
        "comment_block_count": len(blocks),
        "comment_count": sum(len(block["comments"]) for block in blocks),
        "comment_blocks": blocks,
    }
    write_chunk(
        chunks_dir,
        f"{program}__comments.json",
        "\n".join(lines),
        metadata,
    )
    if verbose:
        status = "produced" if produced else "not_produced"
        print(f"  comments: status={status}, blocks={len(blocks)}")
    return 1


def generate_commented_out_code(report_dir: Path, chunks_dir: Path,
                                program: str, verbose: bool) -> int:
    """Generate inactive/commented-out COBOL evidence as a separate chunk."""
    inactive_path = report_dir / "commented_out_code.json"
    produced = inactive_path.exists()
    inactive_data = load_json(inactive_path) if produced else None
    blocks = _normalize_inactive_comment_blocks(inactive_data)

    lines = [f"Commented-out or inactive COBOL evidence for {program}:"]
    if not produced:
        lines.append(
            "Status: not produced. Inactive-code comment extraction did not produce commented_out_code.json."
        )
    elif not blocks:
        lines.append("Status: produced. No commented-out COBOL code blocks were detected.")
    else:
        lines.append("Status: produced.")
        for block in blocks:
            loc = _format_line_range(block.get("line_start"), block.get("line_end"))
            categories = ", ".join(block["categories"]) if block["categories"] else "code-like comment"
            prefix = f"- {block['target']}"
            if loc:
                prefix += f" at {loc}"
            evidence = " / ".join(block["lines"][:3])
            if len(block["lines"]) > 3:
                evidence += f" / ... {len(block['lines']) - 3} more line(s)"
            lines.append(f"{prefix}: inactive categories: {categories}. Evidence: {evidence}.")

    metadata = {
        "chunk_type": "commented_out_code",
        "chunk_id": f"{program}:commented_out_code",
        "program": program,
        "analysis_status": "produced" if produced else "not_produced",
        "inactive_block_count": len(blocks),
        "inactive_line_count": sum(len(block["lines"]) for block in blocks),
        "blocks": blocks,
    }
    write_chunk(
        chunks_dir,
        f"{program}__commented_out_code.json",
        "\n".join(lines),
        metadata,
    )
    if verbose:
        status = "produced" if produced else "not_produced"
        print(f"  commented_out_code: status={status}, blocks={len(blocks)}")
    return 1


def _normalize_comment_blocks(data) -> list[dict]:
    if not isinstance(data, dict):
        return []

    blocks: list[dict] = []
    for target, raw_entries in data.items():
        entries = raw_entries if isinstance(raw_entries, list) else [raw_entries]
        comments: list[str] = []
        line_numbers: list[int] = []
        for entry in entries:
            if isinstance(entry, str):
                text = entry.strip()
                if text:
                    comments.append(text)
            elif isinstance(entry, dict):
                text = str(entry.get("text") or entry.get("comment") or "").strip()
                if text:
                    comments.append(text)
                line = entry.get("line") or entry.get("source_line")
                if isinstance(line, int):
                    line_numbers.append(line)
                line_start = entry.get("line_start")
                line_end = entry.get("line_end")
                if isinstance(line_start, int):
                    line_numbers.append(line_start)
                if isinstance(line_end, int):
                    line_numbers.append(line_end)
        if not comments:
            continue
        block = {
            "target": str(target),
            "comments": comments,
            "line_count": len(comments),
        }
        if line_numbers:
            block["line_start"] = min(line_numbers)
            block["line_end"] = max(line_numbers)
        blocks.append(block)
    return blocks


def _normalize_inactive_comment_blocks(data) -> list[dict]:
    if not isinstance(data, dict):
        return []

    blocks: list[dict] = []
    for target, raw_blocks in data.items():
        entries = raw_blocks if isinstance(raw_blocks, list) else [raw_blocks]
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            raw_lines = entry.get("lines", [])
            lines = [str(line).strip() for line in raw_lines if str(line).strip()]
            if not lines:
                continue
            block = {
                "target": str(target),
                "line_start": entry.get("line_start"),
                "line_end": entry.get("line_end"),
                "line_count": entry.get("line_count", len(lines)),
                "reason": entry.get("reason", "code_like_comment_block"),
                "active": False,
                "categories": _classify_inactive_comment_lines(lines),
                "lines": lines,
            }
            blocks.append(block)
    return blocks


def _classify_inactive_comment_lines(lines: list[str]) -> list[str]:
    joined = "\n".join(lines).upper()
    categories: list[str] = []
    if re.search(r"\bEXEC\s+CICS\b", joined):
        categories.append("commented-out CICS")
    if re.search(r"\bEXEC\s+SQL\b", joined):
        categories.append("commented-out SQL")
    if re.search(r"\bEXEC\s+(DLI|IMS)\b", joined):
        categories.append("commented-out DLI/IMS")
    if re.search(r"\bCALL\b", joined) or re.search(r"\b(LINK|XCTL)\b", joined):
        categories.append("commented-out call/transfer")
    if re.search(r"\bCOPY\b", joined):
        categories.append("commented-out COPY")
    if (
        re.search(r"\b(DATASET|FILE|FD|SELECT|OPEN|READ|READNEXT|READPREV|WRITE|REWRITE|DELETE|START|STARTBR|ENDBR)\b", joined)
        or "DATASET(" in joined
    ):
        categories.append("commented-out file/dataset")
    return list(dict.fromkeys(categories))


def _format_line_range(line_start, line_end) -> str:
    if isinstance(line_start, int) and isinstance(line_end, int):
        if line_start == line_end:
            return f"source line {line_start}"
        return f"source lines {line_start}-{line_end}"
    if isinstance(line_start, int):
        return f"source line {line_start}"
    return ""


def generate_copybook_fields(report_dir: Path, chunks_dir: Path,
                             program: str, verbose: bool) -> int:
    """Generate copybook field/parameter facts, preferring Java parser output."""
    manifest = _load_copybook_manifest(report_dir)
    struct = _load_cobol_structure(report_dir)
    mentioned = []
    if struct:
        for stmt in struct.get("copy_statements", []) or []:
            if isinstance(stmt, dict) and stmt.get("copybook"):
                mentioned.append(str(stmt["copybook"]).upper())
    ordered_names = list(dict.fromkeys(mentioned + sorted(manifest.keys())))

    java_fields = _load_java_data_structure_fields(report_dir)
    if java_fields is None:
        metadata = {
            "chunk_type": "copybook_fields",
            "chunk_id": f"{program}:copybook_fields",
            "program": program,
            "analysis_status": "unavailable",
            "field_source": "none",
            "degradation_reason": "java_data_structures_null_sentinel",
        }
        write_chunk(
            chunks_dir,
            f"{program}__copybook_fields.json",
            (
                f"Copybook fields for {program}: Data structures unavailable "
                "(lenient fallback or null sentinel). Field extraction cannot run."
            ),
            metadata,
        )
        if verbose:
            print("  copybook_fields: unavailable, java_data_structures_null_sentinel")
        return 1
    if java_fields:
        return _write_java_data_copybook_fields_chunk(
            report_dir, chunks_dir, program, verbose,
            ordered_names, manifest, java_fields,
        )

    entries: list[dict] = []
    for name in ordered_names:
        info = manifest.get(name, {})
        copy_path = _resolve_report_copybook_path(report_dir, name, info)
        fields: list[dict] = []
        limitations: list[str] = []
        if info.get("is_stub"):
            limitations.append("copybook is stubbed; real fields are unavailable")
        elif not copy_path:
            limitations.append("copybook file is not available in the report")
        else:
            fields = _extract_copybook_fields(copy_path)
            if not fields:
                limitations.append("no COBOL data-description fields were extracted")

        entries.append({
            "copybook": name,
            "resolved": info.get("status") == "resolved",
            "stubbed": bool(info.get("is_stub", False)),
            "status": info.get("status", "unknown"),
            "file": info.get("file"),
            "path": str(copy_path.relative_to(report_dir)) if copy_path and copy_path.is_relative_to(report_dir) else info.get("path"),
            "field_count": len(fields),
            "fields": fields,
            "limitations": limitations,
        })

    lines = [f"Copybook fields for {program}:"]
    lines.append(
        "Status: incomplete. Java data-structure export was unavailable; "
        "fields were extracted with a raw copybook fallback."
    )
    if entries:
        for entry in entries:
            prefix = f"- {entry['copybook']}"
            if entry.get("stubbed"):
                lines.append(f"{prefix}: stubbed; real fields unavailable.")
                continue
            if entry["fields"]:
                rendered = []
                for field in entry["fields"][:25]:
                    part = f"{field['name']} (level {field['level']}"
                    if field.get("picture"):
                        part += f", PIC {field['picture']}"
                    if field.get("value"):
                        part += f", VALUE {field['value']}"
                    part += f", line {field['line']})"
                    rendered.append(part)
                suffix = ""
                if len(entry["fields"]) > 25:
                    suffix = f" ... and {len(entry['fields']) - 25} more"
                lines.append(f"{prefix}: " + "; ".join(rendered) + suffix + ".")
            else:
                reason = "; ".join(entry["limitations"]) or "field extraction unavailable"
                lines.append(f"{prefix}: {reason}.")
    else:
        lines.append("No copybooks were available for field extraction.")

    metadata = {
        "chunk_type": "copybook_fields",
        "chunk_id": f"{program}:copybook_fields",
        "program": program,
        "analysis_status": "incomplete",
        "field_source": "raw_copybook_fallback",
        "copybook_origin_available": True,
        "copybook_count": len(entries),
        "copybooks": entries,
    }
    write_chunk(
        chunks_dir,
        f"{program}__copybook_fields.json",
        "\n".join(lines),
        metadata,
    )
    if verbose:
        extracted = sum(entry["field_count"] for entry in entries)
        print(f"  copybook_fields: copybooks={len(entries)}, fields={extracted}")
    return 1


def _write_java_data_copybook_fields_chunk(
    report_dir: Path,
    chunks_dir: Path,
    program: str,
    verbose: bool,
    ordered_names: list[str],
    manifest: dict[str, dict],
    java_fields: list[dict],
) -> int:
    entries = []
    for name in ordered_names:
        info = manifest.get(name, {})
        limitations = []
        if info.get("is_stub"):
            limitations.append("copybook is stubbed; real copybook-owned fields are unavailable")
        limitations.append(
            "field-to-copybook ownership is unavailable in current Java data export"
        )
        entries.append({
            "copybook": name,
            "resolved": info.get("status") == "resolved",
            "stubbed": bool(info.get("is_stub", False)),
            "status": info.get("status", "unknown"),
            "file": info.get("file"),
            "path": info.get("path"),
            "field_count": 0,
            "fields": [],
            "limitations": limitations,
        })

    rendered_fields = java_fields[:120]
    omitted_count = max(0, len(java_fields) - len(rendered_fields))
    status = "incomplete" if ordered_names else "produced"

    lines = [f"Copybook fields for {program}:"]
    if ordered_names:
        lines.append(
            "Status: incomplete. Java data-structure export was used for field facts, "
            "but exact field-to-copybook ownership is not available in this report schema."
        )
        lines.append("Included copybooks: " + ", ".join(ordered_names) + ".")
    else:
        lines.append(
            "Status: produced. No COPY statements were found; Java data-structure "
            "fields are listed for program data context."
        )

    if rendered_fields:
        lines.append("Java-parsed program data fields after copybook expansion:")
        for field in rendered_fields:
            lines.append("- " + _format_field_fact(field) + ".")
        if omitted_count:
            lines.append(
                f"... {omitted_count} more Java-parsed fields omitted from this summary; "
                "see variable_group chunks for full grouped field context."
            )
    else:
        lines.append("No Java-parsed data fields were available.")

    for entry in entries:
        reason = "; ".join(entry["limitations"])
        lines.append(f"- {entry['copybook']}: {reason}.")

    metadata = {
        "chunk_type": "copybook_fields",
        "chunk_id": f"{program}:copybook_fields",
        "program": program,
        "analysis_status": status,
        "field_source": "java_structured_fields",
        "copybook_origin_available": False,
        "copybook_count": len(entries),
        "copybooks": entries,
        "program_field_count": len(java_fields),
        "program_fields_sample": java_fields[:50],
    }
    write_chunk(
        chunks_dir,
        f"{program}__copybook_fields.json",
        "\n".join(lines),
        metadata,
    )
    if verbose:
        print(
            f"  copybook_fields: source=java_structured_fields, "
            f"copybooks={len(entries)}, fields={len(java_fields)}"
        )
    return 1


def _load_java_data_structure_fields(report_dir: Path) -> list[dict] | None:
    ds_dir = report_dir / "data_structures"
    if not ds_dir.is_dir():
        return []
    ds_files = sorted(ds_dir.glob("*-data.json"))
    if not ds_files:
        return []
    data = load_json(ds_files[0])
    if not isinstance(data, dict):
        return []
    if data.get("levelNumber") == -99 or str(data.get("name", "")).startswith("NULL["):
        return None

    fields: list[dict] = []

    def _walk(node: dict, parent: str = "") -> None:
        name = str(node.get("name", "")).strip()
        level = node.get("levelNumber")
        if name and name not in {"[ROOT]", "ROOT", "FILLER"} and level:
            raw_text = str(node.get("rawText", "")).strip()
            field = {
                "name": name.upper(),
                "level": str(level).zfill(2) if str(level).isdigit() and len(str(level)) == 1 else str(level),
                "raw_text": raw_text,
                "source_section": node.get("sourceSection", "UNKNOWN"),
                "data_type": node.get("dataType", "UNKNOWN"),
                "parent": parent,
            }
            if node.get("pictureClause"):
                field["picture"] = node["pictureClause"]
            if node.get("usage"):
                field["usage"] = node["usage"]
            for source_key, target_key in [
                ("occursCount", "occurs_count"),
                ("occursDependingOn", "occurs_depending_on"),
                ("byteSize", "byte_size"),
                ("byteOffset", "byte_offset"),
                ("sourceLine", "source_line"),
                ("sourceColumn", "source_column"),
            ]:
                if node.get(source_key) is not None:
                    field[target_key] = node[source_key]
            if node.get("sourceName"):
                field["source_name"] = node["sourceName"]
            if node.get("isRedefinition"):
                field["redefines"] = node.get("redefines", "")
            categories = node.get("categories")
            if isinstance(categories, list) and categories:
                field["categories"] = [str(category) for category in categories]
            fields.append(field)

        next_parent = name.upper() if name and name not in {"[ROOT]", "ROOT"} else parent
        for child in node.get("children", []) or []:
            if isinstance(child, dict):
                _walk(child, next_parent)

    for child in data.get("children", []) or []:
        if isinstance(child, dict):
            _walk(child)
    return fields


def _format_field_fact(field: dict) -> str:
    parts = [f"{field['name']} (level {field.get('level', '?')}"]
    if field.get("picture"):
        parts.append(f"PIC {field['picture']}")
    if field.get("usage"):
        parts.append(f"USAGE {field['usage']}")
    if field.get("occurs_count"):
        occurs = f"OCCURS {field['occurs_count']}"
        if field.get("occurs_depending_on"):
            occurs += f" DEPENDING ON {field['occurs_depending_on']}"
        parts.append(occurs)
    if field.get("data_type"):
        parts.append(f"type {field['data_type']}")
    if field.get("byte_size") is not None:
        parts.append(f"byte_size {field['byte_size']}")
    if field.get("byte_offset") is not None:
        parts.append(f"byte_offset {field['byte_offset']}")
    if field.get("source_line") is not None:
        parts.append(f"source line {field['source_line']}")
    if field.get("source_section"):
        parts.append(f"section {field['source_section']}")
    if field.get("redefines"):
        parts.append(f"REDEFINES {field['redefines']}")
    if field.get("parent"):
        parts.append(f"parent {field['parent']}")
    return ", ".join(parts) + ")"


def _resolve_report_copybook_path(report_dir: Path, name: str, info: dict) -> Path | None:
    candidates: list[Path] = []
    raw_path = info.get("path")
    if raw_path:
        path = Path(str(raw_path))
        candidates.append(path if path.is_absolute() else report_dir / path)
    file_name = info.get("file") or f"{name}.cpy"
    for base in [
        report_dir / "copybooks",
        report_dir / "artifacts" / "copybooks",
        report_dir / "knowledge-base_rag" / "artifacts" / "copybooks",
    ]:
        candidates.append(base / str(file_name))
        candidates.append(base / f"{name}.cpy")
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _extract_copybook_fields(copybook_path: Path) -> list[dict]:
    fields: list[dict] = []
    for lineno, raw_line in enumerate(copybook_path.read_text(
        encoding="utf-8", errors="replace"
    ).splitlines(), start=1):
        code = _copybook_code_area(raw_line)
        if not code:
            continue
        match = re.match(
            r"^\s*(0?[1-9]|[1-4][0-9]|66|77|88)\s+([A-Z0-9_$#@-]+)\b(.*)$",
            code,
            re.IGNORECASE,
        )
        if not match:
            continue
        level, field_name, rest = match.groups()
        field = {
            "name": field_name.upper(),
            "level": level.zfill(2) if level.isdigit() and len(level) == 1 else level,
            "line": lineno,
        }
        picture = _extract_copybook_picture(rest)
        value = _extract_copybook_value(rest)
        if picture:
            field["picture"] = picture
        if value:
            field["value"] = value
        if "REDEFINES" in rest.upper():
            redef = re.search(r"\bREDEFINES\s+([A-Z0-9_$#@-]+)", rest, re.IGNORECASE)
            if redef:
                field["redefines"] = redef.group(1).upper()
        fields.append(field)
    return fields


def _copybook_code_area(raw_line: str) -> str:
    if len(raw_line) >= 7 and raw_line[6:7] in {"*", "/"}:
        return ""
    if len(raw_line) > 7 and raw_line[:6].strip().isdigit():
        return raw_line[6:72].strip()
    stripped = raw_line.strip()
    if stripped.startswith(("*", "/")):
        return ""
    return stripped


def _extract_copybook_picture(rest: str) -> str:
    match = re.search(
        r"\b(?:PIC|PICTURE)\s+(.+?)(?=\s+(?:VALUE|VALUES|OCCURS|REDEFINES|USAGE|COMP|COMP-3|SYNC|SIGN|JUSTIFIED)\b|\.|$)",
        rest,
        re.IGNORECASE,
    )
    return match.group(1).strip() if match else ""


def _extract_copybook_value(rest: str) -> str:
    match = re.search(r"\bVALUES?\s+(.+?)(?=\.|$)", rest, re.IGNORECASE)
    return match.group(1).strip() if match else ""


def generate_external_program_calls(report_dir: Path, chunks_dir: Path,
                                    program: str, verbose: bool) -> int:
    """Generate external program call facts with parameters when available."""
    deps_path = report_dir / "knowledge_base" / "03_Dependencies.yaml"
    if not deps_path.exists():
        return 0
    deps = load_yaml(deps_path)
    if not deps:
        return 0

    detail_lookup = _extract_cics_call_details(report_dir)
    calls: list[dict] = []

    for call in deps.get("calls", []) or []:
        if not isinstance(call, dict):
            continue
        target = str(call.get("target", "")).strip().strip("'\"").upper()
        if not _is_valid_program_target(target):
            continue
        calls.append({
            "command": str(call.get("command") or call.get("type") or "CALL").upper(),
            "target": target,
            "target_kind": "PROGRAM",
            "target_source": call.get("target_source") or call.get("source") or "unknown",
            "using": call.get("using") or call.get("parameters") or [],
        })

    for op in deps.get("cics_operations", []) or []:
        if not isinstance(op, dict):
            continue
        if str(op.get("target_kind", "")).upper() != "PROGRAM":
            continue
        target = str(op.get("target", "")).strip().strip("'\"").upper()
        if not _is_valid_program_target(target):
            continue
        command = str(op.get("command") or "LINK/XCTL").upper()
        details = detail_lookup.get((command, target), [])
        if details:
            calls.extend(details)
        else:
            calls.append({
                "command": command,
                "target": target,
                "target_kind": "PROGRAM",
                "target_source": op.get("target_source") or "unknown",
            })

    # Keep older cics_calls useful if structured operations are absent.
    if not calls:
        for call in deps.get("cics_calls", []) or []:
            if not isinstance(call, dict):
                continue
            target = str(call.get("target", "")).strip().strip("'\"").upper()
            if not _is_valid_program_target(target):
                continue
            command = str(call.get("command") or "LINK/XCTL").upper()
            details = detail_lookup.get((command, target), [])
            calls.extend(details or [{
                "command": command,
                "target": target,
                "target_kind": "PROGRAM",
                "target_source": call.get("target_source") or "unknown",
            }])

    calls = _dedupe_call_facts(calls)
    if not calls:
        return 0

    lines = [f"External program calls for {program}:"]
    for call in calls:
        line = f"- {call.get('command', 'CALL')} {call['target']}"
        if call.get("paragraph"):
            line += f" in {call['paragraph']}"
        details = []
        if call.get("commarea"):
            details.append(f"COMMAREA {call['commarea']}")
        if call.get("length"):
            details.append(f"LENGTH {call['length']}")
        if call.get("using"):
            using = call["using"]
            if isinstance(using, list):
                details.append("USING " + ", ".join(str(item) for item in using))
            else:
                details.append(f"USING {using}")
        if call.get("target_source"):
            details.append(f"target_source {call['target_source']}")
        if details:
            line += ": " + ", ".join(details)
        lines.append(line + ".")

    metadata = {
        "chunk_type": "external_program_calls",
        "chunk_id": f"{program}:external_program_calls",
        "parent_program_chunk": f"{program}:program_summary",
        "program": program,
        "calls": calls,
        "call_targets": sorted({call["target"] for call in calls}),
        "call_count": len(calls),
    }
    write_chunk(
        chunks_dir,
        f"{program}__external_program_calls.json",
        "\n".join(lines),
        metadata,
    )
    if verbose:
        print(f"  external_program_calls: calls={len(calls)}")
    return 1


def generate_datasets_tables_resources(report_dir: Path, chunks_dir: Path,
                                       program: str, verbose: bool) -> int:
    """Generate one chunk separating DB2 tables, CICS datasets/files, and resources."""
    deps_path = report_dir / "knowledge_base" / "03_Dependencies.yaml"
    if not deps_path.exists():
        return 0
    deps = load_yaml(deps_path)
    if not deps:
        return 0

    db = deps.get("database", {}) or {}
    tables_read = db.get("tables_read", []) or []
    tables_updated = db.get("tables_updated", []) or []
    sql_stmts = db.get("sql_statements", []) or []
    resources = _classify_cics_resources(deps.get("cics_operations", []) or [])
    statement_resources = _extract_cics_resource_details(report_dir)
    for group_name, values in statement_resources.items():
        resources.setdefault(group_name, [])
        resources[group_name] = _dedupe_resource_facts(resources[group_name] + values)

    has_content = any([
        tables_read,
        tables_updated,
        sql_stmts,
        any(resources.values()),
    ])
    if not has_content:
        return 0

    lines = [f"Datasets, tables, and resources for {program}:"]
    if tables_read:
        lines.append(f"DB2 tables read: {', '.join(tables_read)}.")
    if tables_updated:
        lines.append(f"DB2 tables updated: {', '.join(tables_updated)}.")
    if sql_stmts:
        lines.append(f"SQL operations: {', '.join(sql_stmts)}.")
    _append_resource_lines(lines, "CICS datasets/files read", resources.get("cics_files_read", []))
    _append_resource_lines(lines, "CICS datasets/files written", resources.get("cics_files_written", []))
    _append_resource_lines(lines, "CICS datasets/files browsed", resources.get("cics_files_browsed", []))
    _append_resource_lines(lines, "CICS queues", resources.get("cics_queues", []))
    _append_resource_lines(lines, "CICS maps", resources.get("cics_maps", []))
    _append_resource_lines(lines, "CICS mapsets", resources.get("cics_mapsets", []))
    _append_resource_lines(lines, "CICS transaction ids", resources.get("cics_transactions", []))

    metadata = {
        "chunk_type": "datasets_tables_resources",
        "chunk_id": f"{program}:datasets_tables_resources",
        "parent_program_chunk": f"{program}:program_summary",
        "program": program,
        "db2_tables_read": tables_read,
        "db2_tables_updated": tables_updated,
        "sql_statements": sql_stmts,
        **resources,
    }
    write_chunk(
        chunks_dir,
        f"{program}__datasets_tables_resources.json",
        "\n".join(lines),
        metadata,
    )
    if verbose:
        print(f"  datasets_tables_resources: db2_r={len(tables_read)}, "
              f"resources={sum(len(v) for v in resources.values())}")
    return 1


def _extract_cics_call_details(report_dir: Path) -> dict[tuple[str, str], list[dict]]:
    details: dict[tuple[str, str], list[dict]] = {}
    for paragraph, statement in _iter_active_cics_statements(report_dir):
        command_match = re.search(r"\bEXEC\s+CICS\s+(LINK|XCTL)\b", statement, re.IGNORECASE)
        if not command_match:
            continue
        command = command_match.group(1).upper()
        target = _extract_cics_arg(statement, "PROGRAM")
        if not _is_valid_program_target(target):
            continue
        call = {
            "command": command,
            "target": str(target).strip().strip("'\"").upper(),
            "target_kind": "PROGRAM",
            "target_source": "literal" if _is_quoted_arg(target) else "identifier",
        }
        if paragraph:
            call["paragraph"] = paragraph
        commarea = _extract_cics_arg(statement, "COMMAREA")
        if commarea:
            call["commarea"] = _clean_cics_arg(commarea)
        length = _extract_cics_arg(statement, "LENGTH")
        if length:
            call["length"] = _clean_cics_arg(length)
        call["statement"] = statement
        details.setdefault((command, call["target"]), []).append(call)
    return {key: _dedupe_call_facts(value) for key, value in details.items()}


def _extract_cics_resource_details(report_dir: Path) -> dict[str, list[dict]]:
    resources: dict[str, list[dict]] = {}
    for paragraph, statement in _iter_active_cics_statements(report_dir):
        command_match = re.search(r"\bEXEC\s+CICS\s+([A-Z0-9-]+)\b", statement, re.IGNORECASE)
        command = command_match.group(1).upper() if command_match else ""
        for arg_name, group_name in [
            ("DATASET", "cics_files_read"),
            ("FILE", "cics_files_read"),
            ("QUEUE", "cics_queues"),
            ("QNAME", "cics_queues"),
            ("MAP", "cics_maps"),
            ("MAPSET", "cics_mapsets"),
            ("TRANSID", "cics_transactions"),
        ]:
            value = _extract_cics_arg(statement, arg_name)
            if not value:
                continue
            target = _clean_cics_arg(value)
            if not target:
                continue
            resolved_group = group_name
            if arg_name in {"DATASET", "FILE"}:
                resolved_group = _file_group_for_command(command)
            fact = {
                "target": target,
                "command": command,
                "target_source": "literal" if _is_quoted_arg(value) else "identifier",
            }
            if paragraph:
                fact["paragraph"] = paragraph
            resources.setdefault(resolved_group, []).append(fact)
    return {
        group: _dedupe_resource_facts(values)
        for group, values in resources.items()
    }


def _iter_active_cics_statements(report_dir: Path):
    narrative = report_dir / "knowledge_base" / "01_Logic_Narrative.md"
    if not narrative.exists():
        return
    paragraph = ""
    for raw_line in narrative.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if line.startswith("## "):
            paragraph = line[3:].strip()
            continue
        if "**CICS:**" not in line:
            continue
        match = re.search(r"`([^`]*EXEC\s+CICS[^`]*)`", line, re.IGNORECASE)
        if match:
            yield paragraph, " ".join(match.group(1).split())


def _extract_cics_arg(statement: str, arg_name: str) -> str:
    match = re.search(rf"\b{re.escape(arg_name)}\s*\(([^)]*)\)", statement, re.IGNORECASE)
    return match.group(1).strip() if match else ""


def _clean_cics_arg(value: str) -> str:
    return str(value or "").strip().strip("'\"")


def _is_quoted_arg(value: str) -> bool:
    value = str(value or "").strip()
    return (value.startswith("'") and value.endswith("'")) or (
        value.startswith('"') and value.endswith('"')
    )


def _dedupe_call_facts(calls: list[dict]) -> list[dict]:
    result = []
    seen = set()
    for call in calls:
        key = (
            call.get("command"),
            call.get("target"),
            call.get("paragraph"),
            call.get("commarea"),
            call.get("length"),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(call)
    return result


def _classify_cics_resources(cics_operations: list[dict]) -> dict[str, list[dict]]:
    resources: dict[str, list[dict]] = {
        "cics_files_read": [],
        "cics_files_written": [],
        "cics_files_browsed": [],
        "cics_queues": [],
        "cics_maps": [],
        "cics_mapsets": [],
        "cics_transactions": [],
    }
    for op in cics_operations:
        if not isinstance(op, dict):
            continue
        target = str(op.get("target", "")).strip()
        target_kind = str(op.get("target_kind", "")).strip().upper()
        if not target or not target_kind:
            continue
        command = str(op.get("command", "")).upper()
        op_type = str(op.get("type", "")).lower()
        group = ""
        if target_kind in {"FILE", "DATASET"}:
            group = _file_group_for_command(command, op_type)
        elif target_kind == "QUEUE":
            group = "cics_queues"
        elif target_kind == "MAP":
            group = "cics_maps"
        elif target_kind == "MAPSET":
            group = "cics_mapsets"
        elif target_kind == "TRANSID":
            group = "cics_transactions"
        if not group:
            continue
        fact = {
            "target": target,
            "command": command,
        }
        if op.get("target_source"):
            fact["target_source"] = op["target_source"]
        resources.setdefault(group, []).append(fact)
    return {
        group: _dedupe_resource_facts(values)
        for group, values in resources.items()
    }


def _file_group_for_command(command: str, op_type: str = "") -> str:
    command = str(command or "").upper()
    op_type = str(op_type or "").lower()
    if command in {"WRITE", "REWRITE", "DELETE"} or "write" in op_type or "delete" in op_type:
        return "cics_files_written"
    if command in {"STARTBR", "READNEXT", "READPREV", "ENDBR"} or "browse" in op_type:
        return "cics_files_browsed"
    return "cics_files_read"


def _dedupe_resource_facts(resources: list[dict]) -> list[dict]:
    result = []
    seen = set()
    for resource in resources:
        key = (
            resource.get("target"),
            resource.get("command"),
            resource.get("paragraph"),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(resource)
    return result


def _append_resource_lines(lines: list[str], label: str, resources: list[dict]) -> None:
    if not resources:
        return
    rendered = []
    for resource in resources:
        text = str(resource.get("target", ""))
        details = []
        if resource.get("command"):
            details.append(str(resource["command"]))
        if resource.get("paragraph"):
            details.append(f"in {resource['paragraph']}")
        if details:
            text += f" ({', '.join(details)})"
        rendered.append(text)
    lines.append(f"{label}: {', '.join(rendered)}.")


def generate_static_values(report_dir: Path, chunks_dir: Path,
                           program: str, verbose: bool) -> int:
    """Create one aggregate chunk for statically assigned COBOL values."""
    values = _load_variable_values(report_dir)
    if not values:
        return 0

    provenance = _extract_static_value_provenance(report_dir)
    consumer_lookup = _extract_static_value_consumers(report_dir, set(values.keys()), provenance)
    entries = []
    for variable, assigned_values in sorted(values.items()):
        clean_values = [str(v) for v in assigned_values if str(v).strip()]
        if clean_values:
            entry = {"variable": variable, "values": clean_values}
            if variable in provenance:
                entry["paragraphs"] = provenance[variable]["paragraphs"]
                entry["category"] = provenance[variable]["category"]
            else:
                entry["category"] = _classify_static_value(variable, [])
            entry["consumers"] = consumer_lookup.get(variable) or [{
                "role": "unknown",
                "paragraph": None,
                "evidence": "no explicit consumer found in available paragraph/CICS evidence",
            }]
            entries.append(entry)
    if not entries:
        return 0

    lines = [f"Static and forced values for program {program}:"]
    for entry in entries:
        rendered_values = ", ".join(entry["values"])
        line = f"- {entry['variable']}: {rendered_values}"
        if entry.get("category"):
            line += f". Category: {entry['category']}"
        if entry.get("paragraphs"):
            line += f". Paragraphs: {', '.join(entry['paragraphs'])}"
        if entry.get("consumers"):
            line += ". Consumer: " + _render_static_consumers(entry["consumers"])
        lines.append(line)

    metadata = {
        "chunk_type": "static_values",
        "chunk_id": f"{program}:static_values",
        "parent_program_chunk": f"{program}:program_summary",
        "program": program,
        "variables": [entry["variable"] for entry in entries],
        "variable_count": len(entries),
        "value_count": sum(len(entry["values"]) for entry in entries),
        "static_values": entries,
    }
    write_chunk(
        chunks_dir,
        f"{program}__static_values.json",
        "\n".join(lines),
        metadata,
    )
    if verbose:
        print(f"  static_values: variables={len(entries)}")
    return 1


def _extract_static_value_provenance(report_dir: Path) -> dict[str, dict]:
    """Extract paragraph-level provenance from generated narrative Known values lines."""
    narrative = report_dir / "knowledge_base" / "01_Logic_Narrative.md"
    if not narrative.exists():
        return {}
    found: dict[str, set[str]] = {}
    paragraph = ""
    for raw_line in narrative.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if line.startswith("## "):
            paragraph = line[3:].strip()
            continue
        match = re.search(r"\bKnown values:\s+([A-Z0-9_$#@-]+)\s*=", line)
        if not match:
            continue
        variable = match.group(1)
        if paragraph:
            found.setdefault(variable, set()).add(paragraph)

    result = {}
    for variable, paragraphs in found.items():
        ordered = sorted(paragraphs)
        result[variable] = {
            "paragraphs": ordered,
            "category": _classify_static_value(variable, ordered),
        }
    return result


def _extract_static_value_consumers(report_dir: Path, variables: set[str],
                                   provenance: dict[str, dict]) -> dict[str, list[dict]]:
    """Infer static-value consumers from same-paragraph CICS evidence.

    This intentionally stays conservative: it only uses variables with paragraph
    provenance and active CICS statements already present in the report narrative.
    """
    by_paragraph: dict[str, list[str]] = {}
    for paragraph, statement in _iter_active_cics_statements(report_dir):
        if paragraph:
            by_paragraph.setdefault(paragraph, []).append(statement)

    result: dict[str, list[dict]] = {}
    for variable in sorted(variables):
        paragraphs = provenance.get(variable, {}).get("paragraphs", [])
        category = provenance.get(variable, {}).get("category", _classify_static_value(variable, paragraphs))
        facts: list[dict] = []
        for paragraph in paragraphs:
            for statement in by_paragraph.get(paragraph, []):
                fact = _static_consumer_from_cics_statement(variable, category, paragraph, statement)
                if fact:
                    facts.append(fact)
        if facts:
            result[variable] = _dedupe_static_consumers(facts)
    return result


def _static_consumer_from_cics_statement(variable: str, category: str,
                                        paragraph: str, statement: str) -> dict | None:
    command_match = re.search(r"\bEXEC\s+CICS\s+([A-Z0-9-]+)\b", statement, re.IGNORECASE)
    command = command_match.group(1).upper() if command_match else ""
    if not command:
        return None

    program_target = _clean_cics_arg(_extract_cics_arg(statement, "PROGRAM"))
    for arg_name, role in [
        ("COMMAREA", "external-call COMMAREA"),
        ("LENGTH", "external-call length"),
        ("TRANSID", "CICS transaction id"),
        ("MAP", "screen/map field"),
        ("MAPSET", "screen/map field"),
        ("QUEUE", "CICS queue name"),
        ("QNAME", "CICS queue name"),
        ("FILE", "CICS file/dataset name"),
        ("DATASET", "CICS file/dataset name"),
    ]:
        raw_value = _extract_cics_arg(statement, arg_name)
        if not raw_value:
            continue
        value = _clean_cics_arg(raw_value)
        if not _variable_matches_cics_arg(variable, value):
            continue
        fact = {
            "role": role,
            "paragraph": paragraph,
            "command": command,
            "argument": arg_name,
            "argument_value": value,
            "evidence": statement,
        }
        if program_target:
            fact["target_program"] = program_target
        return fact

    category_l = str(category or "").lower()
    if "screen/map" in category_l and command in {"SEND", "RECEIVE"}:
        target = _clean_cics_arg(_extract_cics_arg(statement, "MAP")) or _clean_cics_arg(_extract_cics_arg(statement, "MAPSET"))
        return {
            "role": "screen/map field",
            "paragraph": paragraph,
            "command": command,
            "argument": "MAP/MAPSET",
            "argument_value": target,
            "evidence": statement,
        }
    if "abend" in category_l and command in {"ABEND", "LINK", "XCTL"}:
        return {
            "role": "abend/error handling",
            "paragraph": paragraph,
            "command": command,
            "argument": "CICS",
            "argument_value": program_target,
            "evidence": statement,
        }
    return None


def _variable_matches_cics_arg(variable: str, arg_value: str) -> bool:
    var_u = str(variable or "").upper()
    arg_u = str(arg_value or "").upper()
    if not var_u or not arg_u:
        return False
    if var_u == arg_u:
        return True
    root = var_u.split("-", 1)[0]
    if len(root) >= 7 and root in arg_u:
        return True
    if arg_u.startswith("W") and len(root) >= 7 and root in arg_u[1:]:
        return True
    return False


def _dedupe_static_consumers(consumers: list[dict]) -> list[dict]:
    result = []
    seen = set()
    for consumer in consumers:
        key = (
            consumer.get("role"),
            consumer.get("paragraph"),
            consumer.get("command"),
            consumer.get("argument"),
            consumer.get("argument_value"),
            consumer.get("target_program"),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(consumer)
    return result


def _render_static_consumers(consumers: list[dict]) -> str:
    rendered = []
    for consumer in consumers[:3]:
        role = consumer.get("role", "unknown")
        if role == "unknown":
            rendered.append("unknown")
            continue
        text = role
        if consumer.get("target_program"):
            text += f" for {consumer['command']} {consumer['target_program']}"
        elif consumer.get("command"):
            text += f" for {consumer['command']}"
        if consumer.get("argument") and consumer.get("argument_value"):
            text += f" via {consumer['argument']} {consumer['argument_value']}"
        if consumer.get("paragraph"):
            text += f" in {consumer['paragraph']}"
        rendered.append(text)
    if len(consumers) > 3:
        rendered.append(f"{len(consumers) - 3} more")
    return "; ".join(rendered)


def _classify_static_value(variable: str, paragraphs: list[str]) -> str:
    variable_u = str(variable or "").upper()
    paragraph_text = " ".join(paragraphs).upper()
    if "ABEND" in variable_u or "ABEND" in paragraph_text:
        return "abend code"
    if any(term in variable_u for term in ("FUNZIONE", "RETURN", "KOST", "NELEM", "CODICE")):
        if "LINK" in paragraph_text:
            return "external-call parameter"
        return "parameter setup"
    if any(term in variable_u for term in ("MAP", "RIGA", "MSG", "M1")):
        return "screen/map field"
    if "SEP" in variable_u or "SEPARA" in variable_u:
        return "separator/literal formatting value"
    if any(term in variable_u for term in ("FASE", "STATO", "BROWSE")):
        return "CICS control value"
    return "initialization or business constant"


# =============================================================================
# Group C — paragraph_logic
# =============================================================================

def generate_paragraph_logic(report_dir: Path, chunks_dir: Path,
                             program: str, verbose: bool) -> int:
    """Split 01_Logic_Narrative.md by paragraph headings.

    Cross-checks headings against CFG paragraph names to avoid
    treating '## Program Overview' as a paragraph chunk.
    Prepends enriched English comments when available.
    """
    narrative_path = report_dir / "knowledge_base" / "01_Logic_Narrative.md"
    if not narrative_path.exists():
        if verbose:
            print(f"  Skipping paragraph_logic: narrative not found")
        return 0

    text = narrative_path.read_text(encoding="utf-8")

    # Get valid paragraph names from CFG
    cfg_paragraphs = _get_cfg_paragraph_names(report_dir)

    # Build paragraph → section map for metadata
    section_map = _build_paragraph_section_map(report_dir)

    # Load enriched comments if available
    enriched = _load_enriched_comments(report_dir)

    # Split by ## headings
    sections = re.split(r"(?=^## )", text, flags=re.MULTILINE)
    count = 0
    struct = _load_cobol_structure(report_dir)
    profiles = struct.get("paragraph_profiles", {})
    for section in sections:
        m = re.match(r"^## (.+)", section)
        if not m:
            continue
        heading = m.group(1).strip()

        # Skip non-paragraph headings
        if heading == "Program Overview":
            continue
        # If we have CFG data, only accept known paragraph names
        if cfg_paragraphs and heading not in cfg_paragraphs:
            continue

        body = section[m.end():].strip()
        # Remove horizontal rules
        body = re.sub(r"^---\s*$", "", body, flags=re.MULTILINE).strip()

        # Extract PERFORM calls from the FULL body (before stripping reverse
        # section) because bold **PERFORM** markers only appear there.
        # Also extract from forward-section `PERFORM ...` inside backticks.
        raw_calls_bold = re.findall(r"\*\*PERFORM\*\*\s+`(.+?)`", body)
        raw_calls_inline = re.findall(
            r"- `(?:PERFORM\s+)([A-Za-z0-9_-]+(?:\s+(?:THRU|THROUGH)\s+[A-Za-z0-9_-]+)?)",
            body, re.IGNORECASE,
        )
        # Merge both sources, deduplicate by target name
        seen_targets = set()
        raw_calls = []
        for c in raw_calls_bold + raw_calls_inline:
            target = re.split(r"\s+(?:THRU|THROUGH)\s+", c, maxsplit=1,
                              flags=re.IGNORECASE)[0].strip().upper()
            if target not in seen_targets:
                seen_targets.add(target)
                raw_calls.append(c)

        # Remove duplicate reverse-order content (7b.5).
        # The knowledge_base_builder traverses FOLLOWED_BY + STARTS_WITH edges,
        # producing forward-order statements (period-terminated backtick lines)
        # followed by reverse-order duplicates (bold **PERFORM** or no-period
        # backtick lines).  Keep only up to the last period-terminated line.
        body_lines = body.split("\n")
        last_fwd_idx = -1
        for i, ln in enumerate(body_lines):
            # Forward-order lines: - `...TEXT.` (period before closing backtick)
            if re.match(r"^- `.*\.\s*`$", ln):
                last_fwd_idx = i
        if last_fwd_idx >= 0:
            # Keep everything up to and including the last forward line,
            # plus any non-statement lines (blockquotes, blanks) that follow.
            kept = body_lines[: last_fwd_idx + 1]
            # Also keep trailing blockquote / blank lines (not statement lines)
            for ln in body_lines[last_fwd_idx + 1 :]:
                if ln.startswith("- "):
                    break  # start of reverse section
                kept.append(ln)
            body = "\n".join(kept).strip()

        # Build chunk text: comment_english (if available) + heading + body
        parts = []
        comment_meta = enriched.get(heading, {})
        comment_english = comment_meta.get("english", "")
        if comment_english:
            parts.append(comment_english)
            
        prof = profiles.get(heading)
        if prof and prof.get("structural_patterns"):
            pats = prof["structural_patterns"]
            if len(pats) > 1:
                pat_str = ", ".join(pats[:-1]) + " and " + pats[-1]
            else:
                pat_str = pats[0]
            parts.append(f"*This paragraph performs {pat_str}.*")
            
        parts.append(heading)
        parts.append(body)
        chunk_text = "\n".join(parts)

        # raw_calls already extracted above (before body strip)
        # Normalize THRU whitespace (7b.7): collapse multiple spaces
        calls = [re.sub(r"\s+", " ", c).strip() for c in raw_calls]
        has_comments = bool(comment_english)

        metadata = {
            "chunk_type": "paragraph_logic",
            "chunk_id": f"{program}:paragraph_logic:{heading}",
            "parent_program_chunk": f"{program}:program_summary",
            "program": program,
            "paragraph": heading,
            "section": section_map.get(heading, ""),
            "calls": calls,
            "has_comments": has_comments,
            "comment_english": comment_english if has_comments else None,
            "comment_category": comment_meta.get("category") if has_comments else None,
        }
        if prof and prof.get("structural_patterns"):
            metadata["structural_patterns"] = prof["structural_patterns"]
        safe_name = re.sub(r"[^\w\-]", "_", heading)
        write_chunk(
            chunks_dir, f"{program}__paragraph__{safe_name}.json",
            chunk_text, metadata,
        )
        count += 1

    if verbose:
        print(f"  paragraph_logic: {count} chunks "
              f"({sum(1 for v in enriched.values() if v.get('english'))} with comments)")
    return count


def _get_cfg_paragraph_names(report_dir: Path) -> set[str]:
    """Return set of paragraph names from CFG JSON."""
    cfg_dir = report_dir / "cfg"
    if not cfg_dir.is_dir():
        return set()
    cfg_files = list(cfg_dir.glob("cfg-*.json"))
    if not cfg_files:
        return set()
    data = load_json(cfg_files[0])
    if not data:
        return set()
    return {
        n["name"] for n in data.get("nodes", [])
        if n.get("type") == "PARAGRAPH" and "/" not in n.get("name", "")
    }


def _build_paragraph_section_map(report_dir: Path) -> dict[str, str]:
    """Return ``{paragraph_name: enclosing_section_name}`` from the CFG graph.

    The actual graph structure linking paragraphs to their enclosing section
    is NOT a pure STARTS_WITH chain.  The real path (confirmed by inspection
    of real CFG outputs) is::

        SECTION
          --STARTS_WITH--> SECTION_HEADER
          --FOLLOWED_BY--> PARAGRAPHS
          --STARTS_WITH--> SENTENCE   (first statement)
          --FOLLOWED_BY--> PARAGRAPH  (first paragraph)
          --FOLLOWED_BY--> PARAGRAPH  (next paragraph)
          ...

    The original implementation only walked reverse STARTS_WITH edges, which
    stopped at the PARAGRAPHS node and never reached SECTION because the edge
    from PARAGRAPHS to SECTION_HEADER is FOLLOWED_BY (not STARTS_WITH).

    **Fix**: perform a BFS upward from each PARAGRAPH node using *both*
    reverse STARTS_WITH and reverse FOLLOWED_BY edges.  The first SECTION
    node encountered is the enclosing section.  A ``visited`` set prevents
    cycles (the graph has some FOLLOWED_BY edges that loop back).

    Paragraphs with "/" in their name are skipped — these are COPY-injected
    qualified names that are not real procedure paragraphs.

    Args:
        report_dir: Report directory containing the ``cfg/`` subdirectory.

    Returns:
        Dict mapping paragraph name → enclosing section name.  Paragraphs
        not enclosed in any named section map to ``""``.
    """
    cfg_dir = report_dir / "cfg"
    if not cfg_dir.is_dir():
        return {}
    cfg_files = list(cfg_dir.glob("cfg-*.json"))
    if not cfg_files:
        return {}
    data = load_json(cfg_files[0])
    if not data:
        return {}

    nodes = data.get("nodes", [])
    edges = data.get("edges", [])
    node_by_id: dict[str, dict] = {n["id"]: n for n in nodes}

    # Build reverse maps: toNodeID → list of fromNodeIDs, per edge type.
    # We need reverse STARTS_WITH and reverse FOLLOWED_BY to walk upward.
    reverse_starts_with: dict[str, list[str]] = {}
    reverse_followed_by: dict[str, list[str]] = {}
    for e in edges:
        etype = e.get(EDGE_TYPE, "")
        src = e.get(EDGE_SOURCE, "")
        tgt = e.get(EDGE_TARGET, "")
        if etype == "STARTS_WITH":
            reverse_starts_with.setdefault(tgt, []).append(src)
        elif etype == "FOLLOWED_BY":
            reverse_followed_by.setdefault(tgt, []).append(src)

    result: dict[str, str] = {}
    for n in nodes:
        if n.get("type") != "PARAGRAPH" or "/" in n.get("name", ""):
            continue

        # BFS upward using both reverse edge types
        section_name = ""
        visited: set[str] = set()
        queue: list[str] = [n["id"]]
        while queue:
            cur_id = queue.pop(0)
            if cur_id in visited:
                continue
            visited.add(cur_id)
            cur_node = node_by_id.get(cur_id, {})
            if cur_node.get("type") == "SECTION":
                section_name = cur_node.get("name", "")
                break
            # Expand via reverse STARTS_WITH
            for parent_id in reverse_starts_with.get(cur_id, []):
                if parent_id not in visited:
                    queue.append(parent_id)
            # Expand via reverse FOLLOWED_BY
            for parent_id in reverse_followed_by.get(cur_id, []):
                if parent_id not in visited:
                    queue.append(parent_id)

        result[n.get("name", "")] = section_name

    return result


def _normalize_call_target(raw: str) -> str:
    """Strip THRU/THROUGH suffix from PERFORM target string.

    'PREPARA-MAP   THRU PREPARA-MAP-EXIT' → 'PREPARA-MAP'
    'SINGLE-PARA' → 'SINGLE-PARA'
    """
    return re.split(r"\s+(?:THRU|THROUGH)\s+", raw, maxsplit=1,
                    flags=re.IGNORECASE)[0].strip()


def _load_enriched_comments(report_dir: Path) -> dict:
    """Load comments_enriched.json if it exists."""
    path = report_dir / "comments_enriched.json"
    if not path.exists():
        return {}
    data = load_json(path)
    return data if isinstance(data, dict) else {}


# =============================================================================
# Group D — variable_group
# =============================================================================

def _collect_88_conditions(children: list, depth: int = 0) -> list[str]:
    """Recursively find 88-level entries and format as readable condition descriptions.

    Example output line:
      "WS-STATUS-OK (88-level condition) means WS-STATUS = 'OK'"
    """
    lines = []
    parent_name = None
    for child in children:
        level = child.get("levelNumber", 0)
        if level != 88:
            parent_name = child.get("name", parent_name)
            sub = _collect_88_conditions(child.get("children", []), depth + 1)
            lines.extend(sub)
        else:
            cname = child.get("name", "")
            raw = child.get("rawText", "").strip()
            # Extract VALUE clause from rawText
            val_m = re.search(r"\bVALUE[S]?\s+(.+?)(?:\s*\.|$)", raw, re.IGNORECASE)
            val_str = val_m.group(1).strip() if val_m else raw
            if parent_name and parent_name != "FILLER":
                lines.append(f"  {cname} means {parent_name} = {val_str}")
            else:
                lines.append(f"  {cname}: VALUE {val_str}")
    return lines


def _build_redefines_explanation(record: dict, children: list) -> str:
    """Return a REDEFINES explanation sentence for a level-01 record if applicable.

    Looks for the redefines marker on the record itself or on top-level children.
    Returns empty string if no REDEFINES found.
    """
    # Check the record itself
    raw = record.get("rawText", "")
    m = re.search(r"\bREDEFINES\s+([A-Za-z0-9_-]+)", raw, re.IGNORECASE)
    if m:
        target = m.group(1).upper()
        rec_name = record.get("name", "?").upper()
        # Find PIC of first child to describe the new interpretation
        pic = ""
        for c in children:
            c_raw = c.get("rawText", "")
            pm = re.search(r"\bPIC(?:TURE)?\s+([^\s.]+)", c_raw, re.IGNORECASE)
            if pm:
                pic = pm.group(1)
                break
        if pic:
            return (f"REDEFINES: {rec_name} reinterprets the same memory as {target} "
                    f"(new layout uses PIC {pic}).")
        return f"REDEFINES: {rec_name} reinterprets the same memory as {target}."

    # Check direct children for REDEFINES
    redef_children = []
    for c in children:
        cr = c.get("rawText", "")
        m2 = re.search(r"\bREDEFINES\s+([A-Za-z0-9_-]+)", cr, re.IGNORECASE)
        if m2:
            redef_children.append((c.get("name", "?").upper(), m2.group(1).upper()))
    if redef_children:
        parts = [f"{n} REDEFINES {t}" for n, t in redef_children]
        return "Field-level REDEFINES: " + "; ".join(parts) + "."
    return ""


def generate_variable_groups(report_dir: Path, chunks_dir: Path,
                             program: str, verbose: bool) -> int:
    """Create one chunk per level-01 record in *-data.json."""
    ds_dir = report_dir / "data_structures"
    if not ds_dir.is_dir():
        if verbose:
            print(f"  Skipping variable_group: data_structures/ not found")
        return 0
    ds_files = list(ds_dir.glob("*-data.json"))
    if not ds_files:
        return 0

    data = load_json(ds_files[0])
    if not data:
        return 0

    # Load variable static values for enrichment
    var_values = _load_variable_values(report_dir)

    # Root node has children = level-01 records
    children = data.get("children", [])
    pending_chunks: list[tuple[str, str, dict]] = []
    filler_index = 0
    
    struct = _load_cobol_structure(report_dir)
    conds_88 = struct.get("conditions_88", {})
    redefs = struct.get("redefines", [])

    for record in children:
        level = record.get("levelNumber", 0)
        if level != 1:
            continue

        name = record.get("name", "UNKNOWN")
        if name == "FILLER":
            filler_index += 1
            name = f"FILLER_{filler_index}"

        section = record.get("sourceSection", "UNKNOWN")
        rec_children = record.get("children", [])
        field_names = [c.get("name", "?") for c in rec_children]

        # Build text representation — cap to avoid exceeding token limits
        lines = [f"Variable group {name} in {section}:"]
        lines.append(f"  Level 01, {len(rec_children)} fields.")
        # Include field definitions for embedding
        for child in rec_children:
            cname = child.get("name", "FILLER")
            clevel = child.get("levelNumber", "")
            raw = child.get("rawText", "").strip()
            if raw:
                lines.append(f"  {raw}")
            else:
                lines.append(f"  {clevel:02d} {cname}")
            # Recurse one more level for nested children
            for grandchild in child.get("children", []):
                graw = grandchild.get("rawText", "").strip()
                if graw:
                    lines.append(f"    {graw}")
            # Check if we're approaching the token limit
            if token_count("\n".join(lines)) > MAX_CHUNK_TOKENS - 20:
                lines.append(f"  ... ({len(rec_children) - len(lines) + 2} more fields)")
                break

        # Append known static values for fields in this group
        if var_values:
            val_lines = []
            for fn in field_names:
                if fn in var_values:
                    val_lines.append(
                        f"  {fn} known values: {', '.join(var_values[fn])}")
            if val_lines and token_count("\n".join(lines)) + token_count("\n".join(val_lines)) <= MAX_CHUNK_TOKENS:
                lines.append("Static assignments:")
                lines.extend(val_lines)

        # R5.3 & R5.4 — 88-level condition descriptions & REDEFINES from struct
        group_fields = set()
        group_88s = []
        def _walk_fields(nodes):
            for n in nodes:
                if n.get("name"): group_fields.add(n.get("name"))
                if n.get("levelNumber") == 88: group_88s.append(n.get("name", ""))
                _walk_fields(n.get("children", []))
        _walk_fields(rec_children)
        group_fields.add(name)
        
        cond_lines = []
        for cname in group_88s:
            if cname in conds_88:
                info = conds_88[cname]
                vals = ", ".join(info.get("values", []))
                parent = info.get("parent", "")
                cond_lines.append(f"{cname} (88-level condition) = {parent} equals {vals}")
                
        if cond_lines:
            cond_block = "Condition names (88-level):"
            if token_count("\n".join(lines)) + token_count(cond_block) + token_count("\n".join(cond_lines)) <= MAX_CHUNK_TOKENS:
                lines.append(cond_block)
                lines.extend(cond_lines)

        redef_lines = []
        for rd in redefs:
            if rd.get("redefining") in group_fields:
                bs = rd.get("byte_size", "")
                sz_str = f"same {bs} bytes" if bs else "same bytes"
                redef_lines.append(f"{rd['redefining']} REDEFINES {rd['redefines']} — {sz_str}, numeric interpretation.")
        
        if redef_lines and token_count("\n".join(lines)) + token_count("\n".join(redef_lines)) <= MAX_CHUNK_TOKENS:
            lines.extend(redef_lines)

        chunk_text = "\n".join(lines)

        # Filter FILLER from field_names (7b.6): keep named fields, count fillers
        named_fields = [fn for fn in field_names if fn != "FILLER"]
        filler_count = len(field_names) - len(named_fields)

        metadata = {
            "chunk_type": "variable_group",
            "chunk_id": f"{program}:variable_group:{name}",
            "parent_program_chunk": f"{program}:program_summary",
            "program": program,
            "group_name": name,
            "section": section,
            "child_count": len(rec_children),
            "field_names": named_fields[:50],  # cap for metadata size
            "filler_count": filler_count,
        }
        safe_name = re.sub(r"[^\w\-]", "_", name)
        pending_chunks.append((f"{program}__variable_group__{safe_name}.json", chunk_text, metadata))

    merged_chunks: list[tuple[str, str, dict]] = []
    i = 0
    while i < len(pending_chunks):
        filename, text, meta = pending_chunks[i]
        if token_count(text) >= MIN_CHUNK_TOKENS or i + 1 >= len(pending_chunks):
            merged_chunks.append((filename, text, meta))
            i += 1
            continue

        group_names = [meta.get("group_name", "UNKNOWN")]
        field_names = list(meta.get("field_names", []))
        child_count = int(meta.get("child_count", 0) or 0)
        merged_text = text
        j = i + 1
        while j < len(pending_chunks):
            _, next_text, next_meta = pending_chunks[j]
            if token_count(merged_text) >= MIN_CHUNK_TOKENS:
                break
            merged_text += "\n\n" + next_text
            group_names.append(next_meta.get("group_name", "UNKNOWN"))
            field_names.extend(next_meta.get("field_names", []))
            child_count += int(next_meta.get("child_count", 0) or 0)
            j += 1

        if len(group_names) > 1:
            meta = {
                **meta,
                "group_name": group_names[0],
                "group_names": group_names,
                "child_count": child_count,
                "field_names": list(dict.fromkeys(field_names))[:50],
            }
            safe_first = re.sub(r"[^\w\-]", "_", group_names[0])
            filename = f"{program}__variable_group__{safe_first}.json"
            merged_chunks.append((filename, merged_text, meta))
            i = j
        else:
            merged_chunks.append((filename, text, meta))
            i += 1

    count = 0
    for filename, chunk_text, metadata in merged_chunks:
        write_chunk(chunks_dir, filename, chunk_text, metadata)
        count += 1

    if verbose:
        print(f"  variable_group: {count} groups")
    return count


# =============================================================================
# Group E — CFG metadata enrichment
# =============================================================================

def _build_paragraph_subgraphs(report_dir: Path) -> dict[str, dict]:
    """Build per-paragraph metadata from CFG: local complexity, sql/cics ops.

    The CFG links paragraph content via FOLLOWED_BY chains, not
    STARTS_WITH containment. A paragraph's subgraph = its PARAGRAPH_NAME
    node + all FOLLOWED_BY-reachable nodes until the chain reaches
    another PARAGRAPH node or terminates.

    Returns {paragraph_name: {
        "complexity_local": int, "node_count": int,
        "sql_operations": list[str], "cics_commands": list[str]
    }}.
    """
    cfg_dir = report_dir / "cfg"
    if not cfg_dir.is_dir():
        return {}
    cfg_files = list(cfg_dir.glob("cfg-*.json"))
    if not cfg_files:
        return {}
    data = load_json(cfg_files[0])
    if not data:
        return {}

    nodes = data.get("nodes", [])
    edges = data.get("edges", [])

    node_by_id = {n["id"]: n for n in nodes}

    # Build adjacency lists by edge type
    sw_children = {}   # STARTS_WITH: parent -> [children]
    fb_from = {}       # FOLLOWED_BY: source -> [targets]
    jt_from = {}       # JUMPS_TO: source -> [targets]
    all_from = {}      # All non-STARTS_WITH: source -> [targets]

    for e in edges:
        etype = e.get(EDGE_TYPE)
        src, tgt = e[EDGE_SOURCE], e[EDGE_TARGET]
        if etype == "STARTS_WITH":
            sw_children.setdefault(src, []).append(tgt)
        elif etype == "FOLLOWED_BY":
            fb_from.setdefault(src, []).append(tgt)
            all_from.setdefault(src, []).append(tgt)
        elif etype == "JUMPS_TO":
            jt_from.setdefault(src, []).append(tgt)
            all_from.setdefault(src, []).append(tgt)

    # Find PARAGRAPH nodes and their PARAGRAPH_NAME children
    para_nodes = [n for n in nodes if n.get("type") == "PARAGRAPH"
                  and "/" not in n.get("name", "")]
    paragraph_ids = {n["id"] for n in para_nodes}

    result = {}
    for pn in para_nodes:
        pid = pn["id"]
        pname = pn.get("name", "")

        # Find PARAGRAPH_NAME child via STARTS_WITH
        pn_children = sw_children.get(pid, [])
        if not pn_children:
            result[pname] = {"complexity_local": 1, "node_count": 1}
            continue

        # Collect all nodes in this paragraph's subgraph:
        # BFS from PARAGRAPH_NAME via FOLLOWED_BY, stopping at PARAGRAPH nodes
        subgraph = {pid}  # include the PARAGRAPH node itself
        queue = list(pn_children)
        subgraph.update(pn_children)

        while queue:
            nid = queue.pop(0)
            # Follow FOLLOWED_BY edges (primary chain)
            for tgt in fb_from.get(nid, []):
                if tgt in subgraph:
                    continue
                tgt_node = node_by_id.get(tgt, {})
                # Stop at other PARAGRAPH boundaries
                if tgt_node.get("type") == "PARAGRAPH":
                    continue
                subgraph.add(tgt)
                queue.append(tgt)
            # Also include STARTS_WITH children of nodes in the chain
            for tgt in sw_children.get(nid, []):
                if tgt not in subgraph:
                    subgraph.add(tgt)
                    queue.append(tgt)

        # McCabe on open subgraphs (most JUMPS_TO leave the paragraph)
        # doesn't work. Use decision-node count + 1 instead:
        # each IF_BRANCH/EVALUATE adds one independent path.
        decision_types = {"IF_BRANCH", "EVALUATE", "SEARCH"}
        decisions = sum(
            1 for nid in subgraph
            if node_by_id.get(nid, {}).get("type") in decision_types
        )
        complexity = decisions + 1
        internal_nodes = len(subgraph)

        # Extract SQL and CICS operations from DIALECT nodes in the subgraph.
        # Skip DATA DIVISION structural markers — they are not executable statements.
        _NON_EXEC_SQL = ('BEGIN DECLARE', 'END DECLARE', 'INCLUDE ', 'WHENEVER ')
        sql_ops: list[str] = []
        cics_cmds: list[str] = []
        sql_nodes: list[dict] = []  # raw SQL texts for generate_sql_operations()
        _seen_sql_hashes: set[str] = set()  # dedup: same SQL block appears as multiple nodes
        for nid in subgraph:
            orig = node_by_id.get(nid, {}).get("originalText", "")
            orig_upper = orig.upper()
            if "EXEC SQL" in orig_upper:
                if not any(marker in orig_upper for marker in _NON_EXEC_SQL):
                    m = re.search(r"EXEC\s+SQL\s+(\w+)", orig_upper)
                    if m:
                        op = m.group(1).capitalize()
                        # Deduplicate: same SQL text may appear as many CFG nodes
                        _key = hashlib.sha256(orig.encode()).hexdigest()[:12]
                        if _key not in _seen_sql_hashes:
                            _seen_sql_hashes.add(_key)
                            sql_ops.append(op)
                            sql_nodes.append({"text": orig, "operation": op})
            if "EXEC CICS" in orig_upper:
                m = re.search(r"EXEC\s+CICS\s+(\w+)", orig_upper)
                if m:
                    cics_cmds.append(m.group(1).capitalize())

        result[pname] = {
            "complexity_local": complexity,
            "node_count": internal_nodes,
            "sql_operations": sorted(set(sql_ops)),
            "cics_commands": sorted(set(cics_cmds)),
            "sql_nodes": sql_nodes,
        }

    return result


def _compute_reachable_paragraphs(report_dir: Path) -> set[str] | None:
    """BFS from CFG root via all edge types to find reachable paragraphs.

    Returns a set of paragraph names reachable from the root, or None if
    CFG data is unavailable (consumers must skip the reachable flag).

    COBOL fall-through semantics: a paragraph with no JUMPS_TO can still be
    reached via FOLLOWED_BY from the prior paragraph. BFS over all edge types
    (FOLLOWED_BY + STARTS_WITH + JUMPS_TO) correctly handles this.
    """
    cfg_dir = report_dir / "cfg"
    if not cfg_dir.is_dir():
        return None
    cfg_files = list(cfg_dir.glob("cfg-*.json"))
    if not cfg_files:
        return None
    data = load_json(cfg_files[0])
    if not data:
        return None

    nodes = data.get("nodes", [])
    edges = data.get("edges", [])
    if not nodes:
        return set()

    node_by_id = {n["id"]: n for n in nodes}

    # Forward adjacency across all edge types
    adj: dict[str, list[str]] = {}
    all_targets: set[str] = set()
    for e in edges:
        src, tgt = e[EDGE_SOURCE], e[EDGE_TARGET]
        adj.setdefault(src, []).append(tgt)
        all_targets.add(tgt)

    # Root = node(s) with no incoming edges; fall back to first node
    roots = [n["id"] for n in nodes if n["id"] not in all_targets]
    if not roots:
        roots = [nodes[0]["id"]]

    # BFS
    visited: set[str] = set()
    queue = list(roots)
    while queue:
        nid = queue.pop(0)
        if nid in visited:
            continue
        visited.add(nid)
        for tgt in adj.get(nid, []):
            if tgt not in visited:
                queue.append(tgt)

    return {
        node_by_id[nid].get("name", "")
        for nid in visited
        if node_by_id.get(nid, {}).get("type") == "PARAGRAPH"
        and node_by_id[nid].get("name", "")
    }


def enrich_paragraph_chunks(chunks_dir: Path, report_dir: Path,
                            program: str, verbose: bool) -> int:
    """Add complexity_local, node_count, variable values, and loop bounds to paragraph chunks."""
    subgraphs = _build_paragraph_subgraphs(report_dir)
    var_values = _load_variable_values(report_dir)
    loop_info_map = _build_perform_loop_info(report_dir)  # R8.1
    all_vars = _load_all_variable_names(report_dir)        # R2.5
    var_usage = _build_variable_usage_from_cfg(report_dir, all_vars)  # R2.5

    # Enhancement 2b — copybooks used by this program (added to every paragraph chunk)
    struct = _load_cobol_structure(report_dir)
    _copybooks_used: list[str] = []
    if struct:
        copy_stmts = struct.get("copy_statements", [])
        _copybooks_used = list(dict.fromkeys(cs["copybook"] for cs in copy_stmts))

    # Enhancement 4 — dead code detection via CFG BFS
    reachable_set = _compute_reachable_paragraphs(report_dir)

    enriched = 0
    for chunk_file in chunks_dir.glob(f"{program}__paragraph__*.json"):
        data = load_json(chunk_file)
        if not data:
            continue
        para_name = data["metadata"].get("paragraph", "")
        changed = False

        # CFG complexity + SQL/CICS ops
        sg = subgraphs.get(para_name)
        if sg:
            data["metadata"]["complexity_local"] = sg["complexity_local"]
            data["metadata"]["node_count"] = sg["node_count"]
            data["metadata"]["sql_operations"] = sg.get("sql_operations", [])
            data["metadata"]["cics_commands"] = sg.get("cics_commands", [])
            changed = True

        # R2.5 — variables_modified / variables_read from Java CFG when available.
        usage = var_usage.get(para_name)
        if usage:
            modified_list, read_list, usage_source = usage
            if modified_list:
                data["metadata"]["variables_modified"] = modified_list
                changed = True
            if read_list:
                data["metadata"]["variables_read"] = read_list
                changed = True
            data["metadata"]["variable_usage_source"] = usage_source
            changed = True

        # R8.1 — PERFORM VARYING loop bounds
        loops = loop_info_map.get(para_name.upper(), [])
        if loops:
            data["metadata"]["loop_info"] = loops
            # Append narrative annotation to text
            loop_descs = []
            for li in loops:
                desc = (f"(loop: {li['variable']} from {li['from']} by {li['by']}"
                        f" until {li['until']})")
                if li.get("after"):
                    for a in li["after"]:
                        desc += (f", nested: {a['variable']} from {a['from']}"
                                 f" by {a['by']} until {a['until']}")
                loop_descs.append(desc)
            data["text"] += "\n" + " ".join(loop_descs)
            changed = True

        # Variable values: find variables mentioned in chunk text
        if var_values:
            text = data["text"]
            vars_in_chunk = {
                var: vals for var, vals in var_values.items()
                if var in text
            }
            if vars_in_chunk:
                # Append known values to text for richer embedding
                val_lines = [f"Known values: {var} = {', '.join(vals)}"
                             for var, vals in vars_in_chunk.items()]
                data["text"] += "\n" + "\n".join(val_lines)
                data["metadata"]["static_values"] = {
                    v: vs[:10] for v, vs in vars_in_chunk.items()
                }
                changed = True

        # Enhancement 4 — dead code detection
        if reachable_set is not None:
            data["metadata"]["reachable"] = para_name in reachable_set
            changed = True

        # Enhancement 2b — copybooks used by this program
        if _copybooks_used and "copybooks_used" not in data["metadata"]:
            data["metadata"]["copybooks_used"] = _copybooks_used
            changed = True

        if changed:
            # Recompute content_hash if text was extended
            data["metadata"]["content_hash"] = hashlib.sha256(
                data["text"].encode("utf-8")
            ).hexdigest()[:16]
            chunk_file.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            enriched += 1

    if verbose:
        sg_count = len(subgraphs) if subgraphs else 0
        vv_count = len(var_values) if var_values else 0
        print(f"  CFG enrichment: {enriched}/{sg_count} paragraphs enriched"
              f", {vv_count} variable value entries available")
    return enriched


def _load_all_variable_names(report_dir: Path) -> dict[str, str]:
    """Load all named fields from data_structures JSON.

    Returns {FIELD_NAME: group_name} mapping, skipping FILLER entries.
    """
    ds_dir = report_dir / "data_structures"
    if not ds_dir.is_dir():
        return {}
    ds_files = list(ds_dir.glob("*-data.json"))
    if not ds_files:
        return {}
    data = load_json(ds_files[0])
    if not data:
        return {}

    result: dict[str, str] = {}

    def _walk(node: dict, group: str) -> None:
        name = node.get("name", "")
        level = node.get("levelNumber", 0)
        if level == 1:
            group = name if name and name != "FILLER" else group
        if name and name != "FILLER" and name != "[ROOT]":
            result[name.upper()] = group
        for child in node.get("children", []):
            _walk(child, group)

    for record in data.get("children", []):
        _walk(record, record.get("name", "UNKNOWN"))

    return result


# Patterns for write (variable on the receiving end)
_COBOL_WRITE_PATTERNS = [
    re.compile(r"\bMOVE\b.+?\bTO\s+([A-Za-z][A-Za-z0-9_-]*)", re.IGNORECASE | re.DOTALL),
    re.compile(r"\bCOMPUTE\s+([A-Za-z][A-Za-z0-9_-]*)\s*=", re.IGNORECASE),
    re.compile(r"\bADD\b.+?\bTO\s+([A-Za-z][A-Za-z0-9_-]*)", re.IGNORECASE | re.DOTALL),
    re.compile(r"\bSUBTRACT\b.+?\bFROM\s+([A-Za-z][A-Za-z0-9_-]*)", re.IGNORECASE | re.DOTALL),
    re.compile(r"\bSET\s+([A-Za-z][A-Za-z0-9_-]*)\s+TO\b", re.IGNORECASE),
    re.compile(r"\bINITIALIZE\s+([A-Za-z][A-Za-z0-9_-]*)", re.IGNORECASE),
]
# Patterns for read (variable as source/condition)
_COBOL_READ_PATTERNS = [
    re.compile(r"\bIF\s+([A-Za-z][A-Za-z0-9_-]*)\b", re.IGNORECASE),
    re.compile(r"\bMOVE\s+([A-Za-z][A-Za-z0-9_-]*)\s+TO\b", re.IGNORECASE),
    re.compile(r"\bADD\s+([A-Za-z][A-Za-z0-9_-]*)\b", re.IGNORECASE),
]


def _build_variable_usage_from_cfg(
    report_dir: Path,
    all_vars: dict[str, str],
) -> dict[str, tuple[list[str], list[str], str]]:
    """Load paragraph variable usage from Java CFG, falling back to old text heuristics.

    Returns {paragraph_name: (variables_modified, variables_read, source)}.
    """
    cfg_dir = report_dir / "cfg"
    if not cfg_dir.is_dir() or not all_vars:
        return {}
    cfg_files = list(cfg_dir.glob("cfg-*.json"))
    if not cfg_files:
        return {}
    data = load_json(cfg_files[0])
    if not data:
        return {}

    nodes = data.get("nodes", [])
    java_usage = _build_java_variable_usage_from_cfg_nodes(nodes, all_vars)
    if java_usage:
        return java_usage

    edges = data.get("edges", [])
    node_by_id = {n["id"]: n for n in nodes}

    sw_children: dict[str, list[str]] = {}
    fb_from: dict[str, list[str]] = {}
    for e in edges:
        etype = e.get(EDGE_TYPE)
        src, tgt = e[EDGE_SOURCE], e[EDGE_TARGET]
        if etype == "STARTS_WITH":
            sw_children.setdefault(src, []).append(tgt)
        elif etype == "FOLLOWED_BY":
            fb_from.setdefault(src, []).append(tgt)

    para_nodes = [n for n in nodes if n.get("type") == "PARAGRAPH"
                  and "/" not in n.get("name", "")]

    result: dict[str, tuple[list[str], list[str], str]] = {}
    for pn in para_nodes:
        pid = pn["id"]
        pname = pn.get("name", "")

        # Collect subgraph (same BFS as _build_paragraph_subgraphs)
        subgraph: set[str] = {pid}
        queue = list(sw_children.get(pid, []))
        subgraph.update(queue)
        while queue:
            nid = queue.pop(0)
            for tgt in fb_from.get(nid, []):
                if tgt in subgraph:
                    continue
                if node_by_id.get(tgt, {}).get("type") == "PARAGRAPH":
                    continue
                subgraph.add(tgt)
                queue.append(tgt)
            for tgt in sw_children.get(nid, []):
                if tgt not in subgraph:
                    subgraph.add(tgt)
                    queue.append(tgt)

        # Gather all originalText in subgraph
        combined = " ".join(
            node_by_id[nid].get("originalText", "")
            for nid in subgraph
            if nid in node_by_id
        ).upper()

        modified: set[str] = set()
        read: set[str] = set()

        for pat in _COBOL_WRITE_PATTERNS:
            for m in pat.finditer(combined):
                candidate = m.group(1).strip().upper()
                if candidate in all_vars:
                    modified.add(candidate)

        for pat in _COBOL_READ_PATTERNS:
            for m in pat.finditer(combined):
                candidate = m.group(1).strip().upper()
                if candidate in all_vars and candidate not in modified:
                    read.add(candidate)

        if modified or read:
            result[pname] = (sorted(modified), sorted(read), "cfg_text_heuristic")

    return result


def _build_java_variable_usage_from_cfg_nodes(
    nodes: list[dict],
    all_vars: dict[str, str],
) -> dict[str, tuple[list[str], list[str], str]]:
    """Use Java-exported paragraph variable facts when the CFG schema provides them."""
    result: dict[str, tuple[list[str], list[str], str]] = {}
    for node in nodes:
        if node.get("type") != "PARAGRAPH" or "/" in node.get("name", ""):
            continue
        modified = _filter_java_variable_names(node.get("variablesModified", []), all_vars)
        read = _filter_java_variable_names(node.get("variablesRead", []), all_vars)
        if modified or read:
            result[node.get("name", "")] = (modified, read, "java_cfg_variables")
    return result


def _filter_java_variable_names(values: list, all_vars: dict[str, str]) -> list[str]:
    filtered: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        name = str(value).strip().upper()
        if not name or name in seen or name not in all_vars:
            continue
        seen.add(name)
        filtered.append(name)
    return filtered


def _load_variable_values(report_dir: Path) -> dict[str, list[str]]:
    """Load variable_values.json: {VAR_NAME: [val1, val2, ...]}."""
    path = report_dir / "variable_values.json"
    if not path.exists():
        return {}
    data = load_json(path)
    if not isinstance(data, list):
        return {}
    return {entry[0]: entry[1] for entry in data if len(entry) == 2}


# R8.1: PERFORM VARYING regex — matches the VARYING clause and optional AFTER clause.
# Pattern: PERFORM <para> VARYING <var> FROM <from> BY <by> UNTIL <until>
#          followed optionally by AFTER <var2> FROM ... UNTIL ...
_PERFORM_VARYING_RE = re.compile(
    r"\bPERFORM\s+(\S+)\s+VARYING\s+(\S+)\s+FROM\s+(\S+)\s+BY\s+(\S+)"
    r"\s+UNTIL\s+((?:(?!AFTER\b|\bVARYING\b|\bEND-PERFORM\b)\S+\s*)+)",
    re.IGNORECASE,
)
_PERFORM_AFTER_RE = re.compile(
    r"\bAFTER\s+(\S+)\s+FROM\s+(\S+)\s+BY\s+(\S+)"
    r"\s+UNTIL\s+((?:(?!AFTER\b|\bVARYING\b|\bEND-PERFORM\b)\S+\s*)+)",
    re.IGNORECASE,
)


def _build_perform_loop_info(report_dir: Path) -> dict[str, list[dict]]:
    """Scan CFG for PERFORM VARYING nodes; return {called_paragraph: [loop_info, ...]}.

    loop_info dict keys: variable, from, by, until, after (list of nested loop dicts).
    """
    cfg_dir = report_dir / "cfg"
    if not cfg_dir.is_dir():
        return {}
    cfg_files = list(cfg_dir.glob("cfg-*.json"))
    if not cfg_files:
        return {}
    data = load_json(cfg_files[0])
    if not data:
        return {}

    nodes = data.get("nodes", [])
    edges = data.get("edges", [])
    node_by_id = {n["id"]: n for n in nodes}
    # paragraph name → node id mapping
    para_id_by_name = {
        n.get("name", ""): n["id"]
        for n in nodes if n.get("type") == "PARAGRAPH"
    }
    # JUMPS_TO: source → [target ids]
    jt_targets: dict[str, list[str]] = {}
    for e in edges:
        if e.get("edgeType") == "JUMPS_TO":
            src = e[EDGE_SOURCE]
            jt_targets.setdefault(src, []).append(e[EDGE_TARGET])

    result: dict[str, list[dict]] = {}

    for n in nodes:
        orig = n.get("originalText", "")
        m = _PERFORM_VARYING_RE.search(orig)
        if not m:
            continue
        called_para = m.group(1).upper()
        loop = {
            "variable": m.group(2).upper(),
            "from": m.group(3),
            "by": m.group(4),
            "until": m.group(5).strip(),
        }
        # Collect AFTER (nested loop) clauses
        after_loops = [
            {
                "variable": a.group(1).upper(),
                "from": a.group(2),
                "by": a.group(3),
                "until": a.group(4).strip(),
            }
            for a in _PERFORM_AFTER_RE.finditer(orig)
        ]
        if after_loops:
            loop["after"] = after_loops

        result.setdefault(called_para, []).append(loop)

    return result


# =============================================================================
# Group F — JCL chunks: job_flow + step_detail
# =============================================================================

def generate_job_flow(report_dir: Path, chunks_dir: Path,
                      verbose: bool) -> int:
    """Generate a single job_flow chunk from jcl_summary.json + jcl_steps.json."""
    summary = load_json(report_dir / "jcl_summary.json")
    steps = load_json(report_dir / "jcl_steps.json")
    if not summary or not steps:
        return 0

    job_name = summary.get("job_name", "UNKNOWN")
    step_count = summary.get("step_count", 0)
    programs = summary.get("programs_invoked", [])
    ds_read = summary.get("datasets_read", [])
    ds_written = summary.get("datasets_written", [])
    has_cond = summary.get("has_conditional_flow", False)
    unresolved = summary.get("unresolved_symbols", [])

    # Build step sequence text
    step_seq = []
    for s in steps:
        sname = s.get("step_name", "?")
        pgm = s.get("program") or s.get("proc") or "?"
        cond = s.get("condition")
        entry = f"{sname} runs {pgm}"
        if cond:
            entry += f" if {cond}"
        step_seq.append(entry)

    lines = [
        f"Job {job_name} runs {step_count} steps invoking programs: "
        f"{', '.join(programs) if programs else 'none'}.",
        f"Step sequence: {' -> '.join(step_seq)}.",
    ]
    if ds_read:
        lines.append(f"Datasets read: {', '.join(ds_read)}.")
    if ds_written:
        lines.append(f"Datasets written: {', '.join(ds_written)}.")
    if has_cond:
        lines.append("Job contains conditional step execution (IF/THEN/ELSE).")
    if unresolved:
        lines.append(f"Unresolved symbols: {', '.join(unresolved)}.")

    metadata = {
        "chunk_type": "job_flow",
        "chunk_id": f"{job_name}:job_flow",
        "job_name": job_name,
        "step_count": step_count,
        "programs_invoked": programs,
        "datasets_read": ds_read,
        "datasets_written": ds_written,
        "has_conditional_flow": has_cond,
        "unresolved_symbols": unresolved,
    }
    write_chunk(chunks_dir, f"{job_name}__job_flow.json", "\n".join(lines), metadata)
    if verbose:
        print(f"  job_flow: {job_name}, {step_count} steps, "
              f"{len(programs)} programs")
    return 1


_COND_OP_INVERSE = {
    "LT": ">=", "LE": ">", "EQ": "!=", "NE": "=", "GT": "<=", "GE": "<",
}


def _interpret_cond(cond: str | None, cond_modifier: str | None) -> str:
    """R8.4 — Convert raw JCL COND= to a human-readable 'runs only if...' clause.

    COND logic is inverted: step is SKIPPED when condition is TRUE.
    Returns the positive form so readers know when the step runs.
    """
    if cond_modifier == "EVEN":
        return "runs even if a prior step abended"
    if cond_modifier == "ONLY":
        return "runs only if a prior step abended"
    if not cond:
        return ""
    raw = cond.strip()

    def _single(token: str) -> str:
        token = token.strip().strip("()")
        parts = [p.strip() for p in token.split(",")]
        if len(parts) < 2:
            return f"COND={token}"
        code, op = parts[0], parts[1].upper()
        step_ref = parts[2] if len(parts) >= 3 else None
        inv = _COND_OP_INVERSE.get(op, f"!{op}")
        if step_ref:
            return f"{step_ref} returned RC {inv} {code}"
        return f"all prior steps return RC {inv} {code}"

    inner = raw.strip("()")
    if re.search(r"\)\s*,\s*\(", inner):
        singles = re.findall(r"\(([^)]+)\)", inner)
        return "runs only if: " + " AND ".join(_single(s) for s in singles) if singles else f"COND={raw}"
    return "runs only if " + _single(raw)


def generate_step_details(report_dir: Path, chunks_dir: Path,
                          verbose: bool) -> int:
    """Generate one step_detail chunk per JCL step."""
    summary = load_json(report_dir / "jcl_summary.json")
    steps = load_json(report_dir / "jcl_steps.json")
    if not summary or not steps:
        return 0

    job_name = summary.get("job_name", "UNKNOWN")
    total_steps = len(steps)  # R2.3: used for position annotation
    count = 0

    for idx, s in enumerate(steps):
        step_name = s.get("step_name", "UNKNOWN")
        step_index = idx + 1  # 1-based
        pgm = s.get("program")
        proc = s.get("proc")
        cond = s.get("condition")
        cond_mod = s.get("cond_modifier")
        parm = s.get("parm")
        dds = s.get("dd_statements", [])

        # Classify DDs by access
        input_ds = []
        output_ds = []
        for dd in dds:
            dsn_raw = dd.get("dsn")
            if not dsn_raw:
                continue
            # DSN may be a dict for PDS member refs: {"dsn": "X", "member": "Y"}
            if isinstance(dsn_raw, dict):
                dsn = dsn_raw.get("dsn", "")
                member = dsn_raw.get("member", "")
                dsn = f"{dsn}({member})" if member else dsn
            else:
                dsn = str(dsn_raw)
            access = dd.get("access", "")
            if access == "read":
                input_ds.append(dsn)
            elif access in ("write", "append"):  # R8.2: append = MOD
                output_ds.append(dsn)
            else:
                # Classify by DISP if access not pre-classified
                disp = dd.get("disp", {})
                status = disp.get("status", "") if isinstance(disp, dict) else ""
                if status in ("SHR", "OLD"):
                    input_ds.append(dsn)
                elif status in ("NEW", "MOD"):
                    output_ds.append(dsn)

        # Build text
        lines = [f"Step {step_name} executes program {pgm or proc or 'unknown'}."]
        if cond or cond_mod:
            interp = _interpret_cond(cond, cond_mod)
            raw_cond = cond or ""
            if cond_mod:
                raw_cond = f"{raw_cond} {cond_mod}".strip()
            if interp:
                lines.append(f"Condition (COND={raw_cond}): {interp}.")
            else:
                lines.append(f"Condition: {raw_cond}.")
        else:
            lines.append("Condition: unconditional.")
        if parm:
            lines.append(f"Parameters: {parm}.")
        if input_ds:
            lines.append(f"Input datasets: {', '.join(input_ds)}.")
        if output_ds:
            lines.append(f"Output datasets: {', '.join(output_ds)}.")

        # R2.3 — step position annotation
        if total_steps == 1:
            position_label = "sole step"
        elif step_index == 1:
            position_label = "first step"
        elif step_index == total_steps:
            position_label = "final step"
        else:
            position_label = f"step {step_index} of {total_steps}"
        lines.append(f"This is the {position_label} in job {job_name}.")

        metadata = {
            "chunk_type": "step_detail",
            "step_index": step_index,
            "total_steps": total_steps,
            "chunk_id": f"{job_name}:step_detail:{step_name}",
            "job_name": job_name,
            "step_name": step_name,
            "program": pgm,
            "proc": proc,
            "condition": cond,
            "cond_modifier": cond_mod,
            "input_datasets": input_ds,
            "output_datasets": output_ds,
            "datasets": list(dict.fromkeys(input_ds + output_ds)),  # R2.6: unified list, deduped
        }
        safe_name = re.sub(r"[^\w\-]", "_", step_name)
        write_chunk(
            chunks_dir, f"{job_name}__step_detail__{safe_name}.json",
            "\n".join(lines), metadata,
        )
        count += 1

    if verbose:
        print(f"  step_detail: {count} steps for job {job_name}")
    return count


# =============================================================================
# Group G — Chunk size guard + manifest
# =============================================================================

def apply_size_guard(chunks_dir: Path, program_or_job: str,
                     verbose: bool) -> dict:
    """Merge small paragraph chunks into their parents, split large ones.

    Three merge strategies (tried in order):
      1. EXIT-to-parent: merge FOO-EXIT into FOO (COBOL convention)
      2. Consecutive: merge adjacent small chunks
      3. Orphan: any remaining <MIN chunk merges into the previous chunk

    Returns stats dict with merge/split counts.
    """
    stats = {"merged": 0, "split": 0}

    para_files = sorted(chunks_dir.glob(f"{program_or_job}__paragraph__*.json"))
    if not para_files:
        return stats

    # --- Pass 0: merge EXIT paragraphs into their parent ---
    # e.g. INIZ-PARAM-EXIT → merge into INIZ-PARAM
    exit_files = {}   # base_name -> exit_file_path
    parent_files = {} # base_name -> parent_file_path

    for f in para_files:
        d = load_json(f)
        if not d:
            continue
        para = d["metadata"].get("paragraph", "")
        if para.endswith("-EXIT"):
            base = para[:-5]  # strip -EXIT
            exit_files[base] = f
        else:
            parent_files[para] = f

    for base, exit_f in exit_files.items():
        if base not in parent_files:
            continue
        parent_f = parent_files[base]
        parent_data = load_json(parent_f)
        exit_data = load_json(exit_f)
        if not parent_data or not exit_data:
            continue

        # Append exit text to parent
        parent_data["text"] += "\n\n" + exit_data["text"]
        paras = parent_data["metadata"].get("paragraphs",
                    [parent_data["metadata"]["paragraph"]])
        paras.append(exit_data["metadata"].get("paragraph", ""))
        parent_data["metadata"]["paragraphs"] = paras
        _refresh_hash(parent_data)
        parent_f.write_text(
            json.dumps(parent_data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        exit_f.unlink()
        stats["merged"] += 1
        if verbose:
            print(f"    Merged {base}-EXIT into {base}")

    # Refresh file list after EXIT merges
    para_files = sorted(chunks_dir.glob(f"{program_or_job}__paragraph__*.json"))

    # --- Pass 1: merge remaining small consecutive chunks ---
    i = 0
    while i < len(para_files):
        data = load_json(para_files[i])
        if not data:
            i += 1
            continue
        tc = token_count(data["text"])

        if tc < MIN_CHUNK_TOKENS and i + 1 < len(para_files):
            merged_text = data["text"]
            merged_paragraphs = (data["metadata"].get("paragraphs") or
                                 [data["metadata"].get("paragraph", "?")])
            first_meta = data["metadata"]
            j = i + 1
            while j < len(para_files) and token_count(merged_text) < MIN_CHUNK_TOKENS:
                next_data = load_json(para_files[j])
                if not next_data:
                    j += 1
                    continue
                next_tc = token_count(next_data["text"])
                if next_tc >= MIN_CHUNK_TOKENS:
                    break
                merged_text += "\n\n" + next_data["text"]
                next_paras = (next_data["metadata"].get("paragraphs") or
                              [next_data["metadata"].get("paragraph", "?")])
                merged_paragraphs.extend(next_paras)
                para_files[j].unlink()
                j += 1
                stats["merged"] += 1

            if len(merged_paragraphs) > 1:
                first_meta["paragraphs"] = merged_paragraphs
                first_meta["paragraph"] = merged_paragraphs[0]
                data["text"] = merged_text
                data["metadata"] = first_meta
                _refresh_hash(data)
                suffix = f"+{len(merged_paragraphs) - 1}"
                safe_name = re.sub(r"[^\w\-]", "_", merged_paragraphs[0])
                new_name = f"{program_or_job}__paragraph__{safe_name}{suffix}.json"
                para_files[i].unlink()
                (chunks_dir / new_name).write_text(
                    json.dumps(data, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                if verbose:
                    print(f"    Merged {len(merged_paragraphs)} small paragraphs: "
                          f"{', '.join(merged_paragraphs)}")
            i = j
        else:
            i += 1

    # --- Pass 2: orphan merge — any remaining tiny chunk merges into previous ---
    para_files = sorted(chunks_dir.glob(f"{program_or_job}__paragraph__*.json"))
    for idx, f in enumerate(para_files):
        if idx == 0:
            continue
        data = load_json(f)
        if not data:
            continue
        if token_count(data["text"]) >= MIN_CHUNK_TOKENS:
            continue
        # Merge into previous chunk
        prev_f = para_files[idx - 1]
        prev_data = load_json(prev_f)
        if not prev_data:
            continue
        prev_data["text"] += "\n\n" + data["text"]
        prev_paras = (prev_data["metadata"].get("paragraphs") or
                      [prev_data["metadata"].get("paragraph", "?")])
        cur_paras = (data["metadata"].get("paragraphs") or
                     [data["metadata"].get("paragraph", "?")])
        prev_paras.extend(cur_paras)
        prev_data["metadata"]["paragraphs"] = prev_paras
        _refresh_hash(prev_data)
        prev_f.write_text(
            json.dumps(prev_data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        f.unlink()
        stats["merged"] += 1
        if verbose:
            print(f"    Orphan merged {cur_paras} into {prev_paras[0]}")

    # --- Pass 3: split oversized chunks ---
    for f in chunks_dir.glob(f"{program_or_job}__paragraph__*.json"):
        _split_if_needed(f, chunks_dir, stats, verbose)

    return stats


def _split_parts_with_context(text: str, metadata: dict) -> list[str]:
    chunk_type = metadata.get("chunk_type", "")
    if chunk_type in {
        "static_values",
        "external_program_calls",
        "datasets_tables_resources",
        "copybook_mentions",
        "copybook_fields",
        "comments",
        "commented_out_code",
    }:
        return _split_line_based_chunk(text, chunk_type)

    parts = split_bpe_text(text, MAX_CHUNK_TOKENS, OVERLAP_TOKENS)
    if len(parts) <= 1:
        return parts

    section = metadata.get("section", "")
    if chunk_type == "section_summary" and section:
        section_label = section if str(section).upper().startswith("SECTION") else f"SECTION {section}"
        continued = f"## Continued section: {section_label}\n\n"
        adjusted = [parts[0]]
        budget = max(1, MAX_CHUNK_TOKENS - token_count(continued))
        for part in parts[1:]:
            subparts = split_bpe_text(part, budget, OVERLAP_TOKENS)
            adjusted.extend(continued + subpart for subpart in subparts)
        return adjusted
    return parts


def _split_line_based_chunk(text: str, chunk_type: str) -> list[str]:
    """Split structured list chunks without cutting evidence lines in half."""
    lines = text.splitlines()
    if token_count(text) <= MAX_CHUNK_TOKENS or len(lines) <= 2:
        return [text]

    title = lines[0]
    body = [line for line in lines[1:] if line.strip()]
    continued = f"{title} (continued):"
    parts: list[str] = []
    current = [title]

    for line in body:
        candidate = current + [line]
        if token_count("\n".join(candidate)) <= MAX_CHUNK_TOKENS:
            current = candidate
            continue
        if len(current) > 1:
            parts.append("\n".join(current))
            current = [continued, line]
            if token_count("\n".join(current)) > MAX_CHUNK_TOKENS:
                parts.extend(split_bpe_text("\n".join(current), MAX_CHUNK_TOKENS, 0))
                current = [continued]
        else:
            # A single evidence line is too large; fall back for that line only.
            parts.extend(split_bpe_text("\n".join(candidate), MAX_CHUNK_TOKENS, 0))
            current = [continued]

    if len(current) > 1:
        parts.append("\n".join(current))

    return parts or [text]


def _split_if_needed(filepath: Path, chunks_dir: Path,
                     stats: dict, verbose: bool):
    """Split a chunk file if it exceeds MAX_CHUNK_TOKENS."""
    data = load_json(filepath)
    if not data:
        return
    text = data["text"]
    tc = token_count(text)
    if tc <= MAX_CHUNK_TOKENS:
        return

    parts = _split_parts_with_context(text, data.get("metadata", {}))
    if len(parts) <= 1:
        return

    stem = filepath.stem
    original_id = data["metadata"].get("chunk_id", stem)
    filepath.unlink()
    for idx, part_text in enumerate(parts, 1):
        part_meta = {
            **data["metadata"],
            "chunk_id": f"{original_id}:part:{idx}",
            "split_from": original_id,
            "part": idx,
            "part_index": idx,
            "total_parts": len(parts),
        }
        write_chunk(
            chunks_dir,
            f"{stem}__part{idx}.json",
            part_text,
            part_meta,
        )

    stats["split"] += 1
    if verbose:
        print(f"    Split {stem} into {len(parts)} parts ({tc} tokens)")


def apply_universal_size_guard(chunks_dir: Path, stats: dict | None = None,
                               verbose: bool = False) -> dict:
    """Split any chunk type that exceeds the configured token budget."""
    if stats is None:
        stats = {"split": 0}
    _SKIP = {"chunks_manifest.json", "bm25_index.json"}
    for f in sorted(chunks_dir.glob("*.json")):
        if f.name in _SKIP or not f.exists():
            continue
        _split_if_needed(f, chunks_dir, stats, verbose)
    return stats


def generate_bm25_index(chunks_dir: Path, verbose: bool) -> int:
    """Generate bm25_index.json for hybrid BM25 + vector retrieval.

    Pre-tokenizes every chunk's text into term-frequency maps so that a BM25
    retriever can be constructed at query time without re-reading all chunks.
    Includes structured metadata terms as a separate boosted-terms field.

    Returns total number of entries indexed.
    """
    _SKIP = {"chunks_manifest.json", "bm25_index.json"}
    index_entries = []

    for f in sorted(chunks_dir.glob("*.json")):
        if f.name in _SKIP:
            continue
        data = load_json(f)
        if not data:
            continue
        text = data.get("text", "")
        meta = data.get("metadata", {})
        if meta.get("indexable") is False:
            continue

        # Tokenize: COBOL identifiers use [A-Za-z][A-Za-z0-9_-]{2,}
        tokens = re.findall(r'[A-Za-z][A-Za-z0-9_\-]{2,}', text)
        tokens_upper = [t.upper() for t in tokens]

        # Term frequency map
        tf: dict[str, int] = {}
        for t in tokens_upper:
            tf[t] = tf.get(t, 0) + 1

        # Structured metadata terms (field values that should be boosted at query time)
        structured: set[str] = set()
        for field in ("paragraph", "group_name", "program", "section",
                      "sql_tables_read", "sql_tables_updated",
                      "field_names", "cics_commands", "calls", "tables",
                      "conditions", "cics_call_targets"):
            val = meta.get(field)
            if isinstance(val, str) and val:
                structured.add(val.upper())
            elif isinstance(val, list):
                for v in val:
                    if isinstance(v, str) and v:
                        structured.add(v.upper())
                    elif isinstance(v, dict):
                        # e.g. conditions: [{"name": "...", "parent": "..."}]
                        for vv in v.values():
                            if isinstance(vv, str) and vv:
                                structured.add(vv.upper())

        index_entries.append({
            "chunk_id": meta.get("chunk_id", f.stem),
            "file": f.name,
            "chunk_type": meta.get("chunk_type", "unknown"),
            "term_freq": tf,
            "structured_terms": sorted(structured),
            "total_tokens": len(tokens_upper),
        })

    avg_len = (
        sum(e["total_tokens"] for e in index_entries) / len(index_entries)
        if index_entries else 0.0
    )
    index = {
        "total_chunks": len(index_entries),
        "avg_doc_length": round(avg_len, 1),
        "entries": index_entries,
    }
    _atomic_write_json(chunks_dir / "bm25_index.json", index)
    if verbose:
        print(f"  bm25_index: {len(index_entries)} entries, "
              f"avg_len={avg_len:.0f} tokens")
    return len(index_entries)


def generate_manifest(chunks_dir: Path, verbose: bool) -> dict:
    """Write chunks_manifest.json summarizing all generated chunks."""
    entries = []
    _MANIFEST_SKIP = {"chunks_manifest.json", "bm25_index.json"}
    for f in sorted(chunks_dir.glob("*.json")):
        if f.name in _MANIFEST_SKIP:
            continue
        data = load_json(f)
        if not data:
            continue
        meta = data.get("metadata", {})
        text = data.get("text", "")
        entry = {
            "file": f.name,
            "chunk_type": meta.get("chunk_type", "unknown"),
            "program": meta.get("program") or meta.get("job_name", "unknown"),
            "token_count": len(text.split()),
        }
        if _TIKTOKEN_AVAILABLE:
            entry["token_count_bpe"] = _bpe_count(text)
        entries.append(entry)

    # Summary by type
    type_counts = {}
    hash_counts: dict[str, int] = {}
    for e in entries:
        ct = e["chunk_type"]
        type_counts[ct] = type_counts.get(ct, 0) + 1
    for f in sorted(chunks_dir.glob("*.json")):
        if f.name in _MANIFEST_SKIP:
            continue
        data = load_json(f)
        if not data:
            continue
        h = data.get("metadata", {}).get("content_hash")
        if h:
            hash_counts[h] = hash_counts.get(h, 0) + 1
    duplicate_count = sum(count - 1 for count in hash_counts.values() if count > 1)

    manifest = {
        "schema_version": CHUNK_SCHEMA_VERSION,
        "total_chunks": len(entries),
        "type_counts": type_counts,
        "duplicate_content_hashes": duplicate_count,
        "within_report_duplicate_content_hashes": duplicate_count,
        "global_duplicate_content_hashes": duplicate_count,
        "chunks": entries,
    }
    _atomic_write_json(chunks_dir / "chunks_manifest.json", manifest)
    if verbose:
        print(f"  Manifest: {len(entries)} chunks — {type_counts}")
    return manifest


def generate_rag_bundle(report_dir: Path, chunks_dir: Path,
                        program: str, verbose: bool) -> int:
    """Create report-local knowledge-base_rag folder for downstream RAG ingestion."""
    bundle_dir = report_dir / "knowledge-base_rag"
    if bundle_dir.exists():
        shutil.rmtree(bundle_dir)
    bundle_dir.mkdir(parents=True)

    bundle_chunks = bundle_dir / "chunks"
    bundle_kb = bundle_dir / "knowledge_base"
    bundle_artifacts = bundle_dir / "artifacts"
    bundle_chunks.mkdir()
    bundle_kb.mkdir()
    bundle_artifacts.mkdir()

    chunk_count = 0
    for chunk_file in sorted(chunks_dir.glob("*.json")):
        shutil.copy2(chunk_file, bundle_chunks / chunk_file.name)
        chunk_count += 1

    kb_count = 0
    kb_dir = report_dir / "knowledge_base"
    if kb_dir.is_dir():
        for kb_file in sorted(kb_dir.iterdir()):
            if kb_file.is_file() and kb_file.suffix.lower() in {".md", ".yaml", ".yml", ".json"}:
                shutil.copy2(kb_file, bundle_kb / kb_file.name)
                kb_count += 1

    artifact_names = [
        "analysis_health.json",
        "analysis_self_evaluation.json",
        "cobol_structure.json",
        "commented_out_code.json",
        "copybook_manifest.json",
        "parse_diagnostics.json",
        "pipeline_report.json",
        "variable_values.json",
    ]
    artifact_count = 0
    for name in artifact_names:
        source = report_dir / name
        if source.is_file():
            shutil.copy2(source, bundle_artifacts / name)
            artifact_count += 1
    copybooks_dir = report_dir / "copybooks"
    if copybooks_dir.is_dir():
        shutil.copytree(copybooks_dir, bundle_artifacts / "copybooks")
        artifact_count += len([path for path in copybooks_dir.iterdir() if path.is_file()])

    manifest = {
        "program": program,
        "schema_version": CHUNK_SCHEMA_VERSION,
        "pipeline_version": PIPELINE_VERSION,
        "recommended_index_path": "chunks",
        "chunks_path": "chunks",
        "knowledge_base_path": "knowledge_base",
        "artifacts_path": "artifacts",
        "chunk_count": chunk_count,
        "knowledge_base_file_count": kb_count,
        "artifact_count": artifact_count,
        "notes": [
            "Index files under chunks/ for normal RAG retrieval.",
            "Use artifacts/ for diagnostics, confidence, copybook status, and static value provenance.",
            "Inactive COBOL comments are separated in artifacts/commented_out_code.json when detected.",
        ],
    }
    _atomic_write_json(bundle_dir / "manifest.json", manifest)
    (bundle_dir / "README.md").write_text(
        "\n".join([
            f"# RAG Bundle: {program}",
            "",
            "This folder contains the curated artifacts needed by the downstream COBOL RAG pipeline.",
            "",
            "- `chunks/`: index this directory for retrieval.",
            "- `knowledge_base/`: deterministic human-readable summaries.",
            "- `artifacts/`: diagnostics and supporting JSON for confidence/provenance checks.",
            "- `manifest.json`: machine-readable bundle inventory.",
            "",
            "Do not index the whole report directory for normal answers; use `chunks/` first.",
            "",
        ]),
        encoding="utf-8",
    )
    if verbose:
        print(f"  knowledge-base_rag: chunks={chunk_count}, kb={kb_count}, artifacts={artifact_count}")
    return 1


# =============================================================================
# Helpers
# =============================================================================

def _parse_int(val: str) -> int:
    """Parse integer from string, tolerating commas and extra text."""
    m = re.search(r"[\d,]+", val)
    if m:
        return int(m.group(0).replace(",", ""))
    return 0


def _refresh_hash(data: dict) -> None:
    """Recompute content_hash from current data['text'] in-place."""
    text = data.get("text", "")
    if "metadata" in data:
        data["metadata"]["content_hash"] = hashlib.sha256(
            text.encode("utf-8")
        ).hexdigest()[:16]


# =============================================================================
# Phase 2 post-processing enrichments (R2.4, R3.2, R3.3) + R7.4 health chunk
# =============================================================================

def enrich_called_by(chunks_dir: Path, program: str, verbose: bool) -> int:
    """R2.4 — Add called_by to paragraph_logic chunks.

    Builds a reverse call index from all paragraph chunks' `calls` lists,
    then writes the `called_by` field onto each target paragraph's chunk.
    Returns the number of chunks that received a non-empty called_by list.
    """
    # First pass: collect {para_name: [callers]} from all paragraph chunks
    reverse: dict[str, list[str]] = {}
    para_files = list(chunks_dir.glob(f"{program}__paragraph__*.json"))

    for f in para_files:
        data = load_json(f)
        if not data:
            continue
        meta = data.get("metadata", {})
        caller = meta.get("paragraph", "")
        for callee_raw in meta.get("calls", []):
            # calls may be bare names or "prog:paragraph_logic:name" at this point
            callee = callee_raw.split(":")[-1] if ":" in callee_raw else callee_raw
            # Strip THRU targets
            callee = re.split(r"\s+(?:THRU|THROUGH)\s+", callee, maxsplit=1,
                              flags=re.IGNORECASE)[0].strip().upper()
            if callee:
                reverse.setdefault(callee, [])
                if caller and caller not in reverse[callee]:
                    reverse[callee].append(caller)

    # Second pass: write called_by to each paragraph chunk
    updated = 0
    for f in para_files:
        data = load_json(f)
        if not data:
            continue
        meta = data.get("metadata", {})
        para_name = meta.get("paragraph", "").upper()
        callers = reverse.get(para_name, [])
        if meta.get("called_by") != callers:
            meta["called_by"] = callers
            data["metadata"] = meta
            f.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            if callers:
                updated += 1

    if verbose:
        print(f"  enrich_called_by: {updated} paragraphs have non-empty called_by")
    return updated


def enrich_calls_chunk_ids(chunks_dir: Path, program: str, verbose: bool) -> int:
    """R3.2 — Convert paragraph `calls` from bare names to chunk_ids.

    Keeps original bare names in `calls_names` for backward compatibility.
    Searches the manifest for matching chunk_ids (handles merged +N suffixes).
    """
    # Build lookup: para_name_upper → chunk_id from manifest
    manifest_path = chunks_dir / "chunks_manifest.json"
    if not manifest_path.exists():
        return 0
    manifest = load_json(manifest_path) or {}
    # Also build from live files (pre-manifest case)
    name_to_id: dict[str, str] = {}
    for f in chunks_dir.glob(f"{program}__paragraph__*.json"):
        data = load_json(f)
        if not data:
            continue
        meta = data.get("metadata", {})
        para = meta.get("paragraph", "").upper()
        cid = meta.get("chunk_id", "")
        if para and cid:
            name_to_id[para] = cid

    updated = 0
    for f in chunks_dir.glob(f"{program}__paragraph__*.json"):
        data = load_json(f)
        if not data:
            continue
        meta = data.get("metadata", {})
        raw_calls = meta.get("calls", [])
        if not raw_calls:
            continue

        # Skip if already chunk_ids (contains ":")
        if all(":" in c for c in raw_calls):
            continue

        meta["calls_names"] = list(raw_calls)  # backward compat
        resolved = []
        for callee_raw in raw_calls:
            callee_bare = re.split(r"\s+(?:THRU|THROUGH)\s+", callee_raw, maxsplit=1,
                                   flags=re.IGNORECASE)[0].strip().upper()
            cid = name_to_id.get(callee_bare)
            resolved.append(cid if cid else callee_raw)
        meta["calls"] = resolved
        data["metadata"] = meta
        f.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        updated += 1

    if verbose:
        print(f"  enrich_calls_chunk_ids: {updated} paragraph chunks updated")
    return updated


def enrich_program_summary_links(chunks_dir: Path, program: str, verbose: bool) -> bool:
    """R3.3 — Add paragraph_chunks and variable_group_chunks lists to program_summary.

    Must be called after all paragraph and variable_group chunks exist.
    """
    summary_path = chunks_dir / f"{program}__program_summary.json"
    if not summary_path.exists():
        return False

    para_ids = []
    for f in sorted(chunks_dir.glob(f"{program}__paragraph__*.json")):
        data = load_json(f)
        if not data:
            continue
        cid = data.get("metadata", {}).get("chunk_id")
        if cid:
            para_ids.append(cid)

    vg_ids = []
    for f in sorted(chunks_dir.glob(f"{program}__variable_group__*.json")):
        data = load_json(f)
        if not data:
            continue
        cid = data.get("metadata", {}).get("chunk_id")
        if cid:
            vg_ids.append(cid)

    summary = load_json(summary_path)
    if not summary:
        return False

    summary["metadata"]["paragraph_chunks"] = para_ids
    summary["metadata"]["variable_group_chunks"] = vg_ids
    summary_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    if verbose:
        print(f"  enrich_program_summary_links: "
              f"{len(para_ids)} paragraph_chunks, {len(vg_ids)} variable_group_chunks")
    return True


def enrich_variable_group_usage(chunks_dir: Path, report_dir: Path,
                                program: str, verbose: bool) -> int:
    """R2.1 — Append usage context to variable_group chunks.

    For each variable_group, finds paragraphs that modify or read its fields
    (from the variables_modified/variables_read set in paragraph chunks) and
    appends a summary line: "Used in: PARA1 (modified), PARA2 (read)."

    Must be called after enrich_paragraph_chunks (which writes the variable fields).
    """
    # Build {field_name: [(para_name, role)]} from paragraph chunks
    field_usage: dict[str, list[tuple[str, str]]] = {}
    for para_file in chunks_dir.glob(f"{program}__paragraph__*.json"):
        data = load_json(para_file)
        if not data:
            continue
        meta = data.get("metadata", {})
        para_name = meta.get("paragraph", "")
        if not para_name:
            continue
        for v in meta.get("variables_modified", []):
            field_usage.setdefault(v.upper(), []).append((para_name, "modified"))
        for v in meta.get("variables_read", []):
            field_usage.setdefault(v.upper(), []).append((para_name, "read"))

    if not field_usage:
        return 0

    enriched = 0
    for vg_file in chunks_dir.glob(f"{program}__variable_group__*.json"):
        data = load_json(vg_file)
        if not data:
            continue
        meta = data.get("metadata", {})
        field_names = [f.upper() for f in meta.get("field_names", [])]

        usages: dict[str, list[str]] = {}
        for fn in field_names:
            entries = field_usage.get(fn, [])
            for para, role in entries:
                usages.setdefault(para, []).append(f"{fn} {role}")

        if not usages:
            continue

        # Build compact usage text
        usage_parts = []
        for para, roles in sorted(usages.items()):
            usage_parts.append(f"{para} ({', '.join(roles)})")
        usage_line = "Used in paragraphs: " + "; ".join(usage_parts[:10])
        if len(usage_parts) > 10:
            usage_line += f" ... and {len(usage_parts) - 10} more"

        if token_count(data["text"]) + token_count(usage_line) <= MAX_CHUNK_TOKENS:
            data["text"] += "\n" + usage_line
            data["metadata"]["used_in_paragraphs"] = sorted(usages.keys())[:20]
            _refresh_hash(data)
            vg_file.write_text(
                json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            enriched += 1

    if verbose:
        print(f"  enrich_variable_group_usage: {enriched} variable groups enriched")
    return enriched


def enrich_related_variable_groups(chunks_dir: Path, program: str, verbose: bool) -> int:
    """R3.1 — Add related_variable_groups to paragraph_logic chunks.

    For each paragraph that has variables_modified/variables_read set (from R2.5),
    finds which variable_group chunks contain those variables (via field_names metadata)
    and adds related_variable_groups: [chunk_id, ...].

    Must be called after enrich_paragraph_chunks (which writes variables_modified/read).
    """
    # Build {variable_name: variable_group_chunk_id} from all variable_group chunks
    var_to_group: dict[str, str] = {}
    for vg_file in chunks_dir.glob(f"{program}__variable_group__*.json"):
        vg = load_json(vg_file)
        if not vg:
            continue
        cid = vg.get("metadata", {}).get("chunk_id", "")
        for fname in vg.get("metadata", {}).get("field_names", []):
            if fname and fname != "FILLER":
                var_to_group[fname.upper()] = cid

    if not var_to_group:
        return 0

    enriched = 0
    for para_file in chunks_dir.glob(f"{program}__paragraph__*.json"):
        data = load_json(para_file)
        if not data:
            continue
        meta = data.get("metadata", {})
        vars_modified = meta.get("variables_modified", [])
        vars_read = meta.get("variables_read", [])
        all_vars = list(dict.fromkeys(vars_modified + vars_read))

        related = list(dict.fromkeys(
            var_to_group[v.upper()]
            for v in all_vars
            if v.upper() in var_to_group
        ))
        if not related:
            continue

        data["metadata"]["related_variable_groups"] = related
        # Recompute hash (metadata-only change; text unchanged, hash stays valid)
        para_file.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        enriched += 1

    if verbose:
        print(f"  enrich_related_variable_groups: {enriched} paragraphs linked")
    return enriched


def generate_cobol_analysis_health(report_dir: Path, chunks_dir: Path,
                                   program: str, verbose: bool) -> int:
    """R7.4 — Generate one cobol_analysis_health chunk per COBOL program.

    Aggregates parse coverage, stubbed copybooks, and quality flags into a
    single self-describing chunk so consumers can assess analysis reliability
    without reading multiple artifact files.
    """
    diag = _get_parse_diagnostics(report_dir)
    coverage_pct = _compute_parse_coverage(diag) or 100.0
    error_count = diag.get("error_summary", {}).get("total_errors", 0) if diag else 0

    struct = _load_cobol_structure(report_dir)
    copy_stmts = struct.get("copy_statements", [])
    sys_cpbs = struct.get("known_system_copybooks", {})

    # Copybook data
    cpb_manifest_path = report_dir / "copybook_manifest.json"
    stubbed_copybooks: list[str] = []
    total_copybooks = 0
    resolved_copybooks = 0
    if cpb_manifest_path.exists():
        cpb = load_json(cpb_manifest_path) or {}
        summary_cpb = cpb.get("summary", {})
        total_copybooks = summary_cpb.get("total_copybooks", 0)
        resolved_copybooks = summary_cpb.get("resolved", 0)
        for name, info in (cpb.get("copybooks") or {}).items():
            if info.get("is_stub"):
                impact = "Unknown impact"
                if name in sys_cpbs:
                    impact = sys_cpbs[name].get("stub_impact", impact)
                else:
                    for cs in copy_stmts:
                        if cs["copybook"] == name:
                            impact = cs.get("impact", impact)
                            break
                sys_id = sys_cpbs.get(name, {}).get("system")
                sys_part = f" [{sys_id}]" if sys_id else ""
                stubbed_copybooks.append(f"{name}{sys_part}: {impact}")

    stubbed_count = len(stubbed_copybooks)

    # Quality flags
    quality_flags: list[str] = []
    if diag:
        quality_flags.append(
            f"analyzed with --lenient: {coverage_pct}% coverage "
            f"({error_count} parse error(s) skipped)"
        )
    if stubbed_count > 0:
        quality_flags.append(f"{stubbed_count} copybook(s) stubbed")

    # Overall confidence label
    if coverage_pct >= 99 and stubbed_count == 0:
        confidence_label = "high"
    elif coverage_pct >= 90 or stubbed_count <= 3:
        confidence_label = "medium"
    else:
        confidence_label = "low"

    # Human-readable text
    stub_note = (f" {stubbed_count} copybook(s) were stubbed."
                 if stubbed_count else "")
    parse_note = (f" Parse coverage: {coverage_pct}% ({error_count} error(s))."
                  if diag else " Parse completed without errors.")
    text = (
        f"Analysis health for {program}:{parse_note}{stub_note} "
        f"Overall confidence: {confidence_label}."
    )

    metadata = {
        "chunk_type": "cobol_analysis_health",
        "chunk_id": f"{program}:analysis_health",
        "program": program,
        "parse_coverage_pct": coverage_pct,
        "parse_error_count": error_count,
        "stubbed_copybooks": stubbed_copybooks,
        "stubbed_copybook_count": stubbed_count,
        "total_copybooks": total_copybooks,
        "resolved_copybooks": resolved_copybooks,
        "quality_flags": quality_flags,
        "confidence": confidence_label,
    }

    health = _get_analysis_health(report_dir)
    if health:
        metadata["base_analysis_succeeded"] = health.get("base_analysis_succeeded")
        metadata["completed_tasks"] = health.get("completed_tasks", [])
        metadata["failed_tasks"] = health.get("failed_tasks", [])
        metadata["mode"] = health.get("mode")

    self_eval = _get_analysis_self_evaluation(report_dir)
    if self_eval:
        coverage = self_eval.get("coverage") or self_eval.get("semantic_coverage", {}) or {}
        metadata["confidence_score"] = self_eval.get("confidence_score")
        metadata["confidence_label"] = self_eval.get("confidence_label")
        metadata["coverage"] = coverage
        if "typed_node_ratio" in coverage:
            metadata["typed_node_ratio"] = coverage.get("typed_node_ratio")
        score = metadata.get("confidence_score")
        label = metadata.get("confidence_label")
        if score is not None and label:
            text += f" Self-evaluation confidence score: {score}/100 ({label})."

    write_chunk(chunks_dir, f"{program}__analysis_health.json", text, metadata)
    if verbose:
        print(f"  cobol_analysis_health: confidence={confidence_label}, "
              f"coverage={coverage_pct}%, stubs={stubbed_count}")
    return 1


# =============================================================================
# Group G — section_summary chunks
# =============================================================================

def generate_business_rules(report_dir: Path, chunks_dir: Path,
                            program: str, verbose: bool) -> int:
    """Generate a business_rules chunk aggregating all level-88 conditions.

    Requires Enhancement 0 (Java acceptScopedVisitor fix) to have been applied
    and programs re-analyzed, otherwise the data structures JSON will have no
    level-88 nodes and this generator returns 0.
    """
    ds_dir = report_dir / "data_structures"
    if not ds_dir.is_dir():
        return 0
    ds_files = list(ds_dir.glob("*-data.json"))
    if not ds_files:
        return 0
    data = load_json(ds_files[0])
    if not data:
        return 0

    conditions: list[dict] = []

    def _walk(node: dict, parent_name: str = "") -> None:
        name = node.get("name", "")
        level = node.get("levelNumber", 0)
        if level == 88:
            raw = node.get("rawText", "").strip()
            val_m = re.search(r"\bVALUES?\s+(.+?)(?:\s*\.|$)", raw, re.IGNORECASE)
            val_str = val_m.group(1).strip() if val_m else raw
            conditions.append({"condition": name, "parent": parent_name, "values": val_str})
        else:
            if name and name != "FILLER":
                parent_name = name
            for child in node.get("children", []):
                _walk(child, parent_name)

    for record in data.get("children", []):
        _walk(record)

    if not conditions:
        if verbose:
            print("  business_rules: no 88-level conditions — skipping")
        return 0

    lines = [f"Business rules and boolean conditions for {program}:"]
    for c in conditions:
        lines.append(f"- {c['condition']}: {c['parent']} = {c['values']}")

    chunk_text = "\n".join(lines)
    if token_count(chunk_text) > MAX_CHUNK_TOKENS:
        kept = lines[:1]
        for line in lines[1:]:
            kept.append(line)
            if token_count("\n".join(kept)) > MAX_CHUNK_TOKENS - 30:
                kept.append(f"... and {len(conditions) - len(kept) + 1} more conditions.")
                break
        chunk_text = "\n".join(kept)

    metadata = {
        "chunk_type": "business_rules",
        "chunk_id": f"{program}:business_rules:main",
        "parent_program_chunk": f"{program}:program_summary",
        "program": program,
        "condition_count": len(conditions),
        "conditions": [{"name": c["condition"], "parent": c["parent"]} for c in conditions],
    }
    write_chunk(chunks_dir, f"{program}__business_rules.json", chunk_text, metadata)
    if verbose:
        print(f"  business_rules: {len(conditions)} conditions")
    return 1


_SQL_KEYWORD_EXCLUSIONS = frozenset({
    'SELECT', 'VALUES', 'SET', 'WHERE', 'TABLE', 'NULL', 'NOT', 'AND', 'OR',
    'ON', 'AS', 'BY', 'ALL', 'IN', 'IS', 'AT', 'END', 'EXEC', 'SQL',
})


def generate_cics_operations(report_dir: Path, chunks_dir: Path,
                             program: str, verbose: bool) -> int:
    """Generate one cics_operations chunk from dependency CICS metadata."""
    deps_path = report_dir / "knowledge_base" / "03_Dependencies.yaml"
    if not deps_path.exists():
        return 0
    deps = load_yaml(deps_path)
    if not deps:
        return 0

    cics = deps.get("cics", []) or []
    raw_calls = deps.get("cics_calls", []) or []
    cics_calls = [
        {"command": c.get("command"), "target": str(c.get("target", "")).strip().strip("'\"").upper()}
        for c in raw_calls
        if _is_valid_program_target(c.get("target", ""))
    ]
    cics_ops = deps.get("cics_operations", []) or []
    if not cics and not cics_calls and not cics_ops:
        return 0

    commands = sorted({str(cmd).upper() for cmd in cics if cmd})
    targets = sorted({c["target"] for c in cics_calls if c.get("target")})
    lines = [f"CICS operations for program {program}:"]
    if cics_ops:
        lines.append("CICS structured operations:")
        for op in cics_ops:
            line = f"- {op.get('command', '?')} ({op.get('type', 'other')})"
            if op.get('target'):
                line += f" -> {op['target']} [{op.get('target_kind', 'UNKNOWN')}]"
            lines.append(line + ".")
    elif commands:
        lines.append(f"CICS commands used: {', '.join(commands)}.")
    if cics_calls:
        lines.append("CICS program transfers:")
        for call in cics_calls:
            cmd = (call.get("command") or "LINK/XCTL").upper()
            lines.append(f"- {cmd} to program {call['target']}")

    metadata = {
        "chunk_type": "cics_operations",
        "chunk_id": f"{program}:cics_operations",
        "parent_program_chunk": f"{program}:program_summary",
        "program": program,
        "cics_commands": commands,
        "cics_command_count": len(set(commands)),
        "cics_calls": cics_calls,
        "cics_call_targets": targets,
        "cics_operations": cics_ops,
    }
    write_chunk(
        chunks_dir,
        f"{program}__cics_operations.json",
        "\n".join(lines),
        metadata,
    )
    if verbose:
        print(f"  cics_operations: commands={len(commands)}, targets={len(targets)}")
    return 1


def _extract_sql_tables(sql_text: str) -> list[str]:
    """Extract table names from a SQL statement text."""
    tables: set[str] = set()
    sql_upper = sql_text.upper()
    for pattern in [
        r'\bFROM\s+(\w+)',
        r'\bINTO\s+(\w+)',
        r'\bUPDATE\s+(\w+)',
        r'\bJOIN\s+(\w+)',
        r'\bDELETE\s+FROM\s+(\w+)',
    ]:
        for m in re.finditer(pattern, sql_upper):
            name = m.group(1)
            if name not in _SQL_KEYWORD_EXCLUSIONS and len(name) >= 2:
                tables.add(name)
    return sorted(tables)


def generate_sql_operations(report_dir: Path, chunks_dir: Path,
                            program: str, verbose: bool) -> int:
    """Generate sql_operation chunks — one per SQL statement per paragraph.

    Only programs with actual EXEC SQL blocks produce chunks (7/365 in corpus).
    Requires _build_paragraph_subgraphs() to have been called and the subgraphs
    cached; reads subgraphs fresh here to keep the function self-contained.
    """
    subgraphs = _build_paragraph_subgraphs(report_dir)
    if not subgraphs:
        return 0

    count = 0
    for para_name, sg in subgraphs.items():
        sql_nodes = sg.get("sql_nodes", [])
        for i, sql_node in enumerate(sql_nodes):
            operation = sql_node["operation"]
            orig_text = sql_node["text"]
            tables = _extract_sql_tables(orig_text)

            # Truncate very long SQL text to keep chunk under token limit
            display_text = orig_text.strip()[:400]

            chunk_text = (
                f"SQL {operation} in paragraph {para_name} of {program}:\n"
                f"Tables: {', '.join(tables) if tables else 'unknown'}\n"
                f"Statement: {display_text}"
            )

            safe_id = re.sub(r"[^\w\-]", "_", f"{para_name}_{operation}_{i}")
            metadata = {
                "chunk_type": "sql_operation",
                "chunk_id": f"{program}:sql_operation:{para_name}:{operation}:{i}",
                "parent_program_chunk": f"{program}:program_summary",
                "program": program,
                "paragraph": para_name,
                "operation": operation,
                "tables": tables,
            }
            write_chunk(chunks_dir, f"{program}__sql_op__{safe_id}.json",
                        chunk_text, metadata)
            count += 1

    if verbose:
        if count:
            print(f"  sql_operation: {count} chunks")
        else:
            print("  sql_operation: no SQL statements — skipping")
    return count


def generate_section_summaries(
    report_dir: Path,
    chunks_dir: Path,
    program: str,
    verbose: bool = False,
) -> int:
    """Generate one ``section_summary`` chunk per COBOL SECTION.

    A section_summary provides a mid-level retrieval unit between the
    fine-grained ``paragraph_logic`` chunks and the coarse ``program_summary``
    chunk.  Each chunk aggregates:

    - The section name and its paragraph list
    - English comment translations for each paragraph (from
      ``comments_enriched.json`` if available)
    - Internal PERFORM calls (between paragraphs in the same section) and
      external PERFORM calls (to paragraphs outside the section)

    **Empty sections** (sections with no paragraphs) are silently skipped —
    they produce no chunk.

    **Programs with no sections** (flat paragraph structure) return 0 without
    error.

    Args:
        report_dir: Report directory containing the CFG and comments files.
        chunks_dir: Output directory for generated chunk JSON files.
        program: Program name used as chunk ID prefix.
        verbose: If True, print progress.

    Returns:
        Number of section_summary chunks written.
    """
    section_map = _build_paragraph_section_map(report_dir)
    if not section_map:
        if verbose:
            print("  section_summary: no sections found — skipping")
        return 0

    enriched = _load_enriched_comments(report_dir)

    # Group paragraphs by section
    section_paragraphs: dict[str, list[str]] = {}
    for para_name, section_name in section_map.items():
        if section_name:
            section_paragraphs.setdefault(section_name, []).append(para_name)

    if not section_paragraphs:
        if verbose:
            print("  section_summary: no paragraphs assigned to any section — skipping")
        return 0

    # Load paragraph chunks to extract call relationships.
    # Use the ``calls`` field (set by generate_paragraph_logic with raw names).
    # Note: ``calls_names`` is added later by enrich_calls_chunk_ids (Phase 2),
    # so it is NOT available yet when this generator runs.
    para_calls: dict[str, list[str]] = {}
    for chunk_file in chunks_dir.glob(f"{program}__paragraph__*.json"):
        chunk_data = load_json(chunk_file)
        if not chunk_data:
            continue
        meta = chunk_data.get("metadata", {})
        pname = meta.get("paragraph", "")
        # ``calls`` may be raw names or chunk_ids depending on run order;
        # normalize to bare names via _normalize_call_target regardless
        raw_calls = meta.get("calls", [])
        if pname:
            para_calls[pname] = raw_calls

    count = 0
    for section_name, paragraphs in sorted(section_paragraphs.items()):
        # Build the chunk text
        parts: list[str] = [
            f"Section: {section_name}",
            f"Contains {len(paragraphs)} paragraph(s): {', '.join(paragraphs)}",
        ]

        # Append per-paragraph comment translations
        for para in paragraphs:
            entry = enriched.get(para, {})
            english = entry.get("english", "").strip()
            if english and not entry.get("translation_failed"):
                parts.append(f"- {para}: {english}")

        # Classify PERFORM calls as internal (within section) or external
        section_set = set(paragraphs)
        internal_calls: list[str] = []
        external_calls: list[str] = []
        for para in paragraphs:
            for raw_call in para_calls.get(para, []):
                target = _normalize_call_target(raw_call).upper()
                if target in section_set:
                    internal_calls.append(f"{para} → {target}")
                else:
                    external_calls.append(f"{para} → {target}")

        if internal_calls:
            # Deduplicate while preserving order
            seen: set[str] = set()
            unique = [c for c in internal_calls if not (c in seen or seen.add(c))]  # type: ignore[func-returns-value]
            parts.append("Internal calls: " + "; ".join(unique))
        if external_calls:
            seen = set()
            unique = [c for c in external_calls if not (c in seen or seen.add(c))]  # type: ignore[func-returns-value]
            parts.append("External calls: " + "; ".join(unique))

        chunk_text = "\n".join(parts)

        # Sanitize section name for use in chunk ID and filename
        safe_name = re.sub(r"[^\w\-]", "_", section_name)

        metadata: dict = {
            "chunk_type": "section_summary",
            "chunk_id": f"{program}:section_summary:{safe_name}",
            "parent_program_chunk": f"{program}:program_summary",
            "program": program,
            "section": section_name,
            "paragraph_count": len(paragraphs),
            "paragraphs": paragraphs,
        }
        write_chunk(chunks_dir, f"{program}__section__{safe_name}.json",
                    chunk_text, metadata)
        count += 1

    if verbose:
        print(f"  section_summary: {count} chunk(s)")
    return count


# =============================================================================
# Group H — workflow chunks
# =============================================================================

def generate_workflow_chunks(
    report_dir: Path,
    chunks_dir: Path,
    program: str,
    verbose: bool = False,
) -> int:
    """Generate ``workflow`` chunks for paragraphs that orchestrate others.

    A workflow chunk describes a paragraph that PERFORMs two or more other
    paragraphs — i.e. an orchestrating paragraph.  It shows the entry
    paragraph's purpose and the sequence of steps it delegates to, giving
    RAG a mid-level "business process" view that sits between the fine-grained
    per-paragraph chunks and the coarse program_summary.

    **Thresholds** (documented here because they will be questioned):

    - **2+ callees**: guarantees the entry paragraph is actually orchestrating
      something, not just performing a single subroutine.
    - **3+ local nodes** (CFG node count for the paragraph): filters out pure
      dispatchers like ``MAINLINE`` that consist entirely of PERFORM statements
      with no local logic — these add no retrieval value beyond the individual
      callee chunks.

    **Paragraph name sanitization**: COBOL names can contain hyphens but not
    colons or spaces; we still sanitize with ``re.sub`` for safety.

    Args:
        report_dir: Report directory (used to check if enriched comments exist).
        chunks_dir: Directory containing already-generated paragraph_logic chunks.
        program: Program name used as chunk ID prefix.
        verbose: If True, print progress.

    Returns:
        Number of workflow chunks written.
    """
    enriched = _load_enriched_comments(report_dir)

    # Load all paragraph chunks — we need calls_names, node_count, english comment
    paragraph_chunks: list[dict] = []
    for chunk_file in sorted(chunks_dir.glob(f"{program}__paragraph__*.json")):
        data = load_json(chunk_file)
        if data:
            paragraph_chunks.append(data)

    if not paragraph_chunks:
        if verbose:
            print("  workflow: no paragraph chunks found — skipping")
        return 0

    count = 0
    for chunk in paragraph_chunks:
        meta = chunk.get("metadata", {})
        entry_para = meta.get("paragraph", "")
        if not entry_para:
            continue

        # ``calls`` contains raw PERFORM target strings at generation time
        # (e.g. "FOO THRU FOO-EXIT").  Phase 2 enrichment later converts them
        # to chunk_ids in-place and saves the originals as ``calls_names``, but
        # that happens AFTER this generator runs.  We normalize to bare names
        # here so both raw strings and chunk_ids work correctly.
        raw_calls_field: list[str] = meta.get("calls", [])
        callee_names = list(dict.fromkeys(
            _normalize_call_target(c) for c in raw_calls_field
        ))

        # Threshold 1: must call 2+ distinct paragraphs
        if len(callee_names) < 2:
            continue

        # Threshold 2: must have 3+ CFG nodes (filters pure dispatchers)
        node_count = meta.get("node_count", 0)
        if node_count < 3:
            continue

        # Build workflow chunk text
        entry_entry = enriched.get(entry_para, {})
        entry_english = entry_entry.get("english", "").strip()
        if entry_entry.get("translation_failed"):
            entry_english = ""

        parts: list[str] = []
        if entry_english:
            parts.append(entry_english)
        parts.append(f"{entry_para} orchestrates:")

        # Describe each callee
        for callee in callee_names:
            callee_entry = enriched.get(callee, {})
            callee_english = callee_entry.get("english", "").strip()
            if callee_entry.get("translation_failed"):
                callee_english = ""
            cics_suffix = _workflow_callee_cics_suffix(chunks_dir, program, callee)
            if callee_english:
                parts.append(f"  - {callee}{cics_suffix}: {callee_english}")
            else:
                parts.append(f"  - {callee}{cics_suffix}")

        chunk_text = "\n".join(parts)

        # Sanitize paragraph name for chunk ID / filename (no colons or spaces)
        safe_para = re.sub(r"[^\w\-]", "_", entry_para)

        metadata: dict = {
            "chunk_type": "workflow",
            "chunk_id": f"{program}:workflow:{safe_para}",
            "parent_program_chunk": f"{program}:program_summary",
            "program": program,
            "entry_paragraph": entry_para,
            "called_paragraphs": callee_names,
            "callee_count": len(callee_names),
        }
        write_chunk(chunks_dir, f"{program}__workflow__{safe_para}.json",
                    chunk_text, metadata)
        count += 1

    if verbose:
        print(f"  workflow: {count} chunk(s)")
    return count


def _workflow_callee_cics_suffix(chunks_dir: Path, program: str, callee: str) -> str:
    safe_callee = re.sub(r"[^\w\-]", "_", callee)
    chunk_path = chunks_dir / f"{program}__paragraph__{safe_callee}.json"
    if not chunk_path.exists():
        return ""
    data = load_json(chunk_path)
    if not isinstance(data, dict):
        return ""
    commands = data.get("metadata", {}).get("cics_commands", []) or []
    rendered = []
    seen = set()
    for command in commands:
        command_text = str(command).strip()
        if not command_text:
            continue
        key = command_text.upper()
        if key in seen:
            continue
        seen.add(key)
        rendered.append(command_text.title())
        if len(rendered) >= 3:
            break
    if not rendered:
        return ""
    return f" (CICS: {', '.join(rendered)})"


# =============================================================================
# Main orchestrator
# =============================================================================

def run_pipeline(report_dir: Path, verbose: bool = False) -> dict:
    """Run the full chunk pipeline on a report directory.

    Returns a summary dict with chunk counts by type.
    """
    is_cobol, is_jcl = detect_mode(report_dir)

    if not is_cobol and not is_jcl:
        print(f"Error: {report_dir} is neither a COBOL nor JCL report directory.")
        print("  Expected: cfg/ directory (COBOL) or jcl_summary.json (JCL)")
        return {}

    # Derive program name from directory name
    dir_name = report_dir.name  # e.g. "TEST.CBL.report" or "TEST.jcl.report"
    program = dir_name.replace(".report", "")

    chunks_dir = report_dir / "chunks"
    chunks_dir.mkdir(exist_ok=True)
    removed_stale_chunks = clear_existing_chunks(chunks_dir)

    mode = []
    if is_cobol:
        mode.append("COBOL")
    if is_jcl:
        mode.append("JCL")
    print(f"Mode: {' + '.join(mode)} | Schema: v{CHUNK_SCHEMA_VERSION}")
    print(f"Output: {chunks_dir}")
    if verbose and removed_stale_chunks:
        print(f"Cleared {removed_stale_chunks} stale chunk JSON file(s)")

    # Set parse quality for this program (R7.1 — stamped into every chunk)
    global _CURRENT_PARSE_QUALITY, _CURRENT_SOURCE_MTIME
    _diag = _get_parse_diagnostics(report_dir)
    _CURRENT_PARSE_QUALITY = _compute_parse_quality(_diag, _get_analysis_health(report_dir))
    _CURRENT_SOURCE_MTIME = _get_source_mtime(report_dir)

    summary = {}

    # --- COBOL chunks ---
    if is_cobol:
        if verbose:
            print("\n[COBOL chunks]")
        summary["program_summary"] = generate_program_summary(
            report_dir, chunks_dir, program, verbose)
        summary["dependencies"] = generate_dependencies(
            report_dir, chunks_dir, program, verbose)
        summary["copybook_mentions"] = generate_copybook_mentions(
            report_dir, chunks_dir, program, verbose)
        summary["copybook_fields"] = generate_copybook_fields(
            report_dir, chunks_dir, program, verbose)
        summary["comments"] = generate_comments(
            report_dir, chunks_dir, program, verbose)
        summary["commented_out_code"] = generate_commented_out_code(
            report_dir, chunks_dir, program, verbose)
        summary["external_program_calls"] = generate_external_program_calls(
            report_dir, chunks_dir, program, verbose)
        summary["datasets_tables_resources"] = generate_datasets_tables_resources(
            report_dir, chunks_dir, program, verbose)
        summary["cics_operations"] = generate_cics_operations(
            report_dir, chunks_dir, program, verbose)
        summary["static_values"] = generate_static_values(
            report_dir, chunks_dir, program, verbose)
        summary["paragraph_logic"] = generate_paragraph_logic(
            report_dir, chunks_dir, program, verbose)
        summary["variable_group"] = generate_variable_groups(
            report_dir, chunks_dir, program, verbose)
        summary["business_rules"] = generate_business_rules(
            report_dir, chunks_dir, program, verbose)
        summary["sql_operation"] = generate_sql_operations(
            report_dir, chunks_dir, program, verbose)
        summary["cobol_analysis_health"] = generate_cobol_analysis_health(
            report_dir, chunks_dir, program, verbose)

        # Enrich paragraph chunks with CFG metadata
        enriched = enrich_paragraph_chunks(
            chunks_dir, report_dir, program, verbose)
        summary["cfg_enriched"] = enriched

        # Apply size guard to paragraph chunks
        guard_stats = apply_size_guard(chunks_dir, program, verbose)
        if verbose and (guard_stats["merged"] or guard_stats["split"]):
            print(f"  Size guard: {guard_stats['merged']} merges, "
                  f"{guard_stats['split']} splits")

        # Section-level and workflow chunks (new in schema v1.2).
        # section_summary groups paragraphs by COBOL SECTION for mid-level retrieval.
        # workflow groups orchestrating paragraphs with their callee summaries.
        # Both run AFTER paragraph enrichment so they can read calls_names metadata.
        summary["section_summary"] = generate_section_summaries(
            report_dir, chunks_dir, program, verbose)
        summary["workflow"] = generate_workflow_chunks(
            report_dir, chunks_dir, program, verbose)

        # Phase 2 post-processing enrichments
        enrich_called_by(chunks_dir, program, verbose)        # R2.4
        enrich_calls_chunk_ids(chunks_dir, program, verbose)  # R3.2
        enrich_program_summary_links(chunks_dir, program, verbose)  # R3.3

        # Phase 3 post-processing enrichments
        enrich_variable_group_usage(chunks_dir, report_dir, program, verbose)  # R2.1
        enrich_related_variable_groups(chunks_dir, program, verbose)           # R3.1

    # --- JCL chunks ---
    if is_jcl:
        if verbose:
            print("\n[JCL chunks]")
        summary["job_flow"] = generate_job_flow(
            report_dir, chunks_dir, verbose)
        summary["step_detail"] = generate_step_details(
            report_dir, chunks_dir, verbose)

    # --- Universal size guard (after all chunk generation, before indexing) ---
    split_stats = apply_universal_size_guard(chunks_dir, {"split": 0}, verbose)
    summary["universal_splits"] = split_stats.get("split", 0)

    # --- BM25 index (after all chunks written, before manifest) ---
    summary["bm25_entries"] = generate_bm25_index(chunks_dir, verbose)

    # --- Manifest ---
    if verbose:
        print()
    manifest = generate_manifest(chunks_dir, verbose)
    summary["total"] = manifest.get("total_chunks", 0)
    summary["rag_bundle"] = generate_rag_bundle(report_dir, chunks_dir, program, verbose)

    return summary


# =============================================================================
# CLI
# =============================================================================

def main():
    # Must declare global before any use of the names inside this function
    global MIN_CHUNK_TOKENS, MAX_CHUNK_TOKENS, OVERLAP_TOKENS

    parser = argparse.ArgumentParser(
        description="Chunk Pipeline — split report artifacts into RAG retrieval units",
    )
    parser.add_argument("report_dir", type=Path,
                        help="Path to a *.report directory")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Print detailed progress")
    parser.add_argument(
        "--max-tokens", type=int, default=None,
        help=f"Maximum tokens per chunk (default: {MAX_CHUNK_TOKENS})",
    )
    parser.add_argument(
        "--min-tokens", type=int, default=None,
        help=f"Minimum tokens for a standalone chunk (default: {MIN_CHUNK_TOKENS})",
    )
    parser.add_argument(
        "--overlap-tokens", type=int, default=None,
        help=f"Token overlap between split chunks (default: {OVERLAP_TOKENS})",
    )
    parser.add_argument(
        "--token-counter", choices=["bpe", "whitespace"], default="bpe",
        help="Token counting strategy: 'bpe' uses tiktoken cl100k_base (default), "
             "'whitespace' uses simple split()",
    )
    args = parser.parse_args()

    if not args.report_dir.is_dir():
        print(f"Error: {args.report_dir} is not a directory")
        sys.exit(1)

    # Apply CLI overrides to module-level chunk-size globals
    if args.max_tokens is not None:
        MAX_CHUNK_TOKENS = args.max_tokens
    if args.min_tokens is not None:
        MIN_CHUNK_TOKENS = args.min_tokens
    if args.overlap_tokens is not None:
        OVERLAP_TOKENS = args.overlap_tokens

    set_token_counter(args.token_counter)

    summary = run_pipeline(args.report_dir, verbose=args.verbose)
    if summary:
        counter_label = "BPE" if _USE_BPE else "whitespace"
        print(f"\nDone. {summary.get('total', 0)} chunks generated "
              f"(max_tokens={MAX_CHUNK_TOKENS}, counter={counter_label}).")
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
