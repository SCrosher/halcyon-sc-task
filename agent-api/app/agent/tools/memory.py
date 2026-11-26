"""Member memory tools (stored in this app's D1 database). Silent: no status messages."""

from __future__ import annotations

from typing import Any

from .base import Tool, ToolFailure, TurnContext, object_schema

CATEGORIES = [
    "dietary",
    "likes",
    "dislikes",
    "drinks",
    "budget",
    "locations",
    "people",
    "occasions",
    "routine",
    "accessibility",
    "other",
]


async def _save(args: dict[str, Any], ctx: TurnContext) -> dict[str, Any]:
    memory = await ctx.store.add_memory(ctx.member.id, args["category"], args["content"])
    return {"saved": True, "memory_id": memory.id}


async def _update(args: dict[str, Any], ctx: TurnContext) -> dict[str, Any]:
    if not await ctx.store.update_memory(ctx.member.id, args["memory_id"], args["content"], args.get("category")):
        raise ToolFailure(f"No memory {args['memory_id']} for this member.")
    return {"updated": True}


async def _delete(args: dict[str, Any], ctx: TurnContext) -> dict[str, Any]:
    if not await ctx.store.delete_memory(ctx.member.id, args["memory_id"]):
        raise ToolFailure(f"No memory {args['memory_id']} for this member.")
    return {"deleted": True}


CONTENT = {
    "type": "string",
    "minLength": 3,
    "maxLength": 300,
    "description": "One self-contained fact, written in the third person, e.g. 'Partner Alex is vegetarian.'",
}

MEMORY_TOOLS = [
    Tool(
        name="memory_save",
        description=(
            "Remember a durable fact or preference about the member for future conversations. Call it "
            "unprompted whenever you learn one: home city (category locations), dietary needs and allergies, "
            "favourite wines and drinks, cuisines and restaurants they like or dislike, the people they dine "
            "with and those people's tastes, birthdays and anniversaries, budget, usual areas and routines. "
            "Not for one-off details of the current request. Update an existing memory instead of saving a "
            "near-duplicate."
        ),
        parameters=object_schema(
            {"category": {"type": "string", "enum": CATEGORIES}, "content": CONTENT}, ["category", "content"]
        ),
        source="memory",
        activity="memory",
        handler=_save,
        user_facing=False,
    ),
    Tool(
        name="memory_update",
        description="Correct or refine an existing memory (by its id from the turn context).",
        parameters=object_schema(
            {"memory_id": {"type": "string"}, "content": CONTENT, "category": {"type": "string", "enum": CATEGORIES}},
            ["memory_id", "content"],
        ),
        source="memory",
        activity="memory",
        handler=_update,
        user_facing=False,
    ),
    Tool(
        name="memory_delete",
        description="Forget a memory that is wrong or that the member asked you to forget.",
        parameters=object_schema({"memory_id": {"type": "string"}}, ["memory_id"]),
        source="memory",
        activity="memory",
        handler=_delete,
        user_facing=False,
    ),
]
