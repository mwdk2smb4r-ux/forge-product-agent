from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Callable

from .mcp_client import WorkspaceMCP
from .policy import ApprovalGate
from .prompts import SYSTEM_PROMPT
from .providers import ProviderChain
from .tracing import ForgeTracing


class ProductAgent:
    def __init__(
        self,
        provider: ProviderChain,
        mcp: WorkspaceMCP | None,
        approval_gate: ApprovalGate,
        max_tool_rounds: int,
        output_fn: Callable[[str], None] = print,
        tracing: ForgeTracing | None = None,
    ):
        self.provider = provider
        self.mcp = mcp
        self.approval_gate = approval_gate
        self.max_tool_rounds = max_tool_rounds
        self.output_fn = output_fn
        self.tracing = tracing or ForgeTracing.disabled()
        self.session_id = uuid.uuid4().hex
        self.messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]

    async def run_turn(self, user_text: str) -> str:
        self.messages.append({"role": "user", "content": user_text})
        tools = self.mcp.model_tools if self.mcp else []
        with self.tracing.turn(self.session_id, user_text) as turn_trace:
            response = await self._run_tool_loop(tools, turn_trace)
            turn_trace.finish(response)
            return response

    async def _run_tool_loop(self, tools: list[dict[str, Any]], turn_trace: Any) -> str:
        for tool_round in range(self.max_tool_rounds + 1):
            with turn_trace.generation(self.messages, len(tools)) as generation:
                message = await self.provider.complete(self.messages, tools)
                generation.generation_result(message, self.provider)
            assistant_message: dict[str, Any] = {"role": "assistant", "content": message.get("content")}
            tool_calls = message.get("tool_calls") or []
            if tool_calls:
                assistant_message["tool_calls"] = tool_calls
            self.messages.append(assistant_message)
            if not tool_calls:
                return str(message.get("content") or "")
            if tool_round >= self.max_tool_rounds:
                for call in tool_calls:
                    self.messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": str(call.get("id", "missing-call-id")),
                            "name": str((call.get("function") or {}).get("name", "")),
                            "content": json.dumps({"is_error": True, "error": "tool-round limit reached"}),
                        }
                    )
                warning = "Stopped because the tool-round limit was reached. Review the current state before continuing."
                self.messages.append({"role": "assistant", "content": warning})
                return warning
            if message.get("content"):
                self.output_fn(f"\nforge> {message['content']}")
            for call in tool_calls:
                call_id = str(call.get("id", "missing-call-id"))
                function = call.get("function") or {}
                name = str(function.get("name", ""))
                approved: bool | None = None
                invalid_result: str | None = None
                try:
                    arguments = json.loads(function.get("arguments") or "{}")
                    if not isinstance(arguments, dict):
                        raise ValueError("arguments must be an object")
                except (json.JSONDecodeError, ValueError) as exc:
                    arguments = {}
                    invalid_result = json.dumps({"is_error": True, "error": f"invalid tool arguments: {exc}"})
                with turn_trace.tool(name, arguments) as tool_trace:
                    if invalid_result is not None:
                        result = invalid_result
                    else:
                        policy = self.mcp.policy_for_model_name(name) if self.mcp else None
                        if policy is None:
                            result = json.dumps({"is_error": True, "error": "tool is not allowlisted"})
                        else:
                            remote_workspace_read = (
                                name == "workspace_read_file" and not self.provider.active_is_local
                            )
                            approved = self.approval_gate.approve(
                                policy,
                                arguments,
                                force=remote_workspace_read,
                                reason=(
                                    "A remote model is requesting workspace file contents."
                                    if remote_workspace_read
                                    else ""
                                ),
                            )
                            if not approved:
                                result = json.dumps({"is_error": True, "error": "user denied this one action"})
                            else:
                                result = await self.mcp.call(name, arguments)
                    tool_trace.tool_result(result, approved=approved, is_error=_tool_result_is_error(result))
                self.messages.append({"role": "tool", "tool_call_id": call_id, "name": name, "content": result})
        raise AssertionError("unreachable tool loop state")

    def reset(self) -> None:
        self.messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        self.session_id = uuid.uuid4().hex

    def save(self, directory: Path, name: str) -> Path:
        safe_name = "".join(character for character in name if character.isalnum() or character in "-_")[:60]
        if not safe_name:
            safe_name = "session"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{safe_name}.json"
        suffix = 1
        while path.exists():
            path = directory / f"{safe_name}-{suffix}.json"
            suffix += 1
        path.write_text(json.dumps({"version": 1, "messages": self.messages[1:]}, indent=2, ensure_ascii=False), encoding="utf-8")
        return path


def _tool_result_is_error(result: str) -> bool:
    try:
        payload = json.loads(result)
    except (json.JSONDecodeError, TypeError):
        return False
    return isinstance(payload, dict) and bool(payload.get("is_error"))
