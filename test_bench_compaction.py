#!/usr/bin/env python3
"""Stage 6 (D7) contract tests — compaction benchmark harness.

Run: python3 -m unittest test_bench_compaction.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).parent


def _run_bench(output_json: Path, output_md: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable,
            "scripts/bench_compaction.py",
            "--output-json",
            str(output_json),
            "--output-md",
            str(output_md),
        ],
        cwd=REPO_ROOT,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


class BenchCompactionHarnessTest(unittest.TestCase):

    def test_bench_harness_runs_without_error(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            output_json = Path(td) / "bench_results.json"
            output_md = Path(td) / "bench_results.md"

            completed = _run_bench(output_json, output_md)

            self.assertEqual("", completed.stderr)
            self.assertEqual(0, completed.returncode)
            self.assertTrue(output_json.exists())
            self.assertTrue(output_md.exists())

    def test_bench_output_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            first_json = Path(td) / "first.json"
            first_md = Path(td) / "first.md"
            second_json = Path(td) / "second.json"
            second_md = Path(td) / "second.md"

            first = _run_bench(first_json, first_md)
            second = _run_bench(second_json, second_md)

            self.assertEqual(0, first.returncode)
            self.assertEqual(0, second.returncode)
            self.assertEqual(
                first_json.read_text(encoding="utf-8"),
                second_json.read_text(encoding="utf-8"),
            )

    def test_bench_baseline_sha_present_in_fixtures(self) -> None:
        fixtures = json.loads(
            (REPO_ROOT / "scripts" / "bench_fixtures.json").read_text(encoding="utf-8")
        )

        self.assertEqual(40, len(fixtures["baseline_sha"]))
        self.assertEqual("main", fixtures["baseline_branch"])


if __name__ == "__main__":
    unittest.main()
