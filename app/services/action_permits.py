"""Versioned strict JSON action digest; independent of legacy canonical_json."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any

from app.core.auth import AuthContext
from app.schemas.trust import ActionPermitCreateRequest, PermitResponse


@dataclass(frozen=True)
class ActionToolBinding:
    deployment_authority: str
    public_tool_id: str
    upstream_binding_hash: str
    schema_id: str
    schema_version: str
    input_schema: dict[str, Any]


def upstream_action_binding_hash(
    *,
    deployment_authority: str,
    public_tool_id: str,
    upstream_origin: str,
    upstream_tool_name: str,
    schema_id: str,
    schema_version: str,
    input_schema: dict[str, Any],
) -> str:
    """Bind exact configured destination and schema, independent of DNS or keys."""
    descriptor = dict(
        binding_contract_version=1,
        deployment_authority=deployment_authority,
        public_tool_id=public_tool_id,
        upstream_origin=upstream_origin,
        upstream_tool_name=upstream_tool_name,
        schema_id=schema_id,
        schema_version=schema_version,
        input_schema=input_schema,
    )
    for value in (
        deployment_authority,
        public_tool_id,
        upstream_origin,
        upstream_tool_name,
        schema_id,
        schema_version,
    ):
        if type(value) is not str or not value:
            raise ValueError("invalid_action_binding")
    _check_schema(input_schema)
    return hashlib.sha256(
        json.dumps(
            descriptor,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True)
class ActionExecutionIdentity:
    endpoint: str
    idempotency_key: str
    request_payload: dict[str, Any]
    native_idempotency_key: str


def _strict_json(value: Any) -> None:
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float and math.isfinite(value):
        return
    if type(value) is list:
        for child in value:
            _strict_json(child)
        return
    if type(value) is dict and all(type(key) is str for key in value):
        for child in value.values():
            _strict_json(child)
        return
    raise ValueError("action_arguments_must_be_strict_json")


def _check_schema(schema: dict[str, Any]) -> None:
    """Fail closed outside the deliberately small v1 JSON-schema profile."""
    _strict_json(schema)
    kind = schema.get("type")
    keywords = {"type", "default", "enum", "const", "title", "description"}
    if kind == "object":
        keywords |= {"properties", "required", "additionalProperties"}
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        if (
            type(properties) is not dict
            or type(required) is not list
            or any(type(k) is not str or k not in properties for k in required)
        ):
            raise ValueError("invalid_action_schema")
        if type(schema.get("additionalProperties", False)) is not bool:
            raise ValueError("unsupported_action_schema")
        for child in properties.values():
            if type(child) is not dict:
                raise ValueError("invalid_action_schema")
            _check_schema(child)
    elif kind == "array":
        keywords |= {"items", "minItems", "maxItems"}
        if type(schema.get("items")) is not dict:
            raise ValueError("invalid_action_schema")
        _check_schema(schema["items"])
    elif kind in ("number", "integer"):
        keywords |= {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"}
    elif kind == "string":
        keywords |= {"minLength", "maxLength"}
    elif kind not in ("boolean", "null"):
        raise ValueError("unsupported_action_schema")
    if set(schema) - keywords:
        raise ValueError("unsupported_action_schema")
    for name in ("minItems", "maxItems", "minLength", "maxLength"):
        if name in schema and (type(schema[name]) is not int or schema[name] < 0):
            raise ValueError("invalid_action_schema")
    for name in ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"):
        if name in schema and type(schema[name]) not in (int, float):
            raise ValueError("invalid_action_schema")
    if "enum" in schema and (type(schema["enum"]) is not list or not schema["enum"]):
        raise ValueError("invalid_action_schema")
    if "default" in schema:
        _validate(schema, deepcopy(schema["default"]))


def _same_json(left: Any, right: Any) -> bool:
    return json.dumps(
        left, sort_keys=True, separators=(",", ":"), allow_nan=False
    ) == json.dumps(right, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _validate(schema: dict[str, Any], value: Any) -> Any:
    kind = schema["type"]
    types = {
        "object": (dict,),
        "array": (list,),
        "string": (str,),
        "integer": (int,),
        "number": (int, float),
        "boolean": (bool,),
        "null": (type(None),),
    }
    if type(value) not in types[kind]:
        raise ValueError("action_argument_type_mismatch")
    if kind == "object":
        properties = schema.get("properties", {})
        if not schema.get("additionalProperties", False) and set(value) - set(
            properties
        ):
            raise ValueError("action_argument_unknown_property")
        value = dict(value)
        for name, child in properties.items():
            if name not in value and "default" in child:
                value[name] = deepcopy(child["default"])
        if set(schema.get("required", [])) - set(value):
            raise ValueError("action_argument_required")
        value = {
            name: _validate(properties[name], child) if name in properties else child
            for name, child in value.items()
        }
    elif kind == "array":
        value = [_validate(schema["items"], child) for child in value]
    for name, valid in (
        ("minimum", lambda bound: value >= bound),
        ("maximum", lambda bound: value <= bound),
        ("exclusiveMinimum", lambda bound: value > bound),
        ("exclusiveMaximum", lambda bound: value < bound),
        ("minLength", lambda bound: len(value) >= bound),
        ("maxLength", lambda bound: len(value) <= bound),
        ("minItems", lambda bound: len(value) >= bound),
        ("maxItems", lambda bound: len(value) <= bound),
    ):
        if name in schema and not valid(schema[name]):
            raise ValueError("action_argument_constraint")
    if "const" in schema and not _same_json(value, schema["const"]):
        raise ValueError("action_argument_const")
    if "enum" in schema and not any(
        _same_json(value, option) for option in schema["enum"]
    ):
        raise ValueError("action_argument_enum")
    return value


def canonical_action_payload(
    binding: ActionToolBinding, wallet_id: str, arguments: dict[str, Any]
) -> str:
    _strict_json(arguments)
    if (
        type(arguments) is not dict
        or type(binding.input_schema) is not dict
        or binding.input_schema.get("type") != "object"
    ):
        raise ValueError("action_arguments_must_be_object")
    for value in (
        wallet_id,
        binding.public_tool_id,
        binding.upstream_binding_hash,
        binding.schema_id,
        binding.schema_version,
    ):
        if type(value) is not str or not value:
            raise ValueError("invalid_action_binding")
    _check_schema(binding.input_schema)
    validated = _validate(binding.input_schema, arguments)
    _strict_json(validated)
    return json.dumps(
        {
            "action_contract_version": 1,
            "canonicalization": "amw-action-json-v1",
            "subject_wallet_id": wallet_id,
            "public_tool_id": binding.public_tool_id,
            "upstream_binding_hash": binding.upstream_binding_hash,
            "schema_id": binding.schema_id,
            "schema_version": binding.schema_version,
            "arguments": validated,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def action_payload_hash(
    binding: ActionToolBinding, wallet_id: str, arguments: dict[str, Any]
) -> str:
    return hashlib.sha256(
        canonical_action_payload(binding, wallet_id, arguments).encode("utf-8")
    ).hexdigest()


async def authorize_action_issuer(
    request: ActionPermitCreateRequest, auth: AuthContext
) -> None:
    """Require independent sponsor custody or trusted bootstrap authority."""
    from fastapi import HTTPException
    from app.services.agent_money import get_agent_money

    if auth.is_bootstrap_admin:
        return
    auth.require_wallet_access(request.issuer_wallet_id)
    if (
        request.issuer_wallet_id == request.subject_wallet_id
        or not await get_agent_money().is_wallet_or_descendant(
            request.subject_wallet_id, request.issuer_wallet_id
        )
    ):
        raise HTTPException(status_code=403, detail="action_issuer_authority_required")


async def create_action_permit(
    request: ActionPermitCreateRequest, auth: AuthContext
) -> PermitResponse:
    from app.schemas.trust import PermitCreateRequest
    from app.services.permits import PermitError, get_permit_service
    from app.services.service_registry import get_service_registry

    await authorize_action_issuer(request, auth)
    registry = get_service_registry()
    record = await registry.get(request.tool_name)
    try:
        binding = registry.get_action_binding(record) if record else None
        if binding is None:
            raise PermitError("action_tool_binding_required")
        digest = action_payload_hash(
            binding, request.subject_wallet_id, request.arguments
        )
    except ValueError as exc:
        raise PermitError(str(exc)) from exc
    permit = PermitCreateRequest(
        **request.model_dump(exclude={"tool_name", "arguments"}),
        allowed_tools=[request.tool_name],
        max_calls_per_tool={request.tool_name: 1},
        action_contract_version=1,
        action_payload_hash=digest,
        action_schema_id=binding.schema_id,
        action_schema_version=binding.schema_version,
        action_public_tool_id=binding.public_tool_id,
        action_upstream_binding_hash=binding.upstream_binding_hash,
    )
    return await get_permit_service()._persist_permit(permit)
