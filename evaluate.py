#!/usr/bin/env python3
"""
COBOL Syntax Evaluator - Diagnoses parsing issues without exposing code details.
Usage: python evaluate.py <filename.cbl> [--copybooks <dir>] [--verbose]
"""
import os
import subprocess
import sys
import json
import re
from pathlib import Path
from collections import defaultdict

class Colors:
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN = '\033[96m'
    RESET = '\033[0m'
    BOLD = '\033[1m'
    
    @staticmethod
    def print_msg(msg, color=None):
        if color:
            print(f"{color}{msg}{Colors.RESET}")
        else:
            print(msg)

def parse_error_output(stderr_output):
    """Parse smojol-cli error output and extract diagnostic info."""
    errors = []
    
    # Pattern for SyntaxError lines
    syntax_pattern = r'SyntaxError\(.*?suggestion=([^,]+),.*?severity=(\w+)'
    
    # Pattern for JSON error blocks
    json_pattern = r'\[\s*\{[^]]+\}\s*\]'
    
    # Try to extract JSON error blocks
    json_matches = re.findall(json_pattern, stderr_output, re.DOTALL)
    for json_str in json_matches:
        try:
            error_list = json.loads(json_str)
            for err in error_list:
                location = err.get('location', {}).get('location', {})
                range_info = location.get('range', {})
                start = range_info.get('start', {})
                end = range_info.get('end', {})
                
                errors.append({
                    'source': err.get('source', 'Unknown'),
                    'severity': err.get('severity', 'ERROR'),
                    'suggestion': err.get('suggestion', 'No suggestion'),
                    'line': start.get('line', '?'),
                    'start_char': start.get('character', '?'),
                    'end_char': end.get('character', '?'),
                    'file': Path(location.get('uri', '')).name,
                    'copybook_id': err.get('location', {}).get('copybookId', None)
                })
        except json.JSONDecodeError:
            pass
    
    # Also try line-by-line patterns
    for match in re.finditer(syntax_pattern, stderr_output):
        suggestion, severity = match.groups()
        if not any(e['suggestion'] == suggestion for e in errors):
            errors.append({
                'source': 'Parser',
                'severity': severity,
                'suggestion': suggestion,
                'line': '?',
                'start_char': '?',
                'end_char': '?',
                'file': '?',
                'copybook_id': None
            })
    
    # Extract EXEC block info from raw output
    exec_patterns = extract_exec_context(stderr_output)
    
    return errors, exec_patterns

def extract_exec_context(stderr_output):
    """Extract information about EXEC blocks from the raw output."""
    exec_info = []
    
    # Look for replaced dialect text (shows EXEC blocks)
    dialect_pattern = r'Replaced dialect text number \[(\d+)\] : (EXEC \w+ [^\n]+)'
    for match in re.finditer(dialect_pattern, stderr_output):
        num, text = match.groups()
        # Extract first line of EXEC block
        first_line = text.split('\n')[0].strip()
        exec_info.append({
            'number': num,
            'type': 'CICS' if 'CICS' in text else 'SQL' if 'SQL' in text else 'OTHER',
            'preview': first_line[:60] + '...' if len(first_line) > 60 else first_line
        })
    
    return exec_info

def categorize_errors(errors):
    """Group errors by category for clearer reporting."""
    categories = defaultdict(list)
    
    for err in errors:
        suggestion = err['suggestion'].lower()
        
        if 'copybook not found' in suggestion or 'missing copybook' in suggestion:
            categories['Missing Copybooks'].append(err)
        elif 'extraneous input' in suggestion:
            categories['Syntax Errors (Unexpected Token)'].append(err)
        elif 'period was assumed' in suggestion:
            categories['Missing Period/Statement Boundary'].append(err)
        elif 'errors inside the copybook' in suggestion:
            categories['Copybook Internal Errors'].append(err)
        elif 'invalid token' in suggestion:
            categories['Invalid Token'].append(err)
        else:
            categories['Other Errors'].append(err)
    
    return categories

def extract_copybook_name(suggestion):
    """Extract copybook name from error message without showing code."""
    match = re.search(r'(\w+):\s*Copybook not found', suggestion, re.IGNORECASE)
    if match:
        return match.group(1)
    return None

