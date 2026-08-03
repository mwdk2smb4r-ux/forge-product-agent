from __future__ import annotations

import ipaddress
import tomllib
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


@dataclass(frozen=True)
class ProviderSettings:
    name: str
    base_url: str
    api_key_env: str
    model: str


@dataclass(frozen=True)
class WorkspaceSettings:
    root: Path
    max_file_bytes: int
    command_timeout_seconds: int
    allowed_commands: tuple[str, ...]


@dataclass(frozen=True)
class Settings:
    config_path: Path
    provider: ProviderSettings
    fallback_providers: tuple[ProviderSettings, ...]
    model: str
    workspace: WorkspaceSettings
    max_output_tokens: int
    max_tool_rounds: int
    request_timeout_seconds: int
    tool_output_limit: int


def _bounded_int(value: object, default: int, low: int, high: int, name: str) -> int:
    number = default if value is None else int(value)
    if not low <= number <= high:
        raise ValueError(f"{name} must be between {low} and {high}")
    return number


def _safe_base_url(value: str) -> str:
    value = value.rstrip("/")
    parsed = urlparse(value)
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Provider base_url cannot contain credentials, a query, or a fragment")
    if parsed.scheme == "https" and parsed.hostname:
        return value
    if parsed.scheme == "http" and parsed.hostname:
        try:
            if ipaddress.ip_address(parsed.hostname).is_loopback:
                return value
        except ValueError:
            if parsed.hostname == "localhost":
                return value
    raise ValueError("Provider base_url must use HTTPS (HTTP is allowed only for loopback)")


def _safe_workspace(path: Path) -> Path:
    root = path.resolve()
    if root == Path(root.anchor) or root == Path.home().resolve():
        raise ValueError("Workspace cannot be a filesystem root or the whole home directory")
    return root


def load_settings(path: str | Path = "forge.toml") -> Settings:
    config_path = Path(path).resolve()
    if not config_path.is_file():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")
    data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    agent = data.get("agent", {})
    providers = data.get("providers", {})
    workspace_data = data.get("workspace", {})

    default_model = str(agent.get("model", "openai/gpt-oss-120b"))

    def provider_settings(name: str) -> ProviderSettings:
        provider_data = providers.get(name)
        if not isinstance(provider_data, dict):
            raise ValueError(f"Missing [providers.{name}] configuration")
        return ProviderSettings(
            name=name,
            base_url=_safe_base_url(str(provider_data.get("base_url", ""))),
            api_key_env=str(provider_data.get("api_key_env", "")),
            model=str(provider_data.get("model", default_model)),
        )

    provider_name = str(agent.get("provider", "groq"))
    provider = provider_settings(provider_name)
    fallback_value = agent.get("fallback_providers", [])
    if not isinstance(fallback_value, list) or any(not isinstance(item, str) for item in fallback_value):
        raise ValueError("fallback_providers must be an array of provider names")
    fallback_names = tuple(fallback_value)
    if provider_name in fallback_names or len(set(fallback_names)) != len(fallback_names):
        raise ValueError("fallback_providers cannot contain the primary provider or duplicates")
    fallback_providers = tuple(provider_settings(name) for name in fallback_names)

    workspace_value = Path(str(agent.get("workspace", "product_workspace")))
    if not workspace_value.is_absolute():
        workspace_value = config_path.parent / workspace_value
    commands = tuple(str(item).lower() for item in workspace_data.get("allowed_commands", ["python", "py", "git"]))
    valid_commands = {"python", "py", "git", "npm"}
    if not commands or any(command not in valid_commands for command in commands):
        raise ValueError(f"allowed_commands must be a non-empty subset of {sorted(valid_commands)}")

    return Settings(
        config_path=config_path,
        provider=provider,
        fallback_providers=fallback_providers,
        model=default_model,
        workspace=WorkspaceSettings(
            root=_safe_workspace(workspace_value),
            max_file_bytes=_bounded_int(workspace_data.get("max_file_bytes"), 1_000_000, 1_000, 10_000_000, "max_file_bytes"),
            command_timeout_seconds=_bounded_int(
                workspace_data.get("command_timeout_seconds"), 90, 5, 600, "command_timeout_seconds"
            ),
            allowed_commands=commands,
        ),
        max_output_tokens=_bounded_int(agent.get("max_output_tokens"), 4096, 256, 65_536, "max_output_tokens"),
        max_tool_rounds=_bounded_int(agent.get("max_tool_rounds"), 8, 1, 20, "max_tool_rounds"),
        request_timeout_seconds=_bounded_int(
            agent.get("request_timeout_seconds"), 120, 10, 600, "request_timeout_seconds"
        ),
        tool_output_limit=_bounded_int(agent.get("tool_output_limit"), 30_000, 1_000, 100_000, "tool_output_limit"),
    )
