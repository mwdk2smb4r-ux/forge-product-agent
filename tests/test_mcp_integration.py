import json
import tempfile
import unittest
from pathlib import Path

from forge_agent.config import ResearchSettings, WorkspaceSettings
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

    async def test_isolated_research_server_catalog_and_ssrf_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = WorkspaceSettings(
                root=Path(directory) / "work",
                max_file_bytes=10_000,
                command_timeout_seconds=10,
                allowed_commands=("python",),
            )
            research = ResearchSettings(
                enabled=True,
                request_timeout_seconds=10,
                max_response_bytes=50_000,
                max_redirects=1,
                allowed_domains=(),
                search_provider="perplexity",
                search_api_key_env="PERPLEXITY_API_KEY",
            )
            async with WorkspaceMCP(workspace, output_limit=10_000, research_settings=research) as mcp:
                names = [tool["function"]["name"] for tool in mcp.model_tools]
                self.assertEqual(len(names), 8)
                self.assertIn("research_fetch_url", names)
                self.assertIn("research_search_web", names)
                result = json.loads(await mcp.call("research_fetch_url", {"url": "http://127.0.0.1/private"}))
                self.assertTrue(result["is_error"])
                self.assertIn("public HTTPS", str(result["result"]))


if __name__ == "__main__":
    unittest.main()
