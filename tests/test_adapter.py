from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, ClassVar

import pytest
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    StreamEvent,
    TextBlock,
    ToolPermissionContext,
    ToolUseBlock,
)
from promptli_gateway.adapter import GatewayContext, TextDelta, TurnDone, TurnError, TurnKind
from promptli_gateway.config import GatewayConfig
from promptli_gateway.core import Gateway
from promptli_gateway.tools import ToolSpec, obj

from promptli_claude.adapter import ClaudeCodeAdapter
from promptli_claude.permissions import can_use_tool
from promptli_claude.tools import _wrap  # pyright: ignore[reportPrivateUsage]

CTX = GatewayContext("glow", "glow@agents.promptli.com", "+15550100000", None)


def delta(text: str) -> StreamEvent:
    return StreamEvent(
        uuid="u",
        session_id="s",
        event={"type": "content_block_delta", "delta": {"type": "text_delta", "text": text}},
    )


class FakeClaude:
    """Mimics ClaudeSDKClient: one conversation, scripted replies, records everything."""

    instances: ClassVar[list[FakeClaude]] = []
    fail_resume: bool = False

    def __init__(self, options: ClaudeAgentOptions, adapter: ClaudeCodeAdapter | None = None) -> None:
        self.options = options
        self.adapter = adapter
        self.prompts: list[str] = []
        self.session_id = options.resume or f"sess-{len(FakeClaude.instances)}"
        self.connected = False
        self.interrupted = False
        FakeClaude.instances.append(self)

    async def connect(self) -> None:
        if self.options.resume and FakeClaude.fail_resume:
            raise RuntimeError("No conversation found with session ID")
        self.connected = True

    async def query(self, prompt: str) -> None:
        self.prompts.append(prompt)

    async def receive_response(self) -> AsyncIterator[Any]:
        prompt = self.prompts[-1]
        if "USE_TOOL" in prompt and self.adapter is not None:
            tool = next(t for t in self.adapter.tools if t.name == "reply_email")
            yield AssistantMessage([ToolUseBlock("tu_1", "mcp__promptli__reply_email", {})], model="m")
            await tool.handler({"message_id": "msg_1", "text": "sent by tool"})
        reply = f"reply #{len(self.prompts)}"
        for word in reply.split(" "):
            yield delta(word + " ")
        yield AssistantMessage([TextBlock(reply + " ")], model="m")
        yield ResultMessage(
            subtype="success",
            duration_ms=1,
            duration_api_ms=1,
            is_error=False,
            num_turns=1,
            session_id=self.session_id,
            result=reply,
        )

    async def interrupt(self) -> None:
        self.interrupted = True

    async def disconnect(self) -> None:
        self.connected = False


@pytest.fixture(autouse=True)
def _reset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROMPTLI_HOME", str(tmp_path))
    FakeClaude.instances = []
    FakeClaude.fail_resume = False


async def make_adapter(tools: list[ToolSpec] | None = None, **kw: Any) -> ClaudeCodeAdapter:
    holder: dict[str, ClaudeCodeAdapter] = {}
    adapter = ClaudeCodeAdapter(client_factory=lambda o: FakeClaude(o, holder.get("a")), **kw)
    holder["a"] = adapter
    await adapter.start(CTX, tools or [])
    return adapter


async def collect(adapter: ClaudeCodeAdapter, key: str, prompt: str, resume: str | None = None) -> list[Any]:
    return [c async for c in adapter.run_turn(key, prompt, kind=TurnKind.CHANNEL, resume_id=resume)]


async def test_streams_deltas_before_done_without_duplicating_text() -> None:
    a = await make_adapter()
    chunks = await collect(a, "ctc_jane", "hello")
    deltas = [c.text for c in chunks if isinstance(c, TextDelta)]
    assert "".join(deltas) == "reply #1 "
    assert isinstance(chunks[-1], TurnDone)
    assert chunks[-1].text == "reply #1" and chunks[-1].session_id == "sess-0"
    await a.close()


async def test_one_session_per_contact_and_reused_across_turns() -> None:
    a = await make_adapter()
    await collect(a, "ctc_jane", "one")
    await collect(a, "ctc_jane", "two")
    await collect(a, "ctc_bob", "three")
    assert len(FakeClaude.instances) == 2
    assert FakeClaude.instances[0].prompts == ["one", "two"]
    assert a.session_count() == 2
    sys_prompt = FakeClaude.instances[1].options.system_prompt
    assert isinstance(sys_prompt, dict) and "ctc_bob" in str(sys_prompt.get("append"))
    await a.close()
    assert not any(c.connected for c in FakeClaude.instances)


async def test_resume_id_is_used_and_falls_back_to_fresh_when_missing() -> None:
    a = await make_adapter()
    chunks = await collect(a, "ctc_jane", "hi", resume="sess-old")
    assert FakeClaude.instances[0].options.resume == "sess-old"
    assert chunks[-1].session_id == "sess-old"
    await a.reset_session("ctc_jane")
    FakeClaude.fail_resume = True
    chunks = await collect(a, "ctc_jane", "hi again", resume="sess-gone")
    assert isinstance(chunks[-1], TurnDone)
    assert FakeClaude.instances[-1].options.resume is None
    await a.close()


async def test_options_follow_user_settings_and_expose_promptli_tools() -> None:
    async def noop(_a: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True}

    a = await make_adapter([ToolSpec("send_text", "Send an SMS", obj({}), noop)])
    o = a.options("ctc_jane", None)
    assert o.setting_sources == ["user", "project", "local"]
    assert o.permission_mode == "default"
    assert o.include_partial_messages is True
    assert o.allowed_tools == []  # our tools are approved in can_use_tool, not as blanket allow rules
    assert isinstance(o.mcp_servers, dict) and "promptli" in o.mcp_servers
    assert o.can_use_tool is can_use_tool
    assert o.cwd and Path(o.cwd).is_dir()
    await a.close()


