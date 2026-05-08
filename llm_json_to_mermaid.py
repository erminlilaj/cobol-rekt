import json
import sys
import textwrap

def sanitize_text(text):
    if not text:
        return ""
    # Remove quotes and control chars that break styling
    return text.replace('"', "'").replace("\n", " ")

node_counter = 0

def process_node(node, mermaid_lines, parent_id=None):
    global node_counter
    current_id = f"node{node_counter}"
    node_counter += 1
    
    # Extract info
    properties = node.get("properties", {})
    text_content = properties.get("text", "")
    node_type = properties.get("type", "UNKNOWN")
    summary = node.get("summary", "")
    
    # Format label: Type + Truncated Text
    label = f"<b>{node_type}</b><br/>{sanitize_text(text_content)[:30]}..."
    
    # Add node to graph
    # If there is a summary, add it as a subgraph or tooltip-like note?
    # Mermaid doesn't support rich tooltips easily in all renderers.
    # We will put the summary in the node but wrapped.
    
    if summary:
        wrapped_summary = "<br/>".join(textwrap.wrap(sanitize_text(summary), width=40))
        label += f"<br/><i>{wrapped_summary[:200]}...</i>"
        
    mermaid_lines.append(f'{current_id}["{label}"]')
    
    # Edge from parent
    if parent_id:
        mermaid_lines.append(f"{parent_id} --> {current_id}")
        
    # Recurse children
    # The JSON structure for WRITE_LLM_SUMMARY puts children in "children" list
    for child in node.get("children", []):
        process_node(child, mermaid_lines, current_id)

def main():
    if len(sys.argv) < 3:
        print("Usage: python llm_json_to_mermaid.py <json_file> <output_mermaid_file>")
        sys.exit(1)
        
    json_path = sys.argv[1]
    output_path = sys.argv[2]
    
    try:
        with open(json_path, 'r') as f:
            data = json.load(f)
            
        mermaid_lines = ["graph TD"]
        
        # The root object might be a map with "codeSummary" and "dataSummary"
        # Based on the file content check earlier:
        # "codeSummary": { "id":..., "properties":..., "children":... }
        
        if "codeSummary" in data:
            process_node(data["codeSummary"], mermaid_lines)
            
        with open(output_path, 'w') as f:
            f.write("\n".join(mermaid_lines))
            
        print(f"Generated Mermaid graph at {output_path}")
        
    except Exception as e:
        print(f"Error converting JSON to Mermaid: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
