"""
Protocol Generation Engine — Code-to-Discovery Pipeline (Pillar 11)
=====================================================================
When an agent builds a new tool, it needs instant discoverability.
This engine takes raw API code and auto-generates a draft-quality
starting point (strongest on Python/FastAPI; everything else is
labeled as a fallback in the generation warnings):

1. llm.txt — LLM-optimized plaintext documentation
2. OpenAPI 3.1 specification (JSON)
3. agent.json manifest (/.well-known/agent.json)
4. Oracle registration — push the tool into agent directories

Pipeline:
  Raw code → Parse endpoints → Generate docs → Package specs → Register in Oracle

Production wiring:
- AST parsing for Python/FastAPI code
- OpenAPI schema generation
- Agent Oracle integration for instant GTM
"""

import ast
import uuid
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Parsed Endpoint
# ---------------------------------------------------------------------------


@dataclass
class ParsedEndpoint:
    """An endpoint extracted from source code."""

    method: str  # GET, POST, PUT, DELETE, PATCH
    path: str  # /v1/widgets
    summary: str = ""
    description: str = ""
    parameters: list[dict] = field(default_factory=list)
    request_body: dict | None = None
    response_model: str = ""
    tags: list[str] = field(default_factory=list)


@dataclass
class GenerationResult:
    """Result of a full protocol generation run."""

    generation_id: str
    service_name: str
    service_version: str
    endpoints_parsed: int
    llm_txt: str
    openapi_spec: dict
    agent_json: dict
    oracle_registration_id: str | None = None
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    warnings: list[str] = field(default_factory=list)
    # Wallet that submitted the source; None for a bootstrap-admin caller.
    owner_wallet_id: str | None = None


# ---------------------------------------------------------------------------
# Code Parser
# ---------------------------------------------------------------------------


