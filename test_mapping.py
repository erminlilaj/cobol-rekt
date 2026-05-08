
import json
import os
import re

def normalize_text(text):
    """Normalize whitespace for fuzzy matching."""
    if not text:
        return ""
    return re.sub(r'\s+', ' ', text).strip()

def map_nodes_to_lines(source_file, cfg_json_file):
    with open(source_file, 'r') as f:
        source_lines = f.readlines()
    
    with open(cfg_json_file, 'r') as f:
        cfg = json.load(f)

    # Pre-process source for matching
    # Map index to line number (0-based index -> 1-based line number)
    # We will try to match exact blocks first, then fuzzy.
    
    mapping = {}
    
    print(f"Total nodes: {len(cfg['nodes'])}")
    
    matched_count = 0
    
    for node in cfg['nodes']:
        original_text = node.get('originalText')
        node_id = node.get('id')
        
        if not original_text or original_text == "<NULL>":
            continue
            
        # Try to find this block in the source
        # Strategy 1: Exact match of the full block (stripping leading/trailing whitespace)
        # Strategy 2: Line by line match
        
        # Let's try a simple approach: find the first line of the originalText in the source
        node_lines = original_text.split('\n')
        # Filter out empty lines from node_lines for robustness
        node_lines = [l.strip() for l in node_lines if l.strip()]
        
        if not node_lines:
            continue
            
        first_line_clean = normalize_text(node_lines[0])
        
        possible_starts = []
        for idx, line in enumerate(source_lines):
            if first_line_clean in normalize_text(line):
                possible_starts.append(idx)
        
        # Now for each possible start, verify if subsequent lines match
        best_match = None
        
        for start_idx in possible_starts:
            match = True
            current_idx = start_idx
            
            # Check subsequent lines
            for i, node_line in enumerate(node_lines):
                # Skip empty lines in source matching if needed, or assume tight packing
                # This is a greedy check
                
                # Check if we ran out of source lines
                if current_idx >= len(source_lines):
                    match = False
                    break
                
                # Simple loose matching: checks if node_line content is IN the source line
                # Because source might have line numbers or other noise if not clean?
                # The file I saw `test-exp1.cbl` seemed clean COBOL.
                
                src_line_clean = normalize_text(source_lines[current_idx])
                node_line_clean = normalize_text(node_line)
                
                if node_line_clean not in src_line_clean:
                    # Try next source line (maybe empty line in between?)
                    current_idx += 1
                    if current_idx >= len(source_lines):
                        match = False
                        break
                    src_line_clean = normalize_text(source_lines[current_idx])
                    if node_line_clean not in src_line_clean:
                        match = False
                        break
                
                current_idx += 1
            
            if match:
                best_match = (start_idx + 1, current_idx) # 1-based start, inclusive end (converted from 0-based exclusive)
                break
        
        if best_match:
            mapping[node_id] = best_match
            matched_count += 1
            # print(f"Matched {node_id} to lines {best_match}")
        else:
            # print(f"Failed to match node {node_id}: {original_text[:50]}...")
            pass

    print(f"Matched {matched_count} out of {len(cfg['nodes'])} nodes.")
    return mapping

if __name__ == "__main__":
    source = "smojol-test-code/test-exp1.cbl"
    cfg = "out/report/test-exp1.cbl.report/cfg/cfg-test-exp1.cbl.json"
    mapping = map_nodes_to_lines(source, cfg)
    
    # Print sample mapping
    import itertools
    print("Sample mappings:")
    for k, v in itertools.islice(mapping.items(), 5):
        print(f"{k}: {v}")
