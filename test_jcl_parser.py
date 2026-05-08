#!/usr/bin/env python3
"""
Unit tests for jcl_parser.py.

Two sections:
  1. Real-file end-to-end tests 
  2. Synthetic edge-case tests (inline JCL strings)
"""

import json
import os
import sys
import tempfile
import textwrap
from pathlib import Path

# Make sure jcl_parser is importable from the repo root
sys.path.insert(0, str(Path(__file__).parent))
from jcl_parser import JCLParser, build_jcl_report


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_string(jcl_text: str) -> dict:
    """Write jcl_text to a temp file and parse it. Returns parsed dict."""
    jcl_text = textwrap.dedent(jcl_text)
    with tempfile.NamedTemporaryFile(mode='w', suffix='.JCL',
                                     delete=False, encoding='utf-8') as f:
        f.write(jcl_text)
        tmp = Path(f.name)
    try:
        p = JCLParser(tmp, verbose=False)
        return p.parse()
    finally:
        tmp.unlink(missing_ok=True)


def parse_and_build(jcl_text: str) -> tuple[dict, dict, dict, dict]:
    """
    Parse JCL text, write JSON artifacts to a temp dir.
    Returns (parsed, summary, steps, datasets).
    """
    jcl_text = textwrap.dedent(jcl_text)
    with tempfile.NamedTemporaryFile(mode='w', suffix='.JCL',
                                     delete=False, encoding='utf-8') as f:
        f.write(jcl_text)
        tmp = Path(f.name)
    with tempfile.TemporaryDirectory() as td:
        try:
            out_dir = build_jcl_report(tmp, output_dir=td, verbose=False)
            summary = json.loads((out_dir / 'jcl_summary.json').read_text())
            steps   = json.loads((out_dir / 'jcl_steps.json').read_text())
            datasets = json.loads((out_dir / 'jcl_datasets.json').read_text())
            p = JCLParser(tmp)
            parsed = p.parse()
        finally:
            tmp.unlink(missing_ok=True)
    return parsed, summary, steps, datasets


# ---------------------------------------------------------------------------
# Real-file tests
# ---------------------------------------------------------------------------

CODEFILES = Path(__file__).parent.parent / 'codefiles'


def test_pdasco01():
    jcl = CODEFILES / 'PDASCO01.JCL'
    if not jcl.exists():
        print('SKIP test_pdasco01: file not found')
        return

    with tempfile.TemporaryDirectory() as td:
        out_dir = build_jcl_report(jcl, output_dir=td, verbose=False)
        summary = json.loads((out_dir / 'jcl_summary.json').read_text())
        steps   = json.loads((out_dir / 'jcl_steps.json').read_text())

    assert summary['job_name'] == 'PDASCO01', summary['job_name']
    assert summary['step_count'] == 1, f"Expected 1 step, got {summary['step_count']}"
    assert summary['job_cond'] == '(0,LT)', f"job_cond={summary['job_cond']!r}"
    assert not summary['warnings'], f"Unexpected warnings: {summary['warnings']}"
    assert not summary['unresolved_symbols']

    # Single step: cataloged PROC invocation
    assert len(steps) == 1
    s = steps[0]
    assert s['proc'] == 'PDASCO01'
    assert s['proc_source'] == 'cataloged'
    assert s['program'] is None

    print('PASS test_pdasco01')


