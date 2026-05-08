#!/usr/bin/env python3
"""
rag_reranker.py — Re-rank RAG chunks by program proximity and call graph distance.

Consumer-side module. Not part of the chunk generation pipeline.
Operates at retrieval time, not indexing time.

Usage:
    from rag_reranker import rerank

    ranked = rerank(
        query="What does PDCBVC do with the CLAIM table?",
        chunks=retrieved_chunks,          # list of dicts with "metadata" key
        corpus_index_path=Path("out/corpus_index.json"),
        call_graph_path=Path("out/cross_program_calls.json"),
    )
"""

import json
import re
from pathlib import Path


# =============================================================================
# Loading helpers
# =============================================================================

def load_corpus_index(path: Path) -> dict:
    """Load corpus_index.json."""
    return json.loads(path.read_text(encoding="utf-8"))


def load_call_graph(path: Path) -> dict:
    """Load cross_program_calls.json."""
    return json.loads(path.read_text(encoding="utf-8"))


def _bare(name: str) -> str:
    """Strip .CBL/.cbl extension and upper-case for comparison."""
    return re.sub(r'\.[Cc][Bb][Ll]$', '', name).upper()


# =============================================================================
# Query-to-program matching
# =============================================================================

def identify_target_program(query: str, program_names: list[str]) -> str | None:
    """Identify which program the query is about by matching program names.

    Longest match wins to prevent "TEST" from matching "TEST1".
    Returns the original (non-bare) name from program_names, or None.
    """
    query_upper = query.upper()
    for name in sorted(program_names, key=len, reverse=True):
        bare = _bare(name)
        if bare and (bare in query_upper or name.upper() in query_upper):
            return name
    return None


# =============================================================================
# Call graph distance
# =============================================================================

def compute_call_distance(source: str, target: str, programs_map: dict) -> int | None:
    """BFS distance from source to target in call graph. None if unreachable."""
    source_bare = _bare(source)
    target_bare = _bare(target)
    if source_bare not in programs_map or target_bare not in programs_map:
        return None

    visited: set[str] = {source_bare}
    queue: list[tuple[str, int]] = [(source_bare, 0)]
    while queue:
        current, dist = queue.pop(0)
        if current == target_bare:
            return dist
        prog = programs_map.get(current, {})
        for callee in prog.get("calls", []):
            callee_bare = _bare(callee) if isinstance(callee, str) else callee
            if callee_bare not in visited:
                visited.add(callee_bare)
                queue.append((callee_bare, dist + 1))
    return None


# =============================================================================
# Main re-ranking entry point
# =============================================================================

def rerank(
    query: str,
    chunks: list[dict],
    corpus_index_path: Path | None = None,
    call_graph_path: Path | None = None,
    boost_same_program: float = 2.0,
    boost_called_by: float = 1.3,
    boost_calls: float = 1.2,
) -> list[dict]:
    """Re-rank chunks by program proximity to the query subject.

    Each chunk dict must have a 'metadata' key with at least 'program'.
    Optional 'score' key (from initial retrieval) defaults to 1.0.

    Returns the input list sorted by adjusted_score (descending).
    Each chunk gets an 'adjusted_score' key added.

    Args:
        query: The user query string.
        chunks: Retrieved chunks (each a dict with 'metadata').
        corpus_index_path: Path to corpus_index.json for program name lookup.
        call_graph_path: Path to cross_program_calls.json for adjacency.
        boost_same_program: Score multiplier for chunks from the target program.
        boost_called_by: Score multiplier for chunks from programs that call target.
        boost_calls: Score multiplier for chunks from programs called by target.

    Returns:
        Chunks sorted descending by adjusted_score.
    """
    # Load cross-program data
    corpus: dict = {}
    if corpus_index_path and corpus_index_path.exists():
        try:
            corpus = load_corpus_index(corpus_index_path)
        except (json.JSONDecodeError, OSError):
            pass

    call_graph: dict = {}
    programs_map: dict[str, dict] = {}
    if call_graph_path and call_graph_path.exists():
        try:
            call_graph = load_call_graph(call_graph_path)
            programs_map = {_bare(p["name"]): p for p in call_graph.get("programs", [])}
        except (json.JSONDecodeError, OSError):
            pass

    # Collect program names for matching.
    # corpus_index.json has programs as a dict {name: metadata}.
    programs_section = corpus.get("programs", {})
    if isinstance(programs_section, dict):
        program_names = list(programs_section.keys())
    elif isinstance(programs_section, list):
        program_names = [p.get("program", "") for p in programs_section if p.get("program")]
    else:
        program_names = []
    if not program_names:
        # Fall back to names seen in chunk metadata
        program_names = list(dict.fromkeys(
            c.get("metadata", {}).get("program", "") for c in chunks
            if c.get("metadata", {}).get("program")
        ))

    # Identify which program the query is about
    target = identify_target_program(query, program_names)
    if not target:
        # No program match found — return original order with base scores
        for chunk in chunks:
            if "adjusted_score" not in chunk:
                chunk["adjusted_score"] = chunk.get("score", 1.0)
        return chunks

    target_bare = _bare(target)

    # Resolve call-graph neighbourhood of the target program
    target_prog = programs_map.get(target_bare, {})
    calls_set: set[str] = {_bare(c) for c in target_prog.get("calls", [])}
    called_by_set: set[str] = {
        _bare(cb["source"]) if isinstance(cb, dict) else _bare(cb)
        for cb in target_prog.get("called_by", [])
    }

    # Apply score multipliers
    for chunk in chunks:
        meta = chunk.get("metadata", {})
        chunk_program_bare = _bare(meta.get("program", ""))
        base_score = float(chunk.get("score", 1.0))

        if chunk_program_bare == target_bare:
            chunk["adjusted_score"] = base_score * boost_same_program
        elif chunk_program_bare in called_by_set:
            chunk["adjusted_score"] = base_score * boost_called_by
        elif chunk_program_bare in calls_set:
            chunk["adjusted_score"] = base_score * boost_calls
        else:
            chunk["adjusted_score"] = base_score

    return sorted(chunks, key=lambda c: c.get("adjusted_score", 0.0), reverse=True)


# =============================================================================
# CLI (quick sanity test)
# =============================================================================

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python3 rag_reranker.py <query> [corpus_index] [call_graph]")
        sys.exit(0)

    query_str = sys.argv[1]
    corpus_path = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("out/corpus_index.json")
    cg_path = Path(sys.argv[3]) if len(sys.argv) > 3 else Path("out/cross_program_calls.json")

    # Build fake chunks from corpus for demonstration
    fake_chunks: list[dict] = []
    if corpus_path.exists():
        idx = load_corpus_index(corpus_path)
        progs = idx.get("programs", {})
        prog_names = list(progs.keys()) if isinstance(progs, dict) else [p.get("program","") for p in progs]
        for pname in prog_names[:20]:
            fake_chunks.append({
                "metadata": {"program": pname, "chunk_type": "program_summary"},
                "score": 1.0,
                "text": f"Program {pname}",
            })

    ranked = rerank(
        query_str, fake_chunks,
        corpus_index_path=corpus_path,
        call_graph_path=cg_path,
    )
    print(f"Query: {query_str}")
    print(f"Target identified: {identify_target_program(query_str, [c['metadata']['program'] for c in fake_chunks])}")
    print("\nTop 10 chunks by adjusted_score:")
    for c in ranked[:10]:
        print(f"  {c['metadata']['program']:30s}  score={c.get('score',1.0):.2f}  adjusted={c.get('adjusted_score',0.0):.2f}")
