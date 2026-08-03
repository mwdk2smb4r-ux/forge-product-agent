import unittest
from types import SimpleNamespace

from forge_agent.config import ProviderSettings
from forge_agent.providers import OpenAICompatibleProvider, ProviderChain, ProviderError


class FakeProvider:
    def __init__(self, name, model, result=None, error=None, credential=True):
        self.name = name
        self.model = model
        self.result = result
        self.error = error
        self.credential = credential
        self.calls = 0
        self.settings = SimpleNamespace(base_url=f"https://{name}.example/v1")

    def credential_present(self):
        return self.credential

    async def complete(self, messages, tools):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result


class ProviderChainTests(unittest.IsolatedAsyncioTestCase):
    async def test_falls_back_on_rate_limit(self):
        primary = FakeProvider("groq", "large", error=ProviderError("quota", status_code=429))
        local = FakeProvider("local", "forge-local", result={"content": "local answer"})
        notices = []
        chain = ProviderChain([primary, local], notices.append)
        result = await chain.complete([], [])
        self.assertEqual(result["content"], "local answer")
        self.assertEqual(chain.active_name, "local")
        self.assertEqual(local.calls, 1)
        self.assertIn("switching", notices[0])
        await chain.complete([], [])
        self.assertEqual(primary.calls, 1)
        self.assertEqual(local.calls, 2)

    async def test_does_not_hide_authentication_error(self):
        primary = FakeProvider("groq", "large", error=ProviderError("unauthorized", status_code=401))
        local = FakeProvider("local", "forge-local", result={"content": "local answer"})
        chain = ProviderChain([primary, local], lambda _: None)
        with self.assertRaises(ProviderError):
            await chain.complete([], [])
        self.assertEqual(local.calls, 0)

    async def test_starts_on_local_when_primary_credential_is_missing(self):
        primary = FakeProvider("groq", "large", credential=False)
        local = FakeProvider("local", "forge-local", result={"content": "local answer"})
        chain = ProviderChain([primary, local], lambda _: None)

        self.assertTrue(chain.credential_present())
        self.assertEqual(chain.active_name, "local")
        result = await chain.complete([], [])

        self.assertEqual(result["content"], "local answer")
        self.assertEqual(primary.calls, 0)
        self.assertEqual(local.calls, 1)

    async def test_reports_no_credential_when_every_provider_requires_one(self):
        primary = FakeProvider("groq", "large", credential=False)
        fallback = FakeProvider("hosted", "small", credential=False)
        chain = ProviderChain([primary, fallback], lambda _: None)

        self.assertFalse(chain.credential_present())
        with self.assertRaisesRegex(ProviderError, "No usable generation provider"):
            await chain.complete([], [])


class RuntimeIdentityTests(unittest.TestCase):
    def test_local_runtime_identity_is_injected_without_mutating_history(self):
        provider = OpenAICompatibleProvider(
            ProviderSettings("local", "http://127.0.0.1:1234/v1", "", "forge-local"),
            "forge-local",
            100,
            10,
        )
        original = [{"role": "system", "content": "Base instructions"}, {"role": "user", "content": "Who are you?"}]
        enriched = provider.messages_with_runtime_identity(original)
        self.assertEqual(original[0]["content"], "Base instructions")
        self.assertIn("Provider: local", enriched[0]["content"])
        self.assertIn("API model identifier: forge-local", enriched[0]["content"])
        self.assertIn("local LM Studio", enriched[0]["content"])


if __name__ == "__main__":
    unittest.main()
