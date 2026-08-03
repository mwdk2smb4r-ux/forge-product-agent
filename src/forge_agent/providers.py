from __future__ import annotations

import asyncio
import json
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from .config import ProviderSettings


class ProviderError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@dataclass
class OpenAICompatibleProvider:
    settings: ProviderSettings
    model: str
    max_output_tokens: int
    timeout_seconds: int

    @property
    def name(self) -> str:
        return self.settings.name

    def credential_present(self) -> bool:
        return not self.settings.api_key_env or bool(os.environ.get(self.settings.api_key_env))

    def _credential(self) -> str:
        if not self.settings.api_key_env:
            return ""
        value = os.environ.get(self.settings.api_key_env, "")
        if not value:
            raise ProviderError(
                f"Missing {self.settings.api_key_env}. Set a replacement credential in your shell environment."
            )
        return value

    @property
    def execution_location(self) -> str:
        hostname = urllib.parse.urlparse(self.settings.base_url).hostname or ""
        if hostname in {"localhost", "127.0.0.1", "::1"}:
            return "local LM Studio endpoint on the user's computer"
        return f"remote cloud endpoint operated by {self.settings.name}"

    def messages_with_runtime_identity(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        identity = (
            "RUNTIME IDENTITY (authoritative host-supplied facts):\n"
            f"- Provider: {self.settings.name}\n"
            f"- API model identifier: {self.model}\n"
            f"- Execution location: {self.execution_location}\n"
            "Never claim to be a different model or to run in a different location. "
            "If asked about model identity or locality, answer from these facts only."
        )
        copied = [dict(message) for message in messages]
        if copied and copied[0].get("role") == "system":
            existing = str(copied[0].get("content") or "")
            copied[0]["content"] = f"{existing}\n\n{identity}"
        else:
            copied.insert(0, {"role": "system", "content": identity})
        return copied

    async def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
        return await asyncio.to_thread(self._complete_sync, messages, tools)

    def _complete_sync(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
        credential = self._credential()
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": self.messages_with_runtime_identity(messages),
            "temperature": 0.2,
            "max_tokens": self.max_output_tokens,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers = {"Content-Type": "application/json", "User-Agent": "forge-product-agent/0.1"}
        if credential:
            headers["Authorization"] = f"Bearer {credential}"
        request = urllib.request.Request(
            f"{self.settings.base_url}/chat/completions", data=body, headers=headers, method="POST"
        )
        try:
            opener = urllib.request.build_opener(
                urllib.request.HTTPSHandler(context=ssl.create_default_context()), _NoRedirect()
            )
            with opener.open(request, timeout=self.timeout_seconds) as response:
                raw = response.read(5_000_001)
                if len(raw) > 5_000_000:
                    raise ProviderError("Provider response exceeded 5 MB")
        except urllib.error.HTTPError as exc:
            detail = exc.read(4_000).decode("utf-8", errors="replace")
            if credential:
                detail = detail.replace(credential, "[REDACTED]")
            raise ProviderError(f"Provider returned HTTP {exc.code}: {detail}", status_code=exc.code) from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            detail = str(exc).replace(credential, "[REDACTED]") if credential else str(exc)
            raise ProviderError(f"Provider request failed: {detail}") from None
        try:
            data = json.loads(raw)
            message = data["choices"][0]["message"]
        except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
            raise ProviderError(f"Provider returned an invalid response: {exc}") from None
        if not isinstance(message, dict):
            raise ProviderError("Provider response message was not an object")
        return message


class ProviderChain:
    """Try providers in order, failing over only for quota/rate-limit responses."""

    FALLBACK_STATUS_CODES = {402, 429}

    def __init__(self, providers: list[OpenAICompatibleProvider], output_fn=print):
        if not providers:
            raise ValueError("ProviderChain requires at least one provider")
        self.providers = providers
        self.output_fn = output_fn
        self.last_used = providers[0]
        self._active_index = 0

    def credential_present(self) -> bool:
        return self.providers[0].credential_present()

    @property
    def active_name(self) -> str:
        return self.last_used.name

    @property
    def active_model(self) -> str:
        return self.last_used.model

    @property
    def active_location(self) -> str:
        return self.last_used.execution_location

    @property
    def description(self) -> str:
        return " -> ".join(f"{provider.name}/{provider.model}" for provider in self.providers)

    async def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
        failures: list[str] = []
        for index in range(self._active_index, len(self.providers)):
            provider = self.providers[index]
            try:
                result = await provider.complete(messages, tools)
                self.last_used = provider
                self._active_index = index
                return result
            except ProviderError as exc:
                failures.append(f"{provider.name}: {exc}")
                has_fallback = index + 1 < len(self.providers)
                if not has_fallback or exc.status_code not in self.FALLBACK_STATUS_CODES:
                    raise
                next_provider = self.providers[index + 1]
                self._active_index = index + 1
                self.output_fn(
                    f"\n{provider.name} returned HTTP {exc.status_code}; switching this request to "
                    f"{next_provider.name}/{next_provider.model}."
                )
        raise ProviderError("All providers failed: " + "; ".join(failures))
