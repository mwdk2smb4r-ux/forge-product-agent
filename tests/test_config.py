import tempfile
import unittest
from pathlib import Path

from forge_agent.config import load_settings


class ConfigTests(unittest.TestCase):
    def test_rejects_non_https_remote_provider(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "forge.toml"
            path.write_text(
                '[agent]\nprovider="bad"\nworkspace="work"\n[providers.bad]\nbase_url="http://example.com/v1"\napi_key_env="KEY"\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "HTTPS"):
                load_settings(path)

    def test_accepts_loopback_http(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "forge.toml"
            path.write_text(
                '[agent]\nprovider="local"\nworkspace="work"\n[providers.local]\nbase_url="http://127.0.0.1:11434/v1"\napi_key_env=""\n',
                encoding="utf-8",
            )
            settings = load_settings(path)
            self.assertEqual(settings.provider.name, "local")

    def test_project_code_execution_is_blocked_by_default(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "forge.toml"
            path.write_text(
                '[agent]\nprovider="local"\nworkspace="work"\n'
                '[providers.local]\nbase_url="http://127.0.0.1:1234/v1"\napi_key_env=""\n',
                encoding="utf-8",
            )
            settings = load_settings(path)
            self.assertFalse(settings.workspace.allow_project_code_execution)

    def test_rejects_url_credentials_and_fragments(self):
        for base_url in ("https://user@example.com/v1", "https://example.com/v1#other"):
            with self.subTest(base_url=base_url), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "forge.toml"
                path.write_text(
                    f'[agent]\nprovider="bad"\nworkspace="work"\n[providers.bad]\nbase_url="{base_url}"\napi_key_env="KEY"\n',
                    encoding="utf-8",
                )
                with self.assertRaises(ValueError):
                    load_settings(path)

    def test_groq_credential_is_pinned_to_the_groq_endpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "forge.toml"
            path.write_text(
                '[agent]\nprovider="bad"\nworkspace="work"\n'
                '[providers.bad]\nbase_url="https://attacker.example/v1"\napi_key_env="groq_api_key"\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "may only be sent"):
                load_settings(path)

    def test_loads_provider_specific_fallback_model(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "forge.toml"
            path.write_text(
                '[agent]\nprovider="groq"\nmodel="remote-model"\nfallback_providers=["local"]\nworkspace="work"\n'
                '[providers.groq]\nbase_url="https://api.groq.com/openai/v1"\napi_key_env="GROQ_API_KEY"\n'
                '[providers.local]\nbase_url="http://127.0.0.1:1234/v1"\napi_key_env=""\nmodel="forge-local"\n',
                encoding="utf-8",
            )
            settings = load_settings(path)
            self.assertEqual(settings.provider.model, "remote-model")
            self.assertEqual(settings.fallback_providers[0].model, "forge-local")

    def test_loads_bounded_research_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "forge.toml"
            path.write_text(
                '[agent]\nprovider="local"\nworkspace="work"\n'
                '[providers.local]\nbase_url="http://127.0.0.1:1234/v1"\napi_key_env=""\n'
                '[research]\nallowed_domains=["Example.com"]\nmax_redirects=1\nsearch_provider="none"\n',
                encoding="utf-8",
            )
            settings = load_settings(path)
            self.assertTrue(settings.research.enabled)
            self.assertEqual(settings.research.allowed_domains, ("example.com",))
            self.assertEqual(settings.research.max_redirects, 1)

    def test_perplexity_cannot_reuse_an_unrelated_secret_variable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "forge.toml"
            path.write_text(
                '[agent]\nprovider="local"\nworkspace="work"\n'
                '[providers.local]\nbase_url="http://127.0.0.1:1234/v1"\napi_key_env=""\n'
                '[research]\nsearch_provider="perplexity"\nsearch_api_key_env="GROQ_API_KEY"\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "dedicated PERPLEXITY_API_KEY"):
                load_settings(path)

    def test_rejects_domain_values_that_could_change_server_arguments(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "forge.toml"
            path.write_text(
                '[agent]\nprovider="local"\nworkspace="work"\n'
                '[providers.local]\nbase_url="http://127.0.0.1:1234/v1"\napi_key_env=""\n'
                '[research]\nallowed_domains=["safe.example,evil.example"]\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "Invalid research domain"):
                load_settings(path)


if __name__ == "__main__":
    unittest.main()
