import os
import shutil
import re
from pathlib import Path

# ANSI colors for terminal output
class Colors:
    GREEN = '\033[0;32m'
    RED = '\033[0;31m'
    BLUE = '\033[0;34m'
    YELLOW = '\033[1;33m'
    MAGENTA = '\033[0;35m'
    NC = '\033[0m'

    @staticmethod
    def print_msg(msg, color=NC):
        print(f"{color}{msg}{Colors.NC}")

def find_file_recursive(name, root_dir):
    """Find a file with case-insensitive matching in root_dir and subdirs."""
    # Common variations of extensions and cases
    candidates = [
        f"{name}.cpy", f"{name}.CPY",
        f"{name}.cbl", f"{name}.CBL",
        
        name, name.upper(), name.lower()
    ]
    
    # First check flat structure (optimization)
    for cand in candidates:
        possible = root_dir / cand
        if possible.exists():
            return possible

    # Then recursive search
    for path in root_dir.rglob("*"):
        if path.is_file() and path.name in candidates:
            return path
            
    # Try ignoring extension case entirely provided file matches base name
    for path in root_dir.rglob("*"):
         if path.is_file() and path.stem.upper() == name.upper():
             # Check if extension is copybook-like
             if path.suffix.lower() in ['.cpy', '.cbl', '.cob', '']:
                 return path
                 
    return None

def resolve_copybooks_recursively(source_file, copybooks_dir, search_root, seen=None, ignore_mode=False):
    """
    Recursively find COPY statements and ensure copybooks exist in copybooks_dir.
    """
    if seen is None:
        seen = set()

    file_name = Path(source_file).name
    if file_name in seen:
        return
    seen.add(file_name)

    try:
        with open(source_file, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
    except Exception as e:
        Colors.print_msg(f"  Error reading {source_file}: {e}", Colors.RED)
        return

    # Improved Regex:
    # Matches: COPY NAME. 
    #          COPY 'NAME'. 
    #          COPY "NAME". 
    #          COPY NAME OF LIBRARY.
    #          COPY NAME IN LIBRARY.
    matches = re.findall(r'COPY\s+[\'\"]?([\w-]+)[\'\"]?(?:\s+(?:OF|IN)\s+[\w-]+)?', content, re.IGNORECASE)
    
    if not matches:
        return

    Colors.print_msg(f"  Scanning {file_name}: Found {len(matches)} COPY statements", Colors.BLUE)

    for copybook_name in matches:
        # Normalize target name
        target_file = copybooks_dir / f"{copybook_name}.cpy"
        
        # If it's already in the standard location, verify it valid, then recurse
        if target_file.exists():
            # Recurse into it to find nested copybooks
            resolve_copybooks_recursively(target_file, copybooks_dir, search_root, seen, ignore_mode)
            continue

        if ignore_mode:
            Colors.print_msg(f"    [Ignored] {copybook_name}", Colors.MAGENTA)
            continue

        # Search for original
        found_path = find_file_recursive(copybook_name, search_root)
        
        if found_path:
             Colors.print_msg(f"    [Found] {copybook_name} -> {found_path.name}", Colors.GREEN)
             try:
                 shutil.copy(found_path, target_file)
                 # Recursively scan the found copybook!
                 resolve_copybooks_recursively(target_file, copybooks_dir, search_root, seen, ignore_mode)
             except Exception as e:
                 Colors.print_msg(f"    Error copying {copybook_name}: {e}", Colors.RED)
        else:
             Colors.print_msg(f"    [Missing] {copybook_name} (Not found in search path)", Colors.YELLOW)
             # Do NOT create dummy file, as requested. Let parser fail/skip.
