#!/usr/bin/env python3
"""Regression tests for rag_kb_evaluator.py."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from rag_kb_evaluator import RagKbEvaluator


def _write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _chunk(path: Path, text: str, chunk_type: str, program: str,
           metadata_extra: dict | None = None) -> None:
    meta = {
        "schema_version": "1.3",
        "pipeline_version": "1.3",
        "chunk_type": chunk_type,
        "chunk_id": f"{program}:{chunk_type}:{path.stem}",
        "program": program,
        "content_hash": hashlib.sha256(text.encode("utf-8")).hexdigest()[:16],
    }
    if metadata_extra:
        meta.update(metadata_extra)
    _write_json(path, {"text": text, "metadata": meta})


def _metric(program_result: dict, field: str, stage: str) -> dict:
    for metric in program_result["metrics"]:
        if metric["field"] == field and metric["stage"] == stage:
            return metric
    raise AssertionError(f"Missing metric {field}:{stage}")


class RagKbEvaluatorTest(unittest.TestCase):
    def test_synthetic_cobol_percentages_for_core_fields(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            report = root / "TEST.CBL.report"
            source_root = root / "src"
            source_root.mkdir()
            (source_root / "TEST.CBL").write_text(
                """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT CUSTOMER-FILE ASSIGN TO CUSTVSAM.
       DATA DIVISION.
       FILE SECTION.
       FD  CUSTOMER-FILE.
       01  CUSTOMER-REC PIC X(10).
       WORKING-STORAGE SECTION.
       01  WS-AREA PIC X(10).
       PROCEDURE DIVISION.
       MAIN.
           CALL 'PAYPGM' USING WS-AREA.
           EXEC CICS LINK PROGRAM('CICSPGM') END-EXEC.
           EXEC SQL SELECT * FROM ACCOUNTS END-EXEC.
           READ CUSTOMER-FILE.
           STOP RUN.
                """,
                encoding="utf-8",
            )

            _write_json(report / "cfg" / "cfg-TEST.CBL.json", {
                "nodes": [
                    {"id": "p1", "type": "PARAGRAPH", "name": "MAIN"},
                    {"id": "call1", "type": "CALL", "name": "CALL PAYPGM",
                     "originalText": "CALL 'PAYPGM' USING WS-AREA",
                     "metadata": {"call_target": "PAYPGM"}},
                    {"id": "cics1", "type": "DIALECT", "name": "CICS LINK",
                     "originalText": "EXEC CICS LINK PROGRAM('CICSPGM') END-EXEC",
                     "metadata": {
                         "cics_command": "LINK",
                         "cics_target_program": "CICSPGM",
                         "handler_bindings": [{"target": "ERR-PARA"}],
                     }},
                    {"id": "sql1", "type": "EXEC_SQL", "name": "SQL SELECT",
                     "originalText": "EXEC SQL SELECT * FROM ACCOUNTS END-EXEC",
                     "metadata": {"sql_operation": "SELECT"}},
                    {"id": "read1", "type": "READ", "name": "READ CUSTOMER-FILE",
                     "originalText": "READ CUSTOMER-FILE"},
                    {"id": "stop1", "type": "STOP_RUN", "name": "STOP RUN",
                     "originalText": "STOP RUN"},
                ],
                "edges": [
                    {"fromNodeID": "p1", "toNodeID": "call1", "edgeType": "STARTS_WITH"},
                    {"fromNodeID": "call1", "toNodeID": "cics1", "edgeType": "FOLLOWED_BY"},
                ],
            })
            _write_json(report / "data_structures" / "TEST.CBL-data.json", {
                "name": "ROOT",
                "children": [
                    {"name": "WS-AREA", "levelNumber": 1, "sourceSection": "WORKING_STORAGE",
                     "raw": "01 WS-AREA PIC X(10)."},
                    {"name": "CUSTOMER-REC", "levelNumber": 1, "sourceSection": "FILE_DESCRIPTOR",
                     "raw": "01 CUSTOMER-REC PIC X(10)."},
                ],
            })
            _write_json(report / "cobol_structure.json", {
                "divisions": {"IDENTIFICATION": {}, "ENVIRONMENT": {}, "DATA": {}, "PROCEDURE": {}},
                "sections": {"FILE": {"division": "DATA"}, "WORKING-STORAGE": {"division": "DATA"}},
                "copy_statements": [{"copybook": "SQLCA", "impact": "SQLCODE checks"}],
                "known_system_copybooks": {"SQLCA": {"system": "DB2", "stub_impact": "SQLCODE checks"}},
                "conditions_88": {"CUSTOMER-OK": {"parent": "WS-AREA", "values": ["Y"]}},
                "redefines": [{"redefining": "ALT-REC", "redefines": "CUSTOMER-REC"}],
                "paragraph_profiles": {"MAIN": {"type_counts": {"READ": 1}}},
            })
            _write_json(report / "copybook_manifest.json", {
                "copybooks": {"SQLCA": {"is_stub": True, "status": "stubbed"}},
                "summary": {"total_copybooks": 1, "resolved": 0},
            })
            _write_json(report / "comments.json", {"MAIN": ["process customer"]})
            _write_json(report / "comments_enriched.json", {
                "MAIN": {"english": "process customer", "category": "file_io", "translation_failed": False}
            })
            kb = report / "knowledge_base"
            kb.mkdir(parents=True)
            (kb / "00_Executive_Summary.md").write_text(
                "IDENTIFICATION ENVIRONMENT DATA PROCEDURE FILE WORKING-STORAGE MAIN SQLCA DB2",
                encoding="utf-8",
            )
            (kb / "01_Logic_Narrative.md").write_text(
                "MAIN PAYPGM WS-AREA CICSPGM ERR-PARA LINK SELECT ACCOUNTS READ CUSTOMER-FILE STOP RUN process customer file_io",
                encoding="utf-8",
            )
            (kb / "02_Data_Dictionary.md").write_text(
                "WS-AREA CUSTOMER-REC CUSTOMER-OK ALT-REC PIC",
                encoding="utf-8",
            )
            (kb / "03_Dependencies.yaml").write_text(
                """
