#!/usr/bin/env python3
"""
COBOL Syntax Preprocessor - Normalizes vendor-specific syntax variations 
to be compatible with the Che COBOL Language Support parser.

This module handles common syntax patterns that the standard parser doesn't accept,
such as spaces before parentheses in CICS/SQL commands.

Usage:
    from cobol_preprocessor import preprocess_file, preprocess_directory
    
    # Single file
    preprocess_file("source.cbl", "output.cbl")
    
    # Directory (in-place)
    preprocess_directory("/path/to/copybooks")
"""

import re
import os
import shutil
from pathlib import Path
from typing import List, Tuple, Optional

# Common CICS/SQL keywords that should NOT have space before '('
EXEC_KEYWORDS = [
    'FROM', 'INTO', 'LENGTH', 'FLENGTH', 'PROGRAM', 'COMMAREA', 
    'MAP', 'MAPSET', 'MAPONLY', 'CURSOR', 'RESP', 'RESP2',
    'QUEUE', 'QNAME', 'RESOURCE', 'RIDFLD', 'KEYLENGTH',
    'ABSTIME', 'TRANSID', 'TERMID', 'SYSID', 'CHANNEL',
    'CONTAINER', 'SET', 'DATASET', 'FILE', 'HANDLE', 'CONDITION',
    'AID', 'ERROR', 'ABCODE', 'INTERVAL', 'TIME', 'AFTER',
    'ITEM', 'NUMITEMS', 'REWRITE', 'NEXT', 'PREVIOUS',
    # SQL keywords
    'VALUES', 'WHERE', 'SELECT', 'UPDATE', 'DELETE', 'INSERT'
]

def normalize_exec_spaces(content: str) -> Tuple[str, List[dict]]:
    """
    Remove spaces between CICS/SQL keywords and opening parentheses.
    
    Returns:
        Tuple of (normalized_content, list_of_changes)
    """
    changes = []
    
    # Build pattern: KEYWORD <space(s)> (
    keywords_pattern = '|'.join(EXEC_KEYWORDS)
    pattern = rf'\b({keywords_pattern})\s+\('
    
    def replacement(match):
        keyword = match.group(1)
        original = match.group(0)
        fixed = f"{keyword}("
        changes.append({
            'type': 'SPACE_BEFORE_PAREN',
            'original': original.strip(),
            'fixed': fixed,
            'keyword': keyword
        })
        return fixed
    
    normalized = re.sub(pattern, replacement, content, flags=re.IGNORECASE)
    return normalized, changes

def normalize_cics_send(content: str) -> Tuple[str, List[dict]]:
    """
    Handle CICS SEND variations that may be missing TEXT/MAP keyword.
    Adds TEXT keyword when SEND FROM is used without a type specifier.
    """
    changes = []
    
    # Pattern: EXEC CICS SEND FROM(...) without TEXT/MAP/CONTROL/PAGE
    # We need to add TEXT before FROM
    # Match: EXEC CICS SEND <whitespace> FROM (but not if preceded by TEXT/MAP/etc)
    
    def fix_send(match):
        full_match = match.group(0)
        # Check if there's already TEXT, MAP, CONTROL, PAGE before FROM
        if re.search(r'\b(TEXT|MAP|CONTROL|PAGE|LAST|WAIT)\s+FROM', full_match, re.IGNORECASE):
            return full_match  # Already has type, don't change
        
        # Insert TEXT before FROM
        fixed = re.sub(r'(EXEC\s+CICS\s+SEND\s+)(FROM)', r'\1TEXT \2', full_match, flags=re.IGNORECASE)
        if fixed != full_match:
            changes.append({
                'type': 'ADDED_SEND_TEXT',
                'original': 'EXEC CICS SEND FROM',
                'fixed': 'EXEC CICS SEND TEXT FROM'
            })
        return fixed
    
    # Match EXEC CICS SEND ... FROM pattern
    pattern = r'EXEC\s+CICS\s+SEND\s+FROM\s*\('
    content = re.sub(pattern, fix_send, content, flags=re.IGNORECASE)
    
    return content, changes

