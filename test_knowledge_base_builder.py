#!/usr/bin/env python3
"""
Tests for knowledge_base_builder.py — three bug fixes.

  Bug 1: LINKAGE section mismatch (line 578: 'LINKAGE_SECTION' → 'LINKAGE')
  Bug 2: EVALUATE truncation + missing statement types (GOTO, MULTIPLY, DIVIDE, SET, READ, INITIALIZE)
  Bug 3: SPACES false-positive in dynamic CALL / CICS LINK/XCTL resolver

Integration tests redirect builder.kb_dir to a tempfile.TemporaryDirectory so
out/report/ artifacts are read-only and never overwritten.

Run:
    python3 test_knowledge_base_builder.py
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from knowledge_base_builder import KnowledgeBaseBuilder, _COBOL_FIGURATIVE_CONSTANTS

REPORT_DIR = Path(__file__).parent / 'out' / 'report'
PROG_COMPLEX_REPORT = REPORT_DIR / 'PROG_COMPLEX.CBL.report'
PROG_CICS_REPORT = REPORT_DIR / 'PROG_CICS.CBL.report'


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _builder(report_dir: Path, program: str = 'TEST.CBL') -> KnowledgeBaseBuilder:
    return KnowledgeBaseBuilder(report_dir, program, verbose=False)


def _make_cfg(nodes: list, edges: list | None = None) -> dict:
    return {'nodes': nodes, 'edges': edges or []}


def _para(pid: str, name: str) -> dict:
    return {'id': pid, 'type': 'PARAGRAPH', 'name': name,
            'originalText': f'{name}.', 'label': name}


def _stmt(sid: str, node_type: str, text: str) -> dict:
    return {'id': sid, 'type': node_type, 'name': node_type,
            'originalText': text, 'label': ''}


def _edge(fid: str, tid: str, etype: str = 'STARTS_WITH') -> dict:
    return {'fromNodeID': fid, 'toNodeID': tid, 'edgeType': etype}


# ============================================================================
# Bug 1 — LINKAGE section mismatch
# ============================================================================

def test_flatten_variables_emits_linkage_not_linkage_section():
    """_flatten_variables must store 'LINKAGE' from sourceSection verbatim."""
    with tempfile.TemporaryDirectory() as td:
        b = _builder(Path(td))
        data = {
            'name': '[ROOT]',
            'children': [
                {
                    'name': 'LK-PARAM',
                    'levelNumber': 1,
                    'dataType': 'STRING',
                    'rawText': '01 LK-PARAM PIC X(10)',
                    'sourceSection': 'LINKAGE',
                    'children': [],
                }
            ],
        }
        result: list = []
        b._flatten_variables(data, result)
        assert len(result) == 1, f"Expected 1 var, got {len(result)}"
        assert result[0]['section'] == 'LINKAGE', \
            f"Expected 'LINKAGE', got {result[0]['section']!r}"
        assert result[0]['name'] == 'LK-PARAM', result[0]['name']
    print('PASS test_flatten_variables_emits_linkage_not_linkage_section')


def test_linkage_filter_string_matches_json_value():
    """Filter '== LINKAGE' matches real JSON values; '== LINKAGE_SECTION' would match none."""
    # Simulate what real JSON data looks like: sourceSection is 'LINKAGE', never 'LINKAGE_SECTION'
    variables = [
        {'section': 'WORKING_STORAGE', 'name': 'WS-A'},
        {'section': 'LINKAGE',         'name': 'LK-B'},
        {'section': 'LINKAGE',         'name': 'LK-C'},
    ]
    correct = [v for v in variables if v.get('section') == 'LINKAGE']
    old_buggy = [v for v in variables if v.get('section') == 'LINKAGE_SECTION']
    assert len(correct) == 2, f"Expected 2 LINKAGE matches, got {len(correct)}"
    assert correct[0]['name'] == 'LK-B', correct[0]['name']
    assert len(old_buggy) == 0, \
        f"Old filter ('LINKAGE_SECTION') must match nothing in real JSON data, got {len(old_buggy)}"
    print('PASS test_linkage_filter_string_matches_json_value')


def _count_data_section(report_dir: Path, program: str, section: str) -> int:
    """Count variables with the given section label in the data JSON artifact."""
    data_files = list((report_dir / 'data_structures').glob(f'{program}-data.json'))
    if not data_files:
        return -1
    data = json.loads(data_files[0].read_text(encoding='utf-8'))
    variables: list = []
    _builder(report_dir, program)._flatten_variables(data, variables)
    return sum(1 for v in variables if v.get('section') == section)


def test_prog_complex_linkage_section_row_count():
    """LINKAGE rows in 02_Data_Dictionary.md must equal LINKAGE variables in data JSON."""
    if not PROG_COMPLEX_REPORT.exists():
        print('SKIP test_prog_complex_linkage_section_row_count'); return
    expected_linkage = _count_data_section(PROG_COMPLEX_REPORT, 'PROG_COMPLEX.CBL', 'LINKAGE')
    if expected_linkage < 0:
        print('SKIP test_prog_complex_linkage_section_row_count (no data JSON)'); return
    assert expected_linkage > 0, "PROG_COMPLEX must have LINKAGE variables"

    with tempfile.TemporaryDirectory() as td:
        b = _builder(PROG_COMPLEX_REPORT, 'PROG_COMPLEX.CBL')
        b.kb_dir = Path(td)
        b.kb_dir.mkdir(parents=True, exist_ok=True)
        b._generate_data_dictionary()
        content = (Path(td) / '02_Data_Dictionary.md').read_text(encoding='utf-8')

    assert '## Linkage Section Variables' in content, \
        "Expected '## Linkage Section Variables' section header in output"

    linkage_start = content.index('## Linkage Section Variables')
    rest = content[linkage_start + len('## Linkage Section Variables'):]
    next_section_idx = rest.find('\n## ')
    linkage_content = rest[:next_section_idx] if next_section_idx != -1 else rest

    rows = [
        line for line in linkage_content.split('\n')
        if line.startswith('| ') and '---' not in line and 'Variable Name' not in line
    ]
    assert len(rows) == expected_linkage, \
        f"Expected {expected_linkage} LINKAGE rows (from data JSON), got {len(rows)}"
    print('PASS test_prog_complex_linkage_section_row_count')


def test_prog_complex_working_storage_count_unchanged():
    """Bug 1 fix must not change WS row count — rendered rows must equal data JSON count."""
    if not PROG_COMPLEX_REPORT.exists():
        print('SKIP test_prog_complex_working_storage_count_unchanged'); return
    expected_ws = _count_data_section(PROG_COMPLEX_REPORT, 'PROG_COMPLEX.CBL', 'WORKING_STORAGE')
    if expected_ws < 0:
        print('SKIP test_prog_complex_working_storage_count_unchanged (no data JSON)'); return
    assert expected_ws > 0, "PROG_COMPLEX must have WORKING-STORAGE variables"

    with tempfile.TemporaryDirectory() as td:
        b = _builder(PROG_COMPLEX_REPORT, 'PROG_COMPLEX.CBL')
        b.kb_dir = Path(td)
        b.kb_dir.mkdir(parents=True, exist_ok=True)
        b._generate_data_dictionary()
        content = (Path(td) / '02_Data_Dictionary.md').read_text(encoding='utf-8')

    ws_start = content.find('## Working Storage Variables')
    assert ws_start != -1, "Working Storage section must be present"
    ws_block = content[ws_start:]
    next_section = ws_block.find('\n## ', 1)
    ws_section = ws_block[:next_section] if next_section != -1 else ws_block
    ws_rows = [
        line for line in ws_section.split('\n')
        if line.startswith('| ') and '---' not in line and 'Variable Name' not in line
    ]
    assert len(ws_rows) == expected_ws, \
        f"Expected {expected_ws} WS rows (from data JSON), got {len(ws_rows)}"
    print('PASS test_prog_complex_working_storage_count_unchanged')


def test_prog_complex_total_documented_variables():
    """Total variable rows (WS + LINKAGE) must equal count in data JSON."""
    if not PROG_COMPLEX_REPORT.exists():
        print('SKIP test_prog_complex_total_documented_variables'); return
    expected_ws = _count_data_section(PROG_COMPLEX_REPORT, 'PROG_COMPLEX.CBL', 'WORKING_STORAGE')
    expected_lk = _count_data_section(PROG_COMPLEX_REPORT, 'PROG_COMPLEX.CBL', 'LINKAGE')
    if expected_ws < 0 or expected_lk < 0:
        print('SKIP test_prog_complex_total_documented_variables (no data JSON)'); return
    expected_total = expected_ws + expected_lk

    with tempfile.TemporaryDirectory() as td:
        b = _builder(PROG_COMPLEX_REPORT, 'PROG_COMPLEX.CBL')
        b.kb_dir = Path(td)
        b.kb_dir.mkdir(parents=True, exist_ok=True)
        b._generate_data_dictionary()
        content = (Path(td) / '02_Data_Dictionary.md').read_text(encoding='utf-8')

    def _count_section_rows(md: str, heading: str) -> int:
        idx = md.find(f'## {heading}')
        if idx == -1:
            return 0
        block = md[idx + len(f'## {heading}'):]
        end = block.find('\n## ')
        block = block[:end] if end != -1 else block
        return sum(
            1 for line in block.split('\n')
            if line.startswith('| ') and '---' not in line and 'Variable Name' not in line
        )

    ws_count = _count_section_rows(content, 'Working Storage Variables')
    lk_count = _count_section_rows(content, 'Linkage Section Variables')
    total = ws_count + lk_count
    assert total == expected_total, \
        f"Expected {expected_ws} WS + {expected_lk} LINKAGE = {expected_total}, " \
        f"got WS={ws_count} LK={lk_count} total={total}"
    print('PASS test_prog_complex_total_documented_variables')


# ============================================================================
# Bug 2 — EVALUATE truncation + missing statement types
# ============================================================================

def test_format_evaluate_short_text_no_ellipsis():
    """EVALUATE originalText ≤500 chars must appear verbatim without '...'."""
    with tempfile.TemporaryDirectory() as td:
        b = _builder(Path(td))
        short = "EVALUATE WS-FLAG\n    WHEN 'A'\n        MOVE 1 TO X\n    WHEN OTHER\n        MOVE 0 TO X"
        assert len(short) <= 500, "fixture must be short"
        node = {'id': 'n1', 'originalText': short, 'type': 'EVALUATE'}
        result = b._format_evaluate(node, {}, {})
        assert '...' not in result, \
            f"Short EVALUATE must not contain '...', got: {result!r}"
        assert short in result, "Full originalText must appear verbatim in output"
        assert result.startswith('\n### EVALUATE Block\n'), \
            f"Must start with EVALUATE block header, got: {result[:50]!r}"
    print('PASS test_format_evaluate_short_text_no_ellipsis')


def test_format_evaluate_long_text_shows_when_bullets():
    """EVALUATE originalText >500 chars must produce WHEN bullets, not a 200-char blob."""
    with tempfile.TemporaryDirectory() as td:
        b = _builder(Path(td))
        long_text = (
            "EVALUATE WS-RISORSA\n"
            "    WHEN 'OPTION-A'\n" + "        MOVE 'X' TO Y\n" * 20 +
            "    WHEN 'OPTION-B'\n" + "        MOVE 'Z' TO W\n" * 20 +
            "    WHEN OTHER\n        MOVE SPACES TO ERR\n"
        )
        assert len(long_text) > 500, f"fixture must be long, got {len(long_text)}"
        node = {'id': 'n1', 'originalText': long_text, 'type': 'EVALUATE'}
        result = b._format_evaluate(node, {}, {})
        assert long_text[:200] + '...' not in result, \
            "Old 200-char+ellipsis pattern must not appear"
        assert "**WHEN** `'OPTION-A'`" in result, \
            f"Expected WHEN bullet for OPTION-A in: {result!r}"
        assert "**WHEN** `'OPTION-B'`" in result, \
            f"Expected WHEN bullet for OPTION-B in: {result!r}"
        assert "**WHEN** `OTHER`" in result, \
            f"Expected WHEN bullet for OTHER in: {result!r}"
    print('PASS test_format_evaluate_long_text_shows_when_bullets')


def test_goto_dispatch_produces_bullet():
    """GOTO nodes must produce '- **GO TO** `target`' bullet in the narrative."""
    with tempfile.TemporaryDirectory() as td:
        b = _builder(Path(td), 'GOTO-TEST.CBL')
        b.kb_dir = Path(td)
        b.kb_dir.mkdir(parents=True, exist_ok=True)
        cfg = _make_cfg(
            nodes=[
                _para('p1', 'MAIN-PARA'),
                _stmt('g1', 'GOTO', 'GO TO FOO-SECTION'),
            ],
            edges=[_edge('p1', 'g1')],
        )
        b._cfg_data = cfg
        b._comments = {}
        b._enriched_comments = {}
        b._generate_logic_narrative()
        content = (Path(td) / '01_Logic_Narrative.md').read_text(encoding='utf-8')
    assert '**GO TO** `FOO-SECTION`' in content, \
        f"Expected GO TO bullet in narrative, got:\n{content}"
    print('PASS test_goto_dispatch_produces_bullet')


def test_multiply_dispatch_produces_bullet():
    """MULTIPLY nodes must produce a backtick-wrapped bullet."""
    with tempfile.TemporaryDirectory() as td:
        b = _builder(Path(td), 'MULT-TEST.CBL')
        b.kb_dir = Path(td)
        b.kb_dir.mkdir(parents=True, exist_ok=True)
        cfg = _make_cfg(
            nodes=[
                _para('p1', 'CALC-PARA'),
                _stmt('m1', 'MULTIPLY', 'MULTIPLY MAX-RIGHE BY WCTPAG GIVING WKOST'),
            ],
            edges=[_edge('p1', 'm1')],
        )
        b._cfg_data = cfg
        b._comments = {}
        b._enriched_comments = {}
        b._generate_logic_narrative()
        content = (Path(td) / '01_Logic_Narrative.md').read_text(encoding='utf-8')
    assert '`MULTIPLY MAX-RIGHE BY WCTPAG GIVING WKOST`' in content, \
        f"Expected MULTIPLY bullet in narrative, got:\n{content}"
    print('PASS test_multiply_dispatch_produces_bullet')


def test_prog_complex_narrative_goto_exact_target():
    """First GOTO node's parsed target must appear as a GO TO bullet in the narrative."""
    if not PROG_COMPLEX_REPORT.exists():
        print('SKIP test_prog_complex_narrative_goto_exact_target'); return
    import re
    cfg_file = PROG_COMPLEX_REPORT / 'cfg' / 'cfg-PROG_COMPLEX.CBL.json'
    if not cfg_file.exists():
        print('SKIP test_prog_complex_narrative_goto_exact_target (no CFG)'); return
    cfg = json.loads(cfg_file.read_text(encoding='utf-8'))
    goto_nodes = [n for n in cfg['nodes'] if n.get('type') == 'GOTO']
    assert goto_nodes, "PROG_COMPLEX CFG must contain GOTO nodes"
    m = re.search(r'\bGO\s+TO\s+(\S+)', goto_nodes[0].get('originalText', ''), re.IGNORECASE)
    assert m, f"Could not parse target from first GOTO: {goto_nodes[0].get('originalText')!r}"
    expected_target = m.group(1)

    with tempfile.TemporaryDirectory() as td:
        b = _builder(PROG_COMPLEX_REPORT, 'PROG_COMPLEX.CBL')
        b.kb_dir = Path(td)
        b.kb_dir.mkdir(parents=True, exist_ok=True)
        b._generate_logic_narrative()
        content = (Path(td) / '01_Logic_Narrative.md').read_text(encoding='utf-8')
    assert f'**GO TO** `{expected_target}`' in content, \
        f"Expected '**GO TO** `{expected_target}`' (from first GOTO node) in narrative"
    print('PASS test_prog_complex_narrative_goto_exact_target')