def run_evaluation(target_file, copybooks_dir, verbose=False):
    """Run smojol-cli and capture diagnostic output."""
    current_dir = Path.cwd()
    smojol_cli = current_dir / "smojol-cli" / "target" / "smojol-cli.jar"
    dialect_jar = current_dir / "che-che4z-lsp-for-cobol-integration" / "server" / "dialect-idms" / "target" / "dialect-idms.jar"
    
    if not smojol_cli.exists():
        Colors.print_msg(f"Error: smojol-cli.jar not found at {smojol_cli}", Colors.RED)
        sys.exit(1)
    
    target_path = Path(target_file).resolve()
    if not target_path.exists():
        Colors.print_msg(f"Error: File not found: {target_path}", Colors.RED)
        sys.exit(1)
    
    src_dir = target_path.parent
    if not copybooks_dir:
        copybooks_dir = src_dir
    
    # Run with minimal commands just to trigger parsing
    cmd = [
        "java", "-jar", str(smojol_cli),
        "run", target_path.name,
        "--commands=WRITE_RAW_AST",
        f"--srcDir={src_dir}",
        f"--copyBooksDir={copybooks_dir}",
        f"--dialectJarPath={dialect_jar}",
        "--dialect=COBOL",
        "--reportDir=out/evaluate_temp",
        "--generation=PROGRAM"
    ]
    
    if verbose:
        Colors.print_msg(f"Running: {' '.join(cmd)}", Colors.CYAN)
    
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=current_dir
    )
    
    return result.returncode, result.stdout, result.stderr

