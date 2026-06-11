#!/usr/bin/env python3
"""Compare report-local RAG bundles with retrieval and fact-level checks.

The benchmark is intentionally producer-side and deterministic. It does not
call embeddings, a vector database, a reranker, or an LLM; it compares the
bundle contents that this repository generates.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import statistics
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class QuerySpec:
    query_id: str
    category: str
    query: str
    expected_hit: bool
    expected_types: frozenset[str]
    all_terms: frozenset[str]
    any_terms: frozenset[str]
    require_terms: frozenset[str]
    reject_terms: frozenset[str]
    requires_any_chunk_type: frozenset[str]


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tokenize(text: str) -> list[str]:
    return [token.upper() for token in re.findall(r"[A-Za-z][A-Za-z0-9_\-]{1,}", text or "")]


def normalize(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return re.sub(r"\s+", " ", value.strip()).upper()
    return re.sub(r"\s+", " ", json.dumps(value, sort_keys=True)).upper()


def load_queries(path: Path) -> tuple[QuerySpec, ...]:
    data = load_json(path)
    queries = data.get("queries", data if isinstance(data, list) else [])
    return tuple(
        QuerySpec(
            query_id=item["query_id"],
            category=item["category"],
            query=item["query"],
            expected_hit=bool(item.get("expected_hit", True)),
            expected_types=frozenset(item.get("expected_types", [])),
            all_terms=frozenset(item.get("all_terms", [])),
            any_terms=frozenset(item.get("any_terms", [])),
            require_terms=frozenset(item.get("require_terms", [])),
            reject_terms=frozenset(item.get("reject_terms", [])),
            requires_any_chunk_type=frozenset(item.get("requires_any_chunk_type", [])),
        )
        for item in queries
    )


def bundle_files(root: Path, subdir: str) -> set[Path]:
    base = root / subdir
    if not base.exists():
        return set()
    return {path.relative_to(base) for path in base.rglob("*") if path.is_file()}


def chunk_records(bundle: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted((bundle / "chunks").glob("*.json")):
        if path.name in {"bm25_index.json", "chunks_manifest.json"}:
            continue
        data = load_json(path)
        metadata = data.get("metadata") or {}
        text = "\n".join(str(data.get(key, "")) for key in ("title", "text", "content", "summary"))
        if not text.strip():
            text = json.dumps(data, sort_keys=True)
        records.append(
            {
                "file": path.name,
                "chunk_id": metadata.get("chunk_id") or data.get("chunk_id") or path.stem,
                "chunk_type": metadata.get("chunk_type") or data.get("chunk_type") or "",
                "text": text,
                "metadata": metadata,
                "term_freq": Counter(tokenize(text)),
                "tokens": tokenize(text),
            }
        )
    return records


def bundle_metrics(bundle: Path) -> dict[str, Any]:
    records = chunk_records(bundle)
    type_counts = Counter(record["chunk_type"] for record in records)
    manifest_path = bundle / "manifest.json"
    manifest = load_json(manifest_path) if manifest_path.exists() else {}
    return {
        "exists": bundle.exists(),
        "manifest_schema_version": manifest.get("schema_version"),
        "manifest_chunk_count": manifest.get("chunk_count"),
        "chunk_count": len(records),
        "total_files": sum(1 for path in bundle.rglob("*") if path.is_file()) if bundle.exists() else 0,
        "total_bytes": sum(path.stat().st_size for path in bundle.rglob("*") if path.is_file()) if bundle.exists() else 0,
        "knowledge_base_files": len(bundle_files(bundle, "knowledge_base")),
        "artifact_files": len(bundle_files(bundle, "artifacts")),
        "type_counts": dict(sorted(type_counts.items())),
    }


def integrity_checks(v0: Path, current: Path) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    for subdir in ("knowledge_base", "artifacts"):
        v0_files = bundle_files(v0, subdir)
        current_files = bundle_files(current, subdir)
        common = v0_files & current_files
        differing = [
            str(path)
            for path in sorted(common)
            if sha256(v0 / subdir / path) != sha256(current / subdir / path)
        ]
        checks[subdir] = {
            "v0_files": len(v0_files),
            "current_files": len(current_files),
            "missing_current": [str(path) for path in sorted(v0_files - current_files)],
            "added_current": [str(path) for path in sorted(current_files - v0_files)],
            "differing_common_files": differing,
            "file_retention_pct": pct(len(common), len(v0_files)),
            "byte_identical": not differing and v0_files == current_files,
        }
    return checks


def static_value_facts(records: list[dict[str, Any]]) -> set[str]:
    facts: set[str] = set()
    for record in records:
        if record["chunk_type"] != "static_values":
            continue
        for item in record["metadata"].get("static_values", []) or []:
            variable = normalize(item.get("variable"))
            for value in item.get("values", []) or []:
                facts.add(f"{variable}|value|{normalize(value)}")
            for paragraph in item.get("paragraphs", []) or []:
                facts.add(f"{variable}|paragraph|{normalize(paragraph)}")
            for assignment in item.get("assignments", []) or []:
                facts.add("|".join([
                    variable,
                    "assignment",
                    normalize(assignment.get("statement_type")),
                    normalize(assignment.get("source_value")),
                    normalize(assignment.get("paragraph")),
                ]))
            for consumer in item.get("consumers", []) or []:
                facts.add("|".join([
                    variable,
                    "consumer",
                    normalize(consumer.get("role")),
                    normalize(consumer.get("paragraph")),
                ]))
    return facts


def static_value_chunk_completeness(records: list[dict[str, Any]]) -> dict[str, Any]:
    counts: list[int] = []
    variable_sets: list[set[str]] = []
    for record in records:
        if record["chunk_type"] != "static_values":
            continue
        variables = {normalize(item.get("variable")) for item in record["metadata"].get("static_values", []) or []}
        variables.discard("")
        counts.append(len(variables))
        variable_sets.append(variables)
    unique_variables = set().union(*variable_sets) if variable_sets else set()
    full_coverage_chunks = sum(1 for variables in variable_sets if variables == unique_variables and unique_variables)
    return {
        "chunk_count": len(counts),
        "chunks_with_static_values_metadata": sum(1 for count in counts if count > 0),
        "unique_variables": len(unique_variables),
        "metadata_variable_instances": sum(counts),
        "min_variables_per_chunk": min(counts) if counts else 0,
        "max_variables_per_chunk": max(counts) if counts else 0,
        "median_variables_per_chunk": round(statistics.median(counts), 2) if counts else 0,
        "chunks_with_full_program_variable_set": full_coverage_chunks,
    }


def dataflow_facts(records: list[dict[str, Any]]) -> set[str]:
    facts: set[str] = set()
    for record in records:
        if record["chunk_type"] != "dataflow.variable":
            continue
        metadata = record["metadata"]
        variable = normalize(metadata.get("variable"))
        facts.add(f"{variable}|origin_group|{normalize(metadata.get('origin_group'))}")
        facts.add(f"{variable}|read_count|{normalize(metadata.get('read_count'))}")
        facts.add(f"{variable}|write_count|{normalize(metadata.get('write_count'))}")
        for site_kind in ("read_sites", "write_sites"):
            for site in metadata.get(site_kind, []) or []:
                facts.add("|".join([
                    variable,
                    site_kind[:-1],
                    normalize(site.get("paragraph")),
                    normalize(site.get("node_type")),
                ]))
    return facts


def cics_fact_values(records: list[dict[str, Any]]) -> dict[str, str]:
    facts: dict[str, str] = {}
    for record in records:
        if not record["chunk_type"].startswith("cics."):
            continue
        metadata = record["metadata"]
        base = "|".join([
            record["chunk_type"],
            normalize(metadata.get("command")),
            normalize(metadata.get("type")),
            normalize(metadata.get("target_kind")),
            normalize(metadata.get("target")),
        ])
        facts[base] = ""
        for argument in metadata.get("arguments", []) or []:
            key = "|".join([
                base,
                "arg",
                normalize(argument.get("name")),
                normalize(argument.get("value")),
                normalize(argument.get("value_source")),
            ])
            facts[key] = normalize(argument.get("resolved_value"))
    return facts


def cics_facts(records: list[dict[str, Any]]) -> set[str]:
    return set(cics_fact_values(records))


def value_change_label(key: str, before: str, after: str) -> str:
    before_label = before or "<blank>"
    after_label = after or "<blank>"
    return f"{key}|value_changed|{before_label}|{after_label}"


def keyed_fact_diff(before: dict[str, str], after: dict[str, str]) -> dict[str, Any]:
    before_keys = set(before)
    after_keys = set(after)
    common_keys = before_keys & after_keys
    union_keys = before_keys | after_keys
    changed = sorted(key for key in common_keys if before[key] != after[key])
    changed_samples = [value_change_label(key, before[key], after[key]) for key in changed[:25]]
    value_improved = [key for key in changed if not before[key] and bool(after[key])]
    return {
        "v0_count": len(before_keys),
        "current_count": len(after_keys),
        "retained_count": len(common_keys),
        "retention_pct": pct(len(common_keys), len(before_keys)),
        "jaccard_pct": pct(len(common_keys), len(union_keys)),
        "changed_count": len(changed),
        "value_improved_count": len(value_improved),
        "missing_sample": sorted(before_keys - after_keys)[:25],
        "added_sample": sorted(after_keys - before_keys)[:25],
        "changed_sample": changed_samples,
    }


def path_sensitive_facts(records: list[dict[str, Any]]) -> set[str]:
    facts: set[str] = set()
    volatile_keys = {"node_id", "source_line", "source_column", "evidence", "line_origin", "analysis_timestamp", "analysis_run_timestamp"}

    def add_value(prefix: str, value: Any) -> None:
        if isinstance(value, dict):
            for key, child in sorted(value.items()):
                if key in volatile_keys:
                    continue
                add_value(f"{prefix}.{key}", child)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                add_value(f"{prefix}[{index}]", child)
        else:
            normalized = normalize(value)
            if normalized:
                facts.add(f"{prefix}|{normalized}")

    for record in records:
        metadata = record["metadata"]
        for key, value in sorted(metadata.items()):
            if key.startswith("path_sensitive_"):
                add_value(f"{record['chunk_type']}|{normalize(metadata.get('chunk_id') or record['chunk_id'])}|{key}", value)
        if record["chunk_type"] == "flow_sensitive.target":
            chunk_id = normalize(metadata.get("chunk_id") or record["chunk_id"])
            for key in ("call_targets", "cics_targets", "cics_arguments"):
                value = metadata.get(key)
                if value:
                    add_value(f"{record['chunk_type']}|{chunk_id}|{key}", value)
    return facts


def dataflow_sidecar_facts(bundle: Path) -> set[str]:
    facts: set[str] = set()
    candidates = [
        bundle / "artifacts" / "static_analysis" / "dataflow_rag_summary.json",
        bundle / "artifacts" / "static_analysis" / "dataflow.json",
        bundle / "artifacts" / "dataflow.json",
        bundle / "static_analysis" / "dataflow.json",
    ]
    path = next((candidate for candidate in candidates if candidate.exists()), None)
    if path is None:
        return facts
    data = load_json(path)
    facts.add(f"analysis|schema_version|{normalize(data.get('schema_version'))}")
    facts.add(f"analysis|analysis_version|{normalize(data.get('analysis_version'))}")
    summary = data.get("summary") or {}
    for key in ("node_count", "edge_count", "entry_constant_count", "exit_constant_count", "kill_count", "diagnostic_count"):
        facts.add(f"summary|{key}|{normalize(summary.get(key))}")
    for node_id, state in sorted((data.get("node_states") or {}).items()):
        for state_key in ("entry_constants", "exit_constants"):
            for variable, value in sorted((state.get(state_key) or {}).items()):
                facts.add("|".join([
                    "node_state",
                    state_key,
                    normalize(variable),
                    normalize(value.get("state")),
                    normalize(value.get("kind")),
                    normalize(value.get("normalized_value")),
                ]))
    return facts


def business_rule_facts(records: list[dict[str, Any]]) -> set[str]:
    facts: set[str] = set()
    for record in records:
        if record["chunk_type"] != "business_rule":
            continue
        metadata = record["metadata"]
        condition = normalize(metadata.get("condition"))
        evidence = normalize(metadata.get("evidence"))
        base = "|".join([
            "business_rule",
            normalize(metadata.get("category")),
            normalize(metadata.get("severity")),
            normalize(metadata.get("edge_type")),
            condition,
            normalize(metadata.get("action")),
        ])
        facts.add(base)
        for token in sorted(set(tokenize(condition + " " + evidence))):
            if "-" in token or token.startswith(("WS", "TWCOB", "PDC", "PDB", "PD", "DFH", "W", "M")):
                facts.add(f"business_rule|identifier|{token}")
    return facts


def paragraph_facts(records: list[dict[str, Any]]) -> set[str]:
    facts: set[str] = set()
    for record in records:
        if record["chunk_type"] not in {"paragraph_logic", "controlflow.cfg", "workflow"}:
            continue
        metadata = record["metadata"]
        paragraph = normalize(metadata.get("paragraph") or metadata.get("label") or metadata.get("chunk_id"))
        if not paragraph:
            continue
        facts.add(f"{record['chunk_type']}|paragraph|{paragraph}")
        for field in ("calls", "variables_modified", "variables_read", "cics_commands", "sql_operations", "copybooks_used"):
            for value in metadata.get(field, []) or []:
                facts.add(f"{record['chunk_type']}|{paragraph}|{field}|{normalize(value)}")
    return facts


def copybook_facts(records: list[dict[str, Any]]) -> set[str]:
    facts: set[str] = set()
    for record in records:
        if record["chunk_type"] not in {"copybook_fields", "copybook_mentions", "unused_copybooks"}:
            continue
        metadata = record["metadata"]
        for copybook in metadata.get("copybooks", []) or []:
            if isinstance(copybook, str):
                facts.add(f"{record['chunk_type']}|copybook|{normalize(copybook)}")
                continue
            if not isinstance(copybook, dict):
                continue
            name = normalize(copybook.get("copybook"))
            if not name:
                continue
            facts.add(f"{record['chunk_type']}|copybook|{name}|status|{normalize(copybook.get('status'))}")
            facts.add(f"{record['chunk_type']}|copybook|{name}|stubbed|{normalize(copybook.get('stubbed'))}")
            for field in copybook.get("fields", []) or []:
                field_name = normalize(field.get("name"))
                if not field_name:
                    continue
                facts.add("|".join([
                    record["chunk_type"],
                    "field",
                    name,
                    field_name,
                    normalize(field.get("level")),
                    normalize(field.get("picture")),
                    normalize(field.get("parent")),
                ]))
        for key in ("copybook", "copybook_name", "copybooks", "unused_copybooks"):
            value = metadata.get(key)
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        item = item.get("copybook") or item.get("name") or item.get("file")
                    facts.add(f"{record['chunk_type']}|{key}|{normalize(item)}")
            elif value is not None:
                facts.add(f"{record['chunk_type']}|{key}|{normalize(value)}")
        for term in tokenize(record["text"]):
            if term.endswith(".CPY") or term.startswith("PDR") or term.startswith("PDB") or term in {"SQLCA", "DFHAID", "DFHBMSCA"}:
                facts.add(f"{record['chunk_type']}|text_term|{term}")
    return facts


def chunk_id_facts(records: list[dict[str, Any]]) -> set[str]:
    return {f"{record['chunk_type']}|{normalize(record['chunk_id'])}" for record in records}


def bm25_terms(bundle: Path) -> set[str]:
    path = bundle / "chunks" / "bm25_index.json"
    if not path.exists():
        return set()
    data = load_json(path)
    terms: set[str] = set()
    entries = data.get("entries", data if isinstance(data, list) else [])
    for entry in entries:
        terms.update((entry.get("term_freq") or {}).keys())
        terms.update(entry.get("structured_terms") or [])
        terms.update((entry.get("structured_term_weights") or {}).keys())
    return {normalize(term) for term in terms if normalize(term)}


def fact_sets(bundle: Path) -> dict[str, set[str]]:
    records = chunk_records(bundle)
    return {
        "business_rules": business_rule_facts(records),
        "chunk_ids": chunk_id_facts(records),
        "dataflow.variable": dataflow_facts(records),
        "dataflow.sidecar": dataflow_sidecar_facts(bundle),
        "static_values": static_value_facts(records),
        "cics": cics_facts(records),
        "paragraphs": paragraph_facts(records),
        "path_sensitive": path_sensitive_facts(records),
        "copybooks": copybook_facts(records),
        "bm25_terms": bm25_terms(bundle),
    }


def fact_diff(v0: Path, current: Path) -> dict[str, Any]:
    before = fact_sets(v0)
    after = fact_sets(current)
    result: dict[str, Any] = {}
    for name in sorted(before):
        if name == "cics":
            result[name] = keyed_fact_diff(
                cics_fact_values(chunk_records(v0)),
                cics_fact_values(chunk_records(current)),
            )
            continue
        b = before[name]
        a = after.get(name, set())
        common = b & a
        union = b | a
        result[name] = {
            "v0_count": len(b),
            "current_count": len(a),
            "retained_count": len(common),
            "retention_pct": pct(len(common), len(b)),
            "jaccard_pct": pct(len(common), len(union)),
            "changed_count": 0,
            "value_improved_count": 0,
            "missing_sample": sorted(b - a)[:25],
            "added_sample": sorted(a - b)[:25],
            "changed_sample": [],
        }
    return result


def score_query(records: list[dict[str, Any]], query: QuerySpec, include_timings: bool) -> dict[str, Any]:
    if not records:
        return {"hit": False, "rank": None, "top": [], "elapsed_ms": None, "skipped": False, "skip_reason": None}
    if query.requires_any_chunk_type:
        present_types = {record["chunk_type"] for record in records}
        if not present_types & set(query.requires_any_chunk_type):
            required = ", ".join(sorted(query.requires_any_chunk_type))
            return {
                "hit": False,
                "rank": None,
                "top": [],
                "elapsed_ms": None,
                "skipped": True,
                "skip_reason": f"required chunk type absent: {required}",
            }
    query_terms = tokenize(query.query)
    document_frequency: Counter[str] = Counter()
    for record in records:
        for term in set(record["term_freq"]):
            document_frequency[term] += 1
    avg_doc_len = statistics.mean(max(1, len(record["tokens"])) for record in records)
    k1 = 1.5
    b = 0.75
    start = time.perf_counter() if include_timings else None
    scored: list[tuple[float, dict[str, Any]]] = []
    for record in records:
        score = 0.0
        doc_len = max(1, len(record["tokens"]))
        for term in query_terms:
            tf = record["term_freq"].get(term, 0)
            if not tf:
                continue
            df = document_frequency[term]
            idf = math.log(1 + (len(records) - df + 0.5) / (df + 0.5))
            score += idf * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * doc_len / avg_doc_len))
        text_upper = normalize(record["text"] + " " + json.dumps(record["metadata"], sort_keys=True))
        for term in query.all_terms:
            if normalize(term) in text_upper:
                score += 4.0
        for term in query.any_terms:
            if normalize(term) in text_upper:
                score += 2.5
        if record["chunk_type"] in query.expected_types:
            score += 0.15
        scored.append((score, record))
    elapsed_ms = (time.perf_counter() - start) * 1000.0 if start is not None else None
    ranked = sorted(scored, key=lambda item: (-item[0], item[1]["file"]))
    hit_rank = None
    top: list[dict[str, Any]] = []
    for rank, (score, record) in enumerate(ranked[:10], start=1):
        text_upper = normalize(record["text"] + " " + json.dumps(record["metadata"], sort_keys=True))
        has_all = all(normalize(term) in text_upper for term in query.all_terms)
        has_any = not query.any_terms or any(normalize(term) in text_upper for term in query.any_terms)
        has_required = all(normalize(term) in text_upper for term in query.require_terms)
        has_rejected = any(normalize(term) in text_upper for term in query.reject_terms)
        type_ok = record["chunk_type"] in query.expected_types
        relevant = type_ok and has_all and has_any and has_required and not has_rejected
        if relevant and hit_rank is None:
            hit_rank = rank
        top.append(
            {
                "rank": rank,
                "score": round(score, 4),
                "chunk_id": record["chunk_id"],
                "chunk_type": record["chunk_type"],
                "file": record["file"],
                "relevant": relevant,
            }
        )
    return {
        "hit": hit_rank is not None and hit_rank <= 5,
        "rank": hit_rank,
        "top": top,
        "elapsed_ms": elapsed_ms,
        "skipped": False,
        "skip_reason": None,
    }


def retrieval_results(bundle: Path, queries: tuple[QuerySpec, ...], include_timings: bool) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    records = chunk_records(bundle)
    rows = []
    for query in queries:
        result = score_query(records, query, include_timings)
        result["expected_hit"] = query.expected_hit
        result["passed"] = True if result.get("skipped") else result["hit"] == query.expected_hit
        rows.append(
            {
                "query_id": query.query_id,
                "category": query.category,
                "query": query.query,
                "expected_hit": query.expected_hit,
                "result": result,
            }
        )
    active_rows = [row for row in rows if not row["result"].get("skipped")]
    skipped_rows = [row for row in rows if row["result"].get("skipped")]
    positive_rows = [row for row in active_rows if row["expected_hit"]]
    negative_rows = [row for row in active_rows if not row["expected_hit"]]
    hits = sum(1 for row in positive_rows if row["result"]["hit"])
    passes = sum(1 for row in active_rows if row["result"]["passed"])
    negative_passes = sum(1 for row in negative_rows if row["result"]["passed"])
    ranks = [row["result"]["rank"] for row in positive_rows if row["result"]["rank"]]
    elapsed_values = [row["result"]["elapsed_ms"] for row in active_rows if row["result"]["elapsed_ms"] is not None]
    summary = {
        "query_count": len(active_rows),
        "total_query_count": len(rows),
        "skipped_query_count": len(skipped_rows),
        "positive_query_count": len(positive_rows),
        "negative_query_count": len(negative_rows),
        "hit_at_5": hits,
        "hit_at_5_pct": pct(hits, len(positive_rows)),
        "expected_pass_at_5": passes,
        "expected_pass_at_5_pct": pct(passes, len(active_rows)),
        "negative_pass_at_5": negative_passes,
        "negative_pass_at_5_pct": pct(negative_passes, len(negative_rows)),
        "mrr": round(sum(1.0 / rank for rank in ranks) / len(positive_rows), 4) if positive_rows else 0.0,
        "avg_elapsed_ms": round(sum(elapsed_values) / len(elapsed_values), 4) if elapsed_values else None,
    }
    category_summary: dict[str, Any] = {}
    for category in sorted({row["category"] for row in rows}):
        category_rows = [row for row in rows if row["category"] == category]
        active_category_rows = [row for row in category_rows if not row["result"].get("skipped")]
        skipped_category_rows = [row for row in category_rows if row["result"].get("skipped")]
        positive_category_rows = [row for row in active_category_rows if row["expected_hit"]]
        category_hits = sum(1 for row in positive_category_rows if row["result"]["hit"])
        category_passes = sum(1 for row in active_category_rows if row["result"]["passed"])
        category_summary[category] = {
            "hit_at_5": category_hits,
            "positive_query_count": len(positive_category_rows),
            "query_count": len(active_category_rows),
            "total_query_count": len(category_rows),
            "skipped_query_count": len(skipped_category_rows),
            "hit_at_5_pct": pct(category_hits, len(positive_category_rows)),
            "expected_pass_at_5": category_passes,
            "expected_pass_at_5_pct": pct(category_passes, len(active_category_rows)),
        }
    return rows, summary, category_summary


def pct(numerator: int | float, denominator: int | float) -> float:
    if not denominator:
        return 100.0
    return round(100.0 * numerator / denominator, 2)


def evaluate(report_dir: Path, queries_path: Path, baseline_name: str, current_name: str, include_timings: bool) -> dict[str, Any]:
    queries = load_queries(queries_path)
    baseline = report_dir / baseline_name
    current = report_dir / current_name
    baseline_rows, baseline_summary, baseline_categories = retrieval_results(baseline, queries, include_timings)
    current_rows, current_summary, current_categories = retrieval_results(current, queries, include_timings)
    per_query = []
    for before, after in zip(baseline_rows, current_rows, strict=True):
        per_query.append(
            {
                "query_id": before["query_id"],
                "category": before["category"],
                "query": before["query"],
                "expected_hit": before["expected_hit"],
                "baseline": before["result"],
                "current": after["result"],
            }
        )
    return {
        "report_dir": str(report_dir),
        "queries_path": str(queries_path),
        "baseline_bundle": baseline_name,
        "current_bundle": current_name,
        "baseline_metrics": bundle_metrics(baseline),
        "current_metrics": bundle_metrics(current),
        "baseline_completeness": {"static_values": static_value_chunk_completeness(chunk_records(baseline))},
        "current_completeness": {"static_values": static_value_chunk_completeness(chunk_records(current))},
        "integrity": integrity_checks(baseline, current),
        "fact_diff": fact_diff(baseline, current),
        "baseline_retrieval_summary": baseline_summary,
        "current_retrieval_summary": current_summary,
        "baseline_category_summary": baseline_categories,
        "current_category_summary": current_categories,
        "per_query": per_query,
    }


def render_markdown(result: dict[str, Any]) -> str:
    title = Path(result["report_dir"]).name.replace(".report", "")
    lines = [
        f"# {title} RAG Bundle Benchmark",
        "",
        "This benchmark compares the preserved `knowledge-base_rag_v0` bundle with the current `knowledge-base_rag` bundle using deterministic sparse retrieval and fact-level retention checks.",
        "",
        "## Scope",
        "",
        "- Producer-side sparse retrieval only; no embeddings, vector database, reranker, or LLM answer grading.",
        "- Hit criteria require expected chunk type plus required terms from the query specification.",
        "- Fact retention compares structured chunk metadata and BM25 terms; it is stricter than file-count retention but still not a semantic proof.",
        "",
        "## Bundle Metrics",
        "",
        "| Metric | v0 | current |",
        "|---|---:|---:|",
    ]
    for key in ("chunk_count", "total_files", "total_bytes", "knowledge_base_files", "artifact_files"):
        lines.append(f"| {key} | {result['baseline_metrics'].get(key)} | {result['current_metrics'].get(key)} |")
    lines.extend([
        "",
        "## Static Values Chunk Completeness",
        "",
        "This row is separate from fact retention because `metadata.static_values` may be denormalized across chunk parts. A 100% set-union fact retention score does not imply every chunk part kept the same per-variable body text.",
        "",
        "| Metric | v0 | current |",
        "|---|---:|---:|",
    ])
    for key in (
        "chunk_count",
        "chunks_with_static_values_metadata",
        "unique_variables",
        "metadata_variable_instances",
        "min_variables_per_chunk",
        "median_variables_per_chunk",
        "max_variables_per_chunk",
        "chunks_with_full_program_variable_set",
    ):
        lines.append(
            f"| {key} | {result['baseline_completeness']['static_values'].get(key)} | {result['current_completeness']['static_values'].get(key)} |"
        )
    lines.extend([
        "",
        "## Integrity",
        "",
        "| Area | v0 files | current files | retention | byte-identical | differing files |",
        "|---|---:|---:|---:|---|---|",
    ])
    for area, data in result["integrity"].items():
        differing = ", ".join(data["differing_common_files"][:8])
        if len(data["differing_common_files"]) > 8:
            differing += ", ..."
        lines.append(
            f"| `{area}` | {data['v0_files']} | {data['current_files']} | {data['file_retention_pct']}% | {data['byte_identical']} | {differing or '-'} |"
        )
    lines.extend([
        "",
        "## Fact Retention",
        "",
        "| Fact family | v0 facts | current facts | retained | retention | Jaccard | changed | improved |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for family, data in result["fact_diff"].items():
        lines.append(
            f"| `{family}` | {data['v0_count']} | {data['current_count']} | {data['retained_count']} | {data['retention_pct']}% | {data['jaccard_pct']}% | {data.get('changed_count', 0)} | {data.get('value_improved_count', 0)} |"
        )
    lines.extend([
        "",
        "## Retrieval Summary",
        "",
        "| Metric | v0 | current |",
        "|---|---:|---:|",
    ])
    for key in (
        "total_query_count",
        "query_count",
        "skipped_query_count",
        "positive_query_count",
        "negative_query_count",
        "hit_at_5",
        "hit_at_5_pct",
        "expected_pass_at_5",
        "expected_pass_at_5_pct",
        "negative_pass_at_5",
        "negative_pass_at_5_pct",
        "mrr",
        "avg_elapsed_ms",
    ):
        before = result["baseline_retrieval_summary"].get(key)
        after = result["current_retrieval_summary"].get(key)
        lines.append(f"| {key} | {before if before is not None else '-'} | {after if after is not None else '-'} |")
    lines.extend([
        "",
        "## Category Hit@5",
        "",
        "| Category | v0 | current |",
        "|---|---:|---:|",
    ])
    categories = sorted(set(result["baseline_category_summary"]) | set(result["current_category_summary"]))
    for category in categories:
        before = result["baseline_category_summary"].get(category, {})
        after = result["current_category_summary"].get(category, {})
        before_label = (
            f"hits {before.get('hit_at_5', 0)}/{before.get('positive_query_count', 0)} = {before.get('hit_at_5_pct', 0)}%; "
            f"passes {before.get('expected_pass_at_5', 0)}/{before.get('query_count', 0)} = {before.get('expected_pass_at_5_pct', 0)}%; "
            f"skipped {before.get('skipped_query_count', 0)}/{before.get('total_query_count', before.get('query_count', 0))}"
        )
        after_label = (
            f"hits {after.get('hit_at_5', 0)}/{after.get('positive_query_count', 0)} = {after.get('hit_at_5_pct', 0)}%; "
            f"passes {after.get('expected_pass_at_5', 0)}/{after.get('query_count', 0)} = {after.get('expected_pass_at_5_pct', 0)}%; "
            f"skipped {after.get('skipped_query_count', 0)}/{after.get('total_query_count', after.get('query_count', 0))}"
        )
        lines.append(f"| {category} | {before_label} | {after_label} |")
    lines.extend([
        "",
        "## Per-Query Results",
        "",
        "| Query | Category | Expected hit | v0 rank | current rank | v0 status | current status | current top-1 |",
        "|---|---|---|---:|---:|---|---|---|",
    ])
    for row in result["per_query"]:
        current_top = row["current"]["top"][0] if row["current"]["top"] else {}
        current_top_label = f"{current_top.get('chunk_type', '')}:{current_top.get('chunk_id', '')}"
        before_status = "skipped" if row["baseline"].get("skipped") else str(row["baseline"]["passed"])
        after_status = "skipped" if row["current"].get("skipped") else str(row["current"]["passed"])
        lines.append(
            f"| `{row['query_id']}` | {row['category']} | {row['expected_hit']} | {row['baseline']['rank'] or 'miss'} | {row['current']['rank'] or 'miss'} | {before_status} | {after_status} | `{current_top_label}` |"
        )
    lines.extend([
        "",
        "## Missing Fact Samples",
        "",
    ])
    for family, data in result["fact_diff"].items():
        if not data["missing_sample"]:
            continue
        lines.append(f"### `{family}`")
        lines.append("")
        for item in data["missing_sample"][:10]:
            display = item if len(item) <= 220 else item[:217] + "..."
            lines.append(f"- `{display}`")
        lines.append("")
    lines.extend([
        "## Changed Fact Samples",
        "",
    ])
    for family, data in result["fact_diff"].items():
        if not data.get("changed_sample"):
            continue
        lines.append(f"### `{family}`")
        lines.append("")
        for item in data["changed_sample"][:10]:
            display = item if len(item) <= 220 else item[:217] + "..."
            lines.append(f"- `{display}`")
        lines.append("")
    lines.extend([
        "## Interpretation",
        "",
        "A 100% expected-pass score means this fixed sparse query suite found no top-5 regression and the negative canary queries missed as expected. Queries gated by `requires_any_chunk_type` are skipped until the requested chunk family exists, so skipped static-analysis queries are not evidence of improvement. Fact-retention rows above show where chunk compaction changed the granularity or wording of facts.",
        "",
    ])
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", required=True, type=Path)
    parser.add_argument("--queries", required=True, type=Path)
    parser.add_argument("--baseline", default="knowledge-base_rag_v0")
    parser.add_argument("--current", default="knowledge-base_rag")
    parser.add_argument("--json-out", required=True, type=Path)
    parser.add_argument("--md-out", required=True, type=Path)
    parser.add_argument("--include-timings", action="store_true", help="Include wall-clock query timings in JSON/Markdown output.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = evaluate(args.report_dir, args.queries, args.baseline, args.current, args.include_timings)
    write_json(args.json_out, result)
    args.md_out.parent.mkdir(parents=True, exist_ok=True)
    args.md_out.write_text(render_markdown(result), encoding="utf-8")
    print(f"Wrote {args.json_out}")
    print(f"Wrote {args.md_out}")
    print(
        "Pass@5: "
        f"v0={result['baseline_retrieval_summary']['expected_pass_at_5']}/{result['baseline_retrieval_summary']['query_count']} "
        f"current={result['current_retrieval_summary']['expected_pass_at_5']}/{result['current_retrieval_summary']['query_count']}; "
        "positive Hit@5: "
        f"v0={result['baseline_retrieval_summary']['hit_at_5']}/{result['baseline_retrieval_summary']['positive_query_count']} "
        f"current={result['current_retrieval_summary']['hit_at_5']}/{result['current_retrieval_summary']['positive_query_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