def preprocess_content(content: str, verbose: bool = False) -> Tuple[str, List[dict]]:
    """
    Apply all preprocessing transformations to COBOL content.
    
    Returns:
        Tuple of (preprocessed_content, all_changes)
    """
    all_changes = []
    
    # 1. Normalize spaces before parentheses
    content, changes = normalize_exec_spaces(content)
    all_changes.extend(changes)
    
    # 2. Fix CICS SEND FROM by adding TEXT keyword
    content, send_changes = normalize_cics_send(content)
    all_changes.extend(send_changes)
    
    if verbose and all_changes:
        space_fixes = len([c for c in all_changes if c['type'] == 'SPACE_BEFORE_PAREN'])
        send_fixes = len([c for c in all_changes if c['type'] == 'ADDED_SEND_TEXT'])
        if space_fixes:
            print(f"  Applied {space_fixes} space normalizations")
        if send_fixes:
            print(f"  Added TEXT to {send_fixes} CICS SEND commands")
    
    return content, all_changes

def preprocess_file(input_path: str, output_path: Optional[str] = None, 
                    verbose: bool = False) -> List[dict]:
    """
    Preprocess a single COBOL file.
    
    Args:
        input_path: Path to input file
        output_path: Path to output file (if None, modifies in-place)
        verbose: Print changes
    
    Returns:
        List of changes made
    """
    input_path = Path(input_path)
    if output_path is None:
        output_path = input_path
    else:
        output_path = Path(output_path)
    
    try:
        with open(input_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
    except Exception as e:
        print(f"Error reading {input_path}: {e}")
        return []
    
    preprocessed, changes = preprocess_content(content, verbose)
    
    if changes:
        # Backup original if modifying in-place
        if output_path == input_path:
            backup = input_path.with_suffix(input_path.suffix + '.bak')
            if not backup.exists():
                shutil.copy(input_path, backup)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(preprocessed)
        
        if verbose:
            print(f"Preprocessed: {input_path.name} ({len(changes)} changes)")
    
    return changes

def preprocess_directory(directory: str, extensions: List[str] = None,
                         verbose: bool = False) -> dict:
    """
    Preprocess all COBOL files in a directory.
    
    Args:
        directory: Path to directory
        extensions: File extensions to process (default: .cbl, .cob, .cpy)
        verbose: Print progress
    
    Returns:
        Dictionary with stats
    """
    if extensions is None:
        extensions = ['.cbl', '.CBL', '.cob', '.COB', '.cpy', '.CPY', '']
    
    directory = Path(directory)
    stats = {
        'files_processed': 0,
        'files_changed': 0,
        'total_changes': 0,
        'changes_by_type': {}
    }
    
    for ext in extensions:
        pattern = f"*{ext}" if ext else "*"
        for file_path in directory.glob(pattern):
            if file_path.is_file():
                changes = preprocess_file(file_path, verbose=verbose)
                stats['files_processed'] += 1
                if changes:
                    stats['files_changed'] += 1
                    stats['total_changes'] += len(changes)
                    for change in changes:
                        ctype = change['type']
                        stats['changes_by_type'][ctype] = stats['changes_by_type'].get(ctype, 0) + 1
    
    return stats

def main():
    """Command-line interface."""
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python cobol_preprocessor.py <file_or_directory> [--verbose]")
        print("\nPreprocesses COBOL files to normalize syntax for parsing.")
        print("Creates .bak backup files before modifying.")
        sys.exit(1)
    
    target = sys.argv[1]
    verbose = '--verbose' in sys.argv or '-v' in sys.argv
    
    if os.path.isdir(target):
        print(f"Preprocessing directory: {target}")
        stats = preprocess_directory(target, verbose=verbose)
        print(f"\nSummary:")
        print(f"  Files processed: {stats['files_processed']}")
        print(f"  Files changed: {stats['files_changed']}")
        print(f"  Total changes: {stats['total_changes']}")
        if stats['changes_by_type']:
            print(f"  By type:")
            for ctype, count in stats['changes_by_type'].items():
                print(f"    - {ctype}: {count}")
    else:
        print(f"Preprocessing file: {target}")
        changes = preprocess_file(target, verbose=verbose)
        print(f"Applied {len(changes)} changes")
        if verbose:
            for c in changes:
                print(f"  {c}")

if __name__ == "__main__":
    main()
