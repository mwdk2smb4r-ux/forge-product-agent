from __future__ import annotations

import ipaddress
import os
import re
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator, Mapping
from urllib.parse import urlparse

from .config import TracingSettings


LANGFUSE_ENV_VARS = ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_BASE_URL")


@dataclass(frozen=True)
class TracingReadiness:
    ready: bool
    detail: str


def tracing_readiness(settings: TracingSettings, environ: Mapping[str, str] | None = None) -> TracingReadiness:
    if not settings.enabled:
        return TracingReadiness(False, "disabled in forge.toml")
    environment = os.environ if environ is None else environ
    missing = [name for name in LANGFUSE_ENV_VARS if not environment.get(name, "").strip()]
    if missing:
        return TracingReadiness(False, "missing " + ", ".join(missing))
    try:
        _validate_langfuse_base_url(environment["LANGFUSE_BASE_URL"], settings.allowed_hosts)
    except ValueError as exc:
        return TracingReadiness(False, str(exc))
    return TracingReadiness(True, "ready (metadata-only)" if not settings.capture_content else "ready (content capture enabled)")


def _validate_langfuse_base_url(value: str, allowed_hosts: tuple[str, ...]) -> str:
    base_url = value.strip().rstrip("/")
    parsed = urlparse(base_url)
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("LANGFUSE_BASE_URL cannot contain credentials, a query, or a fragment")
    hostname = (parsed.hostname or "").lower()
    if hostname not in allowed_hosts:
        raise ValueError("LANGFUSE_BASE_URL host is not listed in tracing.allowed_hosts")
    if parsed.scheme == "https" and hostname:
        return base_url
    if parsed.scheme == "http" and hostname:
        try:
            if ipaddress.ip_address(hostname).is_loopback:
                return base_url
        except ValueError:
            if hostname == "localhost":
                return base_url
    raise ValueError("LANGFUSE_BASE_URL must use HTTPS (HTTP is allowed only for loopback)")


def _content(value: str, capture: bool) -> Any:
    if capture:
        return value
    return {"redacted": True, "characters": len(value)}


def _tool_input(arguments: Mapping[str, Any], capture: bool) -> Any:
    if capture:
        return dict(arguments)
    return {"redacted": True, "argument_names": sorted(str(key) for key in arguments)}


