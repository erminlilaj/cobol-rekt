#!/usr/bin/env python3
"""
Knowledge Base Builder for COBOL Analysis

Transforms raw analysis artifacts into LLM-optimized documentation:
- 00_Executive_Summary.md: Stats, complexity, dialect
- 01_Logic_Narrative.md: Linear program flow story  
- 02_Data_Dictionary.md: Variable tables
- 03_Dependencies.yaml: SQL/CALL/CICS extraction
"""

import json
import re
import sys
import yaml
from pathlib import Path
from typing import Optional
from collections import defaultdict


class KnowledgeBaseBuilder:
    """Builds LLM-optimized knowledge base from analysis outputs."""
    
    def __init__(self, report_dir: Path, program_name: str, verbose: bool = False):
        self.report_dir = Path(report_dir)
        self.program_name = program_name
        self.verbose = verbose

        # Output directory - inside the report folder
        self.kb_dir = self.report_dir / "knowledge_base"

        # Cached data
        self._cfg_data = None
        self._data_structures = None
        self._comments = None
        self._enriched_comments = None
    
    def build(self) -> Path:
        """Build complete knowledge base. Returns output directory."""
        self.kb_dir.mkdir(parents=True, exist_ok=True)
        
        if self.verbose:
            print(f"[KB] Building knowledge base for {self.program_name}")
            print(f"[KB] Output: {self.kb_dir}")
        
        self._generate_executive_summary()
        self._generate_logic_narrative()
        self._generate_data_dictionary()
        self._generate_dependencies()
        
        if self.verbose:
            print(f"[KB] Complete: 4 files generated")
        
        return self.kb_dir
    
    # =========================================================================
    # 00_Executive_Summary.md
    # =========================================================================
    
    def _generate_executive_summary(self):
        """Generate executive summary with stats and complexity."""
        cfg = self._load_cfg()
        data = self._load_data_structures()
        
        # Calculate metrics
        node_count = len(cfg.get('nodes', [])) if cfg else 0
        edge_count = len(cfg.get('edges', [])) if cfg else 0
        
        # Count by type
        type_counts = defaultdict(int)
        for node in (cfg.get('nodes', []) if cfg else []):
            type_counts[node.get('type', 'UNKNOWN')] += 1
        
        # Variable count
        var_count = self._count_variables(data)
        
        # Complexity score (simple heuristic)
        complexity = self._calculate_complexity(cfg)
        
        content = f"""# Executive Summary: {self.program_name}

## Program Metrics

| Metric | Value |
|--------|-------|
| Total CFG Nodes | {node_count} |
| Total Edges | {edge_count} |
| Variables Defined | {var_count} |
| Complexity Score | {complexity} |

## Node Type Distribution

| Type | Count |
|------|-------|
"""
        _DISPLAY_NAMES = {
            'DIALECT': 'CICS/SQL block',
            'DIALECT_CONTAINER': 'CICS/SQL container',
        }
        for node_type, count in sorted(type_counts.items(), key=lambda x: -x[1])[:10]:
            display = _DISPLAY_NAMES.get(node_type, node_type)
            content += f"| {display} | {count} |\n"
        
        content += f"""
## Analysis Notes

- Generated from `{self.program_name}`
- See `01_Logic_Narrative.md` for program flow
- See `02_Data_Dictionary.md` for variable definitions
- See `03_Dependencies.yaml` for external calls
"""
        goto_count = type_counts.get('GOTO', 0)
        if goto_count > 10:
            content += f"\n> **Warning:** High GO TO count ({goto_count}) — program uses unstructured control flow. Review spaghetti code sections carefully.\n"

        # Dangling paragraph reference validation
        dangling = self._find_dangling_references(cfg)
        if dangling:
            content += f"\n## Validation Warnings\n\n"
            content += f"> **{len(dangling)} undefined paragraph reference(s) detected:**\n>\n"
            for d in dangling[:15]:
                content += f"> - `{d['type']} {d['name']}` (from `{d['from_para']}`)\n"
            if len(dangling) > 15:
                content += f"> - … and {len(dangling) - 15} more\n"
            content += "\n"

        output_path = self.kb_dir / "00_Executive_Summary.md"
        output_path.write_text(content, encoding='utf-8')
        
        if self.verbose:
            print(f"  [OK] 00_Executive_Summary.md ({node_count} nodes, complexity={complexity})")
    
    def _find_dangling_references(self, cfg: dict) -> list:
        """Return list of paragraph names referenced in GO TO / PERFORM that
        don't exist as nodes in the CFG.

        Each entry is a dict with keys: ``type`` (GO TO / PERFORM), ``name``
        (referenced paragraph), ``from_para`` (containing paragraph name).

        Common false-positive patterns are excluded:
        - Names ending in ``-EXIT`` (standard THRU-range exit labels)
        - Single-word names that are COBOL keywords (EXIT, CONTINUE, STOP)
        """
        if not cfg:
            return []

        _KEYWORD_SKIP = {'EXIT', 'CONTINUE', 'STOP', 'RETURN', 'PROGRAM', 'RUN'}

        # Build set of known paragraph / section names
        known: set = {
            n.get('name', '').upper()
            for n in cfg.get('nodes', [])
            if n.get('type') in ('PARAGRAPH', 'SECTION') and n.get('name')
        }

        # Map node id → containing paragraph name for context
        para_of: dict = {}
        for n in cfg.get('nodes', []):
            if n.get('type') in ('PARAGRAPH', 'SECTION'):
                para_of[n['id']] = n.get('name', '?')

        dangling: list = []
        seen: set = set()

        for node in cfg.get('nodes', []):
            original = node.get('originalText', '')
            node_type = node.get('type', '')
            container = para_of.get(node.get('id', ''), '?')

            refs: list = []

            # GO TO targets
            if 'GO TO' in original.upper() or node_type == 'GOTO':
                for m in re.finditer(r'\bGO\s+TO\s+([A-Za-z][A-Za-z0-9-]+)', original, re.IGNORECASE):
                    refs.append(('GO TO', m.group(1).upper()))

            # PERFORM targets (skip VARYING/UNTIL — those are inline loops)
            if node_type == 'PERFORM' and 'VARYING' not in original.upper() and 'UNTIL' not in original.upper():
                m = re.search(r'\bPERFORM\s+([A-Za-z][A-Za-z0-9-]+)', original, re.IGNORECASE)
                if m:
                    refs.append(('PERFORM', m.group(1).upper()))

            for ref_type, ref_name in refs:
                if (ref_name.endswith('-EXIT')
                        or ref_name in _KEYWORD_SKIP
                        or ref_name in seen
                        or ref_name in known):
                    continue
                seen.add(ref_name)
                dangling.append({'type': ref_type, 'name': ref_name, 'from_para': container})

        return dangling

    def _calculate_complexity(self, cfg: dict) -> str:
        """Calculate complexity score based on CFG structure."""
        if not cfg:
            return "Unknown"
        
        nodes = cfg.get('nodes', [])
        edges = cfg.get('edges', [])
        
        # Cyclomatic-ish: edges - nodes + 2
        cyclomatic = max(1, len(edges) - len(nodes) + 2)
        
        if cyclomatic <= 5:
            return f"Low ({cyclomatic})"
        elif cyclomatic <= 15:
            return f"Medium ({cyclomatic})"
        else:
            return f"High ({cyclomatic})"
    
    def _count_variables(self, data: dict) -> int:
        """Recursively count variables in data structures."""
        if not data:
            return 0
        
        count = 0
        def count_recursive(node):
            nonlocal count
            if node.get('name') and node.get('name') != '[ROOT]':
                count += 1
            for child in node.get('children', []):
                count_recursive(child)
        
        count_recursive(data)
        return count
    
    # =========================================================================
    # 01_Logic_Narrative.md
    # =========================================================================
    
    def _generate_logic_narrative(self):
        """Generate linear narrative of program flow.

        When ``comments_enriched.json`` is present (produced by step7b), each
        paragraph's comment block is rendered bilingually:

            > **<English translation>**
            >
            > *Original: <Italian source text>*

        When only ``comments.json`` is available (enrichment was skipped or
        failed), the raw Italian text is shown as plain blockquotes — identical
        to the previous behaviour.

        If a translation is identical to the original (e.g. code-like strings
        such as ``PERFORM VARYING I FROM 1 BY 1``), the bilingual display is
        skipped and the text is shown only once.
        """
        cfg = self._load_cfg()

        if not cfg:
            content = f"# Logic Narrative: {self.program_name}\n\n*No CFG data available.*\n"
            (self.kb_dir / "01_Logic_Narrative.md").write_text(content, encoding='utf-8')
            return

        nodes = {n['id']: n for n in cfg.get('nodes', [])}
        edges = cfg.get('edges', [])

        # Build adjacency list
        outgoing = defaultdict(list)
        incoming = defaultdict(list)
        for edge in edges:
            from_id = edge.get('fromNodeID')
            to_id = edge.get('toNodeID')
            edge_type = edge.get('edgeType', '')
            outgoing[from_id].append((to_id, edge_type))
            incoming[to_id].append((from_id, edge_type))

        # Find entry points (nodes with no incoming FOLLOWED_BY edges)
        entry_points = []
        for node_id in nodes:
            if not any(et == 'FOLLOWED_BY' for _, et in incoming.get(node_id, [])):
                n = nodes[node_id]
                if n.get('type') in ('PARAGRAPH', 'SECTION', 'PROCEDURE_DIVISION_BODY'):
                    entry_points.append(node_id)

        content = f"""# Logic Narrative: {self.program_name}

This document describes the program flow in a linear, readable format.

"""

        # Load comment sources once — enriched (English) and raw (Italian)
        comments = self._load_comments()
        enriched = self._load_enriched_comments()

        # --- Program Overview block ---
        if comments and '_PROGRAM_SUMMARY' in comments:
            content += "## Program Overview\n\n"
            content += self._format_comment_block(
                '_PROGRAM_SUMMARY', comments, enriched
            )
            content += "\n---\n\n"
        else:
            content += "---\n\n"

        # Process paragraphs/sections
        paragraphs = [n for n in cfg.get('nodes', [])
                      if n.get('type') in ('PARAGRAPH', 'SECTION')]

        for para in paragraphs:
            para_name = para.get('name', para.get('label', 'Unknown'))
            content += f"## {para_name}\n\n"

            # Inject comments — bilingual when translation is available
            para_key = para_name.upper()
            comment_block = self._format_comment_block(para_key, comments, enriched)
            if comment_block:
                content += comment_block
                content += "\n"

            # Get statements in this paragraph
            statements = self._get_paragraph_statements(para['id'], nodes, outgoing)

            for stmt in statements:
                node = nodes.get(stmt)
                if not node:
                    continue

                original_text = node.get('originalText', '')
                node_type = node.get('type', '')

                # Fix 3: skip DIALECT_CONTAINER wrapper nodes whose originalText
                # is the raw sequence marker (not an actual EXEC statement)
                if original_text.strip().startswith('_DIALECT_'):
                    continue

                # Fix 2: skip SENTENCE wrappers that have child statement nodes —
                # the children will be output separately, avoiding duplication
                if node_type == 'SENTENCE':
                    children_via_starts_with = [
                        nid for nid, et in outgoing.get(node['id'], [])
                        if et == 'STARTS_WITH'
                    ]
                    if children_via_starts_with:
                        continue

                # Format based on type
                if node_type in ('IF', 'CONDITION'):
                    content += self._format_decision(node, nodes, outgoing)
                elif node_type == 'EVALUATE':
                    content += self._format_evaluate(node, nodes, outgoing)
                elif 'EXEC' in original_text.upper():
                    content += self._format_exec_block(node)
                elif node_type in ('MOVE', 'SENTENCE', 'COMPUTE', 'ADD', 'SUBTRACT'):
                    # Simple statement - just show it
                    clean_text = self._clean_statement(original_text)
                    if clean_text:
                        content += f"- `{clean_text}`\n"
                elif node_type in ('PERFORM',):
                    upper_orig = original_text.upper()
                    if 'VARYING' in upper_orig or re.match(r'\s*PERFORM\s+UNTIL\b', upper_orig):
                        loop_desc = self._extract_perform_loop(original_text)
                        content += f"- **PERFORM** (loop) `{loop_desc}`\n"
                    else:
                        target = self._extract_perform_target(original_text)
                        content += f"- **PERFORM** `{target}`\n"
            
            content += "\n"
        
        output_path = self.kb_dir / "01_Logic_Narrative.md"
        output_path.write_text(content, encoding='utf-8')
        
        if self.verbose:
            print(f"  [OK] 01_Logic_Narrative.md ({len(paragraphs)} paragraphs)")
    
    def _format_comment_block(
        self,
        para_key: str,
        comments: Optional[dict],
        enriched: dict,
    ) -> str:
        """Render comment blockquote(s) for *para_key*.

        Rendering rules (in priority order):

        1. **Bilingual** — when ``comments_enriched.json`` has a successful
           translation for *para_key* AND the translated English text differs
           from the original Italian (i.e. translation actually changed the
           text):

               > **<English translation>**
               >
               > *Original: <joined Italian lines>*

        2. **Italian-only fallback** — when no enriched translation exists, or
           the entry has ``translation_failed: true``, or the English is
           identical to the Italian (code-heavy comments that MarianMT passes
           through unchanged):

               > <Italian line 1>
               > <Italian line 2>

        3. **Empty string** — when *para_key* has no comments at all.

        Args:
            para_key:  Paragraph name in UPPER CASE (key into *comments*).
            comments:  Raw Italian comments dict loaded from ``comments.json``.
            enriched:  Translated entries loaded from ``comments_enriched.json``
                       (may be empty if enrichment was skipped).

        Returns:
            Markdown blockquote string (may be empty).
        """
        raw_lines: list[str] = (comments or {}).get(para_key, [])
        entry: dict = enriched.get(para_key, {})
        english: str = entry.get('english', '').strip()
        failed: bool = bool(entry.get('translation_failed'))

        if english and not failed:
            # Join Italian lines for compact display in the "Original:" line
            original_joined = ' '.join(raw_lines).strip()
            # Skip bilingual display when translation didn't change the text
            # (happens with code-heavy comments like "PERFORM VARYING I FROM 1")
            if english.lower() != original_joined.lower():
                result = f"> **{english}**\n"
                if original_joined:
                    result += f">\n> *Original: {original_joined}*\n"
                return result
            # Fall through to Italian-only display
        if raw_lines:
            return ''.join(f"> {line}\n" for line in raw_lines)
        return ''

    def _get_paragraph_statements(self, para_id: str, nodes: dict, outgoing: dict) -> list:
        """Get ordered list of statement IDs in a paragraph."""
        statements = []
        visited = set()
        
        def traverse(node_id):
            if node_id in visited:
                return
            visited.add(node_id)
            statements.append(node_id)
            
            # Follow FOLLOWED_BY and STARTS_WITH edges
            for next_id, edge_type in outgoing.get(node_id, []):
                if edge_type in ('FOLLOWED_BY', 'STARTS_WITH'):
                    next_node = nodes.get(next_id, {})
                    # Don't cross paragraph boundaries
                    if next_node.get('type') not in ('PARAGRAPH', 'SECTION'):
                        traverse(next_id)
        
        traverse(para_id)
        return statements
    
    def _format_decision(self, node: dict, nodes: dict, outgoing: dict) -> str:
        """Format IF/CONDITION as structured Markdown."""
        original = node.get('originalText', '')
        condition = self._extract_condition(original)
        
        result = f"\n### Decision Point\n"
        result += f"- **Condition:** `{condition}`\n"
        
        # Find true/false paths
        for next_id, edge_type in outgoing.get(node['id'], []):
            next_node = nodes.get(next_id, {})
            next_name = next_node.get('name', next_node.get('label', 'Unknown'))
            if 'TRUE' in edge_type.upper() or 'YES' in next_name.upper():
                result += f"- **True Path:** → `{next_name}`\n"
            elif 'FALSE' in edge_type.upper() or 'NO' in next_name.upper():
                result += f"- **False Path:** → `{next_name}`\n"
        
        result += "\n"
        return result
    
    def _format_evaluate(self, node: dict, nodes: dict, outgoing: dict) -> str:
        """Format EVALUATE as structured Markdown."""
        original = node.get('originalText', '')
        result = f"\n### EVALUATE Block\n```cobol\n{original[:200]}...\n```\n\n"
        return result
    
    # SQL structural markers that belong to the DATA DIVISION — not executable
    # statements. Filter them from the procedure narrative (Fix 6).
    _NON_EXEC_SQL_MARKERS = (
        'BEGIN DECLARE SECTION', 'END DECLARE SECTION', 'INCLUDE', 'WHENEVER',
    )

    def _format_exec_block(self, node: dict) -> str:
        """Format EXEC SQL/CICS blocks."""
        original = node.get('originalText', '')
        upper = original.upper()
        if 'EXEC SQL' in upper:
            # Skip DATA DIVISION structural markers — not executable statements
            for marker in self._NON_EXEC_SQL_MARKERS:
                if marker in upper:
                    return ''
            return f"- **SQL:** `{self._clean_statement(original)}`\n"
        elif 'EXEC CICS' in upper:
            return f"- **CICS:** `{self._clean_statement(original)}`\n"
        return f"- `{self._clean_statement(original)}`\n"
    
    def _clean_statement(self, text: str) -> str:
        """Clean up COBOL statement for display."""
        if not text:
            return ""
        # Remove newlines, collapse whitespace
        clean = ' '.join(text.split())
        # Truncate if too long
        if len(clean) > 300:
            clean = clean[:297] + "..."
        return clean
    
    def _extract_condition(self, text: str) -> str:
        """Extract condition from IF statement."""
        match = re.search(r'IF\s+(.+?)(?:THEN|$)', text, re.IGNORECASE | re.DOTALL)
        if match:
            return self._clean_statement(match.group(1))
        return self._clean_statement(text)
    
    def _extract_perform_target(self, text: str) -> str:
        """Extract target paragraph from PERFORM."""
        match = re.search(r'PERFORM\s+([A-Za-z0-9-]+(?:\s+(?:THRU|THROUGH)\s+[A-Za-z0-9-]+)?)', text, re.IGNORECASE)
        if match:
            return match.group(1)
        return "Unknown"

    def _extract_perform_loop(self, text: str) -> str:
        """Extract PERFORM VARYING/UNTIL loop description preserving bounds.

        Returns the full clause after PERFORM (e.g.
        ``VARYING IX FROM 1 BY 1 UNTIL IX > LENGTH OF WS-STRIN``).
        """
        clean = self._clean_statement(text)
        m = re.match(r'PERFORM\s+(.*)', clean, re.IGNORECASE)
        return m.group(1).strip() if m else clean

    # =========================================================================
    # 02_Data_Dictionary.md
    # =========================================================================
    
    def _generate_data_dictionary(self):
        """Generate Markdown table of variables."""
        data = self._load_data_structures()
        
        if not data:
            content = f"# Data Dictionary: {self.program_name}\n\n*No data structure information available.*\n"
            (self.kb_dir / "02_Data_Dictionary.md").write_text(content, encoding='utf-8')
            return
        
        content = f"""# Data Dictionary: {self.program_name}

"""
        # Check for degraded data structures from parse diagnostics
        diag = self._load_parse_diagnostics()
        if diag.get("data_structures_degraded"):
            content += "> **Warning:** Data structures were unavailable (lenient fallback). This dictionary may be incomplete.\n\n"
        skipped = diag.get("skipped_variables", [])
        if skipped:
            content += f"> **Note:** {len(skipped)} variable(s) skipped due to parse errors: "
            content += ", ".join(sv["variable"] for sv in skipped[:10])
            if len(skipped) > 10:
                content += f" ... and {len(skipped) - 10} more"
            content += "\n\n"

        content += """## Working Storage Variables

| Level | Variable Name | Picture Clause | Data Type | Section |
|:------|:--------------|:---------------|:----------|:--------|
"""
        
        # Flatten and sort variables
        variables = []
        self._flatten_variables(data, variables)
        
        # Filter to WORKING_STORAGE and sort by level
        ws_vars = [v for v in variables if v.get('section') == 'WORKING_STORAGE']
        for var in ws_vars:
            level = var.get('level', '')
            name = var.get('name', '')
            pic = self._extract_pic(var.get('raw', ''))
            dtype = var.get('dataType', '')
            section = var.get('section', '')
            content += f"| {level:02d} | {name} | {pic} | {dtype} | {section} |\n"

        # Linkage section
        ls_vars = [v for v in variables if v.get('section') == 'LINKAGE_SECTION']
        if ls_vars:
            content += f"\n## Linkage Section Variables\n\n"
            content += "| Level | Variable Name | Picture Clause | Data Type |\n"
            content += "|:------|:--------------|:---------------|:----------|\n"
            for var in ls_vars:
                level = var.get('level', '')
                name = var.get('name', '')
                pic = self._extract_pic(var.get('raw', ''))
                dtype = var.get('dataType', '')
                content += f"| {level:02d} | {name} | {pic} | {dtype} |\n"
        
        # Load cobol_structure.json to append 88-level and REDEFINES info
        struct_path = self.report_dir / "cobol_structure.json"
        if struct_path.exists():
            try:
                struct_data = json.loads(struct_path.read_text('utf-8'))
                
                conds = struct_data.get("conditions_88", {})
                if conds:
                    content += "\n## Condition Names (88-Level)\n\n"
                    content += "| Condition | Parent Variable | Value(s) |\n"
                    content += "|-----------|----------------|----------|\n"
                    for cname, info in conds.items():
                        vals = ", ".join(info.get('values', []))
                        parent = info.get('parent', '')
                        content += f"| {cname} | {parent} | {vals} |\n"
                        
                redefs = struct_data.get("redefines", [])
                if redefs:
                    content += "\n## REDEFINES Relationships\n\n"
                    content += "| Redefining | Redefines | Interpretation |\n"
                    content += "|------------|-----------|----------------|\n"
                    for rd in redefs:
                        reding = rd.get('redefining', '')
                        rededing = rd.get('redefines', '')
                        reding_pic = rd.get('redefining_pic', '-')
                        rededing_pic = rd.get('redefined_pic', '-')
                        size = rd.get('byte_size', '')
                        sz_str = f"Same {size} bytes" if size else "Same bytes"
                        content += f"| {reding} (PIC {reding_pic}) | {rededing} (PIC {rededing_pic}) | {sz_str} |\n"
            except (json.JSONDecodeError, KeyError, TypeError) as e:
                print(f"  [WARN] Failed to load cobol_structure.json: {e}", file=sys.stderr)

        output_path = self.kb_dir / "02_Data_Dictionary.md"
        output_path.write_text(content, encoding='utf-8')
        
        if self.verbose:
            print(f"  [OK] 02_Data_Dictionary.md ({len(variables)} variables)")
    
    def _flatten_variables(self, node: dict, result: list, level: int = 0):
        """Recursively flatten variable tree."""
        if node.get('name') and node.get('name') != '[ROOT]':
            result.append({
                'level': node.get('levelNumber', level),
                'name': node.get('name', ''),
                'raw': node.get('rawText', ''),
                'dataType': node.get('dataType', ''),
                'section': node.get('sourceSection', '')
            })
        
        for child in node.get('children', []):
            self._flatten_variables(child, result, level + 1)
    
    def _extract_pic(self, raw_text: str) -> str:
        """Extract PIC clause from raw text."""
        match = re.search(r'PIC(?:TURE)?\s+([^\s.]+)', raw_text, re.IGNORECASE)
        if match:
            return match.group(1)
        return "-"
    
    # =========================================================================
    # 03_Dependencies.yaml
    # =========================================================================
    
    def _generate_dependencies(self):
        """Generate YAML of external dependencies."""
        cfg = self._load_cfg()
        
        deps = {
            'program': self.program_name,
            'database': {
                'tables_read': [],
                'tables_updated': [],
                'sql_statements': []
            },
            'calls': [],
            'cics': [],
            'cics_calls': [],
        }
        
        var_values = self._load_variable_values()

        # Node types that represent individual statements (not containers).
        # PARAGRAPH/SENTENCE/PARAGRAPHS/PROCEDURE_DIVISION_BODY nodes contain
        # the full block text and would cause over-extraction if scanned.
        _ATOMIC_TYPES = {
            'CALL', 'EXEC_SQL', 'EXEC_CICS',
            'DIALECT', 'DIALECT_CONTAINER',  # CICS/SQL in Che4z dialect nodes
            'MOVE', 'PERFORM', 'IF_BRANCH', 'EVALUATE',
            'GOTO', 'INITIALIZE', 'STOP_RUN', 'GOBACK',
        }

        if cfg:
            for node in cfg.get('nodes', []):
                node_type = node.get('type', '')
                original = node.get('originalText', '').upper()

                # SQL detection — only on statement-level nodes
                if 'EXEC SQL' in original and node_type in _ATOMIC_TYPES:
                    # Flag dynamic SQL (PREPARE / EXECUTE IMMEDIATE)
                    if self._is_dynamic_sql(original):
                        deps['database']['dynamic_sql'] = True
                    else:
                        sql_stmt = self._extract_sql_info(original)
                        if sql_stmt:
                            deps['database']['sql_statements'].append(sql_stmt)
                            tables = self._extract_tables(original)
                            if 'SELECT' in original or 'FETCH' in original:
                                deps['database']['tables_read'].extend(tables)
                            elif ('UPDATE' in original or 'INSERT' in original
                                  or 'DELETE' in original):
                                deps['database']['tables_updated'].extend(tables)

                # CALL detection — only on CALL-type nodes to avoid over-extraction
                # from PARAGRAPH/SENTENCE container nodes (R5.2)
                if 'CALL' in original and node_type == 'CALL':
                    target = self._extract_literal_call_target(original)
                    using_params = self._extract_call_using(original)
                    if target:
                        existing = [c.get('target') for c in deps['calls']]
                        if target not in existing:
                            entry = {'target': target}
                            if using_params:
                                entry['using'] = using_params
                            deps['calls'].append(entry)
                    else:
                        # Dynamic CALL: CALL <variable-name>
                        dyn_m = re.search(
                            r'\bCALL\s+([A-Za-z][A-Za-z0-9_-]*)\b', original, re.IGNORECASE
                        )
                        if dyn_m:
                            var_name = dyn_m.group(1).upper()
                            known_vals = var_values.get(var_name, [])
                            if known_vals:
                                for val in known_vals:
                                    resolved = val.strip("'\"").upper()
                                    if resolved and resolved not in [
                                        c.get('target') for c in deps['calls']
                                    ]:
                                        call_entry: dict = {
                                            'target': resolved,
                                            'source': 'dynamic',
                                            'variable': var_name,
                                        }
                                        if using_params:
                                            call_entry['using'] = using_params
                                        deps['calls'].append(call_entry)
                            else:
                                unknown_entry: dict = {
                                    'target': 'UNKNOWN',
                                    'source': 'dynamic',
                                    'variable': var_name,
                                }
                                if using_params:
                                    unknown_entry['using'] = using_params
                                if unknown_entry not in deps['calls']:
                                    deps['calls'].append(unknown_entry)

                # CICS detection — only on statement-level nodes
                if 'EXEC CICS' in original and node_type in _ATOMIC_TYPES:
                    cics_cmd = self._extract_cics_command(original)
                    if cics_cmd:
                        deps['cics'].append(cics_cmd)
                    # Extract PROGRAM() target for LINK and XCTL commands
                    if cics_cmd in ('LINK', 'XCTL'):
                        cics_prog = self._extract_cics_program(original)
                        if cics_prog:
                            deps['cics_calls'].append({'command': cics_cmd, 'target': cics_prog})
                        else:
                            # Indirect target: PROGRAM(VARIABLE-NAME)
                            # Resolve via variable_values.json
                            prog_var = self._extract_cics_program_variable(original)
                            if prog_var:
                                known_vals = var_values.get(prog_var, [])
                                for val in known_vals:
                                    resolved = val.strip("'\"").upper()
                                    if resolved:
                                        deps['cics_calls'].append({
                                            'command': cics_cmd,
                                            'target': resolved,
                                            'source': 'indirect_variable',
                                            'variable': prog_var,
                                        })

        # Deduplicate
        deps['database']['tables_read'] = sorted(set(deps['database']['tables_read']))
        deps['database']['tables_updated'] = sorted(set(deps['database']['tables_updated']))
        deps['database']['sql_statements'] = sorted(set(deps['database']['sql_statements']))
        deps['cics'] = sorted(set(deps['cics']))
        # Deduplicate cics_calls by (command, target) key
        _seen_cics_calls: set = set()
        _deduped_cics_calls: list = []
        for _e in deps['cics_calls']:
            _key = (_e.get('command'), _e.get('target'))
            if _key not in _seen_cics_calls:
                _seen_cics_calls.add(_key)
                _deduped_cics_calls.append(_e)
        deps['cics_calls'] = _deduped_cics_calls

        # Remove empty sections
        if not deps['database']['tables_read'] and not deps['database']['tables_updated']:
            del deps['database']
        if not deps['calls']:
            del deps['calls']
        if not deps['cics']:
            del deps['cics']
        if not deps['cics_calls']:
            del deps['cics_calls']
        
        output_path = self.kb_dir / "03_Dependencies.yaml"
        output_path.write_text(yaml.dump(deps, default_flow_style=False, sort_keys=False), encoding='utf-8')
        
        if self.verbose:
            print(f"  [OK] 03_Dependencies.yaml")
    
    def _extract_sql_info(self, text: str) -> Optional[str]:
        """Extract SQL statement type."""
        for keyword in ['SELECT', 'INSERT', 'UPDATE', 'DELETE', 'OPEN', 'FETCH', 'CLOSE']:
            if keyword in text:
                return keyword
        return None
    
    def _is_dynamic_sql(self, text: str) -> bool:
        """Return True if the SQL statement uses dynamic SQL (PREPARE/EXECUTE IMMEDIATE)."""
        return bool(re.search(r'\b(PREPARE|EXECUTE\s+IMMEDIATE)\b', text, re.IGNORECASE))

    def _extract_tables(self, text: str) -> list:
        """Extract table names from SQL. Tries sqlparse first, falls back to regex."""
        result = self._extract_tables_sqlparse(text)
        if result is not None:
            return result
        return self._extract_tables_regex(text)

    def _extract_tables_sqlparse(self, text: str) -> Optional[list]:
        """Extract table names using sqlparse token walking.

        Handles JOINs, subqueries, and CTEs. Returns None if sqlparse is
        unavailable or raises an exception (caller falls back to regex).
        """
        try:
            import sqlparse                    # noqa: PLC0415
            from sqlparse import tokens as T  # noqa: PLC0415
        except ImportError:
            return None

        # Strip EXEC SQL / END-EXEC wrappers; replace COBOL host variables
        sql = re.sub(r'EXEC\s+SQL\b', '', text, flags=re.IGNORECASE)
        sql = re.sub(r'\bEND-EXEC\b', '', sql, flags=re.IGNORECASE)
        sql = re.sub(r':[A-Za-z][A-Za-z0-9_-]*', 'COBOL_HOST_VAR', sql)

        # Collect CTE alias names so we don't list them as tables
        cte_names = {m.upper() for m in re.findall(r'\b(\w+)\s+AS\s*\(', sql, re.IGNORECASE)}

        # Keywords that introduce a table name
        _TABLE_INTRO = {'FROM', 'JOIN', 'INTO', 'UPDATE'}
        # JOIN subtypes that are NOT table introductors
        _JOIN_MODS = {'INNER', 'LEFT', 'RIGHT', 'FULL', 'OUTER', 'CROSS', 'NATURAL'}

        tables: list[str] = []
        try:
            for stmt in sqlparse.parse(sql.strip()):
                flat = list(stmt.flatten())
                i = 0
                while i < len(flat):
                    tok = flat[i]
                    ttype = tok.ttype
                    val = tok.normalized.upper()

                    if ttype in (T.Keyword, T.Keyword.DML) and val in _TABLE_INTRO:
                        # Scan forward for next non-whitespace token
                        j = i + 1
                        while j < len(flat):
                            nt = flat[j]
                            if nt.ttype in (T.Text.Whitespace, T.Newline,
                                            T.Text.Whitespace.Newline):
                                j += 1
                                continue
                            # Skip JOIN modifier keywords (INNER, LEFT …)
                            nval = nt.normalized.upper()
                            if nt.ttype in (T.Keyword, T.Keyword.DML) and nval in _JOIN_MODS:
                                j += 1
                                continue
                            # If another keyword, stop (e.g. INTO after INSERT … VALUES)
                            if nt.ttype in (T.Keyword, T.Keyword.DML, T.Punctuation):
                                break
                            if nt.ttype in (T.Name, T.Literal.String.Single):
                                name = nval.strip("'\"")
                                if (name and name not in cte_names
                                        and name != 'COBOL_HOST_VAR'
                                        and not name.startswith('COBOL_')):
                                    tables.append(name)
                            break
                    i += 1
        except (ValueError, TypeError, AttributeError) as e:
            return None

        return tables

    def _extract_tables_regex(self, text: str) -> list:
        """Regex-based table extraction (fallback when sqlparse unavailable)."""
        tables = []
        tables.extend(re.findall(r'FROM\s+([A-Za-z0-9_]+)', text, re.IGNORECASE))
        tables.extend(re.findall(r'JOIN\s+([A-Za-z0-9_]+)', text, re.IGNORECASE))
        m = re.search(r'INTO\s+([A-Za-z0-9_]+)', text, re.IGNORECASE)
        if m:
            tables.append(m.group(1))
        m = re.search(r'UPDATE\s+([A-Za-z0-9_]+)', text, re.IGNORECASE)
        if m:
            tables.append(m.group(1))
        return tables

    def _extract_literal_call_target(self, text: str) -> Optional[str]:
        """Extract CALL target — only literal (quoted) targets."""
        match = re.search(r"CALL\s+['\"]([A-Za-z0-9_-]+)['\"]", text, re.IGNORECASE)
        if match:
            return match.group(1)
        return None
    
    def _extract_cics_command(self, text: str) -> Optional[str]:
        """Extract CICS command type."""
        match = re.search(r'EXEC\s+CICS\s+([A-Za-z]+)', text, re.IGNORECASE)
        if match:
            return match.group(1)
        return None

    def _extract_cics_program(self, text: str) -> Optional[str]:
        """Extract PROGRAM() argument from EXEC CICS LINK/XCTL statements.

        Returns the literal program name (without quotes) when PROGRAM() uses a
        quoted string.  Returns None when PROGRAM() uses a variable — see
        ``_extract_cics_program_variable`` for that case.
        """
        match = re.search(r"PROGRAM\s*\(\s*['\"]([^'\"]+)['\"]\s*\)", text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return None

    def _extract_cics_program_variable(self, text: str) -> Optional[str]:
        """Extract the variable name from PROGRAM(VAR) in CICS LINK/XCTL.

        Returns the variable name (uppercase) when PROGRAM() contains an
        unquoted identifier.  Returns None when PROGRAM() contains a quoted
        literal (handled by ``_extract_cics_program``).
        """
        # Match PROGRAM( followed by an unquoted identifier )
        match = re.search(
            r"PROGRAM\s*\(\s*(?!['\"])([A-Za-z][A-Za-z0-9_-]*)\s*\)",
            text, re.IGNORECASE,
        )
        if match:
            return match.group(1).upper()
        return None

    def _extract_call_using(self, text: str) -> list:
        """Extract USING parameter names from a CALL statement (uppercase text).

        Returns a list of variable names appearing after the USING keyword.
        Stops at BY REFERENCE/VALUE/CONTENT, END-CALL, or end of text.
        Filters out COBOL syntactic keywords.
        """
        m = re.search(
            r'\bUSING\b(.+?)(?:\bBY\s+(?:REFERENCE|VALUE|CONTENT)\b|\bEND-CALL\b|$)',
            text, re.IGNORECASE | re.DOTALL,
        )
        if not m:
            return []
        _NOISE = {'BY', 'REFERENCE', 'VALUE', 'CONTENT', 'ADDRESS', 'OF', 'LENGTH', 'USING'}
        params = re.findall(r'\b([A-Z][A-Z0-9-]+)\b', m.group(1).upper())
        return [p for p in params if p not in _NOISE]
    
    # =========================================================================
    # Data Loading
    # =========================================================================
    
    def _load_variable_values(self) -> dict:
        """Load variable_values.json → {VAR_NAME: [val, ...]}. Returns {} if absent."""
        path = self.report_dir / "variable_values.json"
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            if isinstance(data, list):
                return {entry[0].upper(): entry[1] for entry in data if len(entry) == 2}
        except (json.JSONDecodeError, OSError) as e:
            print(f"  [WARN] Failed to load variable_values.json: {e}", file=sys.stderr)
        return {}

    def _load_cfg(self) -> Optional[dict]:
        """Load CFG JSON."""
        if self._cfg_data is not None:
            return self._cfg_data
        
        cfg_path = self.report_dir / "cfg" / f"cfg-{self.program_name}.json"
        if cfg_path.exists():
            try:
                self._cfg_data = json.loads(cfg_path.read_text(encoding='utf-8'))
                return self._cfg_data
            except (json.JSONDecodeError, OSError) as e:
                print(f"  [WARN] Failed to load CFG: {e}", file=sys.stderr)
        return None
    
    def _load_parse_diagnostics(self) -> dict:
        """Load parse_diagnostics.json. Returns empty dict if absent."""
        path = self.report_dir / "parse_diagnostics.json"
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding='utf-8'))
        except (json.JSONDecodeError, OSError):
            return {}

    def _load_data_structures(self) -> Optional[dict]:
        """Load data structures JSON."""
        if self._data_structures is not None:
            return self._data_structures
        
        data_path = self.report_dir / "data_structures" / f"{self.program_name}-data.json"
        if data_path.exists():
            try:
                self._data_structures = json.loads(data_path.read_text(encoding='utf-8'))
                return self._data_structures
            except (json.JSONDecodeError, OSError) as e:
                print(f"  [WARN] Failed to load data structures: {e}", file=sys.stderr)
        return None
    
    def _load_comments(self) -> Optional[dict]:
        """Load raw Italian comments from ``comments.json``."""
        if self._comments is not None:
            return self._comments

        comments_path = self.report_dir / "comments.json"
        if comments_path.exists():
            try:
                self._comments = json.loads(comments_path.read_text(encoding='utf-8'))
                return self._comments
            except (json.JSONDecodeError, OSError) as e:
                print(f"  [WARN] Failed to load comments: {e}", file=sys.stderr)
        return None

    def _load_enriched_comments(self) -> dict:
        """Load translated comments from ``comments_enriched.json``.

        Returns an empty dict when the file is absent (e.g. enrichment was
        skipped via ``--no-comment-enrichment``) so callers can always treat
        the return value as a plain dict without None-checks.
        """
        if self._enriched_comments is not None:
            return self._enriched_comments

        path = self.report_dir / "comments_enriched.json"
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding='utf-8'))
                self._enriched_comments = data if isinstance(data, dict) else {}
            except (json.JSONDecodeError, OSError) as e:
                print(f"  [WARN] Failed to load enriched comments: {e}", file=sys.stderr)
                self._enriched_comments = {}
        else:
            self._enriched_comments = {}

        return self._enriched_comments


def build_knowledge_base(report_dir: Path, program_name: str, verbose: bool = True) -> Path:
    """Convenience function to build knowledge base."""
    builder = KnowledgeBaseBuilder(report_dir, program_name, verbose)
    return builder.build()


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 3:
        print("Usage: python knowledge_base_builder.py <report_dir> <program_name>")
        print("Example: python knowledge_base_builder.py out/report/VAR.cbl.report VAR.cbl")
        sys.exit(1)
    
    report_dir = Path(sys.argv[1])
    program_name = sys.argv[2]
    
    kb_path = build_knowledge_base(report_dir, program_name, verbose=True)
    print(f"\nKnowledge base created at: {kb_path}")
