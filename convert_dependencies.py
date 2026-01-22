import json
import argparse
import sys
import os

def sanitize_id(node_id):
    """Sanitize UUID to be a valid Mermaid ID"""
    return "N" + node_id.replace("-", "_")

def sanitize_label(label):
    """Escape quotes and special characters for Mermaid labels"""
    if not label:
        return "Unknown"
    label = label.replace('"', "'")
    # Truncate very long labels
    if len(label) > 40:
        label = label[:37] + "..."
    return f'"{label}"'

def main():
    parser = argparse.ArgumentParser(description="Generate Data Dependency Graph from Unified Model")
    parser.add_argument("input_json", help="Path to Unified Model JSON")
    parser.add_argument("output_md", help="Path to output Mermaid Markdown file")
    args = parser.parse_args()

    try:
        with open(args.input_json, 'r') as f:
            data = json.load(f)
    except Exception as e:
        print(f"Error reading JSON: {e}")
        sys.exit(1)

    nodes = data.get("codeVertices", [])
    data_nodes = data.get("dataVertices", [])
    nodes.extend(data_nodes)

    # Map ID to Node for label lookup
    node_map = {n["id"]: n for n in nodes if "id" in n}
    
    mermaid_lines = ["flowchart LR"]
    
    # Store used nodes to only print relevant ones
    used_node_ids = set()
    graph_edges = []
    edges = data.get("edges", [])

    for edge in edges:
        edge_type = edge.get("edgeType")
        
        # We only care about data usage
        if edge_type not in ["MODIFIES", "ACCESSES", "USES"]:
            continue
            
        from_id = edge.get("fromNodeID")
        to_id = edge.get("toNodeID")
        
        if from_id not in node_map or to_id not in node_map:
            continue
            
        used_node_ids.add(from_id)
        used_node_ids.add(to_id)
        
        san_from = sanitize_id(from_id)
        san_to = sanitize_id(to_id)
        
        arrow = "-.->"
        if edge_type == "MODIFIES":
            arrow = "-- Modifies -->"
        elif edge_type == "ACCESSES":
            arrow = "-- Reads -->"
            
        graph_edges.append(f'    {san_from} {arrow} {san_to}')

    if not graph_edges:
        print("No data dependencies found.")
        # Create empty file to avoid breaking build
        with open(args.output_md, 'w') as f:
            f.write("flowchart TD\n    Note[No Data Dependencies Found]")
        return

    # Generate Node Definitions
    for node_id in used_node_ids:
        node = node_map[node_id]
        san_id = sanitize_id(node_id)
        
        # Label logic
        label = node.get("originalText", "")
        if not label or len(label) > 40:
             label = node.get("label", node.get("name", "Node"))
        
        # Clean label
        label = label.replace("\n", " ").strip()
        
        # Visual style
        node_type = node.get("type", "")
        cats = node.get("categories", [])
        
        shape_l, shape_r = "[", "]" # Default Rectangle
        
        if "DATA_VERTEX" in node_type or "DATA" in str(cats): # It's a Variable
            shape_l, shape_r = "([", "])" # Ellipse/Stadium for variables
        elif "PROCEDURE" in node_type or "SECTION" in node_type:
             shape_l, shape_r = "[[", "]]"
             
        mermaid_lines.append(f'    {san_id}{shape_l}{sanitize_label(label)}{shape_r}')

    # Add edges
    mermaid_lines.extend(graph_edges)
    
    # Write output
    try:
        with open(args.output_md, 'w') as f:
            f.write("\n".join(mermaid_lines))
        print(f"Generated dependency graph at {args.output_md}")
    except Exception as e:
        print(f"Error writing output: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
