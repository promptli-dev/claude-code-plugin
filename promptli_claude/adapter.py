"""ClaudeCodeAdapter: runs gateway turns in Claude Code via the Claude Agent SDK.

- One ClaudeSDKClient (a Claude Code subprocess) per contact_key, so every person gets an isolated
  conversation. Session ids are returned to the gateway, which persists them; after a restart or an idle
  close the next turn resumes the same conversation.
- Text is streamed as partial deltas (`include_partial_messages`), so voice turns (C2) can start speaking
  before Claude finishes.
- Permissions follow the owner's Claude Code settings; anything not pre-approved is denied.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    McpSdkServerConfig,
    ResultMessage,
    StreamEvent,
    TextBlock,
    ToolUseBlock,
)
from promptli_gateway.adapter import (
    AdapterCapabilities,
    GatewayContext,
    TextDelta,
    ToolActivity,
    TurnChunk,
    TurnDone,
    TurnError,
    TurnKind,
)
from promptli_gateway.config import home_dir
from promptli_gateway.tools import ToolSpec

from promptli_claude.permissions import can_use_tool
from promptli_claude.prompts import system_append, turn_preamble
from promptli_claude.tools import SERVER_NAME, build_mcp_server

log = logging.getLogger("promptli.claude")

RUNTIME = "promptli-claude"


class ClaudeClient(Protocol):
    """The subset of ClaudeSDKClient we use (a fake implements it in tests)."""

    async def connect(self) -> None: ...
    async def query(self, prompt: str) -> None: ...
    def receive_response(self) -> AsyncIterator[Any]: ...
    async def interrupt(self) -> None: ...
    async def disconnect(self) -> None: ...


ClientFactory = Callable[[ClaudeAgentOptions], ClaudeClient]


def _default_factory(options: ClaudeAgentOptions) -> ClaudeClient:
    return ClaudeSDKClient(options=options)


@dataclass
class _Session:
    key: str
    client: ClaudeClient
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    last_used: float = field(default_factory=time.monotonic)
    session_id: str | None = None
    busy: bool = False


class ClaudeCodeAdapter:
    name = "claude-code"
    capabilities = AdapterCapabilities(
        streams_text=True, native_tools=True, resumable_sessions=True, interruptible=True
    )

    def __init__(
        self,
        *,
        model: str | None = None,
        client_factory: ClientFactory | None = None,
        idle_close_s: float = 900,
        max_sessions: int = 8,
        max_turns: int | None = 40,
    ) -> None:
        self.model = model
        self.factory = client_factory or _default_factory
        self.idle_close_s = idle_close_s
        self.max_sessions = max_sessions
        self.max_turns = max_turns
        self.ctx: GatewayContext | None = None
        self.tools: list[ToolSpec] = []
        self._server: McpSdkServerConfig | None = None
        self._sessions: dict[str, _Session] = {}
        self._reaper: asyncio.Task[None] | None = None

    # ---- lifecycle ----------------------------------------------------------------------------
    async def start(self, ctx: GatewayContext, tools: list[ToolSpec]) -> None:
        self.ctx = ctx
        self.tools = tools
        self._server = build_mcp_server(tools)
        if self._reaper is None:
            self._reaper = asyncio.create_task(self._reap_idle())

    async def close(self) -> None:
        if self._reaper:
            self._reaper.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reaper
            self._reaper = None
        for key in list(self._sessions):
            await self._close_session(key)

    def workdir(self) -> str:
        if self.ctx and self.ctx.project_dir:
            return self.ctx.project_dir
        d = home_dir(RUNTIME) / "workspace"
        d.mkdir(parents=True, exist_ok=True)
        return str(d)

    def options(self, session_key: str, resume_id: str | None) -> ClaudeAgentOptions:
        assert self.ctx is not None and self._server is not None, "start() first"
        return ClaudeAgentOptions(
            cwd=self.workdir(),
            model=self.model,
            resume=resume_id,
            max_turns=self.max_turns,
            include_partial_messages=True,
            # Load the owner's permission rules, CLAUDE.md and MCP config like an interactive session would,
            # but never inherit a permissive default mode: unapproved tools go to can_use_tool and are denied.
            setting_sources=["user", "project", "local"],
            permission_mode="default",
            can_use_tool=can_use_tool,
            mcp_servers={SERVER_NAME: self._server},
            system_prompt={
                "type": "preset",
                "preset": "claude_code",
                "append": system_append(self.ctx, session_key),
            },
        )

    # ---- sessions -----------------------------------------------------------------------------
    async def _open(self, session_key: str, resume_id: str | None) -> _Session:
        client = self.factory(self.options(session_key, resume_id))
        await client.connect()
        s = _Session(session_key, client, session_id=resume_id)
        self._sessions[session_key] = s
        await self._evict_over_cap()
        return s

    async def _session(self, session_key: str, resume_id: str | None) -> _Session:
        s = self._sessions.get(session_key)
        if s is not None:
            return s
        try:
            return await self._open(session_key, resume_id)
        except Exception:
            if not resume_id:
                raise
            log.warning("could not resume %s for %s; starting fresh", resume_id, session_key)
            return await self._open(session_key, None)

    async def _close_session(self, key: str) -> None:
        s = self._sessions.pop(key, None)
        if s is not None:
            with contextlib.suppress(Exception):
                await s.client.disconnect()

    async def _evict_over_cap(self) -> None:
        idle = sorted((s for s in self._sessions.values() if not s.busy), key=lambda s: s.last_used)
        while len(self._sessions) > self.max_sessions and idle:
            await self._close_session(idle.pop(0).key)

    async def _reap_idle(self) -> None:
        while True:
            await asyncio.sleep(min(60.0, self.idle_close_s))
            now = time.monotonic()
            for s in list(self._sessions.values()):
                if not s.busy and now - s.last_used > self.idle_close_s:
                    await self._close_session(s.key)

    async def interrupt(self, session_key: str) -> None:
        s = self._sessions.get(session_key)
        if s is not None and s.busy:
            await s.client.interrupt()

    async def reset_session(self, session_key: str) -> None:
        await self._close_session(session_key)

    def session_count(self) -> int:
        return len(self._sessions)

    # ---- turns --------------------------------------------------------------------------------
    async def run_turn(
        self, session_key: str, prompt: str, *, kind: TurnKind, resume_id: str | None
    ) -> AsyncIterator[TurnChunk]:
        try:
            s = await self._session(session_key, resume_id)
        except Exception as e:
            yield TurnError(f"could not start Claude Code: {e}", retryable=True)
            return
        async with s.lock:
            s.busy = True
            try:
                retry = False
                async for chunk in self._stream(s, turn_preamble(kind) + prompt):
                    if isinstance(chunk, TurnError) and chunk.message == "_resume_failed" and resume_id:
                        retry = True
                        break
                    yield chunk
                if retry:
                    log.warning("resumed session %s failed for %s; retrying fresh", resume_id, session_key)
                    await self._close_session(session_key)
                    s = await self._open(session_key, None)
                    s.busy = True
                    async for chunk in self._stream(s, turn_preamble(kind) + prompt):
                        yield chunk
            finally:
                s.busy = False
                s.last_used = time.monotonic()

    async def _stream(self, s: _Session, prompt: str) -> AsyncIterator[TurnChunk]:
        streamed = False
        last_text = ""
        produced = False
        try:
            await s.client.query(prompt)
            async for msg in s.client.receive_response():
                if isinstance(msg, StreamEvent):
                    ev: dict[str, Any] = msg.event
                    delta: dict[str, Any] = ev.get("delta") or {}
                    if ev.get("type") == "content_block_delta" and delta.get("type") == "text_delta":
                        streamed = produced = True
                        yield TextDelta(str(delta.get("text", "")))
                elif isinstance(msg, AssistantMessage):
                    texts = [b.text for b in msg.content if isinstance(b, TextBlock)]
                    for b in msg.content:
                        if isinstance(b, ToolUseBlock):
                            produced = True
                            yield ToolActivity(b.name, "started")
                    if texts:
                        last_text = "".join(texts)
                        produced = True
                        if not streamed:
                            yield TextDelta(last_text)
                    streamed = False  # each assistant message starts a new streamed block
                elif isinstance(msg, ResultMessage):
                    s.session_id = msg.session_id or s.session_id
                    if msg.is_error:
                        if not produced and s.session_id and msg.num_turns == 0:
                            yield TurnError("_resume_failed", retryable=True)
                            return
                        detail = msg.result or ", ".join(str(e) for e in (msg.errors or [])) or msg.subtype
                        yield TurnError(f"claude: {detail}", retryable=False)
                        return
                    yield TurnDone(text=(msg.result or last_text).strip(), session_id=s.session_id)
                    return
        except Exception as e:
            log.exception("claude turn failed for %s", s.key)
            await self._close_session(s.key)
            yield TurnError(f"claude: {e}", retryable=True)
            return
        yield TurnError("claude: response ended without a result", retryable=True)
