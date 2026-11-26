from datetime import UTC, datetime

from app.agent.prompts import GETTING_TO_KNOW, SYSTEM_PROMPT, turn_context
from app.agent.tools.memory import CATEGORIES
from app.store import Member, Memory

JANE = Member("m1", "Jane Doe")
NOW = datetime(2026, 11, 26, 23, 30, tzinfo=UTC)  # already Friday in Paris, still Thursday in LA


def memory(category: str, content: str) -> Memory:
    return Memory(f"id-{category}", JANE.id, category, content, "t", "t")


def test_turn_context_shows_each_city_clock():
    context = turn_context(JANE, [], NOW)
    assert "London Thu 26 Nov 23:30" in context
    assert "Paris Fri 27 Nov 00:30" in context
    assert "New York Thu 26 Nov 18:30" in context
    assert "Los Angeles Thu 26 Nov 15:30" in context


def test_turn_context_lists_only_unknown_topics():
    everything = turn_context(JANE, [], NOW)
    assert "Not yet known" in everything
    assert all(topic in everything for topic in GETTING_TO_KNOW.values())

    some = turn_context(JANE, [memory("locations", "Lives in Paris."), memory("drinks", "Loves Chablis.")], NOW)
    assert "home city" not in some and "favourite wines" not in some
    assert "dietary needs" in some
    assert "[id-locations] (locations) Lives in Paris." in some

    known = [memory(category, "x") for category in GETTING_TO_KNOW]
    assert "Not yet known" not in turn_context(JANE, known, NOW)


def test_getting_to_know_topics_map_to_real_memory_categories():
    assert set(GETTING_TO_KNOW) <= set(CATEGORIES)


def test_system_prompt_names_every_covered_city():
    for city in ("London", "Paris", "New York", "Los Angeles"):
        assert city in SYSTEM_PROMPT
