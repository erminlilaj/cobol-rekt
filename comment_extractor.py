#!/usr/bin/env python3
"""
COBOL Comment Extractor

Extracts comments (lines with * in column 7) from COBOL source files
and maps them to their associated paragraphs/sections.

Output format:
{
    "_PROGRAM_SUMMARY": ["Program description from before PROCEDURE DIVISION"],
    "PARAGRAPH-NAME": ["Comment line 1", "Comment line 2"],
    "ANOTHER-PARA": ["Its comment"]
}
"""

import json
import re
from pathlib import Path
from typing import Optional


def is_noise_line(text: str) -> bool:
    """
    Check if comment is visual noise (separator lines, empty, decorations).
    
    Filters: 
    - Empty comments
    - Lines of only dashes, equals, asterisks, underscores, slashes
    - EJECT/SKIP compiler directives
    """
    stripped = text.strip()
    
    # Empty
    if not stripped:
        return True
    
    # Compiler directives
    upper = stripped.upper()
    if upper.startswith(('EJECT', 'SKIP', 'SKIP1', 'SKIP2', 'SKIP3')):
        return True
    
    # Pure separator line: only consists of repeating decoration chars
    # Matches: -------, ======, ******, _______, //////, or combinations
    if re.match(r'^[-=*_/\s]+$', stripped):
        return True
    
    # Trailing decoration asterisks (common pattern: "TEXT HERE   *")
    # Keep the text, just note this pattern exists
    
    return False


def extract_comments(source_file: Path, verbose: bool = False) -> dict[str, list[str]]:
    """
    Extract comments from a COBOL source file.
    
    Comments are lines with * in column 7 (0-indexed position 6).
    Associates comments with the next paragraph/section definition.
    
    Special key _PROGRAM_SUMMARY: Comments before PROCEDURE DIVISION.
    
    Args:
        source_file: Path to the COBOL source file
        verbose: Print progress messages
        
    Returns:
        Dictionary mapping paragraph names (uppercase) to their comments
    """
    try:
        content = source_file.read_text(encoding='utf-8', errors='replace')
    except Exception as e:
        if verbose:
            print(f"[WARN] Could not read {source_file}: {e}")
        return {}
    
    lines = content.split('\n')
    
    # Pattern to match paragraph/section definitions in Area A
    para_pattern = re.compile(
        r'^.{6}\s([A-Z0-9][A-Z0-9_-]+)(?:\s+SECTION)?\.?\s*$',
        re.IGNORECASE
    )
    
    # Pattern to detect PROCEDURE DIVISION
    proc_div_pattern = re.compile(r'PROCEDURE\s+DIVISION', re.IGNORECASE)
    
    result = {}
    pending_comments = []
    in_procedure_division = False
    
    # Reserved words to skip (these are not paragraph names)
    reserved = {
        'PROCEDURE', 'WORKING-STORAGE', 'DATA', 'IDENTIFICATION',
        'ENVIRONMENT', 'FILE', 'LINKAGE', 'CONFIGURATION',
        'INPUT-OUTPUT', 'FILE-CONTROL', 'DIVISION', 'SECTION',
        'FD', 'SD', '01', '77', 'COPY', 'REPLACE', 'EXEC',
        'PROGRAM-ID', 'AUTHOR', 'DATE-WRITTEN', 'DATE-COMPILED'
    }
    
    for i, line in enumerate(lines):
        # Skip short lines
        if len(line) < 7:
            continue
        
        indicator = line[6] if len(line) > 6 else ' '
        
        # Check if this is a comment line (*  in column 7)
        if indicator == '*':
            comment_text = line[7:].strip() if len(line) > 7 else ""
            
            # Filter noise
            if not is_noise_line(comment_text):
                # Clean trailing asterisks used as decoration
                clean_text = re.sub(r'\s*\*+\s*$', '', comment_text).strip()
                if clean_text:
                    pending_comments.append(clean_text)
            continue
        
        # Skip continuation lines and debug lines
        if indicator in ('-', '/', 'D', 'd'):
            continue
        
        # Check for PROCEDURE DIVISION
        if proc_div_pattern.search(line):
            # Assign pending comments to program summary
            if pending_comments:
                result['_PROGRAM_SUMMARY'] = pending_comments.copy()
                if verbose:
                    print(f"  _PROGRAM_SUMMARY: {len(pending_comments)} comment(s)")
                pending_comments = []
            in_procedure_division = True
            continue
        
        # Try to match paragraph/section definition
        match = para_pattern.match(line)
        if match:
            para_name = match.group(1).upper()
            
            # Skip reserved words
            if para_name in reserved:
                pending_comments = []
                continue
            
            # Skip if it looks like a data definition (starts with number)
            if para_name[0].isdigit():
                continue
            
            # Associate pending comments with this paragraph
            if pending_comments:
                result[para_name] = pending_comments.copy()
                if verbose:
                    print(f"  {para_name}: {len(pending_comments)} comment(s)")
                pending_comments = []
        
        # If we hit non-blank code line, clear pending
        elif line[7:].strip() and indicator == ' ':
            code_area = line[7:72] if len(line) > 7 else ""
            if code_area.strip() and not code_area.strip().startswith('*'):
                pending_comments = []
    
    if verbose:
        total = len(result)
        has_summary = '_PROGRAM_SUMMARY' in result
        print(f"[Comment Extractor] Found comments for {total} items" + 
              (" (includes program summary)" if has_summary else ""))
    
    return result


def extract_comments_to_json(source_file: Path, output_file: Optional[Path] = None,
                             verbose: bool = False) -> Path:
    """
    Extract comments and save to JSON file.
    
    Args:
        source_file: Path to COBOL source
        output_file: Output JSON path (defaults to <source>.comments.json)
        verbose: Print progress
        
    Returns:
        Path to the output JSON file
    """
    comments = extract_comments(source_file, verbose)
    
    if output_file is None:
        output_file = source_file.parent / f"{source_file.stem}.comments.json"
    
    output_file.write_text(
        json.dumps(comments, indent=2, ensure_ascii=False),
        encoding='utf-8'
    )
    
    if verbose:
        print(f"[Comment Extractor] Saved to {output_file}")
    
    return output_file


# CLI interface
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python comment_extractor.py <cobol_source> [output.json]")
        print("Example: python comment_extractor.py PROGRAM.cbl")
        sys.exit(1)
    
    source = Path(sys.argv[1])
    output = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    
    if not source.exists():
        print(f"Error: File not found: {source}")
        sys.exit(1)
    
    result_path = extract_comments_to_json(source, output, verbose=True)
    
    # Also print to stdout
    comments = extract_comments(source)
    print("\n" + json.dumps(comments, indent=2))
