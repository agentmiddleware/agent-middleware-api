import pytest

from app.services.audit_log import list_audit_events, record_audit_event


@pytest.mark.anyio
async def test_record_and_list_audit_events(clean_database):
    event = await record_audit_event(
        event="mcp.invoke",
        wallet_id="wallet-1",
        tool="echo",
        endpoint="/mcp/messages",
        auth_source="db",
        key_id="key-1",
        policy_decision_id="pol-1",
        request_id="req-1",
        ok=True,
        metadata={"cost": 2.0},
    )

    events = await list_audit_events(wallet_id="wallet-1")

    assert event.event_id.startswith("audit-")
    assert len(events) == 1
    assert events[0].event == "mcp.invoke"
    assert events[0].wallet_id == "wallet-1"
    assert events[0].tool == "echo"
    assert events[0].policy_decision_id == "pol-1"
    assert events[0].metadata["cost"] == 2.0
