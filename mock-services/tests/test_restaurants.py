import asyncio
from datetime import timedelta

import pytest

from app.cities import CITIES
from app.restaurants.service import TABLES_NEEDED_SQL, BookingError, load_restaurants, tables_needed

from .conftest import TODAY

THURSDAY = TODAY + timedelta(days=7)
MONDAY = TODAY + timedelta(days=4)


def test_search_filters(restaurants):
    italian = restaurants.search(cuisine="italian")
    assert italian and all("Italian" in r["cuisine"] for r in italian)

    vegan_soho = restaurants.search(area="soho", dietary=["vegan"])
    assert [r["id"] for r in vegan_soho] == ["osteria-lumen"]

    assert all(r["price_level"] >= 3 for r in restaurants.search(min_price_level=3))
    assert all(r["max_party_size"] >= 10 for r in restaurants.search(party_size=10))


def test_every_city_has_a_full_directory():
    rows = load_restaurants()
    assert {r["city"] for r in rows} == set(CITIES)
    for city in CITIES:
        in_city = [r for r in rows if r["city"] == city]
        assert len(in_city) >= 10
        assert len({r["cuisine"] for r in in_city}) >= 8, "each city needs a varied mix"
        assert {1, 2, 3, 4} >= {r["price_level"] for r in in_city} >= {2, 3, 4}


def test_search_is_limited_to_one_city(restaurants):
    for city in CITIES:
        results = restaurants.search(city=city)
        assert results and all(r["city"] == city for r in results)
    assert restaurants.search(city="london", area="soho") == restaurants.search(area="soho")


def test_prices_are_in_local_currency(restaurants):
    expected = {"london": "£", "paris": "€", "new_york": "$", "los_angeles": "$"}
    for city, symbol in expected.items():
        for r in restaurants.search(city=city):
            summary = restaurants.summary(r)
            assert summary["price"] == symbol * r["price_level"]
            assert summary["avg_spend_per_head"] == f"{symbol}{r['avg_spend']}"


def test_tags_rank_results(restaurants):
    results = restaurants.search(tags=["romantic", "special_occasion", "quiet"])
    top_tags = set(results[0]["tags"])
    assert {"romantic", "special_occasion", "quiet"} <= top_tags


async def test_availability_is_deterministic(restaurants):
    a = await restaurants.availability("osteria-lumen", THURSDAY, 2, "19:30")
    b = await restaurants.availability("osteria-lumen", THURSDAY, 2, "19:30")
    assert a == b
    assert a["available_times"], "a popular-but-large venue should have something near 19:30 on a Thursday"


async def test_closed_day_and_limits(restaurants):
    closed = await restaurants.availability("the-gilded-larch", MONDAY, 2)
    assert closed["available_times"] == [] and "closed" in closed["note"]

    too_big = await restaurants.availability("kaito-omakase", THURSDAY, 6)
    assert too_big["available_times"] == [] and "up to 4" in too_big["note"]

    with pytest.raises(BookingError, match="past"):
        await restaurants.availability("osteria-lumen", TODAY - timedelta(days=1), 2)


async def test_booking_consumes_capacity(restaurants):
    restaurant_id, party = "verdant", 2  # small, moderately popular venue
    slots = await restaurants.slots(restaurant_id, THURSDAY, party)
    assert slots
    slot = slots[0]
    for _ in range(slot.tables_left):
        await restaurants.create_booking(
            restaurant_id=restaurant_id,
            day=THURSDAY,
            time=slot.time,
            party_size=party,
            member_id="m1",
            member_name="Jane Doe",
        )
    after = {s.time for s in await restaurants.slots(restaurant_id, THURSDAY, party)}
    assert slot.time not in after
    with pytest.raises(BookingError, match="no table"):
        await restaurants.create_booking(
            restaurant_id=restaurant_id,
            day=THURSDAY,
            time=slot.time,
            party_size=party,
            member_id="m1",
            member_name="Jane Doe",
        )
    bookings = await restaurants.list_bookings("m1")
    assert len(bookings) == slot.tables_left
    assert bookings[0]["reference"].startswith("HC-")


async def test_concurrent_bookings_never_overbook(restaurants):
    restaurant_id, party = "verdant", 2
    slot = (await restaurants.slots(restaurant_id, THURSDAY, party))[0]

    async def book():
        try:
            await restaurants.create_booking(
                restaurant_id=restaurant_id,
                day=THURSDAY,
                time=slot.time,
                party_size=party,
                member_id="m1",
                member_name="Jane Doe",
            )
            return True
        except BookingError:
            return False

    outcomes = await asyncio.gather(*(book() for _ in range(slot.tables_left + 3)))
    assert sum(outcomes) == slot.tables_left


