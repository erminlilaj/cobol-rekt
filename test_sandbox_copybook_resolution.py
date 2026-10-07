import tempfile
import unittest
from pathlib import Path

from analysis.sandbox_manager import SandboxEnvironment


class SandboxCopybookResolutionTest(unittest.TestCase):
    def test_copybook_with_same_stem_as_program_is_not_source(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "PD1VSOC.CBL"
            copybooks = root / "copybooks"
            copybooks.mkdir()
            (copybooks / "PD1VSOC").write_text(
                "           03 PD1VSOC-FUNZIONE PIC XX.\n", encoding="utf-8"
            )
            source.write_text(
                "       IDENTIFICATION DIVISION.\n"
                "       PROGRAM-ID. PD1VSOC.\n"
                "       DATA DIVISION.\n"
                "       LINKAGE SECTION.\n"
                "       01 DFHCOMMAREA.\n"
                "           COPY PD1VSOC.\n"
                "       PROCEDURE DIVISION.\n"
                "           GOBACK.\n",
                encoding="utf-8",
            )

            with SandboxEnvironment(source, [root], auto_stub=False) as sandbox:
                text = (sandbox.sandbox_copybooks / "PD1VSOC.cpy").read_text(
                    encoding="utf-8"
                )
                self.assertIn("PD1VSOC-FUNZIONE", text)
                self.assertNotIn("PROCEDURE DIVISION", text)

    def test_missing_same_named_copybook_is_stubbed_not_self_copied(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "PD1VSOC.CBL"
            source.write_text(
                "       IDENTIFICATION DIVISION.\n"
                "       PROGRAM-ID. PD1VSOC.\n"
                "       DATA DIVISION.\n"
                "       LINKAGE SECTION.\n"
                "       01 DFHCOMMAREA.\n"
                "           COPY PD1VSOC.\n"
                "       PROCEDURE DIVISION.\n"
                "           GOBACK.\n",
                encoding="utf-8",
            )

            with SandboxEnvironment(source, [root], auto_stub=True) as sandbox:
                text = (sandbox.sandbox_copybooks / "PD1VSOC.cpy").read_text(
                    encoding="utf-8"
                )
                self.assertIn("STUB COPYBOOK", text)
                self.assertNotIn("PROCEDURE DIVISION", text)


if __name__ == "__main__":
    unittest.main()
