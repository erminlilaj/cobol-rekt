import os
import glob
import re
import json
import html

MERMAID_DIR = "out/report/test-exp.cbl.report/mermaid"
OUTPUT_HTML = "out/report/test-exp.cbl.report/visualize_graphs.html"

def normalize_text(text):
    """Normalize whitespace for fuzzy matching."""
    if not text:
        return ""
    return re.sub(r'\s+', ' ', text).strip()

def extract_nodes_from_mermaid(mermaid_dir):
    """
    Parses all mermaid markdown files in a directory and extracts node ID -> label mapping.
    Returns a dict like: {'sanitized_id': {'raw_label': ..., 'first_line': ..., 'line_count': ...}, ...}
    """
    node_labels = {}
    # Regex to find node definitions: NODE_ID["Label Text"] or NODE_ID(( )) etc.
    # We primarily care about nodes with labels in square brackets.
    node_pattern = re.compile(r'([a-f0-9\-]{36})\s*\["([^"]+)"\]', re.IGNORECASE)
    
    md_files = glob.glob(os.path.join(mermaid_dir, "*.md"))
    for filepath in md_files:
        try:
            with open(filepath, 'r') as f:
                content = f.read()
            for match in node_pattern.finditer(content):
                raw_id = match.group(1)
                label = match.group(2)
                # Sanitize ID the same way generate_viewer does (N prefix, underscores)
                sanitized_id = "N" + raw_id.replace('-', '_')
                
                # Count lines from <br> tags (each <br> = 1 additional line)
                line_count = label.count('<br>') + 1
                
                # Extract first line for matching (before first <br>)
                first_line_raw = label.split('<br>')[0] if '<br>' in label else label
                # Decode HTML entities
                first_line = first_line_raw.replace('&gt;', '>').replace('&lt;', '<').replace('&quot;', '"')
                
                node_labels[sanitized_id] = {
                    'raw_label': label,
                    'first_line': normalize_text(first_line),
                    'line_count': line_count
                }
        except Exception as e:
            print(f"Warning: Could not parse {filepath}: {e}")
    return node_labels

def extract_nodes_from_svg(graphviz_dir):
    """
    Parses all Graphviz SVG files in a directory and extracts node ID -> label mapping.
    Matches the format of extract_nodes_from_mermaid.
    """
    node_labels = {}
    # Regex to find node groups: <g id="nodeX" class="node">
    # Then find <title>...</title> and <text>...</text> inside
    
    svg_files = glob.glob(os.path.join(graphviz_dir, "*.svg"))
    
    for filepath in svg_files:
        try:
            with open(filepath, 'r') as f:
                content = f.read()
            
            # Simple parsing: Split by <g id="node
            # This is a heuristic. A robust XML parser is better but avoiding deps for now.
            # Using regex for <g class="node"> blocks
            
            # Pattern to capture the content of a node group
            # <g id="node1" class="node"><title>...</title>...<text>...</text>...</g>
            # Note: dot output puts title first.
            
            node_blocks = re.findall(r'<g [^>]*class="node"[^>]*>(.*?)</g>', content, re.DOTALL)
            
            for block in node_blocks:
                # Extract Title (UUID)
                title_match = re.search(r'<title>(.*?)</title>', block)
                if not title_match:
                    continue
                
                raw_id = title_match.group(1).strip()
                
                # Check if it looks like a UUID (approx)
                # Graphviz might add prefixes or suffixes? 
                # In the viewed file: a5bb79f2-eb48-4f88-b065-2e8e50f21928 (raw uuid)
                
                # Sanitize ID to match expected format (N + underscores)
                sanitized_id = "N" + raw_id.replace('-', '_') # Same as mermaid extraction
                
                # Extract Text (Labels)
                # There can be multiple <text> tags for multi-line labels
                text_matches = re.findall(r'<text [^>]*>(.*?)</text>', block)
                
                if not text_matches:
                    continue
                    
                full_label = "\n".join(text_matches)
                first_line = text_matches[0]
                
                # HTML decode first line
                first_line = html.unescape(text_matches[0])
                
                valid_first_line = first_line
                
                # Heuristic: If first line is "Processing", try to find first non-dash line
                if "Processing" in first_line or set(first_line.strip()) == {'-'}:
                    for line in text_matches:
                        line_clean = html.unescape(line).strip()
                        if "Processing" not in line_clean and set(line_clean) != {'-'} and line_clean:
                            valid_first_line = line_clean
                            break



                
                node_labels[sanitized_id] = {
                    'raw_label': full_label,
                    'first_line': normalize_text(valid_first_line),
                    'line_count': len(text_matches)
                }
                
        except Exception as e:
            print(f"Warning: Could not parse {filepath}: {e}")
            
    return node_labels


