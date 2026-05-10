#!/usr/bin/env python3
"""Stage 2 (D3) contract tests — CICS presentation-level dedup in dependencies chunk.

Run: python3 -m unittest test_chunk_pipeline_cics.py
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import chunk_pipeline
import validate_chunks
from chunk_pipeline import (
    CHUNK_SCHEMA_VERSION,
    PIPELINE_VERSION,
    generate_cics_operation_chunks,
    generate_dependencies,
    load_json,
    write_chunk,
)


def _write_deps_yaml(kb_dir: Path, content: str) -> None:
    kb_dir.mkdir(parents=True, exist_ok=True)
    (kb_dir / "03_Dependencies.yaml").write_text(content, encoding="utf-8")


def _write_cfg(cfg_dir: Path, program: str, nodes: list[dict]) -> None:
    cfg_dir.mkdir(parents=True, exist_ok=True)
    chunk_pipeline._atomic_write_json(
        cfg_dir / f"cfg-{program}.json",
        {"nodes": nodes, "edges": []},
    )


def _cics_node(
    node_id: str,
    command: str,
    op_type: str,
    target: str,
    target_kind: str,
    paragraph: str,
    original_text: str,
) -> dict:
    return {
        "id": node_id,
        "type": "DIALECT",
        "originalText": original_text,
        "metadata": {
            "cics_command": command,
            "cics_operation_type": op_type,
            "cics_target": target,
            "cics_target_kind": target_kind,
            "paragraph": paragraph,
        },
    }


class CicsDepsDedupTest(unittest.TestCase):

    def test_dependencies_chunk_aggregates_repeated_cics_triple(self) -> None:
        """Same CICS triple from 3 paragraphs → exactly one aggregated line."""
        with tempfile.TemporaryDirectory() as td:
            report_dir = Path(td) / "TEST.CBL.report"
            chunks_dir = report_dir / "chunks"
            chunks_dir.mkdir(parents=True)
            _write_deps_yaml(
                report_dir / "knowledge_base",
                "program: TEST.CBL\ncics:\n  - WRITEQ\n",
            )
            _write_cfg(
                report_dir / "cfg",
                "TEST.CBL",
                [
                    _cics_node("n1", "WRITEQ", "resource", "Q1", "QUEUE",
                               "PARA-A", "EXEC CICS WRITEQ TS QUEUE('Q1')"),
                    _cics_node("n2", "WRITEQ", "resource", "Q1", "QUEUE",
                               "PARA-B", "EXEC CICS WRITEQ TS QUEUE('Q1')"),
                    _cics_node("n3", "WRITEQ", "resource", "Q1", "QUEUE",
                               "PARA-C", "EXEC CICS WRITEQ TS QUEUE('Q1')"),
                ],
            )

            generate_dependencies(report_dir, chunks_dir, "TEST.CBL", False)

            chunk = load_json(chunks_dir / "TEST.CBL__dependencies.json")
            text = chunk["text"]
            cics_lines = [ln for ln in text.splitlines() if "WRITEQ" in ln]
            self.assertEqual(1, len(cics_lines),
                             f"Expected exactly one WRITEQ line, got: {cics_lines}")
            self.assertIn("used in 3 paragraph(s): PARA-A, PARA-B, PARA-C",
                          cics_lines[0])

    def test_dependencies_chunk_preserves_handle_condition(self) -> None:
        """HANDLE CONDITION from 2 paragraphs → 2 separate lines, not aggregated."""
        with tempfile.TemporaryDirectory() as td:
            report_dir = Path(td) / "HNDL.CBL.report"
            chunks_dir = report_dir / "chunks"
            chunks_dir.mkdir(parents=True)
            _write_deps_yaml(
                report_dir / "knowledge_base",
                "program: HNDL.CBL\ncics:\n  - HANDLE\n",
            )
            _write_cfg(
                report_dir / "cfg",
                "HNDL.CBL",
                [
                    _cics_node("h1", "HANDLE", "error_handler", "", "UNKNOWN",
                               "MAIN-PARA",
                               "EXEC CICS HANDLE CONDITION ERROR(ERR-HANDLER)"),
                    _cics_node("h2", "HANDLE", "error_handler", "", "UNKNOWN",
                               "PROC-PARA",
                               "EXEC CICS HANDLE CONDITION MAPFAIL(MAP-HANDLER)"),
                ],
            )

            generate_dependencies(report_dir, chunks_dir, "HNDL.CBL", False)

            chunk = load_json(chunks_dir / "HNDL.CBL__dependencies.json")
            text = chunk["text"]
            handle_lines = [ln for ln in text.splitlines() if "HANDLE" in ln]
            self.assertEqual(2, len(handle_lines),
                             f"Expected 2 HANDLE lines (one per paragraph), got: {handle_lines}")
            paragraphs_mentioned = {ln for ln in handle_lines
                                    if "MAIN-PARA" in ln or "PROC-PARA" in ln}
            self.assertEqual(2, len(paragraphs_mentioned),
                             "Each HANDLE line must attribute its own paragraph")

    def test_cics_operation_chunks_untouched_by_deps_aggregation(self) -> None:
        """The cics.operation chunks are generated independently and are unchanged."""
        with tempfile.TemporaryDirectory() as td:
            report_dir = Path(td) / "OP.CBL.report"
            chunks_dir = report_dir / "chunks"
            chunks_dir.mkdir(parents=True)
            _write_deps_yaml(
                report_dir / "knowledge_base",
                "program: OP.CBL\ncics:\n  - LINK\n",
            )
            nodes = [
                _cics_node("c1", "LINK", "program_transfer", "PAYPGM", "PROGRAM",
                           "MAIN-PARA", "EXEC CICS LINK PROGRAM('PAYPGM')"),
                _cics_node("c2", "LINK", "program_transfer", "PAYPGM", "PROGRAM",
                           "PROC-PARA", "EXEC CICS LINK PROGRAM('PAYPGM')"),
            ]
            _write_cfg(report_dir / "cfg", "OP.CBL", nodes)

            generate_cics_operation_chunks(report_dir, chunks_dir, "OP.CBL", False)
            generate_dependencies(report_dir, chunks_dir, "OP.CBL", False)

            # cics.operation chunks must exist and be unaffected by deps generation
            op_chunks = sorted(chunks_dir.glob("OP.CBL__cics_operation__*.json"))
            self.assertGreater(len(op_chunks), 0, "Expected at least one cics.operation chunk")
            for op_chunk_path in op_chunks:
                op_chunk = load_json(op_chunk_path)
                self.assertEqual("cics.operation", op_chunk["metadata"]["chunk_type"])
                # each cics.operation chunk still has command field
                self.assertIn("command", op_chunk["metadata"])

            # dependencies chunk must also exist
            deps_chunk = load_json(chunks_dir / "OP.CBL__dependencies.json")
            self.assertEqual("dependencies", deps_chunk["metadata"]["chunk_type"])

    def test_dependencies_chunk_paragraphs_capped_at_five(self) -> None:
        """When 7 paragraphs use the same CICS triple, list 5 and show '+2 more'."""
        with tempfile.TemporaryDirectory() as td:
            report_dir = Path(td) / "BIG.CBL.report"
            chunks_dir = report_dir / "chunks"
            chunks_dir.mkdir(parents=True)
            _write_deps_yaml(
                report_dir / "knowledge_base",
                "program: BIG.CBL\ncics:\n  - SEND\n",
            )
            nodes = [
                _cics_node(f"n{i}", "SEND", "resource", "MYMAP", "MAP",
                           f"PARA-{i:02d}", "EXEC CICS SEND MAP('MYMAP')")
                for i in range(1, 8)
            ]
            _write_cfg(report_dir / "cfg", "BIG.CBL", nodes)

            generate_dependencies(report_dir, chunks_dir, "BIG.CBL", False)

            chunk = load_json(chunks_dir / "BIG.CBL__dependencies.json")
            text = chunk["text"]
            send_lines = [ln for ln in text.splitlines() if "SEND" in ln]
            self.assertEqual(1, len(send_lines))
            self.assertIn("used in 7 paragraph(s)", send_lines[0])
            self.assertIn("... +2 more", send_lines[0])

    def test_dependencies_chunk_schema_version_is_1_6(self) -> None:
        """Every chunk written after Stage 2 has schema_version == '1.6'."""
        self.assertEqual("1.6", CHUNK_SCHEMA_VERSION)
        self.assertEqual("1.6", PIPELINE_VERSION)
        with tempfile.TemporaryDirectory() as td:
            report_dir = Path(td) / "SCHEMA.CBL.report"
            chunks_dir = report_dir / "chunks"
            chunks_dir.mkdir(parents=True)
            _write_deps_yaml(
                report_dir / "knowledge_base",
                "program: SCHEMA.CBL\n",
            )
            (report_dir / "cfg").mkdir()

            generate_dependencies(report_dir, chunks_dir, "SCHEMA.CBL", False)

            chunk = load_json(chunks_dir / "SCHEMA.CBL__dependencies.json")
            self.assertEqual("1.6", chunk["metadata"]["schema_version"])
            self.assertEqual("1.6", chunk["metadata"]["pipeline_version"])

    def test_validate_chunks_accepts_schema_1_6(self) -> None:
        """validate_chunks.SUPPORTED_SCHEMA_VERSIONS includes '1.6' and raises no warning."""
        self.assertIn("1.6", validate_chunks.SUPPORTED_SCHEMA_VERSIONS)
        with tempfile.TemporaryDirectory() as td:
            chunks_dir = Path(td) / "chunks"
            chunks_dir.mkdir()
            write_chunk(
                chunks_dir,
                "VSCHEMA.CBL__dependencies.json",
                "External dependencies for program VSCHEMA.CBL: No external dependencies detected.",
                {
                    "chunk_type": "dependencies",
                    "chunk_id": "VSCHEMA.CBL:dependencies",
                    "program": "VSCHEMA.CBL",
                },
            )
            chunk_path = chunks_dir / "VSCHEMA.CBL__dependencies.json"
            chunk = load_json(chunk_path)
            meta = chunk["metadata"]
            # schema_version written by write_chunk must be 1.6
            self.assertEqual("1.6", meta["schema_version"])
            # validate_chunks must not flag this version
            warnings: list[str] = []
            validate_chunks._check_schema_version(meta, meta["chunk_id"], warnings)
            self.assertEqual([], warnings,
                             f"Unexpected schema warnings: {warnings}")


if __name__ == "__main__":
    unittest.main()
