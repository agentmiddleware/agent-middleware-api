"""
Agent Oracle Infiltration — Service Layer
==========================================
Crawls agent directories, indexes external API capabilities,
computes compatibility scores, and registers our API in agent
networks to drive inbound discovery traffic.

The three pillars:
1. CRAWL  — Discover external APIs via /.well-known/agent.json, /llm.txt, OpenAPI specs
2. INDEX  — Extract capabilities, compute compatibility scores, build the network graph
3. REGISTER — Push our agent profile into external directories for inbound traffic

Production wiring:
- httpx/aiohttp for async crawling
- PostgreSQL + pgvector for capability embeddings
- Redis for crawl queue and rate limiting
- Scheduled workers for periodic re-crawls
"""

import asyncio
import uuid
import logging
import hashlib
from collections import defaultdict
from datetime import datetime, timezone

from ..schemas.oracle import (
    OracleStatus,
    DirectoryType,
    CompatibilityTier,
    IndexedCapability,
    IndexedAPI,
    RegistrationResult,
    VisibilityScore,
    NetworkGraphNode,
    NetworkGraphResponse,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Compatibility Engine
# ---------------------------------------------------------------------------

# Keywords that indicate high compatibility with our middleware
COMPATIBILITY_KEYWORDS = {
    "native": [
        "agent", "api", "headless", "programmatic", "machine-to-machine",
        "webhook", "mqtt", "iot", "telemetry", "media", "content",
        "scheduling", "automation", "b2a", "mcp",
    ],
    "compatible": [
        "rest", "json", "openapi", "oauth", "api-key", "webhook",
        "streaming", "async", "batch", "graphql",
    ],
    "bridgeable": [
        "gui", "dashboard", "web-app", "saas", "portal",
        "manual", "interactive", "form",
    ],
}

# Capability overlap categories
CAPABILITY_CATEGORIES = {
    "iot": ["device", "sensor", "mqtt", "coap", "zigbee", "protocol", "bridge"],
    "media": ["video", "image", "audio", "clip", "render", "caption", "stream"],
    "comms": ["message", "agent", "chat", "notification", "webhook", "queue"],
    "analytics": ["telemetry", "metric", "event", "anomaly", "monitor", "log"],
    "content": ["content", "post", "publish", "schedule", "social", "marketing"],
    "security": ["auth", "security", "scan", "vulnerability", "penetration", "audit"],
}


class CompatibilityEngine:
    """Computes how well an external API integrates with our middleware."""

    @staticmethod
    def compute_score(
        name: str,
        description: str,
        capabilities: list[dict],
    ) -> tuple[CompatibilityTier, float]:
        """
        Compute compatibility tier and score based on API metadata.

        Returns (tier, score) where score is 0.0-1.0.
        """
        text = f"{name} {description} ".lower()
        for cap in capabilities:
            text += f"{cap.get('name', '')} {cap.get('description', '')} "

        # Score based on keyword overlap
        native_hits = sum(1 for kw in COMPATIBILITY_KEYWORDS["native"] if kw in text)
        compat_hits = sum(1 for kw in COMPATIBILITY_KEYWORDS["compatible"] if kw in text)
        bridge_hits = sum(1 for kw in COMPATIBILITY_KEYWORDS["bridgeable"] if kw in text)

        total_keywords = len(COMPATIBILITY_KEYWORDS["native"]) + len(COMPATIBILITY_KEYWORDS["compatible"])
        raw_score = (native_hits * 2 + compat_hits) / max(total_keywords, 1)
        score = min(1.0, raw_score)

        # Determine tier
        if native_hits >= 4:
            tier = CompatibilityTier.NATIVE
        elif native_hits >= 2 or compat_hits >= 3:
            tier = CompatibilityTier.COMPATIBLE
        elif bridge_hits >= 2 or compat_hits >= 1:
            tier = CompatibilityTier.BRIDGEABLE
        else:
            tier = CompatibilityTier.INCOMPATIBLE

        return tier, round(score, 3)

    @staticmethod
    def categorize_capabilities(capabilities: list[dict]) -> dict[str, list[str]]:
        """Map capabilities to our category taxonomy."""
        result: dict[str, list[str]] = defaultdict(list)
        for cap in capabilities:
            text = f"{cap.get('name', '')} {cap.get('description', '')}".lower()
            for category, keywords in CAPABILITY_CATEGORIES.items():
                if any(kw in text for kw in keywords):
                    result[category].append(cap.get("name", "unknown"))
        return dict(result)


# ---------------------------------------------------------------------------
# Crawl Simulator
# ---------------------------------------------------------------------------

# Simulated external API directory (production: real HTTP crawling)
SIMULATED_DIRECTORY: list[dict] = [
    {
        "url": "https://api.openai.com",
        "name": "OpenAI API",
        "description": "Large language model API with GPT-4, embeddings, and assistants.",
        "directory_type": DirectoryType.OPENAPI,
        "capabilities": [
            {"name": "chat-completion", "description": "Generate text with LLMs", "endpoint": "/v1/chat/completions", "method": "POST"},
            {"name": "embeddings", "description": "Generate text embeddings", "endpoint": "/v1/embeddings", "method": "POST"},
            {"name": "assistants", "description": "Programmatic agent creation and management", "endpoint": "/v1/assistants", "method": "POST"},
            {"name": "function-calling", "description": "Structured tool use for agents", "endpoint": "/v1/chat/completions", "method": "POST"},
        ],
    },
    {
        "url": "https://api.anthropic.com",
        "name": "Anthropic API",
        "description": "Claude models with tool use, MCP integration, and agent-native features.",
        "directory_type": DirectoryType.OPENAPI,
        "capabilities": [
            {"name": "messages", "description": "Generate responses with Claude models", "endpoint": "/v1/messages", "method": "POST"},
            {"name": "tool-use", "description": "Structured tool calling for agent workflows", "endpoint": "/v1/messages", "method": "POST"},
            {"name": "mcp-integration", "description": "Model Context Protocol server support", "endpoint": "/v1/messages", "method": "POST"},
            {"name": "batch-api", "description": "Async batch processing for high-volume agent tasks", "endpoint": "/v1/messages/batches", "method": "POST"},
        ],
    },
    {
        "url": "https://api.stripe.com",
        "name": "Stripe API",
        "description": "Payment processing, billing, and financial infrastructure for the internet.",
        "directory_type": DirectoryType.OPENAPI,
        "capabilities": [
            {"name": "payments", "description": "Process payments programmatically", "endpoint": "/v1/payment_intents", "method": "POST"},
            {"name": "subscriptions", "description": "Recurring billing and subscription management", "endpoint": "/v1/subscriptions", "method": "POST"},
            {"name": "webhooks", "description": "Event-driven webhook notifications", "endpoint": "/v1/webhook_endpoints", "method": "POST"},
            {"name": "usage-billing", "description": "Metered API billing for agent consumption", "endpoint": "/v1/billing/meters", "method": "POST"},
        ],
    },
    {
        "url": "https://api.twilio.com",
        "name": "Twilio API",
        "description": "Communication APIs for messaging, voice, and video.",
        "directory_type": DirectoryType.OPENAPI,
        "capabilities": [
            {"name": "sms", "description": "Send and receive SMS messages programmatically", "endpoint": "/2010-04-01/Accounts/{sid}/Messages", "method": "POST"},
            {"name": "voice", "description": "Programmable voice calls", "endpoint": "/2010-04-01/Accounts/{sid}/Calls", "method": "POST"},
            {"name": "webhooks", "description": "Event webhooks for message status", "endpoint": "/v1/webhooks", "method": "POST"},
        ],
    },
    {
        "url": "https://api.github.com",
        "name": "GitHub API",
        "description": "REST and GraphQL API for repositories, issues, pull requests, and automation.",
        "directory_type": DirectoryType.OPENAPI,
        "capabilities": [
            {"name": "repositories", "description": "Repository management and code access", "endpoint": "/repos/{owner}/{repo}", "method": "GET"},
            {"name": "pull-requests", "description": "Automated PR creation and review", "endpoint": "/repos/{owner}/{repo}/pulls", "method": "POST"},
            {"name": "actions", "description": "CI/CD pipeline automation", "endpoint": "/repos/{owner}/{repo}/actions", "method": "GET"},
            {"name": "webhooks", "description": "Repository event notifications", "endpoint": "/repos/{owner}/{repo}/hooks", "method": "POST"},
        ],
    },
    {
        "url": "https://api.cloudflare.com",
        "name": "Cloudflare API",
        "description": "Edge computing, DNS, CDN, and security for agent-deployed infrastructure.",
        "directory_type": DirectoryType.OPENAPI,
        "capabilities": [
            {"name": "workers", "description": "Edge compute for agent workloads", "endpoint": "/client/v4/accounts/{id}/workers/scripts", "method": "PUT"},
            {"name": "dns", "description": "Programmatic DNS management", "endpoint": "/client/v4/zones/{id}/dns_records", "method": "POST"},
            {"name": "r2-storage", "description": "S3-compatible object storage", "endpoint": "/client/v4/accounts/{id}/r2/buckets", "method": "POST"},
        ],
    },
]


class CrawlEngine:
    """
    Crawls external API directories and extracts metadata.
    Production: async HTTP client with rate limiting, retry logic,
    and respect for robots.txt / crawl-delay headers.
    """

    def __init__(self):
        self._compatibility = CompatibilityEngine()

    async def crawl_target(
        self,
        url: str,
        directory_type: DirectoryType,
        tags: list[str],
    ) -> IndexedAPI | None:
        """Crawl a URL and extract API metadata."""
        # Simulate network crawl (production: real HTTP requests)
        match = next((d for d in SIMULATED_DIRECTORY if d["url"] == url), None)

        if match:
            # Use simulated data
            capabilities = match["capabilities"]
            name = match["name"]
            description = match["description"]
        else:
            # Generate synthetic metadata for unknown URLs
            domain = url.split("//")[-1].split("/")[0]
            name = f"{domain.split('.')[0].title()} API"
            description = f"API service discovered at {domain}"
            capabilities = [
                {"name": "api-access", "description": f"REST API at {domain}", "endpoint": "/", "method": "GET"},
            ]

        # Compute compatibility
        tier, score = self._compatibility.compute_score(name, description, capabilities)

        api_id = hashlib.sha256(url.encode()).hexdigest()[:16]

        indexed_caps = [
            IndexedCapability(
                name=c["name"],
                description=c["description"],
                endpoint=c.get("endpoint"),
                method=c.get("method"),
            )
            for c in capabilities
        ]

        return IndexedAPI(
            api_id=api_id,
            url=url,
            name=name,
            description=description,
            directory_type=directory_type,
            capabilities=indexed_caps,
            compatibility_tier=tier,
            compatibility_score=score,
            tags=tags,
            last_crawled=datetime.now(timezone.utc),
            status=OracleStatus.INDEXED,
        )


# ---------------------------------------------------------------------------
# Registration Engine
# ---------------------------------------------------------------------------

# Our API profile for registration
OUR_PROFILE = {
    "name": "Agent-Native Middleware API",
    "description": (
        "Headless B2A middleware: IoT protocol bridging, autonomous code repair, "
        "programmatic media distribution, agent-to-agent comms, content factory "
        "with 1-to-20 multiplication, and red team security scanning."
    ),
    "url": "https://api.yourdomain.com",
    "capabilities": [
        "iot-protocol-bridging",
        "autonomous-code-repair",
        "programmatic-media-distribution",
        "agent-to-agent-messaging",
        "content-factory-scheduling",
        "live-campaign-orchestration",
        "red-team-security-swarm",
    ],
    "auth": {"type": "api_key", "header": "X-API-Key"},
    "discovery": {
        "well_known": "/.well-known/agent.json",
        "llm_txt": "/llm.txt",
        "openapi": "/openapi.json",
    },
}


class RegistrationEngine:
    """
    Registers our API in external agent directories.
    Production: actual HTTP POST/PUT to directory registration endpoints.
    """

    async def register(
        self,
        directory_url: str,
        directory_type: DirectoryType,
        custom_payload: dict | None = None,
        profile_overrides: dict | None = None,
    ) -> RegistrationResult:
        """Register our API with an external directory."""
        profile = {**OUR_PROFILE}
        if profile_overrides:
            profile.update(profile_overrides)

        # Simulate registration (production: real HTTP requests)
        # For now, all registrations succeed
        registration_id = str(uuid.uuid4())[:12]

        logger.info(f"Registered with {directory_url} ({directory_type.value})")

        return RegistrationResult(
            directory_url=directory_url,
            directory_type=directory_type,
            status=OracleStatus.REGISTERED,
            registration_id=registration_id,
            message=f"Successfully registered as '{profile['name']}' in {directory_type.value} directory.",
        )


# ---------------------------------------------------------------------------
# Oracle Store
# ---------------------------------------------------------------------------

class OracleStore:
    """In-memory store for crawl targets, indexed APIs, and registrations."""

    def __init__(self):
        self._targets: dict[str, dict] = {}
        self._indexed: dict[str, IndexedAPI] = {}
        self._registrations: list[RegistrationResult] = []
        self._discovery_hits: int = 0
        self._referrers: dict[str, int] = defaultdict(int)
        self._lock = asyncio.Lock()

    async def store_target(self, target_id: str, data: dict):
        async with self._lock:
            self._targets[target_id] = data

    async def get_target(self, target_id: str) -> dict | None:
        return self._targets.get(target_id)

    async def store_indexed(self, api: IndexedAPI):
        async with self._lock:
            self._indexed[api.api_id] = api

    async def get_indexed(self, api_id: str) -> IndexedAPI | None:
        return self._indexed.get(api_id)

    async def list_indexed(
        self,
        tier: CompatibilityTier | None = None,
        directory_type: DirectoryType | None = None,
    ) -> list[IndexedAPI]:
        apis = list(self._indexed.values())
        if tier:
            apis = [a for a in apis if a.compatibility_tier == tier]
        if directory_type:
            apis = [a for a in apis if a.directory_type == directory_type]
        return sorted(apis, key=lambda a: a.compatibility_score, reverse=True)

    async def store_registration(self, result: RegistrationResult):
        async with self._lock:
            self._registrations.append(result)

    async def get_registrations(self) -> list[RegistrationResult]:
        return list(self._registrations)

    async def record_discovery_hit(self, referrer: str = "direct"):
        async with self._lock:
            self._discovery_hits += 1
            self._referrers[referrer] += 1

    async def get_stats(self) -> dict:
        return {
            "targets_crawled": len(self._targets),
            "apis_indexed": len(self._indexed),
            "registrations": len(self._registrations),
            "discovery_hits": self._discovery_hits,
            "top_referrers": dict(
                sorted(self._referrers.items(), key=lambda x: x[1], reverse=True)[:10]
            ),
        }


# ---------------------------------------------------------------------------
# Agent Oracle Orchestrator
# ---------------------------------------------------------------------------

class AgentOracle:
    """
    Top-level orchestrator for Agent Oracle Infiltration.

    Three operations:
    1. crawl()    — Discover and index external APIs
    2. register() — Push our profile into agent directories
    3. score()    — Compute our visibility across the agent network
    """

    def __init__(self):
        self.store = OracleStore()
        self.crawler = CrawlEngine()
        self.registrar = RegistrationEngine()

    async def crawl(
        self,
        url: str,
        directory_type: DirectoryType = DirectoryType.WELL_KNOWN,
        tags: list[str] | None = None,
        priority: int = 5,
    ) -> IndexedAPI | None:
        """Crawl a URL, index it, and compute compatibility."""
        target_id = str(uuid.uuid4())

        await self.store.store_target(target_id, {
            "target_id": target_id,
            "url": url,
            "directory_type": directory_type.value,
            "status": OracleStatus.CRAWLING.value,
            "queued_at": datetime.now(timezone.utc).isoformat(),
        })

        # Execute crawl
        indexed = await self.crawler.crawl_target(url, directory_type, tags or [])

        if indexed:
            await self.store.store_indexed(indexed)
            # Update target status
            target = await self.store.get_target(target_id)
            if target:
                target["status"] = OracleStatus.INDEXED.value
                target["api_id"] = indexed.api_id

        return indexed

    async def batch_crawl(self, urls: list[str]) -> list[IndexedAPI]:
        """Crawl multiple URLs concurrently."""
        tasks = [self.crawl(url) for url in urls]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return [r for r in results if isinstance(r, IndexedAPI)]

    async def register_in_directories(
        self,
        targets: list[dict],
        profile_overrides: dict | None = None,
    ) -> list[RegistrationResult]:
        """Register our API in multiple external directories."""
        results = []
        for target in targets:
            result = await self.registrar.register(
                directory_url=target["directory_url"],
                directory_type=DirectoryType(target["directory_type"]),
                custom_payload=target.get("registration_payload"),
                profile_overrides=profile_overrides,
            )
            await self.store.store_registration(result)
            results.append(result)
        return results

    async def compute_visibility(self) -> VisibilityScore:
        """Compute our overall visibility score across agent networks."""
        stats = await self.store.get_stats()
        await self.store.get_registrations()
        indexed_apis = await self.store.list_indexed()

        # Compute compatibility distribution
        compat_map: dict[str, int] = defaultdict(int)
        for api in indexed_apis:
            compat_map[api.compatibility_tier.value] += 1

        # Compute visibility score (0-100)
        reg_score = min(40, stats["registrations"] * 10)  # Up to 40 pts for registrations
        index_score = min(30, stats["apis_indexed"] * 5)    # Up to 30 pts for indexed APIs
        discovery_score = min(30, stats["discovery_hits"] * 3)  # Up to 30 pts for discovery hits
        overall = min(100.0, float(reg_score + index_score + discovery_score))

        # Generate recommendations
        recommendations = []
        if stats["registrations"] < 3:
            recommendations.append(
                "Register in more agent directories to increase inbound discovery. "
                "Target: /.well-known/agent.json directories, MCP server listings, and plugin stores."
            )
        if stats["apis_indexed"] < 5:
            recommendations.append(
                "Crawl more external APIs to build your network graph. "
                "Focus on APIs with 'native' or 'compatible' tiers for integration partnerships."
            )
        native_count = compat_map.get("native", 0)
        if native_count < 2:
            recommendations.append(
                "Seek out more agent-native APIs (those with /llm.txt, /.well-known/agent.json). "
                "These are your highest-value integration partners."
            )
        if stats["discovery_hits"] == 0:
            recommendations.append(
                "No inbound discovery traffic yet. Ensure your /.well-known/agent.json and "
                "/llm.txt are publicly accessible and register in at least 3 directories."
            )

        # Top referrers
        top_referrers = [
            {"directory": k, "hits": v}
            for k, v in sorted(
                stats.get("top_referrers", {}).items(),
                key=lambda x: x[1],
                reverse=True,
            )[:5]
        ]

        return VisibilityScore(
            overall_score=overall,
            directories_registered=stats["registrations"],
            directories_crawled=stats["targets_crawled"],
            inbound_discovery_requests=stats["discovery_hits"],
            top_referrers=top_referrers,
            compatibility_map=dict(compat_map),
            recommendations=recommendations,
        )

    async def get_network_graph(self) -> NetworkGraphResponse:
        """Build a network graph of all indexed APIs centered on our API."""
        indexed = await self.store.list_indexed()
        registrations = await self.store.get_registrations()

        nodes: list[NetworkGraphNode] = []
        edges: list[dict] = []

        # Our API is the center node
        self_node = NetworkGraphNode(
            node_id="self",
            name="Agent-Native Middleware API",
            url="https://api.yourdomain.com",
            node_type="self",
            connections=[],
        )
        nodes.append(self_node)

        # Add indexed APIs
        for api in indexed:
            node = NetworkGraphNode(
                node_id=api.api_id,
                name=api.name,
                url=api.url,
                node_type="indexed_api",
                compatibility_tier=api.compatibility_tier,
                connections=["self"],
            )
            nodes.append(node)
            self_node.connections.append(api.api_id)
            edges.append({
                "source": "self",
                "target": api.api_id,
                "relationship": "indexed",
                "compatibility": api.compatibility_tier.value,
                "score": api.compatibility_score,
            })

        # Add registered directories
        for reg in registrations:
            reg_id = f"dir-{hashlib.sha256(reg.directory_url.encode()).hexdigest()[:8]}"
            if not any(n.node_id == reg_id for n in nodes):
                node = NetworkGraphNode(
                    node_id=reg_id,
                    name=reg.directory_url.split("//")[-1].split("/")[0],
                    url=reg.directory_url,
                    node_type="directory",
                    connections=["self"],
                )
                nodes.append(node)
                self_node.connections.append(reg_id)
                edges.append({
                    "source": "self",
                    "target": reg_id,
                    "relationship": "registered",
                })

        return NetworkGraphResponse(
            nodes=nodes,
            edges=edges,
            total_nodes=len(nodes),
            total_edges=len(edges),
            center_node="self",
        )

    async def record_discovery(self, referrer: str = "direct"):
        """Record an inbound discovery hit (called when agents find us)."""
        await self.store.record_discovery_hit(referrer)
