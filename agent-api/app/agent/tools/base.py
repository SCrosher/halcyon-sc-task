"""Common tool plumbing.

Every member-facing tool gets a required ``status_message`` argument: Claude writes a
short line such as "Allow me a moment to check your diary…", the runner posts it to the member
as soon as the tool call is generated, and it is stripped before the tool runs.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx2
from jsonschema import Draft202012Validator

from ...config import Settings
from ...store import Member, Store
from ..progress import Activity

STATUS_FIELD = "status_message"
STATUS_PROPERTY = {
    "type": "string",
    "maxLength": 80,
    "description": (
        "Short, courteous line sent to the member as its own chat message while this runs, "
        "e.g. 'Allow me a moment to check your diary…'. Max ~8 words, ends with '…'. "
        "Vary the wording; don't repeat an earlier one."
    ),
}

Source = Literal["memory", "calendar", "restaurants"]


class ToolFailure(Exception):
    """An anticipated failure whose message the model should read and act on."""


@dataclass
class TurnContext:
    member: Member
    store: Store
    settings: Settings
    mock_http: httpx2.AsyncClient


Handler = Callable[[dict[str, Any], TurnContext], Awaitable[Any]]


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON schema of the real arguments
    source: Source
    activity: Activity  # what the holding message talks about while it runs
    handler: Handler
    user_facing: bool = True
    _validator: Draft202012Validator | None = field(default=None, repr=False)

    def input_schema(self) -> dict[str, Any]:
        schema = copy.deepcopy(self.parameters)
        if self.user_facing:
            schema["properties"] = {STATUS_FIELD: STATUS_PROPERTY, **schema.get("properties", {})}
            schema["required"] = [STATUS_FIELD, *schema.get("required", [])]
        return schema

    def definition(self) -> dict[str, Any]:
        # Eager input streaming lets the status message arrive as soon as it is written;
        # inputs are then unvalidated by the API, so ``validate`` below is mandatory.
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema(),
            "eager_input_streaming": True,
        }

    def validate(self, arguments: Any) -> list[str]:
        if not isinstance(arguments, dict):
            return ["arguments must be a JSON object"]
        if self._validator is None:
            # format_checker makes "format" (e.g. "date") a real constraint rather than an annotation.
            self._validator = Draft202012Validator(
                self.input_schema(), format_checker=Draft202012Validator.FORMAT_CHECKER
            )
        return [
            f"{'/'.join(map(str, e.path)) or '(root)'}: {e.message}" for e in self._validator.iter_errors(arguments)
        ]

    async def run(self, arguments: dict[str, Any], ctx: TurnContext) -> str:
        real_args = {k: v for k, v in arguments.items() if k != STATUS_FIELD}
        result = await self.handler(real_args, ctx)
        return result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, separators=(",", ":"))


def object_schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}
