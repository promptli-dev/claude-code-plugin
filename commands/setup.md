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
3. If it is not configured, ask the user to run `promptli-claude setup` in their own terminal (it asks
   for the API key with hidden input, and shows a security warning they must accept). Never ask for the
   API key in chat and never put it on a command line.
4. Afterwards run `promptli-claude doctor` and explain any failing check.

$ARGUMENTS
