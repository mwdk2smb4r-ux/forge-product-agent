import unittest
from contextlib import nullcontext

from forge_agent.config import TracingSettings
from forge_agent.tracing import ForgeTracing, _mask_sensitive, tracing_readiness


HOSTS = ("cloud.langfuse.com", "us.cloud.langfuse.com")


class FakeObservation:
    def __init__(self):
        self.updates = []

    def update(self, **values):
        self.updates.append(values)


class FakeClient:
    def __init__(self):
        self.starts = []
        self.observations = []
        self.flushes = 0

    def start_as_current_observation(self, **values):
        observation = FakeObservation()
        self.starts.append(values)
        self.observations.append(observation)
        return nullcontext(observation)

    def flush(self):
        self.flushes += 1


class FakeProvider:
    active_model = "forge-local"
    active_name = "local"
    active_is_local = True


class TracingTests(unittest.TestCase):
    def settings(self, *, enabled=True, capture=False):
        return TracingSettings(enabled, capture, "test", 1.0, HOSTS)

    def test_disabled_and_missing_credentials_are_nonfatal(self):
        self.assertIn("disabled", tracing_readiness(self.settings(enabled=False), {}).detail)
        readiness = tracing_readiness(self.settings(), {})
        self.assertFalse(readiness.ready)
        self.assertIn("LANGFUSE_SECRET_KEY", readiness.detail)

    def test_base_url_is_pinned_to_allowlisted_https_host(self):
        environment = {
            "LANGFUSE_PUBLIC_KEY": "pk-lf-test",
            "LANGFUSE_SECRET_KEY": "sk-lf-test",
            "LANGFUSE_BASE_URL": "https://attacker.example",
        }
        readiness = tracing_readiness(self.settings(), environment)
        self.assertFalse(readiness.ready)
        self.assertIn("allowed_hosts", readiness.detail)

    def test_metadata_only_traces_never_include_content(self):
        client = FakeClient()
        tracing = ForgeTracing(self.settings(), client, lambda **_: nullcontext(), "enabled")
        secret_prompt = "private product idea gsk_testvalue123"
        secret_answer = "private response"

        with tracing.turn("session", secret_prompt) as turn:
            with turn.generation([{"role": "user", "content": secret_prompt}], 2) as generation:
                generation.generation_result(
                    {"content": secret_answer, "_forge_usage": {"prompt_tokens": 4, "completion_tokens": 2}},
                    FakeProvider(),
                )
            with turn.tool("workspace_write_file", {"content": secret_prompt, "path": "x"}) as tool:
                tool.tool_result(secret_answer, approved=True, is_error=False)
            turn.finish(secret_answer)

        rendered = repr([client.starts, [item.updates for item in client.observations]])
        self.assertNotIn(secret_prompt, rendered)
        self.assertNotIn(secret_answer, rendered)
        self.assertIn("input_tokens", rendered)
        self.assertIn("workspace_write_file", rendered)

    def test_content_capture_is_explicit_and_masker_redacts_common_keys(self):
        client = FakeClient()
        tracing = ForgeTracing(self.settings(capture=True), client, lambda **_: nullcontext(), "enabled")
        with tracing.turn("session", "ordinary prompt"):
            pass
        self.assertEqual(client.starts[0]["input"], "ordinary prompt")
        masked = _mask_sensitive({"api_key": "value", "text": "Bearer abcdefghijklmnopqrstuvwxyz"})
        self.assertEqual(masked["api_key"], "[REDACTED]")
        self.assertEqual(masked["text"], "Bearer [REDACTED]")

    def test_flush_is_safe_and_explicit(self):
        client = FakeClient()
        tracing = ForgeTracing(self.settings(), client, lambda **_: nullcontext(), "enabled")
        tracing.flush()
        self.assertEqual(client.flushes, 1)


if __name__ == "__main__":
    unittest.main()
