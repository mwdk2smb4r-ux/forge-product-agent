import asyncio
import tempfile
import unittest
from pathlib import Path

from forge_agent.workspace import Workspace, WorkspaceError


class WorkspaceTests(unittest.TestCase):
    def make_workspace(self, root: Path) -> Workspace:
        return Workspace(root, max_file_bytes=10_000, timeout_seconds=10, allowed_commands=("python", "git"))

    def test_blocks_escape_and_secret_files(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = self.make_workspace(Path(directory) / "work")
            with self.assertRaises(WorkspaceError):
                workspace.read_file("../outside.txt")
            (workspace.root / ".env").write_text("SECRET=x", encoding="utf-8")
            with self.assertRaises(WorkspaceError):
                workspace.read_file(".env")
            (workspace.root / ".env.production").write_text("SECRET=y", encoding="utf-8")
            with self.assertRaises(WorkspaceError):
                workspace.read_file(".env.production")

    def test_requires_hash_for_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = self.make_workspace(Path(directory) / "work")
            created = workspace.write_file("app.py", "print('one')\n")
            with self.assertRaisesRegex(WorkspaceError, "read first"):
                workspace.write_file("app.py", "print('two')\n")
            updated = workspace.write_file("app.py", "print('two')\n", created["sha256"])
            self.assertEqual(updated["action"], "updated")

    def test_replace_must_be_unique(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = self.make_workspace(Path(directory) / "work")
            created = workspace.write_file("x.txt", "same same")
            with self.assertRaisesRegex(WorkspaceError, "exactly once"):
                workspace.replace_text("x.txt", "same", "new", created["sha256"])

    def test_command_policy_blocks_python_code_and_allows_version(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = self.make_workspace(Path(directory) / "work")
            with self.assertRaises(WorkspaceError):
                asyncio.run(workspace.run_command("python", ["-c", "print('no')"]))
            result = asyncio.run(workspace.run_command("python", ["--version"]))
            self.assertEqual(result["exit_code"], 0)

    def test_safe_mode_blocks_test_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = self.make_workspace(Path(directory) / "work")
            for module in ("unittest", "pytest", "ruff"):
                with self.subTest(module=module), self.assertRaisesRegex(WorkspaceError, "execution is disabled"):
                    workspace._validate_command("python", ["-m", module])
            command, args = workspace._validate_command("python", ["-m", "compileall", "."])
            self.assertTrue(command)
            self.assertEqual(args[1], "compileall")

    def test_trusted_mode_can_enable_test_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Workspace(
                Path(directory) / "work",
                max_file_bytes=10_000,
                timeout_seconds=10,
                allowed_commands=("python",),
                allow_project_code_execution=True,
            )
            command, args = workspace._validate_command("python", ["-m", "unittest"])
            self.assertTrue(command)
            self.assertEqual(args[1], "unittest")

    def test_blocks_git_output_and_helper_options(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = self.make_workspace(Path(directory) / "work")
            for args in (["diff", "--output=stolen"], ["diff", "--ext-diff"], ["show", "--textconv"]):
                with self.subTest(args=args), self.assertRaises(WorkspaceError):
                    workspace._validate_command("git", args)

    def test_blocks_command_paths_outside_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = self.make_workspace(Path(directory) / "work")
            for args in (
                ["-m", "compileall", ".."],
                ["-m", "pytest", "--basetemp=../outside"],
                ["-m", "pytest", "C:\\outside\\test.py"],
            ):
                with self.subTest(args=args), self.assertRaises(WorkspaceError):
                    workspace._validate_command("python", args)


if __name__ == "__main__":
    unittest.main()
