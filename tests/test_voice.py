"""C2: Claude Code on live calls (streamed, interruptible, top-level speech only)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ResultMessage, StreamEvent, TextBlock
from promptli.calls_live import CallDispatcher
from promptli_gateway.adapter import GatewayContext, TextDelta, TurnDone, TurnKind
from promptli_gateway.voice import CallTurnDriver

from promptli_claude.adapter import ClaudeCodeAdapter

CTX = GatewayContext("glow", "glow@agents.promptli.com", "+15550100000", None)


def delta(text: str, parent: str | None = None) -> StreamEvent:
    event = {"type": "content_block_delta", "delta": {"type": "text_delta", "text": text}}
    return StreamEvent(uuid="u", session_id="s", event=event, parent_tool_use_id=parent)


def result(text: str, sid: str = "sess-1") -> ResultMessage:
    return ResultMessage(
        subtype="success",
        duration_ms=1,
        duration_api_ms=1,
        is_error=False,
        num_turns=1,
        session_id=sid,
        result=text,
    )


class QueueClaude:
    """Like ClaudeSDKClient: one message stream; a turn's unread messages stay queued for the next reader."""

    def __init__(self, options: ClaudeAgentOptions) -> None:
        self.options = options
        self.prompts: list[str] = []
        self.models: list[str | None] = []
        self.interrupted = 0
        self._q: asyncio.Queue[Any] = asyncio.Queue()

    async def connect(self) -> None:
        return None

    async def set_model(self, model: str | None) -> None:
        self.models.append(model)

    async def query(self, prompt: str) -> None:
        self.prompts.append(prompt)
        reply = f"Answer to {prompt[-12:]}"
        for w in reply.split(" "):
            self._q.put_nowait(delta(w + " "))
        self._q.put_nowait(delta("[subagent chatter]", parent="tool_1"))
        self._q.put_nowait(
            AssistantMessage([TextBlock("[subagent chatter]")], model="m", parent_tool_use_id="tool_1")
        )
        self._q.put_nowait(AssistantMessage([TextBlock(reply)], model="m"))
        self._q.put_nowait(result(reply))

    async def receive_response(self) -> AsyncIterator[Any]:
        while True:
            msg = await self._q.get()
            yield msg
            if isinstance(msg, ResultMessage):
                return

    async def interrupt(self) -> None:
        self.interrupted += 1

    async def disconnect(self) -> None:
        return None


@pytest.fixture(autouse=True)
def _home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROMPTLI_HOME", str(tmp_path))


async def make(**kw: Any) -> tuple[ClaudeCodeAdapter, list[QueueClaude]]:
    clients: list[QueueClaude] = []

    def factory(o: ClaudeAgentOptions) -> QueueClaude:
        c = QueueClaude(o)
        clients.append(c)
        return c

    a = ClaudeCodeAdapter(client_factory=factory, **kw)
    await a.start(CTX, [])
    return a, clients


async def test_interrupted_turn_is_drained_so_the_next_turn_gets_its_own_answer() -> None:
    a, clients = await make()
    gen = a.run_turn("ctc_1", "first question", kind=TurnKind.VOICE, resume_id=None)
    first = await anext(gen)
    assert isinstance(first, TextDelta)
    await a.interrupt("ctc_1")
    await gen.aclose()  # the gateway cancels the turn on barge-in
    chunks = [c async for c in a.run_turn("ctc_1", "second question", kind=TurnKind.VOICE, resume_id=None)]
    done = chunks[-1]
    assert isinstance(done, TurnDone) and done.text == "Answer to ond question"
    assert clients[0].interrupted == 1
    await a.close()


async def test_only_top_level_text_is_streamed() -> None:
    a, _ = await make()
    chunks = [c async for c in a.run_turn("ctc_1", "hello there", kind=TurnKind.VOICE, resume_id=None)]
    spoken = "".join(c.text for c in chunks if isinstance(c, TextDelta))
    assert "subagent" not in spoken and spoken.strip() == "Answer to hello there"
    await a.close()


async def test_voice_model_is_used_for_voice_turns_only() -> None:
    a, clients = await make(model="sonnet", voice_model="haiku")
    _ = [c async for c in a.run_turn("ctc_1", "on the phone", kind=TurnKind.VOICE, resume_id=None)]
    _ = [c async for c in a.run_turn("ctc_1", "an email", kind=TurnKind.CHANNEL, resume_id=None)]
    assert clients[0].models == ["haiku", "sonnet"]
    await a.close()


class FakeLink:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send(self, frame: dict[str, Any]) -> None:
        self.sent.append(frame)


async def test_claude_code_answers_a_call_through_the_gateway_driver() -> None:
    a, clients = await make()
    link = FakeLink()
    sessions: dict[str, str | None] = {}
    driver = CallTurnDriver(
        a, identity_name="Glow", get_session=sessions.get, set_session=sessions.__setitem__
    )
    disp = CallDispatcher(link, driver.on_call)  # type: ignore[arg-type]
    for frame in (
        {"type": "call.incoming", "direction": "inbound", "from": "+15550104242", "contact_key": "ctc_1"},
        {"type": "call.start", "turn_id": "t0", "greet": True},
        {"type": "call.transcript", "turn_id": "t1", "text": "What time do you open?", "is_final": True},
        {"type": "call.stop", "reason": "caller_hangup"},
    ):
        await disp.handle({"call_id": "call_1", **frame})
        await asyncio.sleep(0.2)
    await asyncio.sleep(0.3)
    texts = [f for f in link.sent if f["type"] == "call.text"]
    t1 = [f for f in texts if f["turn_id"] == "t1"]
    assert len(t1) >= 3 and t1[-1]["done"], "streamed deltas then done"
    assert "What time do you open?" in clients[0].prompts[1]
    assert "live phone call" in clients[0].prompts[0]
    assert sessions["ctc_1"] == "sess-1"
    await a.close()


async def test_warm_starts_one_session_that_the_greeting_reuses() -> None:
    a, clients = await make(voice_model="haiku")
    await asyncio.gather(
        a.warm("ctc_1", None),
        _collect(a.run_turn("ctc_1", "greet", kind=TurnKind.VOICE, resume_id=None)),
    )
    assert len(clients) == 1, "warm and the first turn share one Claude Code session"
    assert clients[0].models[:1] == ["haiku"]
    await a.close()


async def _collect(gen: Any) -> list[Any]:
    return [c async for c in gen]
