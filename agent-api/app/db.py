"""Cloudflare D1 client (REST API).

The service runs in a Cloudflare Container, which has no Worker bindings, so it talks
to D1 through ``POST {api_url}/accounts/{account_id}/d1/database/{database_id}/query``.
Deployed, ``api_url`` is Cloudflare's API; in local development it is the local D1
server in ``dev/d1-local`` (same endpoint, backed by wrangler's local D1).
Schema changes are managed with ``wrangler d1 migrations apply`` (see ``migrations/``).

agent-api/app/db.py and mock-services/app/db.py are kept identical (each service is built as
its own container image from its own directory); agent-api/tests/test_config.py fails if they drift.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import httpx2

Params = Sequence[Any]


class D1Error(RuntimeError):
    pass


@dataclass
class QueryResult:
    rows: list[dict[str, Any]] = field(default_factory=list)
    changes: int = 0


class D1Database:
    def __init__(
        self,
        api_url: str,
        account_id: str,
        database_id: str,
        api_token: str,
        timeout: float = 15.0,
        transport: httpx2.AsyncBaseTransport | None = None,
    ):
        missing = [
            n
            for n, v in (
                ("CLOUDFLARE_ACCOUNT_ID", account_id),
                ("database_id", database_id),
                ("D1_API_TOKEN", api_token),
            )
            if not v
        ]
        if missing:
            raise ValueError(f"D1 is not configured; missing {', '.join(missing)}")
        self._url = f"{api_url.rstrip('/')}/accounts/{account_id}/d1/database/{database_id}/query"
        self._client = httpx2.AsyncClient(
            headers={"Authorization": f"Bearer {api_token}"},
            timeout=httpx2.Timeout(timeout),
            transport=transport,
        )

    @staticmethod
    def _param(value: Any) -> Any:
        # The REST API takes params as strings; column affinity restores INTEGER/REAL values.
        if value is None:
            return None
        if isinstance(value, bool):
            return "1" if value else "0"
        return str(value)

    async def _post(self, body: dict[str, Any]) -> list[QueryResult]:
        response = await self._client.post(self._url, json=body)
        try:
            payload = response.json()
        except ValueError:
            raise D1Error(f"D1 returned HTTP {response.status_code} with a non-JSON body") from None
        if response.status_code >= 400 or not payload.get("success", False):
            errors = "; ".join(e.get("message", "?") for e in payload.get("errors") or [])
            raise D1Error(f"D1 query failed (HTTP {response.status_code}): {errors or payload}")
        results = []
        for item in payload.get("result") or []:
            meta = item.get("meta") or {}
            results.append(
                QueryResult(
                    rows=list(item.get("results") or []),
                    changes=int(meta.get("changes") or 0),
                )
            )
        return results

    async def execute(self, sql: str, params: Params = ()) -> QueryResult:
        results = await self._post({"sql": sql, "params": [self._param(p) for p in params]})
        return results[-1] if results else QueryResult()

    async def batch(self, statements: Sequence[tuple[str, Params]]) -> list[QueryResult]:
        """Run several statements in one request (D1 executes a batch as a transaction)."""
        body = {"batch": [{"sql": sql, "params": [self._param(p) for p in params]} for sql, params in statements]}
        return await self._post(body)

    async def close(self) -> None:
        await self._client.aclose()
