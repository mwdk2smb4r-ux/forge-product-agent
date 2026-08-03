from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any


IGNORED_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".forge_agent", ".pytest_cache", ".ruff_cache"}
DENIED_PARTS = {".git", ".ssh", ".aws", ".azure", ".gnupg", ".forge_agent"}
DENIED_NAMES = {
    ".env",
    ".git-credentials",
    ".netrc",
    ".npmrc",
    ".pypirc",
    "auth.json",
    "credentials",
    "credentials.json",
    "id_ed25519",
    "id_rsa",
    "secrets.toml",
    "service-account.json",
    "service_account.json",
}
DENIED_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".kdbx"}


class WorkspaceError(ValueError):
    pass


class Workspace:
    def __init__(
        self,
        root: Path,
        max_file_bytes: int,
        timeout_seconds: int,
        allowed_commands: tuple[str, ...],
        allow_project_code_execution: bool = False,
    ):
        self.root = root.resolve()
        self.max_file_bytes = max_file_bytes
        self.timeout_seconds = timeout_seconds
        self.allowed_commands = set(allowed_commands)
        self.allow_project_code_execution = allow_project_code_execution
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, relative: str, *, allow_missing: bool = False) -> Path:
        if not isinstance(relative, str) or not relative or "\x00" in relative:
            raise WorkspaceError("path must be a non-empty string")
        raw = Path(relative)
        if raw.is_absolute():
            raise WorkspaceError("absolute paths are not allowed")
        current = self.root
        for part in raw.parts:
            current = current / part
            if current.is_symlink():
                raise WorkspaceError("symlinks are not allowed")
        candidate = (self.root / raw).resolve(strict=False)
        try:
            candidate.relative_to(self.root)
        except ValueError:
            raise WorkspaceError("path escapes the workspace") from None
        lowered_parts = {part.lower() for part in raw.parts}
        if lowered_parts & DENIED_PARTS:
            raise WorkspaceError("access to this path is denied")
        name = raw.name.lower()
        if name in DENIED_NAMES or name.startswith(".env.") or raw.suffix.lower() in DENIED_SUFFIXES:
            raise WorkspaceError("secret-like files are denied")
        if candidate.exists() and candidate.is_symlink():
            raise WorkspaceError("symlinks are not allowed")
        if not allow_missing and not candidate.exists():
            raise WorkspaceError(f"path does not exist: {relative}")
        return candidate

    @staticmethod
    def _sha(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def list_files(self, path: str = ".", max_entries: int = 300) -> dict[str, Any]:
        max_entries = max(1, min(int(max_entries), 500))
        base = self._path(path)
        if not base.is_dir():
            raise WorkspaceError("path is not a directory")
        entries: list[dict[str, Any]] = []
        for current, dirs, files in os.walk(base, followlinks=False):
            dirs[:] = sorted(d for d in dirs if d not in IGNORED_DIRS and not (Path(current) / d).is_symlink())
            for name in sorted(files):
                item = Path(current) / name
                relative = item.relative_to(self.root).as_posix()
                try:
                    checked = self._path(relative)
                    if checked.is_file():
                        entries.append({"path": relative, "size": checked.stat().st_size})
                except (OSError, WorkspaceError):
                    continue
                if len(entries) >= max_entries:
                    return {"entries": entries, "truncated": True}
        return {"entries": entries, "truncated": False}

    def read_file(self, path: str, start_line: int = 1, max_lines: int = 400) -> dict[str, Any]:
        target = self._path(path)
        if not target.is_file():
            raise WorkspaceError("path is not a regular file")
        data = target.read_bytes()
        if len(data) > self.max_file_bytes:
            raise WorkspaceError(f"file exceeds {self.max_file_bytes} bytes")
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            raise WorkspaceError("only UTF-8 text files can be read") from None
        lines = text.splitlines(keepends=True)
        start = max(1, int(start_line))
        count = max(1, min(int(max_lines), 1000))
        selected = "".join(lines[start - 1 : start - 1 + count])
        return {
            "path": target.relative_to(self.root).as_posix(),
            "content": selected,
            "sha256": self._sha(data),
            "start_line": start,
            "total_lines": len(lines),
            "truncated": start - 1 + count < len(lines),
        }

    def write_file(self, path: str, content: str, expected_sha256: str | None = None) -> dict[str, Any]:
        if not isinstance(content, str):
            raise WorkspaceError("content must be text")
        data = content.encode("utf-8")
        if len(data) > self.max_file_bytes:
            raise WorkspaceError(f"content exceeds {self.max_file_bytes} bytes")
        target = self._path(path, allow_missing=True)
        if target.exists():
            if not target.is_file():
                raise WorkspaceError("path is not a regular file")
            current = target.read_bytes()
            if not expected_sha256 or expected_sha256 != self._sha(current):
                raise WorkspaceError("existing file changed or was not read first; supply its current sha256")
            action = "updated"
        else:
            if expected_sha256:
                raise WorkspaceError("expected_sha256 must be omitted for a new file")
            action = "created"
        target.parent.mkdir(parents=True, exist_ok=True)
        parent = target.parent.resolve()
        try:
            parent.relative_to(self.root)
        except ValueError:
            raise WorkspaceError("parent path escapes the workspace") from None
        temporary_name = ""
        try:
            with tempfile.NamedTemporaryFile("wb", delete=False, dir=parent, prefix=".forge-", suffix=".tmp") as temporary:
                temporary.write(data)
                temporary.flush()
                os.fsync(temporary.fileno())
                temporary_name = temporary.name
            os.replace(temporary_name, target)
        finally:
            if temporary_name and os.path.exists(temporary_name):
                os.unlink(temporary_name)
        return {"path": target.relative_to(self.root).as_posix(), "action": action, "bytes": len(data), "sha256": self._sha(data)}

    def replace_text(self, path: str, old: str, new: str, expected_sha256: str) -> dict[str, Any]:
        if not old:
            raise WorkspaceError("old text must not be empty")
        current = self.read_file(path, 1, 1000)
        target = self._path(path)
        data = target.read_bytes()
        if current["sha256"] != expected_sha256:
            raise WorkspaceError("file changed; read it again before replacing text")
        text = data.decode("utf-8")
        occurrences = text.count(old)
        if occurrences != 1:
            raise WorkspaceError(f"old text must occur exactly once; found {occurrences}")
        return self.write_file(path, text.replace(old, new, 1), expected_sha256)

    def _validate_command(self, executable: str, args: list[str]) -> tuple[str, list[str]]:
        name = Path(executable).name.lower()
        if name.endswith(".exe"):
            name = name[:-4]
        if name not in self.allowed_commands:
            raise WorkspaceError(f"executable is not allowlisted: {name}")
        if len(args) > 64 or any(not isinstance(arg, str) or len(arg) > 1000 or "\x00" in arg or "\n" in arg for arg in args):
            raise WorkspaceError("command arguments are invalid or too large")
        for arg in args:
            normalized = arg.replace("\\", "/")
            path_candidate = normalized.partition("=")[2] if "=" in normalized else normalized
            if (
                ".." in path_candidate.split("/")
                or path_candidate.startswith(("/", "//", "~"))
                or re.search(r"(?:^|=)[A-Za-z]:/", normalized)
            ):
                raise WorkspaceError("command arguments cannot reference paths outside the workspace")
        if name in {"python", "py"}:
            if args in (["--version"], ["-V"]):
                return sys.executable if name == "python" else (shutil.which("py") or sys.executable), args
            allowed_modules = {"compileall"}
            if self.allow_project_code_execution:
                allowed_modules.update({"unittest", "pytest", "ruff"})
            if len(args) < 2 or args[0] != "-m" or args[1] not in allowed_modules:
                if not self.allow_project_code_execution:
                    raise WorkspaceError(
                        "project-code execution is disabled; Python is limited to --version and -m compileall"
                    )
                raise WorkspaceError(f"Python is limited to -m with {sorted(allowed_modules)}")
            resolved = sys.executable if name == "python" else (shutil.which("py") or sys.executable)
            return resolved, args
        if name == "git":
            allowed_git = {"status", "diff", "log", "show", "rev-parse", "ls-files"}
            if not args or args[0] not in allowed_git:
                raise WorkspaceError(f"Git is limited to read-only subcommands: {sorted(allowed_git)}")
            risky_git = ("--output", "--ext-diff", "--textconv", "--config", "-c")
            if any(arg == "-c" or arg.startswith(risky_git[:-1]) for arg in args[1:]):
                raise WorkspaceError("Git options that write output or execute/configure helpers are denied")
        if name == "npm":
            if args == ["--version"]:
                pass
            elif not self.allow_project_code_execution:
                raise WorkspaceError("project-code execution is disabled; npm scripts cannot run")
            elif args[:1] == ["test"]:
                pass
            elif len(args) >= 2 and args[0] == "run" and args[1] in {"test", "lint", "check", "build"}:
                pass
            else:
                raise WorkspaceError("npm is limited to test, lint, check, and build scripts")
        resolved = shutil.which(name)
        if not resolved:
            raise WorkspaceError(f"allowlisted executable is not installed: {name}")
        try:
            Path(resolved).resolve().relative_to(self.root)
        except ValueError:
            pass
        else:
            raise WorkspaceError("workspace-local executables are not allowed")
        return resolved, args

    async def run_command(self, executable: str, args: list[str], cwd: str = ".") -> dict[str, Any]:
        command, checked_args = self._validate_command(executable, args)
        working = self._path(cwd)
        if not working.is_dir():
            raise WorkspaceError("cwd is not a directory")
        env_names = ("PATH", "SystemRoot", "WINDIR", "TEMP", "TMP")
        env = {name: os.environ[name] for name in env_names if name in os.environ}
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONNOUSERSITE"] = "1"
        env["PYTHONSAFEPATH"] = "1"
        env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
        env["GIT_CONFIG_NOSYSTEM"] = "1"
        env["GIT_CONFIG_GLOBAL"] = os.devnull
        env["GIT_PAGER"] = "cat"
        env["PAGER"] = "cat"
        process = await asyncio.create_subprocess_exec(
            command,
            *checked_args,
            cwd=working,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=self.timeout_seconds)
        except TimeoutError:
            process.kill()
            await process.wait()
            raise WorkspaceError(f"command exceeded {self.timeout_seconds} seconds") from None
        limit = 20_000
        stdout_text = stdout.decode("utf-8", errors="replace")
        stderr_text = stderr.decode("utf-8", errors="replace")
        truncated = len(stdout_text) + len(stderr_text) > limit
        if truncated:
            remaining = max(0, limit - len(stdout_text[:limit]))
            stdout_text = stdout_text[:limit]
            stderr_text = stderr_text[:remaining]
        return {
            "command": [Path(command).name, *checked_args],
            "cwd": working.relative_to(self.root).as_posix() or ".",
            "exit_code": process.returncode,
            "stdout": stdout_text,
            "stderr": stderr_text,
            "truncated": truncated,
        }
