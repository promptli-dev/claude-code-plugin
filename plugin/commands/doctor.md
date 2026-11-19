---
description: Diagnose Promptli Comms (MCP sign-in, and the optional background service's key, channels, Agent Link, clock and Claude login)
---

1. Call the `whoami` tool from the `promptli` MCP server. If it fails, explain the fix (usually: run
   `/mcp`, select `promptli`, authenticate).
2. If `promptli-claude` is installed (`promptli-claude version` succeeds), run `promptli-claude doctor`.
   For every failing check, explain what it means and the exact fix.

If everything passes, say so in one line.
