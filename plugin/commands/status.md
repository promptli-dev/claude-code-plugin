---
description: Show the Promptli agent's address and number, and whether the optional background service is running
---

Call the `whoami` tool from the `promptli` MCP server and report the agent and environment. If it
needs authentication, tell the user to run `/mcp` and authenticate `promptli`.

Then, only if `promptli-claude` is installed (`promptli-claude version` succeeds), run
`promptli-claude status` for the background service. Summarise everything in two or three lines.