class CodeParser:
    """Extract API endpoint definitions from source code.

    Best effort for Python/FastAPI code: an AST pass reads handler
    signatures (path/query parameters, request-body models) and a
    decorator-pattern fallback covers anything the AST pass misses.
    Anything the AST pass cannot follow is draft quality and is labeled
    as such in the generation warnings.
    """

    # Pattern to match FastAPI-style decorators (fallback only)
    DECORATOR_RE = re.compile(
        r'@\w+\.(get|post|put|delete|patch)\(\s*["\']([^"\']+)["\']', re.IGNORECASE
    )
    SUMMARY_RE = re.compile(r'summary\s*=\s*["\']([^"\']+)["\']')
    DESC_RE = re.compile(r'description\s*=\s*["\']([^"\']+)["\']')
    RESPONSE_RE = re.compile(r"response_model\s*=\s*(\w+)")
    FUNC_RE = re.compile(r"(?:async\s+)?def\s+(\w+)\s*\(")

    HTTP_METHODS = {"get", "post", "put", "delete", "patch"}

    # Framework-injected handler arguments that are not API parameters.
    _INJECTED_ARGS = {"self", "cls", "request"}

    FALLBACK_WARNING = (
        "Draft quality: the source did not parse as structured Python, "
        "so endpoints were extracted with a decorator-pattern fallback. "
        "Parameters and request bodies may be incomplete; verify the "
        "generated specs against the real service."
    )

    def parse(
        self,
        source_code: str,
        service_name: str = "unknown",
    ) -> list[ParsedEndpoint]:
        """Parse FastAPI-style source code and extract endpoint definitions."""
        endpoints, _ = self.parse_with_notes(source_code, service_name)
        return endpoints

    def parse_with_notes(
        self,
        source_code: str,
        service_name: str = "unknown",
    ) -> tuple[list[ParsedEndpoint], list[str]]:
        """Parse endpoints, returning (endpoints, generation notes)."""
        try:
            tree = ast.parse(source_code)
        except (SyntaxError, ValueError):
            endpoints = self._parse_regex(source_code, service_name)
            notes = [self.FALLBACK_WARNING] if endpoints else []
            return endpoints, notes
        endpoints = self._parse_ast(tree, service_name)
        if endpoints:
            return endpoints, []
        endpoints = self._parse_regex(source_code, service_name)
        if endpoints:
            return endpoints, [self.FALLBACK_WARNING]
        return [], []

    def _parse_ast(self, tree: ast.Module, service_name: str) -> list[ParsedEndpoint]:
        """Extract endpoints from a parsed Python module.

        Reads @router.<method>("path", ...) decorators on functions,
        handler argument names and annotations for parameters, and locally
        defined model classes for request bodies.
        """
        models: dict[str, dict[str, str]] = {}
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                fields = {}
                for stmt in node.body:
                    if isinstance(stmt, ast.AnnAssign) and isinstance(
                        stmt.target, ast.Name
                    ):
                        fields[stmt.target.id] = self._type_name(stmt.annotation)
                if fields:
                    models[node.name] = fields

        endpoints = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                endpoint = self._endpoint_from_decorator(
                    decorator, node, models, service_name
                )
                if endpoint is not None:
                    endpoints.append(endpoint)
                    break
        return endpoints

    def _endpoint_from_decorator(
        self,
        decorator: ast.expr,
        func: ast.FunctionDef | ast.AsyncFunctionDef,
        models: dict[str, dict[str, str]],
        service_name: str,
    ) -> ParsedEndpoint | None:
        if not isinstance(decorator, ast.Call):
            return None
        target = decorator.func
        if not (
            isinstance(target, ast.Attribute)
            and target.attr.lower() in self.HTTP_METHODS
        ):
            return None
        if (
            not decorator.args
            or not isinstance(decorator.args[0], ast.Constant)
            or not isinstance(decorator.args[0].value, str)
        ):
            return None
        method = target.attr.upper()
        path = decorator.args[0].value
        keywords = {kw.arg: kw.value for kw in decorator.keywords if kw.arg}
        response_node = keywords.get("response_model")
        if isinstance(response_node, ast.Name):
            response_model = response_node.id
        elif isinstance(response_node, ast.Attribute):
            response_model = response_node.attr
        else:
            response_model = ""

        parameters: list[dict] = []
        request_body: dict | None = None
        positional = list(func.args.args)
        pos_defaults: list = [None] * (
            len(positional) - len(func.args.defaults)
        ) + list(func.args.defaults)
        argued = list(zip(positional, pos_defaults)) + list(
            zip(func.args.kwonlyargs, func.args.kw_defaults)
        )
        for arg, default in argued:
            if arg.arg in self._INJECTED_ARGS:
                continue
            annotation = (
                self._type_name(arg.annotation)
                if arg.annotation is not None
                else "string"
            )
            if annotation in models and request_body is None:
                request_body = {
                    "type": "object",
                    "title": annotation,
                    "properties": {
                        name: {"type": field_type}
                        for name, field_type in models[annotation].items()
                    },
                }
                continue
            in_path = "{" + arg.arg + "}" in path
            parameters.append(
                {
                    "name": arg.arg,
                    "in": "path" if in_path else "query",
                    "type": annotation,
                    "required": in_path or default is None,
                }
            )

        return ParsedEndpoint(
            method=method,
            path=path,
            summary=self._const_str(keywords.get("summary")),
            description=self._const_str(keywords.get("description")),
            parameters=parameters,
            request_body=request_body,
            response_model=response_model,
            tags=[service_name],
        )

    @staticmethod
    def _type_name(node: ast.expr | None) -> str:
        if isinstance(node, ast.Name):
            return {
                "str": "string",
                "int": "integer",
                "float": "number",
                "bool": "boolean",
            }.get(node.id, node.id)
        if isinstance(node, ast.Attribute):
            return node.attr
        if isinstance(node, ast.Subscript):
            value = node.value
            if isinstance(value, ast.Name) and value.id in ("Optional", "Union"):
                return CodeParser._type_name(node.slice)
            if isinstance(value, ast.Name) and value.id in (
                "List",
                "list",
                "Sequence",
            ):
                return "array"
            return CodeParser._type_name(value)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
            return CodeParser._type_name(node.left)
        return "string"

    @staticmethod
    def _const_str(node: ast.expr | None) -> str:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        return ""

    def _parse_regex(
        self,
        source_code: str,
        service_name: str = "unknown",
    ) -> list[ParsedEndpoint]:
        """Decorator-pattern fallback for code the AST pass cannot follow."""
        endpoints = []
        lines = source_code.split("\n")

        i = 0
        while i < len(lines):
            line = lines[i]
            match = self.DECORATOR_RE.search(line)
            if match:
                method = match.group(1).upper()
                path = match.group(2)

                # Look ahead for summary, description, response_model
                context_block = "\n".join(lines[i : min(i + 20, len(lines))])
                summary_match = self.SUMMARY_RE.search(context_block)
                desc_match = self.DESC_RE.search(context_block)
                resp_match = self.RESPONSE_RE.search(context_block)

                endpoints.append(
                    ParsedEndpoint(
                        method=method,
                        path=path,
                        summary=summary_match.group(1) if summary_match else "",
                        description=desc_match.group(1) if desc_match else "",
                        response_model=resp_match.group(1) if resp_match else "",
                        tags=[service_name],
                    )
                )
            i += 1

        return endpoints


