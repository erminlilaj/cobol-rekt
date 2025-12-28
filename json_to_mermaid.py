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
    label = label.replace('"', "'")
    return f'"{label}"'

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
    # Use 'originalText' if available and short enough, else 'label' or 'name'
    node_map = {}
    
    for node in nodes:
        node_id = node.get("id")
        if not node_id:
            continue
            
        sanitized_id = sanitize_id(node_id)
        
        # Determine label
        raw_label = node.get("originalText", "")
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
            
        mermaid_lines.append(f'    {sanitized_id}{left_shape}{sanitize_label(raw_label)}{right_shape}')
        node_map[node_id] = sanitized_id

    # Process Edges
    for edge in edges:
        from_id = edge.get("fromNodeID")
        to_id = edge.get("toNodeID")
        edge_type = edge.get("edgeType", "")
        
        if from_id in node_map and to_id in node_map:
            arrow = "-->"
            label = ""
            
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