def map_nodes_to_lines(source_file, mermaid_dir, use_graphviz=False):
    """Creates a mapping from Node ID to Source Line Ranges using mermaid file labels."""
    mapping = {}
    
    # In Graphviz mode, mermaid_dir is actually the parent folder (somewhat confusingly named here)
    # or we handle path adjustments inside.
    # The caller passes 'mermaid_dir' as the location of .md files. 
    # If use_graphviz is True, we look in sibling 'graphviz' dir.
    
    if use_graphviz:
         output_dir = os.path.join(os.path.dirname(mermaid_dir), "graphviz")
    else:
         output_dir = mermaid_dir

    if not os.path.exists(source_file) or not os.path.exists(output_dir):
        return mapping

    try:
        with open(source_file, 'r', encoding='utf-8', errors='replace') as f:
            source_lines = f.readlines()
        
        # Precompute normalized source lines
        normalized_source = [normalize_text(line) for line in source_lines]
        
        if use_graphviz:
            node_labels = extract_nodes_from_svg(output_dir)
        else:
            node_labels = extract_nodes_from_mermaid(output_dir)
        
        for node_id, label_info in node_labels.items():



            first_line = label_info['first_line']
            line_count = label_info['line_count']
            
            if not first_line or len(first_line) < 3:
                continue  # Skip empty or very short labels
                
            # Find candidate start lines matching the first line of the label
            for idx, norm_line in enumerate(normalized_source):
                if first_line in norm_line:
                    # Found a match
                    start_line = idx + 1  # 1-based
                    end_line = min(idx + line_count, len(source_lines))  # 1-based inclusive
                    mapping[node_id] = (start_line, end_line)
                    break  # Take first match
                
    except Exception as e:
        print(f"Error creating node mapping: {e}")
        
    return mapping