def test_prog_complex_narrative_multiply_bullet():
    """At least one MULTIPLY bullet must appear in the narrative (dispatcher active)."""
    if not PROG_COMPLEX_REPORT.exists():
        print('SKIP test_prog_complex_narrative_multiply_bullet'); return
    cfg_file = PROG_COMPLEX_REPORT / 'cfg' / 'cfg-PROG_COMPLEX.CBL.json'
    if cfg_file.exists():
        cfg = json.loads(cfg_file.read_text(encoding='utf-8'))
        if not any(n.get('type') == 'MULTIPLY' for n in cfg['nodes']):
            print('SKIP test_prog_complex_narrative_multiply_bullet (no MULTIPLY nodes)'); return

    with tempfile.TemporaryDirectory() as td:
        b = _builder(PROG_COMPLEX_REPORT, 'PROG_COMPLEX.CBL')
        b.kb_dir = Path(td)
        b.kb_dir.mkdir(parents=True, exist_ok=True)
        b._generate_logic_narrative()
        content = (Path(td) / '01_Logic_Narrative.md').read_text(encoding='utf-8')
    multiply_bullets = [ln for ln in content.split('\n') if ln.startswith('- ') and '`MULTIPLY' in ln]
    assert multiply_bullets, \
        "Expected at least one MULTIPLY bullet in narrative — dispatcher may be broken"
    print('PASS test_prog_complex_narrative_multiply_bullet')