program: TEST.CBL
database:
  tables_read: [ACCOUNTS]
  tables_updated: []
  sql_statements: [SELECT]
calls:
  - target: PAYPGM
    using: [WS-AREA]
cics: [LINK]
cics_calls:
  - command: LINK
    target: CICSPGM
                """,
                encoding="utf-8",
            )
            chunks_dir = report / "chunks"
            _chunk(
                chunks_dir / "TEST.CBL__dependencies.json",
                "PAYPGM WS-AREA CICSPGM LINK SELECT ACCOUNTS SQLCA DB2 CUSTOMER-FILE READ MAIN",
                "dependencies",
                "TEST.CBL",
                {"calls": ["PAYPGM"], "cics_calls": [{"target": "CICSPGM"}],
                 "sql_tables_read": ["ACCOUNTS"], "copybooks_used": ["SQLCA"],
                 "known_system_copybooks": {"SQLCA": {"system": "DB2"}}},
            )
            _chunk(
                chunks_dir / "TEST.CBL__paragraph__MAIN.json",
                "MAIN READ CUSTOMER-FILE STOP RUN process customer file_io ERR-PARA",
                "paragraph_logic",
                "TEST.CBL",
                {"paragraph": "MAIN", "cics_handler_bindings": [{"target": "ERR-PARA"}]},
            )
            _chunk(
                chunks_dir / "TEST.CBL__cics_operations.json",
                "Program TEST.CBL CICS operations: LINK target program CICSPGM. "
                "HANDLE CONDITION ERROR transfers control to ERR-PARA.",
                "cics_operations",
                "TEST.CBL",
                {
                    "cics_commands": ["LINK"],
                    "cics_calls": [{"command": "LINK", "target": "CICSPGM"}],
                    "cics_call_targets": ["CICSPGM"],
                    "cics_handler_bindings": [{"target": "ERR-PARA"}],
                },
            )

            result = RagKbEvaluator(root, source_roots=[source_root]).evaluate()
            program = result["programs"][0]

            self.assertEqual("TEST.CBL", program["program"])
            self.assertEqual(6, program["counts"]["cfg_nodes"])
            self.assertEqual(3, program["counts"]["chunks"])
            self.assertEqual(100.0, _metric(program, "external_calls", "artifact_to_knowledge_base")["percentage"])
            self.assertEqual(100.0, _metric(program, "cics", "artifact_to_knowledge_base")["percentage"])
            self.assertEqual(100.0, _metric(program, "db2_sql", "knowledge_base_to_chunks")["percentage"])
            self.assertEqual(100.0, _metric(program, "copybooks", "knowledge_base_to_chunks")["percentage"])
            self.assertEqual(100.0, result["corpus"]["retrieval_summary"]["cics"]["recall_at_1"])
            # Source has SELECT, ASSIGN, and READ. Current artifacts preserve READ only,
            # so the evaluator must expose the file-control loss as an exact percentage.
            self.assertEqual(33.33, _metric(program, "vsam_file_io", "source_to_artifact")["percentage"])

    def test_chunk_quality_detects_thin_and_oversized_chunks(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            report = root / "CHUNK.CBL.report"
            _write_json(report / "cfg" / "cfg-CHUNK.CBL.json", {"nodes": [], "edges": []})
            chunks_dir = report / "chunks"
            _chunk(chunks_dir / "CHUNK.CBL__thin.json", "tiny", "paragraph_logic", "CHUNK.CBL")
            _chunk(
                chunks_dir / "CHUNK.CBL__big.json",
                " ".join(f"TOKEN{i}" for i in range(80)),
                "section_summary",
                "CHUNK.CBL",
            )

            result = RagKbEvaluator(root, max_tokens=50, min_tokens=5).evaluate()
            program = result["programs"][0]

            self.assertEqual(2, program["chunk_quality"]["total_chunks"])
            self.assertEqual(1, program["chunk_quality"]["thin_chunks"])
            self.assertEqual(1, program["chunk_quality"]["oversized_chunks"])
            self.assertEqual(50.0, _metric(program, "chunks", "bpe_size_compliance")["percentage"])
            self.assertEqual(50.0, _metric(program, "chunks", "minimum_context_compliance")["percentage"])

    def test_synthetic_jcl_percentages(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            report = root / "JOB1.jcl.report"
            _write_json(report / "jcl_summary.json", {"job_name": "JOB1"})
            _write_json(report / "jcl_steps.json", [
                {"name": "STEP1", "program": "PAYPGM", "input_datasets": ["IN.FILE"],
                 "output_datasets": ["OUT.FILE"], "cond": "(0,NE)"}
            ])
            _write_json(report / "jcl_datasets.json", [
                {"dsn": "IN.FILE", "access": "read"},
                {"dsn": "OUT.FILE", "access": "write"},
            ])
            chunks_dir = report / "chunks"
            _chunk(
                chunks_dir / "JOB1__step__STEP1.json",
                "JOB1 STEP1 PAYPGM IN.FILE OUT.FILE COND read write",
                "step_detail",
                "JOB1.jcl",
                {"job": "JOB1", "step": "STEP1", "program": "PAYPGM",
                 "condition": "COND", "datasets": ["IN.FILE", "OUT.FILE"],
                 "dataset_access": ["read", "write"]},
            )

            result = RagKbEvaluator(root).evaluate()
            program = result["programs"][0]

            self.assertEqual("JCL", program["mode"])
            self.assertEqual(100.0, _metric(program, "jcl", "knowledge_base_to_chunks")["percentage"])
            self.assertEqual(100.0, _metric(program, "jcl", "chunk_metadata")["percentage"])
            artifact_to_kb = _metric(program, "jcl", "artifact_to_knowledge_base")
            self.assertEqual("not_applicable", artifact_to_kb["status"])
            self.assertIsNone(artifact_to_kb["percentage"])

    def test_semantic_defects_exclude_chunks_field(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            report = root / "CHUNKDEFECT.CBL.report"
            _write_json(report / "cfg" / "cfg-CHUNKDEFECT.CBL.json", {"nodes": [], "edges": []})
            chunks_dir = report / "chunks"
            _chunk(chunks_dir / "CHUNKDEFECT.CBL__thin.json", "tiny", "paragraph_logic", "CHUNKDEFECT.CBL")
            _chunk(
                chunks_dir / "CHUNKDEFECT.CBL__big.json",
                " ".join(f"TOKEN{i}" for i in range(80)),
                "section_summary",
                "CHUNKDEFECT.CBL",
            )

            result = RagKbEvaluator(root, max_tokens=50, min_tokens=5).evaluate()

            self.assertNotIn("chunks", {d["field"] for d in result["corpus"]["top_defects"]})
            self.assertEqual(
                {"oversized_chunks", "thin_chunks"},
                {d["defect"] for d in result["corpus"]["chunk_quality_defects"]},
            )

    def test_failed_base_analysis_is_recorded_unevaluable(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            report = root / "BROKEN.CBL.report"
            _write_json(report / "analysis_health.json", {"base_analysis_succeeded": False})
            _write_json(report / "cfg" / "cfg-BROKEN.CBL.json", {
                "nodes": [
                    {"id": "call1", "type": "CALL", "name": "CALL PAYPGM",
                     "originalText": "CALL 'PAYPGM'", "metadata": {"call_target": "PAYPGM"}},
                ],
                "edges": [],
            })
            _chunk(
                report / "chunks" / "BROKEN.CBL__paragraph__MAIN.json",
                "PAYPGM",
                "paragraph_logic",
                "BROKEN.CBL",
            )

            result = RagKbEvaluator(root).evaluate()
            program = result["programs"][0]

            self.assertEqual("base_analysis_failed", program["unevaluable_reason"])
            self.assertEqual(["BROKEN.CBL"], [p["program"] for p in result["corpus"]["unevaluable_programs"]])
            self.assertEqual({}, result["corpus"]["retrieval_summary"])
            self.assertEqual(1, result["corpus"]["chunk_quality"]["total_chunks"])

    def test_duplicate_reporting_separates_within_report_and_global(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for program in ("DUPA.CBL", "DUPB.CBL"):
                report = root / f"{program}.report"
                _write_json(report / "cfg" / f"cfg-{program}.json", {"nodes": [], "edges": []})
                _chunk(
                    report / "chunks" / f"{program}__paragraph__A.json",
                    "same semantic body",
                    "paragraph_logic",
                    program,
                    {"paragraph": "A"},
                )
            _chunk(
                root / "DUPA.CBL.report" / "chunks" / "DUPA.CBL__paragraph__B.json",
                "same semantic body",
                "paragraph_logic",
                "DUPA.CBL",
                {"paragraph": "B"},
            )

            result = RagKbEvaluator(root).evaluate()
            quality = result["corpus"]["chunk_quality"]
            dupa = next(p for p in result["programs"] if p["program"] == "DUPA.CBL")

            self.assertEqual(3, quality["total_chunks"])
            self.assertEqual(1, quality["within_report_duplicate_content_hashes"])
            self.assertEqual(2, quality["global_duplicate_content_hashes"])
            self.assertEqual(2, dupa["chunk_quality"]["total_chunks"])

    def test_real_prog_complex_golden_counts_when_available(self) -> None:
        report = Path("out/report/PROG_COMPLEX.CBL.report")
        if not report.exists():
            self.skipTest("PROG_COMPLEX report is not available")

        program_eval = RagKbEvaluator(Path("out/report")).evaluate_report(report)
        program = {
            "program": program_eval.program,
            "counts": program_eval.counts,
            "chunk_quality": program_eval.chunk_quality,
            "metrics": [metric.__dict__ for metric in program_eval.metrics],
        }

        # Structural counts from CFG — stable across KB regenerations
        self.assertEqual("PROG_COMPLEX.CBL", program["program"])
        self.assertEqual(922, program["counts"]["cfg_nodes"])
        self.assertEqual(1355, program["counts"]["cfg_edges"])

        # Chunk counts derived from the actual manifest so the test stays
        # data-driven even when KB content changes (e.g. bug fixes add more chunks)
        manifest_path = report / "chunks" / "chunks_manifest.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            expected_total = manifest.get("total_chunks", 0)
            self.assertEqual(expected_total, program["chunk_quality"]["total_chunks"],
                             "Evaluator total_chunks must match chunks_manifest.json")

        self.assertEqual(0, program["chunk_quality"]["thin_chunks"])
        self.assertEqual(100.0, _metric(program, "cics", "artifact_to_knowledge_base")["percentage"])
        composite = _metric(program, "control_flow.composite", "artifact_to_knowledge_base")
        legacy = _metric(program, "control_flow.legacy_verbatim", "artifact_to_knowledge_base")
        self.assertGreater(composite["percentage"], 50.0)
        self.assertGreaterEqual(
            program_eval.control_flow_scores["paragraph_coverage"]["percentage"], 90.0,
        )
        self.assertIn("Legacy exact CFG-fact text match", legacy["note"])
        self.assertNotEqual(
            _metric(program, "control_flow", "artifact_to_knowledge_base")["percentage"],
            composite["percentage"],
        )


if __name__ == "__main__":
    unittest.main()
