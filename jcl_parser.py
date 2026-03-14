#!/usr/bin/env python3
"""
JCL Parser — hand-written column-based IBM JCL parser.

Parses JOB, EXEC, DD, PROC/PEND (instream), OUTPUT, SET, IF/THEN/ELSE/ENDIF,
JCLLIB, and INCLUDE statements. Writes three JSON artifacts per job:
  out/report/<JOBNAME>.jcl.report/jcl_summary.json
  out/report/<JOBNAME>.jcl.report/jcl_steps.json
  out/report/<JOBNAME>.jcl.report/jcl_datasets.json

Usage:
  python3 jcl_parser.py path/to/JOB.jcl --output-dir out/report --verbose
"""

import argparse
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class LogicalRecord:
    """A single logical JCL statement (continuation lines already joined)."""
    type: str           # JOB EXEC DD PROC PEND OUTPUT SET IF THEN ELSE ENDIF
                        # JCLLIB PROCLIB INCLUDE COMMENT INLINE_DATA UNKNOWN
    name: str           # cols 3-10, stripped; empty for nameless statements
    operation: str      # JOB / EXEC / DD / etc.
    operand: str        # full joined operand (continuation lines concatenated)
    inline_count: int = 0   # for INLINE_DATA: number of data lines consumed
    line_num: int = 0   # first physical line (1-based)


# ---------------------------------------------------------------------------
# Known statement types and special DD names
# ---------------------------------------------------------------------------

_KNOWN_OPS = {
    'JOB', 'EXEC', 'DD', 'PROC', 'PEND', 'OUTPUT', 'SET',
    'IF', 'THEN', 'ELSE', 'ENDIF', 'JCLLIB', 'PROCLIB',
    'INCLUDE', 'COMMAND', 'EXPORT', 'XMIT', 'NOTIFY',
}

_EXEC_KEYWORDS = {
    'PGM', 'PROC', 'PARM', 'COND', 'REGION', 'TIME',
    'DYNAMNBR', 'ACCT', 'RD',
}

_SPECIAL_DD_ROLES = {
    'JOBLIB':   'library_override',
    'STEPLIB':  'library_override',
    'SYSIN':    'program_input',
    'SYSPRINT': 'system_print',
    'SYSOUT':   'system_output',
    'SYSERR':   'system_error',
    'SYSUDUMP': 'diagnostic_dump',
    'SYSABEND': 'diagnostic_dump',
}

# System utility programs (excluded from programs_invoked)
_SYSTEM_PGMS = {'IEFBR14', 'ICEMAN', 'IDCAMS', 'IEBGENER', 'SORT', 'PARM2SK'}


# ---------------------------------------------------------------------------
# Core parser class
# ---------------------------------------------------------------------------

