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
