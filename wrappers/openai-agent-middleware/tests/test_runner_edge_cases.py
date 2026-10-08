"""Edge cases in the OpenAI runner not covered by test_governed_flow.py.

Name mapping boundaries, argument shapes, and key-store corruption: the paths
an unusual model output or a damaged state file takes before any money moves.
"""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from openai_b2a import (
    B2AClient,
    GovernedToolRunner,
    JsonFileOperationKeyStore,
    normalize_tool_call,
)
from openai_b2a.runner import function_name_for

TOOL = "partner.notes.write"
WALLET = "wallet-1"


def test_function_name_mapping_replaces_dots_and_truncates_to_64():
    assert function_name_for(TOOL) == "partner_notes_write"
    long_name = "a" * 70
    mapped = function_name_for(long_name)
    assert len(mapped) == 64
    assert mapped == "a" * 64


def test_function_name_mapping_preserves_allowed_characters():
    assert function_name_for("tool-1_X") == "tool-1_X"


def test_normalize_accepts_mapping_arguments_directly():
    call = normalize_tool_call(
        SimpleNamespace(
            id="call_1",
            function=SimpleNamespace(name="f", arguments={"text": "hi", "n": 2}),
        )
    )
    assert call.arguments == {"text": "hi", "n": 2}


@pytest.mark.parametrize("arguments", [5, 3.5, ["a"], ("a",), True])
def test_normalize_rejects_non_object_argument_shapes(arguments):
    with pytest.raises(TypeError):
        normalize_tool_call({"id": "call_1", "function": {"name": "f", "arguments": arguments}})


def test_normalize_rejects_missing_function_name():
    with pytest.raises(ValueError, match="no function name"):
        normalize_tool_call({"id": "call_1", "function": {"arguments": "{}"}})


async def test_run_all_with_no_tool_calls_sends_nothing():
    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(404)

    client = B2AClient(
        api_key="test-key",
        base_url="http://trust.test",
        transport=httpx.MockTransport(handler),
    )
    runner = GovernedToolRunner(client, wallet_id=WALLET, run_id="run-1")
    assert await runner.run_all([]) == []
    assert sent == []
    await client.close()


def test_key_store_with_non_object_sections_fails_loudly(tmp_path):
    store_path = tmp_path / "operations.json"
    store_path.write_text('{"operations": [], "permits": {}}')
    store = JsonFileOperationKeyStore(store_path)
    with pytest.raises(TypeError, match="JSON object"):
        store.get_operation("call_1")


def test_key_store_with_non_object_file_fails_loudly(tmp_path):
    store_path = tmp_path / "operations.json"
    store_path.write_text("[1, 2]")
    store = JsonFileOperationKeyStore(store_path)
    with pytest.raises(TypeError, match="JSON object"):
        store.get_permit("key-1")
