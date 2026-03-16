#!/usr/bin/env python3
"""
Chunk Pipeline — Splits analysis report artifacts into fine-grained
retrieval units for RAG.

Accepts either a COBOL report directory or a JCL report directory (or both).
Each chunk is a JSON file with {"text": "...", "metadata": {...}}.

Usage:
    python3 chunk_pipeline.py out/report/PDCBVC.CBL.report [--verbose]
    python3 chunk_pipeline.py out/report/MYJOB.jcl.report  [--verbose]
"""

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

# =============================================================================
# Constants
# =============================================================================

CHUNK_SCHEMA_VERSION = "1.0"

# CFG JSON field names (NOT source/target/label as CLAUDE.md incorrectly states)
EDGE_SOURCE = "fromNodeID"
EDGE_TARGET = "toNodeID"
EDGE_TYPE = "edgeType"

# Chunk size thresholds (in whitespace-delimited tokens)
MIN_CHUNK_TOKENS = 20
MAX_CHUNK_TOKENS = 512
OVERLAP_TOKENS = 50


# =============================================================================
# Utilities
# =============================================================================

def token_count(text: str) -> int:
    """Approximate token count by whitespace split."""
    return len(text.split())


def write_chunk(chunks_dir: Path, filename: str, text: str, metadata: dict):
    """Write a single chunk JSON file."""
    metadata["schema_version"] = CHUNK_SCHEMA_VERSION
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

    # Build human-readable text
    chunk_text = (
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

    metadata = {
        "chunk_type": "program_summary",
        "program": program,
        "node_count": node_count,
        "edge_count": edge_count,
        "variable_count": variable_count,
        "complexity_score": complexity_score,
    }
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

        # Build chunk text: comment_english (if available) + heading + body
        parts = []
        comment_meta = enriched.get(heading, {})
        comment_english = comment_meta.get("english", "")
        if comment_english:
            parts.append(comment_english)
        parts.append(heading)
        parts.append(body)
        chunk_text = "\n".join(parts)

        # Extract metadata from body
        calls = re.findall(r"\*\*PERFORM\*\*\s+`(.+?)`", body)
        has_comments = bool(comment_english)

        metadata = {
            "chunk_type": "paragraph_logic",
            "program": program,
            "paragraph": heading,
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

        chunk_text = "\n".join(lines)

        metadata = {
            "chunk_type": "variable_group",
            "program": program,
            "group_name": name,
            "section": section,
            "child_count": len(rec_children),
            "field_names": field_names[:50],  # cap for metadata size
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
    """Build per-paragraph metadata from CFG: local complexity.

    The CFG links paragraph content via FOLLOWED_BY chains, not
    STARTS_WITH containment. A paragraph's subgraph = its PARAGRAPH_NAME
    node + all FOLLOWED_BY-reachable nodes until the chain reaches
    another PARAGRAPH node or terminates.

    Returns {paragraph_name: {"complexity_local": int, "node_count": int}}.
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

        result[pname] = {
            "complexity_local": complexity,
            "node_count": internal_nodes,
        }

    return result


def enrich_paragraph_chunks(chunks_dir: Path, report_dir: Path,
                            program: str, verbose: bool) -> int:
    """Add complexity_local, node_count, and variable values to paragraph chunks."""
    subgraphs = _build_paragraph_subgraphs(report_dir)
    var_values = _load_variable_values(report_dir)

    enriched = 0
    for chunk_file in chunks_dir.glob(f"{program}__paragraph__*.json"):
        data = load_json(chunk_file)
        if not data:
            continue
        para_name = data["metadata"].get("paragraph", "")
        changed = False

        # CFG complexity
        sg = subgraphs.get(para_name)
        if sg:
            data["metadata"]["complexity_local"] = sg["complexity_local"]
            data["metadata"]["node_count"] = sg["node_count"]
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


def _load_variable_values(report_dir: Path) -> dict[str, list[str]]:
    """Load variable_values.json: {VAR_NAME: [val1, val2, ...]}."""
    path = report_dir / "variable_values.json"
    if not path.exists():
        return {}
    data = load_json(path)
    if not isinstance(data, list):
        return {}
    return {entry[0]: entry[1] for entry in data if len(entry) == 2}


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
    count = 0

    for s in steps:
        step_name = s.get("step_name", "UNKNOWN")
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

        metadata = {
            "chunk_type": "step_detail",
            "job_name": job_name,
            "step_name": step_name,
            "program": pgm,
            "proc": proc,
            "condition": cond,
            "cond_modifier": cond_mod,
            "input_datasets": input_ds,
            "output_datasets": output_ds,
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
        part_data = {
            "text": part_text,
            "metadata": {**data["metadata"], "part": idx, "total_parts": len(parts)},
        }
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
        entries.append({
            "file": f.name,
            "chunk_type": meta.get("chunk_type", "unknown"),
            "program": meta.get("program") or meta.get("job_name", "unknown"),
            "token_count": token_count(data.get("text", "")),
        })

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
    dir_name = report_dir.name  # e.g. "PDCBVC.CBL.report" or "MYJOB.jcl.report"
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

        # Enrich paragraph chunks with CFG metadata
        enriched = enrich_paragraph_chunks(
            chunks_dir, report_dir, program, verbose)
        summary["cfg_enriched"] = enriched

        # Apply size guard to paragraph chunks
        guard_stats = apply_size_guard(chunks_dir, program, verbose)
        if verbose and (guard_stats["merged"] or guard_stats["split"]):
            print(f"  Size guard: {guard_stats['merged']} merges, "
                  f"{guard_stats['split']} splits")

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
    parser = argparse.ArgumentParser(
        description="Chunk Pipeline — split report artifacts into RAG retrieval units",
    )
    parser.add_argument("report_dir", type=Path,
                        help="Path to a *.report directory")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Print detailed progress")
    args = parser.parse_args()

    if not args.report_dir.is_dir():
        print(f"Error: {args.report_dir} is not a directory")
        sys.exit(1)

    summary = run_pipeline(args.report_dir, verbose=args.verbose)
    if summary:
        print(f"\nDone. {summary.get('total', 0)} chunks generated.")
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
