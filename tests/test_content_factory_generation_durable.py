"""Contract: Content Factory text generation (LLM + durable row)."""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.config import get_settings
from app.db.database import get_session_factory
from app.db.models import ContentFactoryGenerationModel
from app.main import app

HEADERS = {"X-API-Key": "test-key"}


@pytest.fixture(autouse=True)
def _restore_content_factory_sim():
    settings = get_settings()
    saved_sim = settings.SIMULATION_MODE_CONTENT_FACTORY
    saved_key = settings.LLM_API_KEY
    yield
    settings.SIMULATION_MODE_CONTENT_FACTORY = saved_sim
    settings.LLM_API_KEY = saved_key


@pytest.mark.anyio
async def test_real_mode_persists_and_get_returns_row(monkeypatch):
    settings = get_settings()
    settings.SIMULATION_MODE_CONTENT_FACTORY = False
    settings.LLM_API_KEY = "sk-test"

    async def fake_llm(prompt: str, model: str | None = None):
        _ = prompt, model
        return "Generated output text", "gpt-test", "req-abc"

    monkeypatch.setattr(
        "app.services.content_factory_generation.openai_compatible_chat_completion",
        fake_llm,
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/v1/content/generate",
            json={"prompt": "Tell me a joke"},
            headers=HEADERS,
        )
    assert r.status_code == 202
    body = r.json()
    assert body["text"] == "Generated output text"
    assert body["model"] == "gpt-test"
    assert body["prompt_hash"] is not None
    assert body["output_hash"] is not None
    assert body["provenance"]["request_id"] == "req-abc"
    cid = body["content_id"]

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        g = await client.get(f"/v1/content/{cid}", headers=HEADERS)
    assert g.status_code == 200
    got = g.json()
    assert got["output_hash"] == body["output_hash"]
    assert got["text"] == "Generated output text"

    factory = get_session_factory()
    async with factory() as session:
        row = (
            await session.execute(
                select(ContentFactoryGenerationModel).where(
                    ContentFactoryGenerationModel.content_id == cid
                )
            )
        ).scalar_one_or_none()
    assert row is not None
    assert row.output_text == "Generated output text"


@pytest.mark.anyio
async def test_simulation_mode_no_db_row():
    settings = get_settings()
    settings.SIMULATION_MODE_CONTENT_FACTORY = True
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/v1/content/generate",
            json={"prompt": "short prompt"},
            headers=HEADERS,
        )
    assert r.status_code == 202
    body = r.json()
    assert body["prompt_hash"] is None
    assert body["output_hash"] is None
    assert body["provenance"] is None
    assert "[simulated]" in body["text"]
    cid = body["content_id"]

    factory = get_session_factory()
    async with factory() as session:
        row = (
            await session.execute(
                select(ContentFactoryGenerationModel).where(
                    ContentFactoryGenerationModel.content_id == cid
                )
            )
        ).scalar_one_or_none()
    assert row is None


@pytest.mark.anyio
async def test_get_unknown_returns_404():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get(
            f"/v1/content/{uuid.uuid4()}",
            headers=HEADERS,
        )
    assert r.status_code == 404
