import json
import uuid

import anthropic
import httpx2

from app.agent.llm import ToolInputParseError
from app.agent.runner import APOLOGY, REFUSAL, TIMEOUT_APOLOGY, recent_turns

from .conftest import JANE, FakeCatalog, MemoryStore, Step, text, tool_use


def body(message_text: str):
    return {"message_id": str(uuid.uuid4()), "member": JANE, "text": message_text}


def assert_valid_transcript(entries):
    """Every tool_use is answered by a tool_result in the next entry; roles are as the API expects."""
    for i, entry in enumerate(entries):
        assert entry["role"] in {"user", "assistant", "system"}
        if entry["role"] == "assistant":
            ids = {b["id"] for b in entry["content"] if b["type"] == "tool_use"}
            if ids:
                answered = {b["tool_use_id"] for b in entries[i + 1]["content"] if b["type"] == "tool_result"}
                assert ids == answered
    assert entries[-1]["role"] == "assistant"


async def test_tool_turn_posts_status_message_then_reply(make_harness):
    h = await make_harness(
        [
            Step(
                [
                    tool_use(
                        "calendar_check_availability",
                        status_message="Allow me a moment to check your diary…",
                        date="2026-12-03",
                        start_time="19:30",
                        end_time="22:00",
                    ),
                    tool_use("search_restaurants", status_message="Looking for somewhere special…", cuisine="French"),
                ]
            ),
            Step([text("You've got yoga until 19:30. The Gilded Larch has 20:00 - shall I book it?")]),
        ]
    )
    await h.client.post("/conversations/c1/messages", json=body("dinner for 2 thursday, somewhere nice"))
    await h.wait_idle("c1")

    # One status message per model call (parallel calls share it), then the reply.
    assert h.store.texts("c1") == [
        "Allow me a moment to check your diary…",
        "You've got yoga until 19:30. The Gilded Larch has 20:00 - shall I book it?",
    ]
    # Calendar called for this member; restaurant tool got the member injected, not from the model.
    assert h.calendar_requests[0].url.path == f"/v1/calendars/{JANE['id']}/availability"
    assert h.catalog.calls == [{"cuisine": "French", "member_id": JANE["id"]}]

    transcript = h.store.transcripts["c1"]
    assert_valid_transcript(transcript)
    first_text = {"type": "text", "text": "dinner for 2 thursday, somewhere nice"}
    assert transcript[0] == {"role": "user", "content": [first_text]}
    assert transcript[1]["role"] == "system" and "Jane Doe" in transcript[1]["content"]
    results = transcript[3]["content"]
    assert all(not r.get("is_error") for r in results)
    assert "status_message" not in json.dumps(results)  # stripped before the tools ran


async def test_second_turn_sends_history(make_harness):
    h = await make_harness([Step([text("What time?")]), Step([text("Great, 8pm it is.")])])
    await h.client.post("/conversations/c1/messages", json=body("dinner thursday"))
    await h.client.post("/conversations/c1/messages", json=body("8pm"))
    await h.wait_idle("c1")
    assert h.store.texts("c1") == ["What time?", "Great, 8pm it is."]
    second_request = h.llm.calls[1]["messages"]
    assert [m["role"] for m in second_request] == ["user", "system", "assistant", "user", "system"]


async def test_memory_tools_are_silent_and_persist(make_harness):
    h = await make_harness(
        [
            Step([tool_use("memory_save", category="dietary", content="Jane is pescatarian.")]),
            Step([text("Noted - pescatarian-friendly it is.")]),
        ]
    )
    await h.client.post("/conversations/c1/messages", json=body("I'm pescatarian btw"))
    await h.wait_idle("c1")
    assert h.store.texts("c1") == ["Noted - pescatarian-friendly it is."]
    assert [m.content for m in await h.store.list_memories(JANE["id"])] == ["Jane is pescatarian."]
    # Memory tools have no status_message field; member-facing ones require it.
    tools = {t["name"]: t for t in h.llm.calls[0]["tools"]}
    assert "status_message" not in tools["memory_save"]["input_schema"]["properties"]
    assert tools["calendar_add_event"]["input_schema"]["required"][0] == "status_message"
    assert all(t["eager_input_streaming"] for t in tools.values())


async def test_invalid_tool_input_is_returned_as_error(make_harness):
    h = await make_harness(
        [
            Step([tool_use("calendar_check_availability", status_message="Checking…", date="2026-12-03")]),
            Step([text("Sorry, which time?")]),
        ]
    )
    await h.client.post("/conversations/c1/messages", json=body("am I free thursday?"))
    await h.wait_idle("c1")
    result = h.store.transcripts["c1"][3]["content"][0]
    assert result["is_error"] and "start_time" in result["content"]
    assert h.calendar_requests == []


async def test_holding_message_when_quiet_for_too_long(make_harness):
    h = await make_harness(
        [
            Step([tool_use("search_restaurants", status_message="Looking for options…")], delay=1.3),
            Step([text("Found one!")]),
        ],
        holding_after=1.0,
        catalog=FakeCatalog(delay=1.3),
    )
    await h.client.post("/conversations/c1/messages", json=body("find me dinner"))
    await h.wait_idle("c1")
    assert h.store.texts("c1") == [
        "One moment, please…",  # model was quiet for >1s before its first output
        "Looking for options…",
        "Still considering a few options for you…",  # the search took >1s
        "Found one!",
    ]