# ---------------------------------------------------------------------------
# Document Generators
# ---------------------------------------------------------------------------


class LlmTxtGenerator:
    """Generate LLM-optimized plaintext documentation."""

    def generate(
        self,
        service_name: str,
        service_version: str,
        base_url: str,
        endpoints: list[ParsedEndpoint],
        auth_method: str | None = None,
        rate_limit: str | None = None,
    ) -> str:
        # Auth and rate limits are stated only when the submitter declares
        # them. The generator cannot see the running service, so inventing
        # defaults here would put false claims into buyer-facing docs.
        if auth_method:
            auth_line = f"# Auth: {auth_method}"
        else:
            auth_line = "# Auth: not specified in submission"
        lines = [
            f"# {service_name} API v{service_version}",
            f"# Base URL: {base_url}",
            auth_line,
            f"# Endpoints: {len(endpoints)}",
            "",
            "## Endpoints",
            "",
        ]

        for ep in endpoints:
            lines.append(f"### {ep.method} {ep.path}")
            if ep.summary:
                lines.append(f"Summary: {ep.summary}")
            if ep.description:
                lines.append(f"Description: {ep.description}")
            if ep.response_model:
                lines.append(f"Returns: {ep.response_model}")
            if ep.parameters:
                lines.append("Parameters:")
                for p in ep.parameters:
                    lines.append(f"  - {p.get('name', '?')}: {p.get('type', 'string')}")
            lines.append("")

        lines.append("## Authentication")
        if auth_method:
            lines.append(f"Authentication as declared by the submitter: {auth_method}.")
            lines.append("Confirm with the service operator before calling.")
        else:
            lines.append("Authentication: not specified in the submitted source.")
            lines.append(
                "Confirm required credentials with the service operator before calling."
            )
        lines.append("")
        lines.append("## Rate Limits")
        if rate_limit:
            lines.append(f"Rate limits as declared by the submitter: {rate_limit}.")
        else:
            lines.append("Rate limits: not specified in the submitted source.")
            lines.append("Confirm with the service operator before calling.")
        lines.append("")
        lines.append(
            f"# Generated by Protocol Engine at "
            f"{datetime.now(timezone.utc).isoformat()}"
        )

        return "\n".join(lines)


class OpenApiGenerator:
    """Generate OpenAPI 3.1 specification."""

    def generate(
        self,
        service_name: str,
        service_version: str,
        base_url: str,
        endpoints: list[ParsedEndpoint],
    ) -> dict:
        paths: dict = {}
        for ep in endpoints:
            path_key = ep.path
            if path_key not in paths:
                paths[path_key] = {}

            operation = {
                "summary": ep.summary or f"{ep.method} {ep.path}",
                "operationId": (
                    f"{ep.method.lower()}_{ep.path.replace('/', '_').strip('_')}"
                ),
                "tags": ep.tags,
                "responses": {
                    "200": {
                        "description": "Successful response",
                        "content": {"application/json": {"schema": {"type": "object"}}},
                    },
                    "401": {"description": "Missing or invalid API key"},
                },
                "security": [{"ApiKeyAuth": []}],
            }

            if ep.description:
                operation["description"] = ep.description

            if ep.parameters:
                operation["parameters"] = [
                    {
                        "name": p.get("name", "param"),
                        "in": p.get("in", "query"),
                        "schema": {"type": p.get("type", "string")},
                        "required": p.get("required", False),
                    }
                    for p in ep.parameters
                ]

            if ep.request_body:
                operation["requestBody"] = {
                    "required": True,
                    "content": {"application/json": {"schema": ep.request_body}},
                }

            paths[path_key][ep.method.lower()] = operation

        return {
            "openapi": "3.1.0",
            "info": {
                "title": service_name,
                "version": service_version,
                "description": f"Auto-generated OpenAPI spec for {service_name}",
            },
            "servers": [{"url": base_url}],
            "paths": paths,
            "components": {
                "securitySchemes": {
                    "ApiKeyAuth": {
                        "type": "apiKey",
                        "in": "header",
                        "name": "X-API-Key",
                    }
                }
            },
        }


