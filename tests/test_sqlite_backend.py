"""
Tests for SQLite backend in durable state store.
"""

import os
import tempfile

import pytest

from app.core.durable_state import DurableStateStore
from app.core.config import get_settings


@pytest.fixture(autouse=True)
def reset_settings():
    """Reset settings cache before each test."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def sqlite_store():
    """Create a SQLite-based DurableStateStore for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    os.environ["SQLITE_URL"] = db_path
    os.environ["STATE_BACKEND"] = "sqlite"
    os.environ["DATABASE_URL"] = ""
    os.environ["REDIS_URL"] = ""

    store = DurableStateStore()
    yield store

    import asyncio

    asyncio.get_event_loop().run_until_complete(store.close())

    try:
        os.unlink(db_path)
    except FileNotFoundError:
        pass


@pytest.mark.asyncio
async def test_sqlite_backend_save_and_load(sqlite_store):
    """Test saving and loading JSON data with SQLite backend."""
    await sqlite_store._ensure_ready()
    assert sqlite_store.backend == "sqlite"

    test_data = {"key": "value", "number": 42, "nested": {"a": 1, "b": 2}}
    await sqlite_store.save_json("test_key", test_data)

    loaded = await sqlite_store.load_json("test_key")
    assert loaded == test_data


@pytest.mark.asyncio
async def test_sqlite_backend_delete(sqlite_store):
    """Test deleting a key from SQLite backend."""
    await sqlite_store._ensure_ready()

    await sqlite_store.save_json("delete_test", {"data": "test"})
    loaded = await sqlite_store.load_json("delete_test")
    assert loaded is not None

    await sqlite_store.delete("delete_test")
    loaded = await sqlite_store.load_json("delete_test")
    assert loaded is None


@pytest.mark.asyncio
async def test_sqlite_backend_health(sqlite_store):
    """Test SQLite backend health report."""
    await sqlite_store._ensure_ready()

    health = await sqlite_store.health_report()
    assert health["ok"] is True
    assert health["backend"] == "sqlite"
    assert health["enabled"] is True


@pytest.mark.asyncio
async def test_sqlite_backend_overwrite(sqlite_store):
    """Test overwriting existing key in SQLite backend."""
    await sqlite_store._ensure_ready()

    await sqlite_store.save_json("overwrite_key", {"version": 1})
    await sqlite_store.save_json("overwrite_key", {"version": 2})

    loaded = await sqlite_store.load_json("overwrite_key")
    assert loaded == {"version": 2}


@pytest.mark.asyncio
async def test_sqlite_backend_multiple_keys(sqlite_store):
    """Test storing multiple keys in SQLite backend."""
    await sqlite_store._ensure_ready()

    data = {
        "key1": {"data": "value1"},
        "key2": {"data": "value2"},
        "key3": {"data": "value3"},
    }

    for k, v in data.items():
        await sqlite_store.save_json(k, v)

    for k, v in data.items():
        loaded = await sqlite_store.load_json(k)
        assert loaded == v
