#!/usr/bin/env python3
"""
COBOL Structure Analyzer

Pre-processing script that reads raw COBOL source and existing JSON artifacts
to produce a structured `cobol_structure.json` artifact for downstream tasks.
"""

import sys
import json
import argparse
import re
from pathlib import Path
from collections import defaultdict


def _get_cfg(report_dir: Path, program_name: str) -> dict:
    cfg_path = report_dir / "cfg" / f"cfg-{program_name}.json"
    if cfg_path.exists():
        try:
            return json.loads(cfg_path.read_text(encoding='utf-8'))
        except (json.JSONDecodeError, OSError) as e:
            print(f"  [WARN] Failed to load CFG {cfg_path}: {e}", file=sys.stderr)
    return {}


def _get_data(report_dir: Path, program_name: str) -> dict:
    data_path = report_dir / "data_structures" / f"{program_name}-data.json"
    if data_path.exists():
        try:
            return json.loads(data_path.read_text(encoding='utf-8'))
        except (json.JSONDecodeError, OSError) as e:
            print(f"  [WARN] Failed to load data structures {data_path}: {e}", file=sys.stderr)
    return {}


def _build_paragraph_profiles(cfg: dict) -> dict:
    profiles = {}
    nodes = cfg.get('nodes', [])
    edges = cfg.get('edges', [])

    if not nodes:
        return profiles

    node_by_id = {n['id']: n for n in nodes}

    sw_children = defaultdict(list)
    fb_from = defaultdict(list)
    for e in edges:
        s, t = e.get('fromNodeID'), e.get('toNodeID')
        if not s or not t:
            continue
        if e.get('edgeType') == 'STARTS_WITH':
            sw_children[s].append(t)
        elif e.get('edgeType') == 'FOLLOWED_BY':
            fb_from[s].append(t)

    para_nodes = [n for n in nodes if n.get('type') == 'PARAGRAPH' and "/" not in n.get('name', '')]

    for pn in para_nodes:
        pid = pn['id']
        pname = pn.get('name', '')

        subgraph = {pid}
        queue = list(sw_children.get(pid, []))
        subgraph.update(queue)

        while queue:
            nid = queue.pop(0)
            for tgt in fb_from.get(nid, []):
                if tgt in subgraph:
                    continue
                if node_by_id.get(tgt, {}).get('type') == 'PARAGRAPH':
                    continue
                subgraph.add(tgt)
                queue.append(tgt)
            for tgt in sw_children.get(nid, []):
                if tgt not in subgraph:
                    subgraph.add(tgt)
                    queue.append(tgt)

        type_counts = defaultdict(int)
        for nid in subgraph:
            typ = node_by_id.get(nid, {}).get('type')
            if typ:
                type_counts[typ] += 1

        patterns = []
        if type_counts['EXEC_SQL'] > 0:
            patterns.append(f"DB2 access ({type_counts['EXEC_SQL']} SQL)")
        if type_counts['EXEC_CICS'] > 0:
            patterns.append(f"CICS operations ({type_counts['EXEC_CICS']} commands)")
        branches = type_counts['IF_BRANCH'] + type_counts['EVALUATE']
        if branches > 3:
            patterns.append(f"decision logic ({branches} branches)")
        if type_counts['PERFORM'] > 0:
            patterns.append(f"orchestrates {type_counts['PERFORM']} sub-procedures")
        
        # Simple heuristic
        other_types = sum(v for k, v in type_counts.items() if k not in ('MOVE', 'PARAGRAPH', 'PARAGRAPH_NAME'))
        if type_counts['MOVE'] > 5 and other_types < 5:
            patterns.append(f"data initialization ({type_counts['MOVE']} MOVEs)")
        
        if type_counts['READ'] > 0 or type_counts['WRITE'] > 0:
            patterns.append("file I/O")
        if type_counts['GOBACK'] > 0 or type_counts['STOP_RUN'] > 0:
            patterns.append("terminates execution")

        profiles[pname] = {
            "total_statements": len(subgraph),
            "type_counts": dict(type_counts),
            "structural_patterns": patterns
        }

    return profiles