async def test_permissions_allow_promptli_and_deny_everything_else() -> None:
    ctx = ToolPermissionContext(signal=None, suggestions=[])
    allow = await can_use_tool("mcp__promptli__send_email", {}, ctx)
    deny = await can_use_tool("Bash", {"command": "cat ~/.ssh/id_rsa"}, ctx)
    assert allow.behavior == "allow"
    assert deny.behavior == "deny" and "permissions.allow" in deny.message


async def test_tool_wrapper_reports_errors_without_raising() -> None:
    async def boom(_a: dict[str, Any]) -> dict[str, Any]:
        raise ValueError("nope")

    async def bad(_a: dict[str, Any]) -> dict[str, Any]:
        return {"ok": False, "error": "recipient_opted_out"}

    r1 = await _wrap(boom)({})
    r2 = await _wrap(bad)({})
    assert r1["is_error"] and json.loads(r1["content"][0]["text"])["error"] == "tool_failed"
    assert r2["is_error"] and "recipient_opted_out" in r2["content"][0]["text"]


async def test_idle_sessions_are_evicted_over_the_cap() -> None:
    a = await make_adapter(max_sessions=2)
    for who in ("a", "b", "c"):
        await collect(a, f"ctc_{who}", "hi")
    assert a.session_count() == 2
    assert not FakeClaude.instances[0].connected
    await a.close()


async def test_interrupt_reaches_a_running_turn() -> None:
    a = await make_adapter()
    gen = a.run_turn("ctc_jane", "hi", kind=TurnKind.VOICE, resume_id=None)
    first = await anext(gen)
    assert isinstance(first, TextDelta)
    await a.interrupt("ctc_jane")
    assert FakeClaude.instances[0].interrupted
    rest = [c async for c in gen]
    assert isinstance(rest[-1], TurnDone)
    await a.close()


async def test_connect_failure_is_a_retryable_turn_error() -> None:
    def broken(_o: ClaudeAgentOptions) -> Any:
        raise FileNotFoundError("claude not found")

    a = ClaudeCodeAdapter(client_factory=broken)
    await a.start(CTX, [])
    chunks = await collect(a, "ctc_jane", "hi")
    assert isinstance(chunks[0], TurnError) and chunks[0].retryable
    await a.close()


# ---- through the real gateway core ------------------------------------------------------------------


class FakeIdentity:
    def __init__(self, log: list[tuple[str, Any]]) -> None:
        self.log = log

    async def reply(self, message_id: str, *, text: str | None = None, **_: Any) -> None:
        self.log.append(("reply", (message_id, text)))

    async def send_text(self, to: Any, text: str = "", **_: Any) -> None:
        self.log.append(("text", (to, text)))


class FakePromptli:
    def __init__(self) -> None:
        self.log: list[tuple[str, Any]] = []

    def identity(self, _ref: str) -> FakeIdentity:
        return FakeIdentity(self.log)

    async def close(self) -> None:
        return None


class FakeLink:
    async def ack(self, seq: int) -> None:
        return None


def email_event(seq: int, body: str, sender: str = "jane@example.com") -> dict[str, Any]:
    return {
        "id": f"evt_{seq}",
        "seq": seq,
        "type": "message.received",
        "data": {
            "message": {
                "id": f"msg_{seq}",
                "thread_id": "thr_1",
                "from": sender,
                "subject": "Hi",
                "text": body,
                "attachments": [],
                "folder": "inbox",
            },
            "contacts": [{"id": "ctc_jane", "name": "Jane"}],
            "contact_key": "ctc_jane",
        },
    }


async def run_gateway(events: list[dict[str, Any]]) -> tuple[Gateway, FakePromptli]:
    cfg = GatewayConfig(runtime="promptli-claude", identity="glow", batch_window_s=0.01)
    holder: dict[str, ClaudeCodeAdapter] = {}
    adapter = ClaudeCodeAdapter(client_factory=lambda o: FakeClaude(o, holder.get("a")))
    holder["a"] = adapter
    client = FakePromptli()
    gw = Gateway(cfg, adapter, client=client)  # type: ignore[arg-type]
    gw.identity_address, gw.identity_number = "glow@agents.promptli.com", "+15550100000"
    gw.link = FakeLink()  # type: ignore[assignment]

    async def reply_email(a: dict[str, Any]) -> dict[str, Any]:
        gw._mark_sent("email", "jane@example.com")  # pyright: ignore[reportPrivateUsage]
        return {"ok": True}

    await adapter.start(CTX, [ToolSpec("reply_email", "Reply", obj({}), reply_email)])
    for e in events:
        await gw.handle_event(e)
    for _ in range(100):
        await asyncio.sleep(0.01)
        if not gw._pending:  # pyright: ignore[reportPrivateUsage]
            break
    await adapter.close()
    return gw, client


async def test_gateway_email_turn_replies_with_claude_final_text_and_persists_session() -> None:
    gw, client = await run_gateway([email_event(1, "Can we move to 4pm?")])
    assert client.log == [("reply", ("msg_1", "reply #1"))]
    assert gw.state.session("ctc_jane") == "sess-0"
    framed = FakeClaude.instances[0].prompts[0]
    assert "<external_content" in framed and "Can we move to 4pm?" in framed


async def test_gateway_tool_delivered_reply_suppresses_auto_reply() -> None:
    _, client = await run_gateway([email_event(2, "USE_TOOL please")])
    assert client.log == []