class JCLParser:
    """Hand-written IBM JCL parser."""

    def __init__(self, jcl_path: Path, verbose: bool = False):
        self.jcl_path = Path(jcl_path)
        self.verbose = verbose
        self.warnings: list[str] = []

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def parse(self) -> dict:
        """Parse the JCL file. Returns a structured dict."""
        lines = self._read_lines()
        records = self._tokenize(lines)
        return self._parse_records(records)

    # ------------------------------------------------------------------
    # 1. Read lines with encoding fallback
    # ------------------------------------------------------------------

    def _read_lines(self) -> list[str]:
        for enc in ('utf-8', 'latin-1'):
            try:
                return self.jcl_path.read_text(encoding=enc).splitlines()
            except UnicodeDecodeError:
                continue
        # Last resort: ignore errors
        return self.jcl_path.read_text(encoding='latin-1', errors='replace').splitlines()

    # ------------------------------------------------------------------
    # 2. Tokenizer: produce LogicalRecords
    # ------------------------------------------------------------------

    def _tokenize(self, lines: list[str]) -> list[LogicalRecord]:
        records: list[LogicalRecord] = []
        i = 0
        in_inline = False
        inline_delim = '/*'
        inline_count = 0
        inline_start_rec: Optional[LogicalRecord] = None

        while i < len(lines):
            raw = lines[i]
            # Strip cols 73-80 (indices 72+) and trailing whitespace
            line = raw[:72].rstrip()
            i += 1

            # ---- inline data mode ----
            if in_inline:
                # Check for delimiter (/*  or DLM=xx value)
                stripped = line.strip()
                if stripped == inline_delim or line.startswith(inline_delim + ' ') or line == inline_delim:
                    in_inline = False
                    if inline_start_rec is not None:
                        inline_start_rec.inline_count = inline_count
                    inline_count = 0
                else:
                    inline_count += 1
                continue

            # ---- lines that are not JCL ----
            if not line.startswith('//'):
                continue

            # ---- delimiter line (/* ...) ----
            if line.startswith('/*'):
                in_inline = False
                continue

            # ---- comment line (//* ...) ----
            if len(line) > 2 and line[2] == '*':
                # Check for commented-out JCLLIB
                m = re.search(r'JCLLIB\s+ORDER=(\S+)', line, re.IGNORECASE)
                if m:
                    records.append(LogicalRecord(
                        type='_COMMENT_JCLLIB',
                        name='',
                        operation='JCLLIB',
                        operand=f'ORDER={m.group(1)}',
                        line_num=i,
                    ))
                continue

            # ---- named or nameless JCL statement ----
            # Two cases for blank at col 3:
            #   (a) True continuation line (already consumed by _collect_operand)
            #   (b) Nameless statement whose keyword starts after blanks
            #       (ELSE, ENDIF, SET, JCLLIB, INCLUDE, etc.)
            name = ''
            operation = ''
            first_frag = ''

            if len(line) > 2 and line[2] == ' ':
                # Extract the first non-blank token; if it's a known operation
                # keyword treat this as a nameless statement, else skip.
                rest = line[2:].lstrip()
                if not rest:
                    continue
                rest_parts = rest.split(None, 2)
                candidate = rest_parts[0].upper()
                if candidate not in _KNOWN_OPS:
                    continue  # stray continuation line
                name = ''
                operation = candidate
                if len(rest_parts) == 1:
                    first_frag = ''
                elif len(rest_parts) == 2:
                    first_frag = rest_parts[1]
                else:
                    first_frag = rest_parts[1] + ' ' + rest_parts[2]
            else:
                # Parse name and operation as tokens from col 3 onwards.
                # IBM JCL: name is the first token (≤8 chars), operation follows.
                # Fixed-column extraction fails when the name is short (e.g. "DD1")
                # and the operation starts inside the 8-char field.
                content = line[2:] if len(line) > 2 else ''
                parts = content.split(None, 2)
                if not parts:
                    continue

                first_tok = parts[0].upper()
                second_tok = parts[1].upper() if len(parts) > 1 else ''

                # Detect nameless statement: a known operation keyword appears
                # directly at col 3 (e.g. //JCLLIB ORDER=..., //IF (cond) THEN,
                # //ELSE, //ENDIF).  Heuristic: if the first token is a known op
                # keyword AND the second token is NOT, treat it as nameless.
                # If both are known ops (e.g. //PROC EXEC PGM=...) the first
                # token is a step name.
                if first_tok in _KNOWN_OPS and (not second_tok or second_tok not in _KNOWN_OPS):
                    name = ''
                    operation = first_tok
                    if len(parts) == 1:
                        first_frag = ''
                    elif len(parts) == 2:
                        first_frag = parts[1]
                    else:
                        first_frag = parts[1] + ' ' + parts[2]
                else:
                    if len(parts) < 2:
                        continue  # only name, no operation
                    name = parts[0]
                    operation = parts[1].upper()
                    first_frag = parts[2] if len(parts) > 2 else ''

            # Collect continuation lines
            operand, i = self._collect_operand(lines, i, first_frag)

            # Determine record type
            rec_type = operation if operation in _KNOWN_OPS else 'UNKNOWN'

            rec = LogicalRecord(
                type=rec_type,
                name=name,
                operation=operation,
                operand=operand,
                line_num=i,
            )
            records.append(rec)

            # Check for inline data DD
            if rec_type == 'DD':
                trimmed_op = operand.strip()
                is_inline = trimmed_op == '*' or trimmed_op.startswith('DATA') or trimmed_op == 'DATA'
                dlm_m = re.search(r'DLM=(.{2})', operand)
                if is_inline:
                    in_inline = True
                    inline_delim = dlm_m.group(1) if dlm_m else '/*'
                    inline_count = 0
                    inline_start_rec = rec

        return records

    def _collect_operand(self, lines: list[str], start_i: int, first_frag: str) -> tuple[str, int]:
        """
        Collect continuation lines into a single operand string.
        Returns (full_operand, next_line_index).
        """
        operand = self._trim_informal_comment(first_frag)
        i = start_i

        while operand.rstrip().endswith(','):
            # Scan forward for next non-comment continuation line
            found = False
            j = i
            while j < len(lines):
                raw = lines[j]
                line = raw[:72].rstrip()
                j += 1

                if not line.startswith('//'):
                    continue
                if len(line) > 2 and line[2] == '*':
                    # comment — skip, but stay in continuation search
                    continue
                if line.startswith('/*'):
                    break
                # Must be continuation: col 3 is blank
                if len(line) > 2 and line[2] != ' ':
                    break
                # Continuation line: operand starts at col 4 (index 3) stripped
                frag = line[3:71].lstrip() if len(line) > 3 else ''
                frag = self._trim_informal_comment(frag)
                operand += frag
                i = j
                found = True
                break

            if not found:
                break

        return operand, i

    def _trim_informal_comment(self, text: str) -> str:
        """
        Remove informal comment: stop at first unquoted space outside parens.
        Quoted strings ('...') preserve spaces. Embedded '' = literal quote.
        """
        in_quote = False
        result = []
        k = 0
        while k < len(text):
            ch = text[k]
            if in_quote:
                result.append(ch)
                if ch == "'":
                    # Check for doubled quote
                    if k + 1 < len(text) and text[k + 1] == "'":
                        result.append("'")
                        k += 2
                        continue
                    in_quote = False
            else:
                if ch == "'":
                    in_quote = True
                    result.append(ch)
                elif ch == ' ':
                    # End of operand field — rest is informal comment
                    break
                else:
                    result.append(ch)
            k += 1
        return ''.join(result)

    # ------------------------------------------------------------------
    # 3. Parse logical records
    # ------------------------------------------------------------------

    def _parse_records(self, records: list[LogicalRecord]) -> dict:
        parsed = {
            'job_name': None,
            'job_params': {},
            'output_definitions': {},
            'proc_definitions': {},
            'steps': [],
            'jcllib_refs': [],
            'include_refs': [],
            'if_constructs': [],
            'has_conditional_flow': False,
            'set_symbols': {},
            'unknown_statements': [],
            'warnings': self.warnings,
        }

        # Track instream PROC parsing
        proc_stack: list[dict] = []
        proc_definitions: dict[str, list] = {}
        pend_seen: set[str] = set()

        for rec in records:
            op = rec.type

            if op == 'JOB':
                parsed['job_name'] = rec.name or self.jcl_path.stem
                parsed['job_params'] = self._parse_job_params(rec.operand)

            elif op == 'EXEC':
                step = self._parse_exec_params(rec.name, rec.operand)
                if proc_stack:
                    proc_stack[-1]['steps'].append(step)
                else:
                    parsed['steps'].append(step)

            elif op == 'DD':
                dd = self._parse_dd_params(rec.name, rec.operand, rec.inline_count)
                # Attach to last step
                target_steps = proc_stack[-1]['steps'] if proc_stack else parsed['steps']
                if target_steps:
                    last_step = target_steps[-1]
                    if rec.name:
                        last_step.setdefault('dd_statements', []).append(dd)
                    else:
                        # Concatenation: append to last DD
                        dds = last_step.get('dd_statements', [])
                        if dds:
                            dds[-1].setdefault('concatenations', []).append(dd)

            elif op == 'PROC':
                proc_stack.append({'proc_name': rec.name, 'steps': []})

            elif op == 'PEND':
                if proc_stack:
                    completed = proc_stack.pop()
                    pname = completed['proc_name']
                    proc_definitions[pname] = completed['steps']
                    pend_seen.add(pname)
                    parsed['proc_definitions'][pname] = completed['steps']

            elif op == 'SET':
                kv = self._parse_keyword_params(rec.operand)
                parsed['set_symbols'].update(kv)

            elif op in ('IF', 'THEN', 'ELSE', 'ENDIF'):
                parsed['has_conditional_flow'] = True
                parsed['if_constructs'].append({'type': op, 'operand': rec.operand})

            elif op == 'JCLLIB':
                order_m = re.search(r'ORDER=(\S+)', rec.operand, re.IGNORECASE)
                parsed['jcllib_refs'].append({
                    'active': True,
                    'order': order_m.group(1) if order_m else rec.operand,
                })

            elif op == '_COMMENT_JCLLIB':
                order_m = re.search(r'ORDER=(\S+)', rec.operand, re.IGNORECASE)
                parsed['jcllib_refs'].append({
                    'active': False,
                    'order': order_m.group(1) if order_m else rec.operand,
                })

            elif op == 'INCLUDE':
                member_m = re.search(r'MEMBER=(\S+)', rec.operand, re.IGNORECASE)
                parsed['include_refs'].append(member_m.group(1) if member_m else rec.operand)

            elif op == 'OUTPUT':
                out_def = self._parse_output_stmt(rec.name, rec.operand)
                parsed['output_definitions'][rec.name] = out_def

            elif op not in _KNOWN_OPS and op != '_COMMENT_JCLLIB':
                self.warnings.append(f'Unrecognised statement type: {op}')
                parsed['unknown_statements'].append({
                    'name': rec.name,
                    'operation': op,
                    'raw_operand': rec.operand,
                })

        # Resolve EXEC invocations that reference instream PROCs
        self._resolve_proc_invocations(parsed, proc_definitions, pend_seen)

        # Shared set for tracking unresolved symbol references
        parsed['_unresolved'] = set()

        # Resolve symbols in all steps
        self._apply_symbol_resolution(parsed)

        return parsed

    # ------------------------------------------------------------------
    # 4. Statement-level parsers
    # ------------------------------------------------------------------

    def _parse_job_params(self, operand: str) -> dict:
        params, positional = self._parse_keyword_params_with_positional(operand)
        result: dict = {}

        # Positional params: first = job_account, second = programmer_name
        if len(positional) >= 1:
            result['job_account'] = positional[0].strip("()'")
        if len(positional) >= 2:
            result['programmer_name'] = positional[1].strip("'")

        # Known keywords
        for kw in ('CLASS', 'MSGCLASS', 'MSGLEVEL', 'REGION', 'TIME',
                   'NOTIFY', 'USER', 'ADDRSPC', 'TYPRUN', 'RESTART'):
            if kw in params:
                result[kw.lower()] = params.pop(kw)

        if 'COND' in params:
            result['job_cond'] = params.pop('COND')

        # Resource limits
        limits = {}
        for kw in ('BYTES', 'CARDS', 'LINES', 'PAGES'):
            if kw in params:
                limits[kw.lower()] = params.pop(kw)
        if limits:
            result['resource_limits'] = limits

        # Remainder
        if params:
            result['extra_params'] = params

        return result

    def _parse_exec_params(self, step_name: str, operand: str) -> dict:
        params, positional = self._parse_keyword_params_with_positional(operand)
        step: dict = {'step_name': step_name, 'dd_statements': []}

        # Check for COND EVEN/ONLY modifier
        cond_modifier = None
        for mod in ('EVEN', 'ONLY'):
            # Can appear as standalone positional or appended to COND value
            if mod in positional:
                positional.remove(mod)
                cond_modifier = mod
            elif 'COND' in params and mod in params['COND'].upper():
                cond_modifier = mod

        # PGM or PROC invocation
        if 'PGM' in params:
            pgm_val = params.pop('PGM')
            step['program'] = self._maybe_unresolved(pgm_val)
            step['proc'] = None
            step['proc_source'] = None
        else:
            # PROC= explicit or positional (first token before any keyword)
            proc_val = params.pop('PROC', None)
            if proc_val is None and positional:
                proc_val = positional.pop(0)
            step['program'] = None
            step['proc'] = proc_val
            step['proc_source'] = 'cataloged'  # may be updated later

        # Extract standard keywords
        for kw in ('PARM', 'COND', 'REGION', 'TIME', 'DYNAMNBR', 'ACCT', 'RD'):
            if kw in params:
                step[kw.lower()] = params.pop(kw)

        if cond_modifier:
            step['cond_modifier'] = cond_modifier

        # Remainder = PROC override parameters
        if params:
            step['proc_overrides'] = params

        return step

    def _parse_dd_params(self, dd_name: str, operand: str, inline_count: int = 0) -> dict:
        dd: dict = {'dd_name': dd_name}

        # Special DD names
        upper_name = dd_name.upper()
        if upper_name in _SPECIAL_DD_ROLES:
            dd['special_dd'] = True
            dd['role'] = _SPECIAL_DD_ROLES[upper_name]

        # DUMMY shorthand
        trimmed = operand.strip()
        if trimmed.upper().startswith('DUMMY'):
            dd['null_dataset'] = True
            remainder = trimmed[5:].lstrip()
            if remainder:
                self.warnings.append(
                    f'Unexpected trailing text on DD {dd_name}: {remainder!r}')
            return dd

        # Inline data
        if trimmed == '*' or trimmed.startswith('DATA'):
            dd['inline_data'] = True
            dd['inline_data_lines'] = inline_count
            dlm_m = re.search(r'DLM=(.{2})', operand)
            if dlm_m:
                dd['inline_delimiter'] = dlm_m.group(1)
            return dd

        params, _ = self._parse_keyword_params_with_positional(operand)

        # DSN
        if 'DSN' in params:
            dd['dsn'] = self._parse_dsn(params.pop('DSN'))
        elif 'DATASET' in params:
            dd['dsn'] = self._parse_dsn(params.pop('DATASET'))

        # DISP
        if 'DISP' in params:
            dd['disp'] = self._parse_disp(params.pop('DISP'))
            dd['access'] = self._classify_dd_access(dd['disp'].get('status'))

        # Optional structured params
        if 'DCB' in params:
            dd['dcb'] = self._parse_dcb(params.pop('DCB'))
        if 'VOL' in params:
            dd['vol'] = self._parse_vol(params.pop('VOL'))
        if 'SPACE' in params:
            dd['space'] = self._parse_space(params.pop('SPACE'))
        if 'UNIT' in params:
            dd['unit'] = params.pop('UNIT')
        if 'LABEL' in params:
            dd['label'] = params.pop('LABEL')
        if 'SYSOUT' in params:
            dd['sysout_class'] = params.pop('SYSOUT')
        if 'OUTPUT' in params:
            # Extract referenced output names: (*.NAME1,*.NAME2)
            out_val = params.pop('OUTPUT')
            refs = re.findall(r'\*\.([A-Za-z0-9@#$]+)', out_val)
            dd['output_refs'] = refs
        if 'NULLFILE' in params or params.get('DSN') == 'NULLFILE':
            dd['null_dataset'] = True

        # Remaining unknown params
        if params:
            dd['extra_params'] = params

        return dd

    def _parse_output_stmt(self, name: str, operand: str) -> dict:
        """Parse OUTPUT statement (JES output routing definition)."""
        params, _ = self._parse_keyword_params_with_positional(operand)
        result: dict = {'output_name': name}
        for kw in ('CLASS', 'DEFAULT', 'FORMLEN', 'NAME', 'COPIES', 'PRTY'):
            if kw in params:
                result[kw.lower()] = params.pop(kw)
        if params:
            result['extra_params'] = params
        return result

    # ------------------------------------------------------------------
    # 5. Field-level parsers
    # ------------------------------------------------------------------

    def _parse_keyword_params(self, operand: str) -> dict:
        result, _ = self._parse_keyword_params_with_positional(operand)
        return result

    def _parse_keyword_params_with_positional(self, operand: str) -> tuple[dict, list]:
        """
        Parse JCL keyword=value pairs from a joined operand string.
        Returns (keyword_dict, positional_list).
        Handles quoted strings, parenthesized values, and positional params.
        """
        tokens = self._split_operand(operand)
        keywords: dict = {}
        positional: list = []
        for token in tokens:
            if '=' in token:
                idx = token.index('=')
                key = token[:idx].strip().upper()
                val = token[idx + 1:].strip()
                keywords[key] = val
            else:
                t = token.strip()
                if t:
                    positional.append(t)
        return keywords, positional

    def _split_operand(self, operand: str) -> list[str]:
        """
        Split operand on commas, respecting quotes and parentheses.
        Returns list of raw token strings.
        """
        tokens = []
        current = []
        in_quote = False
        paren_depth = 0
        k = 0
        while k < len(operand):
            ch = operand[k]
            if in_quote:
                current.append(ch)
                if ch == "'":
                    if k + 1 < len(operand) and operand[k + 1] == "'":
                        current.append("'")
                        k += 2
                        continue
                    in_quote = False
            elif ch == "'":
                in_quote = True
                current.append(ch)
            elif ch == '(':
                paren_depth += 1
                current.append(ch)
            elif ch == ')':
                paren_depth = max(0, paren_depth - 1)
                current.append(ch)
            elif ch == ',' and paren_depth == 0:
                tokens.append(''.join(current))
                current = []
            else:
                current.append(ch)
            k += 1
        if current:
            tokens.append(''.join(current))
        return [t for t in tokens if t.strip()]

    def _parse_dsn(self, raw: str) -> dict | str:
        """Parse DSN value into structured form."""
        s = raw.strip().strip("'")
        upper = s.upper()

        if upper == 'NULLFILE':
            return {'null_dataset': True}

        # Temporary dataset (&&NAME)
        if s.startswith('&&'):
            return {'dsn': s[2:], 'temporary': True}

        # GDG / PDS member: NAME(something)
        m = re.match(r'^([^(]+)\(([^)]+)\)$', s)
        if m:
            base = m.group(1)
            qualifier = m.group(2)
            # GDG: qualifier is a signed integer or 0
            if re.match(r'^[+-]?\d+$', qualifier):
                return {'base': base, 'generation': qualifier}
            # PDS member
            return {'dsn': base, 'member': qualifier}

        return s

    def _parse_disp(self, raw: str) -> dict:
        """Parse DISP value into {status, normal, abnormal}."""
        s = raw.strip()
        if s.startswith('(') and s.endswith(')'):
            inner = s[1:-1]
            parts = self._split_simple(inner, ',')
        else:
            parts = [s]

        def norm(v):
            v = v.strip()
            return v if v else None

        return {
            'status':   norm(parts[0]) if len(parts) > 0 else None,
            'normal':   norm(parts[1]) if len(parts) > 1 else None,
            'abnormal': norm(parts[2]) if len(parts) > 2 else None,
        }

    def _classify_dd_access(self, status: Optional[str]) -> str:
        if not status:
            return 'special'
        s = status.upper()
        if s in ('SHR', 'OLD'):
            return 'read'
        if s in ('NEW', 'MOD'):
            return 'write'
        if s == 'PASS':
            return 'pass'
        return 'special'

    def _parse_dcb(self, raw: str) -> dict | str:
        """Parse DCB value."""
        s = raw.strip()
        # Back-reference: DCB=(*.DDNAME) or DCB=*.STEP.DDNAME
        br_m = re.match(r'^\(?\*\.([A-Za-z0-9.]+)\)?$', s)
        if br_m:
            return {'backreference': br_m.group(1)}
        # Sub-params
        inner = s.strip('()')
        parts = self._split_simple(inner, ',')
        result = {}
        for p in parts:
            p = p.strip()
            if '=' in p:
                k, v = p.split('=', 1)
                result[k.strip().lower()] = v.strip()
        return result if result else s

    def _parse_vol(self, raw: str) -> dict:
        """Parse VOL parameter."""
        s = raw.strip()
        result = {}

        # VOL=REF=*.DDNAME or VOL=REF=*.STEP.DDNAME
        ref_m = re.match(r'^REF=\*\.(.+)$', s, re.IGNORECASE)
        if ref_m:
            return {'vol_ref': ref_m.group(1)}

        # VOL=SER=X or VOL=SER=(X,Y,Z)
        ser_m = re.match(r'^SER=(.+)$', s, re.IGNORECASE)
        if ser_m:
            val = ser_m.group(1).strip()
            if val.startswith('(') and val.endswith(')'):
                vols = [v.strip() for v in self._split_simple(val[1:-1], ',')]
                result['ser'] = vols
            else:
                result['ser'] = val
            return result

        # Parenthetical form: VOL=(PRIVATE) or VOL=(,,,PRIVATE)
        if s.startswith('(') and s.endswith(')'):
            parts = self._split_simple(s[1:-1], ',')
            for p in parts:
                p = p.strip().upper()
                if p == 'PRIVATE':
                    result['private'] = True
                elif p == 'RETAIN':
                    result['retain'] = True
        return result if result else {'raw': s}

    def _parse_space(self, raw: str) -> dict:
        """Parse SPACE parameter."""
        s = raw.strip()
        result = {}
        if s.startswith('(') and s.endswith(')'):
            # Split top-level commas
            parts = self._split_operand(s[1:-1])
        else:
            parts = [s]

        if len(parts) >= 1:
            result['unit'] = parts[0].strip()
        if len(parts) >= 2:
            alloc = parts[1].strip()
            if alloc.startswith('(') and alloc.endswith(')'):
                sub = self._split_simple(alloc[1:-1], ',')
                result['primary'] = sub[0].strip() if len(sub) > 0 else None
                result['secondary'] = sub[1].strip() if len(sub) > 1 else None
            else:
                result['primary'] = alloc
        for p in parts[2:]:
            p = p.strip().upper()
            if p == 'RLSE':
                result['rlse'] = True
            elif p == 'CONTIG':
                result['contig'] = True
            elif p == 'ROUND':
                result['round'] = True
        return result

    def _parse_cond(self, raw: str) -> dict:
        """Parse COND value, noting EVEN/ONLY modifiers."""
        s = raw.strip()
        modifier = None
        for mod in ('EVEN', 'ONLY'):
            if s.upper().endswith(',' + mod) or s.upper() == mod:
                modifier = mod
                s = re.sub(r',?' + mod + r'$', '', s, flags=re.IGNORECASE).strip()
        return {'value': s, 'modifier': modifier}

    def _maybe_unresolved(self, val: str) -> dict | str:
        if '&' in val:
            return {'value': val, 'resolved': False}
        return val

    # ------------------------------------------------------------------
    # 6. Symbolic resolution
    # ------------------------------------------------------------------

    def _resolve_proc_invocations(self, parsed: dict,
                                   proc_definitions: dict[str, list],
                                   pend_seen: set[str]) -> None:
        """
        For each EXEC step that references an instream PROC (proc in pend_seen),
        expand the PROC's steps into the job-level step list and mark proc_source.
        """
        expanded: list[dict] = []
        for step in parsed['steps']:
            proc_name = step.get('proc')
            if proc_name and proc_name in pend_seen:
                # Mark as instream
                step['proc_source'] = 'instream'
                overrides = step.get('proc_overrides', {})
                # Expand PROC steps (deep copy, propagate overrides for resolution)
                for proc_step in proc_definitions.get(proc_name, []):
                    import copy
                    expanded_step = copy.deepcopy(proc_step)
                    expanded_step['_from_proc'] = proc_name
                    # Propagate overrides so _apply_symbol_resolution can resolve
                    # &SYMBOL references inside DSN, PARM, PGM of expanded steps
                    if overrides:
                        expanded_step.setdefault('proc_overrides', {}).update(overrides)
                    expanded.append(expanded_step)
                # Also keep the invocation record (as metadata)
                step['_proc_expanded'] = True
                expanded.append(step)
            else:
                expanded.append(step)
        parsed['steps'] = expanded

    def _apply_symbol_resolution(self, parsed: dict) -> None:
        """
        Resolve &SYMBOL references in all step fields using set_symbols
        and proc_overrides from each EXEC invocation.
        Unresolved symbols are collected into parsed['_unresolved'].
        """
        global_syms = parsed.get('set_symbols', {})
        unresolved_set = parsed['_unresolved']

        for step in parsed['steps']:
            syms = dict(global_syms)
            syms.update(step.get('proc_overrides', {}))
            # Always call _resolve_step so unresolved &SYMBOL refs are detected
            # even when syms is empty.
            self._resolve_step(step, syms, unresolved_set)

    def _resolve_step(self, step: dict, syms: dict, unresolved_set: set) -> None:
        """Apply symbol resolution to a step dict in-place."""
        # Resolve program
        if isinstance(step.get('program'), str) and '&' in step['program']:
            step['program'] = self._resolve_value(step['program'], syms, unresolved_set)
        if isinstance(step.get('proc'), str) and '&' in step['proc']:
            step['proc'] = self._resolve_value(step['proc'], syms, unresolved_set)
        if isinstance(step.get('parm'), str) and '&' in step['parm']:
            step['parm'] = self._resolve_value(step['parm'], syms, unresolved_set)

        # Resolve DD DSN values
        for dd in step.get('dd_statements', []):
            dsn = dd.get('dsn')
            if isinstance(dsn, str) and '&' in dsn:
                dd['dsn'] = self._resolve_value(dsn, syms, unresolved_set)
            elif isinstance(dsn, dict):
                for k in ('dsn', 'base'):
                    if k in dsn and isinstance(dsn[k], str) and '&' in dsn[k]:
                        dsn[k] = self._resolve_value(dsn[k], syms, unresolved_set)

    def _resolve_value(self, val: str, syms: dict, unresolved_set: set) -> str | dict:
        """
        Replace &SYMBOL references in val using syms dict.
        &SYMBOL. → value (period consumed as separator).
        &SYM1&SYM2 → concatenated values.
        Unresolved → {"value": val, "resolved": False} added to unresolved_set.
        """
        result = val
        # Replace &NAME. first (period-terminated)
        for sym, replacement in syms.items():
            result = result.replace(f'&{sym}.', str(replacement))
            result = result.replace(f'&{sym}', str(replacement))

        if '&' in result:
            unresolved_set.add(result)
            return {'value': result, 'resolved': False}
        return result

    # ------------------------------------------------------------------
    # 7. Output generation
    # ------------------------------------------------------------------

    def _build_outputs(self, parsed: dict, out_dir: Path) -> None:
        out_dir.mkdir(parents=True, exist_ok=True)

        # Start with any DSN/PARM-level unresolved symbols from symbol resolution
        unresolved: set = set(parsed.get('_unresolved', set()))
        programs_invoked: set = set()
        datasets_read: list = []
        datasets_written: list = []
        step_count = 0

        dataset_index: dict[str, dict] = {}

        steps_output = []
        for step in parsed['steps']:
            # Skip metadata-only EXEC invocation stubs
            if step.get('_proc_expanded') and step.get('proc'):
                continue

            pgm = step.get('program')
            if isinstance(pgm, str) and pgm and pgm.upper() not in _SYSTEM_PGMS:
                programs_invoked.add(pgm)
            elif isinstance(pgm, dict):
                unresolved.add(pgm.get('value', ''))

            step_count += 1
            step_out = {
                'step_name': step.get('step_name', ''),
                'program': pgm if pgm else None,
                'proc': step.get('proc'),
                'proc_source': step.get('proc_source'),
                'condition': step.get('cond'),
                'cond_modifier': step.get('cond_modifier'),
                'parm': step.get('parm'),
                'dd_statements': [],
            }

            for dd in step.get('dd_statements', []):
                dsn = dd.get('dsn')
                access = dd.get('access', 'special')
                step_out['dd_statements'].append(dd)

                if isinstance(dsn, dict) and dsn.get('temporary'):
                    continue
                if dd.get('null_dataset') or dd.get('inline_data'):
                    continue

                if isinstance(dsn, str) and dsn:
                    self._index_dataset(dataset_index, dsn, step.get('step_name', ''),
                                        pgm if isinstance(pgm, str) else '', access)
                    if access == 'read':
                        datasets_read.append(dsn)
                    elif access == 'write':
                        datasets_written.append(dsn)
                elif isinstance(dsn, dict):
                    key = dsn.get('dsn') or dsn.get('base', '')
                    if key:
                        self._index_dataset(dataset_index, key, step.get('step_name', ''),
                                            pgm if isinstance(pgm, str) else '', access)

            steps_output.append(step_out)

        # Summary
        summary = {
            'job_name': parsed.get('job_name', ''),
            'step_count': step_count,
            'programs_invoked': sorted(programs_invoked),
            'datasets_read': sorted(set(datasets_read)),
            'datasets_written': sorted(set(datasets_written)),
            'has_conditional_flow': parsed.get('has_conditional_flow', False),
            'unresolved_symbols': sorted(unresolved),
            'warnings': self.warnings,
        }
        job_p = parsed.get('job_params', {})
        for k in ('job_cond', 'region', 'class', 'typrun', 'restart'):
            if k in job_p:
                summary[k] = job_p[k]
        if parsed.get('output_definitions'):
            summary['output_definitions'] = parsed['output_definitions']

        (out_dir / 'jcl_summary.json').write_text(
            json.dumps(summary, indent=2, default=str), encoding='utf-8')

        (out_dir / 'jcl_steps.json').write_text(
            json.dumps(steps_output, indent=2, default=str), encoding='utf-8')

        (out_dir / 'jcl_datasets.json').write_text(
            json.dumps({'datasets': dataset_index}, indent=2, default=str), encoding='utf-8')

        if self.verbose:
            print(f'  [OK] jcl_summary.json  ({step_count} steps)')
            print(f'  [OK] jcl_steps.json')
            print(f'  [OK] jcl_datasets.json  ({len(dataset_index)} datasets)')

    def _index_dataset(self, index: dict, dsn: str, step: str, pgm: str, access: str) -> None:
        if dsn not in index:
            index[dsn] = {'read_by': [], 'written_by': [], 'programs': []}
        entry = index[dsn]
        if access == 'read' and step not in entry['read_by']:
            entry['read_by'].append(step)
        elif access == 'write' and step not in entry['written_by']:
            entry['written_by'].append(step)
        if pgm and pgm not in entry['programs']:
            entry['programs'].append(pgm)

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _split_simple(s: str, sep: str) -> list[str]:
        """Simple split without quote/paren awareness. For inner parsing."""
        return s.split(sep)


