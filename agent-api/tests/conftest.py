"""Test doubles: an in-memory Store, a scripted model and a fake calendar service."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from typing import Any

import httpx2
import pytest

from app.agent.llm import ModelResponse
from app.agent.runner import TurnRunner
from app.agent.tools.base import Tool, object_schema
from app.config import Settings
from app.conversations import ConversationService
from app.db import D1Error
from app.main import create_app
from app.store import Conversation, Member, Memory, Message, utc_now

TOKEN = "test-token"
JANE = {"id": "7c1e4b2a-5f3d-4e8c-a9b6-2d1f0e7c3b45", "name": "Jane Doe"}


class MemoryStore:
    """Implements the Store interface in memory."""

    def __init__(self) -> None:
        self.members: dict[str, Member] = {}
        self.memories: dict[str, Memory] = {}
        self.conversations: dict[str, Conversation] = {}
        self.messages: list[Message] = []
        self.transcripts: dict[str, list[dict[str, Any]]] = {}

    async def upsert_member(self, member_id, name):
        self.members[member_id] = Member(member_id, name)
        return self.members[member_id]

    async def list_memories(self, member_id):
        return [m for m in self.memories.values() if m.member_id == member_id]

    async def add_memory(self, member_id, category, content):
        now = utc_now()
        memory = Memory(str(uuid.uuid4()), member_id, category, content, now, now)
        self.memories[memory.id] = memory
        return memory

    async def update_memory(self, member_id, memory_id, content, category):
        m = self.memories.get(memory_id)
        if not m or m.member_id != member_id:
            return False
        self.memories[memory_id] = replace(m, content=content, category=category or m.category, updated_at=utc_now())
        return True

    async def delete_memory(self, member_id, memory_id):
        m = self.memories.get(memory_id)
        if not m or m.member_id != member_id:
            return False
        del self.memories[memory_id]
        return True

    async def get_conversation(self, conversation_id):
        return self.conversations.get(conversation_id)

    async def create_conversation(self, conversation_id, member_id):
        now = utc_now()
        self.conversations.setdefault(conversation_id, Conversation(conversation_id, member_id, "idle", now, now))
        return self.conversations[conversation_id]

    async def set_status(self, conversation_id, status):
        c = self.conversations[conversation_id]
        self.conversations[conversation_id] = replace(c, status=status, updated_at=utc_now())

    async def reset_processing(self):
        pass

    async def get_message(self, message_id):
        return next((m for m in self.messages if m.id == message_id), None)

    async def add_message(self, conversation_id, role, text, message_id=None):
        if message_id and await self.get_message(message_id):
            raise D1Error("UNIQUE constraint failed: messages.id")
        message = Message(message_id or str(uuid.uuid4()), conversation_id, role, text, utc_now())
        self.messages.append(message)
        return message

    async def list_messages(self, conversation_id):
        return [m for m in self.messages if m.conversation_id == conversation_id]

    async def load_transcript(self, conversation_id):
        return list(self.transcripts.get(conversation_id, []))

    async def append_transcript(self, conversation_id, entries):
        self.transcripts.setdefault(conversation_id, []).extend(entries)

    async def log_request(self, *args, **kwargs):
        pass

    def texts(self, conversation_id: str, role: str = "assistant") -> list[str]:
        return [m.text for m in self.messages if m.conversation_id == conversation_id and m.role == role]


# ---- scripted model -----------------------------------------------------------------------


def text(t: str) -> dict[str, Any]:
    return {"type": "text", "text": t}


def tool_use(name: str, tool_id: str | None = None, **inputs: Any) -> dict[str, Any]:
    return {"type": "tool_use", "id": tool_id or f"toolu_{uuid.uuid4().hex[:8]}", "name": name, "input": inputs}


@dataclass
class Step:
    content: list[dict[str, Any]]
    stop_reason: str = "end_turn"
    delay: float = 0.0
    raises: Exception | None = None


@dataclass
class ScriptedLLM:
    """Replays scripted responses through the same callbacks the real client uses."""

    steps: list[Step]
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def respond(self, *, system, messages, tools, on_text, on_tool_use):
        self.calls.append({"system": system, "messages": [dict(m) for m in messages], "tools": tools})
        step = self.steps.pop(0)
        if step.delay:
            await asyncio.sleep(step.delay)
        for block in step.content:
            if block["type"] == "text":
                await on_text(block["text"])
            elif block["type"] == "tool_use":
                await on_tool_use(block)
        if step.raises:  # after streaming the content, like a stream that fails part-way
            raise step.raises
        stop = step.stop_reason
        if stop == "end_turn" and any(b["type"] == "tool_use" for b in step.content):
            stop = "tool_use"
        return ModelResponse(content=step.content, stop_reason=stop)

    async def aclose(self):
        pass


# ---- fake services ------------------------------------------------------------------------


def calendar_transport(log: list[httpx2.Request]) -> httpx2.MockTransport:
    def handler(request: httpx2.Request) -> httpx2.Response:
        log.append(request)
        if request.url.path.endswith("/availability"):
            q = request.url.params
            return httpx2.Response(
                200,
                json={
                    "date": q["date"],
                    "start_time": q["start_time"],
                    "end_time": q["end_time"],
                    "free": False,
                    "conflicts": [
                        {
                            "id": "e1",
                            "title": "Yoga",
                            "date": q["date"],
                            "start_time": "18:30",
                            "end_time": "19:30",
                            "all_day": False,
                            "location": "Studio",
                            "category": "fitness",
                            "source": "generated",
                        }
                    ],
                    "day_events": [],
                },
            )
        if request.url.path.endswith("/events") and request.method == "POST":
            return httpx2.Response(201, json={"event": {"id": "new", **json.loads(request.content)}})
        return httpx2.Response(200, json={"start": "2026-12-03", "end": "2026-12-03", "events": []})

    return httpx2.MockTransport(handler)


class FakeCatalog:
    """Stands in for the MCP restaurant catalog with one in-process tool."""

    def __init__(self, delay: float = 0.0):
        self.delay = delay
        self.calls: list[dict[str, Any]] = []

    async def tools(self, session) -> list[Tool]:
        async def search(args, ctx):
            self.calls.append({**args, "member_id": ctx.member.id})
            await asyncio.sleep(self.delay)
            return {
                "results": [
                    {
                        "restaurant_id": "the-gilded-larch",
                        "name": "The Gilded Larch",
                        "available_times": ["19:30", "20:00"],
                    }
                ]
            }

        return [
            Tool(
                name="search_restaurants",
                description="Search restaurants",
                parameters=object_schema({"cuisine": {"type": "string"}}, []),
                source="restaurants",
                activity="search",
                handler=search,
            )
        ]


@dataclass
class Harness:
    app: Any
    store: MemoryStore
    llm: ScriptedLLM
    catalog: FakeCatalog
    calendar_requests: list[httpx2.Request]
    client: httpx2.AsyncClient

    async def wait_idle(self, conversation_id: str, within: float = 5.0) -> None:
        async with asyncio.timeout(within):
            # The store has no change notifications, so poll it.
            while (await self.store.get_conversation(conversation_id)).status != "idle":  # noqa: ASYNC110
                await asyncio.sleep(0.01)
        await self.app.state.conversations.drain()


MakeHarness = Callable[..., Awaitable[Harness]]


@pytest.fixture
async def make_harness():
    clients: list[httpx2.AsyncClient] = []

    async def build(
        steps: list[Step],
        *,
        holding_after: float = 9.0,
        catalog: FakeCatalog | None = None,
        store: MemoryStore | None = None,
        **overrides: Any,
    ) -> Harness:
        settings = Settings(
            _env_file=None, agent_api_tokens=TOKEN, holding_message_after_seconds=holding_after, **overrides
        )
        store = store or MemoryStore()
        llm = ScriptedLLM(list(steps))
        catalog = catalog or FakeCatalog()
        calendar_requests: list[httpx2.Request] = []
        mock_http = httpx2.AsyncClient(base_url="http://mock", transport=calendar_transport(calendar_requests))
        app = create_app(settings)
        app.state.store = store
        app.state.conversations = ConversationService(
            settings, store, TurnRunner(settings, store, llm, mock_http, catalog)
        )
        client = httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
        clients.extend([client, mock_http])
        return Harness(app, store, llm, catalog, calendar_requests, client)

    yield build
    for c in clients:
        await c.aclose()