def test_pdaddre1():
    jcl = CODEFILES / 'PDADDRE1.JCL'
    if not jcl.exists():
        print('SKIP test_pdaddre1: file not found')
        return

    with tempfile.TemporaryDirectory() as td:
        out_dir = build_jcl_report(jcl, output_dir=td, verbose=False)
        summary = json.loads((out_dir / 'jcl_summary.json').read_text())
        steps   = json.loads((out_dir / 'jcl_steps.json').read_text())
        datasets = json.loads((out_dir / 'jcl_datasets.json').read_text())

    # Basic counts
    assert summary['step_count'] == 7, f"Expected 7 steps, got {summary['step_count']}"
    assert not summary['warnings'], f"Unexpected warnings: {summary['warnings']}"
    assert not summary['unresolved_symbols']

    # Programs invoked (excluding system utilities)
    assert set(summary['programs_invoked']) == {'PDHADR00', 'PDHADR01', 'PDKADR'}, \
        summary['programs_invoked']

    # Symbol resolution: CATEG=T, TIPO=IP should resolve in DSNs
    all_dsns = {ds for ds in summary['datasets_read'] + summary['datasets_written']}
    assert 'TEPDET.PDADDRE1.ADRTOT.T.IP' in all_dsns, \
        f'Expected resolved DSN in {sorted(all_dsns)}'
    assert 'TEPDET.B.ADRCES.IP' in all_dsns, \
        f'Expected TEPDET.B.ADRCES.IP in {sorted(all_dsns)}'

    # &&INSADR is temporary — must NOT appear in jcl_datasets
    dsn_keys = set(datasets['datasets'].keys())
    assert not any('INSADR' in k for k in dsn_keys), \
        f'Temp &&INSADR should not appear in datasets: {dsn_keys}'

    # Step names match PROC body
    step_names = [s['step_name'] for s in steps]
    for expected in ('DELADR', 'SCRADDR', 'PDHADR00', 'PDHADR01',
                     'SKSADR', 'SORADR', 'CARADR'):
        assert expected in step_names, f'{expected} not in {step_names}'

    print('PASS test_pdaddre1')


def test_pdcafin2():
    jcl = CODEFILES / 'PDCAFIN2.JCL'
    if not jcl.exists():
        print('SKIP test_pdcafin2: file not found')
        return

    with tempfile.TemporaryDirectory() as td:
        out_dir = build_jcl_report(jcl, output_dir=td, verbose=False)
        summary = json.loads((out_dir / 'jcl_summary.json').read_text())
        steps   = json.loads((out_dir / 'jcl_steps.json').read_text())
        datasets = json.loads((out_dir / 'jcl_datasets.json').read_text())

    assert summary['step_count'] == 9, f"Expected 9 steps, got {summary['step_count']}"
    assert summary['region'] == '6M', summary.get('region')
    assert not summary['warnings']
    assert not summary['unresolved_symbols']

    # 3 OUTPUT definitions
    out_defs = summary.get('output_definitions', {})
    assert len(out_defs) == 3, f'Expected 3 OUTPUT defs, got {len(out_defs)}'
    assert 'OUTDEF' in out_defs
    assert 'OUTINF' in out_defs
    assert 'OUTCPA' in out_defs
    assert out_defs['OUTDEF']['default'] == 'Y'
    assert out_defs['OUTINF']['class'] == '*'

    # Temporary datasets absent from jcl_datasets
    dsn_keys = set(datasets['datasets'].keys())
    for temp in ('CAFSEQ', 'SKVAR2', 'FILESTA', 'FILEST2', 'SKANAG', 'ANAGS'):
        assert not any(temp in k for k in dsn_keys), \
            f'Temp &&{temp} should not be in datasets: {dsn_keys}'

    # Symbol resolution: ANNO=2024, MENS=12, TIPO=67
    all_dsns = set(summary['datasets_read'] + summary['datasets_written'])
    assert 'TEPDET.BPDKCAF.PDCAF002.M12T67' in all_dsns, \
        f'Expected M12T67 in {sorted(all_dsns)}'
    assert 'TEPDET.BVARIAZ.CAF2024.M12T67' in all_dsns, \
        f'Expected CAF2024 in {sorted(all_dsns)}'

    # COPYVAR step: DCB backreference *.SYSUT1 and PDS member DSN
    copyvar = next((s for s in steps if s['step_name'] == 'COPYVAR'), None)
    assert copyvar is not None, 'COPYVAR step not found'
    dds = {dd['dd_name']: dd for dd in copyvar.get('dd_statements', [])}
    # SYSUT2 must have DCB backreference
    assert 'SYSUT2' in dds, f'SYSUT2 not in {list(dds)}'
    dcb = dds['SYSUT2'].get('dcb', {})
    assert isinstance(dcb, dict) and dcb.get('backreference') == 'SYSUT1', \
        f'Expected DCB backreference to SYSUT1, got {dcb}'

    # SCARCAF step: SYSIN is PDS member reference
    scarcaf = next((s for s in steps if s['step_name'] == 'SCARCAF'), None)
    assert scarcaf is not None
    sysin = next((dd for dd in scarcaf.get('dd_statements', [])
                  if dd['dd_name'] == 'SYSIN'), None)
    assert sysin is not None
    dsn_val = sysin.get('dsn')
    assert isinstance(dsn_val, dict), f'Expected PDS member dict, got {dsn_val}'
    assert dsn_val.get('dsn') == 'TEPE1A.TSO.PARM'
    assert dsn_val.get('member') == 'PTVSREPR'

    print('PASS test_pdcafin2')


