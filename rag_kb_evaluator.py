#!/usr/bin/env python3
"""
Percentage-based evaluator for knowledge-base and RAG chunk outputs.

The evaluator is read-only with respect to report directories: it only reads
artifacts under out/report and writes its own summary files at the requested
output paths.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import heapq
import json
import math
import re
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - project normally depends on PyYAML
    yaml = None

try:
    import tiktoken as _tiktoken

    _BPE_ENCODING = _tiktoken.get_encoding("cl100k_base")
except ImportError:  # pragma: no cover - tests exercise whitespace fallback
    _BPE_ENCODING = None


MAX_TOKENS_DEFAULT = 512
MIN_TOKENS_DEFAULT = 20

STAGES = (
    "source_to_artifact",
    "artifact_to_knowledge_base",
    "knowledge_base_to_chunks",
    "chunk_metadata",
    "retrieval_at_5",
)

FIELD_FAMILIES = (
    "program_structure",
    "control_flow",
    "data",
    "copybooks",
    "external_calls",
    "cics",
    "db2_sql",
    "vsam_file_io",
    "jcl",
    "comments",
    "chunks",
)

SEMANTIC_DEFECT_FIELDS = frozenset({
    "program_structure",
    "control_flow",
    "control_flow.composite",
    "control_flow.legacy_verbatim",
    "data",
    "copybooks",
    "external_calls",
    "cics",
    "db2_sql",
    "vsam_file_io",
    "jcl",
    "comments",
})

CONTROL_FLOW_TYPES = {
    "PERFORM",
    "GOTO",
    "GO_TO",
    "EVALUATE",
    "EVALUATE_BRANCH",
    "IF",
    "IF_BRANCH",
    "SEARCH",
    "READ",
    "WRITE",
    "OPEN",
    "CLOSE",
    "REWRITE",
    "DELETE",
    "START",
    "RETURN",
    "STOP",
    "STOP_RUN",
    "GOBACK",
    "EXIT",
    "CONTINUE",
}

DOCUMENTED_TYPE_MARKERS = {
    "GOTO": ("**GO TO**", "GO TO"),
    "GO_TO": ("**GO TO**", "GO TO"),
    "PERFORM": ("**PERFORM**", "PERFORM"),
    "EVALUATE": ("EVALUATE Block", "### EVALUATE"),
    "EVALUATE_BRANCH": ("**WHEN**", "WHEN"),
    "IF": ("Decision Point", "**Condition:**"),
    "IF_BRANCH": ("Decision Point", "**Condition:**"),
    "SEARCH": ("SEARCH",),
    "DIALECT": ("**CICS:**", "EXEC CICS", "CICS"),
    "EXEC_CICS": ("**CICS:**", "EXEC CICS", "CICS"),
    "EXEC_SQL": ("**SQL:**", "EXEC SQL", "SQL"),
    "READ": ("READ",),
    "WRITE": ("WRITE",),
    "OPEN": ("OPEN",),
    "CLOSE": ("CLOSE",),
    "REWRITE": ("REWRITE",),
    "DELETE": ("DELETE",),
    "START": ("START",),
    "RETURN": ("RETURN",),
    "STOP": ("**STOP RUN**", "STOP"),
    "STOP_RUN": ("**STOP RUN**", "STOP RUN"),
    "GOBACK": ("GOBACK",),
    "EXIT": ("EXIT",),
}

BRANCH_CONTROL_TYPES = frozenset({
    "IF",
    "IF_BRANCH",
    "EVALUATE",
    "EVALUATE_BRANCH",
    "SEARCH",
})

FILE_IO_TYPES = {
    "OPEN",
    "READ",
    "WRITE",
    "REWRITE",
    "DELETE",
    "START",
    "CLOSE",
    "RETURN",
}


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def load_yaml(path: Path) -> Any:
    if yaml is None or not path.exists():
        return None
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def token_count(text: str) -> int:
    if _BPE_ENCODING is not None:
        return len(_BPE_ENCODING.encode(text))
    return len(text.split())


def normalize_fact(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\s+", " ", text)
    return text.upper()


def safe_fact(prefix: str, value: Any) -> str | None:
    text = normalize_fact(value)
    if not text:
        return None
    return f"{prefix}:{text}"


def fact_value(fact: str) -> str:
    return fact.split(":", 1)[1] if ":" in fact else fact


def contains_fact(text: str, fact: str) -> bool:
    value = re.escape(fact_value(fact))
    if not value:
        return False
    return re.search(rf"(?<![A-Z0-9_-]){value}(?![A-Z0-9_-])", text.upper()) is not None


def flatten_strings(value: Any) -> str:
    parts: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, val in node.items():
                parts.append(str(key))
                walk(val)
        elif isinstance(node, list):
            for item in node:
                walk(item)
        elif node is not None:
            parts.append(str(node))

    walk(value)
    return "\n".join(parts).upper()


def pct(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round((numerator / denominator) * 100, 2)


def confidence(percentage: float | None) -> str:
    if percentage is None:
        return "not_measurable"
    if percentage >= 95:
        return "high"
    if percentage >= 75:
        return "medium"
    return "low"


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    index = (len(ordered) - 1) * p
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[int(index)]
    weight = index - lower
    return round(ordered[lower] * (1 - weight) + ordered[upper] * weight, 2)


@dataclass
class Metric:
    field: str
    stage: str
    numerator: int
    denominator: int
    percentage: float | None
    confidence: str
    note: str = ""
    status: str = "measured"

    @classmethod
    def from_counts(cls, field: str, stage: str, numerator: int,
                    denominator: int, note: str = "") -> "Metric":
        percentage = pct(numerator, denominator)
        return cls(
            field=field,
            stage=stage,
            numerator=numerator,
            denominator=denominator,
            percentage=percentage,
            confidence=confidence(percentage),
            note=note,
        )

    @classmethod
    def from_percentage(cls, field: str, stage: str, percentage: float,
                        note: str = "") -> "Metric":
        bounded = max(0.0, min(100.0, percentage))
        rounded = round(bounded, 2)
        return cls(
            field=field,
            stage=stage,
            numerator=int(round(rounded * 100)),
            denominator=10000,
            percentage=rounded,
            confidence=confidence(rounded),
            note=note,
        )

    @classmethod
    def not_applicable(cls, field: str, stage: str, note: str) -> "Metric":
        return cls(field, stage, 0, 0, None, "not_measurable", note, "not_applicable")


@dataclass
class RetrievalResult:
    category: str
    query: str
    expected: str
    top_1_hit: bool
    top_5_hit: bool
    reciprocal_rank: float


@dataclass
class ProgramEvaluation:
    program: str
    report_dir: str
    mode: str
    metrics: list[Metric] = field(default_factory=list)
    retrieval: list[RetrievalResult] = field(default_factory=list)
    chunk_quality: dict[str, Any] = field(default_factory=dict)
    artifact_inventory: dict[str, bool] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)
    unevaluable_reason: str | None = None
    control_flow_scores: dict[str, Any] = field(default_factory=dict)


class ReportFacts:
    def __init__(self) -> None:
        self.source: dict[str, set[str]] = {family: set() for family in FIELD_FAMILIES}
        self.artifact: dict[str, set[str]] = {family: set() for family in FIELD_FAMILIES}
        self.kb: dict[str, set[str]] = {family: set() for family in FIELD_FAMILIES}
        self.chunk_text: dict[str, set[str]] = {family: set() for family in FIELD_FAMILIES}
        self.chunk_metadata: dict[str, set[str]] = {family: set() for family in FIELD_FAMILIES}


class RagKbEvaluator:
    def __init__(self, report_root: Path, source_roots: list[Path] | None = None,
                 max_tokens: int = MAX_TOKENS_DEFAULT,
                 min_tokens: int = MIN_TOKENS_DEFAULT,
                 retrieval_limit_per_category: int = 5) -> None:
        self.report_root = report_root
        self.source_roots = source_roots or []
        self.max_tokens = max_tokens
        self.min_tokens = min_tokens
        self.retrieval_limit_per_category = retrieval_limit_per_category

    def evaluate(self) -> dict[str, Any]:
        programs = [
            self.evaluate_report(report_dir)
            for report_dir in sorted(self.report_root.glob("*.report"))
            if report_dir.is_dir()
        ]
        return self._build_corpus_result(programs)

    def evaluate_report(self, report_dir: Path) -> ProgramEvaluation:
        program = report_dir.name.removesuffix(".report")
        mode = self._detect_mode(report_dir)
        facts = ReportFacts()
        chunks = self._load_chunks(report_dir)
        kb_text = self._load_kb_text(report_dir)
        narrative_text = read_text(report_dir / "knowledge_base" / "01_Logic_Narrative.md")
        chunk_text = "\n".join(chunk["text"] for chunk in chunks)
        chunk_meta_text = "\n".join(flatten_strings(chunk.get("metadata", {})) for chunk in chunks)

        cfg = self._load_cfg(report_dir)
        data = self._load_data(report_dir)
        structure = load_json(report_dir / "cobol_structure.json") or {}
        health = load_json(report_dir / "analysis_health.json") or {}
        copybook_manifest = load_json(report_dir / "copybook_manifest.json") or {}
        deps = load_yaml(report_dir / "knowledge_base" / "03_Dependencies.yaml") or {}
        comments = load_json(report_dir / "comments.json") or {}
        enriched_comments = load_json(report_dir / "comments_enriched.json") or {}
        jcl_summary = load_json(report_dir / "jcl_summary.json") or {}
        jcl_steps = load_json(report_dir / "jcl_steps.json") or []
        jcl_datasets = load_json(report_dir / "jcl_datasets.json") or []
        source_text = self._load_source_text(program)

        evaluation = ProgramEvaluation(
            program=program,
            report_dir=str(report_dir),
            mode=mode,
            artifact_inventory=self._inventory(report_dir),
            counts=self._counts(cfg, data, structure, chunks),
            chunk_quality=self._chunk_quality(chunks),
        )
        if health.get("base_analysis_succeeded") is False:
            evaluation.unevaluable_reason = "base_analysis_failed"
            evaluation.metrics.extend(self._chunk_quality_metrics(evaluation.chunk_quality))
            return evaluation

        self._collect_source_facts(facts, source_text, structure, comments)
        self._collect_artifact_facts(
            facts, cfg, data, structure, copybook_manifest, deps, comments,
            enriched_comments, jcl_summary, jcl_steps, jcl_datasets,
        )
        self._project_text_facts(facts, facts.artifact, kb_text, facts.kb)
        self._project_text_facts(facts, self._preferred_chunk_denominators(facts), chunk_text, facts.chunk_text)
        self._project_text_facts(facts, facts.artifact, chunk_meta_text, facts.chunk_metadata)
        self._collect_chunk_field_facts(facts, chunks)

        evaluation.metrics.extend(self._stage_metrics(facts, mode))
        control_flow_metrics, control_flow_scores = self._control_flow_metrics(cfg, narrative_text, facts)
        evaluation.metrics.extend(control_flow_metrics)
        evaluation.control_flow_scores = control_flow_scores
        evaluation.metrics.extend(self._chunk_quality_metrics(evaluation.chunk_quality))
        evaluation.retrieval = self._run_retrieval(facts, chunks, program)
        evaluation.metrics.extend(self._retrieval_metrics(evaluation.retrieval))
        return evaluation

    def _detect_mode(self, report_dir: Path) -> str:
        is_cobol = (report_dir / "cfg").exists() or bool(list(report_dir.glob("cfg/cfg-*.json")))
        is_jcl = (report_dir / "jcl_summary.json").exists()
        if is_cobol and is_jcl:
            return "COBOL+JCL"
        if is_cobol:
            return "COBOL"
        if is_jcl:
            return "JCL"
        return "UNKNOWN"

    def _inventory(self, report_dir: Path) -> dict[str, bool]:
        return {
            "cfg": bool(list(report_dir.glob("cfg/cfg-*.json"))),
            "flow_ast": bool(list(report_dir.glob("flow_ast/*.json"))),
            "data_structures": bool(list(report_dir.glob("data_structures/*-data.json"))),
            "analysis_health": (report_dir / "analysis_health.json").exists(),
            "analysis_self_evaluation": (report_dir / "analysis_self_evaluation.json").exists(),
            "parse_diagnostics": (report_dir / "parse_diagnostics.json").exists(),
            "copybook_manifest": (report_dir / "copybook_manifest.json").exists(),
            "cobol_structure": (report_dir / "cobol_structure.json").exists(),
            "knowledge_base": (report_dir / "knowledge_base").exists(),
            "chunks_manifest": (report_dir / "chunks" / "chunks_manifest.json").exists(),
            "jcl_summary": (report_dir / "jcl_summary.json").exists(),
        }

    def _counts(self, cfg: dict, data: dict, structure: dict,
                chunks: list[dict]) -> dict[str, int]:
        nodes = cfg.get("nodes", []) if isinstance(cfg, dict) else []
        edges = cfg.get("edges", []) if isinstance(cfg, dict) else []
        return {
            "cfg_nodes": len(nodes),
            "cfg_edges": len(edges),
            "data_items": len(self._flatten_data_items(data)),
            "paragraph_profiles": len(structure.get("paragraph_profiles", {}) or {}),
            "copy_statements": len(structure.get("copy_statements", []) or []),
            "chunks": len(chunks),
        }

    def _load_cfg(self, report_dir: Path) -> dict:
        for path in report_dir.glob("cfg/cfg-*.json"):
            return load_json(path) or {}
        return {}

    def _load_data(self, report_dir: Path) -> dict:
        for path in report_dir.glob("data_structures/*-data.json"):
            return load_json(path) or {}
        return {}

    def _load_kb_text(self, report_dir: Path) -> str:
        kb_dir = report_dir / "knowledge_base"
        if not kb_dir.exists():
            return ""
        parts = []
        for path in sorted(kb_dir.glob("*")):
            if path.is_file() and path.suffix.lower() in {".md", ".yaml", ".yml", ".json", ".txt"}:
                parts.append(read_text(path))
        return "\n".join(parts)

    def _load_chunks(self, report_dir: Path) -> list[dict]:
        chunks_dir = report_dir / "chunks"
        chunks: list[dict] = []
        if not chunks_dir.exists():
            return chunks
        manifest_counts: dict[str, int] = {}
        manifest = load_json(chunks_dir / "chunks_manifest.json")
        if isinstance(manifest, dict):
            for entry in manifest.get("chunks", []) or []:
                file_name = entry.get("file")
                count = entry.get("token_count_bpe")
                if file_name and isinstance(count, int):
                    manifest_counts[file_name] = count
        for path in sorted(chunks_dir.glob("*.json")):
            if path.name in {"chunks_manifest.json", "bm25_index.json"}:
                continue
            data = load_json(path)
            if not isinstance(data, dict):
                continue
            if "text" not in data or "metadata" not in data:
                continue
            data["_file"] = path.name
            if path.name in manifest_counts:
                data["_token_count"] = manifest_counts[path.name]
            chunks.append(data)
        return chunks

    def _load_source_text(self, program: str) -> str:
        candidates = []
        for root in self.source_roots:
            candidates.extend(root.rglob(program))
            candidates.extend(root.rglob(Path(program).stem + ".*"))
        for candidate in candidates:
            if candidate.is_file() and candidate.suffix.lower() in {".cbl", ".cob", ".cpy", ".jcl"}:
                return read_text(candidate)
        return ""

    def _collect_source_facts(self, facts: ReportFacts, source_text: str,
                              structure: dict, comments: dict) -> None:
        if source_text:
            self._collect_raw_cobol_source_facts(facts, source_text)

        for div in (structure.get("divisions") or {}).keys():
            self._add(facts.source, "program_structure", "DIVISION", div)
        for section in (structure.get("sections") or {}).keys():
            self._add(facts.source, "program_structure", "SECTION", section)
        for paragraph in (structure.get("paragraph_profiles") or {}).keys():
            self._add(facts.source, "program_structure", "PARAGRAPH", paragraph)
        for cp in structure.get("copy_statements", []) or []:
            self._add(facts.source, "copybooks", "COPY", cp.get("copybook"))
        for name in comments.keys():
            if name != "_PROGRAM_SUMMARY":
                self._add(facts.source, "comments", "COMMENT", name)

    def _collect_raw_cobol_source_facts(self, facts: ReportFacts, text: str) -> None:
        in_procedure = False
        for raw in text.splitlines():
            line = raw[6:72] if len(raw) > 6 else raw
            upper = line.upper()
            if re.search(r"\bPROCEDURE\s+DIVISION\b", upper):
                in_procedure = True
            for div in re.findall(r"\b(IDENTIFICATION|ENVIRONMENT|DATA|PROCEDURE)\s+DIVISION\b", upper):
                self._add(facts.source, "program_structure", "DIVISION", div)
            for section in re.findall(r"\b([A-Z][A-Z0-9_-]*)\s+SECTION\b", upper):
                self._add(facts.source, "program_structure", "SECTION", section)
            if in_procedure:
                m = re.match(r"\s*([A-Z][A-Z0-9_-]+)\.\s*$", upper)
                if m:
                    self._add(facts.source, "program_structure", "PARAGRAPH", m.group(1))
            for cp in re.findall(r"\bCOPY\s+([A-Z0-9_-]+)", upper):
                self._add(facts.source, "copybooks", "COPY", cp)
            for sel in re.findall(r"\bSELECT\s+([A-Z0-9_-]+)", upper):
                self._add(facts.source, "vsam_file_io", "SELECT", sel)
            for assign in re.findall(r"\bASSIGN\s+TO\s+([A-Z0-9_.-]+)", upper):
                self._add(facts.source, "vsam_file_io", "ASSIGN", assign)
            for op in FILE_IO_TYPES:
                if re.search(rf"\b{op}\b", upper):
                    self._add(facts.source, "vsam_file_io", "FILE_OP", op)
            if "EXEC CICS" in upper:
                cmd = self._extract_cics_command(upper)
                self._add(facts.source, "cics", "CICS", cmd)
            if "EXEC SQL" in upper:
                op = self._extract_sql_operation(upper)
                self._add(facts.source, "db2_sql", "SQL", op)

    def _collect_artifact_facts(
        self,
        facts: ReportFacts,
        cfg: dict,
        data: dict,
        structure: dict,
        copybook_manifest: dict,
        deps: dict,
        comments: dict,
        enriched_comments: dict,
        jcl_summary: dict,
        jcl_steps: list,
        jcl_datasets: list,
    ) -> None:
        for div in (structure.get("divisions") or {}).keys():
            self._add(facts.artifact, "program_structure", "DIVISION", div)
        for section in (structure.get("sections") or {}).keys():
            self._add(facts.artifact, "program_structure", "SECTION", section)

        nodes = cfg.get("nodes", []) if isinstance(cfg, dict) else []
        for node in nodes:
            ntype = normalize_fact(node.get("type"))
            name = node.get("name") or node.get("label") or node.get("originalText")
            original = node.get("originalText") or ""
            meta = node.get("metadata") or {}
            if ntype in {"PARAGRAPH", "SECTION"}:
                self._add(facts.artifact, "program_structure", ntype, name)
            if ntype in CONTROL_FLOW_TYPES:
                self._add(facts.artifact, "control_flow", ntype, name or original or ntype)
            if "CALL_TARGET" in meta:
                self._add(facts.artifact, "external_calls", "CALL", meta.get("call_target"))
            if "EXEC CICS" in original.upper() or ntype in {"EXEC_CICS", "DIALECT"}:
                cmd = meta.get("cics_command") or self._extract_cics_command(original)
                self._add(facts.artifact, "cics", "CICS", cmd)
                target = meta.get("cics_target_program") or self._extract_cics_target(original)
                self._add(facts.artifact, "cics", "CICS_TARGET", target)
                for binding in meta.get("handler_bindings", []) or []:
                    self._add(facts.artifact, "cics", "HANDLE", binding.get("target"))
            if "EXEC SQL" in original.upper() or ntype == "EXEC_SQL":
                op = meta.get("sql_operation") or self._extract_sql_operation(original)
                self._add(facts.artifact, "db2_sql", "SQL", op)
                for table in self._extract_sql_tables(original):
                    self._add(facts.artifact, "db2_sql", "TABLE", table)
            if ntype in FILE_IO_TYPES:
                self._add(facts.artifact, "vsam_file_io", "FILE_OP", ntype)

        for item in self._flatten_data_items(data):
            name = item.get("name")
            if name:
                self._add(facts.artifact, "data", "DATA", name)
            if item.get("pictureClause") or self._extract_pic(item.get("raw", "")):
                self._add(facts.artifact, "data", "PIC", name)
            section = normalize_fact(item.get("sourceSection") or item.get("section"))
            if section in {"FILE", "FILE_DESCRIPTOR"}:
                self._add(facts.artifact, "vsam_file_io", "FD_RECORD", name)
        for condition in (structure.get("conditions_88") or {}).keys():
            self._add(facts.artifact, "data", "88", condition)
        for redef in structure.get("redefines", []) or []:
            self._add(facts.artifact, "data", "REDEFINES", redef.get("redefining"))

        self._collect_copybook_artifacts(facts, copybook_manifest, structure)
        self._collect_dependency_artifacts(facts, deps)
        self._collect_comment_artifacts(facts, comments, enriched_comments)
        self._collect_jcl_artifacts(facts, jcl_summary, jcl_steps, jcl_datasets)

    def _collect_copybook_artifacts(self, facts: ReportFacts, manifest: dict,
                                    structure: dict) -> None:
        for cp in structure.get("copy_statements", []) or []:
            self._add(facts.artifact, "copybooks", "COPY", cp.get("copybook"))
        copybooks = manifest.get("copybooks") or {}
        if isinstance(copybooks, dict):
            items = copybooks.items()
        else:
            items = ((entry.get("name") or entry.get("copybook"), entry) for entry in copybooks)
        for name, info in items:
            if not name:
                continue
            self._add(facts.artifact, "copybooks", "COPY", name)
            if isinstance(info, dict):
                status = "STUBBED_COPYBOOK" if info.get("is_stub") or info.get("status") == "stubbed" else "RESOLVED_COPYBOOK"
                self._add(facts.artifact, "copybooks", status, name)
        for name, info in (structure.get("known_system_copybooks") or {}).items():
            self._add(facts.artifact, "copybooks", "SYSTEM_COPYBOOK", name)
            if isinstance(info, dict):
                self._add(facts.artifact, "copybooks", "SYSTEM", info.get("system"))

    def _collect_dependency_artifacts(self, facts: ReportFacts, deps: dict) -> None:
        if not isinstance(deps, dict):
            return
        db = deps.get("database") or {}
        for table in db.get("tables_read", []) or []:
            self._add(facts.artifact, "db2_sql", "TABLE_READ", table)
        for table in db.get("tables_updated", []) or []:
            self._add(facts.artifact, "db2_sql", "TABLE_UPDATED", table)
        for op in db.get("sql_statements", []) or []:
            self._add(facts.artifact, "db2_sql", "SQL", op)
        if db.get("dynamic_sql"):
            self._add(facts.artifact, "db2_sql", "DYNAMIC_SQL", "true")
        for call in deps.get("calls", []) or []:
            self._add(facts.artifact, "external_calls", "CALL", call.get("target"))
            for using in call.get("using", []) or []:
                self._add(facts.artifact, "external_calls", "USING", using)
        for cmd in deps.get("cics", []) or []:
            self._add(facts.artifact, "cics", "CICS", cmd)
        for cics_call in deps.get("cics_calls", []) or []:
            self._add(facts.artifact, "cics", "CICS_TARGET", cics_call.get("target"))
            self._add(facts.artifact, "external_calls", "CICS_TARGET", cics_call.get("target"))

    def _collect_comment_artifacts(self, facts: ReportFacts, comments: dict,
                                   enriched: dict) -> None:
        for name in comments.keys():
            if name != "_PROGRAM_SUMMARY":
                self._add(facts.artifact, "comments", "COMMENT", name)
        for name, entry in enriched.items():
            if name == "_PROGRAM_SUMMARY":
                continue
            self._add(facts.artifact, "comments", "TRANSLATED_COMMENT", name)
            if isinstance(entry, dict) and entry.get("translation_failed"):
                self._add(facts.artifact, "comments", "FAILED_TRANSLATION", name)
            category = entry.get("category") if isinstance(entry, dict) else None
            self._add(facts.artifact, "comments", "COMMENT_CATEGORY", category)

    def _collect_jcl_artifacts(self, facts: ReportFacts, summary: dict,
                               steps: list, datasets: list) -> None:
        if summary:
            self._add(facts.artifact, "jcl", "JOB", summary.get("job_name") or summary.get("name"))
        for step in steps if isinstance(steps, list) else []:
            self._add(facts.artifact, "jcl", "STEP", step.get("name") or step.get("step_name"))
            self._add(facts.artifact, "jcl", "EXEC_PROGRAM", step.get("program") or step.get("pgm"))
            if step.get("condition") or step.get("cond"):
                self._add(facts.artifact, "jcl", "COND", step.get("name") or step.get("step_name"))
            for key in ("input_datasets", "output_datasets", "datasets_read", "datasets_written"):
                for ds in step.get(key, []) or []:
                    self._add(facts.artifact, "jcl", "DATASET", ds)
        for ds in datasets if isinstance(datasets, list) else []:
            if isinstance(ds, dict):
                self._add(facts.artifact, "jcl", "DATASET", ds.get("dsn") or ds.get("dataset"))
                self._add(facts.artifact, "jcl", "DATASET_FLOW", ds.get("flow_type") or ds.get("access"))
            else:
                self._add(facts.artifact, "jcl", "DATASET", ds)

    def _project_text_facts(self, facts: ReportFacts, source_sets: dict[str, set[str]],
                            text: str, target_sets: dict[str, set[str]]) -> None:
        for family in FIELD_FAMILIES:
            for fact in source_sets.get(family, set()):
                if contains_fact(text, fact):
                    target_sets[family].add(fact)

    def _preferred_chunk_denominators(self, facts: ReportFacts) -> dict[str, set[str]]:
        result = {}
        for family in FIELD_FAMILIES:
            result[family] = facts.kb[family] or facts.artifact[family]
        return result

    def _collect_chunk_field_facts(self, facts: ReportFacts, chunks: list[dict]) -> None:
        for chunk in chunks:
            meta = chunk.get("metadata", {})
            text = chunk.get("text", "")
            ctype = meta.get("chunk_type")
            self._add(facts.artifact, "chunks", "CHUNK_TYPE", ctype)
            self._add(facts.chunk_text, "chunks", "CHUNK_TYPE", ctype)
            self._add(facts.chunk_metadata, "chunks", "CHUNK_TYPE", ctype)
            tc = self._chunk_token_count(chunk)
            if tc > self.max_tokens:
                self._add(facts.artifact, "chunks", "OVERSIZED_CHUNK", chunk.get("_file"))
            if tc < self.min_tokens:
                self._add(facts.artifact, "chunks", "THIN_CHUNK", chunk.get("_file"))
            for field_name in ("content_hash", "chunk_id", "schema_version", "chunk_type", "program"):
                if meta.get(field_name):
                    self._add(facts.chunk_metadata, "chunks", "METADATA_FIELD", field_name)

    def _stage_metrics(self, facts: ReportFacts, mode: str) -> list[Metric]:
        metrics: list[Metric] = []
        for family in FIELD_FAMILIES:
            source = facts.source[family]
            artifact = facts.artifact[family]
            kb = facts.kb[family]
            chunk_text = facts.chunk_text[family]
            metadata = facts.chunk_metadata[family]
            metrics.append(Metric.from_counts(
                family, "source_to_artifact",
                len(source & artifact), len(source),
                "source denominator comes from raw source when discoverable, otherwise source-derived structure artifacts",
            ))
            if mode == "JCL" and family == "jcl":
                metrics.append(Metric.not_applicable(
                    "jcl",
                    "artifact_to_knowledge_base",
                    "JCL reports produce relationship artifacts and chunks, not knowledge_base/.",
                ))
            else:
                metrics.append(Metric.from_counts(
                    family, "artifact_to_knowledge_base",
                    len(artifact & kb), len(artifact),
                ))
            denom = kb or artifact
            metrics.append(Metric.from_counts(
                family, "knowledge_base_to_chunks",
                len(denom & chunk_text), len(denom),
            ))
            metrics.append(Metric.from_counts(
                family, "chunk_metadata",
                len(artifact & metadata), len(artifact),
            ))
        return metrics

    def _control_flow_metrics(self, cfg: dict, narrative_text: str,
                              facts: ReportFacts) -> tuple[list[Metric], dict[str, Any]]:
        nodes = cfg.get("nodes", []) if isinstance(cfg, dict) else []
        if not nodes:
            return [], {}

        scores = self._control_flow_scores(nodes, narrative_text)
        metrics = [
            Metric.from_percentage(
                "control_flow.composite",
                "artifact_to_knowledge_base",
                scores["composite_percentage"],
                "Weighted paragraph heading, statement marker, and branch marker coverage.",
            ),
            Metric.from_counts(
                "control_flow.legacy_verbatim",
                "artifact_to_knowledge_base",
                len(facts.artifact["control_flow"] & facts.kb["control_flow"]),
                len(facts.artifact["control_flow"]),
                "Legacy exact CFG-fact text match retained for one evaluator cycle.",
            ),
        ]
        return metrics, scores

    def _control_flow_scores(self, nodes: list[dict], narrative_text: str) -> dict[str, Any]:
        paragraph = self._paragraph_heading_coverage(nodes, narrative_text)
        statement = self._statement_type_coverage_from_cfg(nodes, narrative_text)
        branch = self._branch_marker_coverage(nodes, narrative_text)
        components = [
            (paragraph["percentage"], 0.50),
            (statement["percentage"], 0.40),
            (branch["percentage"], 0.10),
        ]
        measured = [(value, weight) for value, weight in components if value is not None]
        if measured:
            weight_total = sum(weight for _, weight in measured)
            composite = round(sum(value * weight for value, weight in measured) / weight_total, 2)
        else:
            composite = 0.0
        return {
            "composite_percentage": composite,
            "paragraph_coverage": paragraph,
            "statement_type_coverage": statement,
            "branch_marker_coverage": branch,
        }

    def _paragraph_heading_coverage(self, nodes: list[dict], narrative_text: str) -> dict[str, Any]:
        headings = set(re.findall(r"(?m)^#{2,6}\s+(.+?)\s*$", narrative_text.upper()))
        paragraphs = {
            normalize_fact(node.get("name") or node.get("label"))
            for node in nodes
            if normalize_fact(node.get("type")) == "PARAGRAPH"
        }
        covered = {name for name in paragraphs if name in headings}
        return {
            "covered": len(covered),
            "expected": len(paragraphs),
            "percentage": pct(len(covered), len(paragraphs)),
        }

    def _statement_type_coverage_from_cfg(self, nodes: list[dict],
                                          narrative_text: str) -> dict[str, Any]:
        narrative_upper = narrative_text.upper()
        present = {
            normalize_fact(node.get("type"))
            for node in nodes
            if normalize_fact(node.get("type")) in DOCUMENTED_TYPE_MARKERS
        }
        covered = {
            node_type
            for node_type in present
            if any(marker.upper() in narrative_upper for marker in DOCUMENTED_TYPE_MARKERS[node_type])
        }
        return {
            "covered": len(covered),
            "expected": len(present),
            "percentage": pct(len(covered), len(present)),
        }

    def _branch_marker_coverage(self, nodes: list[dict], narrative_text: str) -> dict[str, Any]:
        expected = sum(
            1 for node in nodes
            if normalize_fact(node.get("type")) in BRANCH_CONTROL_TYPES
        )
        markers = re.findall(
            r"(?im)^(?:#{2,6}\s+(?:Decision Point|EVALUATE Block|EVALUATE)\b|"
            r"\s*-\s+\*\*WHEN\*\*|\s*\*\*Condition:\*\*)",
            narrative_text,
        )
        covered = min(expected, len(markers))
        return {
            "covered": covered,
            "expected": expected,
            "percentage": pct(covered, expected),
        }

    def _chunk_quality(self, chunks: list[dict]) -> dict[str, Any]:
        token_counts = [self._chunk_token_count(chunk) for chunk in chunks]
        type_counts = Counter(chunk.get("metadata", {}).get("chunk_type", "unknown") for chunk in chunks)
        hashes = [chunk.get("metadata", {}).get("content_hash") for chunk in chunks]
        non_empty_hashes = [h for h in hashes if h]
        hash_counts = Counter(non_empty_hashes)
        duplicate_hashes = sum(count - 1 for count in hash_counts.values() if count > 1)
        missing_metadata = 0
        for chunk in chunks:
            meta = chunk.get("metadata", {})
            for key in ("schema_version", "chunk_type", "chunk_id", "content_hash", "program"):
                if not meta.get(key):
                    missing_metadata += 1
        return {
            "total_chunks": len(chunks),
            "chunk_type_counts": dict(type_counts),
            "token_min": min(token_counts) if token_counts else 0,
            "token_median": statistics.median(token_counts) if token_counts else 0,
            "token_p90": percentile([float(v) for v in token_counts], 0.90) or 0,
            "token_max": max(token_counts) if token_counts else 0,
            "thin_chunks": sum(1 for count in token_counts if count < self.min_tokens),
            "oversized_chunks": sum(1 for count in token_counts if count > self.max_tokens),
            "duplicate_content_hashes": duplicate_hashes,
            "within_report_duplicate_content_hashes": duplicate_hashes,
            "content_hash_counts": dict(hash_counts),
            "missing_required_metadata_fields": missing_metadata,
        }

    def _chunk_token_count(self, chunk: dict) -> int:
        cached = chunk.get("_token_count")
        if isinstance(cached, int):
            return cached
        return token_count(chunk.get("text", ""))

    def _chunk_quality_metrics(self, quality: dict[str, Any]) -> list[Metric]:
        total = int(quality.get("total_chunks", 0))
        if total == 0:
            return [
                Metric.from_counts("chunks", "chunk_existence", 0, 1, "no chunk files found"),
                Metric.from_counts("chunks", "bpe_size_compliance", 0, 0),
                Metric.from_counts("chunks", "minimum_context_compliance", 0, 0),
                Metric.from_counts("chunks", "metadata_completeness", 0, 0),
            ]
        return [
            Metric.from_counts("chunks", "chunk_existence", 1, 1),
            Metric.from_counts(
                "chunks", "bpe_size_compliance",
                total - int(quality.get("oversized_chunks", 0)), total,
            ),
            Metric.from_counts(
                "chunks", "minimum_context_compliance",
                total - int(quality.get("thin_chunks", 0)), total,
            ),
            Metric.from_counts(
                "chunks", "metadata_completeness",
                max(0, total * 5 - int(quality.get("missing_required_metadata_fields", 0))),
                total * 5,
            ),
        ]

    def _run_retrieval(self, facts: ReportFacts, chunks: list[dict],
                       program: str) -> list[RetrievalResult]:
        queries = self._build_queries(facts, program)
        chunk_index = self._prepare_chunk_index(chunks)
        results: list[RetrievalResult] = []
        for category, query, expected in queries:
            ranked = self._rank_chunks(query, chunk_index, category)
            reciprocal = 0.0
            top_1 = False
            top_5 = False
            for idx, chunk in enumerate(ranked[:5], 1):
                haystack = chunk.get("text", "") + "\n" + flatten_strings(chunk.get("metadata", {}))
                if contains_fact(haystack, expected):
                    if idx == 1:
                        top_1 = True
                    top_5 = True
                    reciprocal = 1 / idx
                    break
            results.append(RetrievalResult(category, query, expected, top_1, top_5, reciprocal))
        return results

    def _build_queries(self, facts: ReportFacts, program: str) -> list[tuple[str, str, str]]:
        candidates: list[tuple[str, str, str]] = []
        templates = {
            "external_calls": "Which external program does {program} call or transfer to: {value}?",
            "cics": "Which CICS command, handler, map, or target does {program} use: {value}?",
            "db2_sql": "Which DB2 SQL table or operation does {program} use: {value}?",
            "vsam_file_io": "Which VSAM or file I/O fact does {program} use: {value}?",
            "copybooks": "Which copybook or stub impact is present in {program}: {value}?",
            "jcl": "Which JCL step, program, dataset, or condition is present: {value}?",
            "data": "Which data field or record appears in {program}: {value}?",
            "program_structure": "Which section or paragraph appears in {program}: {value}?",
            "comments": "Which comment or translation category appears in {program}: {value}?",
        }
        for category, template in templates.items():
            values = sorted(facts.artifact[category])[:self.retrieval_limit_per_category]
            for expected in values:
                value = fact_value(expected)
                candidates.append((category, template.format(program=program, value=value), expected))
        return candidates

    def _prepare_chunk_index(self, chunks: list[dict]) -> dict[str, Any]:
        doc_terms = []
        document_frequency: Counter[str] = Counter()
        for chunk in chunks:
            text = chunk.get("text", "") + "\n" + flatten_strings(chunk.get("metadata", {}))
            terms = Counter(self._terms(text))
            doc_terms.append((chunk, terms))
            for term in terms:
                document_frequency[term] += 1
        return {
            "doc_terms": doc_terms,
            "document_frequency": document_frequency,
            "total_docs": max(1, len(chunks)),
        }

    def _rank_chunks(self, query: str, chunk_index: dict[str, Any],
                     category: str | None = None) -> list[dict]:
        q_terms = Counter(self._terms(query))
        if not q_terms:
            return [chunk for chunk, _ in chunk_index["doc_terms"]]
        doc_terms = chunk_index["doc_terms"]
        document_frequency = chunk_index["document_frequency"]
        total_docs = chunk_index["total_docs"]

        def score(item: tuple[dict, Counter[str]]) -> float:
            chunk, terms = item
            value = 0.0
            for term, q_count in q_terms.items():
                tf = terms.get(term, 0)
                if not tf:
                    continue
                idf = math.log((1 + total_docs) / (1 + document_frequency[term])) + 1
                value += q_count * tf * idf
            if category == "cics" and chunk.get("metadata", {}).get("chunk_type") == "cics_operations":
                value += 100.0
            return value

        top = heapq.nlargest(5, doc_terms, key=score)
        return [chunk for chunk, _ in top]

    def _retrieval_metrics(self, retrieval: list[RetrievalResult]) -> list[Metric]:
        by_category: dict[str, list[RetrievalResult]] = defaultdict(list)
        for result in retrieval:
            by_category[result.category].append(result)
        metrics: list[Metric] = []
        for family in FIELD_FAMILIES:
            results = by_category.get(family, [])
            top5_hits = sum(1 for result in results if result.top_5_hit)
            metrics.append(Metric.from_counts(family, "retrieval_at_5", top5_hits, len(results)))
        return metrics

    def _terms(self, text: str) -> list[str]:
        return [t.upper() for t in re.findall(r"[A-Za-z][A-Za-z0-9_-]{1,}", text)]

    def _add(self, bucket: dict[str, set[str]], family: str,
             prefix: str, value: Any) -> None:
        fact = safe_fact(prefix, value)
        if fact:
            bucket[family].add(fact)

    def _flatten_data_items(self, data: Any) -> list[dict]:
        items: list[dict] = []

        def walk(node: Any) -> None:
            if isinstance(node, dict):
                if node.get("name") and (node.get("levelNumber") or node.get("level")):
                    items.append(node)
                for key in ("children", "structures", "conditions"):
                    for child in node.get(key, []) or []:
                        walk(child)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(data)
        return items

    def _extract_pic(self, raw: str) -> str | None:
        match = re.search(r"\bPIC(?:TURE)?\s+([A-Z0-9()VXS9+-]+)", raw or "", re.IGNORECASE)
        return match.group(1) if match else None

    def _extract_cics_command(self, text: str) -> str | None:
        match = re.search(r"EXEC\s+CICS\s+([A-Z]+)", text or "", re.IGNORECASE)
        return match.group(1).upper() if match else None

    def _extract_cics_target(self, text: str) -> str | None:
        match = re.search(r"\bPROGRAM\s*\(\s*['\"]?([A-Z0-9_-]+)['\"]?\s*\)", text or "", re.IGNORECASE)
        return match.group(1).upper() if match else None

    def _extract_sql_operation(self, text: str) -> str | None:
        match = re.search(r"EXEC\s+SQL\s+([A-Z]+)", text or "", re.IGNORECASE)
        return match.group(1).upper() if match else None

    def _extract_sql_tables(self, text: str) -> set[str]:
        tables = set()
        for match in re.finditer(r"\b(?:FROM|JOIN|UPDATE|INTO|TABLE)\s+([A-Z][A-Z0-9_.-]+)", text or "", re.IGNORECASE):
            token = match.group(1).upper().strip(".")
            if token not in {"SELECT", "VALUES", "SET"}:
                tables.add(token)
        return tables

    def _build_corpus_result(self, programs: list[ProgramEvaluation]) -> dict[str, Any]:
        program_dicts = [self._program_to_dict(program) for program in programs]
        metrics = [metric for program in programs for metric in program.metrics]
        retrieval = [result for program in programs for result in program.retrieval]
        corpus = {
            "report_root": str(self.report_root),
            "program_count": len(programs),
            "mode_counts": dict(Counter(program.mode for program in programs)),
            "artifact_inventory": self._aggregate_inventory(programs),
            "stage_summary": self._aggregate_metrics(metrics),
            "retrieval_summary": self._aggregate_retrieval(retrieval),
            "chunk_quality": self._aggregate_chunk_quality(programs),
            "top_defects": self._top_defects(programs),
            "chunk_quality_defects": self._chunk_quality_defects(programs),
            "unevaluable_programs": self._unevaluable_programs(programs),
        }
        return {"corpus": corpus, "programs": program_dicts}

    def _program_to_dict(self, program: ProgramEvaluation) -> dict[str, Any]:
        return {
            "program": program.program,
            "report_dir": program.report_dir,
            "mode": program.mode,
            "artifact_inventory": program.artifact_inventory,
            "counts": program.counts,
            "chunk_quality": program.chunk_quality,
            "unevaluable_reason": program.unevaluable_reason,
            "control_flow_scores": program.control_flow_scores,
            "metrics": [metric.__dict__ for metric in program.metrics],
            "retrieval": [result.__dict__ for result in program.retrieval],
        }

    def _aggregate_inventory(self, programs: list[ProgramEvaluation]) -> dict[str, dict[str, Any]]:
        keys = sorted({key for program in programs for key in program.artifact_inventory})
        total = len(programs)
        result = {}
        for key in keys:
            present = sum(1 for program in programs if program.artifact_inventory.get(key))
            result[key] = {
                "present": present,
                "total": total,
                "percentage": pct(present, total),
                "confidence": confidence(pct(present, total)),
            }
        return result

    def _aggregate_metrics(self, metrics: list[Metric]) -> dict[str, Any]:
        grouped: dict[tuple[str, str], list[Metric]] = defaultdict(list)
        for metric in metrics:
            grouped[(metric.field, metric.stage)].append(metric)
        summary = {}
        for (field, stage), group in sorted(grouped.items()):
            applicable = [m for m in group if m.status != "not_applicable"]
            percentages = [m.percentage for m in applicable if m.percentage is not None]
            numerator = sum(m.numerator for m in applicable)
            denominator = sum(m.denominator for m in applicable)
            key = f"{field}:{stage}"
            percentage = pct(numerator, denominator)
            has_not_applicable = any(m.status == "not_applicable" for m in group)
            status = "not_applicable" if has_not_applicable and denominator == 0 else "measured"
            summary[key] = {
                "field": field,
                "stage": stage,
                "numerator": numerator,
                "denominator": denominator,
                "percentage": percentage,
                "mean_percentage": round(statistics.mean(percentages), 2) if percentages else None,
                "p10": percentile(percentages, 0.10),
                "p50": percentile(percentages, 0.50),
                "p90": percentile(percentages, 0.90),
                "confidence": confidence(percentage),
                "status": status,
                "not_applicable_programs": sum(1 for m in group if m.status == "not_applicable"),
                "programs_measured": len(percentages),
            }
        return summary

    def _aggregate_retrieval(self, retrieval: list[RetrievalResult]) -> dict[str, Any]:
        by_category: dict[str, list[RetrievalResult]] = defaultdict(list)
        for result in retrieval:
            by_category[result.category].append(result)
        summary = {}
        for category, results in sorted(by_category.items()):
            total = len(results)
            top1 = sum(1 for result in results if result.top_1_hit)
            top5 = sum(1 for result in results if result.top_5_hit)
            mrr = round(statistics.mean([result.reciprocal_rank for result in results]), 4) if results else None
            summary[category] = {
                "queries": total,
                "recall_at_1": pct(top1, total),
                "recall_at_5": pct(top5, total),
                "mrr": mrr,
                "answerable_query_percentage": pct(top5, total),
            }
        return summary

    def _aggregate_chunk_quality(self, programs: list[ProgramEvaluation]) -> dict[str, Any]:
        total_chunks = sum(p.chunk_quality.get("total_chunks", 0) for p in programs)
        oversized = sum(p.chunk_quality.get("oversized_chunks", 0) for p in programs)
        thin = sum(p.chunk_quality.get("thin_chunks", 0) for p in programs)
        missing_meta = sum(p.chunk_quality.get("missing_required_metadata_fields", 0) for p in programs)
        within_duplicate_hashes = sum(
            p.chunk_quality.get("within_report_duplicate_content_hashes",
                                p.chunk_quality.get("duplicate_content_hashes", 0))
            for p in programs
        )
        global_hash_counts: Counter[str] = Counter()
        type_counts: Counter[str] = Counter()
        max_tokens = 0
        for program in programs:
            type_counts.update(program.chunk_quality.get("chunk_type_counts", {}))
            global_hash_counts.update(program.chunk_quality.get("content_hash_counts", {}))
            max_tokens = max(max_tokens, int(program.chunk_quality.get("token_max", 0)))
        global_duplicate_hashes = sum(
            count - 1 for count in global_hash_counts.values() if count > 1
        )
        return {
            "total_chunks": total_chunks,
            "type_counts": dict(type_counts),
            "oversized_chunks": oversized,
            "oversized_percentage": pct(oversized, total_chunks),
            "thin_chunks": thin,
            "thin_percentage": pct(thin, total_chunks),
            "missing_required_metadata_fields": missing_meta,
            "duplicate_content_hashes": within_duplicate_hashes,
            "within_report_duplicate_content_hashes": within_duplicate_hashes,
            "global_duplicate_content_hashes": global_duplicate_hashes,
            "max_token_count": max_tokens,
        }

    def _top_defects(self, programs: list[ProgramEvaluation]) -> list[dict[str, Any]]:
        defects = []
        for program in programs:
            for metric in program.metrics:
                if metric.field not in SEMANTIC_DEFECT_FIELDS:
                    continue
                if metric.status == "not_applicable":
                    continue
                if metric.denominator <= 0 or metric.percentage is None:
                    continue
                loss = metric.denominator - metric.numerator
                if loss <= 0:
                    continue
                defects.append({
                    "program": program.program,
                    "field": metric.field,
                    "stage": metric.stage,
                    "lost_facts": loss,
                    "denominator": metric.denominator,
                    "percentage": metric.percentage,
                    "impact_score": round(loss * (100 - metric.percentage), 2),
                })
        return sorted(defects, key=lambda d: d["impact_score"], reverse=True)[:30]

    def _chunk_quality_defects(self, programs: list[ProgramEvaluation]) -> list[dict[str, Any]]:
        defects = []
        for program in programs:
            quality = program.chunk_quality
            total = int(quality.get("total_chunks", 0))
            for key in ("oversized_chunks", "thin_chunks", "duplicate_content_hashes"):
                count = int(quality.get(key, 0))
                if count <= 0:
                    continue
                defects.append({
                    "program": program.program,
                    "defect": key,
                    "count": count,
                    "total_chunks": total,
                    "percentage": pct(count, total),
                })
        return sorted(defects, key=lambda d: d["count"], reverse=True)[:30]

    def _unevaluable_programs(self, programs: list[ProgramEvaluation]) -> list[dict[str, Any]]:
        return [
            {
                "program": program.program,
                "report_dir": program.report_dir,
                "mode": program.mode,
                "reason": program.unevaluable_reason,
                "artifact_inventory": program.artifact_inventory,
                "chunk_quality": program.chunk_quality,
            }
            for program in programs
            if program.unevaluable_reason
        ]


def write_outputs(result: dict[str, Any], output_json: Path,
                  output_report: Path, output_csv: Path | None) -> None:
    output_json.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    output_report.write_text(render_markdown(result), encoding="utf-8")
    if output_csv:
        write_csv(result, output_csv)


def render_markdown(result: dict[str, Any]) -> str:
    corpus = result["corpus"]
    lines = [
        "# RAG Knowledge-Base Percentage Evaluation",
        "",
        "## Corpus Summary",
        "",
        f"- Report root: `{corpus['report_root']}`",
        f"- Programs/jobs evaluated: {corpus['program_count']}",
        f"- Mode counts: {corpus['mode_counts']}",
        f"- Unevaluable programs: {len(corpus.get('unevaluable_programs', []))}",
        "",
        "## Artifact Availability",
        "",
        "| Artifact | Present | Total | Percentage | Confidence |",
        "|---|---:|---:|---:|---|",
    ]
    for name, row in sorted(corpus["artifact_inventory"].items()):
        lines.append(
            f"| {name} | {row['present']} | {row['total']} | "
            f"{fmt_pct(row['percentage'])} | {row['confidence']} |"
        )

    if corpus.get("unevaluable_programs"):
        lines.extend([
            "",
            "## Unevaluable Programs",
            "",
            "| Program | Mode | Reason | Chunks | Oversized | Thin |",
            "|---|---|---|---:|---:|---:|",
        ])
        for program in corpus["unevaluable_programs"]:
            quality = program["chunk_quality"]
            lines.append(
                f"| {program['program']} | {program['mode']} | {program['reason']} | "
                f"{quality.get('total_chunks', 0)} | {quality.get('oversized_chunks', 0)} | "
                f"{quality.get('thin_chunks', 0)} |"
            )

    lines.extend([
        "",
        "## Stage And Field Percentages",
        "",
        "| Field | Stage | Status | Facts Preserved | Facts Expected | Percentage | p10 | p50 | p90 | Confidence |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---|",
    ])
    for row in sorted(corpus["stage_summary"].values(), key=lambda r: (r["field"], r["stage"])):
        lines.append(
            f"| {row['field']} | {row['stage']} | {row['status']} | "
            f"{row['numerator']} | {row['denominator']} | "
            f"{fmt_pct(row['percentage'])} | {fmt_pct(row['p10'])} | {fmt_pct(row['p50'])} | "
            f"{fmt_pct(row['p90'])} | {row['confidence']} |"
        )

    chunk = corpus["chunk_quality"]
    lines.extend([
        "",
        "## Chunk Quality Baseline",
        "",
        f"- Total chunks: {chunk['total_chunks']}",
        f"- Oversized chunks (>{MAX_TOKENS_DEFAULT} BPE/active tokens): {chunk['oversized_chunks']} ({fmt_pct(chunk['oversized_percentage'])})",
        f"- Thin chunks (<{MIN_TOKENS_DEFAULT} tokens): {chunk['thin_chunks']} ({fmt_pct(chunk['thin_percentage'])})",
        f"- Within-report duplicate content hashes: {chunk.get('within_report_duplicate_content_hashes', chunk['duplicate_content_hashes'])}",
        f"- Global duplicate content hashes: {chunk.get('global_duplicate_content_hashes', chunk['duplicate_content_hashes'])}",
        f"- Missing required metadata fields: {chunk['missing_required_metadata_fields']}",
        f"- Max token count: {chunk['max_token_count']}",
        "",
        "### Chunk Type Counts",
        "",
        "| Type | Count |",
        "|---|---:|",
    ])
    for ctype, count in sorted(chunk["type_counts"].items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"| {ctype} | {count} |")

    lines.extend([
        "",
        "### Chunk Quality Defects",
        "",
        "| Program | Defect | Count | Total Chunks | Percentage |",
        "|---|---|---:|---:|---:|",
    ])
    for defect in corpus.get("chunk_quality_defects", [])[:20]:
        lines.append(
            f"| {defect['program']} | {defect['defect']} | {defect['count']} | "
            f"{defect['total_chunks']} | {fmt_pct(defect['percentage'])} |"
        )

    lines.extend([
        "",
        "## Retrieval Benchmark",
        "",
        "| Category | Queries | Recall@1 | Recall@5 | MRR | Answerable |",
        "|---|---:|---:|---:|---:|---:|",
    ])
    for category, row in sorted(corpus["retrieval_summary"].items()):
        lines.append(
            f"| {category} | {row['queries']} | {fmt_pct(row['recall_at_1'])} | "
            f"{fmt_pct(row['recall_at_5'])} | {row['mrr']} | "
            f"{fmt_pct(row['answerable_query_percentage'])} |"
        )

    lines.extend([
        "",
        "## Top Defects By Impact",
        "",
        "| Program | Field | Stage | Lost Facts | Expected | Percentage | Impact |",
        "|---|---|---|---:|---:|---:|---:|",
    ])
    for defect in corpus["top_defects"][:20]:
        lines.append(
            f"| {defect['program']} | {defect['field']} | {defect['stage']} | "
            f"{defect['lost_facts']} | {defect['denominator']} | "
            f"{fmt_pct(defect['percentage'])} | {defect['impact_score']} |"
        )

    lines.extend([
        "",
        "## Chunk Redesign Criteria",
        "",
        "Use this baseline to judge chunk redesigns. A redesign should improve external dependency retrieval, paragraph logic retrieval, file/VSAM retrieval, metadata completeness, BPE compliance, and answerable-query percentage. Recommended next chunk families: dependency-edge chunks, logical paragraph subchunks, hierarchical section summaries, and split data-record chunks.",
    ])
    return "\n".join(lines) + "\n"


def fmt_pct(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.2f}%"


def write_csv(result: dict[str, Any], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "program", "mode", "field", "stage", "numerator",
            "denominator", "percentage", "confidence", "status", "note",
        ])
        for program in result["programs"]:
            for metric in program["metrics"]:
                writer.writerow([
                    program["program"],
                    program["mode"],
                    metric["field"],
                    metric["stage"],
                    metric["numerator"],
                    metric["denominator"],
                    "" if metric["percentage"] is None else metric["percentage"],
                    metric["confidence"],
                    metric.get("status", "measured"),
                    metric.get("note", ""),
                ])


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate KB/RAG preservation percentages across report artifacts."
    )
    parser.add_argument("--report-root", type=Path, default=Path("out/report"))
    parser.add_argument("--output-json", type=Path, default=Path("rag_kb_evaluation.json"))
    parser.add_argument("--output-report", type=Path, default=Path("rag_kb_evaluation_report.md"))
    parser.add_argument("--output-csv", type=Path, default=Path("rag_kb_evaluation.csv"))
    parser.add_argument("--source-root", type=Path, action="append", default=[])
    parser.add_argument("--max-tokens", type=int, default=MAX_TOKENS_DEFAULT)
    parser.add_argument("--min-tokens", type=int, default=MIN_TOKENS_DEFAULT)
    parser.add_argument(
        "--retrieval-limit-per-category", type=int, default=5,
        help="Maximum deterministic fact queries per category per report (default: 5).",
    )
    args = parser.parse_args()

    evaluator = RagKbEvaluator(
        args.report_root,
        source_roots=args.source_root,
        max_tokens=args.max_tokens,
        min_tokens=args.min_tokens,
        retrieval_limit_per_category=args.retrieval_limit_per_category,
    )
    result = evaluator.evaluate()
    write_outputs(result, args.output_json, args.output_report, args.output_csv)
    print(f"Wrote {args.output_report}")
    print(f"Wrote {args.output_json}")
    if args.output_csv:
        print(f"Wrote {args.output_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
