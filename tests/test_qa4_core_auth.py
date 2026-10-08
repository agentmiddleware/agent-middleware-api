"""QA pass for app/core/auth.py, jwt.py, scopes.py, oidc_iga.py, rate_limiter.py.

Unit-level coverage for untested behavior in the auth surface. No DB, no
network, no sleeps. Product files in this module are owned by in-flight
work, so every finding here is a test only; demonstrated bugs are marked
xfail(strict=True) and listed in .metacode_pr.md.
"""

import hashlib
import json
import time

import jwt as pyjwt
import pytest
from fastapi import HTTPException, Response
from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from app.core.auth import (
    CREDENTIAL_ACCEPTANCE,
    CREDENTIAL_REJECTED_HEADER,
    AuthContext,
    CredentialAcceptance,
    _parse_bearer_authorization,
    get_auth_context,
    get_enterprise_principal,
)
from app.core.config import get_settings
from app.core.jwt import get_jwt_service
from app.core.oidc_iga import (
    IGAError,
    _group_policy_map,
    _trusted_issuers,
    enforce_tool_call,
    is_iga_issuer_token,
    reset_iga_counters,
    token_issuer_is_trusted,
)
from app.core.rate_limiter import (
    RateLimitMiddleware,
    _api_key_bucket,
    _client_id,
    _credentials_were_rejected,
    _presented_rate_identity,
    _rate_limited_response,
    enforce_redis_timeouts,
)
from app.core.scopes import require_scope
from app.core.oidc_iga import EnterprisePrincipal

TEST_SIGNING_KEY = "dGVzdC1zaWduaW5nLWtleS1tYXRlcmlhbC0zMmJ5dGU="
OKTA_ISS = "https://example.okta.com/oauth2/default"


@pytest.fixture()
def core_settings():
    """Snapshot and restore cached settings fields mutated below."""
    settings = get_settings()
    saved = {
        name: getattr(settings, name)
        for name in (
            "ENVIRONMENT",
            "DEBUG",
            "VALID_API_KEYS",
            "STATIC_DEV_API_KEYS",
            "ENABLE_DEV_KEY_SELF_PROVISION",
            "TRUST_SIGNING_PRIVATE_KEY_B64",
            "IGA_TRUSTED_ISSUERS",
            "IGA_GROUP_POLICY_MAP",
        )
    }
    try:
        yield settings
    finally:
        for name, value in saved.items():
            setattr(settings, name, value)


@pytest.fixture()
def signing_service(core_settings):
    core_settings.TRUST_SIGNING_PRIVATE_KEY_B64 = TEST_SIGNING_KEY
    return get_jwt_service()


@pytest.fixture()
def env_keys(core_settings):
    core_settings.ENVIRONMENT = "local"
    core_settings.DEBUG = False
    core_settings.VALID_API_KEYS = "test-key"
    core_settings.STATIC_DEV_API_KEYS = ""
    return core_settings


# --- _parse_bearer_authorization -------------------------------------------


@pytest.mark.parametrize(
    "header",
    ["Token abc.def.ghi", "Bearer abc ", "Bearer ab\tc", "Bearer a b"],
)
def test_bearer_parsing_rejects_malformed_headers(header):
    with pytest.raises(HTTPException) as exc:
        _parse_bearer_authorization(header)
    assert exc.value.status_code == 401
    assert exc.value.detail["error"] == "invalid_token"


# --- Authorization precedence: a presented header never falls back ---------


async def test_invalid_bearer_never_falls_back_to_valid_api_key(env_keys):
    """A bad Bearer header plus a good key must still refuse outright."""
    with pytest.raises(HTTPException) as exc:
        await get_auth_context(api_key="test-key", authorization="Bearer garbage")
    assert exc.value.status_code == 401


async def test_jwt_shaped_key_value_that_fails_verify_is_401(env_keys):
    """A dotted long value is verified as a token, never looked up as a key."""
    fake = "k." + "v" * 55 + ".s"
    assert fake.count(".") == 2 and len(fake) > 50
    with pytest.raises(HTTPException) as exc:
        await get_auth_context(api_key=fake)
    assert exc.value.status_code == 401
    assert exc.value.detail["error"] == "invalid_token"


# --- key shape guards -------------------------------------------------------


