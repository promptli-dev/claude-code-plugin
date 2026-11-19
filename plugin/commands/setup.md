---
description: Connect Promptli Comms (email, SMS and phone for this agent), and optionally set up the background service that answers inbound messages
---

Help the user set up Promptli Comms for Claude Code.

1. Call the `whoami` tool from the `promptli` MCP server. If it works, show the agent, organization
   and environment. If the tool is missing or needs authentication, ask the user to run `/mcp`,
   select `promptli` and authenticate in their browser (they pick or create the agent there), then
   try `whoami` again. Never ask for an API key or a login code in chat.
2. Explain that sending email and texts and placing calls now works through those tools. Ask whether
   they also want Claude Code to *answer* inbound email and texts automatically. Only if they do:
   a. Run `promptli-claude version`. If it is missing, show them the installer and tell them to run it
      in their own terminal (do not run it yourself), then stop:
      `curl -fsSL https://comms.promptli.com/install/claude.sh | sh`
      Mention that it installs uv (if missing) and a Python virtualenv under `~/.local/share/promptli-claude`.
   b. Run `promptli-claude status --json`. If it is already configured, show the agent, address,
      number and service state.
   c. Otherwise ask the user to run `promptli-claude setup` in their own terminal. It shows a security
      warning they must accept, then opens their browser to log in.
   d. Afterwards run `promptli-claude doctor` and explain any failing check.

$ARGUMENTS
