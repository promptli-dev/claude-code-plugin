"""Live test: real Claude Code (via the Agent SDK) answering sandbox email and SMS through Promptli.

PROMPTLI_API_KEY=psk_test_<admin> PROMPTLI_BASE_URL=http://localhost:8000 uv run pytest -m live tests/live -s
Needs the Claude Code CLI logged in. Uses a small model to keep it cheap.
"""

from __future__ import annotations

import asyncio
import os
import secrets
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, TypeVar

import pytest
from promptli import AsyncPromptli
from promptli_gateway.config import GatewayConfig
from promptli_gateway.core import Gateway
from promptli_gateway.setup.bootstrap import bootstrap

from promptli_claude.adapter import RUNTIME, ClaudeCodeAdapter
from promptli_claude.cli import claude_check

pytestmark = pytest.mark.live
T = TypeVar("T")
MODEL = os.environ.get("PROMPTLI_CLAUDE_TEST_MODEL", "haiku")


async def wait_until(pred: Callable[[], Awaitable[T]], timeout: float = 120.0) -> T | None:
    end = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < end:
        got = await pred()
        if got:
            return got
        await asyncio.sleep(1)
    return None


async def test_claude_code_answers_email_and_sms(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    admin = os.environ.get("PROMPTLI_API_KEY", "")
    base = os.environ.get("PROMPTLI_BASE_URL", "http://localhost:8000")
    if not admin.startswith("psk_test_"):
        pytest.skip("needs a psk_test_ admin key")
    ok, detail = await claude_check()
    if not ok:
        pytest.skip(detail)
    monkeypatch.setenv("PROMPTLI_HOME", str(tmp_path))
    monkeypatch.delenv("PROMPTLI_API_KEY")
    handle = f"cc-{secrets.token_hex(3)}"
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

            # 1. Email → Claude's final answer goes back as a threaded reply.
            await p.sandbox.inbound_email(
                handle,
                subject="Quick maths",
                text="What is 17 times 3? Reply with just the number.",
                from_address="jane@example.com",
            )

            async def email_reply() -> Any:
                async for m in me.emails(direction="outbound"):
                    return m
                return None

            replied = await wait_until(email_reply)
            assert replied is not None and replied.subject.startswith("Re: Quick maths")
            full = await me.email(replied.id)
            assert "51" in (full.text or ""), full.text

            # 2. SMS → plain short reply on the same channel.
            caller = "+15550104242"
            await p.sandbox.inbound_text(handle, "Reply with the single word PINEAPPLE", from_number=caller)

            async def sms_reply() -> Any:
                return [
                    t for t in await me.texts() if t.direction == "outbound" and "PINEAPPLE" in t.body.upper()
                ]

            assert await wait_until(sms_reply)

            # 3. Claude uses a Promptli tool itself → no duplicate auto-reply.
            await p.sandbox.inbound_text(
                handle,
                "Please use your send_text tool to text me the word MANGO.",
                from_number=caller,
            )

            async def mango() -> Any:
                return [
                    t for t in await me.texts() if t.direction == "outbound" and "MANGO" in t.body.upper()
                ]

            sent = await wait_until(mango)
            assert sent, [(t.direction, t.body) for t in await me.texts()]
            await asyncio.sleep(8)
            assert len(await mango()) == 1, "tool-delivered reply must suppress the auto-reply"
            assert any(gw.state.sessions().values()), "Claude session ids are persisted"

            gw.stop()
            await asyncio.wait_for(task, timeout=30)
        finally:
            await me.release_phone_number()
            await me.delete()
