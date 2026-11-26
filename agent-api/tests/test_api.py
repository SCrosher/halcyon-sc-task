import asyncio
import re
import uuid

import pytest

from app.db import D1Error
from app.schemas import PostMessage

from .conftest import JANE, MemoryStore, Step, text

ISO_Z = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")


def body(message_text: str = "need dinner for 2 thurs, somewhere nice", member=JANE, message_id=None):
    return {"message_id": message_id or str(uuid.uuid4()), "member": member, "text": message_text}


async def test_post_answers_202_and_get_lists_oldest_first(make_harness):
    h = await make_harness([Step([text("Happy to. What time suits you?")])])
    payload = body()
    response = await h.client.post("/conversations/c1/messages", json=payload)
    assert response.status_code == 202
    assert response.json() == {"message_id": payload["message_id"], "conversation_id": "c1", "status": "accepted"}

    await h.wait_idle("c1")
    listed = (await h.client.get("/conversations/c1/messages")).json()["messages"]
    assert [(m["role"], m["text"]) for m in listed] == [
        ("member", "need dinner for 2 thurs, somewhere nice"),
        ("assistant", "Happy to. What time suits you?"),
    ]
    assert listed[0]["id"] == payload["message_id"]
    assert all(set(m) == {"id", "role", "text", "created_at"} and ISO_Z.match(m["created_at"]) for m in listed)

    conversation = (await h.client.get("/conversations/c1")).json()
    assert conversation["status"] == "idle" and conversation["member_id"] == JANE["id"]


async def test_bearer_token_required(make_harness):
    h = await make_harness([])
    for headers in ({"Authorization": ""}, {"Authorization": "Bearer wrong"}, {"Authorization": "Basic abc"}):
        response = await h.client.get("/conversations/c1/messages", headers=headers)
        assert response.status_code == 401
    assert (await h.client.get("/health", headers={})).status_code == 200


async def test_duplicate_message_id_is_idempotent(make_harness):
    h = await make_harness([Step([text("Hi!")])])
    payload = body()
    await h.client.post("/conversations/c1/messages", json=payload)
    await h.wait_idle("c1")
    again = await h.client.post("/conversations/c1/messages", json=payload)
    assert again.status_code == 202 and again.json()["status"] == "duplicate"
    assert len(h.store.messages) == 2  # no second member message, no second turn
    assert len(h.llm.calls) == 1


async def test_conversation_belongs_to_one_member(make_harness):
    h = await make_harness([Step([text("Hi!")])])
    await h.client.post("/conversations/c1/messages", json=body())
    other = body(member={"id": "someone-else", "name": "Bob"})
    response = await h.client.post("/conversations/c1/messages", json=other)
    assert response.status_code == 409
    await h.wait_idle("c1")


async def test_rejected_message_does_not_rename_the_member(make_harness):
    h = await make_harness([Step([text("Hi!")])])
    await h.store.upsert_member("bob", "Bob")
    await h.client.post("/conversations/c1/messages", json=body())
    response = await h.client.post("/conversations/c1/messages", json=body(member={"id": "bob", "name": "Mallory"}))
    assert response.status_code == 409
    assert h.store.members["bob"].name == "Bob"
    await h.wait_idle("c1")


async def test_failed_status_write_does_not_leave_the_turn_pending(make_harness):
    class FlakyStore(MemoryStore):
        fail_next = True

        async def set_status(self, conversation_id, status):
            if status == "processing" and self.fail_next:
                self.fail_next = False
                raise D1Error("D1 unavailable")
            await super().set_status(conversation_id, status)

    h = await make_harness([Step([text("Hi!")])], store=FlakyStore())
    service = h.app.state.conversations
    with pytest.raises(D1Error):
        await service.accept("c1", PostMessage.model_validate(body()), streaming=False)
    assert not service._pending

    await h.client.post("/conversations/c1/messages", json=body("second try"))
    await h.wait_idle("c1")
    assert h.store.texts("c1") == ["Hi!"]


async def test_unknown_conversation_and_validation(make_harness):
    h = await make_harness([])
    assert (await h.client.get("/conversations/nope/messages")).status_code == 404
    bad = await h.client.post("/conversations/c1/messages", json={"message_id": "x", "text": "hi"})
    assert bad.status_code == 422


async def test_request_log_skips_successful_reads(make_harness):
    h = await make_harness([Step([text("Hi!")])])
    await h.client.post("/conversations/c1/messages", json=body())
    await h.wait_idle("c1")
    await h.client.get("/conversations/c1/messages")  # a poll: not logged
    await h.client.get("/conversations/nope")  # a failed read: logged
    await h.client.get("/conversations/c1", headers={"Authorization": "Bearer wrong"})  # logged
    for _ in range(10):  # let the background log writes run
        await asyncio.sleep(0)
    assert [(e["method"], e["path"], e["status_code"]) for e in h.store.request_logs] == [
        ("POST", "/conversations/c1/messages", 202),
        ("GET", "/conversations/nope", 404),
        ("GET", "/conversations/c1", 401),
    ]


async def test_memories_endpoint(make_harness):
    h = await make_harness([])
    await h.store.add_memory(JANE["id"], "dietary", "Pescatarian.")
    memories = (await h.client.get(f"/members/{JANE['id']}/memories")).json()["memories"]
    assert [(m["category"], m["content"]) for m in memories] == [("dietary", "Pescatarian.")]
