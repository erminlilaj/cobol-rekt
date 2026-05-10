#!/usr/bin/env python3
"""Stage 3 (D4) contract tests — BM25 structured term weights.

Run: python3 -m unittest test_bm25_index.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import chunk_pipeline
from chunk_pipeline import generate_bm25_index, load_json, write_chunk


LONG_TEXT = (
    "PROCESS-MAIN paragraph handles account validation and performs the main "
    "business transaction path with deterministic retrieval evidence for tests."
)


def _write_indexable_chunk(chunks_dir: Path, metadata: dict) -> None:
    write_chunk(
        chunks_dir,
        "TEST__controlflow_cfg__PROCESS-MAIN.json",
        LONG_TEXT,
        {
            "chunk_type": "controlflow.cfg",
            "chunk_id": "TEST:controlflow.cfg:PROCESS-MAIN",
            "program": "TEST",
            **metadata,
        },
    )


def _minimal_report(root: Path) -> Path:
    report_dir = root / "BOOST.CBL.report"
    kb_dir = report_dir / "knowledge_base"
    cfg_dir = report_dir / "cfg"
    ds_dir = report_dir / "data_structures"
    kb_dir.mkdir(parents=True)
    cfg_dir.mkdir()
    ds_dir.mkdir()
    (kb_dir / "00_Executive_Summary.md").write_text(
        "| Metric | Value |\n"
        "|---|---|\n"
        "| Total CFG Nodes | 3 |\n"
        "| Total Edges | 2 |\n"
        "| Variables Defined | 1 |\n"
        "| Complexity Score | 1 |\n",
        encoding="utf-8",
    )
    (kb_dir / "01_Logic_Narrative.md").write_text(
        "## Program Overview\n"
        "Small fixture for BM25 boost testing.\n\n"
        "## PROCESS-MAIN\n"
        "- `MOVE 'A' TO WS-FIELD.`\n"
        "- `PERFORM PROCESS-MAIN.`\n"
        "This paragraph contains enough descriptive retrieval text to remain "
        "indexable while preserving the PROCESS-MAIN label boost assertion.\n",
        encoding="utf-8",
    )
    (kb_dir / "03_Dependencies.yaml").write_text(
        "program: BOOST.CBL\n",
        encoding="utf-8",
    )
    chunk_pipeline._atomic_write_json(
        cfg_dir / "cfg-BOOST.CBL.json",
        {
            "nodes": [
                {"id": "p1", "type": "PARAGRAPH", "name": "PROCESS-MAIN"},
                {"id": "s1", "type": "STATEMENT", "name": "MOVE"},
            ],
            "edges": [
                {
                    "fromNodeID": "p1",
                    "toNodeID": "s1",
                    "edgeType": "STARTS_WITH",
                }
            ],
        },
    )
    chunk_pipeline._atomic_write_json(
        ds_dir / "BOOST.CBL-data.json",
        {
            "children": [
                {
                    "levelNumber": 1,
                    "name": "REC",
                    "sourceSection": "WORKING_STORAGE",
                    "children": [
                        {"levelNumber": 5, "name": "WS-FIELD", "rawText": "05 WS-FIELD PIC X."}
                    ],
                }
            ],
        },
    )
    return report_dir


class Bm25IndexWeightsTest(unittest.TestCase):

    def test_structured_term_weights_emitted_for_each_entry(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            chunks_dir = Path(td)
            _write_indexable_chunk(chunks_dir, {"paragraph": "PROCESS-MAIN"})

            generate_bm25_index(chunks_dir, False, label_boost=1.0)

            index = load_json(chunks_dir / "bm25_index.json")
            self.assertEqual(1, len(index["entries"]))
            for entry in index["entries"]:
                self.assertIn("structured_term_weights", entry)
                self.assertIs(type(entry["structured_term_weights"]), dict)
                self.assertTrue(
                    all(isinstance(k, str) and isinstance(v, float)
                        for k, v in entry["structured_term_weights"].items())
                )

    def test_structured_term_weights_contains_paragraph_label_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            chunks_dir = Path(td)
            _write_indexable_chunk(
                chunks_dir,
                {"search_boost": {"paragraph_labels": ["PROCESS-MAIN"]}},
            )

            generate_bm25_index(chunks_dir, False, label_boost=1.5)

            entry = load_json(chunks_dir / "bm25_index.json")["entries"][0]
            self.assertEqual(1.5, entry["structured_term_weights"]["PROCESS-MAIN"])

    def test_term_freq_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            chunks_dir = Path(td)
            _write_indexable_chunk(
                chunks_dir,
                {"search_boost": {"paragraph_labels": ["PROCESS-MAIN"]}},
            )

            generate_bm25_index(chunks_dir, False, label_boost=1.0)
            baseline_tf = load_json(chunks_dir / "bm25_index.json")["entries"][0]["term_freq"]
            generate_bm25_index(chunks_dir, False, label_boost=2.0)
            boosted_tf = load_json(chunks_dir / "bm25_index.json")["entries"][0]["term_freq"]

            self.assertEqual(baseline_tf, boosted_tf)

    def test_structured_terms_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            chunks_dir = Path(td)
            _write_indexable_chunk(
                chunks_dir,
                {
                    "paragraph": "PROCESS-MAIN",
                    "search_boost": {"paragraph_labels": ["PROCESS-MAIN"]},
                },
            )

            generate_bm25_index(chunks_dir, False, label_boost=1.0)
            baseline_terms = load_json(chunks_dir / "bm25_index.json")["entries"][0]["structured_terms"]
            generate_bm25_index(chunks_dir, False, label_boost=2.0)
            boosted_terms = load_json(chunks_dir / "bm25_index.json")["entries"][0]["structured_terms"]

            self.assertEqual(baseline_terms, boosted_terms)

    def test_label_boost_cli_flag(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            report_dir = _minimal_report(Path(td))

            subprocess.run(
                [
                    sys.executable,
                    "chunk_pipeline.py",
                    str(report_dir),
                    "--label-boost",
                    "2.0",
                    "--token-counter",
                    "whitespace",
                ],
                check=True,
                cwd=Path(__file__).parent,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            index = json.loads((report_dir / "chunks" / "bm25_index.json").read_text(encoding="utf-8"))
            weights_by_id = {
                entry["chunk_id"]: entry["structured_term_weights"]
                for entry in index["entries"]
            }
            self.assertEqual(
                2.0,
                weights_by_id["BOOST.CBL:paragraph_logic:PROCESS-MAIN"]["PROCESS-MAIN"],
            )


if __name__ == "__main__":
    unittest.main()