HTML_TEMPLATE_START = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>COBOL-REKT Graph Visualizer</title>
    <style>
        body, html { margin: 0; padding: 0; height: 100%; overflow: hidden; font-family: sans-serif; background: #f4f4f4; }
        .main-container { display: flex; flex-direction: column; height: 100vh; }
        header { background: white; padding: 10px 20px; border-bottom: 1px solid #ddd; flex-shrink: 0; display: flex; justify-content: space-between; align-items: center; box-shadow: 0 2px 5px rgba(0,0,0,0.05); z-index: 20; }
        h1 { margin: 0; font-size: 1.2rem; color: #333; }
        .toolbar { display: flex; gap: 10px; }
        .btn { padding: 6px 12px; border: 1px solid #ccc; background: #f9f9f9; border-radius: 4px; cursor: pointer; font-size: 0.9rem; transition: all 0.2s; }
        .btn:hover { background: #eee; border-color: #bbb; }
        .btn.active { background: #e0e0e0; border-color: #999; box-shadow: inset 0 1px 3px rgba(0,0,0,0.1); }
        
        .content-wrapper { display: flex; flex: 1; overflow: hidden; position: relative; }
        
        /* Code Pane */
        .code-pane { width: 40%; background: #282c34; color: #abb2bf; display: flex; flex-direction: column; border-right: 1px solid #444; transition: width 0.1s; }
        .code-pane.hidden { display: none; }
        .code-header { background: #21252b; padding: 10px; font-size: 0.9rem; border-bottom: 1px solid #181a1f; color: #9da5b4; }
        .code-content { flex: 1; overflow: auto; padding: 10px; font-family: 'Consolas', 'Monaco', 'Courier New', monospace; font-size: 14px; line-height: 1.5; white-space: pre; }
        .line-number { display: inline-block; width: 40px; color: #5c6370; text-align: right; margin-right: 10px; user-select: none; cursor: pointer; }
        .line-row { display: block; }
        .line-row:hover { background: #3e4451; }
        
        /* Highlighting */
        .highlight-code { background-color: #4b5363; color: #fff; font-weight: bold; }
        .highlight-code .line-number { color: #d19a66; font-weight: bold; }

        /* Graph Pane */
        .graph-pane { flex: 1; overflow-y: auto; padding: 20px; background: #f4f4f4; display: flex; flex-direction: column; gap: 20px; position: relative; }
        
        .graph-card { background: white; border-radius: 8px; box-shadow: 0 2px 5px rgba(0,0,0,0.1); overflow: hidden; display: flex; flex-direction: column; min-height: 500px; }
        .graph-card h2 { margin: 0; padding: 15px; border-bottom: 1px solid #eee; font-size: 1.1rem; color: #444; background: #fafafa; }
        .mermaid-container { flex: 1; position: relative; overflow: hidden; background: white; min-height: 400px; }
        .mermaid { width: 100%; height: 100%; display: flex; justify-content: center; align-items: center; }
        .mermaid svg { height: 100%; width: 100%; }
        
        /* Node Highlighting in Graph */
        .highlight-node polygon, .highlight-node rect, .highlight-node circle, .highlight-node path { 
            stroke: #ff0000 !important; 
            stroke-width: 3px !important; 
            filter: drop-shadow(0 0 5px rgba(255,0,0,0.5));
        }

        /* Resizer */
        .resizer { width: 5px; background: #ccc; cursor: col-resize; z-index: 10; transition: background 0.2s; }
        .resizer:hover { background: #999; }
        .resizer.hidden { display: none; }

        .zoom-controls { position: absolute; bottom: 10px; right: 10px; display: flex; gap: 5px; background: rgba(255, 255, 255, 0.9); border: 1px solid #ddd; padding: 5px; border-radius: 4px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); z-index: 5; display: none; }
        .zoom-controls.visible { display: flex; }
        .zoom-btn { background: white; border: 1px solid #ccc; border-radius: 4px; width: 25px; height: 25px; display: flex; align-items: center; justify-content: center; cursor: pointer; font-weight: bold; color: #555; }
        .zoom-btn:hover { background: #f0f0f0; }

    </style>
    <script src="https://cdn.jsdelivr.net/npm/svg-pan-zoom@3.6.1/dist/svg-pan-zoom.min.js"></script>
</head>
<body>
    <div class="main-container">
        <header>
            <h1>COBOL-REKT: test-exp.cbl</h1>
            <div class="toolbar">
                <button id="toggleCodeBtn" class="btn active" onclick="toggleCodePane()">Hide Code</button>
            </div>
        </header>
        <div class="content-wrapper">
            <div id="codePane" class="code-pane">
                <div class="code-header">Source Code</div>
                <div class="code-content" id="sourceCode">
<!-- SOURCE_CODE_PLACEHOLDER -->
                </div>
            </div>
            <div id="resizer" class="resizer"></div>
            <div class="graph-pane">
"""

HTML_TEMPLATE_END = """
            </div>
        </div>
    </div>

    <script type="module">
      import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs';
      
      // Inject Node Mapping Data
      // NODE_TO_LINES_PLACEHOLDER
      
      const ENABLE_PAN_ZOOM = // ENABLE_PAN_ZOOM_PLACEHOLDER;
      const USE_GRAPHVIZ = // USE_GRAPHVIZ_PLACEHOLDER;
      
      if (!USE_GRAPHVIZ) {
          mermaid.initialize({ 
            startOnLoad: false,
            maxTextSize: 5000000, // Increase limit to 5MB
            securityLevel: 'loose', // Allow HTML in labels (required for <br/>, <i>, etc.)
            htmlLabels: true, // Enable HTML label parsing
            flowchart: {
              htmlLabels: true
            }
          });
          
          await mermaid.run({
            querySelector: '.mermaid'
          });
      }

      // Initialize svg-pan-zoom and Event Listeners
      document.querySelectorAll('.mermaid-container').forEach((container) => {
        const svgElement = container.querySelector('.mermaid svg');
        if (!svgElement) return;

        // --- Interaction Logic ---
        
        // 1. Highlight Code from Nodes
        const nodes = svgElement.querySelectorAll('.node');
        nodes.forEach(node => {
            // Restore normal cursor
            node.style.cursor = 'pointer';
            
            node.addEventListener('click', (e) => {
                e.preventDefault(); 
                e.stopPropagation();
                
                // Clear previous highlights
                document.querySelectorAll('.highlight-code').forEach(el => el.classList.remove('highlight-code'));
                document.querySelectorAll('.highlight-node').forEach(el => el.classList.remove('highlight-node'));

                // Mermaid modifies IDs to 'flowchart-XXXXX-N' format. Extract the core UUID.
                let rawNodeId = node.id;
                
                // Graphviz Support: Node ID is usually 'nodeX', UUID is in <title> child
                let graphvizUuid = null;
                const titleNode = node.querySelector('title');
                if (titleNode) {
                    graphvizUuid = titleNode.textContent.trim();
                    // Sanitize to match NODE_TO_LINES format (N + underscores)
                    // Configured in extract_nodes_from_svg to be N + raw_id.replace('-', '_')
                    // But wait, extract_nodes_from_svg used: "N" + raw_id.replace('-', '_')
                    // So we must replicate that here to match the key.
                    if (graphvizUuid) {
                         const sanitizedGraphvizId = "N" + graphvizUuid.replace(/-/g, '_');
                         // If this sanitized ID exists in our map, use it.
                         if (NODE_TO_LINES && NODE_TO_LINES[sanitizedGraphvizId]) {
                             rawNodeId = sanitizedGraphvizId;
                         }
                    }
                }

                // Add highlight to clicked node
                node.classList.add('highlight-node');
                
                // Try to find a matching key in NODE_TO_LINES by checking if the rawNodeId contains it
                if (typeof NODE_TO_LINES !== 'undefined') {
                    for (const [mappedId, range] of Object.entries(NODE_TO_LINES)) {
                        // Check if DOM ID contains mapped ID (Mermaid) OR if it exactly matches (Graphviz sanitized)
                        if (rawNodeId.includes(mappedId) || rawNodeId === mappedId) {
                            const [startLine, endLine] = range;
                            
                            let firstElement = null;
                            for (let i = startLine; i <= endLine; i++) {
                                const lineEl = document.getElementById(`line-${i}`);
                                if (lineEl) {

                                    lineEl.classList.add('highlight-code');
                                    if (!firstElement) firstElement = lineEl;
                                }
                            }
                            
                            if (firstElement) {
                                firstElement.scrollIntoView({ behavior: 'smooth', block: 'center' });
                            }
                            break; // Found matching key
                        }
                    }
                }
            });
            
            // Allow hover effects too?
            node.addEventListener('mouseenter', () => {
                 // Optional: Hover effect logic
            });
        });

        // 2. Highlight Node from Code (Reverse Lookup)
        // Handled globally below to avoid attaching thousands of listeners
        
        // --- End Interaction Logic ---

        if (ENABLE_PAN_ZOOM) {
            // Create custom controls
            const controls = document.createElement('div');
            controls.className = 'zoom-controls visible';
            controls.innerHTML = `
                <button class="zoom-btn zoom-in" title="Zoom In">+</button>
                <button class="zoom-btn zoom-out" title="Zoom Out">-</button>
                <button class="zoom-btn zoom-reset" title="Reset">R</button>
            `;
            container.appendChild(controls);
    
            try {
                const panZoomInstance = svgPanZoom(svgElement, {
                zoomEnabled: true,
                controlIconsEnabled: false,
                fit: true,
                center: true,
                minZoom: 0.1,
                maxZoom: 10
                });
    
                // Bind controls
                controls.querySelector('.zoom-in').addEventListener('click', () => panZoomInstance.zoomIn());
                controls.querySelector('.zoom-out').addEventListener('click', () => panZoomInstance.zoomOut());
                controls.querySelector('.zoom-reset').addEventListener('click', () => panZoomInstance.reset());
                
                // Handle resize
                const observer = new ResizeObserver(() => {
                    panZoomInstance.resize();
                    panZoomInstance.fit();
                    panZoomInstance.center();
                });
                observer.observe(container);
    
            } catch (e) {
                console.error("SVG Pan Zoom failed initialization", e);
            }
        }
      });
      
      // Global Listener for Code Line Clicks
      document.getElementById('sourceCode').addEventListener('click', (e) => {
          const lineRow = e.target.closest('.line-row');
          if (!lineRow) return;
          
          const lineNum = parseInt(lineRow.getAttribute('data-line'), 10);
          if (isNaN(lineNum)) return;

          // Clear previous highlights
          document.querySelectorAll('.highlight-code').forEach(el => el.classList.remove('highlight-code'));
          document.querySelectorAll('.highlight-node').forEach(el => el.classList.remove('highlight-node'));
          
          // Highlight the clicked line row
          lineRow.classList.add('highlight-code');

          // Find node containing this line
          if (typeof NODE_TO_LINES !== 'undefined') {
              for (const [nodeId, range] of Object.entries(NODE_TO_LINES)) {
                  if (lineNum >= range[0] && lineNum <= range[1]) {
                      // Find SVG node whose ID contains the mapped nodeId
                      const allNodes = document.querySelectorAll('.node');
                      allNodes.forEach(svgNode => {
                          // Mermaid check: ID contains mapped ID
                          if (svgNode.id.includes(nodeId)) {
                              svgNode.classList.add('highlight-node');
                          } else {
                              // Graphviz check: Title content contains UUID
                              const titleNode = svgNode.querySelector('title');
                              if (titleNode) {
                                  const rawUuid = titleNode.textContent.trim();
                                  const sanitizedGraphvizId = "N" + rawUuid.replace(/-/g, '_');
                                  if (sanitizedGraphvizId === nodeId) {
                                       svgNode.classList.add('highlight-node');
                                  }
                              }
                          }
                      });
                  }
              }
          }
      });
      
    </script>
    
    <script>
        // Split Pane Logic
        const codePane = document.getElementById('codePane');
        const resizer = document.getElementById('resizer');
        const toggleBtn = document.getElementById('toggleCodeBtn');
        let isCodeVisible = true;

        function toggleCodePane() {
            isCodeVisible = !isCodeVisible;
            if (isCodeVisible) {
                codePane.classList.remove('hidden');
                resizer.classList.remove('hidden');
                toggleBtn.textContent = "Hide Code";
                toggleBtn.classList.add('active');
            } else {
                codePane.classList.add('hidden');
                resizer.classList.add('hidden');
                toggleBtn.textContent = "Show Code";
                toggleBtn.classList.remove('active');
            }
        }

        // Draggable Resizer
        let isResizing = false;

        resizer.addEventListener('mousedown', (e) => {
            isResizing = true;
            document.body.style.cursor = 'col-resize';
            resizer.style.background = '#007fd4'; // Highlight color
        });

        document.addEventListener('mousemove', (e) => {
            if (!isResizing) return;
            const containerWidth = document.body.clientWidth;
            const newWidth = e.clientX;
            
            // Limit constraints (min 10%, max 70%)
            if (newWidth > containerWidth * 0.1 && newWidth < containerWidth * 0.7) {
                codePane.style.width = newWidth + 'px';
            }
        });

        document.addEventListener('mouseup', () => {
            if (isResizing) {
                isResizing = false;
                document.body.style.cursor = 'default';
                resizer.style.background = '#ccc';
            }
        });
    </script>
</body>
</html>
"""

def sanitize_mermaid_code(code):
    """
    Fixes Mermaid syntax errors:
    1. Removes invisible zero-width Unicode characters.
    2. Sanitizes UUIDs: Prefixes with 'N' and replaces hyphens with underscores.
    3. Sanitizes Quotes: Replaces HTML entity &quot; with single quotes to prevent syntax breakage.
    """
    # Remove zero-width and other invisible Unicode characters that break Mermaid parsing
    # Common culprits: Zero Width Space (\u200B), Zero Width Non-Joiner (\u200C),
    # Zero Width Joiner (\u200D), Byte Order Mark (\uFEFF), others
    invisible_chars = [
        '\u200B',  # Zero Width Space
        '\u200C',  # Zero Width Non-Joiner
        '\u200D',  # Zero Width Joiner
        '\uFEFF',  # Byte Order Mark
        '\u00A0',  # Non-breaking space (replace with regular space)
        '\u2028',  # Line Separator
        '\u2029',  # Paragraph Separator
    ]
    for char in invisible_chars:
        if char == '\u00A0':
            code = code.replace(char, ' ')  # Replace NBSP with regular space
        else:
            code = code.replace(char, '')  # Remove others
    
    # Regex to identify UUIDs
    uuid_pattern = re.compile(r'\b([0-9a-f]{8})-([0-9a-f]{4})-([0-9a-f]{4})-([0-9a-f]{4})-([0-9a-f]{12})\b', re.IGNORECASE)
    
    def uuid_replacer(match):
        # Prefix with 'N' and join parts with underscores
        return "N" + "_".join(match.groups())
    
    # Apply UUID fix
    code = uuid_pattern.sub(uuid_replacer, code)
    
    # Apply Quote fix (Replace HTML encoded quotes with single quotes)
    code = code.replace("&quot;", "'")
    
    # Fix potential unescaped double quotes inside labels
    # This matches: Any char not ] or ", followed by ", followed by any char not " or [
    # It's a heuristic. A safer way is to rely on the fact that labels are inside ["..."]
    
    # Aggressive replacement: Replace all " with ' inside the label content
    # We iterate line by line to be safer
    lines = code.split('\n')
    new_lines = []
    for line in lines:
        # Check if line has a label definition like key["label content"]
        if '["' in line and '"]' in line:
            parts = line.split('["', 1)
            pre = parts[0]
            remainder = parts[1]
            if '"]' in remainder:
                label_parts = remainder.rsplit('"]', 1)
                label_content = label_parts[0]
                post = label_parts[1]
                
                # Sanitize content
                label_content = label_content.replace('"', "'")
                # Also escape other chars if needed
                
                new_line = f'{pre}["{label_content}"]{post}'
                new_lines.append(new_line)
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)
            
    code = "\n".join(new_lines)

    return code

    return code

def generate_html(mermaid_dir, output_html, title, source_file=None, enable_pan_zoom=True, use_graphviz=False):

    html_content = HTML_TEMPLATE_START.replace("test-exp.cbl", title)

    # Inject Source Code if provided
    source_code_html = "<!-- Source code not linked -->"
    node_mapping = {}
    
    if source_file and os.path.exists(source_file):
        try:
            # Generate Mapping using mermaid files (not CFG JSON, as IDs differ per run)
            node_mapping = map_nodes_to_lines(source_file, mermaid_dir, use_graphviz=use_graphviz)
            print(f"Generated mappings for {len(node_mapping)} nodes.")

            print(f"Generated mappings for {len(node_mapping)} nodes.")


            with open(source_file, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()
                formatted_lines = []
                for idx, line in enumerate(lines, 1):
                    # Simple HTML escape
                    safe_line = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                    # ADDED: Wrapper div with ID for highlighting targeting
                    formatted_lines.append(f'<div class="line-row" id="line-{idx}" data-line="{idx}"><span class="line-number">{idx}</span>{safe_line}</div>')
                source_code_html = "".join(formatted_lines)
        except Exception as e:
            source_code_html = f"Error reading source file or generating mapping: {e}"
    
    html_content = html_content.replace("<!-- SOURCE_CODE_PLACEHOLDER -->", source_code_html)

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
                    <div class="graph-card">
                        <h2>LLM Business Logic Summary</h2>
                        <div style="padding: 20px; overflow: auto; max-height: 500px;">
                            <pre style="white-space: pre-wrap; word-wrap: break-word; background: #eee; padding: 10px;">{formatted_summary}</pre>
                        </div>
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
    
    files = sorted(glob.glob(os.path.join(mermaid_dir, "*.md")))
    
    if use_graphviz:
        # Switch to Graphviz mode
        # Assume graphviz sibling directory
        graphviz_dir = os.path.join(os.path.dirname(mermaid_dir), "graphviz")
        if os.path.exists(graphviz_dir):
             files = sorted(glob.glob(os.path.join(graphviz_dir, "*.svg")))
             print(f"Graphviz Mode: Found {len(files)} SVG files in {graphviz_dir}")
        else:
             print(f"Graphviz Mode: Directory {graphviz_dir} not found. Falling back to Mermaid.")
             use_graphviz = False # Fallback

    if not files:

        print(f"No md files found in {mermaid_dir}")
        return

    for filepath in files:
        filename = os.path.basename(filepath)
        section_name = os.path.splitext(filename)[0]
        
        if use_graphviz:
             # Graphviz SVG embedding
             with open(filepath, "r") as f:
                 svg_content = f.read()
             
             # Attempt to clean up SVG (remove xml decl, width/height to allow scaling)
             # Removing <?xml ...> and <!DOCTYPE ...>
             svg_content = re.sub(r'<\?xml.*?\?>', '', svg_content)
             svg_content = re.sub(r'<!DOCTYPE.*?>', '', svg_content)

             # Enforce class for styling
             if '<svg' in svg_content:
                 svg_content = svg_content.replace('<svg', '<svg class="graphviz-svg"', 1)

             html_content += f"""
            <div class="graph-card">
                <h2>{section_name}</h2>
                <div class="mermaid-container">
                    <div class="mermaid">
                        {svg_content}
                    </div>
                </div>
            </div>
            """
             continue

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
        <div class="graph-card">
            <h2>{section_name}</h2>
            <div class="mermaid-container">
                <div class="mermaid">
{mermaid_code}
                </div>
            </div>
        </div>
        """
    
    # Inject Mapping Data JSON
    mapping_json = f"const NODE_TO_LINES = {json.dumps(node_mapping)};"
    html_template_end_injected = HTML_TEMPLATE_END.replace("// NODE_TO_LINES_PLACEHOLDER", mapping_json)
    
    # Inject Pan Zoom Flag
    pan_zoom_bool = "true" if enable_pan_zoom else "false"
    html_template_end_injected = html_template_end_injected.replace("// ENABLE_PAN_ZOOM_PLACEHOLDER;", pan_zoom_bool)
    
    # Inject Graphviz Flag
    use_graphviz_bool = "true" if use_graphviz else "false"
    html_template_end_injected = html_template_end_injected.replace("// USE_GRAPHVIZ_PLACEHOLDER;", use_graphviz_bool)
    
    html_content += html_template_end_injected
    
    # Ensure output directory exists
    output_dir = os.path.dirname(output_html)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    
    with open(output_html, "w") as f:
        f.write(html_content)
    
    print(f"Successfully generated {output_html}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Generate HTML viewer for Mermaid graphs")
    parser.add_argument("--mermaid-dir", default=MERMAID_DIR, help="Directory containing Mermaid markdown files")
    parser.add_argument("--output", default=OUTPUT_HTML, help="Output HTML file path")
    parser.add_argument("--title", default="test-exp.cbl", help="Title/filename for the report")
    parser.add_argument("--source", help="Path to the COBOL source file for the split-pane view", required=False)
    parser.add_argument("--code", action="store_true", help="Enable split-pane code view with interactive highlighting")
    parser.add_argument("--graphviz", action="store_true", help="Use Graphviz SVG outputs instead of Mermaid")
    
    args = parser.parse_args()

    # Only pass source file if --code flag is set
    source_file = args.source if args.code else None
    
    # Requirement: "remove completely the pan if its not --code"
    # Logic: Enable pan only if --code is True.
    # Note: Usually pan is good for large graphs, but following specific instruction.
    enable_pan = args.code
    
    generate_html(args.mermaid_dir, args.output, args.title, source_file, enable_pan_zoom=enable_pan, use_graphviz=args.graphviz)