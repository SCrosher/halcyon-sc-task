from collections import Counter
from datetime import date, timedelta

from app.calendar.generator import choose_traits, generate_range
from app.calendar.geography import BLOCK_DAYS, home_city, trip_on
from app.calendar.rules import load_rules
from app.cities import CITIES

START = date(2026, 11, 23)
DAYS = 120


def test_every_member_has_a_covered_home_city_and_all_four_are_used():
    rules = load_rules()
    homes = Counter(home_city(rules.seed, f"member-{i}").id for i in range(400))
    assert set(homes) == set(CITIES)
    assert home_city(rules.seed, "member-1") == home_city(rules.seed, "member-1")


def test_trips_are_contiguous_and_never_go_home():
    rules = load_rules()
    for i in range(60):
        member = f"member-{i}"
        home = home_city(rules.seed, member).name
        for offset in range(DAYS):
            day = START + timedelta(days=offset)
            trip = trip_on(rules.seed, member, day)
            if trip is None:
                continue
            assert trip.destination.name != home
            assert trip.start <= day <= trip.end
            assert 1 <= (trip.end - trip.start).days <= 4
            assert trip.start.toordinal() // BLOCK_DAYS == trip.end.toordinal() // BLOCK_DAYS
            # Every day of the trip agrees on the same trip.
            for d in range((trip.end - trip.start).days + 1):
                assert trip_on(rules.seed, member, trip.start + timedelta(days=d)) == trip


def test_trips_reach_covered_and_uncovered_cities():
    rules = load_rules()
    covered, uncovered = set(), set()
    for i in range(80):
        for offset in range(0, DAYS):
            trip = trip_on(rules.seed, f"member-{i}", START + timedelta(days=offset))
            if trip:
                (covered if trip.destination.covered else uncovered).add(trip.destination.name)
    assert covered == {c.name for c in CITIES.values()}
    assert len(uncovered) >= 5


def test_trip_days_show_where_the_member_is():
    rules = load_rules()
    for i in range(30):
        member = f"member-{i}"
        traits = choose_traits(rules, member)
        events = generate_range(rules, member, traits, START, START + timedelta(days=DAYS))
        by_day: dict[str, list] = {}
        for e in events:
            by_day.setdefault(e.date, []).append(e)
        for offset in range(DAYS):
            day = START + timedelta(days=offset)
            trip = trip_on(rules.seed, member, day, any(t.id == "frequent_traveller" for t in traits))
            todays = by_day.get(day.isoformat(), [])
            stays = [e for e in todays if e.all_day and e.category == "travel"]
            if trip is None:
                assert not stays and not any(e.title.startswith("Flight") for e in todays)
                continue
            assert [s.location for s in stays] == [trip.destination.name]
            # The usual routine is replaced by the trip.
            assert all(e.category in ("travel", "work") for e in todays)
            if day == trip.start:
                assert any(e.title == f"Flight to {trip.destination.name}" for e in todays)
            if day == trip.end:
                home = home_city(rules.seed, member).name
                assert any(e.title == f"Flight home to {home}" for e in todays)
