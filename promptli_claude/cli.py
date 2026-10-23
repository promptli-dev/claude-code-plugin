"""`promptli-claude`: set up and run Claude Code as a Promptli Comms agent."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path
from typing import Any

import claude_agent_sdk
import typer
from promptli import AsyncPromptli, PromptliError
from promptli_gateway.config import DEFAULT_BASE_URL, GatewayConfig, home_dir
from promptli_gateway.core import Gateway
from promptli_gateway.setup.autostart import (
    autostart_status,
    install_autostart,
    uninstall_autostart,
)
from promptli_gateway.setup.bootstrap import BootstrapResult, bootstrap
from promptli_gateway.setup.doctor import doctor as run_doctor

from promptli_claude import __version__
from promptli_claude.adapter import RUNTIME, ClaudeCodeAdapter
from promptli_claude.prompts import STRANGER_WARNING

app = typer.Typer(
    help="Give Claude Code its own email address and phone number (Promptli Comms).",
    no_args_is_help=True,
    add_completion=False,
)

BASE_URL_ENV = "PROMPTLI_BASE_URL"


def _base_url(opt: str | None) -> str:
    return opt or os.environ.get(BASE_URL_ENV) or DEFAULT_BASE_URL


def _print_json(data: Any) -> None:
    typer.echo(json.dumps(data, indent=2, default=str))


def _show_bootstrap(res: BootstrapResult, as_json: bool) -> None:
    if as_json:
        _print_json(res.as_dict())
    elif res.status == "error" and res.error:
        typer.secho(f"Setup failed: {res.error.get('code')}: {res.error.get('message')}", fg="red")
    else:
        typer.secho(f"Agent @{res.identity} is ready ({res.env} mode).", fg="green")
        if res.email_address:
            typer.echo(f"  email  {res.email_address}")
        typer.echo(f"  phone  {res.phone_number or 'none (run setup --number to add one)'}")
        for a in res.actions:
            typer.echo(f"  - {a}")
        if res.next_step:
            typer.secho(f"Next: {res.next_step}", fg="yellow")
    if res.status == "error":
        raise typer.Exit(1)


def _claude_cli() -> str | None:
    bundled = Path(claude_agent_sdk.__file__).parent / "_bundled" / "claude"
    if bundled.exists():
        return str(bundled)
    return shutil.which("claude")


async def claude_check() -> tuple[bool, str]:
    cli = _claude_cli()
    if cli is None:
        return False, "Claude Code CLI not found (install Claude Code, then run `claude` once to log in)"
    try:
        out = await asyncio.to_thread(
            subprocess.run,
            [cli, "auth", "status", "--json"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        status = json.loads(out.stdout or "{}")
    except (OSError, ValueError, subprocess.TimeoutExpired) as e:
        return False, f"could not run Claude Code: {e}"
    if not status.get("loggedIn"):
        return False, "Claude Code is not logged in: run `claude` and sign in"
    return True, f"Claude Code logged in ({status.get('authMethod', 'unknown')})"


# ---- setup ---------------------------------------------------------------------------------------


@app.command()
def setup(
    identity: str | None = typer.Option(None, help="Agent handle, e.g. 'my-agent'"),
    project_dir: str | None = typer.Option(None, help="Directory Claude Code works in (default: here)"),
    number: bool = typer.Option(False, "--number", help="Also get a phone number for SMS and calls"),
    region: str | None = typer.Option(None, help="Phone number region/area code"),
    base_url: str | None = typer.Option(None, help="Promptli API base URL"),
    start: bool = typer.Option(True, help="Start the background service when done"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Accept the security warning"),
) -> None:
    """Interactive setup: connect a key (or sign up), create the agent and start the service."""
    typer.secho("Promptli Comms for Claude Code", bold=True)
    typer.secho("\nBefore you continue:", fg="yellow", bold=True)
    typer.echo(STRANGER_WARNING)
    if not yes and not typer.confirm("\nI understand. Continue?", default=False):
        raise typer.Exit(1)
    url = _base_url(base_url)
    key = os.environ.get("PROMPTLI_API_KEY")
    if not key:
        has_key = typer.confirm("\nDo you have a Promptli API key?", default=True)
        if has_key:
            key = typer.prompt("Paste the key (input hidden)", hide_input=True).strip()
        else:
            human = typer.prompt("Your email (we send you a confirmation code)")
            handle: str = identity or typer.prompt("Pick a handle for the agent")
            identity = handle
            created = asyncio.run(AsyncPromptli.create_signup(human, handle, base_url=url))
            key = created.api_key
            typer.echo(f"Signed up. {created.next_step}")
    res = asyncio.run(
        bootstrap(
            runtime=RUNTIME,
            api_key=key,
            identity=identity,
            base_url=url,
            project_dir=str(Path(project_dir or os.getcwd()).resolve()),
            phone_region=region,
            want_number=number,
        )
    )
    if res.status == "error" and res.error and res.error.get("code") == "identity_required":
        identity = typer.prompt("This is an organization key. Agent handle (existing or new)")
        res = asyncio.run(
            bootstrap(
                runtime=RUNTIME,
                api_key=key,
                identity=identity,
                base_url=url,
                project_dir=str(Path(project_dir or os.getcwd()).resolve()),
                phone_region=region,
                want_number=number,
            )
        )
    _show_bootstrap(res, as_json=False)
    if res.status == "requires_human":
        code = typer.prompt("6-digit code from the email (empty to do it later)", default="")
        if code:
            verify(code)
    if start:
        _start()


@app.command("bootstrap")
def bootstrap_cmd(
    identity: str | None = typer.Option(None, help="Agent handle (required for organization keys)"),
    project_dir: str | None = typer.Option(None, help="Directory Claude Code works in"),
    number: bool = typer.Option(False, "--number", help="Ensure the agent has a phone number"),
    region: str | None = typer.Option(None),
    base_url: str | None = typer.Option(None),
    api_key_stdin: bool = typer.Option(False, help="Read the key from stdin instead of PROMPTLI_API_KEY"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Non-interactive, idempotent setup (for agents and scripts). The key comes from PROMPTLI_API_KEY."""
    key = sys.stdin.readline().strip() if api_key_stdin else os.environ.get("PROMPTLI_API_KEY", "")
    if not key:
        cfg = GatewayConfig.load(RUNTIME)
        if cfg is None:
            typer.secho("Set PROMPTLI_API_KEY (or use --api-key-stdin).", fg="red", err=True)
            raise typer.Exit(2)
        key = cfg.api_key()
    res = asyncio.run(
        bootstrap(
            runtime=RUNTIME,
            api_key=key,
            identity=identity,
            base_url=_base_url(base_url),
            project_dir=str(Path(project_dir).resolve()) if project_dir else None,
            phone_region=region,
            want_number=number,
        )
    )
    _show_bootstrap(res, as_json)


