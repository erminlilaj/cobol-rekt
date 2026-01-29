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
                errors.append({
                    'source': err.get('source', 'Unknown'),
                    'severity': err.get('severity', 'ERROR'),
                    'suggestion': err.get('suggestion', 'No suggestion'),
                    'line': err.get('location', {}).get('location', {}).get('range', {}).get('start', {}).get('line', '?'),
                    'file': Path(err.get('location', {}).get('location', {}).get('uri', '')).name
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
                'file': '?'
            })
    
    return errors

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

def generate_report(errors, target_file, verbose=False):
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
                # Extract just the token type, not the actual code
                token_match = re.search(r"input '([^']+)'", err['suggestion'])
                token = token_match.group(1) if token_match else 'unknown'
                Colors.print_msg(f"  Line {line}: Unexpected '{token}'", Colors.YELLOW)
            Colors.print_msg("  → Check for vendor-specific syntax or macros", Colors.GREEN)
            Colors.print_msg("  → Common causes: spaces before '(', dialect-specific keywords", Colors.GREEN)
        
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
    
    errors = parse_error_output(stderr)
    error_count = generate_report(errors, target_file, verbose)
    
    # Cleanup temp directory
    import shutil
    temp_dir = Path("out/evaluate_temp")
    if temp_dir.exists():
        shutil.rmtree(temp_dir, ignore_errors=True)
    
    sys.exit(0 if error_count == 0 else 1)

if __name__ == "__main__":
    main()