async def test_model_failure_posts_apology_and_keeps_transcript_valid(make_harness):
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    h = await make_harness(
        [
            Step([tool_use("search_restaurants", status_message="Searching…")]),
            Step([], raises=anthropic.APIConnectionError(request=request)),
        ]
    )
    await h.client.post("/conversations/c1/messages", json=body("dinner?"))
    await h.wait_idle("c1")
    assert h.store.texts("c1")[-1] == APOLOGY
    assert_valid_transcript(h.store.transcripts["c1"])
    assert (await h.store.get_conversation("c1")).status == "idle"


async def test_streaming_emits_events_in_order(make_harness):
    h = await make_harness(
        [
            Step([tool_use("search_restaurants", tool_id="toolu_1", status_message="Searching…")]),
            Step([text("Try "), text("The Gilded Larch.")]),
        ]
    )
    events = []
    async with h.client.stream("POST", "/conversations/c1/messages?stream=true", json=body("dinner?")) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        async for line in response.aiter_lines():
            if line.startswith("event: "):
                name = line[7:]
            elif line.startswith("data: "):
                events.append((name, json.loads(line[6:])))

    names = [e for e, _ in events]
    assert names == [
        "message.created",
        "message.created",
        "tool.started",
        "tool.finished",
        "reply.delta",
        "reply.delta",
        "message.created",
        "turn.completed",
    ]
    assert events[0][1]["role"] == "member"
    assert events[1][1]["text"] == "Searching…"
    assert events[2][1] == {"tool_use_id": "toolu_1", "name": "search_restaurants", "source": "restaurants"}
    assert events[6][1]["text"] == "Try The Gilded Larch."
    assert events[-1][1] == {"status": "ok"}


async def stream_events(h, conversation_id: str, message_text: str) -> list[tuple[str, dict]]:
    events, name = [], None
    url = f"/conversations/{conversation_id}/messages?stream=true"
    async with h.client.stream("POST", url, json=body(message_text)) as response:
        async for line in response.aiter_lines():
            if line.startswith("event: "):
                name = line[7:]
            elif line.startswith("data: "):
                events.append((name, json.loads(line[6:])))
    return events


async def test_turn_timeout_posts_apology(make_harness):
    h = await make_harness([Step([text("never sent")], delay=1.0)], turn_timeout_seconds=0.2)
    await h.client.post("/conversations/c1/messages", json=body("dinner?"))
    await h.wait_idle("c1")
    assert h.store.texts("c1") == [TIMEOUT_APOLOGY]
    assert_valid_transcript(h.store.transcripts["c1"])


async def test_refusal_replaces_partial_text(make_harness):
    h = await make_harness([Step([text("Well, ")], stop_reason="refusal")])
    await h.client.post("/conversations/c1/messages", json=body("something off-limits"))
    await h.wait_idle("c1")
    assert h.store.texts("c1") == [REFUSAL]


async def test_truncated_tool_call_is_not_run(make_harness):
    h = await make_harness(
        [
            Step([tool_use("search_restaurants", status_message="Searching…")], stop_reason="max_tokens"),
            Step([text("Here's what I found.")]),
        ]
    )
    await h.client.post("/conversations/c1/messages", json=body("dinner?"))
    await h.wait_idle("c1")
    assert h.catalog.calls == []
    [result] = h.store.transcripts["c1"][3]["content"]
    assert result["is_error"] and "cut off" in result["content"]
    assert h.store.texts("c1")[-1] == "Here's what I found."


async def test_unparseable_tool_input_retries_and_resets_the_draft(make_harness):
    h = await make_harness(
        [
            Step([text("Let me look… ")], raises=ToolInputParseError("bad JSON")),
            Step([text("Here you go.")]),
        ]
    )
    events = await stream_events(h, "c1", "dinner?")
    names = [e for e, _ in events]
    assert names.index("reply.reset") < names.index("message.created", 1)
    assert h.store.texts("c1") == ["Here you go."]
    assert len(h.llm.calls) == 2


async def test_only_recent_turns_are_sent_to_the_model(make_harness):
    h = await make_harness([Step([text(f"Reply {i}")]) for i in range(3)], max_history_turns=1)
    for i in range(3):
        await h.client.post("/conversations/c1/messages", json=body(f"message {i}"))
    await h.wait_idle("c1")
    third = h.llm.calls[2]["messages"]
    assert [m["role"] for m in third] == ["user", "system", "assistant", "user", "system"]
    assert third[0]["content"][0]["text"] == "message 1"
    assert len(h.store.transcripts["c1"]) == 9  # the stored transcript keeps everything


def test_recent_turns_never_splits_a_tool_exchange():
    history = [
        {"role": "user", "content": [{"type": "text", "text": "one"}]},
        {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "x", "input": {}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "done"}]},
        {"role": "user", "content": [{"type": "text", "text": "two"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "sure"}]},
    ]
    assert recent_turns(history, 5) == history
    assert recent_turns(history, 1) == history[4:]
    assert recent_turns(history, 2) == history


async def test_transcript_save_failure_does_not_break_the_turn(make_harness):
    class NoTranscripts(MemoryStore):
        async def append_transcript(self, conversation_id, entries):
            raise RuntimeError("D1 unavailable")

    h = await make_harness([Step([text("Hello!")])], store=NoTranscripts())
    events = await stream_events(h, "c1", "hi")
    assert events[-1] == ("turn.completed", {"status": "ok"})
    assert h.store.texts("c1") == ["Hello!"]
    assert (await h.store.get_conversation("c1")).status == "idle"
