import argparse
import os
import requests
import json
from pathlib import Path
import time
import datetime

# ==============================================================================
# LLM CONFIGURATION - Single Source of Truth
# This file owns all Ollama model/port/endpoint settings.
# analyze.sh calls this script directly without duplicating config.
# ==============================================================================
DEFAULT_MODEL = "granite-code:8b"
DEFAULT_HOST = "localhost"
DEFAULT_PORT = 11434
# Chunking settings for large inputs
MAX_CHUNK_LINES = 200  # Max lines per chunk (keeps each chunk ~4-6KB)
CHUNK_OVERLAP_LINES = 10  # Overlap to maintain context between chunks

DEFAULT_PROMPT = """
You are a Mainframe Modernization Architect performing static analysis on COBOL programs.
Your task is to generate technical documentation from the provided Control Flow Graph (CFG) and code snippets.

ANALYSIS REQUIREMENTS:

1.  **Cyclomatic Complexity**: Estimate complexity based on decision nodes (IF, EVALUATE, PERFORM UNTIL).
2.  **Data Flow Analysis**:
    - Identify DEF (definition) and USE chains for key variables.
    - Flag potential uninitialized reads or dead stores.
3.  **Control Flow Patterns**:
    - Classify loops: bounded (PERFORM N TIMES), conditional (PERFORM UNTIL), or recursive (PERFORM paragraph invoking itself).
    - Identify conditional branches and their coverage (IF/ELSE completeness).
4.  **External Dependencies**:
    - List all CALL statements with their USING parameters (direction: BY REFERENCE/BY CONTENT/BY VALUE).
    - Document FILE I/O operations (OPEN, READ, WRITE, CLOSE) and their associated FD/COPY structures.
    - Identify embedded SQL (EXEC SQL) or CICS (EXEC CICS) blocks.
5.  **Working-Storage / Linkage Analysis**:
    - Summarize data structures (01-level groups, their hierarchy, PIC clauses, and REDEFINES).
    - Note COPY statements and assumed copybook structures.
6.  **Business Rule Extraction**:
    - Translate conditional logic into declarative rules (e.g., "IF WS-BALANCE < 0 → Set WS-OVERDRAFT-FLAG to 'Y'").
    - Identify validation patterns (field-level checks, cross-field dependencies).

OUTPUT FORMAT (Markdown):

## [PARAGRAPH-NAME] Technical Analysis

### Summary
<1-2 sentence purpose>

### Control Flow
- **Type**: <Sequential | Branching | Loop | Hybrid>
- **Complexity**: <Low (1-5) | Medium (6-10) | High (>10)>
- **Graph Path**: <Entry → Decision Points → Exit>

### Data Flow
| Variable | DEF/USE | Scope | Purpose |
|----------|---------|-------|---------|
| ...      | ...     | ...   | ...     |

### External Interactions
- **Calls**: <List with parameters>
- **File I/O**: <Operations and files>
- **DB/CICS**: <Statements if any>

### Extracted Business Rules
1. <Rule as IF-THEN statement>
2. ...

### Modernization Notes
- <Potential refactoring targets, code smells, or migration risks>

INPUT CONTEXT:
"""

def save_performance_report(metrics, output_dir_path):
    report_file = output_dir_path / "llm-performance.md"
    
    total_files = len(metrics["files"])
    total_time = sum(f["duration"] for f in metrics["files"])
    total_tokens = sum(f["eval_count"] for f in metrics["files"])
    avg_speed = total_tokens / total_time if total_time > 0 else 0
    
    with open(report_file, "w") as f:
        f.write(f"# LLM Performance Report\n\n")
        f.write(f"- **Date**: {datetime.datetime.now()}\n")
        f.write(f"- **Model**: {metrics['model']}\n")
        f.write(f"- **Total Files**: {total_files}\n")
        f.write(f"- **Total Time**: {total_time:.2f}s\n")
        f.write(f"- **Total Tokens Generated**: {total_tokens}\n")
        f.write(f"- **Average Speed**: {avg_speed:.2f} tokens/s\n\n")
        
        f.write("| File | Time (s) | Tokens | Speed (t/s) |\n")
        f.write("|------|----------|--------|-------------|\n")
        
        for entry in metrics["files"]:
            speed = entry["eval_count"] / entry["duration"] if entry["duration"] > 0 else 0
            f.write(f"| {entry['filename']} | {entry['duration']:.2f} | {entry['eval_count']} | {speed:.2f} |\n")
            
    print(f"\nPerformance report saved to: {report_file}")

def chunk_content(content: str, max_lines: int = MAX_CHUNK_LINES, overlap: int = CHUNK_OVERLAP_LINES) -> list[str]:
    """
    Split large content into smaller chunks that fit within the model's context.
    
    Tries to split at natural boundaries (empty lines, paragraph markers) when possible.
    
    Args:
        content: The full text content to chunk
        max_lines: Maximum lines per chunk
        overlap: Number of overlapping lines between chunks for context
        
    Returns:
        List of content chunks
    """
    lines = content.split('\n')
    
    # If content is small enough, return as-is
    if len(lines) <= max_lines:
        return [content]
    
    chunks = []
    start = 0
    
    while start < len(lines):
        end = min(start + max_lines, len(lines))
        
        # Try to find a natural break point (empty line or paragraph marker) near the end
        if end < len(lines):
            # Look back up to 20 lines for a good break point
            for i in range(end, max(start + max_lines - 20, start), -1):
                line = lines[i].strip()
                # Good break points: empty line, comment line, paragraph heading
                if line == '' or line.startswith('Paragraph:') or line.startswith('Node:') or line.startswith('---'):
                    end = i
                    break
        
        chunk_lines = lines[start:end]
        chunks.append('\n'.join(chunk_lines))
        
        # Move start forward, accounting for overlap
        start = end - overlap if end < len(lines) else end
    
    return chunks

