from datetime import date, timedelta

import httpx2
import pytest

from app.calendar.service import MAX_DAYS_AHEAD, WINDOW_DAYS_AHEAD, WINDOW_DAYS_BACK, DateOutOfRange
from app.config import Settings
from app.main import create_app

from .conftest import TODAY

MEMBER = "member-abc"


async def test_first_request_generates_the_default_window(calendar):
    row = await calendar.ensure(MEMBER)
    assert row["generated_from"] == (TODAY - timedelta(days=WINDOW_DAYS_BACK)).isoformat()
    assert row["generated_to"] == (TODAY + timedelta(days=WINDOW_DAYS_AHEAD)).isoformat()
    assert await calendar.events(MEMBER, TODAY, TODAY + timedelta(days=6))


async def test_later_requests_extend_the_stored_range(calendar):
    await calendar.ensure(MEMBER)
    later = TODAY + timedelta(days=WINDOW_DAYS_AHEAD + 30)
    events = await calendar.events(MEMBER, later, later + timedelta(days=6))
    assert events and all(later.isoformat() <= e.date for e in events)
    assert (await calendar.ensure(MEMBER))["generated_to"] == (later + timedelta(days=6)).isoformat()
    # Regenerating an overlapping range is idempotent: deterministic ids + INSERT OR IGNORE.
    again = await calendar.events(MEMBER, later, later + timedelta(days=6))
    assert [e.id for e in again] == [e.id for e in events]


async def test_dates_far_from_today_are_rejected(calendar):
    with pytest.raises(DateOutOfRange):
        await calendar.events(MEMBER, date(1900, 1, 1), date(1900, 1, 2))
    with pytest.raises(DateOutOfRange):
        await calendar.availability(MEMBER, TODAY + timedelta(days=MAX_DAYS_AHEAD + 1), "19:00", "21:00")


async def test_added_events_show_up_as_conflicts(calendar):
    await calendar.add_event(
        MEMBER,
        title="Dinner at Verdant",
        day=TODAY,
        start_time="19:00",
        end_time="21:00",
        all_day=False,
        location=None,
        notes="HC-ABC123",
        category="dining",
    )
    result = await calendar.availability(MEMBER, TODAY, "20:00", "22:00")
    assert not result["free"]
    assert "Dinner at Verdant" in [c["title"] for c in result["conflicts"]]


async def test_api_requires_the_token_and_bounds_dates(calendar):
    app = create_app(Settings(_env_file=None, mock_services_token="secret"))
    app.state.calendar = calendar
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/health")).status_code == 200
        assert (await client.get(f"/v1/calendars/{MEMBER}")).status_code == 401
        wrong = await client.get(f"/v1/calendars/{MEMBER}", headers={"Authorization": "Bearer nope"})
        assert wrong.status_code == 401

        auth = {"Authorization": "Bearer secret"}
        ok = await client.get(f"/v1/calendars/{MEMBER}/events", params={"start": TODAY.isoformat()}, headers=auth)
        assert ok.status_code == 200
        far = await client.get(f"/v1/calendars/{MEMBER}/events", params={"start": "1900-01-01"}, headers=auth)
        assert far.status_code == 422 and "between" in far.json()["detail"]


async def _dinner(calendar):
    return await calendar.add_event(
        MEMBER,
        title="Dinner at Verdant (2 people)",
        day=TODAY,
        start_time="19:00",
        end_time="21:00",
        all_day=False,
        location="Soho",
        notes="HC-ABC123",
        category="dining",
    )


async def test_events_can_be_fetched_updated_and_deleted(calendar):
    event = await _dinner(calendar)
    assert (await calendar.get_event(MEMBER, event.id)).notes == "HC-ABC123"
    assert await calendar.get_event("someone-else", event.id) is None

    moved = await calendar.update_event(
        MEMBER,
        event.id,
        title="Dinner at Verdant (4 people)",
        day=TODAY + timedelta(days=1),
        start_time="20:00",
        end_time="22:00",
        all_day=False,
        location="Soho",
        notes="HC-ABC123",
        category="dining",
    )
    assert (moved.id, moved.date, moved.start_time, moved.source) == (
        event.id,
        (TODAY + timedelta(days=1)).isoformat(),
        "20:00",
        "member",
    )
    assert event.id not in [e.id for e in await calendar.events(MEMBER, TODAY, TODAY)]

    assert await calendar.delete_event(MEMBER, event.id)
    assert await calendar.get_event(MEMBER, event.id) is None
    assert not await calendar.delete_event(MEMBER, event.id)


async def test_api_patches_and_deletes_events(calendar):
    app = create_app(Settings(_env_file=None, mock_services_token="secret"))
    app.state.calendar = calendar
    event = await _dinner(calendar)
    auth = {"Authorization": "Bearer secret"}
    url = f"/v1/calendars/{MEMBER}/events/{event.id}"
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://test") as client:
        patched = await client.patch(url, json={"start_time": "19:30", "end_time": "21:30"}, headers=auth)
        assert patched.status_code == 200
        body = patched.json()["event"]
        # Only the given fields change.
        assert (body["start_time"], body["title"], body["notes"]) == ("19:30", event.title, "HC-ABC123")

        backwards = await client.patch(url, json={"end_time": "19:00"}, headers=auth)
        assert backwards.status_code == 422 and "end_time must be after start_time" in backwards.json()["detail"]

        all_day = await client.patch(url, json={"all_day": True}, headers=auth)
        assert all_day.json()["event"]["start_time"] is None
        timed_again = await client.patch(url, json={"start_time": "18:00", "end_time": "19:00"}, headers=auth)
        assert timed_again.json()["event"]["all_day"] is False

        far = await client.patch(url, json={"date": "1900-01-01"}, headers=auth)
        assert far.status_code == 422

        assert (await client.get(url, headers=auth)).status_code == 200
        assert (await client.delete(url, headers=auth)).status_code == 204
        assert (await client.get(url, headers=auth)).status_code == 404
        assert (await client.patch(url, json={"title": "x"}, headers=auth)).status_code == 404
        assert (await client.delete(url, headers=auth)).status_code == 404