def test_prog_complex_narrative_bullet_count_after_bug2_fix():
    """GO TO bullets must be > 0 and ≤ CFG GOTO node count; STOP RUN bullets ≤ CFG STOP node count."""
    if not PROG_COMPLEX_REPORT.exists():
        print('SKIP test_prog_complex_narrative_bullet_count_after_bug2_fix'); return
    cfg_file = PROG_COMPLEX_REPORT / 'cfg' / 'cfg-PROG_COMPLEX.CBL.json'
    if not cfg_file.exists():
        print('SKIP test_prog_complex_narrative_bullet_count_after_bug2_fix (no CFG)'); return
    cfg = json.loads(cfg_file.read_text(encoding='utf-8'))
    cfg_goto_count = sum(1 for n in cfg['nodes'] if n.get('type') == 'GOTO')
    cfg_stop_count = sum(1 for n in cfg['nodes'] if n.get('type') == 'STOP')

    with tempfile.TemporaryDirectory() as td:
        b = _builder(PROG_COMPLEX_REPORT, 'PROG_COMPLEX.CBL')
        b.kb_dir = Path(td)
        b.kb_dir.mkdir(parents=True, exist_ok=True)
        b._generate_logic_narrative()
        content = (Path(td) / '01_Logic_Narrative.md').read_text(encoding='utf-8')
    bullets = [line for line in content.split('\n') if line.startswith('- ')]
    goto_bullets = [b for b in bullets if '**GO TO**' in b]
    stop_bullets = [b for b in bullets if '**STOP RUN**' in b]

    assert goto_bullets, \
        "Expected at least one GO TO bullet — GOTO dispatcher may not be active"
    assert len(goto_bullets) <= cfg_goto_count, \
        f"Got {len(goto_bullets)} GO TO bullets but only {cfg_goto_count} GOTO nodes in CFG"
    assert len(stop_bullets) <= cfg_stop_count, \
        f"Got {len(stop_bullets)} STOP RUN bullets but only {cfg_stop_count} STOP nodes in CFG"
    if cfg_stop_count > 0:
        assert stop_bullets, \
            f"CFG has {cfg_stop_count} STOP node(s) — at least one STOP RUN bullet must appear"
    print(f'PASS test_prog_complex_narrative_bullet_count_after_bug2_fix '
          f'({len(goto_bullets)}/{cfg_goto_count} GO TO, {len(stop_bullets)}/{cfg_stop_count} STOP RUN)')


