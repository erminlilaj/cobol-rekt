import argparse
import hashlib
import json
import re
import sys
import time
import datetime
from pathlib import Path

import requests

# ==============================================================================
# LLM CONFIGURATION - Single Source of Truth
# This file owns all Ollama model/port/endpoint settings.
# analyze.sh calls this script directly without duplicating config.
# ==============================================================================
DEFAULT_MODEL = "granite-code:8b"
DEFAULT_HOST = "localhost"
DEFAULT_PORT = 11434
# Chunking settings — raised to 200 after prompt trim (substep 2.4)
MAX_CHUNK_LINES = 200  # Max lines per chunk
CHUNK_OVERLAP_LINES = 5  # Overlap to maintain context between chunks

# ==============================================================================
# Prompts — trimmed to 3 RAG-relevant sections (substep 2.2)
# Original 6-section prompt kept as FULL_PROMPT for reference.
# ==============================================================================

DEFAULT_PROMPT = """
You are a Mainframe Modernization Architect performing static analysis on COBOL programs.
Analyze the provided Control Flow Graph (CFG) and code snippets.

ANALYSIS REQUIREMENTS:

1.  **Summary**: Provide a 1-2 sentence description of what this program/section does.
2.  **Business Rules**: Translate conditional logic into declarative IF-THEN rules.
    - Identify validation patterns and cross-field dependencies.
3.  **External Dependencies**:
    - List all CALL statements with their USING parameters.
    - Identify embedded SQL (EXEC SQL) or CICS (EXEC CICS) blocks.

OUTPUT FORMAT (Markdown):

## [PARAGRAPH-NAME] Technical Analysis

### Summary
<1-2 sentence purpose>

### Extracted Business Rules
1. <Rule as IF-THEN statement>
2. ...

### External Interactions
- **Calls**: <List with parameters>
- **DB/CICS**: <Statements if any>

INPUT CONTEXT:
"""

FULL_PROMPT = """
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

# Simpler prompt for individual chunks (faster processing)
CHUNK_PROMPT = """
Analyze this COBOL code section and provide:
1. **Summary**: What does this section do?
2. **Business Rules**: Translate conditions to simple IF-THEN rules
3. **External Calls**: List CALLs, SQL, or CICS operations

Keep response concise. Format as Markdown.

