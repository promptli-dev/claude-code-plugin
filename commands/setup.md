---
description: Set up Promptli Comms (email + phone for this agent) and start the background service
allowed-tools: Bash(promptli-claude:*), Bash(~/.local/bin/promptli-claude:*)
---

Help the user set up Promptli Comms for Claude Code.

1. Check whether `promptli-claude` is installed: run `promptli-claude version`. If it is missing, tell
   the user to run the installer in their own terminal and stop:
   `curl -fsSL https://comms.promptli.com/install/claude.sh | sh`
2. Run `promptli-claude status --json`. If it is already configured, show the agent, address, number and
   service state, and offer `promptli-claude doctor`.
3. If it is not configured, ask the user to run `promptli-claude setup` in their own terminal. It shows a
   security warning they must accept, then opens their browser to log in and pick or create the agent
   (`--number` also offers a phone number). Never ask for an API key or a login code in chat and never
   put one on a command line.
4. Afterwards run `promptli-claude doctor` and explain any failing check.

$ARGUMENTS
