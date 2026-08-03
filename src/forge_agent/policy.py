from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class ToolPolicy:
    model_name: str
    mcp_name: str
    purpose: str
    approval: str


POLICIES: tuple[ToolPolicy, ...] = (
    ToolPolicy("workspace_list_files", "list_files", "List non-secret files inside the product workspace.", "never"),
    ToolPolicy("workspace_read_file", "read_file", "Read bounded text from a non-secret workspace file.", "never"),
    ToolPolicy("workspace_write_file", "write_file", "Create or atomically replace one workspace text file.", "always"),
    ToolPolicy("workspace_replace_text", "replace_text", "Replace one exact text occurrence in a workspace file.", "always"),
    ToolPolicy("workspace_run_check", "run_command", "Run one allowlisted test or inspection command without a shell.", "always"),
)

POLICY_BY_MODEL_NAME = {policy.model_name: policy for policy in POLICIES}
POLICY_BY_MCP_NAME = {policy.mcp_name: policy for policy in POLICIES}


def sanitize_schema(value: Any, depth: int = 0) -> dict[str, Any]:
    """Keep validation structure while dropping prompt-bearing annotations."""
    if depth > 8 or not isinstance(value, dict):
        return {}
    clean: dict[str, Any] = {}
    kind = value.get("type")
    if kind in {"object", "array", "string", "integer", "number", "boolean", "null"}:
        clean["type"] = kind
    if isinstance(value.get("enum"), list) and len(value["enum"]) <= 100:
        clean["enum"] = value["enum"]
    if isinstance(value.get("properties"), dict):
        clean["properties"] = {
            str(name): sanitize_schema(schema, depth + 1)
            for name, schema in value["properties"].items()
            if isinstance(name, str) and len(name) <= 100
        }
    if isinstance(value.get("required"), list):
        clean["required"] = [item for item in value["required"] if isinstance(item, str)]
    if isinstance(value.get("items"), dict):
        clean["items"] = sanitize_schema(value["items"], depth + 1)
    if clean.get("type") == "object":
        clean["additionalProperties"] = False
    return clean or {"type": "object", "properties": {}, "additionalProperties": False}


def as_model_tool(mcp_tool: Any, policy: ToolPolicy) -> dict[str, Any]:
    schema = getattr(mcp_tool, "input_schema", None)
    if schema is None:
        schema = getattr(mcp_tool, "inputSchema", {})
    return {
        "type": "function",
        "function": {
            "name": policy.model_name,
            "description": policy.purpose,
            "parameters": sanitize_schema(schema),
        },
    }


class ApprovalGate:
    def __init__(self, input_fn: Callable[[str], str] = input, output_fn: Callable[[str], None] = print):
        self.input_fn = input_fn
        self.output_fn = output_fn

    def approve(self, policy: ToolPolicy, arguments: dict[str, Any]) -> bool:
        if policy.approval == "never":
            return True
        self.output_fn("\nApproval required")
        self.output_fn(f"Action: {policy.purpose}")
        self.output_fn(f"Tool:   {policy.model_name}")
        self.output_fn("Arguments:")
        self.output_fn(json.dumps(arguments, indent=2, ensure_ascii=False, sort_keys=True))
        answer = self.input_fn("Allow this one action? Type 'yes' to allow: ").strip().lower()
        return answer == "yes"
