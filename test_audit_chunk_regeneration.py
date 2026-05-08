#!/usr/bin/env python3
"""Regression tests for audit_chunk_regeneration.py."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import audit_chunk_regeneration
import chunk_pipeline


class AuditChunkRegenerationTest(unittest.TestCase):
    def test_audit_report_flags_stale_manifest_and_chunk_schema(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            report = Path(td) / "OLD.CBL.report"
            chunks = report / "chunks"
            chunks.mkdir(parents=True)
            chunk_pipeline._atomic_write_json(
                chunks / "OLD.CBL__program_summary.json",
                {
                    "text": "Old summary",
                    "metadata": {
                        "chunk_type": "program_summary",
                        "chunk_id": "OLD.CBL:program_summary",
                        "schema_version": "1.3",
                    },
                },
            )
            chunk_pipeline._atomic_write_json(
                chunks / "chunks_manifest.json",
                {
                    "schema_version": "1.3",
                    "chunks": [{"file": "OLD.CBL__program_summary.json"}],
                },
            )

            result = audit_chunk_regeneration.audit_report(
                report,
                chunk_pipeline.CHUNK_SCHEMA_VERSION,
            )

            self.assertTrue(result["needs_regeneration"])
            self.assertIn("stale_manifest_schema:1.3", result["reasons"])
            self.assertIn("stale_chunk_schema:1.3:1", result["reasons"])

    def test_audit_report_accepts_current_schema_report(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            report = Path(td) / "NEW.CBL.report"
            chunks = report / "chunks"
            chunks.mkdir(parents=True)
            chunk_pipeline.write_chunk(
                chunks,
                "NEW.CBL__analysis_health.json",
                "Analysis health for NEW.CBL: Parse completed without errors.",
                {
                    "chunk_type": "cobol_analysis_health",
                    "chunk_id": "NEW.CBL:analysis_health",
                    "program": "NEW.CBL",
                },
            )
            chunk_pipeline.generate_manifest(chunks, False)

            result = audit_chunk_regeneration.audit_report(
                report,
                chunk_pipeline.CHUNK_SCHEMA_VERSION,
            )

            self.assertFalse(result["needs_regeneration"])
            self.assertEqual([], result["reasons"])


if __name__ == "__main__":
    unittest.main()
