"""Expose the gateway's runtime-agnostic ToolSpecs to Claude Code as an in-process SDK MCP server."""

from __future__ import annotations

import json
from typing import Any

from claude_agent_sdk import McpSdkServerConfig, SdkMcpTool, create_sdk_mcp_server
from promptli_gateway.tools import Handler, ToolSpec

from promptli_claude.permissions import PROMPTLI_PREFIX

SERVER_NAME = "promptli"


def _wrap(handler: Handler) -> Any:
    async def run(args: dict[str, Any]) -> dict[str, Any]:
        try:
            payload = await handler(dict(args or {}))
        except Exception as e:  # a tool failure must not kill the Claude turn
            payload = {"ok": False, "error": "tool_failed", "message": str(e)}
        return {
            "content": [{"type": "text", "text": json.dumps(payload, default=str)}],
            "is_error": not payload.get("ok", True),
        }

    return run


def build_mcp_server(tools: list[ToolSpec]) -> McpSdkServerConfig:
    return create_sdk_mcp_server(
        SERVER_NAME,
        version="0.1.0",
        tools=[SdkMcpTool(t.name, t.description, t.input_schema, _wrap(t.handler)) for t in tools],
    )


def allowed_tool_names(tools: list[ToolSpec]) -> list[str]:
    return [f"{PROMPTLI_PREFIX}{t.name}" for t in tools]