# ============================================================================
# Bug 3 — SPACES false positive in dependency CALL resolution
# ============================================================================

def test_is_valid_target_rejects_figurative_constants():
    """_is_valid_target must return False for all COBOL figurative constants."""
    figurative = list(_COBOL_FIGURATIVE_CONSTANTS) + [' SPACES ', '  ZEROS  ']
    for const in figurative:
        result = KnowledgeBaseBuilder._is_valid_target(const)
        assert result is False, \
            f"_is_valid_target({const!r}) must be False, got {result}"
    print('PASS test_is_valid_target_rejects_figurative_constants')


def test_is_valid_target_accepts_real_program_names():
    """_is_valid_target must return True for valid IBM program names."""
    valid = ['PROG_WS_EXT', 'PROG_OPER', 'MYPROG', 'XFRFUN', 'CICS_TARGET_C', 'AB']
    for name in valid:
        result = KnowledgeBaseBuilder._is_valid_target(name)
        assert result is True, \
            f"_is_valid_target({name!r}) must be True, got {result}"
    print('PASS test_is_valid_target_accepts_real_program_names')


def test_is_valid_target_rejects_edge_cases():
    """_is_valid_target must reject empty strings, single chars, and pure numeric values."""
    invalid = ['', 'X', '0', '42', '123', '  ', '\t']
    for val in invalid:
        result = KnowledgeBaseBuilder._is_valid_target(val)
        assert result is False, \
            f"_is_valid_target({val!r}) must be False, got {result}"
    print('PASS test_is_valid_target_rejects_edge_cases')


