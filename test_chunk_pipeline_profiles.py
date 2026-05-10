#!/usr/bin/env python3
"""Stage 5 (D6) contract tests — chunk pipeline retrieval profiles.

Run: python3 -m unittest test_chunk_pipeline_profiles.py
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import chunk_pipeline
from chunk_pipeline import load_json


def _write_profile_fixture(root: Path) -> Path:
    report_dir = root / "PROFILE.CBL.report"
    kb_dir = report_dir / "knowledge_base"
    cfg_dir = report_dir / "cfg"
    ds_dir = report_dir / "data_structures"
    kb_dir.mkdir(parents=True)
    cfg_dir.mkdir()
    ds_dir.mkdir()
    (kb_dir / "00_Executive_Summary.md").write_text(
        "| Metric | Value |\n"
        "|---|---|\n"
        "| Total CFG Nodes | 4 |\n"
        "| Total Edges | 3 |\n"
        "| Variables Defined | 2 |\n"
        "| Complexity Score | 1 |\n",
        encoding="utf-8",
    )
    (kb_dir / "01_Logic_Narrative.md").write_text(
        "## Program Overview\n"
        "Profile fixture overview.\n\n"
        "## PROCESS-MAIN\n"
        "- `MOVE 'A' TO WS-FIELD.`\n"
        "- `PERFORM PROCESS-DETAIL.`\n"
        "This paragraph has enough words for the paragraph logic chunk to be "
        "indexable and stable in the default profile test case.\n\n"
        "## PROCESS-DETAIL\n"
        "- `DISPLAY WS-FIELD.`\n"
        "This paragraph has enough words for a second stable paragraph logic "
        "chunk in the default profile test case.\n",
        encoding="utf-8",
    )
    (kb_dir / "03_Dependencies.yaml").write_text(
        "program: PROFILE.CBL\ncalls: []\n",
        encoding="utf-8",
    )
    chunk_pipeline._atomic_write_json(
        cfg_dir / "cfg-PROFILE.CBL.json",
        {
            "nodes": [
                {"id": "p1", "type": "PARAGRAPH", "name": "PROCESS-MAIN"},
                {"id": "p2", "type": "PARAGRAPH", "name": "PROCESS-DETAIL"},
                {"id": "s1", "type": "STATEMENT", "name": "MOVE"},
                {"id": "s2", "type": "STATEMENT", "name": "DISPLAY"},
            ],
            "edges": [
                {"fromNodeID": "p1", "toNodeID": "s1", "edgeType": "STARTS_WITH"},
                {"fromNodeID": "p2", "toNodeID": "s2", "edgeType": "STARTS_WITH"},
                {
                    "fromNodeID": "s1",
                    "toNodeID": "p2",
                    "edgeType": "JUMPS_TO",
                    "toLabel": "PROCESS-DETAIL",
                    "evidence": "PERFORM PROCESS-DETAIL",
                },
            ],
        },
    )
    chunk_pipeline._atomic_write_json(
        ds_dir / "PROFILE.CBL-data.json",
        {
            "children": [
                {
                    "levelNumber": 1,
                    "name": "PROFILE-REC",
                    "sourceSection": "WORKING_STORAGE",
                    "children": [
                        {"levelNumber": 5, "name": "WS-FIELD", "rawText": "05 WS-FIELD PIC X."}
                    ],
                }
            ],
        },
    )
    return report_dir


def _type_counts(report_dir: Path) -> dict[str, int]:
    manifest = load_json(report_dir / "chunks" / "chunks_manifest.json")
    return manifest["type_counts"]


class ChunkPipelineProfilesTest(unittest.TestCase):

    def setUp(self) -> None:
        chunk_pipeline.set_token_counter("whitespace")

    def test_default_profile_emits_paragraph_logic(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            report_dir = _write_profile_fixture(Path(td))

            chunk_pipeline.run_pipeline(report_dir, profile="default")

            self.assertEqual(2, _type_counts(report_dir)["paragraph_logic"])

    def test_facts_only_profile_omits_paragraph_logic(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            report_dir = _write_profile_fixture(Path(td))

            chunk_pipeline.run_pipeline(report_dir, profile="facts-only")

            counts = _type_counts(report_dir)
            self.assertEqual(0, counts.get("paragraph_logic", 0))
            self.assertEqual(0, counts.get("section_summary", 0))
            self.assertEqual(0, counts.get("workflow", 0))

    def test_facts_only_profile_emits_program_summary(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            report_dir = _write_profile_fixture(Path(td))

            chunk_pipeline.run_pipeline(report_dir, profile="facts-only")

            self.assertEqual(1, _type_counts(report_dir)["program_summary"])

    def test_facts_only_profile_emits_variable_group(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            report_dir = _write_profile_fixture(Path(td))

            chunk_pipeline.run_pipeline(report_dir, profile="facts-only")

            self.assertEqual(1, _type_counts(report_dir)["variable_group"])

    def test_manifest_records_profile_field(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            report_dir = _write_profile_fixture(Path(td))

            chunk_pipeline.run_pipeline(report_dir, profile="facts-only")

            manifest = load_json(report_dir / "chunks" / "chunks_manifest.json")
            self.assertEqual("facts-only", manifest["profile"])


if __name__ == "__main__":
    unittest.main()
