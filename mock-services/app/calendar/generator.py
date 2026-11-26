"""Deterministic calendar generation from the LLM-authored trait library.

Each member's traits are picked by an RNG seeded from ``rules.seed`` and the member
id, and every member/day gets its own RNG too. The same member id therefore always
produces the same calendar, with no knowledge of the member required. The service
stores what this module generates; this module itself has no side effects.
"""

from __future__ import annotations

import hashlib
import random
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import date, timedelta

from .geography import trip_events, trip_on
from .rules import CalendarRules, Pattern, Trait

EVENT_NAMESPACE = uuid.UUID("6f2a4c1e-9b7d-4e3a-8c5f-1d2e3f4a5b6c")
PLACEHOLDER = re.compile(r"\{(\w+)\}")
STEP_MIN = 15
KIND_ORDER = {"all_day": 0, "recurring": 1, "random": 2}
# The extras trait that makes trips (see geography.py) more frequent and more often for work.
FREQUENT_TRAVELLER = "frequent_traveller"


@dataclass
class Event:
    id: str
    title: str
    date: str  # YYYY-MM-DD
    start_time: str | None  # HH:MM local time; None when all-day
    end_time: str | None
    all_day: bool
    location: str | None
    category: str
    source: str  # "generated" | "member"

    def to_dict(self) -> dict:
        return asdict(self)

    def interval(self) -> tuple[int, int] | None:
        if self.all_day or not self.start_time or not self.end_time:
            return None
        return to_minutes(self.start_time), to_minutes(self.end_time)


def to_minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def from_minutes(minutes: int) -> str:
    minutes = max(0, min(minutes, 23 * 60 + 59))
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def sort_key(event: Event) -> tuple:
    return (event.date, 0 if event.all_day else 1, event.start_time or "", event.title)


def _rng(*parts: str) -> random.Random:
    digest = hashlib.sha256("|".join(parts).encode()).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def choose_traits(rules: CalendarRules, member_id: str) -> list[Trait]:
    """Weighted pick, without replacement, of ``pick=[min, max]`` traits from every group."""
    chosen: list[Trait] = []
    for group in rules.trait_groups:
        rng = _rng(rules.seed, member_id, "traits", group.id)
        pool = list(group.traits)
        for _ in range(rng.randint(*group.pick)):
            trait = rng.choices(pool, weights=[t.weight for t in pool], k=1)[0]
            pool.remove(trait)
            chosen.append(trait)
    return chosen


def _fill(template: str, vocab: dict[str, list[str]], rng: random.Random) -> str:
    return PLACEHOLDER.sub(lambda m: rng.choice(vocab[m.group(1)]), template)


def _overlaps(candidate: tuple[int, int], taken: list[tuple[int, int]], gap: int) -> bool:
    start, end = candidate
    return any(start < t_end + gap and t_start < end + gap for t_start, t_end in taken)


def _applies(pattern: Pattern, day: date) -> bool:
    if day.weekday() not in pattern.days:
        return False
    if pattern.week_parity == "any":
        return True
    return (day.isocalendar().week % 2 == 1) == (pattern.week_parity == "odd")


def _place(pattern: Pattern, rng: random.Random, taken: list[tuple[int, int]], rules: CalendarRules):
    duration = rng.choice(pattern.durations_min)
    gap = rules.rules.min_gap_min
    if pattern.kind == "recurring":
        start = to_minutes(pattern.start)
        candidate = (start, min(start + duration, 24 * 60 - 1))
        return None if _overlaps(candidate, taken, gap) else candidate
    earliest = to_minutes(pattern.window_start)
    latest_start = to_minutes(pattern.window_end) - duration
    if latest_start < earliest:
        return None
    steps = (latest_start - earliest) // STEP_MIN
    for _ in range(rules.rules.placement_attempts):
        start = earliest + rng.randint(0, steps) * STEP_MIN
        if not _overlaps((start, start + duration), taken, gap):
            return start, start + duration
    return None


def generate_day(rules: CalendarRules, member_id: str, traits: list[Trait], day: date) -> list[Event]:
    vocab = rules.vocab_map()
    day_str = day.isoformat()

    # Away from home, the trip replaces the usual routine.
    trip = trip_on(rules.seed, member_id, day, any(t.id == FREQUENT_TRAVELLER for t in traits))
    if trip is not None:
        return sorted(
            (
                Event(e.id, e.title, day_str, e.start_time, e.end_time, e.all_day, e.location, e.category, "generated")
                for e in trip_events(rules.seed, member_id, trip, day, vocab.get("client", ["a client"]))
            ),
            key=sort_key,
        )
    events: list[Event] = []
    taken: list[tuple[int, int]] = []

    # Fixed commitments first so flexible ones fit around them.
    patterns = sorted(
        ((trait, pattern) for trait in traits for pattern in trait.patterns),
        key=lambda tp: KIND_ORDER[tp[1].kind],
    )
    for trait, pattern in patterns:
        if not _applies(pattern, day):
            continue
        rng = _rng(rules.seed, member_id, day_str, trait.id, pattern.id)
        if rng.random() >= pattern.probability:
            continue
        occurrences = rng.randint(*pattern.count) if pattern.kind == "random" else 1
        titles = list(pattern.titles)
        rng.shuffle(titles)  # repeated occurrences on one day get different titles where possible

        for n in range(occurrences):
            if len(events) >= rules.rules.max_events_per_day:
                break
            title = _fill(titles[n % len(titles)], vocab, rng)
            location = _fill(rng.choice(pattern.locations), vocab, rng) if pattern.locations else None
            event_id = str(uuid.uuid5(EVENT_NAMESPACE, f"{member_id}|{day_str}|{trait.id}|{pattern.id}|{n}"))

            if pattern.kind == "all_day":
                events.append(
                    Event(event_id, title, day_str, None, None, True, location, pattern.category, "generated")
                )
                continue
            slot = _place(pattern, rng, taken, rules)
            if slot is None:
                continue
            taken.append(slot)
            events.append(
                Event(
                    event_id,
                    title,
                    day_str,
                    from_minutes(slot[0]),
                    from_minutes(slot[1]),
                    False,
                    location,
                    pattern.category,
                    "generated",
                )
            )
    return sorted(events, key=sort_key)


def generate_range(rules: CalendarRules, member_id: str, traits: list[Trait], start: date, end: date) -> list[Event]:
    events: list[Event] = []
    day = start
    while day <= end:
        events.extend(generate_day(rules, member_id, traits, day))
        day += timedelta(days=1)
    return events
