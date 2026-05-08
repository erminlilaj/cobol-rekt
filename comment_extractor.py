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

Code-like comment blocks are written to a sibling commented_out_code.json
artifact by extract_comments_to_json(). They are intentionally excluded from
comments.json so inactive COBOL cannot be indexed as active paragraph logic.
"""

import json
import re
from pathlib import Path
from typing import Optional


_COBOL_COMMENT_CODE_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"^\s*(EXEC\s+(CICS|SQL|DLI|IMS)\b)",
        r"^\s*(MOVE|PERFORM|GO\s+TO|GOBACK|STOP\s+RUN|EXIT|IF|THEN|ELSE|END-IF|"
        r"EVALUATE|WHEN|READ|READNEXT|READPREV|WRITE|REWRITE|DELETE|START|STARTBR|"
        r"ENDBR|RESETBR|CALL|COPY|ADD|SUBTRACT|COMPUTE|INITIALIZE|SET)\b",
        r"^\s*[A-Z0-9][A-Z0-9_-]+\.\s*$",
        r"^\s*(INPUT|OUTPUT)\s*:\s*$",
        r"^\s*\d{2}\s+[A-Z0-9_-]+\b",
    )
)


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


def is_code_like_comment_line(text: str) -> bool:
    """Return True when a comment line looks like deactivated COBOL."""
    stripped = text.strip()
    if not stripped:
        return False
    return any(pattern.search(stripped) for pattern in _COBOL_COMMENT_CODE_PATTERNS)


def is_code_like_comment_block(lines: list[str]) -> bool:
    """Detect comment blocks that are more likely inactive code than prose."""
    non_empty = [line for line in lines if line.strip()]
    if not non_empty:
        return False
    code_like = [line for line in non_empty if is_code_like_comment_line(line)]
    has_exec = any(re.search(r"\bEXEC\s+(CICS|SQL|DLI|IMS)\b", line, re.IGNORECASE)
                   for line in non_empty)
    has_paragraph_label = any(re.match(r"^\s*[A-Z0-9][A-Z0-9_-]+\.\s*$", line, re.IGNORECASE)
                              for line in non_empty)
    if len(code_like) >= 3:
        return True
    if has_exec and len(code_like) >= 2:
        return True
    if has_exec and has_paragraph_label:
        return True
    return len(code_like) >= 2 and (len(code_like) / len(non_empty)) >= 0.5


def _comment_text(entry: dict) -> str:
    return str(entry.get("text", ""))


def _assign_pending_comments(
    target: str,
    pending_comments: list[dict],
    prose_comments: dict[str, list[str]],
    commented_out_code: dict[str, list[dict]],
) -> None:
    if not pending_comments:
        return
    lines = [_comment_text(entry) for entry in pending_comments]
    if is_code_like_comment_block(lines):
        commented_out_code.setdefault(target, []).append({
            "line_start": pending_comments[0]["line"],
            "line_end": pending_comments[-1]["line"],
            "line_count": len(lines),
            "reason": "code_like_comment_block",
            "active": False,
            "lines": lines,
        })
        return
    prose_comments[target] = lines


def extract_comments_with_inactive_code(
    source_file: Path,
    verbose: bool = False,
) -> tuple[dict[str, list[str]], dict[str, list[dict]]]:
    """
    Extract comments from a COBOL source file.
    
    Comments are lines with * in column 7 (0-indexed position 6).
    Associates comments with the next paragraph/section definition.
    
    Special key _PROGRAM_SUMMARY: Comments before PROCEDURE DIVISION.
    
    Args:
        source_file: Path to the COBOL source file
        verbose: Print progress messages
        
    Returns:
        Tuple of prose comments and inactive code comment blocks, both keyed by
        paragraph name (uppercase) or _PROGRAM_SUMMARY.
    """
    try:
        content = source_file.read_text(encoding='utf-8', errors='replace')
    except Exception as e:
        if verbose:
            print(f"[WARN] Could not read {source_file}: {e}")
        return {}, {}
    
    lines = content.split('\n')
    
    # Pattern to match paragraph/section definitions in Area A
    para_pattern = re.compile(
        r'^.{6}\s([A-Z0-9][A-Z0-9_-]+)(?:\s+SECTION)?\.?\s*$',
        re.IGNORECASE
    )
    
    # Pattern to detect PROCEDURE DIVISION
    proc_div_pattern = re.compile(r'PROCEDURE\s+DIVISION', re.IGNORECASE)
    
    result: dict[str, list[str]] = {}
    commented_out_code: dict[str, list[dict]] = {}
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
    
    for i, line in enumerate(lines, start=1):
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
                    pending_comments.append({"line": i, "text": clean_text})
            continue
        
        # Skip continuation lines and debug lines
        if indicator in ('-', '/', 'D', 'd'):
            continue
        
        # Check for PROCEDURE DIVISION
        if proc_div_pattern.search(line):
            # Assign pending comments to program summary
            if pending_comments:
                _assign_pending_comments(
                    '_PROGRAM_SUMMARY', pending_comments, result, commented_out_code
                )
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
                _assign_pending_comments(
                    para_name, pending_comments, result, commented_out_code
                )
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
        inactive_count = sum(len(blocks) for blocks in commented_out_code.values())
        print(f"[Comment Extractor] Found comments for {total} items" +
              (" (includes program summary)" if has_summary else "") +
              f"; inactive code blocks: {inactive_count}")
    
    return result, commented_out_code


def extract_comments(source_file: Path, verbose: bool = False) -> dict[str, list[str]]:
    """
    Extract prose comments from a COBOL source file.

    Code-like comment blocks are omitted from this legacy return value. Use
    extract_comments_with_inactive_code() when the inactive-code artifact is
    needed by callers.
    """
    comments, _ = extract_comments_with_inactive_code(source_file, verbose)
    return comments


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
    comments, commented_out_code = extract_comments_with_inactive_code(source_file, verbose)
    
    if output_file is None:
        output_file = source_file.parent / f"{source_file.stem}.comments.json"
    
    output_file.write_text(
        json.dumps(comments, indent=2, ensure_ascii=False),
        encoding='utf-8'
    )

    inactive_output = output_file.parent / "commented_out_code.json"
    inactive_output.write_text(
        json.dumps(commented_out_code, indent=2, ensure_ascii=False),
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