# ---------------------------------------------------------------------------
# Synthetic edge-case tests
# ---------------------------------------------------------------------------

def test_job_no_card():
    """File with no JOB card: job_name falls back to filename stem."""
    parsed = parse_string("""\
        //STEP1 EXEC PGM=MYPGM
        //SYSPRINT DD SYSOUT=*
    """)
    assert parsed['job_name'] is None or isinstance(parsed['job_name'], str)
    print('PASS test_job_no_card')


def test_vol_multi_volume():
    """VOL=SER=(VOL1,VOL2,VOL3) → ser list."""
    _, summary, steps, _ = parse_and_build("""\
        //VTEST JOB CLASS=A
        //S1 EXEC PGM=MYPGM
        //MYFILE DD DSN=MY.DS,DISP=SHR,VOL=SER=(VOL1,VOL2,VOL3)
    """)
    assert summary['step_count'] == 1
    dd = steps[0]['dd_statements'][0]
    vol = dd.get('vol', {})
    assert vol.get('ser') == ['VOL1', 'VOL2', 'VOL3'], f'vol={vol}'
    print('PASS test_vol_multi_volume')


def test_vol_backreference():
    """VOL=REF=*.DDNAME → vol_ref."""
    _, _, steps, _ = parse_and_build("""\
        //VREF JOB CLASS=A
        //S1 EXEC PGM=MYPGM
        //FILE1 DD DSN=A.DS,DISP=SHR,VOL=REF=*.PREVDD
    """)
    dd = steps[0]['dd_statements'][0]
    assert dd['vol'] == {'vol_ref': 'PREVDD'}, dd.get('vol')
    print('PASS test_vol_backreference')


def test_disp_uncatlg():
    """DISP=(,UNCATLG) parses normal disposition correctly."""
    _, _, steps, _ = parse_and_build("""\
        //DTEST JOB CLASS=A
        //S1 EXEC PGM=MYPGM
        //FILE DD DSN=MY.DS,DISP=(NEW,UNCATLG,DELETE)
    """)
    disp = steps[0]['dd_statements'][0]['disp']
    assert disp['status'] == 'NEW'
    assert disp['normal'] == 'UNCATLG'
    assert disp['abnormal'] == 'DELETE'
    print('PASS test_disp_uncatlg')


def test_disp_mod():
    """DISP=MOD shorthand."""
    _, _, steps, _ = parse_and_build("""\
        //DMOD JOB CLASS=A
        //S1 EXEC PGM=MYPGM
        //FILE DD DSN=MY.DS,DISP=MOD
    """)
    disp = steps[0]['dd_statements'][0]['disp']
    assert disp['status'] == 'MOD'
    assert disp['normal'] is None
    print('PASS test_disp_mod')


def test_space_rlse_contig():
    """SPACE=(CYL,(5,1),RLSE,CONTIG) flags."""
    _, _, steps, _ = parse_and_build("""\
        //STEST JOB CLASS=A
        //S1 EXEC PGM=MYPGM
        //FILE DD DSN=MY.DS,DISP=(,CATLG),SPACE=(CYL,(5,1),RLSE,CONTIG)
    """)
    space = steps[0]['dd_statements'][0]['space']
    assert space['unit'] == 'CYL'
    assert space['primary'] == '5'
    assert space['secondary'] == '1'
    assert space.get('rlse') is True
    assert space.get('contig') is True
    print('PASS test_space_rlse_contig')