def generate_report(errors, exec_context, target_file, verbose=False):
    """Generate a privacy-safe diagnostic report."""
    Colors.print_msg("\n" + "=" * 60, Colors.BLUE)
    Colors.print_msg(f"  COBOL SYNTAX EVALUATION REPORT", Colors.BOLD)
    Colors.print_msg(f"  File: {Path(target_file).name}", Colors.CYAN)
    Colors.print_msg("=" * 60, Colors.BLUE)
    
    if not errors:
        Colors.print_msg("\n✅ No parsing errors detected!", Colors.GREEN)
        Colors.print_msg("   The file parsed successfully.\n", Colors.GREEN)
        return 0
    
    categories = categorize_errors(errors)
    
    Colors.print_msg(f"\n❌ Found {len(errors)} issue(s):\n", Colors.RED)
    
    # Summary
    Colors.print_msg("SUMMARY BY CATEGORY:", Colors.YELLOW)
    Colors.print_msg("-" * 40)
    for cat, cat_errors in categories.items():
        Colors.print_msg(f"  • {cat}: {len(cat_errors)}", Colors.YELLOW)
    
    # Details
    Colors.print_msg("\n" + "-" * 60, Colors.BLUE)
    Colors.print_msg("DETAILED DIAGNOSTICS:", Colors.CYAN)
    Colors.print_msg("-" * 60, Colors.BLUE)
    
    for cat, cat_errors in categories.items():
        Colors.print_msg(f"\n[{cat}]", Colors.MAGENTA)
        
        if cat == 'Missing Copybooks':
            copybooks = set()
            for err in cat_errors:
                cb = extract_copybook_name(err['suggestion'])
                if cb:
                    copybooks.add(cb)
            Colors.print_msg(f"  Missing: {', '.join(sorted(copybooks))}", Colors.YELLOW)
            Colors.print_msg("  → Create stub copybooks or provide correct --copybooks path", Colors.GREEN)
        
        elif cat == 'Syntax Errors (Unexpected Token)':
            for err in cat_errors:
                line = err.get('line', '?')
                start_char = err.get('start_char', '?')
                end_char = err.get('end_char', '?')
                file_name = err.get('file', '?')
                copybook_id = err.get('copybook_id')
                suggestion = err['suggestion']
                
                # Extract just the token type, not the actual code
                token_match = re.search(r"input '([^']+)'", suggestion)
                token = token_match.group(1) if token_match else 'unknown'
                
                Colors.print_msg(f"\n  ┌─ ERROR at Line {line}, Columns {start_char}-{end_char}", Colors.YELLOW)
                Colors.print_msg(f"  │  File: {file_name}", Colors.YELLOW)
                if copybook_id:
                    Colors.print_msg(f"  │  Inside copybook: {copybook_id}", Colors.YELLOW)
                Colors.print_msg(f"  │  Unexpected token: '{token}'", Colors.YELLOW)
                Colors.print_msg(f"  └─ Span length: {end_char - start_char if isinstance(start_char, int) and isinstance(end_char, int) else '?'} characters", Colors.YELLOW)
                
                # Provide specific guidance based on token
                if token == '(':
                    Colors.print_msg(f"    DIAGNOSIS: Parenthesis appeared where parser didn't expect it", Colors.CYAN)
                    Colors.print_msg(f"    LOCATION HINT: Check what keyword is at column {start_char - 10 if isinstance(start_char, int) else '?'}-{start_char}", Colors.CYAN)
                    Colors.print_msg(f"    COMMON CAUSES:", Colors.GREEN)
                    Colors.print_msg(f"      1. Space before '(' in CICS/SQL command", Colors.GREEN)
                    Colors.print_msg(f"         BAD:  EXEC CICS SEND FROM (VAR)", Colors.RED)
                    Colors.print_msg(f"         GOOD: EXEC CICS SEND FROM(VAR)", Colors.GREEN)
                    Colors.print_msg(f"      2. Missing LENGTH clause in CICS SEND", Colors.GREEN)
                    Colors.print_msg(f"         BAD:  EXEC CICS SEND FROM(VAR) END-EXEC", Colors.RED)
                    Colors.print_msg(f"         GOOD: EXEC CICS SEND FROM(VAR) LENGTH(LEN) END-EXEC", Colors.GREEN)
                    Colors.print_msg(f"      3. Preprocessor macro not expanded", Colors.GREEN)
                    Colors.print_msg(f"      4. Reference modification issue: VAR(1:5)", Colors.GREEN)
                elif token in ('WHEN', 'ELSE', 'END-IF', 'END-EVALUATE', 'END-PERFORM'):
                    Colors.print_msg(f"    DIAGNOSIS: Control structure keyword found outside its block", Colors.CYAN)
                    Colors.print_msg(f"    ROOT CAUSE: An earlier error broke the parser's understanding", Colors.GREEN)
                    Colors.print_msg(f"    FIX: Scroll UP and fix the FIRST error - this one will disappear", Colors.GREEN)
                elif token == 'CONDITION':
                    Colors.print_msg(f"    DIAGNOSIS: 'CONDITION' is a reserved word in CICS", Colors.CYAN)
                    Colors.print_msg(f"    CAUSE: Used as variable name OR in unsupported HANDLE CONDITION", Colors.GREEN)
                    Colors.print_msg(f"    FIX: Rename the variable OR check CICS HANDLE syntax", Colors.GREEN)
                elif token in ('EXEC', 'END-EXEC'):
                    Colors.print_msg(f"    DIAGNOSIS: Embedded SQL/CICS block boundary issue", Colors.CYAN)
                    Colors.print_msg(f"    CAUSE: Nested EXEC blocks or unclosed previous EXEC", Colors.GREEN)
                    Colors.print_msg(f"    FIX: Ensure each EXEC has exactly one matching END-EXEC", Colors.GREEN)
                else:
                    Colors.print_msg(f"    DIAGNOSIS: Token '{token}' not expected in this context", Colors.CYAN)
                    Colors.print_msg(f"    POSSIBLE CAUSES:", Colors.GREEN)
                    Colors.print_msg(f"      • Vendor-specific extension not in standard grammar", Colors.GREEN)
                    Colors.print_msg(f"      • Typo or missing punctuation on previous line", Colors.GREEN)
                    Colors.print_msg(f"      • Preprocessor macro that wasn't expanded", Colors.GREEN)
            
            Colors.print_msg("\n  GENERAL SYNTAX ERROR TIPS:", Colors.MAGENTA)
            Colors.print_msg("  • Fix errors from TOP to BOTTOM (first error causes cascade)", Colors.GREEN)
            Colors.print_msg("  • Check column alignment (code must be in columns 8-72)", Colors.GREEN)
            Colors.print_msg("  • Ensure all statements end with periods where required", Colors.GREEN)
        
        elif cat == 'Missing Period/Statement Boundary':
            lines = [str(err.get('line', '?')) for err in cat_errors]
            Colors.print_msg(f"  Lines: {', '.join(lines[:5])}{'...' if len(lines) > 5 else ''}", Colors.YELLOW)
            Colors.print_msg("  → Earlier syntax error caused cascade; fix root cause first", Colors.GREEN)
        
        elif cat == 'Copybook Internal Errors':
            files = set(err.get('file', '?') for err in cat_errors)
            Colors.print_msg(f"  Affected copybooks: {', '.join(files)}", Colors.YELLOW)
            Colors.print_msg("  → Fix errors in the copybook files first", Colors.GREEN)
        
        else:
            for err in cat_errors[:3]:  # Show first 3
                Colors.print_msg(f"  Line {err.get('line', '?')}: {err['suggestion'][:60]}...", Colors.YELLOW)
            if len(cat_errors) > 3:
                Colors.print_msg(f"  ... and {len(cat_errors) - 3} more", Colors.YELLOW)
    
    # Recommendations
    Colors.print_msg("\n" + "-" * 60, Colors.BLUE)
    Colors.print_msg("RECOMMENDED ACTIONS:", Colors.GREEN)
    Colors.print_msg("-" * 60, Colors.BLUE)
    
    if 'Missing Copybooks' in categories:
        Colors.print_msg("1. Provide missing copybooks or use --ignore-copybooks flag", Colors.GREEN)
    
    if 'Syntax Errors (Unexpected Token)' in categories:
        Colors.print_msg("2. Check for dialect-specific syntax (CICS/SQL/IDMS)", Colors.GREEN)
        Colors.print_msg("   • CICS: Ensure no spaces before '(' in commands", Colors.GREEN)
        Colors.print_msg("   • SQL: Ensure EXEC SQL blocks are complete", Colors.GREEN)
    
    if 'Missing Period/Statement Boundary' in categories:
        Colors.print_msg("3. Fix the FIRST error - later errors are often cascading", Colors.GREEN)
    
    # Show EXEC context if available
    if exec_context:
        Colors.print_msg("\n" + "-" * 60, Colors.BLUE)
        Colors.print_msg("DETECTED EXEC BLOCKS (for context):", Colors.CYAN)
        Colors.print_msg("-" * 60, Colors.BLUE)
        cics_count = sum(1 for e in exec_context if e['type'] == 'CICS')
        sql_count = sum(1 for e in exec_context if e['type'] == 'SQL')
        Colors.print_msg(f"  Total EXEC blocks found: {len(exec_context)}", Colors.YELLOW)
        Colors.print_msg(f"    • CICS blocks: {cics_count}", Colors.YELLOW)
        Colors.print_msg(f"    • SQL blocks: {sql_count}", Colors.YELLOW)
        if verbose:
            for ex in exec_context[:5]:
                Colors.print_msg(f"    [{ex['number']}] {ex['type']}: {ex['preview']}", Colors.CYAN)
    
    Colors.print_msg("\n" + "=" * 60 + "\n", Colors.BLUE)
    
    return len(errors)