def test_cics_resolver_excludes_spaces_figurative():
    """CICS LINK resolver must not add 'SPACES' (or padded ' SPACES ') as a target."""
    with tempfile.TemporaryDirectory() as td:
        report = Path(td) / 'FAKE.CBL.report'
        report.mkdir(parents=True)
        cfg = _make_cfg(nodes=[
            {'id': 'n1', 'type': 'DIALECT',
             'originalText': 'EXEC CICS LINK PROGRAM(WS-LINKPGM) END-EXEC',
             'name': '', 'label': ''},
        ])
        (report / 'cfg').mkdir()
        (report / 'cfg' / 'cfg-FAKE.CBL.json').write_text(json.dumps(cfg))
        var_values = [['WS-LINKPGM', ["'MYPROG'", 'SPACES', ' SPACES ', "'OTHERPROG'"]]]
        (report / 'variable_values.json').write_text(json.dumps(var_values))

        b = _builder(report, 'FAKE.CBL')
        b.kb_dir = Path(td) / 'kb'
        b.kb_dir.mkdir(parents=True)
        b._generate_dependencies()

        import yaml as _yaml
        deps = _yaml.safe_load((b.kb_dir / '03_Dependencies.yaml').read_text())

    cics_calls = deps.get('cics_calls', [])
    targets = [e.get('target') for e in cics_calls]
    assert 'SPACES' not in targets, \
        f"'SPACES' must not appear in cics_calls, got: {targets}"
    assert 'MYPROG' in targets, \
        f"'MYPROG' must appear in cics_calls, got: {targets}"
    assert 'OTHERPROG' in targets, \
        f"'OTHERPROG' must appear in cics_calls, got: {targets}"
    assert len(targets) == 2, \
        f"Expected exactly 2 targets (MYPROG, OTHERPROG), got {len(targets)}: {targets}"
    print('PASS test_cics_resolver_excludes_spaces_figurative')