def _mask_sensitive(value: Any) -> Any:
    """Defense-in-depth masking for explicitly enabled content capture."""
    sensitive_names = ("authorization", "api_key", "apikey", "password", "secret", "token")
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if any(name in str(key).lower() for name in sensitive_names) else _mask_sensitive(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_mask_sensitive(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_mask_sensitive(item) for item in value)
    if isinstance(value, str):
        masked = re.sub(r"(?i)bearer\s+[a-z0-9._~+/=-]{12,}", "Bearer [REDACTED]", value)
        masked = re.sub(r"\b(?:gsk_|hf_|sk-lf-)[A-Za-z0-9_-]{12,}\b", "[REDACTED]", masked)
        return masked
    return value


def _usage(message: Mapping[str, Any]) -> dict[str, int] | None:
    raw = message.get("_forge_usage")
    if not isinstance(raw, Mapping):
        return None
    mapped: dict[str, int] = {}
    for source, target in (
        ("prompt_tokens", "input_tokens"),
        ("completion_tokens", "output_tokens"),
        ("total_tokens", "total_tokens"),
    ):
        value = raw.get(source)
        if isinstance(value, int) and value >= 0:
            mapped[target] = value
    return mapped or None


class _Observation:
    def __init__(self, observation: Any | None, capture_content: bool):
        self._observation = observation
        self._capture_content = capture_content

    def generation_result(self, message: Mapping[str, Any], provider: Any) -> None:
        tool_calls = message.get("tool_calls") or []
        model = getattr(provider, "active_model", "unknown")
        provider_name = getattr(provider, "active_name", "unknown")
        is_local = bool(getattr(provider, "active_is_local", False))
        self._update(
            output=_content(str(message.get("content") or ""), self._capture_content),
            model=model,
            usage_details=_usage(message),
            metadata={
                "provider": provider_name,
                "execution": "local" if is_local else "remote",
                "tool_call_count": len(tool_calls),
            },
        )

    def tool_result(self, result: str, *, approved: bool | None, is_error: bool) -> None:
        self._update(
            output=_content(result, self._capture_content),
            level="ERROR" if is_error else "DEFAULT",
            status_message="tool-error" if is_error else None,
            metadata={"approved": approved, "is_error": is_error},
        )

    def failure(self, exc: BaseException) -> None:
        self._update(
            level="ERROR",
            status_message=type(exc).__name__,
            metadata={"error_type": type(exc).__name__},
        )

    def _update(self, **values: Any) -> None:
        if self._observation is None:
            return
        try:
            self._observation.update(**{key: value for key, value in values.items() if value is not None})
        except Exception:
            pass


class _TurnTrace(_Observation):
    def __init__(self, owner: ForgeTracing, observation: Any | None):
        super().__init__(observation, owner.capture_content)
        self._owner = owner

    @contextmanager
    def generation(self, messages: list[dict[str, Any]], tool_count: int) -> Iterator[_Observation]:
        input_value: Any
        if self._owner.capture_content:
            input_value = messages
        else:
            input_value = {"redacted": True, "message_count": len(messages), "available_tool_count": tool_count}
        with self._owner._observation(
            "generate-response", "generation", input=input_value
        ) as observation:
            yield observation

    @contextmanager
    def tool(self, name: str, arguments: Mapping[str, Any]) -> Iterator[_Observation]:
        with self._owner._observation(
            "execute-tool", "tool", input=_tool_input(arguments, self._owner.capture_content), metadata={"tool": name}
        ) as observation:
            yield observation

    def finish(self, response: str) -> None:
        self._update(output=_content(response, self._capture_content))


class ForgeTracing:
    """Optional Langfuse adapter that never lets telemetry break the agent."""

    def __init__(
        self,
        settings: TracingSettings,
        client: Any | None = None,
        propagate_attributes: Any | None = None,
        detail: str = "disabled",
    ):
        self.capture_content = settings.capture_content
        self.environment = settings.environment
        self._client = client
        self._propagate_attributes = propagate_attributes
        self.detail = detail

    @classmethod
    def disabled(cls) -> ForgeTracing:
        return cls(TracingSettings(False, False, "local", 1.0, ("cloud.langfuse.com",)))

    @classmethod
    def from_settings(cls, settings: TracingSettings) -> ForgeTracing:
        readiness = tracing_readiness(settings)
        if not readiness.ready:
            return cls(settings, detail=readiness.detail)
        try:
            from langfuse import Langfuse, propagate_attributes
            from opentelemetry.sdk.trace import TracerProvider

            base_url = _validate_langfuse_base_url(os.environ["LANGFUSE_BASE_URL"], settings.allowed_hosts)
            client = Langfuse(
                public_key=os.environ["LANGFUSE_PUBLIC_KEY"],
                secret_key=os.environ["LANGFUSE_SECRET_KEY"],
                base_url=base_url,
                environment=settings.environment,
                sample_rate=settings.sample_rate,
                tracer_provider=TracerProvider(),
                mask_otel_spans=_mask_sensitive,
            )
        except Exception as exc:
            return cls(settings, detail=f"unavailable ({type(exc).__name__})")
        detail = "enabled (content capture)" if settings.capture_content else "enabled (metadata-only)"
        return cls(settings, client, propagate_attributes, detail)

    @property
    def enabled(self) -> bool:
        return self._client is not None

    @contextmanager
    def turn(self, session_id: str, user_text: str) -> Iterator[_TurnTrace]:
        if self._client is None:
            yield _TurnTrace(self, None)
            return
        attributes_context = None
        observation_context = None
        try:
            attributes_context = self._propagate_attributes(
                session_id=session_id,
                version="0.4.0",
                trace_name="forge-turn",
                environment=self.environment,
            )
            attributes_context.__enter__()
            observation_context = self._client.start_as_current_observation(
                name="forge-turn",
                as_type="agent",
                input=_content(user_text, self.capture_content),
                metadata={"privacy": "content" if self.capture_content else "metadata-only"},
            )
            root = observation_context.__enter__()
        except Exception:
            if observation_context is not None:
                try:
                    observation_context.__exit__(None, None, None)
                except Exception:
                    pass
            if attributes_context is not None:
                try:
                    attributes_context.__exit__(None, None, None)
                except Exception:
                    pass
            yield _TurnTrace(self, None)
            return
        trace = _TurnTrace(self, root)
        try:
            yield trace
        except BaseException as exc:
            trace.failure(exc)
            raise
        finally:
            try:
                observation_context.__exit__(None, None, None)
            except Exception:
                pass
            try:
                attributes_context.__exit__(None, None, None)
            except Exception:
                pass

    @contextmanager
    def _observation(self, name: str, as_type: str, **values: Any) -> Iterator[_Observation]:
        if self._client is None:
            yield _Observation(None, self.capture_content)
            return
        try:
            context = self._client.start_as_current_observation(name=name, as_type=as_type, **values)
            raw = context.__enter__()
        except Exception:
            yield _Observation(None, self.capture_content)
            return
        observation = _Observation(raw, self.capture_content)
        try:
            yield observation
        except BaseException as exc:
            observation.failure(exc)
            raise
        finally:
            try:
                context.__exit__(None, None, None)
            except Exception:
                pass

    def flush(self) -> None:
        if self._client is not None:
            try:
                self._client.flush()
            except Exception:
                pass
