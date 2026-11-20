"""Neon (serverless Postgres) sleeps when idle and drops connections. The pool must cope."""

from __future__ import annotations

import asyncio

from app import config, db_postgres


class FakeConn:
    async def execute(self, *_a, **_k):
        return None


class FakePool:
    def acquire(self):
        class Ctx:
            async def __aenter__(self):
                return FakeConn()

            async def __aexit__(self, *a):
                return False

        return Ctx()


def test_pool_has_timeouts_and_recycles_idle_connections(monkeypatch):
    seen = {}

    async def fake_create_pool(dsn, **kwargs):
        seen["dsn"], seen["kwargs"] = dsn, kwargs
        return FakePool()

    monkeypatch.setattr(db_postgres.asyncpg, "create_pool", fake_create_pool)
    monkeypatch.setattr(config, "DATABASE_URL", "postgres://u:p@host.example/db")
    asyncio.run(db_postgres.init())

    k = seen["kwargs"]
    assert seen["dsn"].startswith("postgresql://"), "postgres:// must be normalised"
    assert 0 < k["timeout"] <= 60, "opening a connection must not hang forever"
    assert 0 < k["command_timeout"] <= 60, "a query must not hang forever"
    # Neon suspends after about 5 minutes idle; idle connections must be dropped sooner.
    assert 0 < k["max_inactive_connection_lifetime"] < 300
    assert k["ssl"] == config.PG_SSL
