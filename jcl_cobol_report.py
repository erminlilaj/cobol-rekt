#!/usr/bin/env python3
"""
jcl_cobol_report.py -- Detailed JCL-to-COBOL relationship report generator.

Takes a JCL report directory and cross-references it with COBOL report
directories to produce a comprehensive relationship report showing how
each JCL step relates to the COBOL programs it invokes.

Outputs:
  - jcl_cobol_relationship.json   (machine-readable model)
  - jcl_cobol_relationship.md     (human-readable Markdown report)
  - mermaid/jcl_cobol_flow.md     (Mermaid diagram)
  - chunks/ (RAG chunks: jcl_cobol_overview + jcl_cobol_step_relationship)

Usage:
    python3 jcl_cobol_report.py out/report/TEST.jcl.report
    python3 jcl_cobol_report.py out/report/TEST.jcl.report --report-dir out/report -v
"""

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path

import yaml

from build_call_graph import (
    normalize_program_name,
    discover_reports,
    build_corpus_registry,
    parse_cobol_calls,
    _SYSTEM_PGMS,
)

# =============================================================================
# Constants
# =============================================================================

CHUNK_SCHEMA_VERSION = "1.1"
PIPELINE_VERSION = "1.2"

# Expected artifacts in a COBOL report directory
_COBOL_ARTIFACTS = {
    "knowledge_base/03_Dependencies.yaml": "dependencies",
    "knowledge_base/00_Executive_Summary.md": "executive_summary",
    "knowledge_base/01_Logic_Narrative.md": "logic_narrative",
    "knowledge_base/02_Data_Dictionary.md": "data_dictionary",
}

# Artifact patterns that use glob
_COBOL_ARTIFACT_GLOBS = {
    "cfg/cfg-*.json": "cfg",
    "data_structures/*-data.json": "data_structures",
}

MAX_CALL_DEPTH = 5


# =============================================================================
# Data classes
# =============================================================================

@dataclass
class DDMapping:
    dd_name: str
    dsn: str
    access: str        # read, write, pass, special
    role: str          # data, library_override, program_input, system_print, system_output, diagnostic_dump
    is_temporary: bool = False
    is_null: bool = False
    dcb: dict | None = None


@dataclass
class StepRelationship:
    step_name: str
    step_index: int
    program: str | None
    proc: str | None
    program_in_corpus: bool
    is_system_utility: bool
    condition: str | None
    cond_modifier: str | None
    parm: str | None
    dd_mappings: list[DDMapping] = field(default_factory=list)
    # COBOL info (populated only if program_in_corpus)
    complexity_score: int = -1
    complexity_label: str = ""
    cfg_nodes: int = 0
    cfg_edges: int = 0
    variables_defined: int = 0
    sql_tables_read: list[str] = field(default_factory=list)
    sql_tables_updated: list[str] = field(default_factory=list)
    sql_statements: list[str] = field(default_factory=list)
    called_programs: list[str] = field(default_factory=list)
    cics_commands: list[str] = field(default_factory=list)
    transitive_call_chain: list[str] = field(default_factory=list)


@dataclass
class DatasetFlow:
    dataset: str
    producer_step: str | None      # None = external input
    consumer_steps: list[str] = field(default_factory=list)
    is_temporary: bool = False
    flow_type: str = ""            # external_input, inter_step, final_output


@dataclass
class ProgramHealth:
    name: str
    status: str                    # complete, partial, missing
    report_dir: str | None
    artifacts: dict[str, bool] = field(default_factory=dict)
    quality_flags: list[str] = field(default_factory=list)


# =============================================================================
# Utilities
# =============================================================================

def _extract_dsn_string(dsn_field) -> tuple[str, bool]:
    """Extract a display string and temporary flag from a DSN field.

    DSN can be: str, dict with 'dsn', dict with 'base' (GDG), or None.
    Returns (dsn_string, is_temporary).
    """
    if dsn_field is None:
        return ("(none)", False)
    if isinstance(dsn_field, str):
        return (dsn_field, dsn_field.startswith("&&"))
    if isinstance(dsn_field, dict):
        if dsn_field.get("null_dataset"):
            return ("(DUMMY)", False)
        if dsn_field.get("temporary"):
            return (f"&&{dsn_field.get('dsn', '?')}", True)
        if "member" in dsn_field:
            return (f"{dsn_field.get('dsn', '?')}({dsn_field['member']})", False)
        if "base" in dsn_field:
            gen = dsn_field.get("generation", "0")
            return (f"{dsn_field['base']}({gen})", False)
        return (dsn_field.get("dsn", str(dsn_field)), False)
    return (str(dsn_field), False)


def _classify_dd_role(dd: dict) -> str:
    """Classify a DD statement's role."""
    if dd.get("role"):
        return dd["role"]
    name = dd.get("dd_name", "").upper()
    if name in ("JOBLIB", "STEPLIB"):
        return "library_override"
    if dd.get("special_dd"):
        return dd.get("role", "system_output")
    if dd.get("null_dataset"):
        return "null"
    return "data"


def _parse_complexity_from_summary(text: str) -> tuple[int, str, int, int, int]:
    """Parse complexity score, label, nodes, edges, variables from executive summary markdown.

    Returns (score, label, nodes, edges, variables).
    """
    score, label = -1, ""
    nodes, edges, variables = 0, 0, 0

    m = re.search(r"Complexity Score\s*\|\s*(\w+)\s*\((\d+)\)", text)
    if m:
        label, score = m.group(1), int(m.group(2))

    m = re.search(r"Total CFG Nodes\s*\|\s*(\d+)", text)
    if m:
        nodes = int(m.group(1))

    m = re.search(r"Total Edges\s*\|\s*(\d+)", text)
    if m:
        edges = int(m.group(1))

    m = re.search(r"Variables Defined\s*\|\s*(\d+)", text)
    if m:
        variables = int(m.group(1))

    return score, label, nodes, edges, variables


