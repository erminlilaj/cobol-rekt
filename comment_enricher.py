#!/usr/bin/env python3
"""
comment_enricher.py — Translate and categorize Italian COBOL comments via Ollama.

Reads comments.json (produced by analyze.py Step 7), sends paragraph comments in
batches to a local Ollama model for English translation and semantic categorization,
and writes comments_enriched.json next to the input file.

Usage:
  python3 comment_enricher.py out/report/MYPROGRAM.CBL.report/comments.json
  python3 comment_enricher.py out/report/MYPROGRAM.CBL.report/comments.json \\
      --model granite-code:8b --port 11434 --verbose

Output schema (comments_enriched.json):
  {
    "PARAGRAPH-NAME": {
      "original": ["Italian comment text", ...],
      "english": "Translated and merged English description.",
      "category": "initialization",
      "semantic_label": "Setup and precondition check"
    },
    ...
  }
"""

import argparse
import json
import re
import sys
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_MODEL = "granite-code:8b"
DEFAULT_PORT = 11434
BATCH_SIZE = 15          # Paragraphs per LLM call (keeps output tokens in budget)
REQUEST_TIMEOUT = 120    # seconds

VALID_CATEGORIES = {
    'initialization', 'error_handling', 'main_logic', 'database_access',
    'terminal_io', 'cleanup', 'validation', 'utility',
}

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_BATCH_PROMPT = """\
You are a COBOL documentation assistant. Translate Italian comments into English \
and categorize each paragraph.

For each entry in the JSON input, produce a JSON object with:
  - "english": a concise English description (1-2 sentences) merging all comment lines
  - "category": one of: initialization, error_handling, main_logic, database_access, \
terminal_io, cleanup, validation, utility
  - "semantic_label": 3-5 word label summarizing the purpose

Return ONLY a valid JSON object mapping each paragraph name to its result.
No markdown fences. No explanation. No extra keys.

INPUT:
"""

_SUMMARY_PROMPT = """\
You are a COBOL documentation assistant. This is the program-level summary \
extracted from a COBOL source file.

Translate the following Italian text into a concise English program description \
(2-3 sentences).

Return ONLY a valid JSON object:
{"english": "<description>", "category": "main_logic", "semantic_label": "<3-5 word label>"}

No markdown fences. No explanation.

INPUT:
"""

_RETRY_PROMPT_SUFFIX = "\n\nIMPORTANT: Return ONLY raw JSON. No markdown code fences. No text before or after the JSON object."

# ---------------------------------------------------------------------------
# Ollama helpers
# ---------------------------------------------------------------------------

def check_ollama(port: int) -> bool:
    """Return True if Ollama is reachable at the given port."""
    try:
        r = requests.get(f"http://localhost:{port}/api/tags", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


def list_models(port: int) -> list[str]:
    """Return list of model names available in Ollama."""
    try:
        r = requests.get(f"http://localhost:{port}/api/tags", timeout=3)
        if r.status_code == 200:
            return [m['name'] for m in r.json().get('models', [])]
    except Exception:
        pass
    return []


def pick_model(port: int, preferred: str) -> str:
    """
    Auto-select model: prefer smaller translation-capable models when available,
    fall back to the user-specified model.
    """
    available = list_models(port)
    # Prefer smaller general models for translation — faster and equally capable
    for candidate in ('qwen2.5:3b', 'llama3.2:3b', 'llama3:3b'):
        if any(candidate in m for m in available):
            return candidate
    return preferred


def _call_ollama(prompt: str, model: str, port: int) -> str:
    """Send a prompt to Ollama /api/generate (non-streaming). Returns response text."""
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.1,   # Low temp for deterministic JSON output
            "num_ctx": 8192,
        },
    }
    r = requests.post(
        f"http://localhost:{port}/api/generate",
        json=payload,
        timeout=REQUEST_TIMEOUT,
    )
    r.raise_for_status()
    return r.json().get("response", "")

# ---------------------------------------------------------------------------
# JSON extraction helpers
# ---------------------------------------------------------------------------