def test_cics_operations_from_metadata():
    """cics_operations: key is built from Java-enriched metadata on CFG nodes."""
    with tempfile.TemporaryDirectory() as td:
        report = Path(td) / 'META.CBL.report'
        report.mkdir(parents=True)
        cfg = _make_cfg(nodes=[
            {'id': 'n1', 'type': 'DIALECT',
             'originalText': 'EXEC CICS STARTBR DATASET(CUSTFILE) END-EXEC',
             'name': '', 'label': '',
             'metadata': {
                 'dialect_family': 'CICS', 'cics_command': 'STARTBR',
                 'cics_operation_type': 'browse', 'cics_target_kind': 'DATASET',
                 'cics_target': 'CUSTFILE', 'cics_target_source': 'literal',
                 'dialect_semantics_status': 'metadata_only'}},
            {'id': 'n2', 'type': 'DIALECT',
             'originalText': 'EXEC CICS XCTL PROGRAM(WS-PROG) END-EXEC',
             'name': '', 'label': '',
             'metadata': {
                 'dialect_family': 'CICS', 'cics_command': 'XCTL',
                 'cics_operation_type': 'program_transfer', 'cics_target_kind': 'PROGRAM',
                 'cics_target': 'WS-PROG', 'cics_target_source': 'identifier',
                 'dialect_semantics_status': 'metadata_only'}},
        ])
        (report / 'cfg').mkdir()
        (report / 'cfg' / 'cfg-META.CBL.json').write_text(json.dumps(cfg))
        (report / 'variable_values.json').write_text('[]')
        b = _builder(report, 'META.CBL')
        b.kb_dir = Path(td) / 'kb'
        b.kb_dir.mkdir(parents=True)
        b._generate_dependencies()
        import yaml as _yaml
        deps = _yaml.safe_load((b.kb_dir / '03_Dependencies.yaml').read_text())

    ops = deps.get('cics_operations', [])
    assert ops, "cics_operations must be present when metadata has cics_operation_type"
    cmds = {o['command'] for o in ops}
    assert 'STARTBR' in cmds, f"Expected STARTBR in cics_operations, got {cmds}"
    assert 'XCTL' in cmds, f"Expected XCTL in cics_operations, got {cmds}"
    startbr = next(o for o in ops if o['command'] == 'STARTBR')
    assert startbr['type'] == 'browse', f"STARTBR type must be browse, got {startbr['type']}"
    assert startbr.get('target_kind') == 'DATASET'
    assert startbr.get('target') == 'CUSTFILE'
    xctl = next(o for o in ops if o['command'] == 'XCTL')
    assert xctl['type'] == 'program_transfer'
    assert xctl.get('target_kind') == 'PROGRAM'
    cics_list = deps.get('cics', [])
    assert 'STARTBR' in cics_list, "cics: backward-compat list must still contain STARTBR"
    assert 'XCTL' in cics_list, "cics: backward-compat list must still contain XCTL"
    print('PASS test_cics_operations_from_metadata')


def test_prog_cics_cics_calls_excludes_spaces():
    """After Bug 3 fix, PROG_CICS cics_calls must contain no figurative constants."""
    if not PROG_CICS_REPORT.exists():
        print('SKIP test_prog_cics_cics_calls_excludes_spaces'); return
    with tempfile.TemporaryDirectory() as td:
        b = _builder(PROG_CICS_REPORT, 'PROG_CICS.CBL')
        b.kb_dir = Path(td)
        b.kb_dir.mkdir(parents=True, exist_ok=True)
        b._generate_dependencies()
        import yaml as _yaml
        deps = _yaml.safe_load((Path(td) / '03_Dependencies.yaml').read_text())

    cics_calls = deps.get('cics_calls', [])
    targets = [e.get('target') for e in cics_calls]
    assert targets, "PROG_CICS must have at least one cics_call after Bug 3 fix"
    for t in targets:
        assert t not in _COBOL_FIGURATIVE_CONSTANTS, \
            f"Figurative constant {t!r} must not appear in cics_calls after Bug 3 fix"
    print('PASS test_prog_cics_cics_calls_excludes_spaces')


def test_prog_complex_cics_calls_unaffected_by_bug3_fix():
    """Bug 3 fix must not remove valid PROG_COMPLEX cics_calls — targets must contain no figurative constants."""
    if not PROG_COMPLEX_REPORT.exists():
        print('SKIP test_prog_complex_cics_calls_unaffected_by_bug3_fix'); return
    with tempfile.TemporaryDirectory() as td:
        b = _builder(PROG_COMPLEX_REPORT, 'PROG_COMPLEX.CBL')
        b.kb_dir = Path(td)
        b.kb_dir.mkdir(parents=True, exist_ok=True)
        b._generate_dependencies()
        import yaml as _yaml
        deps = _yaml.safe_load((Path(td) / '03_Dependencies.yaml').read_text())

    cics_calls = deps.get('cics_calls', [])
    targets = {e.get('target') for e in cics_calls}
    assert targets, "PROG_COMPLEX must have at least one cics_call — Bug 3 fix must not over-filter"
    for t in targets:
        assert t not in _COBOL_FIGURATIVE_CONSTANTS, \
            f"Figurative constant {t!r} found in PROG_COMPLEX cics_calls — Bug 3 fix failed"
    print('PASS test_prog_complex_cics_calls_unaffected_by_bug3_fix')


# ============================================================================
# Codex phase-2 fixes — QUOTE/QUOTES, internal-space, EXIT/STOP dispatch
# ============================================================================

def test_is_valid_target_rejects_quote_quotes():
    """QUOTE and QUOTES must be rejected as figurative constants."""
    from knowledge_base_builder import KnowledgeBaseBuilder as _KB
    for val in ('QUOTE', 'Quotes', ' QUOTE ', "'QUOTE'"):
        normalized = val.strip("'\"")
        result = _KB._is_valid_target(normalized)
        assert not result, \
            f"_is_valid_target({val!r}) must be False (figurative constant), got True"
    print('PASS test_is_valid_target_rejects_quote_quotes')