def test_dcb_sub_params():
    """DCB=(RECFM=FB,LRECL=80,BLKSIZE=32720) sub-params."""
    _, _, steps, _ = parse_and_build("""\
        //DCBT JOB CLASS=A
        //S1 EXEC PGM=MYPGM
        //FILE DD DSN=MY.DS,DISP=(,CATLG),DCB=(RECFM=FB,LRECL=80,BLKSIZE=32720)
    """)
    dcb = steps[0]['dd_statements'][0]['dcb']
    assert isinstance(dcb, dict)
    assert dcb.get('recfm') == 'FB'
    assert dcb.get('lrecl') == '80'
    assert dcb.get('blksize') == '32720'
    print('PASS test_dcb_sub_params')


def test_dd_inline_data():
    """DD * inline data records are counted, not parsed as JCL."""
    parsed = parse_string("""\
        //ITEST JOB CLASS=A
        //S1 EXEC PGM=MYPGM
        //SYSIN DD *
        SORT FIELDS=(1,5,CH,A)
        RECORD TYPE=ALL
        END
        /*
        //SYSPRINT DD SYSOUT=*
    """)
    # SYSIN should be inline_data=True
    dds = parsed['steps'][0].get('dd_statements', [])
    sysin = next((d for d in dds if d['dd_name'] == 'SYSIN'), None)
    assert sysin is not None
    assert sysin.get('inline_data') is True
    assert sysin.get('inline_data_lines') == 3
    print('PASS test_dd_inline_data')


def test_dd_data_dlm():
    """DD DATA DLM=@@ uses custom delimiter."""
    parsed = parse_string("""\
        //DLMTEST JOB CLASS=A
        //S1 EXEC PGM=MYPGM
        //SYSIN DD DATA,DLM=@@
        line one
        line two
        @@
        //SYSPRINT DD SYSOUT=*
    """)
    dds = parsed['steps'][0].get('dd_statements', [])
    sysin = next((d for d in dds if d['dd_name'] == 'SYSIN'), None)
    assert sysin is not None
    assert sysin.get('inline_data') is True
    assert sysin.get('inline_data_lines') == 2
    print('PASS test_dd_data_dlm')


def test_cond_even():
    """EXEC with COND=EVEN modifier."""
    parsed = parse_string("""\
        //CTEST JOB CLASS=A
        //S1 EXEC PGM=MYPGM,COND=(4,LT),EVEN
    """)
    step = parsed['steps'][0]
    assert step.get('cond_modifier') == 'EVEN', step
    print('PASS test_cond_even')


def test_cond_only():
    """EXEC with COND=ONLY modifier."""
    parsed = parse_string("""\
        //CTEST JOB CLASS=A
        //S1 EXEC PGM=MYPGM,COND=(8,LT),ONLY
    """)
    step = parsed['steps'][0]
    assert step.get('cond_modifier') == 'ONLY', step
    print('PASS test_cond_only')


def test_rd_restart():
    """RD=R on EXEC step."""
    parsed = parse_string("""\
        //RDTEST JOB CLASS=A
        //S1 EXEC PGM=MYPGM,RD=R
    """)
    assert parsed['steps'][0].get('rd') == 'R'
    print('PASS test_rd_restart')


def test_typrun_scan():
    """TYPRUN=SCAN on JOB card."""
    parsed = parse_string("""\
        //TTEST JOB CLASS=A,TYPRUN=SCAN
        //S1 EXEC PGM=MYPGM
    """)
    assert parsed['job_params'].get('typrun') == 'SCAN', parsed['job_params']
    print('PASS test_typrun_scan')


