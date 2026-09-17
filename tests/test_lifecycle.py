import asyncio
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from backend.app import db, main


def test_close_connection_resets_singleton(sandbox):
    async def exercise():
        conn = await db.get_connection()
        try:
            await db.close_connection()
            assert db._conn is None
            with pytest.raises(ValueError):
                await conn.execute("SELECT 1")
            await db.close_connection()
            replacement = await db.get_connection()
            assert replacement is not conn
            async with replacement.execute("SELECT 1") as cursor:
                assert tuple(await cursor.fetchone()) == (1,)
        finally:
            if db._conn is not None:
                await db._conn.close()
                db._conn = None

    asyncio.run(exercise())


def test_repeated_client_lifespans(sandbox):
    connections = []
    try:
        for _ in range(2):
            with TestClient(main.app) as client:
                connections.append(main.app.state.conn)
                assert client.get("/api/stats/summary").status_code == 200
        assert connections[0] is not connections[1]
        assert db._conn is None
    finally:
        if db._conn is not None:
            asyncio.run(db._conn.close())
            db._conn = None


@pytest.mark.parametrize("stage", ["init_schema", "sync_directory"])
def test_startup_failure_cleanup_and_recovery(sandbox, monkeypatch, stage):
    original = getattr(main, stage)
    failure = AsyncMock(side_effect=RuntimeError("startup failed"))
    monkeypatch.setattr(main, stage, failure)
    try:
        with pytest.raises(RuntimeError, match="startup failed"):
            with TestClient(main.app):
                pytest.fail("startup should fail")
        failed_conn = main.app.state.conn
        assert db._conn is None

        async def check_closed():
            with pytest.raises(ValueError):
                await failed_conn.execute("SELECT 1")

        asyncio.run(check_closed())
        monkeypatch.setattr(main, stage, original)
        with TestClient(main.app) as client:
            assert main.app.state.conn is not failed_conn
            assert client.get("/api/stats/summary").status_code == 200
        assert db._conn is None
    finally:
        if db._conn is not None:
            asyncio.run(db._conn.close())
            db._conn = None


def test_lifespan_body_failure_cleanup(sandbox):
    async def exercise():
        try:
            with pytest.raises(RuntimeError, match="body failed"):
                async with main.lifespan(main.app):
                    conn = main.app.state.conn
                    raise RuntimeError("body failed")
            assert db._conn is None
            with pytest.raises(ValueError):
                await conn.execute("SELECT 1")
            async with main.lifespan(main.app):
                assert main.app.state.conn is not conn
            assert db._conn is None
        finally:
            if db._conn is not None:
                await db._conn.close()
                db._conn = None

    asyncio.run(exercise())


@pytest.mark.parametrize("pragma", ["PRAGMA foreign_keys = ON", "PRAGMA journal_mode = WAL"])
def test_pragma_failure_cleanup_and_recovery(sandbox, monkeypatch, pragma):
    original = db.aiosqlite.Connection.execute
    connections = []

    async def fail_pragma(conn, sql, *args, **kwargs):
        if sql == pragma:
            connections.append(conn)
            raise RuntimeError("pragma failed")
        return await original(conn, sql, *args, **kwargs)

    async def exercise():
        try:
            with monkeypatch.context() as patch:
                patch.setattr(db.aiosqlite.Connection, "execute", fail_pragma)
                with pytest.raises(RuntimeError, match="pragma failed"):
                    await db.get_connection()
            assert db._conn is None
            with pytest.raises(ValueError):
                await connections[0].execute("SELECT 1")
            replacement = await db.get_connection()
            assert replacement is not connections[0]
            async with replacement.execute("PRAGMA foreign_keys") as cursor:
                assert tuple(await cursor.fetchone()) == (1,)
            async with replacement.execute("PRAGMA journal_mode") as cursor:
                assert tuple(await cursor.fetchone()) == ("wal",)
        finally:
            if db._conn is not None:
                await db._conn.close()
                db._conn = None

    asyncio.run(exercise())
