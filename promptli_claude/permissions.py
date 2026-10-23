"""Tool permissions: follow the owner's Claude Code settings, deny everything else.

Claude Code applies the user's/project's `permissions.allow|deny` rules itself (we load them with
`setting_sources`). A tool only reaches `can_use_tool` when no rule pre-approved it; there is no human at
the keyboard to ask, so we deny it, except for our own Promptli tools.
"""

from __future__ import annotations

from typing import Any

from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny, ToolPermissionContext

PROMPTLI_PREFIX = "mcp__promptli__"


def deny_message(tool_name: str) -> str:
    return (
        f"{tool_name} is not pre-approved for this agent. Your owner can allow it by adding it to "
        "permissions.allow in their Claude Code settings. Continue without it."
    )


async def can_use_tool(
    tool_name: str, tool_input: dict[str, Any], context: ToolPermissionContext
) -> PermissionResultAllow | PermissionResultDeny:
    del tool_input, context
    if tool_name.startswith(PROMPTLI_PREFIX):
        return PermissionResultAllow()
    return PermissionResultDeny(message=deny_message(tool_name))
