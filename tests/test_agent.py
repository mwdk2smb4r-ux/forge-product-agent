import json
import unittest

from forge_agent.agent import ProductAgent
from forge_agent.policy import ApprovalGate, POLICY_BY_MODEL_NAME


class FakeProvider:
    def __init__(self, replies, *, active_is_local=True):
        self.replies = iter(replies)
        self.active_is_local = active_is_local

    async def complete(self, messages, tools):
        return next(self.replies)


class FakeMCP:
    model_tools = [{"type": "function", "function": {"name": "workspace_write_file"}}]

    def __init__(self):
        self.calls = []

    def policy_for_model_name(self, name):
        return POLICY_BY_MODEL_NAME.get(name)

    async def call(self, name, arguments):
        self.calls.append((name, arguments))
        return json.dumps({"ok": True})


class AgentTests(unittest.IsolatedAsyncioTestCase):
    async def test_denied_tool_never_reaches_mcp(self):
        provider = FakeProvider(
            [
                {
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "1",
                            "function": {"name": "workspace_write_file", "arguments": '{"path":"x","content":"y"}'},
                        }
                    ],
                },
                {"content": "I did not write the file."},
            ]
        )
        mcp = FakeMCP()
        agent = ProductAgent(provider, mcp, ApprovalGate(lambda _: "no", lambda _: None), 2, lambda _: None)
        response = await agent.run_turn("write it")
        self.assertEqual(response, "I did not write the file.")
        self.assertEqual(mcp.calls, [])

    async def test_denied_research_query_never_leaves_the_host(self):
        provider = FakeProvider(
            [
                {
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "research-1",
                            "function": {
                                "name": "research_search_web",
                                "arguments": '{"query":"private product notes"}',
                            },
                        }
                    ],
                },
                {"content": "The query was not sent."},
            ]
        )
        mcp = FakeMCP()
        agent = ProductAgent(provider, mcp, ApprovalGate(lambda _: "no", lambda _: None), 2, lambda _: None)
        response = await agent.run_turn("research this")
        self.assertEqual(response, "The query was not sent.")
        self.assertEqual(mcp.calls, [])

    async def test_tool_round_limit_does_not_execute_extra_call(self):
        tool_message = {
            "content": None,
            "tool_calls": [
                {
                    "id": "1",
                    "function": {"name": "workspace_write_file", "arguments": '{"path":"x","content":"y"}'},
                }
            ],
        }
        provider = FakeProvider([tool_message, tool_message])
        mcp = FakeMCP()
        agent = ProductAgent(provider, mcp, ApprovalGate(lambda _: "yes", lambda _: None), 1, lambda _: None)
        response = await agent.run_turn("write it")
        self.assertIn("tool-round limit", response)
        self.assertEqual(len(mcp.calls), 1)

    async def test_remote_model_needs_approval_to_read_workspace_content(self):
        provider = FakeProvider(
            [
                {
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "read-1",
                            "function": {"name": "workspace_read_file", "arguments": '{"path":"PRODUCT.md"}'},
                        }
                    ],
                },
                {"content": "The file was not read."},
            ],
            active_is_local=False,
        )
        mcp = FakeMCP()
        agent = ProductAgent(provider, mcp, ApprovalGate(lambda _: "no", lambda _: None), 2, lambda _: None)

        response = await agent.run_turn("read the product brief")

        self.assertEqual(response, "The file was not read.")
        self.assertEqual(mcp.calls, [])

    async def test_local_model_can_read_workspace_without_extra_approval(self):
        provider = FakeProvider(
            [
                {
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "read-1",
                            "function": {"name": "workspace_read_file", "arguments": '{"path":"PRODUCT.md"}'},
                        }
                    ],
                },
                {"content": "Read locally."},
            ],
            active_is_local=True,
        )
        mcp = FakeMCP()
        gate = ApprovalGate(lambda _: self.fail("local reads must not prompt"), lambda _: None)
        agent = ProductAgent(provider, mcp, gate, 2, lambda _: None)

        response = await agent.run_turn("read the product brief")

        self.assertEqual(response, "Read locally.")
        self.assertEqual(mcp.calls, [("workspace_read_file", {"path": "PRODUCT.md"})])

    async def test_new_conversation_gets_a_new_tracing_session(self):
        provider = FakeProvider([{"content": "hello"}])
        agent = ProductAgent(provider, None, ApprovalGate(lambda _: "no", lambda _: None), 1)
        previous = agent.session_id
        agent.reset()
        self.assertNotEqual(agent.session_id, previous)


if __name__ == "__main__":
    unittest.main()