def _extract_json(text: str) -> dict | None:
    """
    Try to extract a JSON object from LLM output.
    Strategy:
      1. Direct json.loads() on the full text (ideal case).
      2. Regex to find the outermost { ... } block (handles surrounding prose).
      3. Return None on failure.
    """
    text = text.strip()

    # Strategy 1: direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Strategy 2: extract outermost { ... }
    m = re.search(r'\{.*\}', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass

    return None

# ---------------------------------------------------------------------------
# Core enrichment logic
# ---------------------------------------------------------------------------

def _make_fallback(original: list[str]) -> dict:
    return {
        "original": original,
        "english": " ".join(original),
        "category": "utility",
        "semantic_label": "Translation failed",
        "translation_failed": True,
    }


def _validate_entry(entry: dict) -> bool:
    """Return True if a single enriched entry has the required fields."""
    return (
        isinstance(entry, dict)
        and isinstance(entry.get("english"), str)
        and entry.get("english")
        and isinstance(entry.get("category"), str)
        and isinstance(entry.get("semantic_label"), str)
    )


def _enrich_batch(
    batch: dict[str, list[str]],
    model: str,
    port: int,
    is_summary: bool = False,
    verbose: bool = False,
) -> dict[str, dict]:
    """
    Send one batch of paragraphs to Ollama.
    Returns dict mapping paragraph name → enriched result dict.
    Falls back per-entry on validation failure.
    """
    if is_summary:
        # _PROGRAM_SUMMARY: send each comment line joined
        para_name = list(batch.keys())[0]
        lines = batch[para_name]
        prompt = _SUMMARY_PROMPT + json.dumps(lines, ensure_ascii=False)
    else:
        prompt = _BATCH_PROMPT + json.dumps(batch, ensure_ascii=False, indent=2)

    if verbose:
        names = list(batch.keys())
        print(f"    LLM call: {len(names)} paragraph(s) — {names}")

    # First attempt
    raw = _call_ollama(prompt, model, port)
    parsed = _extract_json(raw)

    # Retry with stricter prompt if parse failed or result is not a dict
    if not isinstance(parsed, dict):
        if verbose:
            print("    JSON parse failed — retrying with strict prompt")
        raw = _call_ollama(prompt + _RETRY_PROMPT_SUFFIX, model, port)
        parsed = _extract_json(raw)

    results: dict[str, dict] = {}

    if is_summary:
        para_name = list(batch.keys())[0]
        original = batch[para_name]
        if isinstance(parsed, dict) and _validate_entry(parsed):
            results[para_name] = {"original": original, **parsed}
        else:
            if verbose:
                print(f"    Fallback for {para_name}")
            results[para_name] = _make_fallback(original)
        return results

    # Normal batch: expect {para_name: {english, category, semantic_label}, ...}
    for para_name, original_lines in batch.items():
        entry = parsed.get(para_name) if isinstance(parsed, dict) else None
        if entry and _validate_entry(entry):
            results[para_name] = {"original": original_lines, **entry}
        else:
            if verbose:
                print(f"    Fallback for {para_name}")
            results[para_name] = _make_fallback(original_lines)

    return results


def enrich_comments(
    comments_json: Path,
    model: str = DEFAULT_MODEL,
    port: int = DEFAULT_PORT,
    verbose: bool = False,
) -> Path:
    """
    Translate and categorize all comments in comments_json.
    Writes <parent>/comments_enriched.json and returns its path.
    Skips paragraphs that already have an entry in an existing output file
    (incremental caching — substep 3.5).
    """
    comments_json = Path(comments_json)
    output_path = comments_json.parent / "comments_enriched.json"

    # Load input
    raw_comments: dict[str, list[str]] = json.loads(
        comments_json.read_text(encoding='utf-8'))

    # Incremental cache: load existing results (substep 3.5)
    existing: dict[str, dict] = {}
    if output_path.exists():
        try:
            existing = json.loads(output_path.read_text(encoding='utf-8'))
        except Exception:
            existing = {}

    # Separate _PROGRAM_SUMMARY from paragraph entries
    summary_raw = raw_comments.get('_PROGRAM_SUMMARY')
    paragraphs: dict[str, list[str]] = {
        k: v for k, v in raw_comments.items()
        if k != '_PROGRAM_SUMMARY' and v  # skip empty comment lists
    }

    # Determine which paragraphs still need processing
    todo_paragraphs = {
        k: v for k, v in paragraphs.items()
        if k not in existing
    }
    todo_summary = summary_raw and '_PROGRAM_SUMMARY' not in existing

    total_todo = len(todo_paragraphs) + (1 if todo_summary else 0)
    total_already = len(existing)

    if verbose:
        print(f"  comments.json: {len(raw_comments)} keys "
              f"({len(paragraphs)} paragraphs + program summary)")
        print(f"  Already enriched: {total_already} | Remaining: {total_todo}")

    if total_todo == 0:
        print("  All paragraphs already enriched. Nothing to do.")
        return output_path

    results = dict(existing)

    # Process _PROGRAM_SUMMARY (substep 3.6)
    if todo_summary and summary_raw:
        if verbose:
            print("  Enriching _PROGRAM_SUMMARY...")
        summary_result = _enrich_batch(
            {'_PROGRAM_SUMMARY': summary_raw},
            model, port,
            is_summary=True,
            verbose=verbose,
        )
        results.update(summary_result)

    # Process paragraphs in batches of BATCH_SIZE (substep 3.3)
    para_names = list(todo_paragraphs.keys())
    total_batches = (len(para_names) + BATCH_SIZE - 1) // BATCH_SIZE

    for batch_idx in range(total_batches):
        start = batch_idx * BATCH_SIZE
        batch_names = para_names[start:start + BATCH_SIZE]
        batch = {n: todo_paragraphs[n] for n in batch_names}

        if verbose:
            print(f"  Batch {batch_idx + 1}/{total_batches} "
                  f"({len(batch_names)} paragraphs)...")

        batch_results = _enrich_batch(batch, model, port, verbose=verbose)
        results.update(batch_results)

        # Write incrementally so progress is not lost on interruption
        output_path.write_text(
            json.dumps(results, indent=2, ensure_ascii=False),
            encoding='utf-8')

    if verbose:
        failed = sum(1 for v in results.values()
                     if isinstance(v, dict) and v.get('translation_failed'))
        print(f"  Done. {len(results)} entries written "
              f"({failed} fallback/failed).")

    return output_path

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(
        description='Translate and categorize Italian COBOL comments via Ollama.')
    ap.add_argument('comments_json',
                    help='Path to comments.json (from analyze.py Step 7)')
    ap.add_argument('--model', default=DEFAULT_MODEL,
                    help=f'Ollama model (default: {DEFAULT_MODEL})')
    ap.add_argument('--port', type=int, default=DEFAULT_PORT,
                    help=f'Ollama port (default: {DEFAULT_PORT})')
    ap.add_argument('--auto-model', action='store_true',
                    help='Auto-select smallest available Ollama model')
    ap.add_argument('--verbose', action='store_true')
    args = ap.parse_args()

    comments_path = Path(args.comments_json)
    if not comments_path.exists():
        print(f'Error: file not found: {comments_path}')
        sys.exit(1)

    # Ollama health check (substep 3.1)
    if not check_ollama(args.port):
        print(f'Error: Ollama not reachable at port {args.port}. '
              f'Start it with: ollama serve')
        sys.exit(1)

    model = pick_model(args.port, args.model) if args.auto_model else args.model

    # Report status
    raw = json.loads(comments_path.read_text(encoding='utf-8'))
    paragraph_count = sum(1 for k, v in raw.items()
                          if k != '_PROGRAM_SUMMARY' and v)
    has_summary = bool(raw.get('_PROGRAM_SUMMARY'))

    print(f'[comment_enricher] {comments_path.name}')
    print(f'  Paragraphs with comments : {paragraph_count}')
    print(f'  Program summary present  : {has_summary}')
    print(f'  Model: {model} | Port: {args.port}')

    if args.verbose:
        print()

    out = enrich_comments(comments_path, model=model, port=args.port,
                          verbose=args.verbose)
    print(f'  Output: {out}')


if __name__ == '__main__':
    main()
