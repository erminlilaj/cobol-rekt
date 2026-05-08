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

def scan_source_for_copybooks(file_path):
    """
    Scans the source file to find all COPY statements.
    Returns a set of expected copybook names.
    """
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
            
        # Regex for COPY NAME. or COPY 'NAME'. or COPY "NAME".
        # Also handles COPY NAME OF LIBRARY.
        pattern = re.compile(
            r'COPY\s+[\'"]?([A-Za-z0-9_-]+)[\'"]?(?:\s+(?:OF|IN)\s+[A-Za-z0-9_-]+)?',
            re.IGNORECASE
        )
        return set(pattern.findall(content))
    except Exception:
        return set()

def analyze_copybook_health(target_file, copybooks_dir, parser_errors):
    """
    Analyzes the status of all referenced copybooks.
    Classifies them as: OK, Broken, Missing, or Stub/Empty.
    """
    if not copybooks_dir or not Path(copybooks_dir).exists():
        return None

    # 1. Identify what SHOULD be there
    expected_copybooks = scan_source_for_copybooks(target_file)
    
    # 2. Identify what failed in parsing
    broken_copybooks = set()
    missing_copybooks = set()
    
    # Extract broken/missing names from error logs
    for err in parser_errors:
        suggestion = err.get('suggestion', '').lower()
        # Direct broken reference
        if 'errors inside the copybook' in suggestion:
            # Try to get ID from location if available
            cb_id = err.get('copybook_id')
            if cb_id:
                broken_copybooks.add(cb_id)
            # Or from filename in location
            elif err.get('file') and err.get('file') != Path(target_file).name:
                broken_copybooks.add(err.get('file').split('.')[0])
                
        # Direct missing reference
        if 'copybook not found' in suggestion:
            cb_id = extract_copybook_name(err['suggestion'])
            if cb_id:
                missing_copybooks.add(cb_id)

    # 3. Check physical files
    stats = {
        'ok': [],
        'broken': [],
        'missing': [],
        'stub': []
    }

    # Helper to find file case-insensitively
    def find_file(name, directory):
        p = Path(directory)
        for ext in ['', '.cpy', '.cbl', '.CPY', '.CBL']:
            target = p / f"{name}{ext}"
            if target.exists(): return target
            # Try lowercase match
            target_lower = p / f"{name.lower()}{ext}"
            if target_lower.exists(): return target_lower
        return None

    for cb_name in expected_copybooks:
        file_path = find_file(cb_name, copybooks_dir)
        
        # CATEGORY: MISSING
        if not file_path:
            stats['missing'].append(cb_name)
            continue
            
        # CATEGORY: STUB / EMPTY
        try:
            size = file_path.stat().st_size
            content = file_path.read_text(errors='ignore')
            # Check for empty or specific "STUB" marker from our sandbox tool
            if size < 50 or "STUB COPYBOOK" in content:
                stats['stub'].append(cb_name)
                continue
        except:
            pass # Treat as existing if we can't read it
            
        # CATEGORY: BROKEN (Found in parser errors)
        # Check if this name appears in our broken list (fuzzy match)
        is_broken = False
        for broken in broken_copybooks:
            if cb_name.upper() == broken.upper() or cb_name.upper() in broken.upper():
                stats['broken'].append(cb_name)
                is_broken = True
                break
        
        if is_broken:
            continue
            
        # CATEGORY: OK
        # If it exists, isn't empty, and didn't crash the parser -> It's OK
        stats['ok'].append(cb_name)
        
    return stats

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

