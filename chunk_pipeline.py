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
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

# =============================================================================
# Constants
# =============================================================================

CHUNK_SCHEMA_VERSION = "1.1"
PIPELINE_VERSION = "1.2"

# CFG JSON field names (NOT source/target/label as CLAUDE.md incorrectly states)
EDGE_SOURCE = "fromNodeID"
EDGE_TARGET = "toNodeID"
EDGE_TYPE = "edgeType"

# Chunk size thresholds — overridable via CLI flags (--min-tokens / --max-tokens / --overlap-tokens).
# When tiktoken is active the unit is BPE tokens; otherwise whitespace tokens.
MIN_CHUNK_TOKENS = 20
MAX_CHUNK_TOKENS = 512
OVERLAP_TOKENS = 50

# Parse quality for the current program being chunked.
# Set by run_pipeline() from parse_diagnostics.json before any write_chunk() call.
_CURRENT_PARSE_QUALITY: str = "unknown"


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


def write_chunk(chunks_dir: Path, filename: str, text: str, metadata: dict):
    """Write a single chunk JSON file."""
    metadata["schema_version"] = CHUNK_SCHEMA_VERSION
    metadata["pipeline_version"] = PIPELINE_VERSION
    metadata["analysis_timestamp"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    metadata["content_hash"] = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    metadata["parse_quality"] = _CURRENT_PARSE_QUALITY
    chunk = {"text": text, "metadata": metadata}
    (chunks_dir / filename).write_text(
        json.dumps(chunk, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def load_json(path: Path) -> dict | list | None:
    """Load a JSON file, return None on failure."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def load_yaml(path: Path) -> dict | None:
    """Load a YAML file, return None on failure."""
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return None


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
    except Exception:
        return {}


def _compute_parse_quality(diag: dict) -> str:
    """Map parse diagnostics to a quality label: full / partial / degraded / unknown."""
    if not diag:
        return "unknown"
    errors = diag.get("error_summary", {}).get("total_errors", 0)
    if errors == 0:
        return "full"
    if errors <= 5:
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

    # Append Program Overview from narrative if available
    overview_text = _extract_program_overview(report_dir)
    if overview_text:
        chunk_text += "\n" + overview_text

    # Parse coverage from diagnostics (R7.2)
    diag = _get_parse_diagnostics(report_dir)
    parse_coverage_pct = _compute_parse_coverage(diag)

    metadata = {
        "chunk_type": "program_summary",
        "chunk_id": f"{program}:program_summary",
        "program": program,
        "node_count": node_count,
        "edge_count": edge_count,
        "variable_count": variable_count,
        "complexity_score": complexity_score,
    }
    if parse_coverage_pct is not None:
        metadata["parse_coverage_pct"] = parse_coverage_pct

    write_chunk(chunks_dir, f"{program}__program_summary.json", chunk_text, metadata)
    if verbose:
        print(f"  program_summary: complexity={complexity_score}, "
              f"nodes={node_count}, vars={variable_count}")
    return 1


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
    if not any([tables_read, tables_updated, sql_stmts, calls, cics]):
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
    }
    write_chunk(
        chunks_dir, f"{program}__dependencies.json",
        "\n".join(lines), metadata,
    )
    if verbose:
        print(f"  dependencies: tables_r={len(tables_read)}, "
              f"calls={len(calls)}, cics={len(cics)}")
    return 1


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
    """Return {paragraph_name: enclosing_section_name} from CFG STARTS_WITH edges.

    Traverses upward from each PARAGRAPH node via reverse STARTS_WITH edges
    until a node of type SECTION is found.
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

    # Build reverse STARTS_WITH: child_id → parent_id
    parent_of: dict[str, str] = {}
    for e in edges:
        if e.get(EDGE_TYPE) == "STARTS_WITH":
            parent_of[e[EDGE_TARGET]] = e[EDGE_SOURCE]

    result: dict[str, str] = {}
    for n in nodes:
        if n.get("type") != "PARAGRAPH" or "/" in n.get("name", ""):
            continue
        # Walk up until we hit a SECTION node or exhaust parents
        current_id = n["id"]
        section_name = ""
        visited = set()
        while current_id in parent_of and current_id not in visited:
            visited.add(current_id)
            current_id = parent_of[current_id]
            parent_node = node_by_id.get(current_id, {})
            if parent_node.get("type") == "SECTION":
                section_name = parent_node.get("name", "")
                break
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
    count = 0
    filler_index = 0

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

        # R5.3 — 88-level condition descriptions
        cond_lines = _collect_88_conditions(rec_children)
        if cond_lines:
            cond_block = "Condition names (88-level):"
            if token_count("\n".join(lines)) + token_count(cond_block) + token_count("\n".join(cond_lines)) <= MAX_CHUNK_TOKENS:
                lines.append(cond_block)
                lines.extend(cond_lines)

        # R5.4 — REDEFINES aliasing explanation
        redef_line = _build_redefines_explanation(record, rec_children)
        if redef_line and token_count("\n".join(lines)) + token_count(redef_line) <= MAX_CHUNK_TOKENS:
            lines.append(redef_line)

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
        write_chunk(
            chunks_dir, f"{program}__variable_group__{safe_name}.json",
            chunk_text, metadata,
        )
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

        # Extract SQL and CICS operations from DIALECT nodes in the subgraph
        sql_ops: list[str] = []
        cics_cmds: list[str] = []
        for nid in subgraph:
            orig = node_by_id.get(nid, {}).get("originalText", "").upper()
            if "EXEC SQL" in orig:
                m = re.search(r"EXEC\s+SQL\s+(\w+)", orig)
                if m:
                    sql_ops.append(m.group(1).capitalize())
            if "EXEC CICS" in orig:
                m = re.search(r"EXEC\s+CICS\s+(\w+)", orig)
                if m:
                    cics_cmds.append(m.group(1).capitalize())

        result[pname] = {
            "complexity_local": complexity,
            "node_count": internal_nodes,
            "sql_operations": sorted(set(sql_ops)),
            "cics_commands": sorted(set(cics_cmds)),
        }

    return result


def enrich_paragraph_chunks(chunks_dir: Path, report_dir: Path,
                            program: str, verbose: bool) -> int:
    """Add complexity_local, node_count, variable values, and loop bounds to paragraph chunks."""
    subgraphs = _build_paragraph_subgraphs(report_dir)
    var_values = _load_variable_values(report_dir)
    loop_info_map = _build_perform_loop_info(report_dir)  # R8.1
    all_vars = _load_all_variable_names(report_dir)        # R2.5
    var_usage = _build_variable_usage_from_cfg(report_dir, all_vars)  # R2.5

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

        # R2.5 — variables_modified / variables_read from CFG text heuristic
        usage = var_usage.get(para_name)
        if usage:
            modified_list, read_list = usage
            if modified_list:
                data["metadata"]["variables_modified"] = modified_list
                changed = True
            if read_list:
                data["metadata"]["variables_read"] = read_list
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
) -> dict[str, tuple[list[str], list[str]]]:
    """Scan CFG node originalText within paragraph subgraphs to infer variable usage.

    Returns {paragraph_name: (variables_modified, variables_read)}.
    Uses simple regex heuristics on COBOL statement text.
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

    result: dict[str, tuple[list[str], list[str]]] = {}
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
            result[pname] = (sorted(modified), sorted(read))

    return result


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
            elif access == "write":
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
        if cond:
            cond_str = cond
            if cond_mod:
                cond_str += f" ({cond_mod})"
            lines.append(f"Condition: {cond_str}.")
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

    words = text.split()
    parts = []
    start = 0
    while start < len(words):
        end = min(start + MAX_CHUNK_TOKENS, len(words))
        parts.append(" ".join(words[start:end]))
        start = end - OVERLAP_TOKENS if end < len(words) else end

    if len(parts) <= 1:
        return

    stem = filepath.stem
    filepath.unlink()
    for idx, part_text in enumerate(parts, 1):
        part_meta = {**data["metadata"], "part": idx, "total_parts": len(parts)}
        part_meta["content_hash"] = hashlib.sha256(
            part_text.encode("utf-8")
        ).hexdigest()[:16]
        part_data = {"text": part_text, "metadata": part_meta}
        (chunks_dir / f"{stem}__part{idx}.json").write_text(
            json.dumps(part_data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    stats["split"] += 1
    if verbose:
        print(f"    Split {stem} into {len(parts)} parts ({tc} tokens)")


def generate_manifest(chunks_dir: Path, verbose: bool) -> dict:
    """Write chunks_manifest.json summarizing all generated chunks."""
    entries = []
    for f in sorted(chunks_dir.glob("*.json")):
        if f.name == "chunks_manifest.json":
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
    for e in entries:
        ct = e["chunk_type"]
        type_counts[ct] = type_counts.get(ct, 0) + 1

    manifest = {
        "schema_version": CHUNK_SCHEMA_VERSION,
        "total_chunks": len(entries),
        "type_counts": type_counts,
        "chunks": entries,
    }
    (chunks_dir / "chunks_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    if verbose:
        print(f"  Manifest: {len(entries)} chunks — {type_counts}")
    return manifest


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
                stubbed_copybooks.append(name)

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
    write_chunk(chunks_dir, f"{program}__analysis_health.json", text, metadata)
    if verbose:
        print(f"  cobol_analysis_health: confidence={confidence_label}, "
              f"coverage={coverage_pct}%, stubs={stubbed_count}")
    return 1


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

    mode = []
    if is_cobol:
        mode.append("COBOL")
    if is_jcl:
        mode.append("JCL")
    print(f"Mode: {' + '.join(mode)} | Schema: v{CHUNK_SCHEMA_VERSION}")
    print(f"Output: {chunks_dir}")

    # Set parse quality for this program (R7.1 — stamped into every chunk)
    global _CURRENT_PARSE_QUALITY
    _diag = _get_parse_diagnostics(report_dir)
    _CURRENT_PARSE_QUALITY = _compute_parse_quality(_diag)

    summary = {}

    # --- COBOL chunks ---
    if is_cobol:
        if verbose:
            print("\n[COBOL chunks]")
        summary["program_summary"] = generate_program_summary(
            report_dir, chunks_dir, program, verbose)
        summary["dependencies"] = generate_dependencies(
            report_dir, chunks_dir, program, verbose)
        summary["paragraph_logic"] = generate_paragraph_logic(
            report_dir, chunks_dir, program, verbose)
        summary["variable_group"] = generate_variable_groups(
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

    # --- Manifest ---
    if verbose:
        print()
    manifest = generate_manifest(chunks_dir, verbose)
    summary["total"] = manifest.get("total_chunks", 0)

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