@app.command()
def signup(
    email: str = typer.Option(..., help="Your (the human owner's) email address"),
    handle: str = typer.Option(..., help="Handle for the new agent"),
    test: bool = typer.Option(False, "--test", help="Sign up in test mode (sandbox)"),
    project_dir: str | None = typer.Option(None),
    base_url: str | None = typer.Option(None),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Self-signup without a key: creates the agent; the human confirms with an emailed code."""
    url = _base_url(base_url)
    try:
        created = asyncio.run(AsyncPromptli.create_signup(email, handle, test_mode=test, base_url=url))
    except PromptliError as e:
        typer.secho(f"Signup failed: {e.code}: {e.message}", fg="red", err=True)
        raise typer.Exit(1) from e
    res = asyncio.run(
        bootstrap(
            runtime=RUNTIME,
            api_key=created.api_key,
            identity=None,
            base_url=url,
            project_dir=str(Path(project_dir).resolve()) if project_dir else None,
        )
    )
    _show_bootstrap(res, as_json)


@app.command()
def verify(code: str = typer.Argument(..., help="The 6-digit code emailed to the human")) -> None:
    """Confirm a self-signup with the code the human received."""
    cfg = _require_config()

    async def go() -> bool:
        async with AsyncPromptli(cfg.api_key(), base_url=cfg.base_url) as p:
            return await p.signup.verify(code)

    try:
        ok = asyncio.run(go())
    except PromptliError as e:
        typer.secho(f"{e.code}: {e.message}", fg="red", err=True)
        raise typer.Exit(1) from e
    msg = "Verified: the agent is fully active." if ok else "Code not accepted."
    typer.secho(msg, fg="green" if ok else "red")
    if not ok:
        raise typer.Exit(1)


# ---- run / service ---------------------------------------------------------------------------------


def _require_config() -> GatewayConfig:
    cfg = GatewayConfig.load(RUNTIME)
    if cfg is None:
        typer.secho("Not set up yet: run `promptli-claude setup`.", fg="red", err=True)
        raise typer.Exit(2)
    return cfg


@app.command()
def run(verbose: bool = typer.Option(False, "-v", "--verbose")) -> None:
    """Run the gateway in the foreground (this is what the background service runs)."""
    cfg = _require_config()
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    adapter = ClaudeCodeAdapter(model=cfg.extra.get("model"), voice_model=cfg.extra.get("voice_model"))

    async def main_loop() -> None:
        gw = Gateway(cfg, adapter)
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, gw.stop)
        await gw.run()

    asyncio.run(main_loop())


def _start() -> None:
    cfg = _require_config()
    env = {k: v for k, v in os.environ.items() if k in ("PROMPTLI_HOME", "ANTHROPIC_API_KEY", "HOME")}
    path = install_autostart(RUNTIME, [sys.executable, "-m", "promptli_claude", "run"], env=env)
    typer.secho(f"Background service started for @{cfg.identity} ({path}).", fg="green")
    typer.echo("Logs: promptli-claude logs -f")


@app.command()
def start() -> None:
    """Install and start the background service (launchd, starts at login)."""
    _start()


@app.command()
def stop() -> None:
    """Stop the background service and remove it from login items."""
    typer.echo("Stopped." if uninstall_autostart(RUNTIME) else "Service was not installed.")


@app.command()
def restart() -> None:
    """Restart the background service."""
    uninstall_autostart(RUNTIME)
    _start()


@app.command()
def status(as_json: bool = typer.Option(False, "--json")) -> None:
    """Show the agent, its channels and whether the service is running."""
    cfg = GatewayConfig.load(RUNTIME)
    running, detail = autostart_status(RUNTIME)
    data: dict[str, Any] = {
        "version": __version__,
        "configured": cfg is not None,
        "service": {"running": running, "detail": detail},
    }
    if cfg is not None:
        data.update(identity=cfg.identity, base_url=cfg.base_url, project_dir=cfg.project_dir)
        with contextlib.suppress(Exception):

            async def channels() -> dict[str, Any]:
                async with AsyncPromptli(cfg.api_key(), base_url=cfg.base_url) as p:
                    st = await p.identity(cfg.identity).channel_status()
                    return {"email": st.email.address, "sms": st.sms.number, "sms_status": st.sms.status}

            data["channels"] = asyncio.run(channels())
    if as_json:
        _print_json(data)
        return
    if cfg is None:
        typer.echo("Not set up: run `promptli-claude setup`.")
        return
    ch = data.get("channels", {})
    typer.echo(f"Agent      @{cfg.identity}")
    typer.echo(f"Email      {ch.get('email') or '-'}")
    typer.echo(f"Phone      {ch.get('sms') or '-'}")
    typer.echo(f"Project    {cfg.project_dir or home_dir(RUNTIME) / 'workspace'}")
    typer.echo(f"Service    {'running' if running else detail}")


@app.command()
def doctor(as_json: bool = typer.Option(False, "--json")) -> None:
    """Check the key, channels, Agent Link, clock, service and Claude Code login."""
    rep = asyncio.run(run_doctor(RUNTIME, runtime_check=claude_check))
    if as_json:
        _print_json(rep.as_dict())
    else:
        for c in rep.checks:
            mark = typer.style("ok  ", fg="green") if c.ok else typer.style("FAIL", fg="red")
            typer.echo(f"{mark} {c.name:<14} {c.detail}")
    if not rep.ok:
        raise typer.Exit(1)


@app.command()
def logs(follow: bool = typer.Option(False, "-f", "--follow"), lines: int = typer.Option(50, "-n")) -> None:
    """Show the background service's logs."""
    d = home_dir(RUNTIME) / "logs"
    files = [p for p in (d / "gateway.err.log", d / "gateway.log") if p.exists()]
    if not files:
        typer.echo(f"No logs yet in {d}.")
        return
    if follow:
        os.execvp("tail", ["tail", "-n", str(lines), "-F", *map(str, files)])  # noqa: S606, S607
    for f in files:
        for line in f.read_text(errors="replace").splitlines()[-lines:]:
            typer.echo(line)


@app.command()
def mcp() -> None:
    """Serve the Promptli tools over MCP stdio (used by the Claude Code plugin in interactive sessions)."""
    from promptli_gateway.mcp_stdio import serve

    asyncio.run(serve(RUNTIME))


@app.command()
def uninstall(
    purge: bool = typer.Option(False, help="Also delete local config, key and state"),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    """Stop the service; with --purge also remove ~/.promptli/promptli-claude (the agent itself is kept)."""
    uninstall_autostart(RUNTIME)
    if purge:
        d = home_dir(RUNTIME)
        if yes or typer.confirm(f"Delete {d}?", default=False):
            shutil.rmtree(d, ignore_errors=True)
    typer.echo("Uninstalled. The agent and its history stay in your Promptli account.")


@app.command()
def version() -> None:
    """Print the version."""
    typer.echo(f"promptli-claude {__version__}")


def main() -> None:
    app()
