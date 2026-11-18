# Promptli Comms for Claude Code

Give Claude its own email address and phone number. With this plugin, Claude can send and read email,
send texts, place and schedule phone calls, and remember the people it talks to, as your
[Promptli Comms](https://comms.promptli.com) agent.

The plugin has two parts:

1. **The plugin itself** (this is all you need to send and read): a connection to the hosted Promptli
   Comms MCP server at `https://api.comms.promptli.com/mcp`, a skill that teaches Claude how to use it,
   and the `/promptli-comms:setup`, `/promptli-comms:status` and `/promptli-comms:doctor` commands.
   It installs and runs nothing on your machine.
2. **An optional background service**, `promptli-claude`, that lets Claude Code *answer* people who
   email or text your agent while you are away. You install it yourself with a separate installer;
   see [Optional: answer inbound email and texts](#optional-answer-inbound-email-and-texts).

## Install

From the Claude Code plugin directory, or from this repository's marketplace:

```
/plugin marketplace add promptli-dev/claude-code-plugin
/plugin install promptli-comms@promptli
```

Then run `/mcp`, select `promptli` and choose **Authenticate**. Your browser opens the Promptli Comms
sign-in (OAuth 2.1 with PKCE). Create an account or log in, then pick or create the agent that Claude
acts as. Nothing is copied or pasted, and no API key is stored in Claude Code's settings. The
connection shows up in the Promptli console under **API keys → Connected apps**, where you can revoke it.

Run `/promptli-comms:setup` to check the connection.

## What Claude can do

| Tool | What it does |
| --- | --- |
| `whoami` | The agent, organization and environment (live or test) this connection acts as |
| `list_emails`, `send_email`, `reply_email` | Email from the agent's own address, keeping threads |
| `send_text` | SMS from the agent's phone number |
| `place_call`, `schedule_call`, `schedule_text`, `list_scheduled`, `cancel_scheduled` | Phone calls (the Promptli voice assistant can talk for you) and scheduled calls and texts |
| `get_call`, `get_call_transcript` | A call's outcome, summary and transcript |
| `list_conversations`, `get_conversation` | The history with a person across email, texts and calls |
| `lookup_contact`, `add_contact_memory` | Who someone is, and notes to remember about them |
| `get_usage` | Call minutes used this month |

A phone number, calls and higher sending limits depend on your Promptli Comms plan; see
[comms.promptli.com](https://comms.promptli.com).

## Data and privacy

- Every tool call goes to Promptli Comms at `api.comms.promptli.com`, over HTTPS, with the OAuth token
  you granted. Emails, texts, call transcripts and contact notes are stored by Promptli Comms so the
  agent can read its history; you can see them in the console.
- Messages you send leave through Promptli's email, SMS and voice providers to the recipients you name.
- The plugin has no hooks and sends nothing anywhere else.
- Anything people send to your agent is untrusted. The skill tells Claude to treat it as data, not
  instructions, and to confirm before contacting someone you haven't named.

## Optional: answer inbound email and texts

```
person ──email/SMS──▶ Promptli Comms ──Agent Link (WebSocket)──▶ promptli-claude ──▶ Claude Code session
                                                                (on your Mac)       (one per person)
```

The `promptli-claude` service keeps an outbound WebSocket to Promptli and starts one Claude Code session
per person who writes to your agent:

- **No tunnels or webhooks.** It resumes from where it left off, so nothing is lost while your Mac sleeps.
- **One Claude Code session per person.** The same person by email and then by text lands in the same
  conversation. Sessions survive restarts (Claude session ids are persisted).
- **Your permissions.** Sessions load your Claude Code settings (`~/.claude/settings.json`, project and
  local settings). Tools you pre-approved in `permissions.allow` can run; anything else is denied
  automatically, because nobody is at the keyboard to approve it. Promptli's own tools are always allowed.

> **Security:** anyone who learns the agent's address or number can message it. Each person gets an
> isolated session, and inbound content is marked as untrusted, but Claude can still be talked into
> using any tool you allow. Keep `permissions.allow` tight for the project you point it at.

### Install the service (macOS; Linux for development)

Read [`install.sh`](install.sh) first if you like; it is short. Then:

```bash
curl -fsSL https://comms.promptli.com/install/claude.sh | sh
promptli-claude setup
```

The installer:
- installs [uv](https://docs.astral.sh/uv/) from astral.sh if it is missing;
- creates a virtualenv at `~/.local/share/promptli-claude/venv` and installs `promptli-claude` from this
  repository with `promptli` and `promptli-gateway` from PyPI, and links it to `~/.local/bin`;
- adds this repository as a Claude Code marketplace and installs this plugin (`PROMPTLI_SKIP_PLUGIN=1`
  skips that).

It never asks for or stores a key. `setup` shows the security warning, then **logs you in with your
browser**. There you pick an existing agent or create one (add `--number` to get it a phone number). Use
`--no-browser` over SSH, or `--api-key` to paste a key instead (an organization key is only used once to
mint an identity-scoped key). Then it starts the background service (launchd, starts at login). The
login refreshes itself and shows up under **API keys → Connected apps**, where you can revoke it.
`promptli-claude logout` revokes it from this machine. Credentials live in
`~/.promptli/promptli-claude/credentials` (mode 600). `promptli-claude uninstall --purge` removes the
service and its local state.

### Service commands

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

How the service replies:
- Claude's final answer is sent back on the channel the person used (a threaded email reply, or SMS
  without markdown).
- If Claude already replied with a tool, or answers `NO_REPLY`, nothing extra is sent.

### Service configuration

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