async def test_tables_needed_sql_matches_python(d1):
    fake, _ = d1
    # An INTEGER column, as in bookings: D1 sends the value as a string and affinity converts it.
    fake.conn.execute("CREATE TEMP TABLE parties (party_size INTEGER)")
    fake.conn.executemany("INSERT INTO parties VALUES (?)", [(str(p),) for p in range(1, 21)])
    rows = fake.conn.execute(f"SELECT party_size, {TABLES_NEEDED_SQL} AS n FROM parties").fetchall()
    assert {r["party_size"]: r["n"] for r in rows} == {p: tables_needed(p) for p in range(1, 21)}


async def test_cancel_booking(restaurants):
    slot = (await restaurants.slots("verdant", THURSDAY, 2))[0]
    booking = await restaurants.create_booking(
        restaurant_id="verdant", day=THURSDAY, time=slot.time, party_size=2, member_id="m1", member_name="Jane Doe"
    )
    with pytest.raises(BookingError, match="not found"):
        await restaurants.cancel_booking(booking["reference"], "someone-else")
    cancelled = await restaurants.cancel_booking(booking["reference"], "m1")
    assert cancelled["status"] == "cancelled"
    assert slot.time in {s.time for s in await restaurants.slots("verdant", THURSDAY, 2)}


async def _book(restaurants, time, party=2, member="m1"):
    return await restaurants.create_booking(
        restaurant_id="verdant", day=THURSDAY, time=time, party_size=party, member_id=member, member_name="Jane Doe"
    )


async def test_modify_booking_moves_it_and_frees_the_old_slot(restaurants):
    slots = await restaurants.slots("verdant", THURSDAY, 2)
    first, second = slots[0], slots[-1]
    booking = await _book(restaurants, first.time)

    with pytest.raises(BookingError, match="not found"):
        await restaurants.modify_booking(booking["reference"], "someone-else", time=second.time)

    moved = await restaurants.modify_booking(
        booking["reference"], "m1", time=second.time, party_size=3, special_requests="Window table"
    )
    assert (moved["reference"], moved["time"], moved["party_size"]) == (booking["reference"], second.time, 3)
    assert moved["special_requests"] == "Window table"
    assert moved["previous"] == {"date": THURSDAY.isoformat(), "time": first.time, "party_size": 2}
    left = {s.time: s.tables_left for s in await restaurants.slots("verdant", THURSDAY, 2)}
    assert left[first.time] == first.tables_left
    assert left.get(second.time, 0) == second.tables_left - 1

    # Fields not passed are kept.
    again = await restaurants.modify_booking(booking["booking_id"], "m1", occasion="birthday")
    assert (again["time"], again["special_requests"], again["occasion"]) == (second.time, "Window table", "birthday")


async def test_modify_booking_into_a_full_slot_leaves_it_unchanged(restaurants):
    slots = await restaurants.slots("verdant", THURSDAY, 2)
    mine, full = slots[0], slots[1]
    booking = await _book(restaurants, mine.time)
    for _ in range(full.tables_left):
        await _book(restaurants, full.time, member="m2")

    with pytest.raises(BookingError, match="unchanged"):
        await restaurants.modify_booking(booking["reference"], "m1", time=full.time)
    with pytest.raises(BookingError, match="unchanged"):
        await restaurants.modify_booking(booking["reference"], "m1", time="03:00")
    [kept] = await restaurants.list_bookings("m1")
    assert (kept["time"], kept["status"]) == (mine.time, "confirmed")
    # Changing only the requests never needs a new table.
    assert (await restaurants.modify_booking(booking["reference"], "m1", special_requests="Quiet"))["time"] == mine.time


async def test_cancelled_and_past_bookings_cannot_be_changed(restaurants, d1):
    fake, _ = d1
    slot = (await restaurants.slots("verdant", THURSDAY, 2))[0]
    cancelled = await _book(restaurants, slot.time)
    await restaurants.cancel_booking(cancelled["reference"], "m1")
    with pytest.raises(BookingError, match="cancelled"):
        await restaurants.modify_booking(cancelled["reference"], "m1", party_size=3)

    past = await _book(restaurants, slot.time)
    last_week = (TODAY - timedelta(days=3)).isoformat()
    fake.conn.execute("UPDATE bookings SET date = ? WHERE id = ?", (last_week, past["booking_id"]))
    with pytest.raises(BookingError, match="in the past"):
        await restaurants.modify_booking(past["reference"], "m1", party_size=3)
    with pytest.raises(BookingError, match="in the past"):
        await restaurants.cancel_booking(past["reference"], "m1")