CODE:
"""


# ==============================================================================
# Cache helpers (substep 2.1)
# Cache key includes both the chunk content and the model name so that changing
# the model automatically invalidates all cached entries.
# ==============================================================================

def _cache_key(chunk: str, model: str) -> str:
    return hashlib.sha256(f"{model}:{chunk}".encode()).hexdigest()


def _cache_path(output_dir: Path, stem: str) -> Path:
    return output_dir / f"{stem}.cache.json"


def _load_cache(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding='utf-8'))
        except Exception:
            return {}
    return {}


def _save_cache(path: Path, cache: dict) -> None:
    path.write_text(json.dumps(cache, indent=2), encoding='utf-8')


# ==============================================================================
# Structured extraction (substep 2.3)
# Post-processes free-form Markdown to extract the 3 RAG-relevant fields.
# ==============================================================================

def _extract_structured(text: str) -> dict:
    """
    Extract summary, business_rules, external_calls from Markdown output.
    Handles both ### heading style and **bold:** inline style.
    Returns a dict with keys: summary, business_rules, external_calls.
    Empty string when a section is absent.
    """
    def _section(pattern: str) -> str:
        m = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        return m.group(1).strip() if m else ''

    summary = _section(r'###\s*Summary\s*\n(.*?)(?=###|##|\Z)')
    if not summary:
        summary = _section(r'\*\*Summary:\*\*\s*(.*?)(?=\n\*\*|\Z)')

    business_rules = _section(r'###\s*(?:Extracted\s+)?Business Rules\s*\n(.*?)(?=###|##|\Z)')
    if not business_rules:
        business_rules = _section(r'\*\*Business Rules:\*\*\s*(.*?)(?=\n\*\*|\Z)')

    external_calls = _section(
        r'###\s*External\s+(?:Interactions|Calls|Dependencies)\s*\n(.*?)(?=###|##|\Z)')
    if not external_calls:
        external_calls = _section(r'\*\*External\s+(?:Calls|Dependencies):\*\*\s*(.*?)(?=\n\*\*|\Z)')

    return {
        'summary': summary,
        'business_rules': business_rules,
        'external_calls': external_calls,
    }


# ==============================================================================
# Performance reporting
# ==============================================================================

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

        f.write("| File | Time (s) | Tokens | Speed (t/s) | Cached |\n")
        f.write("|------|----------|--------|-------------|--------|\n")

        for entry in metrics["files"]:
            speed = entry["eval_count"] / entry["duration"] if entry["duration"] > 0 else 0
            cached = entry.get("cached_chunks", 0)
            f.write(f"| {entry['filename']} | {entry['duration']:.2f} | "
                    f"{entry['eval_count']} | {speed:.2f} | {cached} |\n")

    print(f"\nPerformance report saved to: {report_file}")


# ==============================================================================
# Chunking
# ==============================================================================

def chunk_content(content: str, max_lines: int = MAX_CHUNK_LINES,
                  overlap: int = CHUNK_OVERLAP_LINES) -> list[str]:
    """
    Split large content into smaller chunks that fit within the model's context.
    Tries to split at natural boundaries (empty lines, paragraph markers).
    """
    lines = content.split('\n')

    if len(lines) <= max_lines:
        return [content]

    chunks = []
    start = 0

    while start < len(lines):
        end = min(start + max_lines, len(lines))

        if end < len(lines):
            for i in range(end, max(start + max_lines - 20, start), -1):
                line = lines[i].strip()
                if line == '' or line.startswith('Paragraph:') or \
                        line.startswith('Node:') or line.startswith('---'):
                    end = i
                    break

        chunks.append('\n'.join(lines[start:end]))
        start = end - overlap if end < len(lines) else end

    return chunks


# ==============================================================================
# Main generation loop
# ==============================================================================

def generate_documentation(input_dir, output_dir, model, port,
                            prompt_override=None, verbose=False):
    input_path = Path(input_dir)

    if output_dir:
        output_path = Path(output_dir)
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

    metrics = {"model": model, "files": []}

    for txt_file in sorted(files):
        print(f"Processing: {txt_file.name}")

        start_time = time.time()
        stem = txt_file.stem

        # Load per-file cache (substep 2.1)
        cache_file = _cache_path(output_path, stem)
        cache = _load_cache(cache_file)
        cached_chunks = 0

        try:
            content = txt_file.read_text(encoding='utf-8', errors='replace')

            chunks = chunk_content(content)
            num_chunks = len(chunks)

            if num_chunks > 1:
                print(f"  Large file ({len(content.splitlines())} lines) "
                      f"— splitting into {num_chunks} chunks")

            all_responses = []
            total_eval_count = 0

            for chunk_idx, chunk in enumerate(chunks):
                chunk_header = f"\n[Chunk {chunk_idx + 1}/{num_chunks}]\n" if num_chunks > 1 else ""

                # Choose prompt for this chunk
                if num_chunks > 1:
                    full_prompt_for_chunk = f"{CHUNK_PROMPT}\n\n{chunk}"
                else:
                    full_prompt_for_chunk = f"{prompt_template}\n\n{chunk}"

                # Cache lookup (substep 2.1)
                ck = _cache_key(full_prompt_for_chunk, model)
                if ck in cache:
                    if verbose:
                        print(f"  Chunk {chunk_idx + 1}/{num_chunks}: using cached response")
                    all_responses.append(chunk_header + cache[ck])
                    cached_chunks += 1
                    continue

                if verbose:
                    print(f"  Sending request to {api_url}...")
                elif num_chunks > 1:
                    print(f"  Processing chunk {chunk_idx + 1}/{num_chunks}...")

                payload = {
                    "model": model,
                    "prompt": full_prompt_for_chunk,
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

                # Save to cache (substep 2.1)
                cache[ck] = chunk_response
                _save_cache(cache_file, cache)

                all_responses.append(chunk_header + chunk_response)

            # Combine all chunk responses
            full_response_text = "\n".join(all_responses)

            if num_chunks > 1:
                print(f"  Combined {num_chunks} chunks, total {total_eval_count} tokens"
                      f" ({cached_chunks} from cache)")

            # Save Markdown output
            out_file = output_path / f"{stem}_doc.md"
            with open(out_file, "w") as out:
                out.write(f"# Documentation for {stem}\n\n")
                if num_chunks > 1:
                    out.write(f"> *Generated from {num_chunks} chunks.*\n\n")
                out.write(full_response_text)

            # Post-process: extract structured fields (substep 2.3)
            structured = _extract_structured(full_response_text)
            structured_file = output_path / f"{stem}.structured.json"
            structured_file.write_text(
                json.dumps(structured, indent=2, ensure_ascii=False),
                encoding='utf-8')

            elapsed = time.time() - start_time

            metrics["files"].append({
                "filename": txt_file.name,
                "duration": elapsed,
                "eval_count": total_eval_count,
                "chunks": num_chunks,
                "cached_chunks": cached_chunks,
            })

            if verbose or num_chunks > 1:
                print(f"  > Saved: {out_file.name}, {structured_file.name}")
                print(f"  > Time: {elapsed:.2f}s | Tokens: {total_eval_count} | "
                      f"Chunks: {num_chunks} | Cached: {cached_chunks}")

        except requests.exceptions.ConnectionError:
            print(f"\nError: Could not connect to Ollama at {api_url}. Is it running?")
            break
        except Exception as e:
            print(f"\nError processing {txt_file.name}: {e}")

    save_performance_report(metrics, output_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate COBOL documentation using Ollama.")

    parser.add_argument("input_dir",
                        help="Directory containing graph_to_text output .txt files")
    parser.add_argument("--output-dir",
                        help="Directory to save generated markdown (default: auto-inferred)")
    parser.add_argument("--model", default=DEFAULT_MODEL,
                        help=f"Ollama model to use (default: {DEFAULT_MODEL})")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help=f"Ollama API port (default: {DEFAULT_PORT})")
    parser.add_argument("--prompt-file",
                        help="Path to a text file containing a custom system prompt")
    parser.add_argument("--full-prompt", action="store_true",
                        help="Use the full 6-section prompt instead of the trimmed 3-section default")
    parser.add_argument("--verbose", action="store_true",
                        help="Enable verbose logging")

    args = parser.parse_args()

    prompt = None
    if args.prompt_file:
        try:
            prompt = Path(args.prompt_file).read_text()
        except Exception as e:
            print(f"Error reading prompt file: {e}")
            sys.exit(1)
    elif args.full_prompt:
        prompt = FULL_PROMPT

    generate_documentation(args.input_dir, args.output_dir, args.model,
                           args.port, prompt, args.verbose)
