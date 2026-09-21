from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts import start_revb_detached


class DetachedLauncherTests(unittest.TestCase):
    def test_identifies_only_this_workspaces_resume_orchestrator(self) -> None:
        workspace = Path("/tmp/SemanticInfoTheory").resolve()
        command = [
            "/usr/bin/python3",
            str(workspace / "scripts" / "resume_throttled_orchestrator.py"),
            "--workspace",
            ".",
        ]

        self.assertTrue(start_revb_detached.is_expected_orchestrator(command, workspace))
        self.assertFalse(
            start_revb_detached.is_expected_orchestrator(
                ["/usr/bin/python3", "/tmp/other/scripts/resume_throttled_orchestrator.py"],
                workspace,
            )
        )
        self.assertFalse(start_revb_detached.is_expected_orchestrator(["/bin/sleep", "60"], workspace))

    def test_atomic_pid_file_replaces_stale_value(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "orchestrator.pid"
            path.write_text("123\n", encoding="utf-8")

            start_revb_detached.atomic_write_pid(path, 456)

            self.assertEqual(path.read_text(encoding="utf-8"), "456\n")


if __name__ == "__main__":
    unittest.main()
