# Promptli Comms for Claude Code

Give Claude Code its own email address and phone number. People email or text your agent, and Claude
Code answers in your project with your permissions. It can also send email and texts itself.

```
person ──email/SMS──▶ Promptli Comms ──Agent Link (WebSocket)──▶ promptli-claude ──▶ Claude Code session
                                                                (on your Mac)       (one per person)
```

- **No tunnels or webhooks.** The background service keeps an outbound WebSocket to Promptli and
  resumes from where it left off, so nothing is lost while your Mac sleeps.
- **One Claude Code session per person.** The same person by email and then by text lands in the same
  conversation. Sessions survive restarts (Claude session ids are persisted).
- **Streaming.** Replies are streamed from Claude as they are written (needed for phone calls, coming next).
- **Your permissions.** Sessions load your Claude Code settings (`~/.claude/settings.json`, project and
  local settings). Tools you pre-approved in `permissions.allow` can run; anything else is denied
  automatically, because nobody is at the keyboard to approve it. Promptli's own tools are always allowed.

> **Security:** anyone who learns the agent's address or number can message it. Each person gets an
> isolated session, and inbound content is marked as untrusted, but Claude can still be talked into
> using any tool you allow. Keep `permissions.allow` tight for the project you point it at.

## Install (macOS)

```bash
curl -fsSL https://comms.promptli.com/install/claude.sh | sh
promptli-claude setup
```

`setup` shows the security warning, then **logs you in with your browser**. There you pick an existing
agent or create one (add `--number` to get it a phone number); nothing is copied or pasted. Use
`--no-browser` over SSH, or `--api-key` to paste a key instead (an organization key is only used once to
mint an identity-scoped key). Then it starts the background service (launchd, starts at login). The
login refreshes itself and shows up under **API keys → Connected apps**, where you can revoke it.
`promptli-claude logout` revokes it from this machine. Credentials live in
`~/.promptli/promptli-claude/credentials` (mode 600).

The installer also adds this repo as a Claude Code plugin marketplace and installs the plugin, which
gives interactive Claude Code sessions the Promptli tools (`mcp__promptli__*`), a skill, and the
`/promptli-comms:setup`, `/promptli-comms:status` and `/promptli-comms:doctor` commands. To add it by hand:

```
/plugin marketplace add promptli-dev/claude-code-plugin
/plugin install promptli-comms@promptli
```

## Commands

| Command | What it does |
| --- | --- |
| `promptli-claude setup` | Interactive setup (browser login, key or signup; project directory; phone number with `--number`) |
| `promptli-claude logout` | Revoke this machine's login and stop the service (the agent is kept) |
| `promptli-claude bootstrap --identity <handle> --json` | Non-interactive and idempotent; uses the stored login, or a key from `PROMPTLI_API_KEY` |
| `promptli-claude signup --email you@x.com --handle my-agent` | Self-signup without a key |
| `promptli-claude verify <code>` | Confirm a self-signup with the emailed code |
| `promptli-claude start / stop / restart` | Manage the background service |
| `promptli-claude status` | Agent, address, number, service state |
| `promptli-claude doctor` | Key, channels, Agent Link, clock, service, Claude Code login |
| `promptli-claude logs -f` | Follow the service logs |
| `promptli-claude run -v` | Run in the foreground (debugging) |
| `promptli-claude uninstall [--purge]` | Stop the service; `--purge` deletes local config and state |

How replies work:
- Claude's final answer is sent back on the channel the person used (a threaded email reply, or SMS
  without markdown).
- If Claude already replied with a tool, or answers `NO_REPLY`, nothing extra is sent.

## Configuration

`~/.promptli/promptli-claude/config.json` (written by setup):
- `project_dir`: where Claude Code runs. Your `CLAUDE.md` and project settings apply there.
- `auto_reply`: send the final answer back automatically.
- `batch_window_s`: texts arriving within this window become one turn.
- `extra.model`: Claude model alias or id (default: your Claude Code default).

## Development

```bash
uv sync
uv run pytest                     # unit tests (fake Claude client, real gateway core)
uv run ruff check . && uv run pyright
# live: real Claude Code + a local Promptli stack in test mode
PROMPTLI_API_KEY=psk_test_... PROMPTLI_BASE_URL=http://localhost:8000 uv run pytest -m live tests/live
claude plugin validate --strict .
```

Install from a local checkout: `PROMPTLI_CLAUDE_SOURCE=$PWD sh install.sh`.

The runtime-independent pieces live in `promptli-gateway` (the [promptli-comms](https://github.com/promptli-dev/promptli-comms) repo):
- Agent Link, dedupe and acks.
- Contact-keyed queues, framing and auto-reply.
- Bootstrap, doctor, launchd, and the MCP stdio server.

This repo only adds the Claude Code adapter (`promptli_claude/adapter.py`), the plugin files and the CLI.