async def test_blank_or_short_key_is_401(env_keys):
    for bad in ("   ", "short"):
        with pytest.raises(HTTPException) as exc:
            await get_auth_context(api_key=bad)
        assert exc.value.status_code == 401
        assert exc.value.detail["error"] == "invalid_api_key"


async def test_eight_char_unknown_key_is_403_with_rejected_marker(env_keys):
    """Long enough to pass the shape guard, unknown, so refused as a key."""
    with pytest.raises(HTTPException) as exc:
        await get_auth_context(api_key="unknown-1")
    assert exc.value.status_code == 403
    assert exc.value.detail["error"] == "invalid_api_key"
    assert exc.value.headers[CREDENTIAL_REJECTED_HEADER] == "1"


async def test_missing_credentials_is_401(env_keys):
    with pytest.raises(HTTPException) as exc:
        await get_auth_context(api_key=None, authorization=None)
    assert exc.value.status_code == 401
    assert exc.value.detail["error"] == "missing_credentials"


async def test_missing_credentials_points_at_self_provision(core_settings):
    core_settings.ENVIRONMENT = "local"
    core_settings.ENABLE_DEV_KEY_SELF_PROVISION = True
    with pytest.raises(HTTPException) as exc:
        await get_auth_context(api_key=None, authorization=None)
    assert "self_provision" in exc.value.detail


async def test_missing_credentials_hides_self_provision_otherwise(
    core_settings,
):
    """No hint when the flag is off, or when the boot is production-like."""
    for environment, flag in (("local", False), ("production", True)):
        core_settings.ENVIRONMENT = environment
        core_settings.ENABLE_DEV_KEY_SELF_PROVISION = flag
        with pytest.raises(HTTPException) as exc:
            await get_auth_context(api_key=None, authorization=None)
        assert "self_provision" not in exc.value.detail


async def test_debug_open_mode_mints_admin_only_when_no_keys(core_settings):
    core_settings.ENVIRONMENT = "local"
    core_settings.DEBUG = True
    core_settings.VALID_API_KEYS = ""
    core_settings.STATIC_DEV_API_KEYS = ""
    context = await get_auth_context(api_key="any-unconfigured-key")
    assert context.is_bootstrap_admin is True
    assert context.source == "env"


async def test_debug_open_mode_refused_in_production(core_settings):
    core_settings.ENVIRONMENT = "production"
    core_settings.DEBUG = True
    core_settings.VALID_API_KEYS = ""
    core_settings.STATIC_DEV_API_KEYS = ""
    with pytest.raises(HTTPException) as exc:
        await get_auth_context(api_key="any-unconfigured-key")
    assert exc.value.status_code == 403


# --- AuthContext helpers ----------------------------------------------------


def test_require_wallet_access_allows_exact_owner():
    context = AuthContext(source="db", raw_key="k", wallet_id="w1")
    context.require_wallet_access("w1")  # must not raise


def test_require_wallet_access_denies_non_owner():
    context = AuthContext(source="db", raw_key="k", wallet_id="w1")
    for other in ("w2", None):
        with pytest.raises(HTTPException) as exc:
            context.require_wallet_access(other)
        assert exc.value.status_code == 403
        assert exc.value.detail["error"] == "wallet_access_denied"


def test_require_wallet_access_admin_bypasses_everything():
    context = AuthContext(source="env", raw_key="k", is_bootstrap_admin=True)
    context.require_wallet_access("anything")
    context.require_wallet_access(None)


def test_require_bootstrap_admin_denies_non_admin():
    context = AuthContext(source="db", raw_key="k", wallet_id="w1")
    with pytest.raises(HTTPException) as exc:
        context.require_bootstrap_admin()
    assert exc.value.detail["error"] == "admin_access_denied"


async def test_successful_auth_marks_credential_acceptance(env_keys):
    acceptance = CredentialAcceptance()
    token = CREDENTIAL_ACCEPTANCE.set(acceptance)
    try:
        await get_auth_context(api_key="test-key")
    finally:
        CREDENTIAL_ACCEPTANCE.reset(token)
    assert acceptance.accepted is True


def _request(headers=None):
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return Request(
        {"type": "http", "method": "GET", "headers": raw, "client": ("9.9.9.9", 5000)}
    )


# --- JWT service ------------------------------------------------------------


