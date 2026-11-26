from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

from .store import Conversation, Memory, Message


def api_time(value: str) -> str:
    """Stored timestamps -> the API's second-precision UTC format, e.g. 2026-11-16T09:12:03Z."""
    return datetime.fromisoformat(value).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class MemberRef(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)


class PostMessage(BaseModel):
    message_id: str = Field(min_length=1, max_length=100)
    member: MemberRef
    text: str = Field(min_length=1, max_length=4000)


class Accepted(BaseModel):
    message_id: str
    conversation_id: str
    status: Literal["accepted", "duplicate"]


class MessageOut(BaseModel):
    id: str
    role: Literal["member", "assistant"]
    text: str
    created_at: str

    @classmethod
    def of(cls, message: Message) -> MessageOut:
        return cls(id=message.id, role=message.role, text=message.text, created_at=api_time(message.created_at))


class MessagesOut(BaseModel):
    messages: list[MessageOut]


class ConversationOut(BaseModel):
    id: str
    member_id: str
    status: Literal["idle", "processing"]
    created_at: str
    updated_at: str

    @classmethod
    def of(cls, c: Conversation) -> ConversationOut:
        return cls(
            id=c.id,
            member_id=c.member_id,
            status=c.status,
            created_at=api_time(c.created_at),
            updated_at=api_time(c.updated_at),
        )


class MemoryOut(BaseModel):
    id: str
    category: str
    content: str
    updated_at: str

    @classmethod
    def of(cls, m: Memory) -> MemoryOut:
        return cls(id=m.id, category=m.category, content=m.content, updated_at=api_time(m.updated_at))


class MemoriesOut(BaseModel):
    memories: list[MemoryOut]
