import json
import tempfile
import unittest
from pathlib import Path

from forge_agent.config import WorkspaceSettings
from forge_agent.mcp_client import WorkspaceMCP


def contains_key(value, key):
    if isinstance(value, dict):
        return key in value or any(contains_key(item, key) for item in value.values())
    if isinstance(value, list):
        return any(contains_key(item, key) for item in value)
    return False


class MCPIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_stdio_round_trip_and_sanitized_catalog(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = WorkspaceSettings(
                root=Path(directory) / "work",
                max_file_bytes=10_000,
                command_timeout_seconds=10,
                allowed_commands=("python",),
            )
            async with WorkspaceMCP(settings, output_limit=10_000) as mcp:
                names = [tool["function"]["name"] for tool in mcp.model_tools]
                self.assertEqual(len(names), 5)
                self.assertIn("workspace_write_file", names)
                for tool in mcp.model_tools:
                    self.assertFalse(contains_key(tool["function"]["parameters"], "description"))
                result = json.loads(
                    await mcp.call("workspace_write_file", {"path": "hello.txt", "content": "hello\n"})
                )
                self.assertFalse(result["is_error"])
                self.assertEqual(result["result"]["action"], "created")


if __name__ == "__main__":
    unittest.main()
