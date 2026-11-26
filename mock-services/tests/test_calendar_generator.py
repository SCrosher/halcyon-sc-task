from datetime import date, timedelta

from app.calendar.generator import choose_traits, generate_day, generate_range
from app.calendar.rules import load_rules

MEMBERS = [
    "7c1e4b2a-5f3d-4e8c-a9b6-2d1f0e7c3b45",
    "00000000-0000-0000-0000-000000000001",
    "11111111-2222-3333-4444-555555555555",
    "member-abc",
    "member-xyz",
]
START = date(2026, 11, 23)


def test_rules_file_is_valid():
    rules = load_rules()
    assert [g.id for g in rules.trait_groups] == ["work", "household", "fitness", "social", "extras"]


def test_trait_pick_respects_groups():
    rules = load_rules()
    group_of = {t.id: g for g in rules.trait_groups for t in g.traits}
    for i in range(200):
        traits = choose_traits(rules, f"member-{i}")
        assert len({t.id for t in traits}) == len(traits), "no trait picked twice"
        for group in rules.trait_groups:
            picked = sum(1 for t in traits if group_of[t.id] is group)
            assert group.pick[0] <= picked <= group.pick[1]


def test_trait_mixes_vary_across_members():
    rules = load_rules()
    mixes = {tuple(t.id for t in choose_traits(rules, f"member-{i}")) for i in range(100)}
    assert len(mixes) > 50


def test_generation_is_deterministic():
    rules = load_rules()
    for member in MEMBERS:
        traits = choose_traits(rules, member)
        assert [t.id for t in choose_traits(rules, member)] == [t.id for t in traits]
        first = [e.to_dict() for e in generate_range(rules, member, traits, START, START + timedelta(days=13))]
        second = [e.to_dict() for e in generate_range(rules, member, traits, START, START + timedelta(days=13))]
        assert first == second
        assert first, "a fortnight should never be empty"


def test_timed_events_never_overlap_and_fit_the_day():
    rules = load_rules()
    for i in range(40):
        member = f"member-{i}"
        traits = choose_traits(rules, member)
        for offset in range(60):
            events = generate_day(rules, member, traits, START + timedelta(days=offset))
            assert len(events) <= rules.rules.max_events_per_day
            intervals = sorted(e.interval() for e in events if e.interval())
            for (_, end_1), (start_2, _) in zip(intervals, intervals[1:], strict=False):
                assert end_1 <= start_2
            for start, end in intervals:
                assert 0 <= start < end < 24 * 60


def test_event_ids_are_unique_and_placeholders_filled():
    rules = load_rules()
    for member in MEMBERS:
        traits = choose_traits(rules, member)
        events = generate_range(rules, member, traits, START, START + timedelta(days=90))
        assert len({e.id for e in events}) == len(events)
        for event in events:
            assert "{" not in event.title
            assert event.location is None or "{" not in event.location
