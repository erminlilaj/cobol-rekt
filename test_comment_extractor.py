#!/usr/bin/env python3
"""Regression tests for comment_extractor.py."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import comment_extractor


class CommentExtractorTest(unittest.TestCase):
    def test_code_like_comment_block_is_separated_from_prose_comments(self) -> None:
        source = "\n".join([
            "       IDENTIFICATION DIVISION.",
            "       PROGRAM-ID. TESTPROG.",
            "       PROCEDURE DIVISION.",
            "      * SENDS THE SCREEN",
            "       SEND-MAP.",
            "           EXIT.",
            "      * OLD DATASET BROWSE",
            "      * BROWSE-OLD.",
            "      * EXEC CICS STARTBR DATASET('OLDDS') RIDFLD(OLD-KEY)",
            "      * END-EXEC.",
            "      * EXEC CICS READNEXT DATASET('OLDDS') INTO(OLD-REC)",
            "      * END-EXEC.",
            "       ACTIVE-PARA.",
            "           EXIT.",
        ])
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "TESTPROG.CBL"
            path.write_text(source, encoding="utf-8")

            comments, inactive = comment_extractor.extract_comments_with_inactive_code(path)

        self.assertEqual({"SEND-MAP": ["SENDS THE SCREEN"]}, comments)
        self.assertEqual(["ACTIVE-PARA"], list(inactive.keys()))
        block = inactive["ACTIVE-PARA"][0]
        self.assertFalse(block["active"])
        self.assertEqual("code_like_comment_block", block["reason"])
        self.assertIn("EXEC CICS STARTBR DATASET('OLDDS') RIDFLD(OLD-KEY)", block["lines"])

    def test_extract_comments_to_json_writes_inactive_artifact(self) -> None:
        source = "\n".join([
            "       IDENTIFICATION DIVISION.",
            "       PROGRAM-ID. TESTPROG.",
            "       PROCEDURE DIVISION.",
            "      * OLD.",
            "      * MOVE 'X' TO FIELD-A.",
            "      * EXEC CICS LINK PROGRAM('OLDPGM') END-EXEC.",
            "       MAIN.",
            "           EXIT.",
        ])
        with tempfile.TemporaryDirectory() as td:
            source_path = Path(td) / "TESTPROG.CBL"
            comments_path = Path(td) / "comments.json"
            source_path.write_text(source, encoding="utf-8")

            comment_extractor.extract_comments_to_json(source_path, comments_path)

            comments = json.loads(comments_path.read_text(encoding="utf-8"))
            inactive = json.loads((Path(td) / "commented_out_code.json").read_text(encoding="utf-8"))

        self.assertEqual({}, comments)
        self.assertEqual(["MAIN"], list(inactive.keys()))
        self.assertEqual(3, inactive["MAIN"][0]["line_count"])


if __name__ == "__main__":
    unittest.main()