def generate_report(errors, exec_context, target_file, copybook_stats, verbose=False):
    """Generate a privacy-safe diagnostic report."""
    Colors.print_msg("\n" + "=" * 60, Colors.BLUE)
    Colors.print_msg(f"  COBOL SYNTAX EVALUATION REPORT", Colors.BOLD)
    Colors.print_msg(f"  File: {Path(target_file).name}", Colors.CYAN)
    Colors.print_msg("=" * 60, Colors.BLUE)
    
    # 1. COPYBOOK HEALTH SECTION
    if copybook_stats:
        Colors.print_msg("\n" + "-" * 60, Colors.BLUE)
        Colors.print_msg("COPYBOOK HEALTH CHECK:", Colors.CYAN)
        Colors.print_msg("-" * 60, Colors.BLUE)
        
        n_ok = len(copybook_stats['ok'])
        n_stub = len(copybook_stats['stub'])
        n_broken = len(copybook_stats['broken'])
        n_missing = len(copybook_stats['missing'])
        total = n_ok + n_stub + n_broken + n_missing
        
        Colors.print_msg(f"  Total Referenced: {total}", Colors.BOLD)
        
        # Progress Bar Visual
        if total > 0:
            bar_len = 40
            ok_chars = int((n_ok / total) * bar_len)
            stub_chars = int((n_stub / total) * bar_len)
            broken_chars = int((n_broken / total) * bar_len)
            missing_chars = bar_len - (ok_chars + stub_chars + broken_chars)
            
            bar = (f"{Colors.GREEN}{'█' * ok_chars}"
                   f"{Colors.YELLOW}{'▒' * stub_chars}"
                   f"{Colors.RED}{'▓' * broken_chars}"
                   f"{Colors.RED}{'░' * missing_chars}{Colors.RESET}")
            print(f"  [{bar}]")
        
        print("")
        Colors.print_msg(f"  ✅ OK (Healthy):      {n_ok}", Colors.GREEN)
        Colors.print_msg(f"  ⚠️  STUBBED (Empty):   {n_stub}", Colors.YELLOW)
        Colors.print_msg(f"  ❌ BROKEN (Errors):   {n_broken}", Colors.RED)
        Colors.print_msg(f"  🚫 MISSING:           {n_missing}", Colors.RED)
        
        if n_broken > 0:
            Colors.print_msg(f"\n  Broken files: {', '.join(copybook_stats['broken'][:5])}" + ("..." if n_broken > 5 else ""), Colors.RED)
        if n_missing > 0:
            Colors.print_msg(f"  Missing files: {', '.join(copybook_stats['missing'][:5])}" + ("..." if n_missing > 5 else ""), Colors.RED)

    # 2. SYNTAX ERROR SECTION
    if not errors:
        Colors.print_msg("\n✅ No parsing errors detected in main program!", Colors.GREEN)
        return 0
    
    categories = categorize_errors(errors)
    
    Colors.print_msg(f"\n❌ Found {len(errors)} parsing issue(s):\n", Colors.RED)
    
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
                
                # Provide specific guidance based on token
                if token == '(':
                    Colors.print_msg(f"    DIAGNOSIS: Parenthesis appeared where parser didn't expect it", Colors.CYAN)
                    Colors.print_msg(f"    FIX: Check for space before '(' in CICS/SQL commands", Colors.GREEN)
                elif token in ('EXEC', 'END-EXEC'):
                    Colors.print_msg(f"    DIAGNOSIS: Embedded SQL/CICS block boundary issue", Colors.CYAN)
                    Colors.print_msg(f"    FIX: Ensure each EXEC has exactly one matching END-EXEC", Colors.GREEN)
        
        elif cat == 'Missing Period/Statement Boundary':
            lines = [str(err.get('line', '?')) for err in cat_errors]
            Colors.print_msg(f"  Lines: {', '.join(lines[:5])}{'...' if len(lines) > 5 else ''}", Colors.YELLOW)
            Colors.print_msg("  → Earlier syntax error caused cascade; fix root cause first", Colors.GREEN)
        
        elif cat == 'Copybook Internal Errors':
            files = set(err.get('file', '?') for err in cat_errors)
            Colors.print_msg(f"  Affected copybooks: {', '.join(files)}", Colors.YELLOW)
            Colors.print_msg("  → See 'Copybook Health Check' above for details", Colors.GREEN)
        
        else:
            for err in cat_errors[:3]:  # Show first 3
                Colors.print_msg(f"  Line {err.get('line', '?')}: {err['suggestion'][:60]}...", Colors.YELLOW)
    
    # Recommendations
    Colors.print_msg("\n" + "-" * 60, Colors.BLUE)
    Colors.print_msg("RECOMMENDED ACTIONS:", Colors.GREEN)
    Colors.print_msg("-" * 60, Colors.BLUE)
    
    if copybook_stats and len(copybook_stats['missing']) > 0:
        Colors.print_msg("1. Run with --auto-stub to create placeholders for missing files", Colors.GREEN)
    
    if copybook_stats and len(copybook_stats['broken']) > 0:
        Colors.print_msg("2. Run the preprocessor to fix CICS syntax in broken copybooks", Colors.GREEN)
    
    if 'Syntax Errors (Unexpected Token)' in categories:
         Colors.print_msg("3. Check for correct dialect (IDMS vs COBOL) configuration", Colors.GREEN)

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
    
    # If not provided, assume same dir as source
    if not copybooks_dir:
        copybooks_dir = str(Path(target_file).parent)

    Colors.print_msg("\n🔍 Evaluating COBOL syntax...\n", Colors.CYAN)
    
    returncode, stdout, stderr = run_evaluation(target_file, copybooks_dir, verbose)
    
    if verbose:
        Colors.print_msg("\n--- Raw Output ---", Colors.CYAN)
        print(stderr[:2000] if len(stderr) > 2000 else stderr)
        Colors.print_msg("--- End Raw Output ---\n", Colors.CYAN)
    
    errors, exec_context = parse_error_output(stderr)
    
    # Run Copybook Health Check
    copybook_stats = analyze_copybook_health(target_file, copybooks_dir, errors)
    
    error_count = generate_report(errors, exec_context, target_file, copybook_stats, verbose)
    
    # Cleanup temp directory
    import shutil
    temp_dir = Path("out/evaluate_temp")
    if temp_dir.exists():
        shutil.rmtree(temp_dir, ignore_errors=True)
    
    sys.exit(0 if error_count == 0 else 1)

if __name__ == "__main__":
    main()