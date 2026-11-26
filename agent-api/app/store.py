"""Data access for members, memories, conversations, messages and transcripts (D1)."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from .db import D1Database


def utc_now() -> str:
    # Microsecond precision so messages written in quick succession keep their order.
    return datetime.now(UTC).isoformat(timespec="microseconds")


@dataclass
class Member:
    id: str
    name: str


@dataclass
class Conversation:
    id: str
    member_id: str
    status: str
    created_at: str
    updated_at: str


@dataclass
class Message:
    id: str
    conversation_id: str
    role: str
    text: str
    created_at: str


@dataclass
class Memory:
    id: str
    member_id: str
    category: str
    content: str
    created_at: str
    updated_at: str


class Store:
    def __init__(self, db: D1Database):
        self.db = db

    async def upsert_member(self, member_id: str, name: str) -> Member:
        now = utc_now()
        await self.db.execute(
            "INSERT INTO members (id, name, created_at, updated_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT (id) DO UPDATE SET name = excluded.name, updated_at = excluded.updated_at",
            (member_id, name, now, now),
        )
        return Member(member_id, name)

    async def list_memories(self, member_id: str) -> list[Memory]:
        rows = (
            await self.db.execute(
                "SELECT * FROM memories WHERE member_id = ? ORDER BY category, created_at", (member_id,)
            )
        ).rows
        return [Memory(**r) for r in rows]

    async def add_memory(self, member_id: str, category: str, content: str) -> Memory:
        now = utc_now()
        memory = Memory(str(uuid.uuid4()), member_id, category, content, now, now)
        await self.db.execute(
            "INSERT INTO memories (id, member_id, category, content, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (memory.id, member_id, category, content, now, now),
        )
        return memory

    async def update_memory(self, member_id: str, memory_id: str, content: str, category: str | None) -> bool:
        result = await self.db.execute(
            "UPDATE memories SET content = ?, category = COALESCE(?, category), updated_at = ? "
            "WHERE id = ? AND member_id = ?",
            (content, category, utc_now(), memory_id, member_id),
        )
        return result.changes > 0

    async def delete_memory(self, member_id: str, memory_id: str) -> bool:
        result = await self.db.execute("DELETE FROM memories WHERE id = ? AND member_id = ?", (memory_id, member_id))
        return result.changes > 0

    async def get_conversation(self, conversation_id: str) -> Conversation | None:
        rows = (await self.db.execute("SELECT * FROM conversations WHERE id = ?", (conversation_id,))).rows
        return Conversation(**rows[0]) if rows else None

    async def create_conversation(self, conversation_id: str, member_id: str) -> Conversation:
        now = utc_now()
        await self.db.execute(
            "INSERT OR IGNORE INTO conversations (id, member_id, status, created_at, updated_at) "
            "VALUES (?, ?, 'idle', ?, ?)",
            (conversation_id, member_id, now, now),
        )
        return await self.get_conversation(conversation_id)

    async def set_status(self, conversation_id: str, status: str) -> None:
        await self.db.execute(
            "UPDATE conversations SET status = ?, updated_at = ? WHERE id = ?", (status, utc_now(), conversation_id)
        )

    async def reset_processing(self) -> None:
        """On startup no turn is running, so nothing can genuinely be 'processing'."""
        await self.db.execute("UPDATE conversations SET status = 'idle' WHERE status = 'processing'")

    async def get_message(self, message_id: str) -> Message | None:
        rows = (await self.db.execute("SELECT * FROM messages WHERE id = ?", (message_id,))).rows
        return Message(**rows[0]) if rows else None

    async def add_message(self, conversation_id: str, role: str, text: str, message_id: str | None = None) -> Message:
        message = Message(message_id or str(uuid.uuid4()), conversation_id, role, text, utc_now())
        await self.db.execute(
            "INSERT INTO messages (id, conversation_id, role, text, created_at) VALUES (?, ?, ?, ?, ?)",
            (message.id, conversation_id, role, text, message.created_at),
        )
        return message

    async def list_messages(self, conversation_id: str) -> list[Message]:
        rows = (
            await self.db.execute(
                "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at, rowid", (conversation_id,)
            )
        ).rows
        return [Message(**r) for r in rows]

    async def load_transcript(self, conversation_id: str) -> list[dict[str, Any]]:
        rows = (
            await self.db.execute(
                "SELECT entry FROM transcript_entries WHERE conversation_id = ? ORDER BY id", (conversation_id,)
            )
        ).rows
        return [json.loads(r["entry"]) for r in rows]

    async def append_transcript(self, conversation_id: str, entries: list[dict[str, Any]]) -> None:
        if not entries:
            return
        now = utc_now()
        await self.db.batch(
            [
                (
                    "INSERT INTO transcript_entries (conversation_id, entry, created_at) VALUES (?, ?, ?)",
                    (conversation_id, json.dumps(entry, ensure_ascii=False), now),
                )
                for entry in entries
            ]
        )

    async def log_request(
        self,
        method: str,
        path: str,
        query: str | None,
        status_code: int,
        duration_ms: int,
        client_ip: str | None,
        error: str | None,
    ) -> None:
        await self.db.execute(
            "INSERT INTO request_logs (method, path, query, status_code, duration_ms, client_ip, error, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (method, path, query or None, status_code, duration_ms, client_ip, error, utc_now()),
        )

    async def prune_request_logs(self, older_than: timedelta) -> int:
        """Delete request logs older than ``older_than``. Returns how many were deleted."""
        cutoff = (datetime.now(UTC) - older_than).isoformat(timespec="microseconds")
        result = await self.db.execute("DELETE FROM request_logs WHERE created_at < ?", (cutoff,))
        return result.changes