def test_jwt_access_roundtrip(signing_service):
    token = signing_service.create_access_token(
        wallet_id="w", key_id="k", scopes=["billing:read"]
    )
    payload = signing_service.verify_access_token(token)
    assert payload.sub == "w"
    assert payload.key_id == "k"
    assert payload.scopes == ["billing:read"]
    assert payload.type == "access"
    assert payload.iss == "agent-middleware-api"
    assert payload.aud == "agent-middleware-api"
    assert payload.exp > payload.iat


def test_jwt_refresh_token_rejected_as_access(signing_service):
    refresh = signing_service.create_refresh_token("w", ["billing:read"])
    with pytest.raises(Exception, match="token_type_mismatch"):
        signing_service.verify_access_token(refresh)


def test_jwt_expired_token_refused(signing_service):
    private_key, _ = signing_service._load_keys()
    now = int(time.time())
    token = pyjwt.encode(
        {
            "sub": "w",
            "key_id": "k",
            "scopes": [],
            "iat": now - 2000,
            "exp": now - 100,
            "iss": "agent-middleware-api",
            "aud": "agent-middleware-api",
            "jti": "j-exp",
            "type": "access",
        },
        private_key,
        algorithm="EdDSA",
    )
    with pytest.raises(Exception, match="token_expired"):
        signing_service.verify_access_token(token)


def _mint_raw(signing_service, claims):
    private_key, _ = signing_service._load_keys()
    base = {
        "sub": "w",
        "scopes": [],
        "iat": int(time.time()),
        "exp": int(time.time()) + 300,
        "iss": "agent-middleware-api",
        "aud": "agent-middleware-api",
        "jti": "j-raw",
        "type": "access",
    }
    base.update(claims)
    return pyjwt.encode(base, private_key, algorithm="EdDSA")


def test_jwt_missing_expiry_refused(signing_service):
    private_key, _ = signing_service._load_keys()
    claims = {
        "sub": "w",
        "scopes": [],
        "iat": int(time.time()),
        "iss": "agent-middleware-api",
        "aud": "agent-middleware-api",
        "jti": "j-noexp",
        "type": "access",
    }
    token = pyjwt.encode(claims, private_key, algorithm="EdDSA")
    with pytest.raises(Exception, match="invalid_token"):
        signing_service.verify_access_token(token)


@pytest.mark.parametrize(
    ("claims", "reason"),
    [
        ({"aud": "someone-else"}, "invalid_token"),
        ({"scopes": "billing:read"}, "invalid_or_missing_scopes"),
    ],
)
def test_jwt_malformed_claims_refused(signing_service, claims, reason):
    with pytest.raises(Exception, match=reason):
        signing_service.verify_access_token(_mint_raw(signing_service, claims))


def test_jwt_tampered_signature_refused(signing_service):
    token = signing_service.create_access_token("w", "k", [])
    head, body, _sig = token.split(".")
    other = signing_service.create_access_token("w", "k", [])
    bad = head + "." + body + "." + other.split(".")[2]
    if bad == token:  # keyed tokens must differ; guard the swap
        bad = head + "." + body + ".AAAA"
    with pytest.raises(Exception, match="invalid_token"):
        signing_service.verify_access_token(bad)


def test_jwt_without_signing_key_configured(core_settings):
    core_settings.TRUST_SIGNING_PRIVATE_KEY_B64 = ""
    with pytest.raises(Exception, match="signing_key_not_configured"):
        get_jwt_service().create_access_token("w", "k", [])


# --- require_scope ----------------------------------------------------------


async def test_require_scope_accepts_context_as_positional_arg():
    @require_scope("billing:charge")
    async def protected(auth):
        return "ok"

    context = AuthContext(
        source="jwt", raw_key="jwt:k", wallet_id="w", scopes=["billing:charge"]
    )
    assert await protected(context) == "ok"


async def test_require_scope_accepts_any_one_of_several():
    @require_scope("billing:charge", "billing:refund")
    async def protected(auth: AuthContext):
        return "ok"

    context = AuthContext(
        source="jwt", raw_key="jwt:k", wallet_id="w", scopes=["billing:refund"]
    )
    assert await protected(auth=context) == "ok"


async def test_require_scope_denies_jwt_without_scope():
    @require_scope("billing:charge")
    async def protected(auth: AuthContext):
        return "ok"  # pragma: no cover

    context = AuthContext(
        source="jwt", raw_key="jwt:k", wallet_id="w", scopes=["billing:read"]
    )
    with pytest.raises(HTTPException) as exc:
        await protected(auth=context)
    assert exc.value.status_code == 403
    assert exc.value.detail["error"] == "insufficient_scope"
    assert exc.value.detail["required"] == ["billing:charge"]
    assert exc.value.detail["provided"] == ["billing:read"]


