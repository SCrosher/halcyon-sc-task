"""The real Store SQL and D1 client, against SQLite built from migrations/."""

import pytest

from app.db import D1Error
from app.store import Store

from .d1_fake import FakeD1


@pytest.fixture
async def store():
    db = FakeD1().database()
    yield Store(db)
    await db.close()


async def test_members_and_conversations(store):
    await store.upsert_member("m1", "Jane")
    await store.upsert_member("m1", "Jane Doe")
    conversation = await store.create_conversation("c1", "m1")
    assert (conversation.member_id, conversation.status) == ("m1", "idle")
    assert (await store.create_conversation("c1", "m2")).member_id == "m1"  # INSERT OR IGNORE keeps the owner

    await store.set_status("c1", "processing")
    await store.reset_processing()
    assert (await store.get_conversation("c1")).status == "idle"
    assert await store.get_conversation("nope") is None


async def test_conversation_needs_an_existing_member(store):
    with pytest.raises(D1Error, match="FOREIGN KEY"):
        await store.create_conversation("c1", "ghost")


async def test_messages_keep_order_and_reject_duplicate_ids(store):
    await store.upsert_member("m1", "Jane")
    await store.create_conversation("c1", "m1")
    first = await store.add_message("c1", "member", "hello", "msg-1")
    await store.add_message("c1", "assistant", "hi there")
    assert [m.text for m in await store.list_messages("c1")] == ["hello", "hi there"]
    assert await store.get_message("msg-1") == first
    with pytest.raises(D1Error, match="UNIQUE"):
        await store.add_message("c1", "member", "hello again", "msg-1")


async def test_memories_are_scoped_to_their_member(store):
    await store.upsert_member("m1", "Jane")
    await store.upsert_member("m2", "Bob")
    memory = await store.add_memory("m1", "dietary", "Pescatarian.")
    assert not await store.update_memory("m2", memory.id, "Vegan.", None)
    assert not await store.delete_memory("m2", memory.id)
    assert await store.update_memory("m1", memory.id, "Vegetarian.", None)
    [saved] = await store.list_memories("m1")
    assert (saved.category, saved.content) == ("dietary", "Vegetarian.")
    assert await store.delete_memory("m1", memory.id)
    assert await store.list_memories("m1") == []


async def test_transcript_round_trip(store):
    await store.upsert_member("m1", "Jane")
    await store.create_conversation("c1", "m1")
    entries = [
        {"role": "user", "content": [{"type": "text", "text": "dîner £40"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "Sure"}]},
    ]
    await store.append_transcript("c1", entries[:1])
    await store.append_transcript("c1", entries[1:])
    assert await store.load_transcript("c1") == entries
