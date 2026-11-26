"""In-memory SQLite served through the D1 REST API shape, so tests run the real SQL and D1 client.

Like D1, every parameter arrives as a string, foreign keys are enforced and a batch is a transaction.
The same file lives in agent-api/tests and mock-services/tests (checked by agent-api/tests/test_config.py).
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import httpx2

from app.db import D1Database

MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations"


class FakeD1:
    def __init__(self) -> None:
        self.conn = sqlite3.connect(":memory:", isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        for migration in sorted(MIGRATIONS.glob("*.sql")):
            self.conn.executescript(migration.read_text(encoding="utf-8"))
        self.statements: list[str] = []

    def _run(self, statement: dict[str, Any]) -> dict[str, Any]:
        self.statements.append(statement["sql"])
        cursor = self.conn.execute(statement["sql"], statement.get("params") or [])
        rows = [dict(r) for r in cursor.fetchall()]
        return {"results": rows, "meta": {"changes": max(cursor.rowcount, 0)}, "success": True}

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        try:
            if "batch" in body:
                self.conn.execute("BEGIN")
                try:
                    results = [self._run(s) for s in body["batch"]]
                except sqlite3.Error:
                    self.conn.execute("ROLLBACK")
                    raise
                self.conn.execute("COMMIT")
            else:
                results = [self._run(body)]
        except sqlite3.Error as exc:
            errors = [{"code": 7500, "message": str(exc)}]
            return httpx2.Response(400, json={"success": False, "errors": errors, "result": []})
        return httpx2.Response(200, json={"success": True, "errors": [], "result": results})

    def database(self) -> D1Database:
        return D1Database(
            "http://d1.test/client/v4", "account", "database", "token", transport=httpx2.MockTransport(self._handle)
        )
