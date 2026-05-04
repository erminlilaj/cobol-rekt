import json
import tempfile
import unittest
from pathlib import Path

from analyze import AnalysisPipeline, PipelineReport
from analysis.sandbox_manager import SandboxEnvironment, copy_text_normalized, is_bms_source


class PipelineHardeningTest(unittest.TestCase):
    def test_lenient_partial_success_rejects_failed_base_analysis(self):
        with tempfile.TemporaryDirectory() as td:
            report_dir = Path(td)
            (report_dir / "parse_diagnostics.json").write_text(
                json.dumps({"coverage_percentage": 90, "error_summary": {"total_errors": 1}}),
                encoding="utf-8",
            )
            (report_dir / "analysis_health.json").write_text(
                json.dumps(
                    {
                        "base_analysis_succeeded": False,
                        "primary_failure": {"diagnostic_code": "MISSING_PROCEDURE_DIVISION_BODY"},
                    }
                ),
                encoding="utf-8",
            )

            pipeline = AnalysisPipeline.__new__(AnalysisPipeline)
            pipeline.report_subdir = report_dir

            self.assertFalse(pipeline._check_lenient_partial_success("", "lenient"))

    def test_pipeline_report_uses_analysis_health_failure(self):
        with tempfile.TemporaryDirectory() as td:
            report_dir = Path(td)
            (report_dir / "analysis_health.json").write_text(
                json.dumps(
                    {
                        "base_analysis_succeeded": False,
                        "data_structures_degraded": False,
                        "failed_tasks": ["BUILD_BASE_ANALYSIS"],
                        "primary_failure": {"diagnostic_code": "MISSING_PROCEDURE_DIVISION_BODY"},
                    }
                ),
                encoding="utf-8",
            )

            report = PipelineReport("BROKEN.CBL")
            report.start_step("step1_core_structures")
            report.end_step("success")
            out = report_dir / "pipeline_report.json"
            report.write(out)

            data = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual("completed_with_failures", data["overall_status"])
            self.assertFalse(data["analysis_health"]["base_analysis_succeeded"])

    def test_pipeline_report_warns_on_degraded_data_structures(self):
        with tempfile.TemporaryDirectory() as td:
            report_dir = Path(td)
            (report_dir / "analysis_health.json").write_text(
                json.dumps(
                    {
                        "base_analysis_succeeded": True,
                        "data_structures_degraded": True,
                        "failed_tasks": [],
                    }
                ),
                encoding="utf-8",
            )

            report = PipelineReport("DEGRADED.CBL")
            report.start_step("step1_core_structures")
            report.end_step("success")
            out = report_dir / "pipeline_report.json"
            report.write(out)

            data = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual("completed_with_warnings", data["overall_status"])
            self.assertTrue(data["analysis_health"]["data_structures_degraded"])

    def test_cleanup_removes_stale_parse_diagnostics_after_clean_analysis(self):
        with tempfile.TemporaryDirectory() as td:
            report_dir = Path(td)
            (report_dir / "analysis_health.json").write_text(
                json.dumps(
                    {
                        "base_analysis_succeeded": True,
                        "parse_error_count": 0,
                    }
                ),
                encoding="utf-8",
            )
            stale_diag = report_dir / "parse_diagnostics.json"
            stale_diag.write_text(
                json.dumps({"coverage_percentage": 99.88}),
                encoding="utf-8",
            )

            pipeline = AnalysisPipeline.__new__(AnalysisPipeline)
            pipeline.report_subdir = report_dir
            pipeline._clear_stale_parse_diagnostics()

            self.assertFalse(stale_diag.exists())

    def test_copy_text_normalized_strips_crlf(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "SRC.CBL"
            dst = Path(td) / "DST.CBL"
            src.write_bytes(b"000001 IDENTIFICATION DIVISION.   \r\n000002 PROGRAM-ID. T.\t\r\n")

            copy_text_normalized(src, dst)

            content = dst.read_bytes()
            self.assertNotIn(b"\r\n", content)
            self.assertNotIn(b"   \n", content)
            self.assertNotIn(b"\t\n", content)
            self.assertIn(b"\n", content)

    def test_sandbox_stubs_bms_macro_copybook(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "PROG.CBL"
            copybook = root / "MAPCPY.cpy"
            source.write_text(
                "       IDENTIFICATION DIVISION.\n"
                "       PROGRAM-ID. PROG.\n"
                "       DATA DIVISION.\n"
                "       WORKING-STORAGE SECTION.\n"
                "       COPY MAPCPY.\n"
                "       PROCEDURE DIVISION.\n"
                "           GOBACK.\n",
                encoding="utf-8",
            )
            copybook.write_text(
                "MAPCPY   DFHMSD TYPE=&SYSPARM,MODE=INOUT,TIOAPFX=YES\n"
                "FIELD1   DFHMDF POS=(1,1),LENGTH=2\n",
                encoding="utf-8",
            )

            self.assertTrue(is_bms_source(copybook))
            with SandboxEnvironment(source, [root], auto_stub=False) as sandbox:
                sandboxed = sandbox.sandbox_copybooks / "MAPCPY.cpy"
                text = sandboxed.read_text(encoding="utf-8")
                self.assertIn("STUB COPYBOOK", text)
                self.assertIn("BMS macro source detected", text)


if __name__ == "__main__":
    unittest.main()