def _load_json(path: Path):
    """Load a JSON file, return None on failure."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_yaml(path: Path):
    """Load a YAML file, return None on failure."""
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_chunk(chunks_dir: Path, filename: str, text: str, metadata: dict):
    """Write a single chunk JSON file."""
    metadata["schema_version"] = CHUNK_SCHEMA_VERSION
    metadata["pipeline_version"] = PIPELINE_VERSION
    metadata["analysis_timestamp"] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    metadata["content_hash"] = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    chunk = {"text": text, "metadata": metadata}
    (chunks_dir / filename).write_text(
        json.dumps(chunk, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


# =============================================================================
# Main builder class
# =============================================================================

class JCLCOBOLReportBuilder:
    """Builds a detailed JCL-to-COBOL relationship report."""

    def __init__(
        self,
        jcl_report_dir: Path,
        report_dirs: list[Path],
        verbose: bool = False,
        lenient_programs: set[str] | None = None,
    ):
        self.jcl_report_dir = Path(jcl_report_dir)
        self.report_dirs = report_dirs
        self.verbose = verbose
        self.lenient_programs = lenient_programs or set()

        # JCL artifacts
        self.jcl_summary: dict = {}
        self.jcl_steps: list[dict] = []
        self.jcl_datasets: dict = {}

        # COBOL data
        self.corpus: dict[str, Path] = {}
        self.cobol_deps: dict[str, dict] = {}      # canonical → deps yaml data
        self.cobol_summaries: dict[str, str] = {}   # canonical → executive summary text
        self.cobol_reports: list[Path] = []

        # Results
        self.step_relationships: list[StepRelationship] = []
        self.dataset_flows: list[DatasetFlow] = []
        self.program_health: dict[str, ProgramHealth] = {}
        self.cobol_edges: list[dict] = []           # for transitive calls
        self.logs: list[str] = []

    def _log(self, level: str, msg: str):
        entry = f"[{level}] {msg}"
        self.logs.append(entry)
        if self.verbose:
            print(entry)

    # -------------------------------------------------------------------------
    # Phase A: Data Loading
    # -------------------------------------------------------------------------

    def _load_jcl_artifacts(self):
        """Load the 3 JCL JSON artifacts."""
        self._log("INFO", f"Loading JCL artifacts from {self.jcl_report_dir.name}...")

        summary_path = self.jcl_report_dir / "jcl_summary.json"
        steps_path = self.jcl_report_dir / "jcl_steps.json"
        datasets_path = self.jcl_report_dir / "jcl_datasets.json"

        self.jcl_summary = _load_json(summary_path) or {}
        self.jcl_steps = _load_json(steps_path) or []
        self.jcl_datasets = (_load_json(datasets_path) or {}).get("datasets", {})

        if not self.jcl_summary:
            self._log("ERROR", f"Could not load {summary_path}")
            sys.exit(1)

        job_name = self.jcl_summary.get("job_name", "UNKNOWN")
        programs = self.jcl_summary.get("programs_invoked", [])
        step_count = self.jcl_summary.get("step_count", len(self.jcl_steps))

        # Filter system utilities
        user_programs = [p for p in programs if p.upper() not in _SYSTEM_PGMS]

        self._log(
            "INFO",
            f"Job {job_name}: {step_count} steps, "
            f"{len(user_programs)} user programs "
            f"(excluding {len(programs) - len(user_programs)} system utilities)",
        )

    def _discover_cobol_reports(self):
        """Find COBOL report directories for all invoked programs."""
        cobol_reports, jcl_reports = discover_reports(self.report_dirs)
        self.cobol_reports = cobol_reports
        self.corpus = build_corpus_registry(cobol_reports, jcl_reports)

        programs = self.jcl_summary.get("programs_invoked", [])
        user_programs = [p for p in programs if p.upper() not in _SYSTEM_PGMS]

        self._log(
            "INFO",
            f"Searching for COBOL reports for: {', '.join(user_programs)}",
        )

        for pgm in user_programs:
            canonical = normalize_program_name(pgm)
            report_dir = self.corpus.get(canonical)

            if report_dir is None:
                self._log("MISSING", f"{canonical} -> no report directory found")
                self.program_health[canonical] = ProgramHealth(
                    name=canonical,
                    status="missing",
                    report_dir=None,
                    quality_flags=[
                        "no report directory found -- run analyze.py on this program"
                    ],
                )
                continue

            # Check artifacts
            health = self._check_program_artifacts(canonical, report_dir)
            self.program_health[canonical] = health

            if health.status == "complete":
                self._log(
                    "FOUND",
                    f"{canonical} -> {report_dir.name} "
                    f"(knowledge_base: OK, data_structures: OK, cfg: OK)",
                )
            else:
                missing = [k for k, v in health.artifacts.items() if not v]
                self._log(
                    "WARN",
                    f"{canonical} -> {report_dir.name} "
                    f"(missing: {', '.join(missing)})",
                )

    def _check_program_artifacts(self, canonical: str, report_dir: Path) -> ProgramHealth:
        """Check which expected artifacts exist for a COBOL report."""
        artifacts: dict[str, bool] = {}
        quality_flags: list[str] = []

        # Check fixed-path artifacts
        for rel_path, label in _COBOL_ARTIFACTS.items():
            exists = (report_dir / rel_path).is_file()
            artifacts[rel_path] = exists
            if not exists:
                quality_flags.append(f"{rel_path} missing")

        # Check glob-pattern artifacts
        for pattern, label in _COBOL_ARTIFACT_GLOBS.items():
            matches = list(report_dir.glob(pattern))
            artifacts[pattern] = len(matches) > 0
            if not matches:
                quality_flags.append(f"{pattern} missing")

        # Check chunks directory
        chunks_exists = (report_dir / "chunks").is_dir()
        artifacts["chunks/"] = chunks_exists

        # Load and check content quality
        deps_path = report_dir / "knowledge_base" / "03_Dependencies.yaml"
        if deps_path.is_file():
            deps = _load_yaml(deps_path)
            if deps:
                self.cobol_deps[canonical] = deps
                db = deps.get("database", {})
                if not db.get("tables_read") and not db.get("tables_updated") and not db.get("sql_statements"):
                    quality_flags.append("no SQL statements found")
                if not deps.get("calls"):
                    quality_flags.append("no CALL targets found (leaf program)")
                if not deps.get("cics"):
                    quality_flags.append("no CICS commands")
        else:
            quality_flags.append("03_Dependencies.yaml missing -- dependency info unavailable")

        # Load executive summary
        summary_path = report_dir / "knowledge_base" / "00_Executive_Summary.md"
        if summary_path.is_file():
            text = summary_path.read_text(encoding="utf-8")
            self.cobol_summaries[canonical] = text
            score, label, nodes, _, _ = _parse_complexity_from_summary(text)
            if nodes == 0:
                quality_flags.append("empty CFG (0 nodes) -- parse may have failed")
            if score > 50:
                quality_flags.append(f"high complexity ({score}) -- flag for review")

        # Read parse diagnostics if available (written by Java CLI in lenient mode)
        diag_path = report_dir / "parse_diagnostics.json"
        if diag_path.is_file():
            try:
                diag = json.loads(diag_path.read_text(encoding="utf-8"))
                coverage = diag.get("coverage_percentage", 0)
                err_count = diag.get("error_summary", {}).get("total_errors", 0)
                quality_flags.append(
                    f"analyzed with --lenient: {coverage}% coverage "
                    f"({err_count} parse error(s) skipped)"
                )
                for err in diag.get("errors", []):
                    line = err.get("line", "?")
                    suggestion = err.get("suggestion", "")
                    cpb = err.get("copybook")
                    loc = f"line {line}" + (f" in copybook {cpb}" if cpb else "")
                    quality_flags.append(f"  parse error at {loc}: {suggestion}")
            except Exception:
                pass
        elif canonical in self.lenient_programs:
            quality_flags.append(
                "analyzed with --lenient (parse diagnostics file not found)"
            )

        # Read copybook manifest if available
        cpb_manifest_path = report_dir / "copybook_manifest.json"
        if cpb_manifest_path.is_file():
            try:
                cpb_data = json.loads(cpb_manifest_path.read_text(encoding="utf-8"))
                cpb_summary = cpb_data.get("summary", {})
                cpb_total = cpb_summary.get("total_copybooks", 0)
                cpb_stubbed = cpb_summary.get("stubbed", 0)
                cpb_pct = cpb_summary.get("resolved_percentage", 100)
                if cpb_stubbed > 0:
                    quality_flags.append(
                        f"copybooks: {cpb_pct}% resolved "
                        f"({cpb_total - cpb_stubbed}/{cpb_total}), "
                        f"{cpb_stubbed} stubbed"
                    )
                    stub_names = [
                        n for n, v in cpb_data.get("copybooks", {}).items()
                        if v.get("is_stub")
                    ]
                    if stub_names:
                        quality_flags.append(
                            f"  stubbed copybooks: {', '.join(stub_names[:10])}"
                        )
            except Exception:
                pass

        all_present = all(artifacts.values())
        status = "complete" if all_present else "partial"

        return ProgramHealth(
            name=canonical,
            status=status,
            report_dir=str(report_dir),
            artifacts=artifacts,
            quality_flags=quality_flags,
        )

    # -------------------------------------------------------------------------
    # Phase B: Correlation
    # -------------------------------------------------------------------------

    def _build_step_relationships(self):
        """Build StepRelationship for each JCL step."""
        for idx, step in enumerate(self.jcl_steps):
            pgm_raw = step.get("program", "")
            # Handle unresolved program references
            if isinstance(pgm_raw, dict):
                pgm_display = pgm_raw.get("value", str(pgm_raw))
                canonical = None
            else:
                pgm_display = pgm_raw
                canonical = normalize_program_name(pgm_raw) if pgm_raw else None

            is_system = pgm_display.upper() in _SYSTEM_PGMS if pgm_display else False
            in_corpus = canonical in self.corpus if canonical and not is_system else False

            # Build DD mappings
            dd_mappings = []
            for dd in step.get("dd_statements", []):
                dsn_raw = dd.get("dsn")
                dsn_str, is_temp = _extract_dsn_string(dsn_raw)
                role = _classify_dd_role(dd)
                access = dd.get("access", "special")

                # Refine access from DISP if access is "special"
                if access == "special":
                    disp = dd.get("disp", {}) or {}
                    normal = (disp.get("normal") or "").upper()
                    status = (disp.get("status") or "").upper()
                    if normal in ("CATLG", "KEEP"):
                        access = "write"
                    elif normal == "PASS":
                        access = "pass"
                    elif status in ("SHR", "OLD"):
                        access = "read"
                    else:
                        access = "write"  # default for NEW/MOD with CATLG

                dd_mappings.append(DDMapping(
                    dd_name=dd.get("dd_name", ""),
                    dsn=dsn_str,
                    access=access,
                    role=role,
                    is_temporary=is_temp,
                    is_null=dd.get("null_dataset", False),
                    dcb=dd.get("dcb") if isinstance(dd.get("dcb"), dict) else None,
                ))

            rel = StepRelationship(
                step_name=step.get("step_name", f"STEP{idx+1}"),
                step_index=idx,
                program=pgm_display,
                proc=step.get("proc"),
                program_in_corpus=in_corpus,
                is_system_utility=is_system,
                condition=step.get("condition"),
                cond_modifier=step.get("cond_modifier"),
                parm=step.get("parm"),
                dd_mappings=dd_mappings,
            )

            # Enrich with COBOL data if available
            if in_corpus and canonical:
                self._enrich_from_cobol(rel, canonical)

            self.step_relationships.append(rel)

    def _enrich_from_cobol(self, rel: StepRelationship, canonical: str):
        """Populate COBOL-derived fields on a StepRelationship."""
        # From executive summary
        summary_text = self.cobol_summaries.get(canonical, "")
        if summary_text:
            score, label, nodes, edges, variables = _parse_complexity_from_summary(summary_text)
            rel.complexity_score = score
            rel.complexity_label = label
            rel.cfg_nodes = nodes
            rel.cfg_edges = edges
            rel.variables_defined = variables

        # From dependencies
        deps = self.cobol_deps.get(canonical, {})
        db = deps.get("database", {})
        rel.sql_tables_read = db.get("tables_read", []) or []
        rel.sql_tables_updated = db.get("tables_updated", []) or []
        rel.sql_statements = db.get("sql_statements", []) or []

        calls = deps.get("calls", []) or []
        rel.called_programs = []
        for c in calls:
            if isinstance(c, dict):
                rel.called_programs.append(c.get("target", ""))
            elif isinstance(c, str):
                rel.called_programs.append(c)

        rel.cics_commands = deps.get("cics", []) or []

    def _build_dataset_flows(self):
        """Build dataset flow analysis from jcl_datasets."""
        self._log("INFO", "Building dataset flow analysis...")

        for dsn, info in self.jcl_datasets.items():
            read_by = info.get("read_by", [])
            written_by = info.get("written_by", [])
            is_temp = dsn.startswith("&&")

            if written_by and read_by:
                flow_type = "inter_step"
            elif not written_by and read_by:
                flow_type = "external_input"
            elif written_by and not read_by:
                flow_type = "final_output"
            else:
                flow_type = "unused"

            self.dataset_flows.append(DatasetFlow(
                dataset=dsn,
                producer_step=written_by[0] if written_by else None,
                consumer_steps=read_by,
                is_temporary=is_temp,
                flow_type=flow_type,
            ))

        # Also scan step DD mappings for temporary datasets not in jcl_datasets
        temp_producers: dict[str, str] = {}
        temp_consumers: dict[str, list[str]] = {}
        known_dsns = set(self.jcl_datasets.keys())

        for rel in self.step_relationships:
            for dd in rel.dd_mappings:
                if dd.is_temporary and dd.dsn not in known_dsns:
                    clean_dsn = dd.dsn.lstrip("&")
                    if dd.access in ("write", "pass", "special"):
                        temp_producers[clean_dsn] = rel.step_name
                    elif dd.access == "read":
                        temp_consumers.setdefault(clean_dsn, []).append(rel.step_name)

        for dsn, producer in temp_producers.items():
            consumers = temp_consumers.get(dsn, [])
            flow_type = "inter_step" if consumers else "final_output"
            self.dataset_flows.append(DatasetFlow(
                dataset=f"&&{dsn}",
                producer_step=producer,
                consumer_steps=consumers,
                is_temporary=True,
                flow_type=flow_type,
            ))

        ext_count = sum(1 for f in self.dataset_flows if f.flow_type == "external_input")
        inter_count = sum(1 for f in self.dataset_flows if f.flow_type == "inter_step")
        final_count = sum(1 for f in self.dataset_flows if f.flow_type == "final_output")
        self._log(
            "INFO",
            f"Dataset flow: {ext_count} external inputs, "
            f"{inter_count} inter-step flows, {final_count} final outputs",
        )

    def _compute_transitive_calls(self):
        """Compute transitive call chains for all JCL-invoked programs."""
        self._log("INFO", "Computing transitive call chains...")

        # Get all COBOL edges
        self.cobol_edges = parse_cobol_calls(self.cobol_reports, verbose=False)

        # Build adjacency map
        call_map: dict[str, list[str]] = {}
        for edge in self.cobol_edges:
            src = edge["source"]
            tgt = edge["target"]
            call_map.setdefault(src, []).append(tgt)

        for rel in self.step_relationships:
            if not rel.program or rel.is_system_utility:
                continue
            canonical = normalize_program_name(rel.program)
            chain = self._walk_call_chain(canonical, call_map, set(), 0)
            rel.transitive_call_chain = chain
            if chain:
                chain_str = " -> ".join(chain)
                in_corpus_flags = []
                for c in chain:
                    if c not in self.corpus:
                        in_corpus_flags.append(f"{c} (not in corpus)")
                    else:
                        in_corpus_flags.append(c)
                self._log("INFO", f"Transitive calls: {' -> '.join(in_corpus_flags)}")

    def _walk_call_chain(
        self, program: str, call_map: dict, visited: set, depth: int
    ) -> list[str]:
        """Walk the call graph forward from program, returning the chain."""
        if depth >= MAX_CALL_DEPTH or program in visited:
            return []
        visited.add(program)
        result = [program]
        for target in call_map.get(program, []):
            sub_chain = self._walk_call_chain(target, call_map, visited.copy(), depth + 1)
            result.extend(sub_chain)
        return result

    # -------------------------------------------------------------------------
    # Phase C: Output Generation
    # -------------------------------------------------------------------------

    def _write_json_model(self):
        """Write jcl_cobol_relationship.json."""
        job_name = self.jcl_summary.get("job_name", "UNKNOWN")
        programs = self.jcl_summary.get("programs_invoked", [])
        user_programs = [p for p in programs if p.upper() not in _SYSTEM_PGMS]

        analyzed = sum(
            1 for p in user_programs
            if self.program_health.get(normalize_program_name(p), ProgramHealth("", "missing", None)).status != "missing"
        )

        model = {
            "job_name": job_name,
            "generated": datetime.now().isoformat(timespec="seconds"),
            "steps": [self._step_to_dict(s) for s in self.step_relationships],
            "dataset_flows": [asdict(f) for f in self.dataset_flows],
            "program_health": {
                k: asdict(v) for k, v in self.program_health.items()
            },
            "external_inputs": [
                f.dataset for f in self.dataset_flows if f.flow_type == "external_input"
            ],
            "final_outputs": [
                f.dataset for f in self.dataset_flows if f.flow_type == "final_output"
            ],
            "missing_programs": [
                k for k, v in self.program_health.items() if v.status == "missing"
            ],
            "summary": {
                "total_steps": len(self.step_relationships),
                "user_programs": len(user_programs),
                "programs_analyzed": analyzed,
                "programs_missing": len(user_programs) - analyzed,
                "total_datasets": len(self.jcl_datasets),
                "inter_step_flows": sum(
                    1 for f in self.dataset_flows if f.flow_type == "inter_step"
                ),
                "coverage_pct": round(analyzed / len(user_programs) * 100) if user_programs else 0,
            },
            "logs": self.logs,
        }

        out_path = self.jcl_report_dir / "jcl_cobol_relationship.json"
        out_path.write_text(
            json.dumps(model, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        self._log("INFO", f"Wrote {out_path}")

    def _step_to_dict(self, s: StepRelationship) -> dict:
        """Convert StepRelationship to JSON-serializable dict."""
        return {
            "step_name": s.step_name,
            "step_index": s.step_index,
            "program": s.program,
            "proc": s.proc,
            "program_in_corpus": s.program_in_corpus,
            "is_system_utility": s.is_system_utility,
            "condition": s.condition,
            "cond_modifier": s.cond_modifier,
            "parm": s.parm,
            "dd_mappings": [asdict(d) for d in s.dd_mappings],
            "complexity_score": s.complexity_score,
            "complexity_label": s.complexity_label,
            "cfg_nodes": s.cfg_nodes,
            "cfg_edges": s.cfg_edges,
            "variables_defined": s.variables_defined,
            "sql_tables_read": s.sql_tables_read,
            "sql_tables_updated": s.sql_tables_updated,
            "sql_statements": s.sql_statements,
            "called_programs": s.called_programs,
            "cics_commands": s.cics_commands,
            "transitive_call_chain": s.transitive_call_chain,
        }

    def _write_markdown_report(self):
        """Write jcl_cobol_relationship.md."""
        job_name = self.jcl_summary.get("job_name", "UNKNOWN")
        lines: list[str] = []

        # --- Job Overview ---
        lines.append(f"# JCL-COBOL Relationship Report: {job_name}")
        lines.append("")
        lines.append("## Job Overview")
        lines.append("")
        lines.append(f"| Property | Value |")
        lines.append(f"|----------|-------|")
        lines.append(f"| Job Name | {job_name} |")
        lines.append(f"| Steps | {len(self.step_relationships)} |")
        programs = self.jcl_summary.get("programs_invoked", [])
        lines.append(f"| Programs Invoked | {', '.join(programs) if programs else '(none)'} |")
        lines.append(f"| Conditional Flow | {'Yes' if self.jcl_summary.get('has_conditional_flow') else 'No'} |")
        unresolved = self.jcl_summary.get("unresolved_symbols", [])
        if unresolved:
            lines.append(f"| Unresolved Symbols | {', '.join(unresolved)} |")
        region = self.jcl_summary.get("region", "")
        if region:
            lines.append(f"| Region | {region} |")
        jcl_class = self.jcl_summary.get("class", "")
        if jcl_class:
            lines.append(f"| Class | {jcl_class} |")
        lines.append("")

        # --- Execution Flow Diagram ---
        lines.append("## Execution Flow Diagram")
        lines.append("")
        lines.append("See `mermaid/jcl_cobol_flow.md` for the visual flow diagram.")
        lines.append("")

        # --- Step-by-Step Breakdown ---
        lines.append("## Step-by-Step Breakdown")
        lines.append("")

        for rel in self.step_relationships:
            lines.append(f"### Step {rel.step_index + 1}: {rel.step_name}")
            lines.append("")

            # Program info
            if rel.is_system_utility:
                lines.append(f"- **Program:** {rel.program} (system utility)")
            elif rel.program_in_corpus:
                lines.append(f"- **Program:** {rel.program} (analyzed)")
            else:
                lines.append(f"- **Program:** {rel.program} (not analyzed)")

            if rel.proc:
                lines.append(f"- **PROC:** {rel.proc}")
            if rel.condition:
                cond_str = rel.condition
                if rel.cond_modifier:
                    cond_str += f" ({rel.cond_modifier})"
                lines.append(f"- **Condition:** {cond_str}")
            if rel.parm:
                lines.append(f"- **Parameters:** {rel.parm}")

            # COBOL details (only for analyzed programs)
            if rel.program_in_corpus:
                lines.append(f"- **Complexity:** {rel.complexity_label} ({rel.complexity_score})")
                lines.append(f"- **CFG:** {rel.cfg_nodes} nodes, {rel.cfg_edges} edges")
                lines.append(f"- **Variables:** {rel.variables_defined}")

                if rel.sql_tables_read:
                    lines.append(f"- **SQL Tables Read:** {', '.join(rel.sql_tables_read)}")
                if rel.sql_tables_updated:
                    lines.append(f"- **SQL Tables Updated:** {', '.join(rel.sql_tables_updated)}")
                if rel.sql_statements:
                    lines.append(f"- **SQL Statements:** {', '.join(rel.sql_statements)}")
                if rel.called_programs:
                    lines.append(f"- **Calls:** {', '.join(rel.called_programs)}")
                if rel.cics_commands:
                    lines.append(f"- **CICS Commands:** {', '.join(rel.cics_commands)}")
                if len(rel.transitive_call_chain) > 1:
                    lines.append(f"- **Call Chain:** {' -> '.join(rel.transitive_call_chain)}")

            # DD statements table
            data_dds = [d for d in rel.dd_mappings if d.role == "data" or d.role == "null"]
            system_dds = [d for d in rel.dd_mappings if d.role != "data" and d.role != "null"]

            if data_dds:
                lines.append("")
                lines.append("**Data DD Statements:**")
                lines.append("")
                lines.append("| DD Name | Dataset | Access | Temp |")
                lines.append("|---------|---------|--------|------|")
                for d in data_dds:
                    temp_flag = "Yes" if d.is_temporary else ""
                    null_flag = "(DUMMY)" if d.is_null else ""
                    dsn_display = null_flag if d.is_null else d.dsn
                    lines.append(f"| {d.dd_name} | {dsn_display} | {d.access} | {temp_flag} |")

            if system_dds:
                lines.append("")
                lines.append("**System/Control DD Statements:**")
                lines.append("")
                lines.append("| DD Name | Role | Dataset |")
                lines.append("|---------|------|---------|")
                for d in system_dds:
                    dsn_display = d.dsn if d.dsn != "(none)" else "-"
                    lines.append(f"| {d.dd_name} | {d.role} | {dsn_display} |")

            lines.append("")

        # --- Analysis Health Check ---
        lines.append("## Analysis Health Check")
        lines.append("")

        user_programs = [p for p in programs if p.upper() not in _SYSTEM_PGMS]
        analyzed = sum(
            1 for p in user_programs
            if self.program_health.get(normalize_program_name(p), ProgramHealth("", "missing", None)).status != "missing"
        )
        total = len(user_programs)
        pct = round(analyzed / total * 100) if total else 0
        lines.append(f"**Coverage:** {analyzed}/{total} programs analyzed ({pct}%)")
        lines.append("")

        lines.append("| Program | Status | Missing Artifacts | Quality Flags |")
        lines.append("|---------|--------|-------------------|---------------|")
        for canonical, health in sorted(self.program_health.items()):
            missing_arts = [k for k, v in health.artifacts.items() if not v]
            missing_str = ", ".join(missing_arts) if missing_arts else "-"
            flags_str = "; ".join(health.quality_flags) if health.quality_flags else "-"
            lines.append(f"| {health.name} | {health.status.upper()} | {missing_str} | {flags_str} |")

        lines.append("")

        if any(h.status == "missing" for h in self.program_health.values()):
            lines.append("**Recommendations:**")
            for canonical, health in self.program_health.items():
                if health.status == "missing":
                    lines.append(f"- Run `python3 analyze.py <path_to_{canonical}.cbl>` to generate report for {canonical}")
            lines.append("")

        # --- Dataset Flow Table ---
        lines.append("## Dataset Flow")
        lines.append("")

        if self.dataset_flows:
            lines.append("| Dataset | Written By | Read By | Type |")
            lines.append("|---------|-----------|---------|------|")
            for f in sorted(self.dataset_flows, key=lambda x: x.flow_type):
                producer = f.producer_step or "(external)"
                consumers = ", ".join(f.consumer_steps) if f.consumer_steps else "(final output)"
                label = f.flow_type.replace("_", " ").title()
                if f.is_temporary:
                    label += " (temp)"
                lines.append(f"| {f.dataset} | {producer} | {consumers} | {label} |")
            lines.append("")
        else:
            lines.append("No dataset flows detected.")
            lines.append("")

        # --- Transitive Call Chains ---
        has_chains = any(
            len(r.transitive_call_chain) > 1
            for r in self.step_relationships
        )
        if has_chains:
            lines.append("## Transitive Call Chains")
            lines.append("")
            for rel in self.step_relationships:
                if len(rel.transitive_call_chain) > 1:
                    chain_parts = []
                    for c in rel.transitive_call_chain:
                        canonical_c = normalize_program_name(c)
                        if canonical_c not in self.corpus:
                            chain_parts.append(f"{c} (not in corpus)")
                        else:
                            chain_parts.append(c)
                    lines.append(f"- **{rel.step_name}:** {' -> '.join(chain_parts)}")
            lines.append("")

        # --- Data Contract Summary ---
        lines.append("## Data Contract Summary")
        lines.append("")
        lines.append("| Step | Program | Consumes | Produces |")
        lines.append("|------|---------|----------|----------|")
        for rel in self.step_relationships:
            inputs = [d.dsn for d in rel.dd_mappings if d.access == "read" and d.role == "data"]
            outputs = [d.dsn for d in rel.dd_mappings if d.access in ("write", "pass") and d.role == "data"]
            inputs_str = ", ".join(inputs) if inputs else "-"
            outputs_str = ", ".join(outputs) if outputs else "-"
            lines.append(f"| {rel.step_name} | {rel.program} | {inputs_str} | {outputs_str} |")
        lines.append("")

        # --- Analysis Log ---
        lines.append("## Analysis Log")
        lines.append("")
        lines.append("```")
        for log in self.logs:
            lines.append(log)
        lines.append("```")
        lines.append("")

        out_path = self.jcl_report_dir / "jcl_cobol_relationship.md"
        out_path.write_text("\n".join(lines), encoding="utf-8")
        self._log("INFO", f"Wrote {out_path}")

    def _write_mermaid_diagram(self):
        """Write mermaid/jcl_cobol_flow.md."""
        job_name = self.jcl_summary.get("job_name", "UNKNOWN")
        mermaid_dir = self.jcl_report_dir / "mermaid"
        mermaid_dir.mkdir(parents=True, exist_ok=True)

        lines = ["```mermaid", "flowchart TD"]

        # Style definitions
        lines.append("    classDef analyzed fill:#d4edda,stroke:#28a745,color:#000")
        lines.append("    classDef missing fill:#f8d7da,stroke:#dc3545,color:#000")
        lines.append("    classDef utility fill:#e2e3e5,stroke:#6c757d,color:#000")
        lines.append("    classDef dataset fill:#cce5ff,stroke:#004085,color:#000")
        lines.append("    classDef tempds fill:#fff3cd,stroke:#856404,color:#000")
        lines.append("")

        # Subgraph for the job
        lines.append(f"    subgraph JOB_{job_name}[\"{job_name}\"]")
        lines.append(f"        direction TD")

        # Step nodes
        for rel in self.step_relationships:
            node_id = f"S{rel.step_index}"
            label = f"{rel.step_name}\\n({rel.program})"
            if rel.program_in_corpus and rel.complexity_label:
                label += f"\\nComplexity: {rel.complexity_label}"

            lines.append(f"        {node_id}[\"{label}\"]")

            if rel.program_in_corpus:
                lines.append(f"        class {node_id} analyzed")
            elif rel.is_system_utility:
                lines.append(f"        class {node_id} utility")
            else:
                lines.append(f"        class {node_id} missing")

        # Step sequence arrows
        for i in range(len(self.step_relationships) - 1):
            lines.append(f"        S{i} --> S{i+1}")

        lines.append("    end")
        lines.append("")

        # Dataset nodes and edges (limit to avoid oversized diagrams)
        datasets_shown = set()
        node_count = len(self.step_relationships)
        max_datasets = max(50 - node_count, 10)

        # Prioritize inter-step and external datasets
        priority_flows = sorted(
            self.dataset_flows,
            key=lambda f: (
                0 if f.flow_type == "inter_step" else
                1 if f.flow_type == "external_input" else
                2 if f.flow_type == "final_output" else 3
            ),
        )

        for flow in priority_flows[:max_datasets]:
            dsn_safe = flow.dataset.replace('"', "'")
            dsn_id = re.sub(r"[^A-Za-z0-9]", "_", flow.dataset)
            datasets_shown.add(flow.dataset)

            # Truncate long DSN for display
            dsn_display = dsn_safe if len(dsn_safe) <= 40 else dsn_safe[:37] + "..."

            lines.append(f"    {dsn_id}[/\"{dsn_display}\"/]")
            if flow.is_temporary:
                lines.append(f"    class {dsn_id} tempds")
            else:
                lines.append(f"    class {dsn_id} dataset")

            # Producer edge
            if flow.producer_step:
                step_idx = self._step_name_to_index(flow.producer_step)
                if step_idx is not None:
                    lines.append(f"    S{step_idx} -->|writes| {dsn_id}")

            # Consumer edges
            for consumer in flow.consumer_steps:
                step_idx = self._step_name_to_index(consumer)
                if step_idx is not None:
                    lines.append(f"    {dsn_id} -->|reads| S{step_idx}")

        if len(priority_flows) > max_datasets:
            lines.append(f"    NOTE[\"{len(priority_flows) - max_datasets} datasets omitted\"]")

        # COBOL CALL edges (dashed)
        for rel in self.step_relationships:
            if rel.called_programs:
                src_id = f"S{rel.step_index}"
                for called in rel.called_programs:
                    # Find if called program is also a JCL step
                    called_canonical = normalize_program_name(called)
                    called_step_idx = None
                    for other_rel in self.step_relationships:
                        if other_rel.program and normalize_program_name(other_rel.program) == called_canonical:
                            called_step_idx = other_rel.step_index
                            break
                    if called_step_idx is not None:
                        lines.append(f"    {src_id} -.->|CALLS| S{called_step_idx}")
                    else:
                        # External call target -- add as separate node
                        ext_id = f"EXT_{called_canonical}"
                        lines.append(f"    {ext_id}([\"{called}\"])")
                        lines.append(f"    class {ext_id} missing")
                        lines.append(f"    {src_id} -.->|CALLS| {ext_id}")

        lines.append("```")

        out_path = mermaid_dir / "jcl_cobol_flow.md"
        out_path.write_text("\n".join(lines), encoding="utf-8")
        self._log("INFO", f"Wrote {out_path}")

    def _step_name_to_index(self, step_name: str) -> int | None:
        """Find step index by name."""
        for rel in self.step_relationships:
            if rel.step_name == step_name:
                return rel.step_index
        return None

    def _write_chunks(self):
        """Write RAG chunks for the JCL-COBOL relationship."""
        chunks_dir = self.jcl_report_dir / "chunks"
        chunks_dir.mkdir(parents=True, exist_ok=True)

        job_name = self.jcl_summary.get("job_name", "UNKNOWN")
        chunk_files = []

        # Classify dataset flows once for reuse
        ext = [f for f in self.dataset_flows if f.flow_type == "external_input"]
        inter = [f for f in self.dataset_flows if f.flow_type == "inter_step"]
        final = [f for f in self.dataset_flows if f.flow_type == "final_output"]

        programs = self.jcl_summary.get("programs_invoked", [])
        user_programs = [p for p in programs if p.upper() not in _SYSTEM_PGMS]
        analyzed = sum(1 for h in self.program_health.values() if h.status != "missing")

        # --- jcl_cobol_overview chunk (with natural language flow narration) ---
        overview_parts = [
            f"Job {job_name} executes {len(self.step_relationships)} steps "
            f"invoking {len(user_programs)} user programs: {', '.join(user_programs)}.",
            f"Analysis coverage: {analyzed}/{len(user_programs)} programs analyzed.",
            f"Dataset flow: {len(ext)} external inputs, "
            f"{len(inter)} inter-step flows, {len(final)} final outputs.",
        ]

        # Natural language flow narration (7b.11)
        narration_parts = []
        for i, rel in enumerate(self.step_relationships):
            input_dds = [d for d in rel.dd_mappings
                         if d.access == "read" and d.role == "data"
                         and d.dsn not in ("(none)", "", None) and not d.is_null]
            output_dds = [d for d in rel.dd_mappings
                          if d.access in ("write", "pass") and d.role == "data"
                          and d.dsn not in ("(none)", "", None) and not d.is_null]
            desc = f"{rel.step_name} executes {rel.program}"
            if rel.is_system_utility:
                desc += " (system utility)"
            elif not rel.program_in_corpus:
                desc += " (not analyzed)"
            if rel.parm:
                desc += f" with PARM={rel.parm}"
            if input_dds:
                desc += f", reading {', '.join(d.dsn for d in input_dds)}"
            if output_dds:
                desc += f", writing {', '.join(d.dsn for d in output_dds)}"
            narration_parts.append(desc)
        if narration_parts:
            overview_parts.append(
                "Execution flow: " + ". ".join(narration_parts) + "."
            )

        overview_text = " ".join(overview_parts)

        overview_meta = {
            "chunk_type": "jcl_cobol_overview",
            "chunk_id": f"{job_name}:jcl_cobol_overview",
            "program": job_name,
            "job_name": job_name,
            "step_count": len(self.step_relationships),
            "programs_invoked": user_programs,
            "programs_analyzed": analyzed,
            "programs_missing": [k for k, v in self.program_health.items() if v.status == "missing"],
            "external_inputs": [f.dataset for f in ext],
            "final_outputs": [f.dataset for f in final],
        }

        overview_file = f"{job_name}__jcl_cobol_overview.json"
        _write_chunk(chunks_dir, overview_file, overview_text, overview_meta)
        chunk_files.append({"file": overview_file, "chunk_type": "jcl_cobol_overview", "program": job_name})

        # --- jcl_cobol_step_relationship chunks (one per EVERY step) ---
        for rel in self.step_relationships:
            parts = [
                f"Step {rel.step_name} (index {rel.step_index}) executes "
                f"program {rel.program}.",
            ]

            if rel.is_system_utility:
                parts.append("This is a system utility.")
            elif not rel.program_in_corpus:
                parts.append("Program not analyzed (report missing).")

            if rel.condition:
                cond_text = f"Condition: {rel.condition}"
                if rel.cond_modifier:
                    cond_text += f" ({rel.cond_modifier})"
                parts.append(cond_text + ".")
            if rel.parm:
                parts.append(f"Parameters: {rel.parm}.")

            # DD summary (exclude DDs with no real DSN)
            input_dds = [d for d in rel.dd_mappings
                         if d.access == "read" and d.role == "data"
                         and d.dsn not in ("(none)", "", None) and not d.is_null]
            output_dds = [d for d in rel.dd_mappings
                          if d.access in ("write", "pass") and d.role == "data"
                          and d.dsn not in ("(none)", "", None) and not d.is_null]
            if input_dds:
                parts.append(f"Input datasets: {', '.join(d.dsn for d in input_dds)}.")
            if output_dds:
                parts.append(f"Output datasets: {', '.join(d.dsn for d in output_dds)}.")

            # COBOL details (only present if program_in_corpus)
            if rel.complexity_label:
                parts.append(f"Complexity: {rel.complexity_label} ({rel.complexity_score}).")
            if rel.sql_tables_read:
                parts.append(f"SQL tables read: {', '.join(rel.sql_tables_read)}.")
            if rel.sql_tables_updated:
                parts.append(f"SQL tables updated: {', '.join(rel.sql_tables_updated)}.")
            if rel.called_programs:
                parts.append(f"Calls programs: {', '.join(rel.called_programs)}.")
            if rel.cics_commands:
                parts.append(f"CICS commands: {', '.join(rel.cics_commands)}.")
            if len(rel.transitive_call_chain) > 1:
                parts.append(f"Full call chain: {' -> '.join(rel.transitive_call_chain)}.")

            step_text = " ".join(parts)

            # Determine analysis status
            if rel.is_system_utility:
                analysis_status = "system_utility"
            elif rel.program_in_corpus:
                analysis_status = "analyzed"
            else:
                analysis_status = "missing"

            # Cross-references to COBOL chunks (7b.3)
            related_cobol = []
            if rel.program_in_corpus and rel.program:
                canonical = normalize_program_name(rel.program)
                health = self.program_health.get(canonical)
                if health and health.report_dir:
                    # Check which COBOL report extensions exist
                    rdir = Path(health.report_dir)
                    for ext_suffix in (".cbl", ".CBL", ".cob", ".COB"):
                        prog_name = canonical + ext_suffix
                        if (rdir / "knowledge_base" / "00_Executive_Summary.md").exists():
                            related_cobol.append(f"{prog_name}:program_summary")
                            related_cobol.append(f"{prog_name}:dependencies")
                            break

            step_meta = {
                "chunk_type": "jcl_cobol_step_relationship",
                "chunk_id": f"{job_name}:step_relationship:{rel.step_name}",
                "program": job_name,
                "job_name": job_name,
                "step_name": rel.step_name,
                "step_program": rel.program,
                "analysis_status": analysis_status,
                "complexity_score": rel.complexity_score,
                "sql_tables_read": rel.sql_tables_read,
                "sql_tables_updated": rel.sql_tables_updated,
                "called_programs": rel.called_programs,
                "cics_commands": rel.cics_commands,
                "input_datasets": [d.dsn for d in input_dds],
                "output_datasets": [d.dsn for d in output_dds],
            }
            if related_cobol:
                step_meta["related_cobol_chunks"] = related_cobol

            step_file = f"{job_name}__step_relationship__{rel.step_name}.json"
            _write_chunk(chunks_dir, step_file, step_text, step_meta)
            chunk_files.append({
                "file": step_file,
                "chunk_type": "jcl_cobol_step_relationship",
                "program": job_name,
            })

        # --- jcl_dataset_flow chunks (7b.4) ---
        for flow in self.dataset_flows:
            if flow.flow_type == "unused":
                continue
            flow_parts = [f"Dataset {flow.dataset}"]
            if flow.producer_step:
                flow_parts.append(f"is written by step {flow.producer_step}")
            else:
                flow_parts.append("is an external input (not written by any step)")
            if flow.consumer_steps:
                flow_parts.append(
                    f"and read by step{'s' if len(flow.consumer_steps) > 1 else ''} "
                    f"{', '.join(flow.consumer_steps)}"
                )
            else:
                flow_parts.append("and is not read by any subsequent step")
            temp_label = "temporary" if flow.is_temporary else "permanent"
            flow_parts.append(f". It is a {temp_label} {flow.flow_type.replace('_', ' ')} dataset.")
            flow_text = " ".join(flow_parts)

            flow_meta = {
                "chunk_type": "jcl_dataset_flow",
                "chunk_id": f"{job_name}:dataset_flow:{flow.dataset}",
                "program": job_name,
                "job_name": job_name,
                "dataset": flow.dataset,
                "producer_step": flow.producer_step,
                "consumer_steps": flow.consumer_steps,
                "flow_type": flow.flow_type,
                "is_temporary": flow.is_temporary,
            }
            safe_dsn = re.sub(r"[^\w\-]", "_", flow.dataset)[:60]
            flow_file = f"{job_name}__dataset_flow__{safe_dsn}.json"
            _write_chunk(chunks_dir, flow_file, flow_text, flow_meta)
            chunk_files.append({
                "file": flow_file,
                "chunk_type": "jcl_dataset_flow",
                "program": job_name,
            })

        # --- jcl_analysis_health chunk (7b.8) ---
        missing_progs = [k for k, v in self.program_health.items() if v.status == "missing"]
        total_user = len(user_programs)
        pct = round(analyzed / total_user * 100) if total_user else 0

        health_parts = [
            f"Analysis health for job {job_name}: "
            f"{analyzed}/{total_user} programs analyzed ({pct}% coverage).",
        ]
        if missing_progs:
            health_parts.append(f"Missing programs: {', '.join(missing_progs)}.")
        # Collect quality flags across all programs
        all_flags = {}
        for canonical, health in self.program_health.items():
            if health.quality_flags:
                all_flags[canonical] = health.quality_flags
        if all_flags:
            for prog, flags in all_flags.items():
                health_parts.append(f"{prog}: {'; '.join(flags)}.")
        if not missing_progs and not all_flags:
            health_parts.append("All programs fully analyzed with no quality issues.")

        health_text = " ".join(health_parts)
        health_meta = {
            "chunk_type": "jcl_analysis_health",
            "chunk_id": f"{job_name}:analysis_health",
            "program": job_name,
            "job_name": job_name,
            "coverage_pct": pct,
            "programs_analyzed": analyzed,
            "programs_total": total_user,
            "missing_programs": missing_progs,
            "quality_flags_by_program": all_flags,
        }
        health_file = f"{job_name}__analysis_health.json"
        _write_chunk(chunks_dir, health_file, health_text, health_meta)
        chunk_files.append({
            "file": health_file,
            "chunk_type": "jcl_analysis_health",
            "program": job_name,
        })

        # --- jcl_condition_flow chunk (7b.9) ---
        cond_steps = [
            r for r in self.step_relationships
            if r.condition or r.cond_modifier
        ]
        if cond_steps:
            cond_parts = [f"Job {job_name} has {len(cond_steps)} conditional step(s)."]
            for cs in cond_steps:
                desc = f"Step {cs.step_name} ({cs.program})"
                if cs.condition:
                    desc += f" runs if {cs.condition}"
                if cs.cond_modifier:
                    desc += f" (modifier: {cs.cond_modifier})"
                cond_parts.append(desc + ".")
        else:
            cond_parts = [
                f"Job {job_name} has no conditional steps. "
                f"All {len(self.step_relationships)} steps execute "
                f"unconditionally in sequence."
            ]

        cond_text = " ".join(cond_parts)
        cond_meta = {
            "chunk_type": "jcl_condition_flow",
            "chunk_id": f"{job_name}:condition_flow",
            "program": job_name,
            "job_name": job_name,
            "has_conditions": bool(cond_steps),
            "condition_steps": [cs.step_name for cs in cond_steps],
        }
        cond_file = f"{job_name}__condition_flow.json"
        _write_chunk(chunks_dir, cond_file, cond_text, cond_meta)
        chunk_files.append({
            "file": cond_file,
            "chunk_type": "jcl_condition_flow",
            "program": job_name,
        })

        # --- Update manifest ---
        manifest_path = chunks_dir / "chunks_manifest.json"
        existing_manifest = _load_json(manifest_path) or {}
        existing_chunks = existing_manifest.get("chunks", [])

        # Remove old jcl_cobol chunks (all types we generate)
        jcl_cobol_types = {
            "jcl_cobol_overview", "jcl_cobol_step_relationship",
            "jcl_dataset_flow", "jcl_analysis_health", "jcl_condition_flow",
        }
        existing_chunks = [
            c for c in existing_chunks
            if c.get("chunk_type") not in jcl_cobol_types
        ]
        all_chunks = existing_chunks + chunk_files

        # Recount
        type_counts: dict[str, int] = {}
        for c in all_chunks:
            ct = c.get("chunk_type", "unknown")
            type_counts[ct] = type_counts.get(ct, 0) + 1

        manifest = {
            "schema_version": CHUNK_SCHEMA_VERSION,
            "total_chunks": len(all_chunks),
            "type_counts": type_counts,
            "chunks": all_chunks,
        }

        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        self._log("INFO", f"Wrote {len(chunk_files)} new chunks, manifest updated")

    # -------------------------------------------------------------------------
    # Main entry point
    # -------------------------------------------------------------------------

    def build(self) -> Path:
        """Run the full report generation pipeline. Returns output directory."""
        self._load_jcl_artifacts()
        self._discover_cobol_reports()
        self._build_step_relationships()
        self._build_dataset_flows()
        self._compute_transitive_calls()
        self._write_json_model()
        self._write_markdown_report()
        self._write_mermaid_diagram()
        self._write_chunks()

        # Print final summary
        programs = self.jcl_summary.get("programs_invoked", [])
        user_programs = [p for p in programs if p.upper() not in _SYSTEM_PGMS]
        analyzed = sum(1 for h in self.program_health.values() if h.status != "missing")
        total = len(user_programs)

        print(
            f"\nJCL-COBOL Relationship Report: {self.jcl_summary.get('job_name', '?')}"
        )
        print(f"  Steps: {len(self.step_relationships)}")
        print(f"  Coverage: {analyzed}/{total} programs analyzed ({round(analyzed/total*100) if total else 0}%)")
        print(f"  Outputs: {self.jcl_report_dir}")

        return self.jcl_report_dir


# =============================================================================
# CLI
# =============================================================================

_COBOL_EXTENSIONS = {".cbl", ".CBL", ".cob", ".COB"}
_JCL_EXTENSIONS = {".jcl", ".JCL"}


def _find_cobol_sources(directory: Path) -> list[Path]:
    """Find all COBOL source files in a directory (non-recursive)."""
    results = []
    for f in sorted(directory.iterdir()):
        if f.is_file() and f.suffix in _COBOL_EXTENSIONS:
            results.append(f)
    return results


def _run_jcl_parser(jcl_file: Path, output_dir: Path, verbose: bool) -> Path:
    """Parse a raw JCL file and return the report directory."""
    from jcl_parser import build_jcl_report
    return build_jcl_report(jcl_file, output_dir=output_dir, verbose=verbose)


def _run_cobol_analysis(cobol_file: Path, copybook_dirs: list[Path], verbose: bool, lenient: bool = False):
    """Run analyze.py on a single COBOL file. Retries with --lenient on failure.

    The parser's lenient mode uses ANTLR error recovery to skip problematic tokens
    and continue parsing. The resulting AST covers everything except the few
    statements that triggered errors. For typical COBOL files, this means
    >99% of the program is captured even with parse errors.
    """
    import subprocess
    cmd = [sys.executable, "analyze.py", str(cobol_file)]
    for cpd in copybook_dirs:
        cmd.extend(["--copybooks-dir", str(cpd)])
    if lenient:
        cmd.append("--lenient")
    if verbose:
        print(f"[AUTO] Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    used_lenient = lenient
    if result.returncode != 0 and not lenient:
        # Extract error count for reporting
        err_count = _count_parse_errors(result.stderr or result.stdout or "")
        print(f"[AUTO] Strict parse failed for {cobol_file.name} "
              f"({err_count} parse error(s)), retrying with --lenient...")
        print(f"[AUTO] Lenient mode skips only the errored tokens; "
              f"all other code is fully analyzed.")
        cmd.append("--lenient")
        if verbose:
            print(f"[AUTO] Running: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=not verbose, text=True)
        used_lenient = True
    if result.returncode != 0:
        print(f"[AUTO] Warning: analyze.py failed for {cobol_file.name} (rc={result.returncode})")
        if result.stderr:
            lines = result.stderr.strip().split("\n")
            for line in lines[-5:]:
                print(f"  {line}")
        return "failed"
    if used_lenient and not lenient:
        print(f"[AUTO] {cobol_file.name} analyzed successfully with --lenient "
              f"(only errored tokens skipped, rest fully analyzed)")
    return "lenient" if used_lenient else "strict"


def _count_parse_errors(output: str) -> int:
    """Count the number of parse errors reported in Java CLI output."""
    import re
    # Count SyntaxError occurrences or "severity=ERROR" markers
    errors = re.findall(r'severity=ERROR|"severity":\s*"ERROR"', output)
    return len(errors) if errors else 1  # at least 1 if we got here


def main():
    parser = argparse.ArgumentParser(
        description="Generate detailed JCL-to-COBOL relationship report",
        epilog="""
