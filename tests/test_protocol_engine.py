"""Unit tests for app.services.protocol_engine.

Direct coverage of the code to discovery pipeline without HTTP or
external services. The router level is covered by tests/test_protocol.py;
these tests pin the service classes themselves.
"""

from types import SimpleNamespace

import pytest

from app.services.protocol_engine import (
    AgentJsonGenerator,
    CodeParser,
    LlmTxtGenerator,
    OpenApiGenerator,
    ProtocolEngine,
)

SAMPLE_CODE = """
from fastapi import APIRouter
router = APIRouter()

@router.get("/api/v1/widgets", summary="List widgets", description="Get all widgets")
async def list_widgets():
    return []

@router.post("/api/v1/widgets", summary="Create widget", response_model=Widget)
async def create_widget():
    return {"id": "w1"}
"""


def test_parser_extracts_method_path_and_metadata():
    endpoints = CodeParser().parse(SAMPLE_CODE, service_name="widget-api")

    assert len(endpoints) == 2
    assert (endpoints[0].method, endpoints[0].path) == ("GET", "/api/v1/widgets")
    assert endpoints[0].summary == "List widgets"
    assert endpoints[0].description == "Get all widgets"
    assert endpoints[1].response_model == "Widget"
    assert endpoints[0].tags == ["widget-api"]


def test_parser_returns_empty_list_when_no_decorators():
    endpoints = CodeParser().parse("# empty file\nprint('hello')")

    assert endpoints == []


def test_parser_supports_put_patch_delete_and_missing_summary():
    code = (
        '@router.put("/items")\nasync def update_item(): ...\n'
        '@router.patch("/items")\nasync def patch_item(): ...\n'
        '@router.delete("/items")\nasync def delete_item(): ...\n'
    )
    endpoints = CodeParser().parse(code)

    assert [(e.method, e.path) for e in endpoints] == [
        ("PUT", "/items"),
        ("PATCH", "/items"),
        ("DELETE", "/items"),
    ]
    assert all(e.summary == "" for e in endpoints)


def test_llm_txt_lists_endpoints_and_auth_footer():
    endpoints = CodeParser().parse(SAMPLE_CODE, service_name="widget-api")
    text = LlmTxtGenerator().generate(
        service_name="widget-api",
        service_version="2.0.0",
        base_url="https://api.widgets.io",
        endpoints=endpoints,
    )

    assert "# widget-api API v2.0.0" in text
    assert "GET /api/v1/widgets" in text
    assert "POST /api/v1/widgets" in text
    assert "List widgets" in text
    assert "X-API-Key" in text


def test_openapi_spec_structure_and_shared_path_merge():
    endpoints = CodeParser().parse(SAMPLE_CODE, service_name="widget-api")
    spec = OpenApiGenerator().generate(
        service_name="widget-api",
        service_version="2.0.0",
        base_url="https://api.widgets.io",
        endpoints=endpoints,
    )

    assert spec["openapi"] == "3.1.0"
    assert spec["info"]["title"] == "widget-api"
    assert spec["servers"] == [{"url": "https://api.widgets.io"}]
    assert set(spec["paths"]["/api/v1/widgets"]) == {"get", "post"}
    assert spec["components"]["securitySchemes"]["ApiKeyAuth"]["in"] == "header"


def test_openapi_spec_carries_parameters_and_request_body():
    endpoints = CodeParser().parse(SAMPLE_CODE)
    endpoints[0].parameters = [
        {"name": "limit", "in": "query", "type": "integer", "required": False}
    ]
    endpoints[1].request_body = {"type": "object"}
    spec = OpenApiGenerator().generate(
        service_name="s",
        service_version="1",
        base_url="https://x.example",
        endpoints=endpoints,
    )

    get_op = spec["paths"]["/api/v1/widgets"]["get"]
    post_op = spec["paths"]["/api/v1/widgets"]["post"]
    assert get_op["parameters"][0]["name"] == "limit"
    assert post_op["requestBody"]["content"]["application/json"]["schema"] == {
        "type": "object"
    }