def main():
    os.system('')  # Enable ANSI on Windows
    
    if len(sys.argv) < 2:
        print("Usage: python evaluate.py <filename.cbl> [--copybooks <dir>] [--verbose]")
        sys.exit(1)
    
    target_file = sys.argv[1]
    copybooks_dir = None
    verbose = "--verbose" in sys.argv or "-v" in sys.argv
    
    # Parse --copybooks argument
    for i, arg in enumerate(sys.argv):
        if arg == "--copybooks" and i + 1 < len(sys.argv):
            copybooks_dir = sys.argv[i + 1]
    
    Colors.print_msg("\n🔍 Evaluating COBOL syntax...\n", Colors.CYAN)
    
    returncode, stdout, stderr = run_evaluation(target_file, copybooks_dir, verbose)
    
    if verbose:
        Colors.print_msg("\n--- Raw Output ---", Colors.CYAN)
        print(stderr[:2000] if len(stderr) > 2000 else stderr)
        Colors.print_msg("--- End Raw Output ---\n", Colors.CYAN)
    
    errors, exec_context = parse_error_output(stderr)
    error_count = generate_report(errors, exec_context, target_file, verbose)
    
    # Cleanup temp directory
    import shutil
    temp_dir = Path("out/evaluate_temp")
    if temp_dir.exists():
        shutil.rmtree(temp_dir, ignore_errors=True)
    
    sys.exit(0 if error_count == 0 else 1)

if __name__ == "__main__":
    main()