async def test_require_scope_needs_authentication():
    @require_scope("billing:charge")
    async def protected(auth: AuthContext):
        return "ok"  # pragma: no cover

    with pytest.raises(HTTPException) as exc:
        await protected()
    assert exc.value.status_code == 401


@pytest.mark.parametrize("source", ["db", "env", "static-dev"])
async def test_require_scope_bypasses_key_sources(source):
    @require_scope("billing:charge")
    async def protected(auth: AuthContext):
        return "ok"

    context = AuthContext(source=source, raw_key="k", wallet_id="w")
    assert await protected(auth=context) == "ok"


@pytest.mark.xfail(
    strict=True,
    reason="BUG(scopes.py:32): wrapper always awaits func, so sync callables raise TypeError",
)
async def test_require_scope_supports_sync_functions():
    @require_scope("billing:charge")
    def protected(auth: AuthContext):
        return "ok"

    context = AuthContext(source="db", raw_key="k", wallet_id="w")
    assert await protected(auth=context) == "ok"


# --- oidc_iga: config parsing ----------------------------------------------

OKTA_ENTRY = {
    "audience": "api://agent-middleware",
    "algorithms": ["RS256"],
    "public_key_pem": "-----DUMMY-----",
}


def _issuers_doc(entries):
    return json.dumps(entries)


async def test_iga_disabled_by_default(core_settings):
    core_settings.IGA_TRUSTED_ISSUERS = ""
    assert _trusted_issuers() == {}
    assert token_issuer_is_trusted("anything") is False
    assert is_iga_issuer_token("anything") is False


async def test_iga_malformed_json_fails_closed(core_settings):
    core_settings.IGA_TRUSTED_ISSUERS = "{nope"
    with pytest.raises(IGAError) as exc:
        _trusted_issuers()
    assert exc.value.reason == "iga_config_invalid"


async def test_iga_none_algorithm_never_allowed(core_settings):
    entry = dict(OKTA_ENTRY, algorithms=["none"])
    core_settings.IGA_TRUSTED_ISSUERS = _issuers_doc({OKTA_ISS: entry})
    with pytest.raises(IGAError) as exc:
        _trusted_issuers()
    assert exc.value.reason == "iga_config_invalid"


async def test_iga_both_key_sources_fails_closed(core_settings):
    entry = dict(OKTA_ENTRY, jwks={"keys": []})
    core_settings.IGA_TRUSTED_ISSUERS = _issuers_doc({OKTA_ISS: entry})
    with pytest.raises(IGAError):
        _trusted_issuers()


async def test_iga_provider_inference(core_settings):
    core_settings.IGA_TRUSTED_ISSUERS = _issuers_doc({OKTA_ISS: dict(OKTA_ENTRY)})
    assert _trusted_issuers()[OKTA_ISS].provider == "okta"
    core_settings.IGA_TRUSTED_ISSUERS = _issuers_doc(
        {"https://login.vanity.example/tenant": dict(OKTA_ENTRY)}
    )
    with pytest.raises(IGAError):
        _trusted_issuers()


async def test_iga_group_map_half_velocity_cap_fails(core_settings):
    core_settings.IGA_GROUP_POLICY_MAP = json.dumps(
        {"ops": {"policy_id": "p1", "velocity_window_seconds": 60}}
    )
    with pytest.raises(IGAError):
        _group_policy_map()


async def test_iga_routing_fails_closed_on_bad_config(core_settings, caplog):
    core_settings.IGA_TRUSTED_ISSUERS = "{bad json"
    with caplog.at_level("ERROR"):
        assert is_iga_issuer_token("aaa.bbb.ccc") is False


async def test_enforce_blocks_principal_without_mapped_role(core_settings):
    reset_iga_counters()
    core_settings.IGA_GROUP_POLICY_MAP = ""
    principal = EnterprisePrincipal(
        subject="u1", provider="okta", issuer=OKTA_ISS, groups=("nobody",)
    )
    decision = await enforce_tool_call(principal, "demo.tool")
    assert decision.allowed is False
    assert decision.reason == "iga_no_matching_role"