def test_agent_json_manifest_lists_capabilities():
    endpoints = CodeParser().parse(SAMPLE_CODE, service_name="agent-test")
    manifest = AgentJsonGenerator().generate(
        service_name="agent-test",
        service_version="1.0.0",
        base_url="https://api.test.com",
        endpoints=endpoints,
    )

    assert manifest["schema_version"] == "1.0"
    assert manifest["auth"] == {"type": "api_key", "header": "X-API-Key"}
    assert len(manifest["capabilities"]) == 2
    assert manifest["capabilities"][0]["method"] == "GET"
    assert manifest["documentation"]["llm_txt"] == "https://api.test.com/llm.txt"


@pytest.mark.anyio
async def test_engine_full_pipeline_stores_and_retrieves_result():
    engine = ProtocolEngine()
    result = await engine.generate(
        source_code=SAMPLE_CODE,
        service_name="widget-api",
        service_version="2.0.0",
        base_url="https://api.widgets.io",
        owner_wallet_id="wallet-1",
    )

    assert result.generation_id.startswith("gen-")
    assert result.endpoints_parsed == 2
    assert "widget-api" in result.llm_txt
    assert result.openapi_spec["openapi"] == "3.1.0"
    assert result.agent_json["name"] == "widget-api"
    assert result.oracle_registration_id is None
    assert result.owner_wallet_id == "wallet-1"
    assert result.warnings == []

    assert await engine.get_generation(result.generation_id) is result
    assert [g.generation_id for g in await engine.list_generations()] == [
        result.generation_id
    ]


@pytest.mark.anyio
async def test_engine_empty_source_warns_but_still_produces_package():
    engine = ProtocolEngine()
    result = await engine.generate(
        source_code="# empty file\nprint('hello')",
        service_name="empty-api",
    )

    assert result.endpoints_parsed == 0
    assert len(result.warnings) == 1
    assert "No endpoints detected" in result.warnings[0]
    assert result.openapi_spec["paths"] == {}
    assert result.agent_json["capabilities"] == []


@pytest.mark.anyio
async def test_engine_oracle_success_sets_registration_id():
    engine = ProtocolEngine()
    oracle = SimpleNamespace(crawl=_fake_crawl(returning="api-123"))
    result = await engine.generate(
        source_code=SAMPLE_CODE,
        service_name="widget-api",
        register_in_oracle=True,
        oracle_instance=oracle,
    )

    assert result.oracle_registration_id == "api-123"
    assert result.warnings == []


@pytest.mark.anyio
async def test_engine_oracle_miss_warns_and_leaves_id_empty():
    engine = ProtocolEngine()
    oracle = SimpleNamespace(crawl=_fake_crawl(returning=None))
    result = await engine.generate(
        source_code=SAMPLE_CODE,
        service_name="widget-api",
        register_in_oracle=True,
        oracle_instance=oracle,
    )

    assert result.oracle_registration_id is None
    assert any("Oracle registration failed" in w for w in result.warnings)


@pytest.mark.anyio
async def test_engine_oracle_error_warns_instead_of_raising():
    async def boom(_url):
        raise RuntimeError("index down")

    engine = ProtocolEngine()
    oracle = SimpleNamespace(crawl=boom)
    result = await engine.generate(
        source_code=SAMPLE_CODE,
        service_name="widget-api",
        register_in_oracle=True,
        oracle_instance=oracle,
    )

    assert result.oracle_registration_id is None
    assert any("index down" in w for w in result.warnings)


@pytest.mark.anyio
async def test_engine_get_unknown_generation_returns_none():
    assert await ProtocolEngine().get_generation("gen-does-not-exist") is None


def _fake_crawl(returning):
    async def crawl(_url):
        if returning is None:
            return None
        return SimpleNamespace(api_id=returning)

    return crawl
