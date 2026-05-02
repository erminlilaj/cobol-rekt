#!/usr/bin/env python3
"""Regression tests for chunk_pipeline.py."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import chunk_pipeline
import validate_chunks
from chunk_pipeline import (
    _split_if_needed,
    generate_bm25_index,
    generate_cics_operations,
    generate_cobol_analysis_health,
    generate_dependencies,
    generate_manifest,
    generate_static_values,
    generate_variable_groups,
    split_bpe_text,
    token_count,
    write_chunk,
)


class ChunkPipelineTest(unittest.TestCase):
    def setUp(self) -> None:
        self._min_tokens = chunk_pipeline.MIN_CHUNK_TOKENS
        self._max_tokens = chunk_pipeline.MAX_CHUNK_TOKENS
        self._overlap_tokens = chunk_pipeline.OVERLAP_TOKENS
        chunk_pipeline.MIN_CHUNK_TOKENS = 80
        chunk_pipeline.MAX_CHUNK_TOKENS = 45
        chunk_pipeline.OVERLAP_TOKENS = 5

    def tearDown(self) -> None:
        chunk_pipeline.MIN_CHUNK_TOKENS = self._min_tokens
        chunk_pipeline.MAX_CHUNK_TOKENS = self._max_tokens
        chunk_pipeline.OVERLAP_TOKENS = self._overlap_tokens

    def test_split_bpe_never_exceeds_limit(self) -> None:
        text = " ".join(f"CUSTOMER-FIELD-{i:04d}" for i in range(250))

        parts = split_bpe_text(text, 45, 5)

        self.assertGreater(len(parts), 1)
        self.assertTrue(all(token_count(part) <= 45 for part in parts))

    def test_structural_split_preserves_header(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            chunks_dir = Path(td)
            text = "# SECTION A\n\n" + "\n".join(
                f"- FIELD-{i:04d} moves CUSTOMER-FIELD-{i:04d} into TARGET-{i:04d}."
                for i in range(80)
            )
            write_chunk(
                chunks_dir,
                "PROG__section__A.json",
                text,
                {
                    "chunk_type": "section_summary",
                    "chunk_id": "PROG:section_summary:A",
                    "program": "PROG",
                    "section": "A",
                },
            )

            stats = {"split": 0}
            _split_if_needed(chunks_dir / "PROG__section__A.json", chunks_dir, stats, False)
            parts = sorted(chunks_dir.glob("PROG__section__A__part*.json"))

            self.assertEqual(1, stats["split"])
            self.assertGreater(len(parts), 1)
            first_text = chunk_pipeline.load_json(parts[0])["text"]
            self.assertTrue(first_text.startswith("# SECTION A"))
            for part in parts[1:]:
                data = chunk_pipeline.load_json(part)
                self.assertTrue(data["text"].startswith("## Continued section: SECTION A"))
                self.assertLessEqual(token_count(data["text"]), 45)

    def test_manifest_after_split_matches_files(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            report_dir = Path(td) / "PROG.CBL.report"
            chunks_dir = report_dir / "chunks"
            chunks_dir.mkdir(parents=True)
            text = " ".join(f"PAYLOAD-{i:04d}" for i in range(200))
            write_chunk(
                chunks_dir,
                "PROG__workflow__MAIN.json",
                text,
                {
                    "chunk_type": "workflow",
                    "chunk_id": "PROG:workflow:MAIN",
                    "program": "PROG",
                    "paragraph": "MAIN",
                },
            )

            stats = {"split": 0}
            _split_if_needed(chunks_dir / "PROG__workflow__MAIN.json", chunks_dir, stats, False)
            write_chunk(
                chunks_dir,
                "PROG__program_summary.json",
                "Program summary references the original workflow id.",
                {
                    "chunk_type": "program_summary",
                    "chunk_id": "PROG:program_summary",
                    "program": "PROG",
                    "calls": ["PROG:workflow:MAIN"],
                },
            )
            manifest = generate_manifest(chunks_dir, False)
            chunk_files = [
                p for p in chunks_dir.glob("*.json")
                if p.name not in {"chunks_manifest.json", "bm25_index.json"}
            ]
            validation = validate_chunks.validate(report_dir.parent, Path(td) / "missing-index.json", 45, False)

            self.assertEqual(len(chunk_files), manifest["total_chunks"])
            self.assertEqual(0, len(validation["token_warnings"]))
            self.assertEqual([], validation["xref_errors"])
            self.assertLessEqual(validation["max_token_count"], 45)

    def test_health_thin_chunk_remains_indexable(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            chunks_dir = Path(td)
            write_chunk(
                chunks_dir,
                "PROG__analysis_health.json",
                "OK",
                {
                    "chunk_type": "cobol_analysis_health",
                    "chunk_id": "PROG:cobol_analysis_health",
                    "program": "PROG",
                },
            )
            data = chunk_pipeline.load_json(chunks_dir / "PROG__analysis_health.json")

            self.assertTrue(data["metadata"]["indexable"])
            self.assertFalse(data["metadata"]["thin_chunk"])
            self.assertEqual("1.4", data["metadata"]["schema_version"])

    def test_dependency_negative_evidence_stays_indexable(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            report_dir = Path(td) / "NODEPS.CBL.report"
            chunks_dir = report_dir / "chunks"
            chunks_dir.mkdir(parents=True)
            kb_dir = report_dir / "knowledge_base"
            kb_dir.mkdir()
            (kb_dir / "03_Dependencies.yaml").write_text(
                "database:\n  tables_read: []\n  tables_updated: []\n  sql_statements: []\n"
                "calls: []\ncics: []\ncics_calls: []\n",
                encoding="utf-8",
            )

            count = generate_dependencies(report_dir, chunks_dir, "NODEPS.CBL", False)
            data = chunk_pipeline.load_json(chunks_dir / "NODEPS.CBL__dependencies.json")

            self.assertEqual(1, count)
            self.assertTrue(data["metadata"]["thin_chunk"])
            self.assertTrue(data["metadata"]["indexable"])

    def test_bm25_skips_non_indexable_thin_chunks(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            chunks_dir = Path(td)
            write_chunk(
                chunks_dir,
                "PROG__variable_group__A.json",
                "tiny",
                {
                    "chunk_type": "variable_group",
                    "chunk_id": "PROG:variable_group:A",
                    "program": "PROG",
                    "group_name": "A",
                },
            )

            entries = generate_bm25_index(chunks_dir, False)

            self.assertEqual(0, entries)

    def test_adjacent_tiny_variable_groups_merge(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            report_dir = Path(td) / "TINY.CBL.report"
            chunks_dir = report_dir / "chunks"
            chunks_dir.mkdir(parents=True)
            ds_dir = report_dir / "data_structures"
            ds_dir.mkdir()
            chunk_pipeline._atomic_write_json(ds_dir / "TINY.CBL-data.json", {
                "children": [
                    {
                        "levelNumber": 1,
                        "name": "REC-A",
                        "sourceSection": "WORKING_STORAGE",
                        "children": [{"levelNumber": 5, "name": "FIELD-A", "rawText": "05 FIELD-A PIC X."}],
                    },
                    {
                        "levelNumber": 1,
                        "name": "REC-B",
                        "sourceSection": "WORKING_STORAGE",
                        "children": [{"levelNumber": 5, "name": "FIELD-B", "rawText": "05 FIELD-B PIC X."}],
                    },
                ],
            })

            count = generate_variable_groups(report_dir, chunks_dir, "TINY.CBL", False)
            files = sorted(chunks_dir.glob("TINY.CBL__variable_group__*.json"))
            data = chunk_pipeline.load_json(files[0])

            self.assertEqual(1, count)
            self.assertEqual(1, len(files))
            self.assertEqual(["REC-A", "REC-B"], data["metadata"]["group_names"])
            self.assertIn("FIELD-A", data["text"])
            self.assertIn("FIELD-B", data["text"])

    def test_prog_complex_cics_operations_chunk_targets(self) -> None:
        report = Path("out/report/PROG_COMPLEX.CBL.report")
        if not report.exists():
            self.skipTest("PROG_COMPLEX report is not available")
        with tempfile.TemporaryDirectory() as td:
            chunks_dir = Path(td)

            count = generate_cics_operations(report, chunks_dir, "PROG_COMPLEX.CBL", False)
            data = chunk_pipeline.load_json(chunks_dir / "PROG_COMPLEX.CBL__cics_operations.json")

            self.assertEqual(1, count)
            self.assertEqual("cics_operations", data["metadata"]["chunk_type"])
            self.assertEqual(
                {"CICS_TARGET_A", "CICS_TARGET_B", "CICS_TARGET_C", "CICS_TARGET_D"},
                set(data["metadata"]["cics_call_targets"]),
            )

    def test_no_cics_program_emits_no_cics_operations_chunk(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            report_dir = Path(td) / "NOCICS.CBL.report"
            chunks_dir = report_dir / "chunks"
            chunks_dir.mkdir(parents=True)
            kb_dir = report_dir / "knowledge_base"
            kb_dir.mkdir()
            (kb_dir / "03_Dependencies.yaml").write_text(
                "database:\n  tables_read: []\n  tables_updated: []\n  sql_statements: []\n"
                "calls: []\ncics: []\ncics_calls: []\n",
                encoding="utf-8",
            )

            count = generate_cics_operations(report_dir, chunks_dir, "NOCICS.CBL", False)

            self.assertEqual(0, count)
            self.assertEqual([], list(chunks_dir.glob("*cics_operations*.json")))

    def test_dependencies_chunk_includes_structured_cics_resources(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            report_dir = Path(td) / "RES.CBL.report"
            chunks_dir = report_dir / "chunks"
            kb_dir = report_dir / "knowledge_base"
            chunks_dir.mkdir(parents=True)
            kb_dir.mkdir()
            (kb_dir / "03_Dependencies.yaml").write_text(
                "\n".join([
                    "program: RES.CBL",
                    "cics:",
                    "- WRITEQ",
                    "- SEND",
                    "cics_operations:",
                    "- command: WRITEQ",
                    "  type: queue_write",
                    "  target_kind: QUEUE",
                    "  target: TWCOB-TS-CODA",
                    "  target_source: identifier",
                    "- command: SEND",
                    "  type: other",
                    "  target_kind: MAP",
                    "  target: PDB3051",
                    "  target_source: literal",
                ]),
                encoding="utf-8",
            )

            count = generate_dependencies(report_dir, chunks_dir, "RES.CBL", False)
            data = chunk_pipeline.load_json(chunks_dir / "RES.CBL__dependencies.json")

            self.assertEqual(1, count)
            self.assertIn("CICS resources: QUEUE TWCOB-TS-CODA, MAP PDB3051.", data["text"])
            self.assertEqual(
                [
                    {
                        "target_kind": "QUEUE",
                        "target": "TWCOB-TS-CODA",
                        "target_source": "identifier",
                    },
                    {
                        "target_kind": "MAP",
                        "target": "PDB3051",
                        "target_source": "literal",
                    },
                ],
                data["metadata"]["cics_resources"],
            )

    def test_static_values_chunk_aggregates_variable_values(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            report_dir = Path(td) / "VALUES.CBL.report"
            chunks_dir = report_dir / "chunks"
            chunks_dir.mkdir(parents=True)
            chunk_pipeline._atomic_write_json(report_dir / "variable_values.json", [
                ["WABEND-CODE", ["'BR00'", "'AV05'"]],
                ["TWCOB-FASE", ["'1'", "'2'"]],
            ])

            count = generate_static_values(report_dir, chunks_dir, "VALUES.CBL", False)
            data = chunk_pipeline.load_json(chunks_dir / "VALUES.CBL__static_values.json")

            self.assertEqual(1, count)
            self.assertEqual("static_values", data["metadata"]["chunk_type"])
            self.assertTrue(data["metadata"]["indexable"])
            self.assertEqual(["TWCOB-FASE", "WABEND-CODE"], data["metadata"]["variables"])
            self.assertIn("- WABEND-CODE: 'BR00', 'AV05'", data["text"])

    def test_analysis_health_includes_self_evaluation_when_available(self) -> None:
        report = Path("out/report/PROG_SIMPLE.cbl.report")
        if not (report / "analysis_self_evaluation.json").exists():
            self.skipTest("PROG_SIMPLE self-evaluation artifact is not available")
        with tempfile.TemporaryDirectory() as td:
            chunks_dir = Path(td)

            count = generate_cobol_analysis_health(report, chunks_dir, "PROG_SIMPLE.cbl", False)
            data = chunk_pipeline.load_json(chunks_dir / "PROG_SIMPLE.cbl__analysis_health.json")

            self.assertEqual(1, count)
            self.assertEqual(100, data["metadata"]["confidence_score"])
            self.assertEqual("high", data["metadata"]["confidence_label"])
            self.assertEqual(100.0, data["metadata"]["typed_node_ratio"])
            self.assertIn("Self-evaluation confidence score: 100/100 (high).", data["text"])

    def test_analysis_health_tolerates_missing_self_evaluation(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            report_dir = Path(td) / "NOSELF.CBL.report"
            chunks_dir = report_dir / "chunks"
            chunks_dir.mkdir(parents=True)
            chunk_pipeline._atomic_write_json(report_dir / "analysis_health.json", {
                "base_analysis_succeeded": True,
                "mode": "strict",
                "completed_tasks": ["BUILD_BASE_ANALYSIS"],
                "failed_tasks": [],
            })

            count = generate_cobol_analysis_health(report_dir, chunks_dir, "NOSELF.CBL", False)
            data = chunk_pipeline.load_json(chunks_dir / "NOSELF.CBL__analysis_health.json")

            self.assertEqual(1, count)
            self.assertNotIn("confidence_score", data["metadata"])
            self.assertNotIn("typed_node_ratio", data["metadata"])

    def test_validate_fails_over_limit_indexable_chunk(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            report_dir = Path(td) / "BIG.CBL.report"
            chunks_dir = report_dir / "chunks"
            chunks_dir.mkdir(parents=True)
            write_chunk(
                chunks_dir,
                "BIG__program_summary.json",
                " ".join(f"TOKEN{i}" for i in range(80)),
                {
                    "chunk_type": "program_summary",
                    "chunk_id": "BIG:program_summary",
                    "program": "BIG",
                },
            )
            generate_manifest(chunks_dir, False)

            validation = validate_chunks.validate(report_dir.parent, Path(td) / "missing-index.json", 45, False)

            self.assertEqual(1, len(validation["token_errors"]))
            self.assertEqual(0, len(validation["token_warnings"]))

    def test_validate_warns_over_limit_non_indexable_chunk(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            report_dir = Path(td) / "BIGSKIP.CBL.report"
            chunks_dir = report_dir / "chunks"
            chunks_dir.mkdir(parents=True)
            text = " ".join(f"TOKEN{i}" for i in range(80))
            write_chunk(
                chunks_dir,
                "BIGSKIP__variable_group__A.json",
                text,
                {
                    "chunk_type": "variable_group",
                    "chunk_id": "BIGSKIP:variable_group:A",
                    "program": "BIGSKIP",
                    "group_name": "A",
                    "indexable": False,
                },
            )
            data = chunk_pipeline.load_json(chunks_dir / "BIGSKIP__variable_group__A.json")
            data["metadata"]["indexable"] = False
            chunk_pipeline._atomic_write_json(chunks_dir / "BIGSKIP__variable_group__A.json", data)
            generate_manifest(chunks_dir, False)

            validation = validate_chunks.validate(report_dir.parent, Path(td) / "missing-index.json", 45, False)

            self.assertEqual(0, len(validation["token_errors"]))
            self.assertEqual(1, len(validation["token_warnings"]))

    def test_validate_warns_not_fails_missing_self_eval_fields(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            report_dir = Path(td) / "NOSELF.CBL.report"
            chunks_dir = report_dir / "chunks"
            chunks_dir.mkdir(parents=True)
            write_chunk(
                chunks_dir,
                "NOSELF__analysis_health.json",
                "Analysis health without self eval.",
                {
                    "chunk_type": "cobol_analysis_health",
                    "chunk_id": "NOSELF:analysis_health",
                    "program": "NOSELF",
                },
            )
            generate_manifest(chunks_dir, False)

            validation = validate_chunks.validate(report_dir.parent, Path(td) / "missing-index.json", 45, False)

            self.assertEqual([], validation["required_field_errors"])
            self.assertEqual([], validation["token_errors"])
            self.assertTrue(any("MISSING_SELF_EVAL" in w for w in validation["unknown_type_warnings"]))


if __name__ == "__main__":
    unittest.main()