async def test_enterprise_principal_absent_when_iga_disabled(core_settings):
    core_settings.IGA_TRUSTED_ISSUERS = ""
    assert await get_enterprise_principal(authorization="Bearer x.y.z") is None
    assert await get_enterprise_principal(authorization=None) is None
    assert await get_enterprise_principal(authorization="Basic abc") is None


# --- rate limiter units -----------------------------------------------------


def test_api_key_bucket_hides_key_material():
    bucket = _api_key_bucket("test-key")
    assert "test-key" not in bucket
    expected = hashlib.sha256(
        b"agent-middleware-api:rate-limit-bucket:v1\x00" + b"test-key"
    ).hexdigest()
    assert bucket == f"api_key_sha256:{expected}"


def test_api_key_bucket_none_is_shared_anonymous():
    assert _api_key_bucket(None) == "anonymous"
    assert _api_key_bucket("a") != _api_key_bucket("b")


def test_rate_limited_response_shape():
    response = _rate_limited_response(120, 30, "slow down")
    assert response.status_code == 429
    assert response.headers["X-RateLimit-Remaining"] == "0"
    assert response.headers["Retry-After"] == "30"
    body = json.loads(bytes(response.body).decode())
    assert body["detail"]["error"] == "rate_limited"
    assert body["detail"]["retry_after_seconds"] == 30


def test_rejected_credentials_detection_and_stripping():
    assert _credentials_were_rejected(Response(status_code=401)) is True
    assert _credentials_were_rejected(Response(status_code=403)) is False
    marked = Response(status_code=403, headers={CREDENTIAL_REJECTED_HEADER: "1"})
    assert _credentials_were_rejected(marked) is True
    assert CREDENTIAL_REJECTED_HEADER not in marked.headers


def test_client_id_peer_and_railway(monkeypatch):
    peer = Request(
        {"type": "http", "method": "GET", "headers": [], "client": ("9.9.9.9", 5000)}
    )
    assert _client_id(peer) == "9.9.9.9"
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_ID", "env-1")
    single = Request(
        {
            "type": "http",
            "method": "GET",
            "headers": [(b"x-real-ip", b"1.2.3.4")],
            "client": ("9.9.9.9", 5000),
        }
    )
    assert _client_id(single) == "1.2.3.4"


def test_client_id_railway_rejects_spoofable_values(monkeypatch):
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_ID", "env-1")
    multi = Request(
        {
            "type": "http",
            "method": "GET",
            "headers": [(b"x-real-ip", b"1.2.3.4"), (b"x-real-ip", b"5.6.7.8")],
            "client": ("9.9.9.9", 5000),
        }
    )
    assert _client_id(multi) == "9.9.9.9"


def test_enforce_redis_timeouts_rewrites_pool_kwargs():
    pool = {"socket_timeout": 99}
    client = type(
        "C", (), {"connection_pool": type("P", (), {"connection_kwargs": pool})()}
    )()
    assert enforce_redis_timeouts(client) is client
    assert pool == {
        "socket_timeout": 2.0,
        "socket_connect_timeout": 2.0,
        "health_check_interval": 15,
    }


def test_presented_identity_cases():
    assert _presented_rate_identity(_request({"x-api-key": "abc"})) == "abc"
    assert _presented_rate_identity(_request()) is None
    malformed = _presented_rate_identity(_request({"authorization": "Token x"}))
    assert malformed.startswith("invalid-authorization:")


def _ok_app():
    async def ok(_request):
        return PlainTextResponse("ok")

    return Starlette(routes=[Route("/v1/wallets", ok)])


async def test_memory_limiter_429_shape_and_headers():
    limited = RateLimitMiddleware(_ok_app(), requests_per_minute=2)
    transport = ASGITransport(app=limited)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        first = await http.get("/v1/wallets", headers={"X-API-Key": "k1"})
        second = await http.get("/v1/wallets", headers={"X-API-Key": "k1"})
        third = await http.get("/v1/wallets", headers={"X-API-Key": "k1"})
        other = await http.get("/v1/wallets", headers={"X-API-Key": "k2"})
    assert (first.status_code, second.status_code) == (200, 200)
    assert third.status_code == 429
    assert third.headers["X-RateLimit-Remaining"] == "0"
    assert "Retry-After" in third.headers
    assert other.status_code == 200