def test_is_valid_target_rejects_internal_space():
    """Values with internal spaces (e.g. 'MY PROG') must be rejected."""
    from knowledge_base_builder import KnowledgeBaseBuilder as _KB
    for val in ('MY PROG', 'PD W0', 'A B'):
        result = _KB._is_valid_target(val)
        assert not result, \
            f"_is_valid_target({val!r}) must be False (internal space), got True"
    print('PASS test_is_valid_target_rejects_internal_space')


def _narrative_for_cfg(nodes: list, edges: list) -> str:
    """Helper: build a narrative string from a synthetic CFG."""
    with tempfile.TemporaryDirectory() as td:
        b = _builder(Path(td), 'EXIT-TEST.CBL')
        b.kb_dir = Path(td)
        b.kb_dir.mkdir(parents=True, exist_ok=True)
        b._cfg_data = _make_cfg(nodes, edges)
        b._comments = {}
        b._enriched_comments = {}
        b._generate_logic_narrative()
        return (Path(td) / '01_Logic_Narrative.md').read_text(encoding='utf-8')


def test_exit_bare_skipped_in_narrative():
    """Bare EXIT nodes must produce no bullet — they are structural punctuation."""
    content = _narrative_for_cfg(
        nodes=[_para('p1', 'END-PARA'), _stmt('e1', 'EXIT', 'EXIT')],
        edges=[_edge('p1', 'e1')],
    )
    bullets = [ln for ln in content.split('\n') if ln.startswith('- ')]
    assert not any('EXIT' in b for b in bullets), \
        f"Bare EXIT must not produce a bullet, got bullets: {bullets}"
    print('PASS test_exit_bare_skipped_in_narrative')


def test_exit_perform_renders_bullet():
    """EXIT PERFORM must render as '- **EXIT PERFORM**'."""
    content = _narrative_for_cfg(
        nodes=[_para('p1', 'LOOP-PARA'), _stmt('e1', 'EXIT', 'EXIT PERFORM')],
        edges=[_edge('p1', 'e1')],
    )
    assert '**EXIT PERFORM**' in content, \
        f"'**EXIT PERFORM**' must appear in narrative, got:\n{content}"
    print('PASS test_exit_perform_renders_bullet')


def test_stop_run_renders_bullet():
    """STOP RUN must render as '- **STOP RUN**'."""
    content = _narrative_for_cfg(
        nodes=[_para('p1', 'TERM-PARA'), _stmt('s1', 'STOP', 'STOP RUN')],
        edges=[_edge('p1', 's1')],
    )
    assert '**STOP RUN**' in content, \
        f"'**STOP RUN**' must appear in narrative, got:\n{content}"
    print('PASS test_stop_run_renders_bullet')


# ============================================================================
# Analysis Quality section in 00_Executive_Summary.md
# ============================================================================

def _write_manifest(td: str, total: int, resolved: int, copybooks: dict) -> None:
    """Write a synthetic copybook_manifest.json into a temp directory."""
    manifest = {
        'program': 'TEST.CBL',
        'copybooks': copybooks,
        'summary': {
            'total_copybooks': total,
            'resolved': resolved,
            'stubbed': total - resolved,
            'resolved_percentage': round((resolved / total) * 100, 1) if total else 100.0,
        },
    }
    (Path(td) / 'copybook_manifest.json').write_text(
        json.dumps(manifest), encoding='utf-8'
    )


def test_analysis_quality_no_stubs_shows_high_confidence():
    """When all copybooks are resolved and no parse errors, confidence must be High."""
    with tempfile.TemporaryDirectory() as td:
        _write_manifest(td, 2, 2, {
            'CPYA': {'file': 'CPYA.cpy', 'is_stub': False, 'lines': 10, 'status': 'resolved'},
            'CPYB': {'file': 'CPYB.cpy', 'is_stub': False, 'lines': 5, 'status': 'resolved'},
        })
        b = _builder(Path(td), 'TEST.CBL')
        section = b._build_analysis_quality_section()

    assert '**High**' in section, \
        f"Expected '**High**' confidence with 0 stubs and no parse errors, got:\n{section}"
    assert 'Stubbed Copybooks' not in section, \
        "No stub table should appear when all copybooks are resolved"
    assert '2 / 2 (100.0%)' in section, \
        f"Expected '2 / 2 (100.0%)' in copybook resolution, got:\n{section}"
    print('PASS test_analysis_quality_no_stubs_shows_high_confidence')


