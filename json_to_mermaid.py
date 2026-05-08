import json
import argparse
import sys
import re

def sanitize_id(node_id):
    """Sanitize UUID to be a valid Mermaid ID (start with letter, no dashes)"""
    return "N" + node_id.replace("-", "_")

def sanitize_label(label):
    """Escape quotes and special characters for Mermaid labels"""
    if not label:
        return ""
    # Replace double quotes with single quotes to avoid breaking Mermaid syntax
    label = label.replace('"', "'")
    # Replace newlines with spaces to prevent syntax errors
    label = label.replace('\n', ' ').replace('\r', '')
    # Escape single quotes by doubling them (Mermaid uses "" inside "")
    # Actually, the safest is to use HTML entity for apostrophe
    label = label.replace("'", "&#39;")
    # Escape other problematic characters
    label = label.replace("<", "&lt;").replace(">", "&gt;")
    return label.strip()

def parse_evaluate_node(node, sanitized_id, node_map, mermaid_lines):
    """
    Parses an EVALUATE node and generates a subgraph with split WHEN conditions.
    Returns the ID of the last node created (to link to NEXT logic).
    """
    original_text = node.get("originalText", "")
    
    # regex to find WHEN clauses.
    # Pattern looks for 'WHEN ...' up to the next 'WHEN' or 'END-EVALUATE' or end of string
    # We treat 'ALSO' lines as part of the same condition for now to keep it simple, 
    # or we could split them too. For visual clarity, let's keep the full condition text.
    
    # 1. Extract the main subject (e.g. EVALUATE TRUE ALSO TRUE)
    subject_match = re.match(r"(EVALUATE\s+.*?)(?=\s+WHEN)", original_text, re.DOTALL | re.IGNORECASE)
    subject_text = subject_match.group(1).strip() if subject_match else "EVALUATE"
    
    # Create the Diamond Decision Node for the Evaluate Entry
    mermaid_lines.append(f'    subgraph SG_{sanitized_id} ["{sanitize_label(subject_text)}"]')
    mermaid_lines.append(f'    direction TB')
    
    entry_id = f"{sanitized_id}_ENTRY"
    mermaid_lines.append(f'    {entry_id}{{"{sanitize_label(subject_text)}"}}')
    node_map[node.get("id")] = entry_id # Map external edges to this entry point

    # 2. Extract WHEN clauses
    # This regex matches "WHEN <condition> <action>"
    # It's tricky because actions can be multi-line.
    # We'll split by "WHEN" keyword.
    
    parts = re.split(r"\s+WHEN\s+", original_text)
    
    # parts[0] is the EVALUATE line (already handled)
    # parts[1:] are the WHEN clauses
    
    previous_decision_id = entry_id
    
    for i, part in enumerate(parts[1:]):
        # part contains "condition ... action ..."
        # simplistic heuristic: split by first newline or known keywords to separate condition from action?
        # A robust way is hard without a full parser. 
        # Let's just display the whole text in a box for now, OR try to split "ALSO"
        
        # Clean up termination
        part = part.replace("END-EVALUATE.", "").replace("END-EVALUATE", "").strip()
        
        # Create a unique ID for this branch
        branch_id = f"{sanitized_id}_WHEN_{i}"
        
        # Draw arrow from entry (or previous) to this branch
        mermaid_lines.append(f'    {entry_id} -- Option {i+1} --> {branch_id}["WHEN {sanitize_label(part)}"]')

    mermaid_lines.append(f'    end') # End subgraph

def main():
    parser = argparse.ArgumentParser(description="Convert CFG JSON to Mermaid Flowchart")
    parser.add_argument("input_json", help="Path to CFG JSON file")
    parser.add_argument("output_md", help="Path to output Mermaid Markdown file")
    args = parser.parse_args()

    try:
        with open(args.input_json, 'r') as f:
            data = json.load(f)
    except Exception as e:
        print(f"Error reading JSON: {e}")
        sys.exit(1)

    nodes = data.get("nodes", [])
    edges = data.get("edges", [])

    mermaid_lines = ["flowchart TD"]

    # Process Nodes
    node_map = {}
    
    for node in nodes:
        node_id = node.get("id")
        if not node_id:
            continue
            
        sanitized_id = sanitize_id(node_id)
        original_text = node.get("originalText", "")
        
        # SPECIAL HANDLING FOR EVALUATE NODES
        if original_text.strip().upper().startswith("EVALUATE"):
            parse_evaluate_node(node, sanitized_id, node_map, mermaid_lines)
            continue
            
        # Normal Node Processing
        
        # Determine label
        raw_label = original_text
        if not raw_label or len(raw_label) > 50:
             raw_label = node.get("label", node.get("name", "Node"))
        
        # Clean up newlines in label
        raw_label = raw_label.replace("\n", " ").strip()
        
        # Determine shape based on type
        node_type = node.get("type", "")
        left_shape = "["
        right_shape = "]"
        
        if node_type == "IF_DECISION":
            left_shape = "{"
            right_shape = "}"
        elif node_type == "PERFORM_PROCEDURE":
            left_shape = "[["
            right_shape = "]]"
        elif node_type == "TERMINATION":
            left_shape = "(("
            right_shape = "))"
            
        mermaid_lines.append(f'    {sanitized_id}{left_shape}"{sanitize_label(raw_label)}"{right_shape}')
        node_map[node_id] = sanitized_id

    # Process Edges
    for edge in edges:
        from_id = edge.get("fromNodeID")
        to_id = edge.get("toNodeID")
        edge_type = edge.get("edgeType", "")
        
        if from_id in node_map and to_id in node_map:
            arrow = "-->"
            
            if edge_type == "TRUE_CONDITION":
                arrow = "-- Yes -->"
            elif edge_type == "FALSE_CONDITION":
                arrow = "-- No -->"
            elif edge_type == "PERFORM_RETURN":
                arrow = "-.->"
            
            mermaid_lines.append(f'    {node_map[from_id]} {arrow} {node_map[to_id]}')

    # Assign output
    output_content = "\n".join(mermaid_lines)
    
    try:
        with open(args.output_md, 'w') as f:
            f.write(output_content)
        print(f"Successfully generated Mermaid graph at {args.output_md}")
    except Exception as e:
        print(f"Error writing output: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