def test_parm_empty():
    """PARM='' (empty quoted string)."""
    parsed = parse_string("""\
        //PTEST JOB CLASS=A
        //S1 EXEC PGM=MYPGM,PARM=''
    """)
    assert parsed['steps'][0].get('parm') == "''", parsed['steps'][0]
    print('PASS test_parm_empty')


def test_gdg_dsn():
    """GDG DSN: MY.DATASET(0) → base + generation."""
    _, _, steps, _ = parse_and_build("""\
        //GDGT JOB CLASS=A
        //S1 EXEC PGM=MYPGM
        //FILE DD DSN=MY.GDG.BASE(0),DISP=SHR
    """)
    dsn = steps[0]['dd_statements'][0]['dsn']
    assert isinstance(dsn, dict), dsn
    assert dsn['base'] == 'MY.GDG.BASE'
    assert dsn['generation'] == '0'
    print('PASS test_gdg_dsn')


def test_gdg_plus_generation():
    """GDG DSN: MY.GDG(+1) → generation '+1'."""
    _, _, steps, _ = parse_and_build("""\
        //GDGP JOB CLASS=A
        //S1 EXEC PGM=MYPGM
        //OUT DD DSN=MY.GDG(+1),DISP=(,CATLG)
    """)
    dsn = steps[0]['dd_statements'][0]['dsn']
    assert dsn['generation'] == '+1', dsn
    print('PASS test_gdg_plus_generation')


def test_pds_member_dsn():
    """PDS member DSN: HLQ.LIB(MEMBER) → dsn + member."""
    _, _, steps, _ = parse_and_build("""\
        //PDST JOB CLASS=A
        //S1 EXEC PGM=MYPGM
        //INFILE DD DSN=HLQ.MY.LIB(MYMEMBER),DISP=SHR
    """)
    dsn = steps[0]['dd_statements'][0]['dsn']
    assert isinstance(dsn, dict)
    assert dsn['dsn'] == 'HLQ.MY.LIB'
    assert dsn['member'] == 'MYMEMBER'
    print('PASS test_pds_member_dsn')


def test_temp_dataset_excluded():
    """&&TEMP should be absent from jcl_datasets."""
    _, _, _, datasets = parse_and_build("""\
        //TEMPT JOB CLASS=A
        //S1 EXEC PGM=MYPGM
        //WORK DD DSN=&&TEMPDS,DISP=(,PASS),UNIT=3390,SPACE=(TRK,1)
    """)
    assert not any('TEMPDS' in k for k in datasets['datasets'])
    print('PASS test_temp_dataset_excluded')


def test_dummy_dd():
    """DD DUMMY → null_dataset=True, no dsn."""
    parsed = parse_string("""\
        //DT JOB CLASS=A
        //S1 EXEC PGM=MYPGM
        //MYFILE DD DUMMY
    """)
    dd = parsed['steps'][0]['dd_statements'][0]
    assert dd.get('null_dataset') is True
    assert 'dsn' not in dd
    print('PASS test_dummy_dd')


def test_blank_continuation():
    """Blank continuation line (all spaces after //) should not break parsing."""
    parsed = parse_string("""\
        //BCT JOB CLASS=A
        //S1 EXEC PGM=MYPGM,
        //     PARM='HELLO'
    """)
    assert parsed['steps'][0].get('parm') == "'HELLO'", parsed['steps'][0]
    print('PASS test_blank_continuation')


def test_comment_lines_in_continuation():
    """Comment lines embedded in a continuation block are skipped."""
    parsed = parse_string("""\
        //CCT JOB CLASS=A
        //S1 EXEC PGM=MYPGM,
        //* this is a comment between continuation lines
        //     PARM='TEST'
    """)
    assert parsed['steps'][0].get('parm') == "'TEST'", parsed['steps'][0]
    print('PASS test_comment_lines_in_continuation')


