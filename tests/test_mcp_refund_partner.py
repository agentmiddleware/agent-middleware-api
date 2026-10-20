"""Behavior of the non-idempotent refund partner fixture.

Runs in a subprocess because the fixture reads its configuration from the
environment at import time.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _run(tmp_path: Path, script: str) -> None:
    environment = os.environ.copy()
    environment.update(
        {
            "MCP_REFUND_PARTNER_ALLOWED_HOST": "testserver",
            "MCP_REFUND_PARTNER_BEARER_TOKEN": "refund-bearer",
            "MCP_REFUND_PARTNER_CONTROL_TOKEN": "refund-control",
            "MCP_REFUND_PARTNER_DB_PATH": str(tmp_path / "refund-partner.sqlite3"),
        }
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout


def test_default_mode_duplicates_the_effect_on_redispatch(tmp_path: Path) -> None:
    _run(
        tmp_path,
        "from tests.support import mcp_refund_partner_app as p\n"
        "assert p._honor_idempotency() is False\n"
        "for _ in range(3):\n"
        "    p._apply_refund(refund_ref='r1', amount_cents=500,\n"
        "        invocation_id='i', idempotency_key='k1', honor_idempotency=False)\n"
        "totals = p._totals()\n"
        "assert totals['effect_count'] == 3, totals\n"
        "assert totals['total_refunded_cents'] == 1500, totals\n",
    )


def test_honoring_mode_collapses_repeated_keys_to_one_effect(tmp_path: Path) -> None:
    _run(
        tmp_path,
        "from tests.support import mcp_refund_partner_app as p\n"
        "results = [p._apply_refund(refund_ref='r1', amount_cents=500,\n"
        "    invocation_id='i', idempotency_key='k1', honor_idempotency=True)\n"
        "    for _ in range(3)]\n"
        "assert [r['deduplicated'] for r in results] == [False, True, True]\n"
        "assert len({r['effect_id'] for r in results}) == 1\n"
        "totals = p._totals()\n"
        "assert totals['effect_count'] == 1, totals\n"
        "assert totals['total_refunded_cents'] == 500, totals\n"
        "assert totals['attempt_count'] == 3, totals\n"
        "assert totals['deduplicated_attempt_count'] == 2, totals\n"
        "p._apply_refund(refund_ref='r2', amount_cents=700,\n"
        "    invocation_id='i', idempotency_key='k2', honor_idempotency=True)\n"
        "assert p._totals()['effect_count'] == 2\n",
    )


def test_honoring_mode_rejects_key_reuse_with_different_arguments(
    tmp_path: Path,
) -> None:
    _run(
        tmp_path,
        "from tests.support import mcp_refund_partner_app as p\n"
        "p._apply_refund(refund_ref='r1', amount_cents=500,\n"
        "    invocation_id='i', idempotency_key='k1', honor_idempotency=True)\n"
        "try:\n"
        "    p._apply_refund(refund_ref='r1', amount_cents=900,\n"
        "        invocation_id='i', idempotency_key='k1', honor_idempotency=True)\n"
        "except ValueError as error:\n"
        "    assert 'different arguments' in str(error)\n"
        "else:\n"
        "    raise AssertionError('key reuse with new arguments was accepted')\n"
        "assert p._totals()['effect_count'] == 1\n",
    )


def test_effects_endpoint_reports_the_true_total_beyond_the_row_limit(
    tmp_path: Path,
) -> None:
    _run(
        tmp_path,
        "from starlette.testclient import TestClient\n"
        "from tests.support import mcp_refund_partner_app as p\n"
        "with p._connect() as connection:\n"
        "    connection.executemany(\n"
        '        "INSERT INTO refund_effects (refund_ref, amount_cents, '
        'invocation_id, idempotency_key, worker_pid) VALUES (?, ?, ?, ?, ?)",\n'
        "        [('big', 1, 'i', f'k{n}', 1) for n in range(1001)]\n"
        "        + [('small', 1, 'i', 'ks', 1)],\n"
        "    )\n"
        "    connection.commit()\n"
        "client = TestClient(p.app)\n"
        "headers = {p.CONTROL_HEADER: 'refund-control'}\n"
        "body = client.get('/__stress/effects', headers=headers,\n"
        "    params={'refund_ref': 'big'}).json()\n"
        "assert body['count'] == 1001, body['count']\n"
        "assert body['returned'] == 1000\n"
        "assert body['truncated'] is True\n"
        "small = client.get('/__stress/effects', headers=headers,\n"
        "    params={'refund_ref': 'small'}).json()\n"
        "assert (small['count'], small['returned'], small['truncated']) "
        "== (1, 1, False)\n",
    )


def test_default_hang_outlasts_the_default_gateway_timeout(tmp_path: Path) -> None:
    _run(
        tmp_path,
        "import inspect\n"
        "from app.core.config import Settings\n"
        "from tests.support import mcp_refund_partner_app as p\n"
        "gateway_default = Settings.model_fields["
        "'MCP_UPSTREAM_CALL_TIMEOUT_SECONDS'].default\n"
        "default = inspect.signature(p.partner_refund)"
        ".parameters['hang_seconds'].default\n"
        "assert default >= 2 * gateway_default, (default, gateway_default)\n"
        "assert p.MAX_HANG_SECONDS > default\n",
    )


def test_control_endpoints_require_the_control_token_and_switch_mode(
    tmp_path: Path,
) -> None:
    _run(
        tmp_path,
        "from starlette.testclient import TestClient\n"
        "from tests.support import mcp_refund_partner_app as p\n"
        "client = TestClient(p.app)\n"
        "denied = client.get('/__stress/health')\n"
        "assert denied.status_code == 403\n"
        "headers = {p.CONTROL_HEADER: 'refund-control'}\n"
        "assert client.get('/__stress/health', headers=headers).json()"
        "['honor_idempotency'] is False\n"
        "assert client.post('/__stress/mode', headers=headers,\n"
        "    json={'honor_idempotency': 'yes'}).status_code == 400\n"
        "assert client.post('/__stress/mode', json={'honor_idempotency': True}"
        ").status_code == 403\n"
        "switched = client.post('/__stress/mode', headers=headers,\n"
        "    json={'honor_idempotency': True})\n"
        "assert switched.json() == {'honor_idempotency': True}\n"
        "assert p._honor_idempotency() is True\n"
        "p._apply_refund(refund_ref='r1', amount_cents=500,\n"
        "    invocation_id='i', idempotency_key='k1', honor_idempotency=True)\n"
        "effects = client.get('/__stress/effects', headers=headers).json()\n"
        "assert effects['count'] == 1\n"
        "assert client.get('/mcp').status_code == 401\n",
    )


def test_status_probe_reports_executed_not_executed_and_denies_auth(
    tmp_path: Path,
) -> None:
    _run(
        tmp_path,
        "from starlette.testclient import TestClient\n"
        "from tests.support import mcp_refund_partner_app as p\n"
        "client = TestClient(p.app)\n"
        "body = {'tool': p.REFUND_TOOL_NAME, 'invocation_id': 'inv-1',\n"
        "    'idempotency_key': 'key-1'}\n"
        "denied = client.post('/status', json=body)\n"
        "assert denied.status_code == 401\n"
        "wrong = client.post('/status', json=body,\n"
        "    headers={'Authorization': 'Bearer wrong-token'})\n"
        "assert wrong.status_code == 401\n"
        "control = client.post('/status', json=body,\n"
        "    headers={p.CONTROL_HEADER: 'refund-control'})\n"
        "assert control.status_code == 401\n"
        "headers = {'Authorization': 'Bearer refund-bearer'}\n"
        "missing = client.post('/status', headers=headers, json={\n"
        "    'tool': p.REFUND_TOOL_NAME, 'invocation_id': 'never',\n"
        "    'idempotency_key': 'never'}).json()\n"
        "assert missing == {'status': 'not_executed', 'tool': p.REFUND_TOOL_NAME,\n"
        "    'invocation_id': 'never', 'idempotency_key': 'never'}\n"
        "p._apply_refund(refund_ref='r1', amount_cents=500,\n"
        "    invocation_id='inv-1', idempotency_key='key-1',\n"
        "    honor_idempotency=False)\n"
        "executed = client.post('/status', headers=headers, json=body).json()\n"
        "assert executed == {'status': 'executed', 'tool': p.REFUND_TOOL_NAME,\n"
        "    'invocation_id': 'inv-1', 'idempotency_key': 'key-1'}\n"
        "other_key = client.post('/status', headers=headers, json={\n"
        "    'tool': p.REFUND_TOOL_NAME, 'invocation_id': 'inv-1',\n"
        "    'idempotency_key': 'other'}).json()\n"
        "assert other_key['status'] == 'not_executed'\n"
        "p._open_decision('inv-open', 'key-open')\n"
        "pending = client.post('/status', headers=headers, json={\n"
        "    'tool': p.REFUND_TOOL_NAME, 'invocation_id': 'inv-open',\n"
        "    'idempotency_key': 'key-open'}).json()\n"
        "assert pending['status'] == 'pending'\n"
        "p._apply_refund(refund_ref='r-hang', amount_cents=100,\n"
        "    invocation_id='inv-hang', idempotency_key='key-hang',\n"
        "    honor_idempotency=False)\n"
        "p._open_decision('inv-hang', 'key-hang')\n"
        "hanging = client.post('/status', headers=headers, json={\n"
        "    'tool': p.REFUND_TOOL_NAME, 'invocation_id': 'inv-hang',\n"
        "    'idempotency_key': 'key-hang'}).json()\n"
        "assert hanging['status'] == 'executed'\n",
    )


def test_refund_partner_fixture_stays_out_of_the_production_image() -> None:
    ignored = [
        line.strip()
        for line in (REPO_ROOT / ".dockerignore")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert "tests" in ignored
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "mcp_refund_partner_app" not in dockerfile
    assert "COPY tests" not in dockerfile
    bundle = (REPO_ROOT / "scripts" / "build_refund_partner_bundle.sh").read_text(
        encoding="utf-8"
    )
    assert "tests/support/mcp_refund_partner_app.py" in bundle
    assert ".dockerignore excludes" in bundle
