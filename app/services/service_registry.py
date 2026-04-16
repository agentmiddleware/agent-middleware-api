"""
Service Registry
================

Central registry for MCP-enabled services in the B2A marketplace.
Handles service registration, discovery, and MCP manifest generation.

Architecture:
- Services are registered with their Pydantic input/output schemas
- Schemas are auto-converted to MCP JSON Schema format
- Dynamic MCP proxy routes calls through existing billing layer
"""

import inspect
import json
import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable, get_type_hints

from pydantic import BaseModel
from sqlalchemy import select

from ..db.database import get_session_factory
from ..db.models import ServiceRegistryModel
from ..schemas.billing import ServiceCategory

logger = logging.getLogger(__name__)


def pydantic_to_mcp_schema(model: type[BaseModel] | None) -> dict[str, Any] | None:
    """
    Convert a Pydantic model to MCP JSON Schema format.

    MCP requires full JSON Schema 2020-12 objects for inputSchema.
    Pydantic v2's model_json_schema() is 99% compatible.
    """
    if model is None:
        return None

    if hasattr(model, "model_json_schema"):
        schema = model.model_json_schema(ref_template="#/components/schemas/{model}")
        return {
            "type": "object",
            "properties": schema.get("properties", {}),
            "required": schema.get("required", []),
            "additionalProperties": False,
            **{
                k: v
                for k, v in schema.items()
                if k
                not in (
                    "properties",
                    "required",
                    "title",
                    "type",
                )
            },
        }

    if hasattr(model, "schema"):
        schema = model.schema()
        return {
            "type": "object",
            "properties": schema.get("properties", {}),
            "required": schema.get("required", []),
        }

    return None