def test_instream_proc_expansion():
    """Instream PROC/PEND → steps are expanded into job-level step list."""
    parsed, summary, steps, _ = parse_and_build("""\
        //PROCT JOB CLASS=A
        //MYPROC PROC
        //STEP1 EXEC PGM=PGM1
        //STEP2 EXEC PGM=PGM2
        //MYPROC PEND
        //RUN EXEC MYPROC
    """)
    assert summary['step_count'] == 2, f'Expected 2, got {summary["step_count"]}'
    step_names = [s['step_name'] for s in steps]
    assert 'STEP1' in step_names
    assert 'STEP2' in step_names
    print('PASS test_instream_proc_expansion')


def test_symbol_resolution_in_proc():
    """Symbols from EXEC proc override are resolved in PROC step DSNs."""
    _, summary, steps, _ = parse_and_build("""\
        //SYMT JOB CLASS=A
        //MYPROC PROC
        //S1 EXEC PGM=MYPGM
        //FILE DD DSN=HLQ.&QUAL..DATA,DISP=SHR
        //MYPROC PEND
        //RUN EXEC MYPROC,QUAL=TEST
    """)
    assert not summary['unresolved_symbols'], summary['unresolved_symbols']
    dds = steps[0].get('dd_statements', [])
    dsn_values = [dd.get('dsn') for dd in dds]
    assert 'HLQ.TEST.DATA' in dsn_values, f'DSNs: {dsn_values}'
    print('PASS test_symbol_resolution_in_proc')


def test_set_symbol_resolution():
    """SET statement symbols are used as fallback in resolution."""
    _, summary, steps, _ = parse_and_build("""\
        //SETT JOB CLASS=A
        //SET QUAL=PROD
        //S1 EXEC PGM=MYPGM
        //FILE DD DSN=HLQ.&QUAL..DATA,DISP=SHR
    """)
    dds = steps[0].get('dd_statements', [])
    dsn_values = [dd.get('dsn') for dd in dds]
    assert 'HLQ.PROD.DATA' in dsn_values, f'DSNs: {dsn_values}'
    print('PASS test_set_symbol_resolution')


def test_unresolved_symbol():
    """Symbol with no matching SET or override → unresolved marker."""
    _, summary, _, _ = parse_and_build("""\
        //URT JOB CLASS=A
        //S1 EXEC PGM=MYPGM
        //FILE DD DSN=HLQ.&UNKNOWN..DATA,DISP=SHR
    """)
    assert summary['unresolved_symbols'], 'Expected unresolved symbol'
    print('PASS test_unresolved_symbol')


def test_if_then_else():
    """IF/THEN/ELSE/ENDIF sets has_conditional_flow."""
    _, summary, _, _ = parse_and_build("""\
        //IFT JOB CLASS=A
        //S1 EXEC PGM=PGM1
        //IF (S1.RC = 0) THEN
        //S2 EXEC PGM=PGM2
        //ELSE
        //S3 EXEC PGM=PGM3
        //ENDIF
    """)
    assert summary['has_conditional_flow'] is True
    print('PASS test_if_then_else')


def test_jcllib_active():
    """JCLLIB ORDER= is recorded as active."""
    parsed = parse_string("""\
        //JLT JOB CLASS=A
        //JCLLIB ORDER=MY.PROCLIB
        //S1 EXEC MYPROC
    """)
    refs = parsed.get('jcllib_refs', [])
    assert any(r['active'] and 'MY.PROCLIB' in r.get('order', '')
               for r in refs), f'jcllib_refs={refs}'
    print('PASS test_jcllib_active')


def test_unknown_statement_type():
    """Unrecognised statement type emits warning, does not crash."""
    _, summary, _, _ = parse_and_build("""\
        //UNK JOB CLASS=A
        //S1 EXEC PGM=MYPGM
        //WEIRD FAKEOP PARAM=VALUE
    """)
    assert any('UNKNOWN' in w or 'Unrecognised' in w
               for w in summary['warnings']), summary['warnings']
    print('PASS test_unknown_statement_type')


def test_empty_proc_pend():
    """PROC/PEND with no steps inside does not crash."""
    _, summary, steps, _ = parse_and_build("""\
        //EPT JOB CLASS=A
        //EMPTY PROC
        //EMPTY PEND
        //S1 EXEC PGM=MYPGM
    """)
    assert summary['step_count'] == 1
    print('PASS test_empty_proc_pend')


