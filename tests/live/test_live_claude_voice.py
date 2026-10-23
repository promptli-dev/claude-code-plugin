"""Live: real Claude Code answers a sandbox phone call through the dev stack (Mode C, streamed).

PROMPTLI_API_KEY=psk_test_<admin> PROMPTLI_BASE_URL=http://localhost:8000 uv run pytest -m live tests/live -s
"""

from __future__ import annotations

import asyncio
import os
import secrets
from pathlib import Path
from typing import Any

import pytest
from promptli import AsyncPromptli
from promptli_gateway.config import GatewayConfig
from promptli_gateway.core import Gateway
from promptli_gateway.setup.bootstrap import bootstrap

from promptli_claude.adapter import RUNTIME, ClaudeCodeAdapter
from promptli_claude.cli import claude_check

pytestmark = pytest.mark.live
MODEL = os.environ.get("PROMPTLI_CLAUDE_TEST_MODEL", "haiku")


async def test_claude_code_takes_a_phone_call(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    admin = os.environ.get("PROMPTLI_API_KEY", "")
    base = os.environ.get("PROMPTLI_BASE_URL", "http://localhost:8000")
    if not admin.startswith("psk_test_"):
        pytest.skip("needs a psk_test_ admin key")
    ok, detail = await claude_check()
    if not ok:
        pytest.skip(detail)
    monkeypatch.setenv("PROMPTLI_HOME", str(tmp_path))
    monkeypatch.delenv("PROMPTLI_API_KEY")
    handle = f"ccv-{secrets.token_hex(3)}"
    async with AsyncPromptli(admin, base_url=base) as p:
        me = p.identity(handle)
        try:
            res = await bootstrap(
                runtime=RUNTIME, api_key=admin, identity=handle, base_url=base, want_number=True
            )
            assert res.status == "ok", res
            cfg = GatewayConfig.load(RUNTIME)
            assert cfg is not None
            gw = Gateway(cfg, ClaudeCodeAdapter(model=MODEL))
            task = asyncio.create_task(gw.run())
            await asyncio.sleep(3)
            cid = await p.sandbox.inbound_call(
                handle,
                script=[
                    {"wait_for_agent": True, "timeout_ms": 40000},
                    {"say": "Hi, quick question. What is two plus two?"},
                    {"wait_for_agent": True, "timeout_ms": 40000},
                    {"say": "Great, thanks. Bye!"},
                    {"wait_for_agent": True, "timeout_ms": 30000},
                    {"wait_ms": 2000},
                ],
            )

            call: Any = None
            for _ in range(150):
                call = await p.calls.get(cid)
                if call.ended_at:
                    break
                await asyncio.sleep(1)
            assert call is not None and call.ended_at, call
            tr = await p.calls.transcript(cid)
            lines = [(s.party, s.text) for s in tr.segments]
            print("\n".join(f"{party:>6}: {text}" for party, text in lines))
            agent = " ".join(t for party, t in lines if party == "agent").lower()
            assert call.outcome == "answered_by_agent", call
            assert lines and lines[0][0] == "agent", "Claude greets first"
            assert "four" in agent or " 4" in agent, agent
            assert "*" not in agent and "http" not in agent, "only speakable text"
            gw.stop()
            await asyncio.wait_for(task, timeout=60)
        finally:
            await me.release_phone_number()
            await me.delete()
