from __future__ import annotations

from datetime import date

import pytest

from app.calendar.rules import load_rules
from app.calendar.service import CalendarService
from app.restaurants.service import RestaurantService

from .d1_fake import FakeD1

TODAY = date(2026, 11, 26)  # a Thursday


@pytest.fixture
async def d1():
    fake = FakeD1()
    db = fake.database()
    yield fake, db
    await db.close()


@pytest.fixture
def restaurants(d1) -> RestaurantService:
    return RestaurantService(d1[1], today=lambda: TODAY)


@pytest.fixture
def calendar(d1) -> CalendarService:
    return CalendarService(d1[1], load_rules(), today=lambda: TODAY)
