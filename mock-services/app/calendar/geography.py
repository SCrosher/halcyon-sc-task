"""Where a member is: a home city plus occasional trips, layered over the trait calendar.

The trait library is deliberately place-free, so location comes from here. Every member
gets a home city (one of the covered cities) and, per fortnight-long block of the
calendar, maybe one trip of 2-5 days. Trips only go to the other covered cities, so
whatever the diary says, the agent can book there (members can still ask about other
cities themselves). Everything is derived from the seed, member id and date, so any day
can be generated on its own, in any order, with the same result.

On trip days the member's usual routine is replaced by the trip: an all-day
"<city>" travel event whose location is the city, flights out and home, and (for work
trips) daytime meetings.
"""

from __future__ import annotations

import hashlib
import random
import uuid
from dataclasses import dataclass
from datetime import date, timedelta

from ..cities import CITIES, City

EVENT_NAMESPACE = uuid.UUID("0b8f7d52-3c1a-4e6b-9d2f-7a4c5e1b8f30")
BLOCK_DAYS = 14
HOME_WEIGHTS = {"london": 4, "new_york": 3, "paris": 2, "los_angeles": 2}
# Approximate flight times between each pair of covered cities.
FLIGHT_MINUTES = {
    frozenset({"london", "paris"}): 75,
    frozenset({"london", "new_york"}): 480,
    frozenset({"london", "los_angeles"}): 660,
    frozenset({"paris", "new_york"}): 510,
    frozenset({"paris", "los_angeles"}): 690,
    frozenset({"new_york", "los_angeles"}): 360,
}
assert set(FLIGHT_MINUTES) == {frozenset({a, b}) for a in CITIES for b in CITIES if a != b}


@dataclass(frozen=True)
class Trip:
    destination: City  # always another covered city, so a diary never sends the member somewhere we can't book
    start: date
    end: date  # inclusive: the day they fly home
    purpose: str  # "work" | "leisure"


def _rng(*parts: str) -> random.Random:
    digest = hashlib.sha256("|".join(parts).encode()).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def home_city(seed: str, member_id: str) -> City:
    rng = _rng(seed, member_id, "home")
    ids = list(HOME_WEIGHTS)
    return CITIES[rng.choices(ids, weights=[HOME_WEIGHTS[i] for i in ids], k=1)[0]]


def trip_on(seed: str, member_id: str, day: date, frequent_traveller: bool = False) -> Trip | None:
    """The trip the member is on that day, if any. Trips never cross a block boundary."""
    block = day.toordinal() // BLOCK_DAYS
    rng = _rng(seed, member_id, "trip", str(block))
    if rng.random() >= (0.6 if frequent_traveller else 0.35):
        return None
    length = rng.randint(2, 5)
    start = date.fromordinal(block * BLOCK_DAYS + rng.randint(0, BLOCK_DAYS - length))
    end = start + timedelta(days=length - 1)
    if not start <= day <= end:
        return None
    home = home_city(seed, member_id)
    options = [c for c in CITIES.values() if c != home]
    destination = rng.choices(options, k=1)[0]
    purpose = "work" if rng.random() < (0.75 if frequent_traveller else 0.3) else "leisure"
    return Trip(destination, start, end, purpose)


@dataclass
class TripEvent:
    id: str
    title: str
    start_time: str | None
    end_time: str | None
    all_day: bool
    location: str
    category: str


def _hhmm(minutes: int) -> str:
    minutes = max(0, min(minutes, 23 * 60 + 59))
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def trip_events(seed: str, member_id: str, trip: Trip, day: date, clients: list[str]) -> list[TripEvent]:
    home = home_city(seed, member_id)
    dest = trip.destination
    rng = _rng(seed, member_id, "trip-day", day.isoformat())

    def event_id(kind: str) -> str:
        return str(uuid.uuid5(EVENT_NAMESPACE, f"{member_id}|{day.isoformat()}|trip|{kind}"))

    label = f"Work trip: {dest.name}" if trip.purpose == "work" else f"Trip to {dest.name}"
    events = [TripEvent(event_id("stay"), label, None, None, True, dest.name, "travel")]
    flight = FLIGHT_MINUTES[frozenset({home.id, dest.id})]

    if day == trip.start:
        start = rng.choice([7 * 60, 8 * 60, 9 * 60 + 30])
        events.append(
            TripEvent(
                event_id("out"),
                f"Flight to {dest.name}",
                _hhmm(start),
                _hhmm(start + flight),
                False,
                f"{home.airport}, {home.name}",  # where they fly from hints at their home city
                "travel",
            )
        )
    elif day == trip.end:
        # A long-haul flight home leaves in the morning; a short hop can wait until the afternoon.
        start = 9 * 60 if flight > 120 else rng.choice([15 * 60, 17 * 60])
        events.append(
            TripEvent(
                event_id("home"),
                f"Flight home to {home.name}",
                _hhmm(start),
                _hhmm(start + flight),
                False,
                f"{dest.airport}, {dest.name}",
                "travel",
            )
        )
    elif trip.purpose == "work" and day.weekday() < 5:
        start = rng.choice([9 * 60, 9 * 60 + 30, 10 * 60])
        client = rng.choice(clients)
        events.append(
            TripEvent(
                event_id("meetings"),
                f"Meetings with {client}",
                _hhmm(start),
                _hhmm(start + rng.choice([180, 240, 300])),
                False,
                f"{client} office, {dest.name}",
                "work",
            )
        )
    return events