def _build_88_conditions(data: dict) -> dict:
    conditions = {}

    def _walk(node, parent_name):
        level = node.get("levelNumber", 0)
        cname = node.get("name", "")
        if level == 88 and parent_name:
            raw = node.get("rawText", "")
            val_m = re.search(r"\bVALUE[S]?\s+(.+?)(?:\s*\.|$)", raw, re.IGNORECASE)
            vals = [val_m.group(1).strip()] if val_m else []
            conditions[cname] = {
                "parent": parent_name,
                "values": vals
            }
        else:
            pname = cname if level > 0 and cname != 'FILLER' else parent_name
            for child in node.get("children", []):
                _walk(child, pname)

    for r in data.get("children", []):
        _walk(r, None)

    return conditions


def _build_redefines(data: dict) -> list:
    redefines = []

    def _walk(node, parent_children):
        cname = node.get("name", "")
        if node.get("isRedefinition"):
            level = node.get("levelNumber")
            prev = None
            for sib in parent_children:
                if sib is node:
                    break
                if sib.get("levelNumber") == level:
                    prev = sib

            if prev:
                def get_pic(nr):
                    raw = nr.get("rawText", "")
                    m = re.search(r"\bPIC(?:TURE)?\s+([^\s.]+)", raw, re.IGNORECASE)
                    return m.group(1) if m else "-"

                redefines.append({
                    "redefining": cname,
                    "redefines": prev.get("name", ""),
                    "redefining_pic": get_pic(node),
                    "redefined_pic": get_pic(prev),
                    "level": level,
                    "byte_size": node.get("byteSize", 0)
                })
                
        children = node.get("children", [])
        for child in children:
            _walk(child, children)

    children = data.get("children", [])
    for r in children:
        _walk(r, children)

    return redefines


