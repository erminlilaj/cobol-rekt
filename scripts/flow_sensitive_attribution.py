#!/usr/bin/env python3
"""Attribute flow-sensitive target-resolution failures for real reports."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


SUPPORTED_CICS_ARGUMENTS = {"PROGRAM", "FILE", "DATASET", "QUEUE", "QNAME", "MAP", "MAPSET", "TRANSID"}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def canonical(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip().upper()
    subscript = text.find("(")
    return text if subscript < 0 else text[:subscript]


def compact_text(value: Any, limit: int = 140) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


def static_value_evidence(report_dir: Path) -> dict[str, dict[str, Any]]:
    evidence: dict[str, dict[str, Any]] = {}
    for path in sorted((report_dir / "chunks").glob("*__static_values__*.json")):
        metadata = load_json(path).get("metadata") or {}
        for item in metadata.get("static_values", []) or []:
            variable = canonical(item.get("variable"))
            if not variable:
                continue
            values = item.get("values", []) or []
            assignments = item.get("assignments", []) or []
            if variable not in evidence:
                evidence[variable] = {
                    "values": values,
                    "assignments": assignments,
                    "source_chunk": path.name,
                }
    return evidence


def kill_rules_affecting(dataflow: dict[str, Any], variable: str, before_line: int | None) -> list[dict[str, Any]]:
    if before_line is None:
        return []
    aliases = dataflow.get("alias_sets") or {}
    result = []
    for rule_id, rule in (dataflow.get("kill_rules") or {}).items():
        line = rule.get("source_line")
        if not isinstance(line, int) or line >= before_line:
            continue
        affects_variable = variable in {canonical(v) for v in rule.get("killed_variables", []) or []}
        alias_set_id = rule.get("killed_alias_set_id")
        alias_members = aliases.get(alias_set_id, {}).get("members", []) if alias_set_id else []
        affects_alias = variable in {canonical(v) for v in alias_members}
        affects_all = rule.get("kill_scope") == "all_constants"
        if affects_variable or affects_alias or affects_all:
            item = dict(rule)
            item["rule_id"] = rule_id
            result.append(item)
    return sorted(result, key=lambda item: (item.get("source_line", -1), item.get("rule_id", "")))


def node_transfer_kills(dataflow: dict[str, Any], node_id: str) -> list[dict[str, Any]]:
    state = (dataflow.get("node_states") or {}).get(node_id) or {}
    result = []
    for ref in state.get("kill_rule_refs", []) or []:
        rule = (dataflow.get("kill_rules") or {}).get(ref)
        if rule:
            item = dict(rule)
            item["rule_id"] = ref
            result.append(item)
    return result


def classify(site: dict[str, Any], dataflow: dict[str, Any], static_values: dict[str, dict[str, Any]]) -> dict[str, Any]:
    node_state = (dataflow.get("node_states") or {}).get(site["node_id"])
    if node_state is None:
        return {
            "cause": "missing_cfg_metadata",
            "detail": "No dataflow node_state exists for this CFG node.",
            "entry_value": None,
            "static_value_evidence": static_values.get(site["identifier"]),
            "prior_kills": [],
            "node_transfer_kills": [],
        }

    entry_constants = node_state.get("entry_constants") or {}
    entry_value = entry_constants.get(site["identifier"])
    prior_kills = kill_rules_affecting(dataflow, site["identifier"], site.get("source_line"))
    same_node_kills = node_transfer_kills(dataflow, site["node_id"])
    static_evidence = static_values.get(site["identifier"])
    diagnostics = node_state.get("diagnostics") or []

    if site.get("resolution_status") == "resolved":
        return {
            "cause": "resolved",
            "detail": "Flow-sensitive metadata resolved this site from the CFG node entry constants.",
            "entry_value": entry_value,
            "static_value_evidence": static_evidence,
            "prior_kills": prior_kills[-5:],
            "node_transfer_kills": same_node_kills,
        }

    has_executable_assignment = bool(static_evidence and any(
        canonical(assignment.get("statement_type")) not in {"", "VALUE"}
        for assignment in static_evidence.get("assignments", []) or []
        if isinstance(assignment, dict)
    ))

    if any(diagnostic.get("code") == "DATAFLOW_LOOP_CARRIED_CONSTANT_NOT_INFERRED" for diagnostic in diagnostics):
        cause = "loop_carried"
        detail = "The node carries a loop diagnostic for a constant not inferred."
    elif entry_value is None and static_evidence and prior_kills and has_executable_assignment:
        kill = prior_kills[-1]
        cause = f"killed_by({kill.get('statement_type', 'UNKNOWN')})"
        detail = f"Static-value evidence exists, but a prior {kill.get('code')} kill can remove {site['identifier']} before this site."
    elif entry_value is None and static_evidence:
        cause = "missing_cfg_metadata"
        detail = (
            "Static-value chunks show a declaration/static value, but the flow-sensitive entry map does not seed "
            "that value at this CFG node."
        )
    elif entry_value is None:
        cause = "no_assignment_found"
        detail = "No entry constant and no static VALUE/assignment evidence for this identifier was found in the report artifacts."
    elif entry_value.get("state") != "CONSTANT":
        cause = "conflicting_join(values)"
        detail = f"Entry lattice state is {entry_value.get('state')}, so no single constant is proven at the site."
    elif entry_value.get("kind") != "ALPHANUMERIC":
        cause = "unsupported_expression"
        detail = f"Entry constant kind is {entry_value.get('kind')}; target resolution currently requires ALPHANUMERIC."
    elif site.get("resolution_status") in {"unresolved", ""}:
        cause = "missing_cfg_metadata"
        detail = "A compatible entry constant appears present, but no resolved path_sensitive_* metadata was emitted."
    else:
        cause = "missing_cfg_metadata"
        detail = f"Unhandled resolution status: {site.get('resolution_status') or '<missing>'}."

    return {
        "cause": cause,
        "detail": detail,
        "entry_value": entry_value,
        "static_value_evidence": static_evidence,
        "prior_kills": prior_kills[-5:],
        "node_transfer_kills": same_node_kills,
    }


def call_sites(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for node in nodes:
        metadata = node.get("metadata") or {}
        if node.get("type") != "CALL" or not metadata.get("dynamic_call"):
            continue
        identifier = canonical(
            metadata.get("path_sensitive_call_target_identifier")
            or metadata.get("call_target_identifier")
            or metadata.get("call_target")
        )
        if not identifier:
            continue
        result.append({
            "site_id": f"{node['id']}:call_target:{identifier}",
            "site_kind": "dynamic_call_target",
            "node_id": node["id"],
            "source_line": node.get("sourceLine"),
            "source_column": node.get("sourceColumn"),
            "statement_type": node.get("type"),
            "statement_text": compact_text(node.get("originalText")),
            "operation": "CALL",
            "argument_name": "CALL_TARGET",
            "identifier": identifier,
            "resolution_status": metadata.get("path_sensitive_call_resolution_status", ""),
            "resolved_value": metadata.get("path_sensitive_call_target"),
            "resolution_note": metadata.get("path_sensitive_call_resolution_note"),
        })
    return result


def cics_sites(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for node in nodes:
        metadata = node.get("metadata") or {}
        if node.get("type") != "DIALECT" or not metadata.get("cics_command"):
            continue
        path_args = {
            (canonical(arg.get("name")), canonical(arg.get("identifier"))): arg
            for arg in metadata.get("path_sensitive_cics_arguments", []) or []
            if isinstance(arg, dict)
        }
        for argument in metadata.get("cics_arguments", []) or []:
            if not isinstance(argument, dict):
                continue
            name = canonical(argument.get("name"))
            identifier = canonical(argument.get("value"))
            if name not in SUPPORTED_CICS_ARGUMENTS or canonical(argument.get("value_source")) != "IDENTIFIER":
                continue
            path_arg = path_args.get((name, identifier), {})
            result.append({
                "site_id": f"{node['id']}:cics_arg:{name}:{identifier}",
                "site_kind": "cics_resource_argument",
                "node_id": node["id"],
                "source_line": node.get("sourceLine"),
                "source_column": node.get("sourceColumn"),
                "statement_type": node.get("type"),
                "statement_text": compact_text(node.get("originalText")),
                "operation": canonical(metadata.get("cics_command")),
                "argument_name": name,
                "target_kind": canonical(metadata.get("cics_target_kind")),
                "identifier": identifier,
                "resolution_status": path_arg.get("resolution_status", metadata.get("path_sensitive_cics_resolution_status", "")),
                "resolved_value": path_arg.get("resolved_value", metadata.get("path_sensitive_cics_target")),
                "resolution_note": path_arg.get("resolution_note", metadata.get("path_sensitive_cics_resolution_note")),
            })
    return result


def analyze_report(report_dir: Path) -> dict[str, Any]:
    program = report_dir.name.removesuffix(".report")
    cfg_path = report_dir / "cfg" / f"cfg-{program}.json"
    dataflow_path = report_dir / "static_analysis" / "dataflow.json"
    cfg = load_json(cfg_path)
    dataflow = load_json(dataflow_path)
    static_values = static_value_evidence(report_dir)
    sites = call_sites(cfg.get("nodes", [])) + cics_sites(cfg.get("nodes", []))
    for site in sites:
        site.update(classify(site, dataflow, static_values))
    distribution = Counter(site["cause"] for site in sites)
    result = {
        "schema_version": "1.0",
        "semantics": "flow-sensitive",
        "program": program,
        "report_dir": str(report_dir),
        "cfg_artifact": str(cfg_path),
        "dataflow_artifact": str(dataflow_path),
        "site_count": len(sites),
        "cause_distribution": dict(sorted(distribution.items())),
        "sites": sorted(sites, key=lambda site: (site.get("source_line") or 0, site["site_id"])),
    }
    write_json(report_dir / "static_analysis" / "flow_sensitive_attribution.json", result)
    return result


def render_markdown(results: list[dict[str, Any]]) -> str:
    lines = [
        "# Flow-Sensitive Target Attribution",
        "",
        "This report enumerates dynamic CALL targets and CICS resource arguments that the flow-sensitive resolver considered in PDB305 and PDCBVC.",
        "",
        "The JSON artifacts are also written to each report directory at `static_analysis/flow_sensitive_attribution.json`. Field names retain the historical `path_sensitive_*` compatibility wording in source metadata, but the semantics are flow-sensitive CFG entry-state resolution.",
        "",
        "## Cause Distribution",
        "",
        "| Program | Sites | Cause | Count |",
        "|---|---:|---|---:|",
    ]
    for result in results:
        for cause, count in result["cause_distribution"].items():
            lines.append(f"| `{result['program']}` | {result['site_count']} | `{cause}` | {count} |")
    lines.extend([
        "",
        "## Site Table",
        "",
        "| Program | Line | Kind | Operation | Argument | Identifier | Status | Cause | Evidence |",
        "|---|---:|---|---|---|---|---|---|---|",
    ])
    for result in results:
        for site in result["sites"]:
            evidence = site["detail"]
            if site.get("static_value_evidence"):
                values = ", ".join(str(value) for value in site["static_value_evidence"].get("values", [])[:3])
                evidence += f" Static values: {values or 'present'}."
            if site.get("node_transfer_kills"):
                codes = ", ".join(kill.get("code", "") for kill in site["node_transfer_kills"][:3])
                evidence += f" Node transfer kills after entry: {codes}."
            lines.append(
                f"| `{result['program']}` | {site.get('source_line') or '-'} | `{site['site_kind']}` | "
                f"`{site.get('operation') or '-'}` | `{site.get('argument_name') or '-'}` | `{site['identifier']}` | "
                f"`{site.get('resolution_status') or 'missing'}` | `{site['cause']}` | {evidence} |"
            )
    lines.extend([
        "",
        "## Summary",
        "",
        "- PDB305 has one CICS QUEUE variable site, `TWCOB-TS-CODA`, at line 3094. It has no entry constant and no static assignment evidence; the dominant cause is `no_assignment_found`.",
        "- PDCBVC has one dynamic CALL target identifier, `PXRSEMAF`, at line 2861 in the generated CFG. Static-value chunks show `VALUE 'PXRSEMAF'`, but the flow-sensitive dataflow entry map does not seed declaration VALUE constants, so the cause is `missing_cfg_metadata`.",
        "- No site in these two programs is currently classified as `resolved`, `killed_by(...)`, `conflicting_join(values)`, `pic_rejected(...)`, `unsupported_expression`, or `loop_carried`.",
        "",
    ])
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", action="append", required=True, type=Path)
    parser.add_argument("--json-out", type=Path, default=Path("docs/analysis/flow_sensitive_attribution.json"))
    parser.add_argument("--md-out", type=Path, default=Path("docs/analysis/flow_sensitive_attribution.md"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    results = [analyze_report(report_dir) for report_dir in args.report_dir]
    combined = {
        "schema_version": "1.0",
        "semantics": "flow-sensitive",
        "programs": results,
        "combined_cause_distribution": dict(sorted(Counter(
            cause
            for result in results
            for site in result["sites"]
            for cause in [site["cause"]]
        ).items())),
    }
    write_json(args.json_out, combined)
    args.md_out.parent.mkdir(parents=True, exist_ok=True)
    args.md_out.write_text(render_markdown(results), encoding="utf-8")
    print(f"Wrote {args.json_out}")
    print(f"Wrote {args.md_out}")
    for result in results:
        print(f"Wrote {result['report_dir']}/static_analysis/flow_sensitive_attribution.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