def generate_documentation(input_dir, output_dir, model, port, prompt_override=None, verbose=False):
    input_path = Path(input_dir)
    
    # Smart Default: If output_dir is None, create 'documentation' output inside the parent's directory
    # or sibling to 'llm_input'
    if output_dir:
        output_path = Path(output_dir)
    else:
        # If input is ".../llm_input", output becomes ".../documentation"
        if input_path.name == "llm_input":
             output_path = input_path.parent / "documentation"
        else:
             output_path = input_path.parent / "documentation"

    output_path.mkdir(parents=True, exist_ok=True)
    
    api_url = f"http://localhost:{port}/api/generate"
    
    files = list(input_path.glob("*.txt"))
    if not files:
        print(f"No .txt files found in {input_path}")
        return

    print(f"\n{'='*60}")
    print(f"STARTING LLM DOCUMENTATION GENERATION")
    print(f"Model: {model}")
    print(f"Input: {input_path}")
    print(f"Output: {output_path}")
    print(f"{'='*60}\n")

    prompt_template = prompt_override if prompt_override else DEFAULT_PROMPT
    
    metrics = {
        "model": model,
        "files": []
    }

    for txt_file in sorted(files):
        print(f"Processing: {txt_file.name}")
            
        start_time = time.time()
        
        try:
            with open(txt_file, "r") as f:
                content = f.read()

            # Chunk the content if it's too large
            chunks = chunk_content(content)
            num_chunks = len(chunks)
            
            if num_chunks > 1:
                print(f"  Large file detected ({len(content.split(chr(10)))} lines) - splitting into {num_chunks} chunks")
            
            all_responses = []
            total_eval_count = 0
            
            for chunk_idx, chunk in enumerate(chunks):
                if num_chunks > 1:
                    chunk_header = f"\n[Chunk {chunk_idx + 1}/{num_chunks}]\n"
                    print(f"  Processing chunk {chunk_idx + 1}/{num_chunks}...")
                else:
                    chunk_header = ""
                
                if verbose:
                    print(f"  Sending request to {api_url}...")
                
                # Add chunk context to prompt for multi-chunk files
                if num_chunks > 1:
                    chunk_prompt = f"{prompt_template}\n\n[This is part {chunk_idx + 1} of {num_chunks} of a large program. Focus on documenting this section.]\n\n{chunk}"
                else:
                    chunk_prompt = f"{prompt_template}\n\n{chunk}"
                
                payload = {
                    "model": model,
                    "prompt": chunk_prompt,
                    "stream": True,
                    "options": {
                        "temperature": 0.2,
                        "num_ctx": 8192
                    }
                }
                
                response = requests.post(api_url, json=payload, stream=True)
                response.raise_for_status()
                
                chunk_response = ""
                eval_count = 0
                
                # Streaming Loop
                if num_chunks == 1:
                    print("  Response: ", end="", flush=True)
                
                for line in response.iter_lines():
                    if line:
                        body = json.loads(line)
                        text_chunk = body.get("response", "")
                        chunk_response += text_chunk
                        if num_chunks == 1:
                            print(text_chunk, end="", flush=True)
                        
                        if body.get("done"):
                            eval_count = body.get("eval_count", 0)
                            total_eval_count += eval_count
                
                if num_chunks == 1:
                    print("\n")
                elif verbose:
                    print(f"    Chunk {chunk_idx + 1}: {eval_count} tokens")
                
                all_responses.append(chunk_header + chunk_response)
            
            # Combine all chunk responses
            full_response_text = "\n".join(all_responses)
            
            if num_chunks > 1:
                print(f"  Combined {num_chunks} chunks, total {total_eval_count} tokens")

            # Save Output
            out_file = output_path / f"{txt_file.stem}_doc.md"
            with open(out_file, "w") as out:
                out.write(f"# Documentation for {txt_file.stem}\n\n")
                if num_chunks > 1:
                    out.write(f"> *This documentation was generated from {num_chunks} chunks due to file size.*\n\n")
                out.write(full_response_text)
                
            elapsed = time.time() - start_time
            
            # Record Metrics
            metrics["files"].append({
                "filename": txt_file.name,
                "duration": elapsed,
                "eval_count": total_eval_count,
                "chunks": num_chunks
            })
            
            if verbose or num_chunks > 1:
                print(f"  > Saved to {out_file}")
                print(f"  > Time: {elapsed:.2f}s | Tokens: {total_eval_count} | Chunks: {num_chunks}")
            
        except requests.exceptions.ConnectionError:
            print(f"\nError: Could not connect to Ollama at {api_url}. Is it running?")
            break
        except Exception as e:
            print(f"\nError processing {txt_file.name}: {e}")

    save_performance_report(metrics, output_path)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate COBOL documentation using Ollama.")
    
    parser.add_argument("input_dir", help="Directory containing graph_to_text output .txt files")
    parser.add_argument("--output-dir", help="Directory to save generated markdown (default: auto-inferred sibling directory)")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Ollama model to use (default: {DEFAULT_MODEL})")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Ollama API port (default: {DEFAULT_PORT})")
    parser.add_argument("--prompt-file", help="Path to a text file containing a custom system prompt")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")

    args = parser.parse_args()
    
    prompt = None
    if args.prompt_file:
        try:
            with open(args.prompt_file, "r") as f:
                prompt = f.read()
        except Exception as e:
            print(f"Error reading prompt file: {e}")
            sys.exit(1)

    generate_documentation(args.input_dir, args.output_dir, args.model, args.port, prompt, args.verbose)