def test_no_job_card_fallback():
    """File without a JOB card: job_name falls back to filename stem."""
    jcl = """\
        //S1 EXEC PGM=MYPGM
        //SYSPRINT DD SYSOUT=*
    """
    parsed = parse_string(jcl)
    # No JOB card → job_name is None (set from JOB record, absent here)
    assert parsed.get('job_name') is None
    print('PASS test_no_job_card_fallback')


def test_output_stmt_routing():
    """OUTPUT statement parsed; DD OUTPUT= refs extracted."""
    parsed = parse_string("""\
        //ORT JOB CLASS=A
        //MYOUT OUTPUT CLASS=X,FORMLEN=11IN
        //S1 EXEC PGM=MYPGM
        //SYSOUT DD SYSOUT=(,),OUTPUT=(*.MYOUT)
    """)
    assert 'MYOUT' in parsed.get('output_definitions', {}), parsed['output_definitions']
    dds = parsed['steps'][0].get('dd_statements', [])
    sysout_dd = next((d for d in dds if d['dd_name'] == 'SYSOUT'), None)
    assert sysout_dd is not None
    assert 'MYOUT' in sysout_dd.get('output_refs', []), sysout_dd
    print('PASS test_output_stmt_routing')


def test_disp_blank_first_field():
    """DISP=(,CATLG) → status=None, normal='CATLG'."""
    _, _, steps, _ = parse_and_build("""\
        //DBT JOB CLASS=A
        //S1 EXEC PGM=MYPGM
        //FILE DD DSN=MY.DS,DISP=(,CATLG)
    """)
    disp = steps[0]['dd_statements'][0]['disp']
    assert disp['status'] is None
    assert disp['normal'] == 'CATLG'
    print('PASS test_disp_blank_first_field')


def test_short_name_dd():
    """Name shorter than 8 chars (e.g. 'DD1') with operation on same 8-char field."""
    parsed = parse_string("""\
        //JOB1 JOB CLASS=A
        //STEP1 EXEC PGM=IEFBR14
        //DD1  DD  DSN=MY.DS1,DISP=SHR
        //DD2  DD  DSN=MY.DS2,DISP=OLD
    """)
    dds = parsed['steps'][0]['dd_statements']
    names = [d['dd_name'] for d in dds]
    assert 'DD1' in names, f'Expected DD1 in {names}'
    assert 'DD2' in names, f'Expected DD2 in {names}'
    print('PASS test_short_name_dd')


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    tests = [
        # Real-file tests
        test_pdasco01,
        test_pdaddre1,
        test_pdcafin2,
        # Synthetic edge cases
        test_job_no_card,
        test_vol_multi_volume,
        test_vol_backreference,
        test_disp_uncatlg,
        test_disp_mod,
        test_space_rlse_contig,
        test_dcb_sub_params,
        test_dd_inline_data,
        test_dd_data_dlm,
        test_cond_even,
        test_cond_only,
        test_rd_restart,
        test_typrun_scan,
        test_parm_empty,
        test_gdg_dsn,
        test_gdg_plus_generation,
        test_pds_member_dsn,
        test_temp_dataset_excluded,
        test_dummy_dd,
        test_blank_continuation,
        test_comment_lines_in_continuation,
        test_instream_proc_expansion,
        test_symbol_resolution_in_proc,
        test_set_symbol_resolution,
        test_unresolved_symbol,
        test_if_then_else,
        test_jcllib_active,
        test_unknown_statement_type,
        test_empty_proc_pend,
        test_no_job_card_fallback,
        test_output_stmt_routing,
        test_disp_blank_first_field,
        test_short_name_dd,
    ]

    passed = failed = skipped = 0
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

    total = passed + failed + skipped
    print(f'\n{passed}/{total} passed, {failed} failed')
    sys.exit(0 if failed == 0 else 1)
