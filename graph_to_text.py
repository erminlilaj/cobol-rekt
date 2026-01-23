import sys
import re
import os

def clean_label(label_raw):
    """
    Cleans the raw DOT label.
    Input format example:
    "Processing Block: 3797...Processing\n------------------------\nDISPLAY \"GRADUATED STANDARD\"\n/3797..."
    
    Output goal:
    DISPLAY "GRADUATED STANDARD"
    """
    # Remove surrounding quotes if present
    if label_raw.startswith('"') and label_raw.endswith('"'):
        label_raw = label_raw[1:-1]
    
    # Unescape newlines
    label_raw = label_raw.replace('\\n', '\n').replace('\\"', '"')

    # lines = label_raw.split('\n')
    # Filter out metadata lines
    cleaned_lines = []
    
    # State machine or simple filtering
    # We want lines that are NOT:
    # - "Processing Block: ..."
    # - "Processing"
    # - "------------------------"
    # - "/<UUID>"
    
    for line in label_raw.split('\n'):
        line = line.strip()
        if not line: continue
        if line.startswith("Processing Block:"): continue
        if line == "Processing": continue
        if line.startswith("---------"): continue
        if line.startswith("/") and len(line) > 30: continue # Likely UUID footer
        
        cleaned_lines.append(line)
        
    return "\n".join(cleaned_lines)

def parse_dot(dot_path):
    nodes = {}
    edges = []
    
    try:
        with open(dot_path, 'r') as f:
            content = f.read()
    except Exception as e:
        print(f"Error reading {dot_path}: {e}")
        return None, None

    # Regex to find node definitions: "NodeID" ["label"="..."]
    # This is a basic parser; for production use pydot or pygraphviz if available.
    # But since we generated the DOT, we know its structure.
    
    # 1. Extract Nodes
    # Pattern: "UUID" [ ... "label"="CONTENT" ... ]
    # Handle escaped quotes like \" inside the label string
    node_pattern = re.compile(r'"([a-f0-9\-]+)"\s*\[.*?"label"="( (?:[^"\\]|\\.)* )".*?\]', re.DOTALL | re.VERBOSE)
    for match in node_pattern.finditer(content):
        node_id = match.group(1)
        raw_label = match.group(2)
        nodes[node_id] = clean_label(raw_label)

        
    # 2. Extract Edges
    # Pattern: "UUID" -> "UUID" [ ... "label"="Yes/No" ... ]
    edge_pattern = re.compile(r'"([a-f0-9\-]+)"\s*->\s*"([a-f0-9\-]+)"(?:\s*\[(.*?)\])?')
    for match in edge_pattern.finditer(content):
        src = match.group(1)
        dst = match.group(2)
        attrs = match.group(3) or ""
        
        edge_label = ""
        # Try to find specific edge labels mostly for IF conditions (Yes/No)
        # Often these are actually nodes in our graph structure, but let's check attributes
        # Our generator uses nodes for "Yes"/"No" usually, but let's be safe.
        
        edges.append((src, dst, edge_label))

    return nodes, edges

def generate_llm_text(nodes, edges, output_file):
    with open(output_file, 'w') as f:
        f.write(f"FLOW DOCUMENTATION\n")
        f.write(f"==================\n\n")
        
        # We can try to sort nodes topologically or just list them
        # For now, listing them by interactions is better.
        
        # Build adjacency for traversal if needed, or just list list edges
        f.write("FLOW LOGIC:\n")
        for src, dst, label in edges:
            src_text = nodes.get(src, "Unknown Node").replace('\n', ' ')
            dst_text = nodes.get(dst, "Unknown Node").replace('\n', ' ')
            
            # Truncate for readability in edge list
            src_short = (src_text[:50] + '..') if len(src_text) > 50 else src_text
            dst_short = (dst_text[:50] + '..') if len(dst_text) > 50 else dst_text
            
            arrow = "-->"
            if label:
                arrow = f"--[{label}]-->"
            
            f.write(f"  [{src_short}] {arrow} [{dst_short}]\n")

        f.write("\n")
        f.write("NODE DETAILS (CODE CONTENT):\n")
        f.write("----------------------------\n")
        
        # List full content of nodes involved
        seen_nodes = set()
        for src, dst, _ in edges:
            if src not in seen_nodes:
                f.write(f"\n[NODE: {src}]\n")
                f.write(nodes.get(src, ""))
                f.write("\n")
                seen_nodes.add(src)
            if dst not in seen_nodes:
                f.write(f"\n[NODE: {dst}]\n")
                f.write(nodes.get(dst, ""))
                f.write("\n")
                seen_nodes.add(dst)

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python3 graph_to_text.py <input.dot> <output.txt>")
        sys.exit(1)
        
    dot_file = sys.argv[1]
    out_file = sys.argv[2]
    
    print(f"Converting {dot_file} -> {out_file}")
    nodes, edges = parse_dot(dot_file)
    
    if nodes:
        generate_llm_text(nodes, edges, out_file)
        print("Done.")
    else:
        print("No nodes found or error parsing.")
