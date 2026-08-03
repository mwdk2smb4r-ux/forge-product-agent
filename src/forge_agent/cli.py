from __future__ import annotations

import argparse
import asyncio
import importlib.metadata
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator

from .agent import ProductAgent
from .config import Settings, load_settings
from .mcp_client import WorkspaceMCP
from .policy import ApprovalGate
from .providers import OpenAICompatibleProvider, ProviderChain, ProviderError
from .tracing import ForgeTracing, tracing_readiness


HELP = """Commands:
  /help                Show this help
  /status              Show configuration and conversation size
  /tools               Show available MCP tools and approval policy
  /save [name]         Save a local session snapshot
  /new                 Clear the current conversation
  /quit                Exit
"""


def _provider(settings: Settings) -> ProviderChain:
    configured = (settings.provider, *settings.fallback_providers)
    providers = [
        OpenAICompatibleProvider(
            provider_settings,
            provider_settings.model,
            settings.max_output_tokens,
            settings.request_timeout_seconds,
        )
        for provider_settings in configured
    ]
    return ProviderChain(providers)


def _doctor(settings: Settings, provider: ProviderChain) -> int:
    try:
        sdk_version = importlib.metadata.version("mcp")
    except importlib.metadata.PackageNotFoundError:
        sdk_version = "not installed"
    print("Forge doctor")
    print(f"  config:       {settings.config_path}")
    print(f"  workspace:    {settings.workspace.root}")
    print(
        "  project code execution: "
        + ("enabled (trusted projects only)" if settings.workspace.allow_project_code_execution else "blocked")
    )
    print(f"  provider chain: {provider.description}")
    for position, configured in enumerate(provider.providers):
        label = "primary" if position == 0 else f"fallback {position}"
        print(f"  {label}: {configured.name} / {configured.model}")
        print(f"    endpoint:   {configured.settings.base_url}")
        print(f"    credential: {'present' if configured.credential_present() else 'missing'}")
    print(f"  MCP SDK:      {sdk_version}")
    print(f"  MCP transport: local stdio only")
    print(f"  research:     {'enabled' if settings.research.enabled else 'disabled'}")
    if settings.research.enabled:
        if settings.research.search_provider == "none":
            search_status = "disabled"
        else:
            search_status = (
                f"{settings.research.search_provider} (ready)"
                if os.environ.get(settings.research.search_api_key_env)
                else f"{settings.research.search_provider} (optional key missing)"
            )
        print(f"    direct URL: available")
        print(f"    public GitHub: available")
        print(f"    web search: {search_status}")
    tracing_status = tracing_readiness(settings.tracing)
    print(f"  Langfuse:     {tracing_status.detail}")
    if settings.tracing.enabled:
        try:
            langfuse_version = importlib.metadata.version("langfuse")
        except importlib.metadata.PackageNotFoundError:
            langfuse_version = "not installed (install the tracing extra)"
        print(f"    SDK:        {langfuse_version}")
        print(f"    content:    {'captured' if settings.tracing.capture_content else 'redacted (metadata-only)'}")
    return 0 if provider.credential_present() and sdk_version == "2.0.0" else 1


@asynccontextmanager
async def _maybe_mcp(settings: Settings, enabled: bool) -> AsyncIterator[WorkspaceMCP | None]:
    if not enabled:
        yield None
        return
    async with WorkspaceMCP(settings.workspace, settings.tool_output_limit, settings.research) as mcp:
        yield mcp


@asynccontextmanager
async def _maybe_tracing(settings: Settings) -> AsyncIterator[ForgeTracing]:
    tracing = ForgeTracing.from_settings(settings.tracing)
    try:
        yield tracing
    finally:
        tracing.flush()


async def _run(args: argparse.Namespace) -> int:
    settings = load_settings(args.config)
    provider = _provider(settings)
    if args.doctor:
        return _doctor(settings, provider)
    if not provider.credential_present():
        raise ProviderError("No configured generation provider has its required credential. Use --doctor for details.")
    async with _maybe_tracing(settings) as tracing, _maybe_mcp(settings, not args.no_tools) as mcp:
        gate = ApprovalGate()
        agent = ProductAgent(provider, mcp, gate, settings.max_tool_rounds, tracing=tracing)
        if args.message:
            response = await agent.run_turn(args.message)
            print(response)
            return 0

        print("Forge Product Agent")
        print(f"Provider chain: {provider.description}")
        print(f"Workspace: {settings.workspace.root}")
        print("MCP: bundled local workspace and research servers" if mcp else "MCP: disabled")
        print(f"Tracing: {tracing.detail}")
        print("Type /help for commands. Start by describing your idea.\n")
        while True:
            try:
                text = input("you> ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nGoodbye.")
                return 0
            if not text:
                continue
            if text == "/quit":
                return 0
            if text == "/help":
                print(HELP)
                continue
            if text == "/status":
                print(f"Provider chain: {provider.description}")
                print(f"Last provider used: {provider.active_name} / {provider.active_model}")
                print(f"Execution location: {provider.active_location}")
                print(f"Workspace: {settings.workspace.root}")
                print(f"Research tools: {'enabled' if settings.research.enabled else 'disabled'}")
                if settings.research.enabled:
                    print(f"Search provider: {settings.research.search_provider}")
                print(f"Tracing: {tracing.detail}")
                print(f"Conversation messages: {len(agent.messages) - 1}")
                continue
            if text == "/tools":
                if not mcp:
                    print("MCP tools are disabled.")
                else:
                    for policy in mcp.policies:
                        approval = policy.approval
                        if policy.model_name == "workspace_read_file" and not provider.active_is_local:
                            approval = "always while using a remote model"
                        print(f"{policy.model_name}: approval={approval} — {policy.purpose}")
                continue
            if text.startswith("/save"):
                supplied = text.partition(" ")[2].strip()
                name = supplied or datetime.now(timezone.utc).strftime("session-%Y%m%d-%H%M%S")
                path = agent.save(settings.config_path.parent / ".forge_agent" / "sessions", name)
                print(f"Saved: {path}")
                continue
            if text == "/new":
                if input("Clear this conversation? Type 'yes' to confirm: ").strip().lower() == "yes":
                    agent.reset()
                    print("Started a new conversation.")
                continue
            try:
                response = await agent.run_turn(text)
            except ProviderError as exc:
                print(f"Provider error: {exc}", file=sys.stderr)
                continue
            print(f"\nforge [{provider.active_name}/{provider.active_model}]> {response}\n")


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Brainstorm and build maintainable products with human-approved MCP tools.")
    parser.add_argument("--config", default="forge.toml", help="Path to the TOML configuration file")
    parser.add_argument("--message", help="Run one prompt and exit")
    parser.add_argument("--no-tools", action="store_true", help="Disable all bundled MCP tools")
    parser.add_argument("--doctor", action="store_true", help="Validate local configuration without making network requests")
    args = parser.parse_args()
    try:
        raise_code = asyncio.run(_run(args))
    except (FileNotFoundError, ValueError, ProviderError, RuntimeError) as exc:
        print(f"Forge could not start: {exc}", file=sys.stderr)
        raise_code = 1
    raise SystemExit(raise_code)


if __name__ == "__main__":
    main()