def test_analysis_quality_with_stubs_shows_stub_table():
    """When stubs exist, the stub table must appear with each stubbed copybook listed."""
    with tempfile.TemporaryDirectory() as td:
        _write_manifest(td, 3, 1, {
            'RESOLVED': {'file': 'RESOLVED.cpy', 'is_stub': False, 'lines': 10, 'status': 'resolved'},
            'STUBBED1': {'file': 'STUBBED1.cpy', 'is_stub': True, 'lines': 3, 'status': 'stubbed'},
            'STUBBED2': {'file': 'STUBBED2.cpy', 'is_stub': True, 'lines': 3, 'status': 'stubbed'},
        })
        b = _builder(Path(td), 'TEST.CBL')
        section = b._build_analysis_quality_section()

    assert 'Stubbed Copybooks' in section, \
        "Stub table heading must appear when stubs exist"
    assert '`STUBBED1`' in section, \
        "STUBBED1 must appear in the stub table"
    assert '`STUBBED2`' in section, \
        "STUBBED2 must appear in the stub table"
    assert '`RESOLVED`' not in section, \
        "Resolved copybooks must not appear in the stub table"
    assert '1 / 3 (33.3%)' in section, \
        f"Expected '1 / 3 (33.3%)' resolution ratio, got:\n{section}"
    print('PASS test_analysis_quality_with_stubs_shows_stub_table')


def test_prog_complex_executive_summary_has_analysis_quality_section():
    """Executive summary must contain Analysis Quality section; stub table lists all stubs from manifest."""
    if not PROG_COMPLEX_REPORT.exists():
        print('SKIP test_prog_complex_executive_summary_has_analysis_quality_section'); return
    manifest_path = PROG_COMPLEX_REPORT / 'copybook_manifest.json'
    if not manifest_path.exists():
        print('SKIP test_prog_complex_executive_summary_has_analysis_quality_section (no manifest)'); return
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    summary = manifest.get('summary', {})
    total = summary.get('total_copybooks', manifest.get('total', 0))
    resolved = summary.get('resolved', manifest.get('resolved', 0))
    stub_names = [
        name for name, info in manifest.get('copybooks', {}).items()
        if info.get('is_stub', False)
    ]

    with tempfile.TemporaryDirectory() as td:
        b = _builder(PROG_COMPLEX_REPORT, 'PROG_COMPLEX.CBL')
        b.kb_dir = Path(td)
        b.kb_dir.mkdir(parents=True, exist_ok=True)
        b._generate_executive_summary()
        content = (Path(td) / '00_Executive_Summary.md').read_text(encoding='utf-8')

    assert '## Analysis Quality' in content, \
        "Executive summary must contain '## Analysis Quality' section"
    assert 'Confidence' in content, \
        "Analysis Quality section must contain a Confidence row"
    if stub_names:
        assert '### Stubbed Copybooks' in content, \
            f"Manifest has {len(stub_names)} stubs — stub table must appear"
        pct = f'{resolved / total * 100:.1f}' if total else '0.0'
        assert f'{resolved} / {total} ({pct}%)' in content, \
            f"Expected '{resolved} / {total} ({pct}%)' resolution ratio from manifest"
        for name in stub_names:
            assert f'`{name}`' in content, \
                f"Stub '{name}' from manifest must appear in the stub table"
    print('PASS test_prog_complex_executive_summary_has_analysis_quality_section')


# ============================================================================
# Runner
# ============================================================================

if __name__ == '__main__':
    tests = [
        # Bug 1
        test_flatten_variables_emits_linkage_not_linkage_section,
        test_linkage_filter_string_matches_json_value,
        test_prog_complex_linkage_section_row_count,
        test_prog_complex_working_storage_count_unchanged,
        test_prog_complex_total_documented_variables,
        # Bug 2
        test_format_evaluate_short_text_no_ellipsis,
        test_format_evaluate_long_text_shows_when_bullets,
        test_goto_dispatch_produces_bullet,
        test_multiply_dispatch_produces_bullet,
        test_prog_complex_narrative_goto_exact_target,
        test_prog_complex_narrative_multiply_bullet,
        test_prog_complex_narrative_bullet_count_after_bug2_fix,
        # Bug 3
        test_is_valid_target_rejects_figurative_constants,
        test_is_valid_target_accepts_real_program_names,
        test_is_valid_target_rejects_edge_cases,
        test_cics_resolver_excludes_spaces_figurative,
        test_cics_operations_from_metadata,
        test_prog_cics_cics_calls_excludes_spaces,
        test_prog_complex_cics_calls_unaffected_by_bug3_fix,
        # Codex phase-2 fixes
        test_is_valid_target_rejects_quote_quotes,
        test_is_valid_target_rejects_internal_space,
        test_exit_bare_skipped_in_narrative,
        test_exit_perform_renders_bullet,
        test_stop_run_renders_bullet,
        # Analysis Quality section
        test_analysis_quality_no_stubs_shows_high_confidence,
        test_analysis_quality_with_stubs_shows_stub_table,
        test_prog_complex_executive_summary_has_analysis_quality_section,
    ]

    passed = failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except AssertionError as e:
            print(f'FAIL {t.__name__}: {e}')
            failed += 1
        except Exception as e:
            print(f'ERROR {t.__name__}: {type(e).__name__}: {e}')
            failed += 1

    total = passed + failed
    print(f'\n{passed}/{total} passed, {failed} failed')
    sys.exit(0 if failed == 0 else 1)
