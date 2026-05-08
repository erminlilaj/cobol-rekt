import json
import sys
import os
import textwrap

def sanitize_text(text):
    if not text:
        return ""
    return text.replace('"', "'").replace("\n", " ").replace(">", "&gt;").replace("<", "&lt;")

def process_node(node, mermaid_lines, parent_id=None, label_key="label", id_key="id"):
    current_id = node.get(id_key)
    if not current_id:
        # Fallback if ID invalid
        current_id = f"node_{id(node)}"
        
    # Sanitize ID for mermaid (must be alphanumeric)
    safe_id = "N" + current_id.replace("-", "_")
    
    label = node.get(label_key, "")
    if not label:
        label = node.get("name", "UNKNOWN")
        
    # Optional extra info
    extra = ""
    if "type" in node:
         extra = f"<br/><i>{node['type']}</i>"
    if "levelNumber" in node:
         extra += f"<br/>Lv: {node['levelNumber']}"
    
    # Wrap label
    wrapped_label = "<br/>".join(textwrap.wrap(sanitize_text(label), width=30))
    final_label = f"{wrapped_label}{extra}"
    
    mermaid_lines.append(f'{safe_id}["{final_label}"]')
    
    if parent_id:
        mermaid_lines.append(f"{parent_id} --> {safe_id}")
        
    for child in node.get("children", []):
        process_node(child, mermaid_lines, safe_id, label_key, id_key)

def convert_file(json_path, output_path, type_label):
    try:
        with open(json_path, 'r') as f:
            data = json.load(f)
            
        mermaid_lines = ["graph TD"]
        
        # Determine keys based on file type
        label_key = "label" if "flow" in type_label else "name"
        
        # Data structures might be a list or a root object
        # Flow AST is usually a root object with children
        if isinstance(data, list):
            for item in data:
                process_node(item, mermaid_lines, None, label_key)
        else:
            process_node(data, mermaid_lines, None, label_key)
            
        with open(output_path, 'w') as f:
            f.write("\n".join(mermaid_lines))
            
        print(f"Generated {type_label} graph: {output_path}")
        
    except Exception as e:
        print(f"Error converting {json_path}: {e}")

def main():
    if len(sys.argv) < 2:
        print("Usage: python convert_json_graphs.py <report_dir>")
        sys.exit(1)
        
    report_dir = sys.argv[1]
    mermaid_dir = os.path.join(report_dir, "mermaid")
    os.makedirs(mermaid_dir, exist_ok=True)
    
    # Convert Flow AST
    flow_ast_dir = os.path.join(report_dir, "flow_ast")
    if os.path.exists(flow_ast_dir):
        for f in os.listdir(flow_ast_dir):
            if f.endswith(".json"):
                out_name = f.replace(".json", "_graph.md")
                convert_file(
                    os.path.join(flow_ast_dir, f), 
                    os.path.join(mermaid_dir, out_name),
                    "flow_ast"
                )

    # Convert Data Structures
    data_dir = os.path.join(report_dir, "data_structures")
    if os.path.exists(data_dir):
        for f in os.listdir(data_dir):
            if f.endswith(".json"):
                out_name = f.replace(".json", "_graph.md")
                convert_file(
                    os.path.join(data_dir, f), 
                    os.path.join(mermaid_dir, out_name),
                    "data_structure"
                )

if __name__ == "__main__":
    main()