def _analyze_source(source_path: Path):
    divisions = {}
    sections = {}
    copy_statements = []

    if not source_path or not source_path.exists():
        return {"divisions": divisions, "sections": sections}, copy_statements, {}

    try:
        lines = source_path.read_text(errors='replace').splitlines()
    except OSError as e:
        print(f"  [WARN] Failed to read source {source_path}: {e}", file=sys.stderr)
        return {"divisions": divisions, "sections": sections}, copy_statements, {}

    current_div = None
    current_sec = None

    div_re = re.compile(r"^\s+(IDENTIFICATION|ENVIRONMENT|DATA|PROCEDURE)\s+DIVISION\b", re.IGNORECASE)
    sec_re = re.compile(r"^\s+([A-Za-z0-9_-]+)\s+SECTION\b", re.IGNORECASE)
    copy_re = re.compile(r"^\s+COPY\s+([A-Za-z0-9_-]+)", re.IGNORECASE)

    for idx, line in enumerate(lines, 1):
        if len(line) > 6 and line[6] in ('*', '/'):
            continue  # comment line

        text = line[6:72] if len(line) > 6 else line  # source area
        if not text.strip():
            continue

        # Division
        dm = div_re.search(text)
        if dm:
            div_name = dm.group(1).upper()
            if current_div and current_div in divisions:
                divisions[current_div]["end_line"] = idx - 1
            if current_sec and current_sec in sections:
                sections[current_sec]["end_line"] = idx - 1
            current_div = div_name
            current_sec = None
            divisions[current_div] = {"start_line": idx, "end_line": len(lines)}
            continue

        # Section
        sm = sec_re.search(text)
        if sm:
            sec_name = sm.group(1).upper()
            if current_sec and current_sec in sections:
                sections[current_sec]["end_line"] = idx - 1
            current_sec = sec_name
            sections[current_sec] = {"start_line": idx, "end_line": len(lines), "division": current_div}
            continue

        # Copy
        cm = copy_re.search(text)
        if cm:
            cp_name = cm.group(1).upper()
            replacing = None
            if "REPLACING" in text.upper():
                rm = re.search(r"REPLACING\s+(.+?)(?:\.|$)", text, re.IGNORECASE)
                if rm:
                    # e.g., ==A== BY ==B==  -> [["==A==", "==B=="]]
                    replaced_text = rm.group(1).strip()
                    replacing_pairs = []
                    for pair_m in re.finditer(r"(==.+?==|[A-Za-z0-9_-]+)\s+BY\s+(==.+?==|[A-Za-z0-9_-]+)", replaced_text, re.IGNORECASE):
                        replacing_pairs.append([pair_m.group(1), pair_m.group(2)])
                    replacing = replacing_pairs if replacing_pairs else replaced_text

            if current_div == "DATA":
                if current_sec == "WORKING-STORAGE":
                    impact = "missing variable definitions (WORKING-STORAGE)"
                elif current_sec == "LINKAGE":
                    impact = "missing CALL parameter types (LINKAGE SECTION)"
                else:
                    impact = f"missing data definitions ({current_sec or 'DATA'})"
            elif current_div == "PROCEDURE":
                impact = "missing inlined procedure logic (PROCEDURE DIVISION COPY)"
            elif current_div == "ENVIRONMENT":
                impact = "missing environment definitions"
            else:
                impact = "missing definitions"

            copy_statements.append({
                "copybook": cp_name,
                "line": idx,
                "division": current_div,
                "section": current_sec,
                "replacing": replacing,
                "impact": impact
            })

    # System copybooks
    known_sys = {}

    patterns = [
        (re.compile(r"^DFHCOMMAREA$", re.IGNORECASE), "CICS", "CICS communication area — EIBCALEN, EIBAID, EIBTRNID fields", ["EIBCALEN", "EIBAID", "EIBTRNID", "EIBDATE", "EIBTIME"], "CICS EIB field references will be unresolved in data dictionary"),
        (re.compile(r"^DFHEIBLK$", re.IGNORECASE), "CICS", "CICS communication area — EIBCALEN, EIBAID, EIBTRNID fields", ["EIBCALEN", "EIBAID", "EIBTRNID", "EIBDATE", "EIBTIME"], "CICS EIB field references will be unresolved in data dictionary"),
        (re.compile(r"^DFHAID$", re.IGNORECASE), "CICS", "CICS attention identifiers (PF keys)", ["DFHCLEAR", "DFHENTER"], "PF key checks will reference undefined variables"),
        (re.compile(r"^DFHBMSCA$", re.IGNORECASE), "CICS", "CICS BMS screen attributes", ["DFHBMUNP", "DFHBMASK"], "Screen attribute updates will reference undefined variables"),
        (re.compile(r"^SQLCA$", re.IGNORECASE), "DB2", "SQL communication area — SQLCODE, SQLERRM, SQLSTATE", ["SQLCODE", "SQLERRM", "SQLSTATE", "SQLERRD"], "SQLCODE checks will reference undefined variable"),
        (re.compile(r"^SQLDA$", re.IGNORECASE), "DB2", "SQL descriptor area", ["SQLDAID", "SQLDABC"], "SQL descriptor references will fail"),
        (re.compile(r"^DCL", re.IGNORECASE), "DB2", "DB2 DCLGEN table declaration", [], "Database host variables will be undefined")
    ]

    prog_base = source_path.stem.upper()

    for cs in copy_statements:
        name = cs["copybook"].upper()
        if name in known_sys:
            continue

        matched = False
        for pat, sys_nm, purp, fields, imp in patterns:
            if pat.search(name):
                known_sys[name] = {
                    "system": sys_nm,
                    "purpose": purp,
                    "typical_fields": fields,
                    "stub_impact": imp
                }
                matched = True
                break

        if not matched:
            if name.startswith(prog_base) and len(name) > len(prog_base):
                # likely BMS map
                known_sys[name] = {
                    "system": "CICS BMS",
                    "purpose": "BMS Map definition",
                    "typical_fields": [],
                    "stub_impact": "Screen fields will be unresolved"
                }

    return {"divisions": divisions, "sections": sections}, copy_statements, known_sys


def main():
    parser = argparse.ArgumentParser(description="Extract structural facts from COBOL source text and JSON artifacts.")
    parser.add_argument("report_dir", type=Path, help="Path to the analysis report directory")
    parser.add_argument("program_name", type=str, help="Name of the COBOL program")
    parser.add_argument("--source", type=Path, help="Path to original COBOL source file for text analysis", default=None)
    args = parser.parse_args()

    report_dir = args.report_dir
    program_name = args.program_name
    source_path = args.source

    cfg = _get_cfg(report_dir, program_name)
    data = _get_data(report_dir, program_name)

    # 1-3. Source-derived
    div_sec_map, copy_statements, known_sys = _analyze_source(source_path)

    # 4-6. JSON-derived
    conditions_88 = _build_88_conditions(data)
    redefines = _build_redefines(data)
    paragraph_profiles = _build_paragraph_profiles(cfg)

    output = {
        "divisions": div_sec_map.get("divisions", {}),
        "sections": div_sec_map.get("sections", {}),
        "copy_statements": copy_statements,
        "known_system_copybooks": known_sys,
        "conditions_88": conditions_88,
        "redefines": redefines,
        "paragraph_profiles": paragraph_profiles
    }

    out_file = report_dir / "cobol_structure.json"
    out_file.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f"Generated {out_file}")


if __name__ == "__main__":
    main()
