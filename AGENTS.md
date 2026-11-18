# AGENTS.md: claude-code-plugin

Claude Code adapter for Promptli Comms. Keep this repo thin: transport, dedupe, sessions-by-contact,
framing, setup and doctor belong in `promptli-gateway` (promptli-comms repo), not here.

- `promptli_claude/adapter.py`: ClaudeCodeAdapter (one ClaudeSDKClient per contact_key, partial-message streaming, resume).
- `promptli_claude/permissions.py`: follow the user's settings; deny anything not pre-approved; allow `mcp__promptli__*`.
- `promptli_claude/tools.py`: gateway ToolSpecs → in-process SDK MCP server `promptli`.
- `promptli_claude/prompts.py`: system prompt append + the stranger/prompt-injection warning shown at setup.
- `promptli_claude/cli.py`: `promptli-claude` Typer CLI (runtime id / config dir: `promptli-claude`).
- `.claude-plugin/`, `skills/`, `commands/`: the Claude Code plugin + marketplace (validate with `claude plugin validate --strict .`).
  The plugin's MCP server is the hosted `https://api.comms.promptli.com/mcp` (OAuth), so the plugin works without the
  background service; keep it that way (it is listed in Anthropic's plugin directory, which scans every commit on `main`).
  Keep the skill's tool list in sync with the hosted server's tools, and raise `version` in both `plugin.json` and
  `marketplace.json` with every plugin change.
- `install.sh`: curl installer (own venv under ~/.local/share/promptli-claude, shim in ~/.local/bin).

Rules:
- Never print, log or commit API keys. Keys are read from hidden input, env or stdin, never argv.
- Never set `permission_mode` to anything that bypasses the user's rules; never add blanket `allowed_tools`.
- `promptli` / `promptli-gateway` come from PyPI with the same range in `pyproject.toml` and `install.sh`; bump both together.
- Checks: `uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest`.
