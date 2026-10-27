#!/bin/sh
# Promptli Comms for Claude Code: installer.
#
#   curl -fsSL https://comms.promptli.com/install/claude.sh | sh
#
# Installs `promptli-claude` into its own virtualenv (~/.local/share/promptli-claude/venv), links it to
# ~/.local/bin, and adds the Claude Code plugin (skill, /commands, MCP tools) from the Promptli marketplace.
# It never asks for or stores an API key: run `promptli-claude setup` afterwards.
#
# Environment overrides:
#   PROMPTLI_CLAUDE_SOURCE  pip requirement or local path for the plugin  (default: GitHub main)
#   PROMPTLI_COMMS_REF      install the SDK/gateway from this git ref instead of PyPI (development)
#   PROMPTLI_COMMS_SOURCE   git URL used with PROMPTLI_COMMS_REF          (default: GitHub)
#   PROMPTLI_SKIP_PLUGIN=1  do not register the Claude Code plugin
set -eu

COMMS_SOURCE="${PROMPTLI_COMMS_SOURCE:-https://github.com/promptli-dev/promptli-comms}"
COMMS_REF="${PROMPTLI_COMMS_REF:-}"
PLUGIN_SOURCE="${PROMPTLI_CLAUDE_SOURCE:-git+https://github.com/promptli-dev/claude-code-plugin@main}"
DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/promptli-claude"
VENV="$DATA_DIR/venv"
BIN_DIR="$HOME/.local/bin"

say() { printf '\033[1;38;5;202m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mwarning:\033[0m %s\n' "$*" >&2; }
die() { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

case "$(uname -s)" in
  Darwin) ;;
  Linux) ;;
  *) die "unsupported OS: $(uname -s)" ;;
esac

if ! command -v uv >/dev/null 2>&1; then
  if [ -x "$HOME/.local/bin/uv" ]; then
    PATH="$HOME/.local/bin:$PATH"
  else
    say "Installing uv (Python package manager from astral.sh)"
    curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null
    PATH="$HOME/.local/bin:$PATH"
  fi
fi
command -v uv >/dev/null 2>&1 || die "uv is required: https://docs.astral.sh/uv/"

say "Creating $VENV"
mkdir -p "$DATA_DIR" "$BIN_DIR"
uv venv --quiet --allow-existing --python ">=3.11" "$VENV"

say "Installing promptli-claude"
if [ -n "$COMMS_REF" ]; then  # development: SDK + gateway from a git ref
  set -- "promptli[cli] @ git+$COMMS_SOURCE@$COMMS_REF#subdirectory=sdk/python" \
    "promptli-gateway @ git+$COMMS_SOURCE@$COMMS_REF#subdirectory=gateway"
else  # released packages from PyPI
  set -- "promptli[cli]>=0.2.0,<0.3" "promptli-gateway>=0.2.0,<0.3"
fi
uv pip install --quiet --no-sources --python "$VENV/bin/python" "$@" "$PLUGIN_SOURCE"

ln -sf "$VENV/bin/promptli-claude" "$BIN_DIR/promptli-claude"
"$BIN_DIR/promptli-claude" version >/dev/null || die "install failed: promptli-claude does not run"

if [ "${PROMPTLI_SKIP_PLUGIN:-0}" != "1" ]; then
  if command -v claude >/dev/null 2>&1; then
    say "Adding the Claude Code plugin (marketplace: promptli)"
    claude plugin marketplace add promptli-dev/claude-code-plugin >/dev/null 2>&1 \
      || claude plugin marketplace update promptli >/dev/null 2>&1 || warn "could not add the marketplace"
    claude plugin install promptli-comms@promptli >/dev/null 2>&1 \
      || warn "could not install the plugin; inside Claude Code run: /plugin install promptli-comms@promptli"
  else
    warn "Claude Code CLI not found; install it, then run: claude plugin install promptli-comms@promptli"
  fi
fi

case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) warn "$BIN_DIR is not on your PATH. Add it: echo 'export PATH=\"$BIN_DIR:\$PATH\"' >> ~/.zshrc" ;;
esac

say "Installed $("$BIN_DIR/promptli-claude" version)"
cat <<'EOF'

Next:
  promptli-claude setup     connect your Promptli key (or sign up), pick a project, start the service
  promptli-claude doctor    check everything is working

Anyone who learns your agent's address or number can message it. Only tools you pre-approve in your
Claude Code settings (permissions.allow) can run in those sessions.
EOF