class AgentJsonGenerator:
    """Generate /.well-known/agent.json manifest."""

    def generate(
        self,
        service_name: str,
        service_version: str,
        base_url: str,
        endpoints: list[ParsedEndpoint],
    ) -> dict:
        capabilities = []
        for ep in endpoints:
            capabilities.append(
                {
                    "method": ep.method,
                    "path": ep.path,
                    "summary": ep.summary,
                }
            )

        return {
            "schema_version": "1.0",
            "name": service_name,
            "version": service_version,
            "description": f"Agent-consumable API: {service_name}",
            "base_url": base_url,
            "auth": {
                "type": "api_key",
                "header": "X-API-Key",
            },
            "capabilities": capabilities,
            "documentation": {
                "llm_txt": f"{base_url}/llm.txt",
                "openapi": f"{base_url}/openapi.json",
            },
        }


# ---------------------------------------------------------------------------
# Protocol Engine
# ---------------------------------------------------------------------------


class ProtocolEngine:
    """
    Code-to-Discovery Pipeline.

    Takes raw source code and produces a complete agent-discoverable package:
    llm.txt + OpenAPI spec + agent.json + optional Oracle registration.
    """

    def __init__(self):
        self.parser = CodeParser()
        self.llm_gen = LlmTxtGenerator()
        self.openapi_gen = OpenApiGenerator()
        self.agent_json_gen = AgentJsonGenerator()
        self._generations: dict[str, GenerationResult] = {}

    async def generate(
        self,
        source_code: str,
        service_name: str,
        service_version: str = "1.0.0",
        base_url: str = "https://api.example.com",
        register_in_oracle: bool = False,
        oracle_instance=None,
        owner_wallet_id: str | None = None,
        auth_method: str | None = None,
        rate_limit: str | None = None,
    ) -> GenerationResult:
        """Run the full code-to-discovery pipeline."""
        gen_id = f"gen-{uuid.uuid4().hex[:12]}"
        warnings = []

        # Step 1: Parse endpoints from code
        endpoints, parse_notes = self.parser.parse_with_notes(source_code, service_name)
        warnings.extend(parse_notes)
        if not endpoints:
            warnings.append(
                "No endpoints detected in source code. Check decorator format."
            )

        # Step 2: Generate llm.txt
        llm_txt = self.llm_gen.generate(
            service_name=service_name,
            service_version=service_version,
            base_url=base_url,
            endpoints=endpoints,
            auth_method=auth_method,
            rate_limit=rate_limit,
        )

        # Step 3: Generate OpenAPI spec
        openapi_spec = self.openapi_gen.generate(
            service_name=service_name,
            service_version=service_version,
            base_url=base_url,
            endpoints=endpoints,
        )

        # Step 4: Generate agent.json
        agent_json = self.agent_json_gen.generate(
            service_name=service_name,
            service_version=service_version,
            base_url=base_url,
            endpoints=endpoints,
        )

        # Step 5: Register in Oracle (optional)
        registration_id = None
        if register_in_oracle and oracle_instance:
            try:
                crawl_result = await oracle_instance.crawl(base_url)
                # crawl() returns an IndexedAPI model (or None), not a dict.
                if crawl_result is None:
                    warnings.append("Oracle registration failed: service not indexed")
                else:
                    registration_id = crawl_result.api_id
            except Exception as e:
                warnings.append(f"Oracle registration failed: {str(e)}")

        result = GenerationResult(
            generation_id=gen_id,
            service_name=service_name,
            service_version=service_version,
            endpoints_parsed=len(endpoints),
            llm_txt=llm_txt,
            openapi_spec=openapi_spec,
            agent_json=agent_json,
            oracle_registration_id=registration_id,
            warnings=warnings,
            owner_wallet_id=owner_wallet_id,
        )

        self._generations[gen_id] = result
        logger.info(
            f"Protocol generation {gen_id}: {len(endpoints)} "
            f"endpoints for {service_name}"
        )
        return result

    async def get_generation(self, generation_id: str) -> GenerationResult | None:
        return self._generations.get(generation_id)

    async def list_generations(self) -> list[GenerationResult]:
        return list(self._generations.values())