# ---------------------------------------------------------------------------
# Convenience function (called from other modules)
# ---------------------------------------------------------------------------

def build_jcl_report(jcl_path: Path | str, output_dir: Path | str = 'out/report',
                     verbose: bool = False) -> Path:
    """Parse a JCL file and write all three JSON artifacts. Returns output dir."""
    jcl_path = Path(jcl_path)
    parser = JCLParser(jcl_path, verbose=verbose)
    parsed = parser.parse()

    job_name = parsed.get('job_name') or jcl_path.stem
    out_dir = Path(output_dir) / f'{job_name}.jcl.report'

    if verbose:
        print(f'[JCL] Parsing {jcl_path.name} → {out_dir}')

    parser._build_outputs(parsed, out_dir)

    if verbose:
        print(f'[JCL] Complete: 3 files written')

    return out_dir


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(
        description='Parse an IBM JCL file and write structured JSON artifacts.')
    ap.add_argument('jcl_file', help='Path to the JCL file to parse')
    ap.add_argument('--output-dir', default='out/report',
                    help='Root output directory (default: out/report)')
    ap.add_argument('--verbose', action='store_true',
                    help='Print progress messages')
    args = ap.parse_args()

    jcl_path = Path(args.jcl_file)
    if not jcl_path.exists():
        print(f'Error: file not found: {jcl_path}')
        raise SystemExit(1)

    # Basic validation: first non-empty non-comment line must start with //
    try:
        lines = JCLParser(jcl_path)._read_lines()
    except Exception as e:
        print(f'Error reading file: {e}')
        raise SystemExit(1)

    first_jcl = next((l for l in lines if l.strip() and not l.strip().startswith('//*')), '')
    if not first_jcl.startswith('//'):
        print(f'Error: {jcl_path.name} does not appear to be a valid JCL file '
              f'(first non-comment line does not start with //)')
        raise SystemExit(1)

    out_dir = build_jcl_report(jcl_path, args.output_dir, verbose=args.verbose)
    print(f'Output written to: {out_dir}')


if __name__ == '__main__':
    main()