def extract_schema_from_callable(
    func: Callable,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """
    Extract input and output schemas from a callable's signature.

    Returns:
        Tuple of (input_schema, output_schema)
    """
    try:
        sig = inspect.signature(func)
        type_hints = get_type_hints(func)

        properties = {}
        required = []

        for param_name, param in sig.parameters.items():
            if param_name in ("self", "cls"):
                continue

            if param_name in type_hints:
                hint = type_hints[param_name]
                if hasattr(hint, "model_json_schema"):
                    properties[param_name] = hint.model_json_schema()
                elif hasattr(hint, "schema"):
                    properties[param_name] = hint.schema()
                else:
                    properties[param_name] = {"type": "string"}

                if param.default is inspect.Parameter.empty:
                    required.append(param_name)

        input_schema = {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        } if properties else None

        return_type = type_hints.get("return")
        output_schema = None
        if return_type and return_type is not type(None):
            if hasattr(return_type, "model_json_schema"):
                output_schema = return_type.model_json_schema()
            elif hasattr(return_type, "schema"):
                output_schema = return_type.schema()
            else:
                output_schema = {"type": "string"}

        return input_schema, output_schema

    except Exception as e:
        logger.warning(f"Failed to extract schema from {func}: {e}")
        return None, None


def _service_to_mcp_tool(service: dict) -> dict:
    """Convert a service record to MCP tool format."""
    tool = {
        "name": service["service_id"],
        "description": service.get("description", ""),
        "inputSchema": service.get("input_schema")
        or {"type": "object", "properties": {}},
    }

    annotations = {
        "creditsPerCall": service.get("credits_per_unit", 1.0),
        "unitName": service.get("unit_name", "call"),
        "category": service.get("category", "custom"),
    }

    if service.get("owner_wallet_id"):
        annotations["providerWallet"] = service["owner_wallet_id"]

    if service.get("output_schema"):
        annotations["hasOutputSchema"] = True

    if not service.get("is_local", True):
        annotations["external"] = True

    tool["annotations"] = annotations

    return tool


class ServiceRegistry:
    """
    Unified registry for MCP-enabled services.

    Services can be registered with:
    - @mcp_tool decorator (local, in-memory)
    - API endpoint /v1/billing/services (persistent, DB)

    The registry provides:
    - Service discovery for MCP manifests
    - Schema extraction and translation
    - Unified query interface for billing engine
    """

    def __init__(self):
        self._session_factory = get_session_factory
        self._local_registry: dict[str, dict] = {}
        self._func_registry: dict[str, Callable] = {}

    def register_local(
        self,
        service_id: str,
        name: str,
        description: str,
        category: ServiceCategory,
        func: Callable,
        input_model: type[BaseModel] | None = None,
        output_model: type[BaseModel] | None = None,
        credits_per_unit: float = 1.0,
        unit_name: str = "call",
        owner_key: str | None = None,
        owner_wallet_id: str | None = None,
    ) -> dict:
        """
        Register a service locally (in-memory) for immediate use.

        This is useful for services defined in the same codebase
        that want MCP-enabled tool exposure without DB persistence.
        """
        input_schema = pydantic_to_mcp_schema(input_model)
        output_schema = pydantic_to_mcp_schema(output_model)

        if input_schema is None and output_schema is None:
            input_schema, output_schema = extract_schema_from_callable(func)

        service_record = {
            "service_id": service_id,
            "name": name,
            "description": description,
            "category": category.value,
            "credits_per_unit": credits_per_unit,
            "unit_name": unit_name,
            "input_schema": input_schema,
            "output_schema": output_schema,
            "owner_key": owner_key,
            "owner_wallet_id": owner_wallet_id,
            "is_active": True,
            "is_local": True,
            "func": func,
            "created_at": datetime.now(timezone.utc),
        }

        self._local_registry[service_id] = service_record
        self._func_registry[service_id] = func

        logger.info(f"Registered local service: {service_id} ({name})")
        return service_record

    async def register_persistent(
        self,
        owner_key: str,
        name: str,
        description: str,
        category: ServiceCategory,
        credits_per_unit: float,
        unit_name: str = "call",
        input_schema: dict | None = None,
        output_schema: dict | None = None,
        owner_wallet_id: str | None = None,
        mcp_metadata: dict | None = None,
    ) -> dict:
        """
        Register a service persistently in the database.

        Used by external developers registering billable services
        through the API.
        """
        service_id = f"svc-{uuid.uuid4().hex[:12]}"

        mcp_manifest = {
            "inputSchema": input_schema,
            "outputSchema": output_schema,
            **(mcp_metadata or {}),
        }

        async with self._session_factory()() as session:
            service = ServiceRegistryModel(
                service_id=service_id,
                name=name,
                description=description,
                owner_key=owner_key,
                owner_wallet_id=owner_wallet_id or "",
                category=category.value,
                credits_per_unit=Decimal(str(credits_per_unit)),
                unit_name=unit_name,
                mcp_manifest=json.dumps(mcp_manifest),
                is_active=True,
            )
            session.add(service)
            await session.commit()

        logger.info(f"Registered persistent service: {service_id} ({name})")

        return {
            "service_id": service_id,
            "name": name,
            "description": description,
            "category": category.value,
            "credits_per_unit": credits_per_unit,
            "unit_name": unit_name,
            "input_schema": input_schema,
            "output_schema": output_schema,
            "owner_wallet_id": owner_wallet_id,
            "is_active": True,
            "is_local": False,
            "created_at": datetime.now(timezone.utc),
        }

    def get_local(self, service_id: str) -> dict | None:
        """Get a locally registered service."""
        return self._local_registry.get(service_id)

    def get_local_func(self, service_id: str) -> Callable | None:
        """Get the callable for a locally registered service."""
        return self._func_registry.get(service_id)

    async def get(self, service_id: str) -> dict | None:
        """Get a service from local or persistent registry."""
        local = self.get_local(service_id)
        if local:
            return local
        return await self.get_persistent(service_id)

    async def get_persistent(self, service_id: str) -> dict | None:
        """Get a persistently registered service from the database."""
        async with self._session_factory()() as session:
            result = await session.execute(
                select(ServiceRegistryModel).where(
                    ServiceRegistryModel.service_id == service_id
                )
            )
            service = result.scalar_one_or_none()
            if not service:
                return None

            manifest = {}
            if service.mcp_manifest:
                try:
                    manifest = json.loads(service.mcp_manifest)
                except json.JSONDecodeError:
                    pass

            return {
                "service_id": service.service_id,
                "name": service.name,
                "description": service.description,
                "category": service.category,
                "credits_per_unit": float(service.credits_per_unit),
                "unit_name": service.unit_name,
                "input_schema": manifest.get("inputSchema"),
                "output_schema": manifest.get("outputSchema"),
                "owner_wallet_id": service.owner_wallet_id,
                "is_active": service.is_active,
                "is_local": False,
                "created_at": service.created_at,
            }

    async def list_local(self) -> list[dict]:
        """List all locally registered services."""
        return [
            {k: v for k, v in svc.items() if k not in ("func",)}
            for svc in self._local_registry.values()
        ]

    async def list_persistent(
        self,
        category: ServiceCategory | None = None,
        active_only: bool = True,
    ) -> list[dict]:
        """List all persistently registered services."""
        async with self._session_factory()() as session:
            query = select(ServiceRegistryModel)
            if category:
                query = query.where(ServiceRegistryModel.category == category.value)
            if active_only:
                query = query.where(ServiceRegistryModel.is_active.is_(True))

            result = await session.execute(query)
            services = result.scalars().all()

            results = []
            for service in services:
                manifest = {}
                if service.mcp_manifest:
                    try:
                        manifest = json.loads(service.mcp_manifest)
                    except json.JSONDecodeError:
                        pass

                results.append({
                    "service_id": service.service_id,
                    "name": service.name,
                    "description": service.description,
                    "category": service.category,
                    "credits_per_unit": float(service.credits_per_unit),
                    "unit_name": service.unit_name,
                    "input_schema": manifest.get("inputSchema"),
                    "output_schema": manifest.get("outputSchema"),
                    "owner_wallet_id": service.owner_wallet_id,
                    "is_active": service.is_active,
                    "is_local": False,
                    "created_at": service.created_at,
                })

            return results

    async def list_all(self, category: ServiceCategory | None = None) -> list[dict]:
        """List all services (local + persistent)."""
        local = await self.list_local()
        persistent = await self.list_persistent(category=category)

        all_services = local + persistent
        if category:
            all_services = [
                s
                for s in all_services
                if s.get("category") == category.value
            ]

        return [s for s in all_services if s.get("is_active", True)]

    async def get_pricing(self, service_id: str) -> tuple[float, str] | None:
        """
        Get pricing for a service. Used by billing engine.

        Returns:
            Tuple of (credits_per_unit, unit_name) or None if not found
        """
        service = await self.get(service_id)
        if service:
            return (
                service.get("credits_per_unit", 1.0),
                service.get("unit_name", "call"),
            )
        return None

    def to_mcp_tool(self, service: dict) -> dict:
        """Convert a service record to MCP tool format."""
        return _service_to_mcp_tool(service)

    def unregister_local(self, service_id: str) -> bool:
        """Unregister a local service."""
        if service_id in self._local_registry:
            del self._local_registry[service_id]
            if service_id in self._func_registry:
                del self._func_registry[service_id]
            return True
        return False


_service_registry: ServiceRegistry | None = None


def get_service_registry() -> ServiceRegistry:
    """Get or create the global ServiceRegistry singleton."""
    global _service_registry
    if _service_registry is None:
        _service_registry = ServiceRegistry()
    return _service_registry