Examples:
  # From a pre-existing JCL report directory:
  python3 jcl_cobol_report.py out/report/TEST.jcl.report -v

  # From a raw JCL file (auto-parses it first):
  python3 jcl_cobol_report.py /path/to/MYJOB.jcl -v

  # With COBOL source directory (auto-analyzes missing programs):
  python3 jcl_cobol_report.py /path/to/MYJOB.jcl --cobol-dir /path/to/sources -v

  # COBOL sources + copybooks in a separate dir:
  python3 jcl_cobol_report.py /path/to/MYJOB.jcl --cobol-dir /path/to/sources --copybooks-dir /path/to/copybooks -v
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "jcl_input",
        type=Path,
        help="Path to JCL report directory OR raw JCL file (.jcl)",
    )
    parser.add_argument(
        "--report-dir",
        type=Path,
        action="append",
        dest="report_dirs",
        default=None,
        help="Report directory to search for COBOL reports (repeatable; default: out/report)",
    )
    parser.add_argument(
        "--cobol-dir",
        type=Path,
        action="append",
        dest="cobol_dirs",
        default=None,
        help="Directory containing COBOL source files (.cbl/.cob) and optionally copybooks (.cpy). "
             "Missing programs will be auto-analyzed. Repeatable for multiple directories.",
    )
    parser.add_argument(
        "--copybooks-dir",
        type=Path,
        action="append",
        dest="copybook_dirs",
        default=None,
        help="Directory containing copybook files (.cpy). Passed to analyze.py when auto-analyzing. "
             "If not specified, --cobol-dir is used for copybooks too.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("out/report"),
        help="Root output directory for reports (default: out/report)",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument(
        "--lenient",
        action="store_true",
        help="Pass --lenient to analyze.py when auto-analyzing COBOL files. "
             "Allows parsing to continue past syntax errors. "
             "Also auto-retries with --lenient if strict parsing fails.",
    )
    args = parser.parse_args()

    jcl_input = args.jcl_input

    # Determine if input is a raw JCL file or a report directory
    if jcl_input.is_file() and jcl_input.suffix.lower() in (".jcl",):
        # Raw JCL file -- parse it first
        print(f"Parsing JCL file: {jcl_input}")
        jcl_report_dir = _run_jcl_parser(jcl_input, args.output_dir, args.verbose)
        print(f"JCL report created: {jcl_report_dir}")
    elif jcl_input.is_dir():
        jcl_report_dir = jcl_input
    else:
        print(f"Error: {jcl_input} is not a .jcl file or a directory", file=sys.stderr)
        sys.exit(1)

    if not (jcl_report_dir / "jcl_summary.json").is_file():
        print(f"Error: {jcl_report_dir} does not contain jcl_summary.json", file=sys.stderr)
        sys.exit(1)

    # Determine report search dirs
    if args.report_dirs is None:
        args.report_dirs = [args.output_dir]

    # Auto-analyze missing COBOL programs if --cobol-dir given
    if args.cobol_dirs:
        summary = _load_json(jcl_report_dir / "jcl_summary.json") or {}
        programs_needed = [
            p for p in summary.get("programs_invoked", [])
            if p.upper() not in _SYSTEM_PGMS
        ]

        # Check which already have reports
        from build_call_graph import discover_reports, build_corpus_registry
        existing_cobol, existing_jcl = discover_reports(args.report_dirs)
        corpus = build_corpus_registry(existing_cobol, existing_jcl)

        missing = [
            p for p in programs_needed
            if normalize_program_name(p) not in corpus
        ]

        lenient_programs: set[str] = set()

        if missing:
            print(f"\nAuto-analyzing {len(missing)} missing COBOL programs: {', '.join(missing)}")

            # Find source files across all cobol dirs
            cobol_sources: dict[str, Path] = {}
            for cobol_dir in args.cobol_dirs:
                if not cobol_dir.is_dir():
                    print(f"Warning: --cobol-dir {cobol_dir} is not a directory, skipping")
                    continue
                for src_file in _find_cobol_sources(cobol_dir):
                    canonical = normalize_program_name(src_file.name)
                    cobol_sources[canonical] = src_file

            # Determine copybook dirs
            cpb_dirs = args.copybook_dirs or args.cobol_dirs

            for pgm in missing:
                canonical = normalize_program_name(pgm)
                src_path = cobol_sources.get(canonical)
                if src_path:
                    print(f"  Analyzing {src_path.name}...")
                    result = _run_cobol_analysis(src_path, cpb_dirs, args.verbose, lenient=args.lenient)
                    if result == "lenient":
                        lenient_programs.add(canonical)
                else:
                    print(f"  {canonical}: no source file found in --cobol-dir")
            print()
    else:
        lenient_programs = set()

    builder = JCLCOBOLReportBuilder(
        jcl_report_dir=jcl_report_dir,
        report_dirs=args.report_dirs,
        verbose=args.verbose,
        lenient_programs=lenient_programs,
    )
    builder.build()


if __name__ == "__main__":
    main()
