"""One agent turn: member message in, one or more assistant messages out."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any
from urllib.parse import quote

import httpx2

from ..channel import TurnChannel
from ..config import Settings
from ..store import Member, Store
from .llm import ClaudeClient, ToolInputParseError
from .prompts import SYSTEM_PROMPT, turn_context
from .tools.base import STATUS_FIELD, Tool, ToolFailure, TurnContext
from .tools.calendar import CALENDAR_TOOLS
from .tools.memory import MEMORY_TOOLS
from .tools.restaurants import RestaurantCatalog, RestaurantSession

log = logging.getLogger(__name__)

APOLOGY = "My apologies, something went wrong on our side. Would you mind trying again in a moment?"
TIMEOUT_APOLOGY = "My apologies, this is taking far longer than it should. Would you mind trying again in a moment?"
REFUSAL = "I'm afraid that isn't something I can help with."
MAX_JSON_RETRIES = 2


class _Iteration:
    """Per-model-call state: buffered text and whether a status message went out."""

    def __init__(self) -> None:
        self.text: list[str] = []
        self.status_posted = False

    def take_text(self) -> str:
        text, self.text = "".join(self.text), []
        return text


class TurnRunner:
    def __init__(
        self,
        settings: Settings,
        store: Store,
        llm: ClaudeClient,
        mock_http: httpx2.AsyncClient,
        catalog: RestaurantCatalog,
    ):
        self.settings = settings
        self.store = store
        self.llm = llm
        self.mock_http = mock_http
        self.catalog = catalog

    async def run(self, member: Member, conversation_id: str, text: str, channel: TurnChannel) -> str:
        """Run the turn and persist its transcript. Returns "ok" or "error"; never raises."""
        turn: list[dict[str, Any]] = [{"role": "user", "content": [{"type": "text", "text": text}]}]
        session = RestaurantSession(self.settings)
        try:
            memories = await self.store.list_memories(member.id)
            history = recent_turns(await self.store.load_transcript(conversation_id), self.settings.max_history_turns)
            # Operator-authored context after the member's message (mid-conversation system message).
            turn.append({"role": "system", "content": turn_context(member, memories)})
            tools = [*MEMORY_TOOLS, *CALENDAR_TOOLS, *await self.catalog.tools(session)]
            ctx = TurnContext(member, self.store, self.settings, self.mock_http)
            status = await asyncio.wait_for(
                self._loop(history, turn, tools, ctx, channel), timeout=self.settings.turn_timeout_seconds
            )
        except TimeoutError:
            log.warning("Turn timed out in conversation %s", conversation_id)
            status = await self._fail(turn, channel, TIMEOUT_APOLOGY)
        except Exception:
            log.exception("Turn failed in conversation %s", conversation_id)
            status = await self._fail(turn, channel, APOLOGY)
        finally:
            # Cleanup must never cost us the transcript: without it the model loses this turn.
            try:
                await session.aclose()
            except Exception:
                log.exception("Could not close restaurant session in conversation %s", conversation_id)
        try:
            await self.store.append_transcript(conversation_id, turn)
        except Exception:
            # The member has seen this turn's replies, but the model won't remember them next turn.
            log.exception("Could not save the transcript for conversation %s", conversation_id)
        return status

    async def _loop(self, history, turn, tools: list[Tool], ctx: TurnContext, channel: TurnChannel) -> str:
        by_name = {t.name: t for t in tools}
        definitions = [t.definition() for t in tools]

        for call in range(self.settings.max_model_calls_per_turn):
            channel.activity = "starting" if call == 0 else "composing"
            state = _Iteration()
            response = await self._call_model(history + turn, definitions, by_name, state, channel)
            tool_uses = [b for b in response.content if b.get("type") == "tool_use"]
            content = response.content
            if tool_uses:
                # Text beside a tool call is the model thinking aloud ("I need the city: check diary
                # first"); the member only sees the status message. Keeping it out of the transcript
                # also stops the model believing the member saw it, and copying the habit.
                content = [b for b in content if b.get("type") != "text"]
            turn.append({"role": "assistant", "content": content})

            if response.stop_reason == "refusal":
                await channel.post(REFUSAL)
                return "ok"
            if tool_uses:
                self._discard_draft(state, channel)
                if response.stop_reason == "max_tokens":
                    # A truncated tool input parses as a valid partial object; don't run it.
                    results = [
                        _tool_result(b["id"], "Output was cut off; call the tool again.", True) for b in tool_uses
                    ]
                else:
                    results = await asyncio.gather(*(self._run_tool(b, by_name, ctx, channel) for b in tool_uses))
                turn.append({"role": "user", "content": list(results)})
                continue

            await channel.post(state.take_text())
            return "ok"

        log.warning("Turn hit max_model_calls_per_turn (%s)", self.settings.max_model_calls_per_turn)
        return await self._fail(turn, channel, APOLOGY)

    async def _call_model(
        self, messages, definitions, by_name: dict[str, Tool], state: _Iteration, channel: TurnChannel
    ):
        async def on_text(text: str) -> None:
            state.text.append(text)
            channel.delta(text)

        async def on_tool_use(block: dict[str, Any]) -> None:
            # Post progress the moment the call is generated, before the tool runs. Any text the
            # model streamed before the call is never sent: only the curated status message is.
            self._discard_draft(state, channel)
            tool = by_name.get(block.get("name", ""))
            status = (block.get("input") or {}).get(STATUS_FIELD)
            if tool and tool.user_facing and isinstance(status, str) and not state.status_posted:
                state.status_posted = True
                await channel.post(status)

        for attempt in range(MAX_JSON_RETRIES + 1):
            try:
                return await self.llm.respond(
                    system=SYSTEM_PROMPT,
                    messages=messages,
                    tools=definitions,
                    on_text=on_text,
                    on_tool_use=on_tool_use,
                )
            except ToolInputParseError:
                # No complete tool_use to answer, so re-issue the call. Text already posted as a message
                # stays; the streamed-but-unposted draft is discarded on the client.
                if attempt == MAX_JSON_RETRIES:
                    raise
                log.warning("Re-issuing model call after unparseable tool input")
                if state.text:
                    state.text.clear()
                    channel.reset_reply()
        raise AssertionError("unreachable")

    @staticmethod
    def _discard_draft(state: _Iteration, channel: TurnChannel) -> None:
        """Drop streamed-but-unposted text and tell a streaming client to clear its draft."""
        if state.take_text():
            channel.reset_reply()

    async def warm_up(self, member_id: str) -> None:
        """Generate the member's calendar ahead of their first diary lookup.

        First use generates and writes a few hundred events; doing that while the model makes
        its first call keeps it off the member's wait. Best effort: the tool call still works
        (and generates on demand) if this fails.
        """
        try:
            await self.mock_http.get(f"/v1/calendars/{quote(member_id, safe='')}")
        except Exception:
            log.warning("Calendar warm-up failed for member %s", member_id, exc_info=True)

    async def _run_tool(
        self, block: dict[str, Any], by_name: dict[str, Tool], ctx: TurnContext, channel: TurnChannel
    ) -> dict[str, Any]:
        tool = by_name.get(block["name"])
        if tool is None:
            return _tool_result(block["id"], f"Unknown tool {block['name']!r}.", True)
        errors = tool.validate(block.get("input"))
        if errors:
            return _tool_result(block["id"], json.dumps({"invalid_input": errors}), True)

        channel.activity = tool.activity
        channel.emit("tool.started", {"tool_use_id": block["id"], "name": tool.name, "source": tool.source})
        started = time.monotonic()
        is_error = False
        try:
            content = await tool.run(block["input"], ctx)
        except ToolFailure as exc:
            content, is_error = str(exc), True
        except Exception:
            log.exception("Tool %s crashed", tool.name)
            content, is_error = "The tool failed unexpectedly.", True
        channel.emit(
            "tool.finished",
            {
                "tool_use_id": block["id"],
                "name": tool.name,
                "is_error": is_error,
                "duration_ms": round((time.monotonic() - started) * 1000),
            },
        )
        channel.activity = "composing"
        return _tool_result(block["id"], content, is_error)

    async def _fail(self, turn: list[dict[str, Any]], channel: TurnChannel, text: str) -> str:
        """Leave the transcript valid for the next turn, then tell the member."""
        last = turn[-1]
        if last["role"] == "assistant" and any(b.get("type") == "tool_use" for b in last["content"]):
            turn.pop()  # a tool call that never got results would make the next request invalid
        turn.append({"role": "assistant", "content": [{"type": "text", "text": text}]})
        try:
            await channel.post(text)
        except Exception:
            log.exception("Could not post failure message")
        return "error"


def recent_turns(history: list[dict[str, Any]], max_turns: int) -> list[dict[str, Any]]:
    """The last ``max_turns`` turns of a transcript, so request size stays bounded.

    A turn starts at a member message: a user entry holding text rather than tool results.
    Cutting only at those points keeps every tool_use next to its tool_result.
    """
    starts = [
        i
        for i, entry in enumerate(history)
        if entry["role"] == "user" and any(b.get("type") == "text" for b in entry["content"])
    ]
    if len(starts) <= max_turns:
        return history
    return history[starts[-max_turns] :]


def _tool_result(tool_use_id: str, content: str, is_error: bool) -> dict[str, Any]:
    result: dict[str, Any] = {"type": "tool_result", "tool_use_id": tool_use_id, "content": content}
    if is_error:
        result["is_error"] = True
    return result
