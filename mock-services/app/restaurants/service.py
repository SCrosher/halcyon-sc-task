"""Mock restaurant directory and booking engine.

Availability is deterministic: each restaurant/date/slot gets a baseline occupancy
from a hash (busier on Fri/Sat and at peak times, scaled by the restaurant's
popularity), then real bookings stored in the database are subtracted on top.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from ..cities import CITIES, City
from ..db import D1Database

DATA_PATH = Path(__file__).with_name("restaurants.json")
SLOT_MIN = 30
DAY_FACTOR = {0: 0.55, 1: 0.65, 2: 0.8, 3: 0.95, 4: 1.2, 5: 1.25, 6: 0.7}


class BookingError(ValueError):
    pass


@lru_cache
def load_restaurants() -> list[dict[str, Any]]:
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _noise(*parts: str) -> float:
    digest = hashlib.sha256("|".join(parts).encode()).digest()
    return int.from_bytes(digest[:4], "big") / 0xFFFFFFFF  # 0..1


def tables_needed(party_size: int) -> int:
    return 1 if party_size <= 4 else 2 if party_size <= 8 else 3


# tables_needed() as SQL over the bookings table; tests check the two agree.
TABLES_NEEDED_SQL = "CASE WHEN party_size <= 4 THEN 1 WHEN party_size <= 8 THEN 2 ELSE 3 END"


@dataclass
class Slot:
    time: str
    tables_left: int


def city_of(r: dict[str, Any]) -> City:
    return CITIES[r["city"]]


class RestaurantService:
    def __init__(self, db: D1Database, today: Callable[[], date] | None = None):
        """``today`` pins one date for every city (tests); by default it is each city's local date."""
        self.db = db
        self._fixed_today = today
        self.restaurants = {r["id"]: r for r in load_restaurants()}

    def _today(self, city: City) -> date:
        if self._fixed_today is not None:
            return self._fixed_today()
        return datetime.now(ZoneInfo(city.timezone)).date()

    def get(self, restaurant_id: str) -> dict[str, Any]:
        restaurant = self.restaurants.get(restaurant_id)
        if restaurant is None:
            raise BookingError(f"Unknown restaurant_id {restaurant_id!r}. Use search_restaurants to find ids.")
        return restaurant

    @staticmethod
    def summary(r: dict[str, Any]) -> dict[str, Any]:
        city = city_of(r)
        return {
            "restaurant_id": r["id"],
            "name": r["name"],
            "city": city.name,
            "cuisine": r["cuisine"],
            "area": r["area"],
            "price": city.symbol * r["price_level"],
            "avg_spend_per_head": f"{city.symbol}{r['avg_spend']}",
            "rating": r["rating"],
            "tags": r["tags"],
            "dietary_options": r["dietary"],
            "description": r["description"],
        }

    def details(self, restaurant_id: str) -> dict[str, Any]:
        r = self.get(restaurant_id)
        weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        return {
            **self.summary(r),
            "address": r["address"],
            "open_days": [weekdays[d] for d in r["open_days"]],
            "lunch_service": r["lunch"],
            "dinner_service": r["dinner"],
            "max_party_size": r["max_party_size"],
            "timezone": city_of(r).timezone,
        }

    def search(
        self,
        *,
        city: str | None = None,
        query: str | None = None,
        cuisine: str | None = None,
        area: str | None = None,
        max_price_level: int | None = None,
        min_price_level: int | None = None,
        tags: list[str] | None = None,
        dietary: list[str] | None = None,
        party_size: int | None = None,
    ) -> list[dict[str, Any]]:
        def matches(r: dict[str, Any]) -> bool:
            if city and r["city"] != city:
                return False
            if cuisine and cuisine.lower() not in r["cuisine"].lower():
                return False
            if area and area.lower() not in r["area"].lower():
                return False
            if max_price_level and r["price_level"] > max_price_level:
                return False
            if min_price_level and r["price_level"] < min_price_level:
                return False
            if dietary and not all(d.lower() in r["dietary"] for d in dietary):
                return False
            if party_size and party_size > r["max_party_size"]:
                return False
            if query:
                haystack = " ".join([r["name"], r["cuisine"], r["area"], r["description"], *r["tags"]]).lower()
                if not all(word in haystack for word in query.lower().split()):
                    return False
            return True

        results = [r for r in self.restaurants.values() if matches(r)]
        wanted_tags = {t.lower() for t in tags or []}

        def score(r: dict[str, Any]) -> tuple:
            return (len(wanted_tags & set(r["tags"])), r["rating"])

        if wanted_tags:
            # Tags rank rather than filter, so "romantic, quiet" still returns near-misses.
            results = [r for r in results if wanted_tags & set(r["tags"])] or results
        return sorted(results, key=score, reverse=True)

    def _service_slots(self, r: dict[str, Any], day: date) -> list[str]:
        if day.weekday() not in r["open_days"]:
            return []
        slots = []
        for window in (r["lunch"], r["dinner"]):
            if not window:
                continue
            start, end = _minutes(window[0]), _minutes(window[1])
            t = start
            while t <= end:
                slots.append(_hhmm(t))
                t += SLOT_MIN
        return slots

    def _baseline_tables_taken(self, r: dict[str, Any], day: date, slot: str) -> int:
        minutes = _minutes(slot)
        peak = 1.25 if 19 * 60 <= minutes <= 20 * 60 + 30 else 1.0 if minutes >= 18 * 60 else 0.7
        occupancy = r["popularity"] * DAY_FACTOR[day.weekday()] * peak
        occupancy += (_noise(r["id"], day.isoformat(), slot) - 0.5) * 0.5
        occupancy = max(0.0, min(1.0, occupancy))
        return round(occupancy * r["tables_per_slot"])

    async def _booked_tables(self, restaurant_id: str, day: date) -> dict[str, int]:
        rows = (
            await self.db.execute(
                "SELECT time, party_size FROM bookings WHERE restaurant_id = ? AND date = ? AND status = 'confirmed'",
                (restaurant_id, day.isoformat()),
            )
        ).rows
        taken: dict[str, int] = {}
        for row in rows:
            taken[row["time"]] = taken.get(row["time"], 0) + tables_needed(int(row["party_size"]))
        return taken

    def _validate_day(self, r: dict[str, Any], day: date) -> None:
        city = city_of(r)
        today = self._today(city)
        if day < today:
            raise BookingError(f"{day.isoformat()} is in the past (today in {city.name} is {today.isoformat()}).")
        if day > today + timedelta(days=90):
            raise BookingError("Bookings open 90 days in advance.")

    async def slots(self, restaurant_id: str, day: date, party_size: int) -> list[Slot]:
        r = self.get(restaurant_id)
        self._validate_day(r, day)
        if party_size > r["max_party_size"]:
            return []
        needed = tables_needed(party_size)
        booked = await self._booked_tables(restaurant_id, day)
        result = []
        for slot in self._service_slots(r, day):
            left = r["tables_per_slot"] - self._baseline_tables_taken(r, day, slot) - booked.get(slot, 0)
            if left >= needed:
                result.append(Slot(slot, left))
        return result

    async def availability(
        self, restaurant_id: str, day: date, party_size: int, preferred_time: str | None = None, window_min: int = 90
    ) -> dict[str, Any]:
        r = self.get(restaurant_id)
        all_slots = await self.slots(restaurant_id, day, party_size)
        times = [s.time for s in all_slots]
        if preferred_time:
            target = _minutes(preferred_time)
            times = [t for t in times if abs(_minutes(t) - target) <= window_min]
            times.sort(key=lambda t: abs(_minutes(t) - target))
        note = None
        if day.weekday() not in r["open_days"]:
            note = f"{r['name']} is closed on {day.strftime('%A')}s."
        elif party_size > r["max_party_size"]:
            note = f"{r['name']} takes parties of up to {r['max_party_size']} online."
        elif not times:
            note = "Fully booked around that time."
        return {
            "restaurant_id": r["id"],
            "name": r["name"],
            "date": day.isoformat(),
            "party_size": party_size,
            "available_times": times[:8],
            "note": note,
        }

    async def create_booking(
        self,
        *,
        restaurant_id: str,
        day: date,
        time: str,
        party_size: int,
        member_id: str,
        member_name: str,
        occasion: str | None = None,
        special_requests: str | None = None,
    ) -> dict[str, Any]:
        r = self.get(restaurant_id)
        if party_size < 1:
            raise BookingError("party_size must be at least 1")
        no_table = BookingError(
            f"{r['name']} has no table for {party_size} at {time} on {day.isoformat()}. "
            "Call check_availability for open times."
        )
        self._validate_day(r, day)
        if party_size > r["max_party_size"] or time not in self._service_slots(r, day):
            raise no_table
        # Booked tables may not exceed this; the check and the insert are one statement, so two
        # concurrent bookings can't both take the last table.
        allowed = r["tables_per_slot"] - self._baseline_tables_taken(r, day, time) - tables_needed(party_size)
        booking_id = str(uuid.uuid4())
        reference = "HC-" + secrets.token_hex(3).upper()
        result = await self.db.execute(
            "INSERT INTO bookings (id, reference, restaurant_id, member_id, member_name, date, time, party_size, "
            "occasion, special_requests, status, created_at) "
            "SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'confirmed', ? "
            f"WHERE (SELECT COALESCE(SUM({TABLES_NEEDED_SQL}), 0) FROM bookings "
            # CAST: D1 params arrive as strings, and an integer never compares <= a string in SQLite.
            "WHERE restaurant_id = ? AND date = ? AND time = ? AND status = 'confirmed') <= CAST(? AS INTEGER)",
            (
                booking_id,
                reference,
                restaurant_id,
                member_id,
                member_name,
                day.isoformat(),
                time,
                party_size,
                occasion,
                special_requests,
                datetime.now(UTC).isoformat(),
                restaurant_id,
                day.isoformat(),
                time,
                allowed,
            ),
        )
        if result.changes == 0:
            raise no_table
        return {
            "booking_id": booking_id,
            "reference": reference,
            "status": "confirmed",
            "restaurant": {
                "restaurant_id": r["id"],
                "name": r["name"],
                "address": r["address"],
                "area": r["area"],
                "city": city_of(r).name,
            },
            "date": day.isoformat(),
            "time": time,
            "party_size": party_size,
            "occasion": occasion,
            "special_requests": special_requests,
        }

    def _booking_view(self, row: dict[str, Any]) -> dict[str, Any]:
        r = self.restaurants.get(row["restaurant_id"], {})
        return {
            "booking_id": row["id"],
            "reference": row["reference"],
            "status": row["status"],
            "restaurant_id": row["restaurant_id"],
            "restaurant_name": r.get("name"),
            "area": r.get("area"),
            "city": city_of(r).name if r else None,
            "cuisine": r.get("cuisine"),
            "date": row["date"],
            "time": row["time"],
            "party_size": int(row["party_size"]),
            "occasion": row["occasion"],
            "special_requests": row["special_requests"],
        }

    async def list_bookings(self, member_id: str, include_past: bool = True) -> list[dict[str, Any]]:
        rows = (
            await self.db.execute(
                "SELECT * FROM bookings WHERE member_id = ? ORDER BY date DESC, time DESC LIMIT 50", (member_id,)
            )
        ).rows

        def upcoming(row: dict[str, Any]) -> bool:
            r = self.restaurants.get(row["restaurant_id"])
            return row["date"] >= self._today(city_of(r) if r else CITIES["london"]).isoformat()

        return [self._booking_view(r) for r in rows if include_past or upcoming(r)]

    async def cancel_booking(self, booking_id: str, member_id: str) -> dict[str, Any]:
        rows = (
            await self.db.execute("SELECT * FROM bookings WHERE id = ? OR reference = ?", (booking_id, booking_id))
        ).rows
        if not rows or rows[0]["member_id"] != member_id:
            raise BookingError("Booking not found for this member.")
        row = rows[0]
        if row["status"] == "cancelled":
            return self._booking_view(row)
        await self.db.execute("UPDATE bookings SET status = 'cancelled' WHERE id = ?", (row["id"],))
        row["status"] = "cancelled"
        return self._booking_view(row)
