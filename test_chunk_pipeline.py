#!/usr/bin/env python3
"""Regression tests for chunk_pipeline.py."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import chunk_pipeline
import validate_chunks
from chunk_pipeline import (
    _split_parts_with_context,
    _split_if_needed,
    clear_existing_chunks,
    generate_bm25_index,
    generate_cics_operations,
    generate_commented_out_code,
    generate_comments,
    generate_cobol_analysis_health,
    generate_copybook_fields,
    generate_copybook_mentions,
    generate_datasets_tables_resources,
    generate_dependencies,
    generate_external_program_calls,
    generate_manifest,
    generate_program_summary,
    generate_rag_bundle,
    generate_static_values,
    generate_variable_groups,
    generate_workflow_chunks,
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

    def test_line_based_split_preserves_static_value_lines(self) -> None:
        text = "Static and forced values for program BIG.CBL:\n" + "\n".join(
            f"- VAR-{i:03d}: 'VALUE-{i:03d}'. Category: parameter setup. Paragraphs: PARA-{i:03d}"
            for i in range(30)
        )

        parts = _split_parts_with_context(text, {"chunk_type": "static_values"})

        self.assertGreater(len(parts), 1)
        self.assertTrue(all(part.startswith("Static and forced values") for part in parts))
        for part in parts:
            for line in part.splitlines()[1:]:
                self.assertTrue(line.startswith("- VAR-"), line)
                self.assertIn("Paragraphs: PARA-", line)
            self.assertLessEqual(token_count(part), 45)

    def test_line_based_split_handles_single_oversized_static_value_line(self) -> None:
        huge_values = ", ".join(f"'VALUE-{i:03d}'" for i in range(140))
        text = (
            "Static and forced values for program HUGE.CBL:\n"
            "- SMALL-VAR: 'A'. Category: initialization. Consumer: unknown\n"
            f"- HUGE-VAR: {huge_values}. Category: initialization. Consumer: unknown"
        )

        parts = _split_parts_with_context(text, {"chunk_type": "static_values"})

        self.assertGreater(len(parts), 1)
        self.assertTrue(all(token_count(part) <= 45 for part in parts))

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

    def test_clear_existing_chunks_removes_stale_json_only(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            chunks_dir = Path(td)
            (chunks_dir / "OLD__paragraph.json").write_text("{}", encoding="utf-8")
            (chunks_dir / "bm25_index.json").write_text("{}", encoding="utf-8")
            (chunks_dir / "notes.txt").write_text("keep", encoding="utf-8")

            removed = clear_existing_chunks(chunks_dir)

            self.assertEqual(2, removed)
            self.assertEqual(["notes.txt"], sorted(p.name for p in chunks_dir.iterdir()))

    def test_run_pipeline_removes_stale_chunks_before_regeneration(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            report_dir = Path(td) / "SAFE.CBL.report"
            chunks_dir = report_dir / "chunks"
            (report_dir / "cfg").mkdir(parents=True)
            chunks_dir.mkdir()
            chunk_pipeline._atomic_write_json(
                chunks_dir / "SAFE.CBL__paragraph_logic__OLD.json",
                {
                    "text": "old paragraph text",
                    "metadata": {
                        "chunk_type": "paragraph_logic",
                        "chunk_id": "SAFE.CBL:paragraph_logic:OLD",
                        "schema_version": "1.3",
                    },
                },
            )
            chunk_pipeline._atomic_write_json(
                chunks_dir / "SAFE.CBL__paragraph_logic__OLD__part001.json",
                {
                    "text": "old split text",
                    "metadata": {
                        "chunk_type": "paragraph_logic",
                        "chunk_id": "SAFE.CBL:paragraph_logic:OLD:part001",
                        "schema_version": "1.3",
                    },
                },
            )
            chunk_pipeline._atomic_write_json(chunks_dir / "chunks_manifest.json", {"schema_version": "1.3"})
            chunk_pipeline._atomic_write_json(chunks_dir / "bm25_index.json", {"entries": ["stale"]})
            (chunks_dir / "notes.txt").write_text("keep me", encoding="utf-8")

            summary = chunk_pipeline.run_pipeline(report_dir, False)

            self.assertGreaterEqual(summary["total"], 1)
            self.assertFalse((chunks_dir / "SAFE.CBL__paragraph_logic__OLD.json").exists())
            self.assertFalse((chunks_dir / "SAFE.CBL__paragraph_logic__OLD__part001.json").exists())
            self.assertTrue((chunks_dir / "notes.txt").exists())

            manifest = chunk_pipeline.load_json(chunks_dir / "chunks_manifest.json")
            self.assertEqual(chunk_pipeline.CHUNK_SCHEMA_VERSION, manifest["schema_version"])
            for chunk_path in chunks_dir.glob("*.json"):
                if chunk_path.name in {"chunks_manifest.json", "bm25_index.json"}:
                    continue
                data = chunk_pipeline.load_json(chunk_path)
                self.assertEqual(chunk_pipeline.CHUNK_SCHEMA_VERSION, data["metadata"]["schema_version"])

    def test_workflow_chunk_includes_callee_cics_commands(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            report_dir = Path(td) / "WF.CBL.report"
            chunks_dir = report_dir / "chunks"
            chunks_dir.mkdir(parents=True)
            write_chunk(
                chunks_dir,
                "WF.CBL__paragraph__A010.json",
                "A010 performs other paragraphs.",
                {
                    "chunk_type": "paragraph_logic",
                    "chunk_id": "WF.CBL:paragraph_logic:A010",
                    "program": "WF.CBL",
                    "paragraph": "A010",
                    "node_count": 4,
                    "calls": ["POPULATE-TIME-DATE", "ABEND-THIS-TASK"],
                },
            )
            write_chunk(
                chunks_dir,
                "WF.CBL__paragraph__POPULATE-TIME-DATE.json",
                "POPULATE-TIME-DATE has no CICS.",
                {
                    "chunk_type": "paragraph_logic",
                    "chunk_id": "WF.CBL:paragraph_logic:POPULATE-TIME-DATE",
                    "program": "WF.CBL",
                    "paragraph": "POPULATE-TIME-DATE",
                    "node_count": 2,
                    "calls": [],
                    "cics_commands": [],
                },
            )
            write_chunk(
                chunks_dir,
                "WF.CBL__paragraph__ABEND-THIS-TASK.json",
                "ABEND-THIS-TASK runs CICS.",
                {
                    "chunk_type": "paragraph_logic",
                    "chunk_id": "WF.CBL:paragraph_logic:ABEND-THIS-TASK",
                    "program": "WF.CBL",
                    "paragraph": "ABEND-THIS-TASK",
                    "node_count": 2,
                    "calls": [],
                    "cics_commands": ["ABEND", "ASSIGN", "SEND", "RETURN"],
                },
            )

            count = generate_workflow_chunks(report_dir, chunks_dir, "WF.CBL", False)
            data = chunk_pipeline.load_json(chunks_dir / "WF.CBL__workflow__A010.json")

            self.assertEqual(1, count)
            self.assertIn("  - ABEND-THIS-TASK (CICS: Abend, Assign, Send)", data["text"])
            self.assertIn("  - POPULATE-TIME-DATE", data["text"])

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
            self.assertEqual("1.5", data["metadata"]["schema_version"])

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

    def test_copybook_mentions_include_lines_and_stub_status(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            report_dir = Path(td) / "COPYTEST.CBL.report"
            chunks_dir = report_dir / "chunks"
            chunks_dir.mkdir(parents=True)
            chunk_pipeline._atomic_write_json(report_dir / "cobol_structure.json", {
                "copy_statements": [
                    {
                        "copybook": "FOO",
                        "line": 12,
                        "division": "DATA",
                        "section": "WORKING-STORAGE",
                        "replacing": None,
                        "impact": "missing variable definitions",
                    },
                    {
                        "copybook": "BAR",
                        "line": 20,
                        "division": "DATA",
                        "section": "LINKAGE",
                        "replacing": "==A== BY ==B==",
                    },
                ],
            })
            chunk_pipeline._atomic_write_json(report_dir / "copybook_manifest.json", {
                "copybooks": {
                    "FOO": {"file": "FOO.cpy", "is_stub": False, "status": "resolved"},
                    "BAR": {"file": "BAR.cpy", "is_stub": True, "status": "stubbed"},
                },
            })

            count = generate_copybook_mentions(report_dir, chunks_dir, "COPYTEST.CBL", False)
            data = chunk_pipeline.load_json(chunks_dir / "COPYTEST.CBL__copybook_mentions.json")

            self.assertEqual(1, count)
            self.assertEqual("copybook_mentions", data["metadata"]["chunk_type"])
            self.assertEqual(2, data["metadata"]["mention_count"])
            self.assertIn("COPY FOO. at source line 12, resolved: yes", data["text"])
            self.assertIn(
                "COPY BAR REPLACING ==A== BY ==B==. at source line 20, resolved: no, stubbed: yes",
                data["text"],
            )
            mentions = data["metadata"]["mentions"]
            self.assertEqual("FOO.cpy", mentions[0]["file"])
            self.assertFalse(mentions[0]["stubbed"])
            self.assertTrue(mentions[1]["stubbed"])
            self.assertEqual("LINKAGE", mentions[1]["section"])

    def test_copybook_mentions_no_mentions_chunk_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            report_dir = Path(td) / "NOCOPY.CBL.report"
            chunks_dir = report_dir / "chunks"
            chunks_dir.mkdir(parents=True)
            chunk_pipeline._atomic_write_json(report_dir / "cobol_structure.json", {
                "copy_statements": [],
            })

            count = generate_copybook_mentions(report_dir, chunks_dir, "NOCOPY.CBL", False)
            data = chunk_pipeline.load_json(chunks_dir / "NOCOPY.CBL__copybook_mentions.json")

            self.assertEqual(1, count)
            self.assertEqual(0, data["metadata"]["mention_count"])
            self.assertIn("No COPY statements were found", data["text"])
            self.assertTrue(data["metadata"]["indexable"])

    def test_comments_chunk_uses_extracted_prose_comments(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            report_dir = Path(td) / "COMMENTS.CBL.report"
            chunks_dir = report_dir / "chunks"
            chunks_dir.mkdir(parents=True)
            chunk_pipeline._atomic_write_json(report_dir / "comments.json", {
                "_PROGRAM_SUMMARY": [
                    {"text": "Program-level overview.", "line": 3},
                ],
                "MAIN": [
                    {"text": "Validate input fields.", "line": 42},
                    {"text": "Send response map.", "line": 43},
                ],
            })

            count = generate_comments(report_dir, chunks_dir, "COMMENTS.CBL", False)
            data = chunk_pipeline.load_json(chunks_dir / "COMMENTS.CBL__comments.json")

            self.assertEqual(1, count)
            self.assertEqual("comments", data["metadata"]["chunk_type"])
            self.assertEqual("produced", data["metadata"]["analysis_status"])
            self.assertEqual(2, data["metadata"]["comment_block_count"])
            self.assertIn("MAIN at source lines 42-43", data["text"])
            self.assertIn("Validate input fields", data["text"])

    def test_comments_chunk_is_explicit_when_scanner_found_none(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            report_dir = Path(td) / "NOCOMMENTS.CBL.report"
            chunks_dir = report_dir / "chunks"
            chunks_dir.mkdir(parents=True)
            chunk_pipeline._atomic_write_json(report_dir / "comments.json", {})

            count = generate_comments(report_dir, chunks_dir, "NOCOMMENTS.CBL", False)
            data = chunk_pipeline.load_json(chunks_dir / "NOCOMMENTS.CBL__comments.json")

            self.assertEqual(1, count)
            self.assertIn("No ordinary source comments were detected", data["text"])
            self.assertEqual(0, data["metadata"]["comment_count"])

    def test_comments_chunk_is_explicit_when_scanner_missing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            report_dir = Path(td) / "MISSINGCOMMENTS.CBL.report"
            chunks_dir = report_dir / "chunks"
            chunks_dir.mkdir(parents=True)

            count = generate_comments(report_dir, chunks_dir, "MISSINGCOMMENTS.CBL", False)
            data = chunk_pipeline.load_json(chunks_dir / "MISSINGCOMMENTS.CBL__comments.json")

            self.assertEqual(1, count)
            self.assertIn("Status: not produced", data["text"])
            self.assertEqual("not_produced", data["metadata"]["analysis_status"])

    def test_commented_out_code_chunk_separates_inactive_cics_and_dataset(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            report_dir = Path(td) / "INACTIVE.CBL.report"
            chunks_dir = report_dir / "chunks"
            chunks_dir.mkdir(parents=True)
            chunk_pipeline._atomic_write_json(report_dir / "commented_out_code.json", {
                "MAIN": [
                    {
                        "line_start": 20,
                        "line_end": 23,
                        "line_count": 4,
                        "reason": "code_like_comment_block",
                        "active": False,
                        "lines": [
                            "EXEC CICS LINK PROGRAM('OLDPGM') END-EXEC.",
                            "EXEC CICS READ DATASET('OLDDS') INTO(OLD-REC) END-EXEC.",
                            "END-EXEC.",
                        ],
                    }
                ],
            })

            count = generate_commented_out_code(report_dir, chunks_dir, "INACTIVE.CBL", False)
            data = chunk_pipeline.load_json(chunks_dir / "INACTIVE.CBL__commented_out_code.json")
            block = data["metadata"]["blocks"][0]

            self.assertEqual(1, count)
            self.assertEqual("commented_out_code", data["metadata"]["chunk_type"])
            self.assertFalse(block["active"])
            self.assertIn("commented-out CICS", block["categories"])
            self.assertIn("commented-out file/dataset", block["categories"])
            self.assertIn("inactive categories", data["text"])
            self.assertIn("source lines 20-23", data["text"])

    def test_commented_out_code_chunk_classifies_inactive_sql(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            report_dir = Path(td) / "INACTIVESQL.CBL.report"
            chunks_dir = report_dir / "chunks"
            chunks_dir.mkdir(parents=True)
            chunk_pipeline._atomic_write_json(report_dir / "commented_out_code.json", {
                "MAIN": [
                    {
                        "line_start": 9,
                        "line_end": 10,
                        "lines": [
                            "EXEC SQL SELECT COL1 FROM OLD_TABLE END-EXEC.",
                        ],
                    }
                ],
            })

            count = generate_commented_out_code(report_dir, chunks_dir, "INACTIVESQL.CBL", False)
            data = chunk_pipeline.load_json(chunks_dir / "INACTIVESQL.CBL__commented_out_code.json")

            self.assertEqual(1, count)
            self.assertIn("commented-out SQL", data["metadata"]["blocks"][0]["categories"])
            self.assertIn("OLD_TABLE", data["text"])

    def test_commented_out_code_chunk_is_explicit_when_none_detected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            report_dir = Path(td) / "NOINACTIVE.CBL.report"
            chunks_dir = report_dir / "chunks"
            chunks_dir.mkdir(parents=True)
            chunk_pipeline._atomic_write_json(report_dir / "commented_out_code.json", {})

            count = generate_commented_out_code(report_dir, chunks_dir, "NOINACTIVE.CBL", False)
            data = chunk_pipeline.load_json(chunks_dir / "NOINACTIVE.CBL__commented_out_code.json")

            self.assertEqual(1, count)
            self.assertIn("No commented-out COBOL code blocks were detected", data["text"])
            self.assertEqual(0, data["metadata"]["inactive_block_count"])

    def test_copybook_fields_extracts_basic_fields_and_88_values(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            report_dir = Path(td) / "FIELDS.CBL.report"
            chunks_dir = report_dir / "chunks"
            copybooks_dir = report_dir / "copybooks"
            chunks_dir.mkdir(parents=True)
            copybooks_dir.mkdir()
            (copybooks_dir / "PARAMS.cpy").write_text(
                "\n".join([
                    "       01 PARAMS-AREA.",
                    "          05 PARAMS-CODE PIC X(02) VALUE '01'.",
                    "          05 PARAMS-AMOUNT PIC S9(7)V99 COMP-3.",
                    "          88 PARAMS-VALID VALUE 'Y'.",
                ]),
                encoding="utf-8",
            )
            chunk_pipeline._atomic_write_json(report_dir / "cobol_structure.json", {
                "copy_statements": [{"copybook": "PARAMS", "line": 10}],
            })
            chunk_pipeline._atomic_write_json(report_dir / "copybook_manifest.json", {
                "copybooks": {
                    "PARAMS": {
                        "file": "PARAMS.cpy",
                        "path": "copybooks/PARAMS.cpy",
                        "is_stub": False,
                        "status": "resolved",
                    },
                },
            })

            count = generate_copybook_fields(report_dir, chunks_dir, "FIELDS.CBL", False)
            data = chunk_pipeline.load_json(chunks_dir / "FIELDS.CBL__copybook_fields.json")

            self.assertEqual(1, count)
            self.assertEqual("copybook_fields", data["metadata"]["chunk_type"])
            self.assertIn("PARAMS-CODE", data["text"])
            self.assertIn("PIC X(02)", data["text"])
            self.assertIn("VALUE '01'", data["text"])
            self.assertIn("PARAMS-VALID", data["text"])
            fields = data["metadata"]["copybooks"][0]["fields"]
            self.assertEqual("PARAMS-AREA", fields[0]["name"])
            self.assertEqual(1, fields[0]["line"])
            self.assertEqual("PARAMS-CODE", fields[1]["name"])
            self.assertEqual("X(02)", fields[1]["picture"])
            self.assertEqual("'01'", fields[1]["value"])
            self.assertEqual("PARAMS-VALID", fields[3]["name"])
            self.assertEqual("88", fields[3]["level"])

    def test_copybook_fields_reports_stubbed_and_missing_copybooks(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            report_dir = Path(td) / "LIMITS.CBL.report"
            chunks_dir = report_dir / "chunks"
            chunks_dir.mkdir(parents=True)
            chunk_pipeline._atomic_write_json(report_dir / "copybook_manifest.json", {
                "copybooks": {
                    "STUBBED": {
                        "file": "STUBBED.cpy",
                        "is_stub": True,
                        "status": "stubbed",
                    },
                    "MISSING": {
                        "file": "MISSING.cpy",
                        "is_stub": False,
                        "status": "resolved",
                    },
                },
            })

            count = generate_copybook_fields(report_dir, chunks_dir, "LIMITS.CBL", False)
            data = chunk_pipeline.load_json(chunks_dir / "LIMITS.CBL__copybook_fields.json")

            self.assertEqual(1, count)
            self.assertIn("STUBBED: stubbed; real fields unavailable.", data["text"])
            self.assertIn("MISSING: copybook file is not available in the report.", data["text"])
            copybooks = {entry["copybook"]: entry for entry in data["metadata"]["copybooks"]}
            self.assertTrue(copybooks["STUBBED"]["stubbed"])
            self.assertEqual([], copybooks["STUBBED"]["fields"])
            self.assertIn("copybook file is not available", copybooks["MISSING"]["limitations"][0])

    def test_copybook_fields_prefers_java_data_structures_over_raw_copybook_parser(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            report_dir = Path(td) / "JAVAFIELDS.CBL.report"
            chunks_dir = report_dir / "chunks"
            copybooks_dir = report_dir / "copybooks"
            ds_dir = report_dir / "data_structures"
            chunks_dir.mkdir(parents=True)
            copybooks_dir.mkdir()
            ds_dir.mkdir()
            (copybooks_dir / "PARAMS.cpy").write_text(
                "       01 RAW-FALLBACK-ONLY PIC X(10).",
                encoding="utf-8",
            )
            chunk_pipeline._atomic_write_json(report_dir / "cobol_structure.json", {
                "copy_statements": [{"copybook": "PARAMS", "line": 10}],
            })
            chunk_pipeline._atomic_write_json(report_dir / "copybook_manifest.json", {
                "copybooks": {
                    "PARAMS": {
                        "file": "PARAMS.cpy",
                        "path": "copybooks/PARAMS.cpy",
                        "is_stub": False,
                        "status": "resolved",
                    },
                },
            })
            chunk_pipeline._atomic_write_json(ds_dir / "JAVAFIELDS.CBL-data.json", {
                "children": [
                    {
                        "levelNumber": 1,
                        "name": "PARAMS-AREA",
                        "rawText": "01 PARAMS-AREA.",
                        "sourceSection": "LINKAGE",
                        "dataType": "GROUP",
                        "children": [
                            {
                                "levelNumber": 5,
                                "name": "JAVA-PARSED-FIELD",
                                "rawText": "05 JAVA-PARSED-FIELD PIC X(10).",
                                "sourceSection": "LINKAGE",
                                "dataType": "STRING",
                                "children": [],
                            }
                        ],
                    }
                ],
            })

            count = generate_copybook_fields(report_dir, chunks_dir, "JAVAFIELDS.CBL", False)
            data = chunk_pipeline.load_json(chunks_dir / "JAVAFIELDS.CBL__copybook_fields.json")

            self.assertEqual(1, count)
            self.assertEqual("java_rawtext_regex", data["metadata"]["field_source"])
            self.assertFalse(data["metadata"]["copybook_origin_available"])
            self.assertEqual("incomplete", data["metadata"]["analysis_status"])
            self.assertIn("JAVA-PARSED-FIELD", data["text"])
            self.assertNotIn("RAW-FALLBACK-ONLY", data["text"])
            self.assertIn("field-to-copybook ownership is not available", data["text"])

    def test_copybook_fields_unavailable_for_null_java_data_structure_sentinel(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            report_dir = Path(td) / "NULLFIELDS.CBL.report"
            chunks_dir = report_dir / "chunks"
            copybooks_dir = report_dir / "copybooks"
            ds_dir = report_dir / "data_structures"
            chunks_dir.mkdir(parents=True)
            copybooks_dir.mkdir()
            ds_dir.mkdir()
            (copybooks_dir / "PARAMS.cpy").write_text(
                "       01 RAW-FALLBACK-ONLY PIC X(10).",
                encoding="utf-8",
            )
            chunk_pipeline._atomic_write_json(report_dir / "cobol_structure.json", {
                "copy_statements": [{"copybook": "PARAMS", "line": 10}],
            })
            chunk_pipeline._atomic_write_json(report_dir / "copybook_manifest.json", {
                "copybooks": {
                    "PARAMS": {
                        "file": "PARAMS.cpy",
                        "path": "copybooks/PARAMS.cpy",
                        "is_stub": False,
                        "status": "resolved",
                    },
                },
            })
            chunk_pipeline._atomic_write_json(ds_dir / "NULLFIELDS.CBL-data.json", {
                "name": "NULL[LENIENT_FALLBACK]",
                "levelNumber": -99,
                "children": [],
            })

            count = generate_copybook_fields(report_dir, chunks_dir, "NULLFIELDS.CBL", False)
            data = chunk_pipeline.load_json(chunks_dir / "NULLFIELDS.CBL__copybook_fields.json")

            self.assertEqual(1, count)
            self.assertEqual("unavailable", data["metadata"]["analysis_status"])
            self.assertEqual("none", data["metadata"]["field_source"])
            self.assertEqual(
                "java_data_structures_null_sentinel",
                data["metadata"]["degradation_reason"],
            )
            self.assertIn("Data structures unavailable", data["text"])
            self.assertNotIn("RAW-FALLBACK-ONLY", data["text"])

    def test_line_based_split_preserves_copybook_field_lines(self) -> None:
        text = "Copybook fields for BIG.CBL:\n" + "\n".join(
            f"- COPY{i:03d}: FIELD-{i:03d} (level 05, PIC X(10), line {i})."
            for i in range(30)
        )

        parts = _split_parts_with_context(text, {"chunk_type": "copybook_fields"})

        self.assertGreater(len(parts), 1)
        self.assertTrue(all(part.startswith("Copybook fields") for part in parts))
        for part in parts:
            for line in part.splitlines()[1:]:
                self.assertTrue(line.startswith("- COPY"), line)
            self.assertLessEqual(token_count(part), 45)

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

    def test_dependencies_chunk_extracts_literal_cics_arguments_from_cfg(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            report_dir = Path(td) / "CFGRES.CBL.report"
            chunks_dir = report_dir / "chunks"
            kb_dir = report_dir / "knowledge_base"
            cfg_dir = report_dir / "cfg"
            chunks_dir.mkdir(parents=True)
            kb_dir.mkdir()
            cfg_dir.mkdir()
            (kb_dir / "03_Dependencies.yaml").write_text(
                "\n".join([
                    "program: CFGRES.CBL",
                    "cics:",
                    "- SEND",
                    "- RETURN",
                ]),
                encoding="utf-8",
            )
            chunk_pipeline._atomic_write_json(cfg_dir / "cfg-CFGRES.CBL.json", {
                "nodes": [
                    {
                        "type": "DIALECT",
                        "originalText": (
                            "EXEC CICS SEND MAP('BNK1DA') MAPSET('BNK1DAM') "
                            "RESP(WS-RESP) END-EXEC"
                        ),
                    },
                    {
                        "type": "EXEC_CICS",
                        "originalText": (
                            "EXEC CICS RETURN TRANSID('OMEN') "
                            "QUEUE(WS-QUEUE-NAME) END-EXEC"
                        ),
                    },
                ],
            })

            count = generate_dependencies(report_dir, chunks_dir, "CFGRES.CBL", False)
            data = chunk_pipeline.load_json(chunks_dir / "CFGRES.CBL__dependencies.json")

            self.assertEqual(1, count)
            self.assertIn("MAP BNK1DA", data["text"])
            self.assertIn("MAPSET BNK1DAM", data["text"])
            self.assertIn("TRANSID OMEN", data["text"])
            self.assertNotIn("WS-QUEUE-NAME", data["text"])
            self.assertEqual(["BNK1DA"], data["metadata"]["cics_maps"])
            self.assertEqual(["BNK1DAM"], data["metadata"]["cics_mapsets"])
            self.assertEqual(["OMEN"], data["metadata"]["cics_transids"])
            self.assertEqual([], data["metadata"]["cics_queues"])

    def test_program_summary_includes_called_by_from_cross_program_calls(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out_dir = Path(td) / "out"
            report_dir = out_dir / "report" / "CALLEE.CBL.report"
            chunks_dir = report_dir / "chunks"
            kb_dir = report_dir / "knowledge_base"
            chunks_dir.mkdir(parents=True)
            kb_dir.mkdir()
            (kb_dir / "00_Executive_Summary.md").write_text(
                "\n".join([
                    "| Metric | Value |",
                    "| ------ | ----- |",
                    "| Total CFG Nodes | 10 |",
                    "| Total Edges | 12 |",
                    "| Variables Defined | 3 |",
                    "| Complexity Score | Low (4) |",
                ]),
                encoding="utf-8",
            )
            chunk_pipeline._atomic_write_json(out_dir / "cross_program_calls.json", {
                "programs": [
                    {
                        "name": "CALLEE",
                        "called_by": [
                            {"source": "CALLER1", "edge_type": "CALLS"},
                            {"source": "CALLER2", "edge_type": "LINKS"},
                        ],
                    },
                ],
            })

            count = generate_program_summary(report_dir, chunks_dir, "CALLEE.CBL", False)
            data = chunk_pipeline.load_json(chunks_dir / "CALLEE.CBL__program_summary.json")

            self.assertEqual(1, count)
            self.assertIn("Called by: CALLER1, CALLER2.", data["text"])
            self.assertEqual(["CALLER1", "CALLER2"], data["metadata"]["called_by"])

    def test_program_summary_includes_structural_facts_from_cobol_structure(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            report_dir = Path(td) / "STRUCT.CBL.report"
            chunks_dir = report_dir / "chunks"
            kb_dir = report_dir / "knowledge_base"
            chunks_dir.mkdir(parents=True)
            kb_dir.mkdir()
            (kb_dir / "00_Executive_Summary.md").write_text(
                "\n".join([
                    "| Metric | Value |",
                    "| ------ | ----- |",
                    "| Total CFG Nodes | 20 |",
                    "| Total Edges | 25 |",
                    "| Variables Defined | 8 |",
                    "| Complexity Score | Medium (7) |",
                    "",
                    "## Node Type Distribution",
                    "| Type | Count |",
                    "| --- | --- |",
                    "| PARAGRAPH | 2 |",
                ]),
                encoding="utf-8",
            )
            chunk_pipeline._atomic_write_json(report_dir / "cobol_structure.json", {
                "paragraph_profiles": {"A010": {}, "A020": {}},
                "sections": {"SEC-A": {}, "SEC-B": {}, "SEC-C": {}},
                "conditions_88": {"IS-VALID": {}, "IS-CLOSED": {}},
                "redefines": [{"name": "A"}, {"name": "B"}, {"name": "C"}, {"name": "D"}],
            })

            count = generate_program_summary(report_dir, chunks_dir, "STRUCT.CBL", False)
            data = chunk_pipeline.load_json(chunks_dir / "STRUCT.CBL__program_summary.json")

            self.assertEqual(1, count)
            self.assertIn(
                "Paragraphs: 2 in 3 sections. 88-level conditions: 2. REDEFINES: 4.",
                data["text"],
            )
            self.assertEqual(2, data["metadata"]["paragraph_count"])
            self.assertEqual(3, data["metadata"]["section_count"])
            self.assertEqual(2, data["metadata"]["condition_count"])
            self.assertEqual(4, data["metadata"]["redefines_count"])

    def test_external_program_calls_chunk_includes_cics_parameters(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            report_dir = Path(td) / "CALLS.CBL.report"
            chunks_dir = report_dir / "chunks"
            kb_dir = report_dir / "knowledge_base"
            chunks_dir.mkdir(parents=True)
            kb_dir.mkdir()
            (kb_dir / "03_Dependencies.yaml").write_text(
                "\n".join([
                    "program: CALLS.CBL",
                    "cics_operations:",
                    "- command: LINK",
                    "  type: program_transfer",
                    "  target_kind: PROGRAM",
                    "  target: PD0GCODA",
                    "  target_source: literal",
                    "- command: XCTL",
                    "  type: program_transfer",
                    "  target_kind: PROGRAM",
                    "  target: PDPRED",
                    "  target_source: literal",
                ]),
                encoding="utf-8",
            )
            (kb_dir / "01_Logic_Narrative.md").write_text(
                "\n".join([
                    "## LINK-CODA",
                    "- **CICS:** `EXEC CICS LINK PROGRAM('PD0GCODA') "
                    "COMMAREA(WPDRGCODA) LENGTH(PDRGCODA-LUNGH) END-EXEC.`",
                    "## XCTL-MAIN",
                    "- **CICS:** `EXEC CICS XCTL PROGRAM('PDPRED') END-EXEC.`",
                ]),
                encoding="utf-8",
            )

            count = generate_external_program_calls(report_dir, chunks_dir, "CALLS.CBL", False)
            data = chunk_pipeline.load_json(chunks_dir / "CALLS.CBL__external_program_calls.json")

            self.assertEqual(1, count)
            self.assertEqual("external_program_calls", data["metadata"]["chunk_type"])
            self.assertIn(
                "- LINK PD0GCODA in LINK-CODA: COMMAREA WPDRGCODA, "
                "LENGTH PDRGCODA-LUNGH, target_source literal.",
                data["text"],
            )
            self.assertIn("- XCTL PDPRED in XCTL-MAIN: target_source literal.", data["text"])
            self.assertEqual({"PD0GCODA", "PDPRED"}, set(data["metadata"]["call_targets"]))
            pd0gcoda = next(call for call in data["metadata"]["calls"] if call["target"] == "PD0GCODA")
            self.assertEqual("WPDRGCODA", pd0gcoda["commarea"])
            self.assertEqual("PDRGCODA-LUNGH", pd0gcoda["length"])

    def test_datasets_tables_resources_chunk_separates_resource_kinds(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            report_dir = Path(td) / "RESOURCES.CBL.report"
            chunks_dir = report_dir / "chunks"
            kb_dir = report_dir / "knowledge_base"
            chunks_dir.mkdir(parents=True)
            kb_dir.mkdir()
            (kb_dir / "03_Dependencies.yaml").write_text(
                "\n".join([
                    "program: RESOURCES.CBL",
                    "database:",
                    "  tables_read: [DUAL]",
                    "  tables_updated: [CUSTOMER]",
                    "  sql_statements: [SELECT, UPDATE]",
                    "cics_operations:",
                    "- command: READ",
                    "  type: file_read",
                    "  target_kind: DATASET",
                    "  target: CUSTFILE",
                    "  target_source: literal",
                    "- command: WRITEQ",
                    "  type: queue_write",
                    "  target_kind: QUEUE",
                    "  target: TSQ-NAME",
                    "  target_source: identifier",
                    "- command: RETURN",
                    "  type: program_transfer",
                    "  target_kind: TRANSID",
                    "  target: MENU",
                    "  target_source: literal",
                    "- command: SEND",
                    "  type: other",
                    "  target_kind: MAP",
                    "  target: MAP01",
                    "  target_source: literal",
                ]),
                encoding="utf-8",
            )
            (kb_dir / "01_Logic_Narrative.md").write_text(
                "## SEND-MAP\n"
                "- **CICS:** `EXEC CICS SEND MAP('MAP01') MAPSET('MAPSET1') END-EXEC.`\n",
                encoding="utf-8",
            )

            count = generate_datasets_tables_resources(report_dir, chunks_dir, "RESOURCES.CBL", False)
            data = chunk_pipeline.load_json(
                chunks_dir / "RESOURCES.CBL__datasets_tables_resources.json"
            )

            self.assertEqual(1, count)
            self.assertEqual("datasets_tables_resources", data["metadata"]["chunk_type"])
            self.assertIn("DB2 tables read: DUAL.", data["text"])
            self.assertIn("DB2 tables updated: CUSTOMER.", data["text"])
            self.assertIn("CICS datasets/files read: CUSTFILE (READ).", data["text"])
            self.assertIn("CICS queues: TSQ-NAME (WRITEQ).", data["text"])
            self.assertIn("CICS maps: MAP01 (SEND), MAP01 (SEND, in SEND-MAP).", data["text"])
            self.assertIn("CICS mapsets: MAPSET1 (SEND, in SEND-MAP).", data["text"])
            self.assertIn("CICS transaction ids: MENU (RETURN).", data["text"])
            self.assertEqual(["DUAL"], data["metadata"]["db2_tables_read"])
            self.assertEqual(["CUSTOMER"], data["metadata"]["db2_tables_updated"])

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

    def test_static_values_chunk_includes_provenance_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            report_dir = Path(td) / "VALUES2.CBL.report"
            chunks_dir = report_dir / "chunks"
            kb_dir = report_dir / "knowledge_base"
            chunks_dir.mkdir(parents=True)
            kb_dir.mkdir()
            chunk_pipeline._atomic_write_json(report_dir / "variable_values.json", [
                ["PDRUTI01-FUNZIONE", ["'04'"]],
                ["WABEND-CODE", ["'UT$$'"]],
            ])
            (kb_dir / "01_Logic_Narrative.md").write_text(
                "\n".join([
                    "## LINK-PD0UTI01",
                    "Known values: PDRUTI01-FUNZIONE = '04'",
                    "Known values: WABEND-CODE = 'UT$$'",
                ]),
                encoding="utf-8",
            )

            count = generate_static_values(report_dir, chunks_dir, "VALUES2.CBL", False)
            data = chunk_pipeline.load_json(chunks_dir / "VALUES2.CBL__static_values.json")
            entries = {entry["variable"]: entry for entry in data["metadata"]["static_values"]}

            self.assertEqual(1, count)
            self.assertIn(
                "- PDRUTI01-FUNZIONE: '04'. Category: external-call parameter. "
                "Paragraphs: LINK-PD0UTI01",
                data["text"],
            )
            self.assertIn(
                "- WABEND-CODE: 'UT$$'. Category: abend code. Paragraphs: LINK-PD0UTI01",
                data["text"],
            )
            self.assertEqual(["LINK-PD0UTI01"], entries["PDRUTI01-FUNZIONE"]["paragraphs"])
            self.assertEqual("external-call parameter", entries["PDRUTI01-FUNZIONE"]["category"])

    def test_static_values_include_external_call_consumer_when_evidenced(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            report_dir = Path(td) / "VALUES3.CBL.report"
            chunks_dir = report_dir / "chunks"
            kb_dir = report_dir / "knowledge_base"
            chunks_dir.mkdir(parents=True)
            kb_dir.mkdir()
            chunk_pipeline._atomic_write_json(report_dir / "variable_values.json", [
                ["PDRGCODA-FUNZIONE", ["'01'"]],
                ["WABEND-CODE", ["'UT$$'"]],
            ])
            (kb_dir / "01_Logic_Narrative.md").write_text(
                "\n".join([
                    "## LINK-CODA",
                    "Known values: PDRGCODA-FUNZIONE = '01'",
                    "- **CICS:** `EXEC CICS LINK PROGRAM('PD0GCODA') COMMAREA(WPDRGCODA) LENGTH(PDRGCODA-LUNGH) END-EXEC.`",
                    "## ABEND00",
                    "Known values: WABEND-CODE = 'UT$$'",
                    "- **CICS:** `EXEC CICS LINK PROGRAM('TE0CDUMP') COMMAREA(WABEND-CODE) LENGTH(4) END-EXEC.`",
                ]),
                encoding="utf-8",
            )

            count = generate_static_values(report_dir, chunks_dir, "VALUES3.CBL", False)
            data = chunk_pipeline.load_json(chunks_dir / "VALUES3.CBL__static_values.json")
            entries = {entry["variable"]: entry for entry in data["metadata"]["static_values"]}

            self.assertEqual(1, count)
            self.assertIn(
                "Consumer: external-call COMMAREA for LINK PD0GCODA via COMMAREA WPDRGCODA in LINK-CODA",
                data["text"],
            )
            self.assertIn(
                "Consumer: external-call COMMAREA for LINK TE0CDUMP via COMMAREA WABEND-CODE in ABEND00",
                data["text"],
            )
            consumer = entries["PDRGCODA-FUNZIONE"]["consumers"][0]
            self.assertEqual("external-call COMMAREA", consumer["role"])
            self.assertEqual("PD0GCODA", consumer["target_program"])
            self.assertEqual("WPDRGCODA", consumer["argument_value"])

    def test_static_values_unknown_consumer_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            report_dir = Path(td) / "VALUES4.CBL.report"
            chunks_dir = report_dir / "chunks"
            chunks_dir.mkdir(parents=True)
            chunk_pipeline._atomic_write_json(report_dir / "variable_values.json", [
                ["BUSINESS-FLAG", ["'Y'"]],
            ])

            count = generate_static_values(report_dir, chunks_dir, "VALUES4.CBL", False)
            data = chunk_pipeline.load_json(chunks_dir / "VALUES4.CBL__static_values.json")
            entry = data["metadata"]["static_values"][0]

            self.assertEqual(1, count)
            self.assertIn("Consumer: unknown", data["text"])
            self.assertEqual("unknown", entry["consumers"][0]["role"])

    def test_variable_matches_cics_arg_no_false_positive_short_root(self) -> None:
        self.assertFalse(chunk_pipeline._variable_matches_cics_arg("WS-CODE", "TRAN-CODE"))
        self.assertFalse(chunk_pipeline._variable_matches_cics_arg("CODE", "TRAN-CODE"))

    def test_generate_rag_bundle_copies_chunks_kb_and_supporting_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            report_dir = Path(td) / "BUNDLE.CBL.report"
            chunks_dir = report_dir / "chunks"
            kb_dir = report_dir / "knowledge_base"
            chunks_dir.mkdir(parents=True)
            kb_dir.mkdir()
            write_chunk(
                chunks_dir,
                "BUNDLE.CBL__dependencies.json",
                "External dependencies for program BUNDLE.CBL: none.",
                {
                    "chunk_type": "dependencies",
                    "chunk_id": "BUNDLE.CBL:dependencies",
                    "program": "BUNDLE.CBL",
                },
            )
            (kb_dir / "03_Dependencies.yaml").write_text("program: BUNDLE.CBL\n", encoding="utf-8")
            chunk_pipeline._atomic_write_json(report_dir / "parse_diagnostics.json", {
                "coverage_percentage": 100.0,
            })

            count = generate_rag_bundle(report_dir, chunks_dir, "BUNDLE.CBL", False)
            manifest = chunk_pipeline.load_json(report_dir / "knowledge-base_rag" / "manifest.json")

            self.assertEqual(1, count)
            self.assertTrue((report_dir / "knowledge-base_rag" / "chunks" / "BUNDLE.CBL__dependencies.json").exists())
            self.assertTrue((report_dir / "knowledge-base_rag" / "knowledge_base" / "03_Dependencies.yaml").exists())
            self.assertTrue((report_dir / "knowledge-base_rag" / "artifacts" / "parse_diagnostics.json").exists())
            self.assertEqual("chunks", manifest["recommended_index_path"])
            self.assertEqual(1, manifest["chunk_count"])

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
