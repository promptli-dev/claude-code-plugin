from __future__ import annotations

import json
from pathlib import Path

import pytest
from promptli_gateway.config import GatewayConfig
from typer.testing import CliRunner

from promptli_claude import cli

runner = CliRunner()


@pytest.fixture(autouse=True)
def _home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROMPTLI_HOME", str(tmp_path))
    monkeypatch.delenv("PROMPTLI_API_KEY", raising=False)


def test_version() -> None:
    r = runner.invoke(cli.app, ["version"])
    assert r.exit_code == 0 and "promptli-claude 0.1.0" in r.output


def test_unconfigured_status_doctor_and_run() -> None:
    r = runner.invoke(cli.app, ["status", "--json"])
    assert r.exit_code == 0 and json.loads(r.output)["configured"] is False
    assert runner.invoke(cli.app, ["doctor"]).exit_code == 1
    assert runner.invoke(cli.app, ["run"]).exit_code == 2


def test_bootstrap_needs_a_key() -> None:
    r = runner.invoke(cli.app, ["bootstrap", "--json"])
    assert r.exit_code == 2 and "PROMPTLI_API_KEY" in r.output


def test_setup_requires_accepting_the_warning() -> None:
    r = runner.invoke(cli.app, ["setup"], input="n\n")
    assert r.exit_code == 1
    assert "Anyone who knows your email address" in r.output


def test_status_shows_local_config_even_offline(tmp_path: Path) -> None:
    GatewayConfig(runtime="promptli-claude", identity="glow", base_url="http://127.0.0.1:9").save(
        api_key="psk_test_x"
    )
    r = runner.invoke(cli.app, ["status", "--json"])
    data = json.loads(r.output)
    assert data["identity"] == "glow" and "channels" not in data
    assert (tmp_path / "promptli-claude" / "credentials").stat().st_mode & 0o777 == 0o600


def test_uninstall_purge_removes_local_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "uninstall_autostart", lambda _r: False)  # never touch the real LaunchAgent
    GatewayConfig(runtime="promptli-claude", identity="glow").save(api_key="psk_test_x")
    r = runner.invoke(cli.app, ["uninstall", "--purge", "--yes"])
    assert r.exit_code == 0 and not (tmp_path / "promptli-claude").exists()


async def test_claude_check_reports_missing_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "_claude_cli", lambda: None)
    ok, detail = await cli.claude_check()
    assert not ok and "not found" in detail
