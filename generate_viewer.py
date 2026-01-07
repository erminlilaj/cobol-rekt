import os
import glob
import re
import json

MERMAID_DIR = "out/report/test-exp.cbl.report/mermaid"
OUTPUT_HTML = "out/report/test-exp.cbl.report/visualize_graphs.html"

HTML_TEMPLATE_START = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>COBOL-REKT Graph Visualizer</title>
    <style>
        body { font-family: sans-serif; padding: 20px; background: #f4f4f4; }
        .graph-container { background: white; padding: 20px; margin-bottom: 20px; border-radius: 8px; box-shadow: 0 2px 5px rgba(0,0,0,0.1); }
        h2 { border-bottom: 1px solid #eee; padding-bottom: 10px; color: #333; }
        .mermaid { text-align: center; }
    </style>
</head>
<body>
    <h1>COBOL-REKT Graph Visualizer</h1>
    <p>Generated flowcharts for <code>test-exp.cbl</code></p>
"""

HTML_TEMPLATE_END = """
    <script type="module">
      import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs';
      mermaid.initialize({ startOnLoad: true });
    </script>
</body>
</html>
"""

def sanitize_mermaid_code(code):
    """
    Fixes Mermaid syntax errors:
    1. Sanitizes UUIDs: Prefixes with 'N' and replaces hyphens with underscores.
    2. Sanitizes Quotes: Replaces HTML entity &quot; with single quotes to prevent syntax breakage.
    """
    # Regex to identify UUIDs
    uuid_pattern = re.compile(r'\b([0-9a-f]{8})-([0-9a-f]{4})-([0-9a-f]{4})-([0-9a-f]{4})-([0-9a-f]{12})\b', re.IGNORECASE)
    
    def uuid_replacer(match):
        # Prefix with 'N' and join parts with underscores
        return "N" + "_".join(match.groups())
    
    # Apply UUID fix
    code = uuid_pattern.sub(uuid_replacer, code)
    
    # Apply Quote fix (Replace HTML encoded quotes with single quotes)
    code = code.replace("&quot;", "'")
    
    return code

def generate_html(mermaid_dir, output_html, title):
    html_content = HTML_TEMPLATE_START.replace("test-exp.cbl", title)

    # Check for LLM Summary
    report_dir = os.path.dirname(mermaid_dir)
    llm_summary_dir = os.path.join(report_dir, "llm_summary")
    if os.path.exists(llm_summary_dir):
        json_files = [f for f in os.listdir(llm_summary_dir) if f.endswith(".json")]
        if json_files:
            summary_path = os.path.join(llm_summary_dir, json_files[0])
            try:
                with open(summary_path, 'r') as f:
                    summary_data = json.load(f)
                    formatted_summary = json.dumps(summary_data, indent=2)
                    html_content += f"""
                    <div class="graph-container">
                        <h2>LLM Business Logic Summary</h2>
                        <pre style="white-space: pre-wrap; word-wrap: break-word; background: #eee; padding: 10px;">{formatted_summary}</pre>
                    </div>
                    """
            except Exception as e:
                print(f"Error reading LLM summary: {e}")
    
    # Ensure directory exists to avoid errors if path is missing
    if not os.path.exists(mermaid_dir):
        print(f"Error: Directory {mermaid_dir} not found.")
        return

    # Sort files for consistent order
    files = sorted(glob.glob(os.path.join(mermaid_dir, "*.md")))
    
    if not files:
        print(f"No md files found in {mermaid_dir}")
        return

    for filepath in files:
        filename = os.path.basename(filepath)
        section_name = os.path.splitext(filename)[0]
        
        with open(filepath, "r") as f:
            mermaid_code = f.read()

        # Remove YAML front matter
        if mermaid_code.startswith("---"):
            try:
                parts = mermaid_code.split("---", 2)
                if len(parts) >= 3:
                    mermaid_code = parts[2]
            except ValueError:
                pass 
            
        # Clean up markdown code blocks
        mermaid_code = mermaid_code.replace("```mermaid", "").replace("```", "").strip()
        
        # Apply Sanitize Fixes
        mermaid_code = sanitize_mermaid_code(mermaid_code)
        
        html_content += f"""
        <div class="graph-container">
            <h2>{section_name}</h2>
            <div class="mermaid">
{mermaid_code}
            </div>
        </div>
        """
    
    html_content += HTML_TEMPLATE_END
    
    # Ensure output directory exists
    os.makedirs(os.path.dirname(output_html), exist_ok=True)
    
    with open(output_html, "w") as f:
        f.write(html_content)
    
    print(f"Successfully generated {output_html}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Generate HTML viewer for Mermaid graphs")
    parser.add_argument("--mermaid-dir", default=MERMAID_DIR, help="Directory containing Mermaid markdown files")
    parser.add_argument("--output", default=OUTPUT_HTML, help="Output HTML file path")
    parser.add_argument("--title", default="test-exp.cbl", help="Title/filename for the report")
    
    args = parser.parse_args()
    generate_html(args.mermaid_dir, args.output, args.title)