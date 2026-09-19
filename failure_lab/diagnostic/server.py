"""The self-serve diagnostic: "Agent Action Safety Check".

A visitor opens a page, runs a failure against a sandboxed agent integration,
and reads what the instruments counted. The page can tell them they do not need
the product, and does, because :mod:`failure_lab.diagnostic.answer` computes
that result from the same comparison objects the evidence bundle is built from.

What this server will not do, and why each refusal is structural rather than a
warning in the copy:

**It never talks to anything the operator did not explicitly allow.** The
sandbox is the only target. An external target requires two independent
authorizations that cannot substitute for one another: the operator starts the
server with ``allow_external_targets=True``, *and* the individual request
carries ``external_target_acknowledged``. Either alone is refused. The PRD's
"explicit opt-in" is not one flag, because one flag is a thing somebody turns
on once and forgets.

**It never accepts a credential.** The check endpoint has no field for one. The
verify endpoint takes a receipt bundle and a key document, and refuses a
submission whose content is credential-shaped before parsing it, because a
secret that reaches the parser has already been in memory, in a log buffer and
possibly in an error message.

**It never returns a document that has not been redacted.** Every response body
built from a run goes through :func:`failure_lab.evidence.redact`, the same
pass the evidence bundle uses. One pass, used twice, cannot drift.

**It bounds what one visitor can consume.** Runs are serialized behind a
semaphore, each visitor gets a token bucket, and the scenario selection is
capped -- a visitor cannot ask this server to run the slow tier.

**It never counts itself as a customer.** :class:`TrafficSource` is fixed at
construction and defaults to ``unknown``. ``human_customer`` has to be typed by
an operator who means it, and the PRD forbids synthetic traffic from ever
reaching conversion metrics.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import Route

from failure_lab import TEST_DEFINITION_VERSION, __version__
from failure_lab.diagnostic import pages
from failure_lab.diagnostic.answer import DiagnosticAnswer, build_answer
from failure_lab.evidence import REDACTED_KEY_PATTERN, redact
from failure_lab.telemetry import EventName, TelemetryClient, TelemetryRejected, TrafficSource
from failure_lab.verifier import KeySource, parse_key_document, verify

#: Scenarios a visitor may run. The fast tier only: a public endpoint that can
#: be made to run the slow tier is a public endpoint that can be made to burn a
#: machine. An operator who wants the whole suite runs the CLI.
PUBLIC_SCENARIOS: tuple[str, ...] = ("T01", "T02", "T03", "T06")

#: The default check, chosen because it is the one failure every agent
#: integration meets and the one where a correct baseline can win outright.
DEFAULT_SCENARIOS: tuple[str, ...] = ("T03", "T06")

#: How many results are kept addressable. Old ones fall off the end; nothing
#: here is a system of record.
MAX_RETAINED_RESULTS = 32

#: Requests per window, per client, for the endpoint that actually runs a lab.
RUN_RATE_LIMIT = 4
RUN_RATE_WINDOW_SECONDS = 300.0

#: Requests per window, per client, for the cheap endpoints.
READ_RATE_LIMIT = 120
READ_RATE_WINDOW_SECONDS = 60.0

#: Nothing submitted to /verify may be larger than this. A receipt bundle is a
#: few kilobytes; a megabyte of it is somebody else's problem being made ours.
MAX_SUBMISSION_BYTES = 256 * 1024

#: How long one check may run before it is abandoned.
RUN_TIMEOUT_SECONDS = 600.0

#: Text that must never be accepted from a visitor, whatever it is labelled as.
#: This is the *submission* guard, and it is deliberately stricter than the
#: redaction pass: redaction exists to keep a secret out of an artifact after
#: the fact, and this exists so the secret never arrives.
_CREDENTIAL_SHAPED = re.compile(
    r"(?i)"
    r"(?:-----BEGIN [A-Z ]*PRIVATE KEY-----)"
    r"|(?:\bsk-[A-Za-z0-9]{16,})"
    r"|(?:\bBearer\s+[A-Za-z0-9._~+/-]{16,})"
    r"|(?:\b(?:api[_-]?key|apikey|secret|password|passwd|private[_-]?key|"
    r"client[_-]?secret|access[_-]?token|refresh[_-]?token)\b\s*[:=]\s*\S{8,})"
)


class SubmissionRefused(ValueError):
    """A visitor's submission was refused before it was parsed."""

    def __init__(self, reason: str, *, status_code: int = 400) -> None:
        super().__init__(reason)
        self.reason = reason
        self.status_code = status_code


@dataclass
class DiagnosticSettings:
    """How this instance is allowed to behave.

    Every field that widens what the server may do defaults to the narrow
    value. There is no configuration file and no environment override: an
    operator who wants an external target has to pass it at construction, where
    it is visible in the command that started the process.
    """

    #: Whether an external target may be named at all. Off by default. On its
    #: own it still is not enough -- see :meth:`external_target_allowed`.
    allow_external_targets: bool = False
    #: The traffic source stamped on every telemetry event. Never inferred
    #: from a request: a visitor cannot make themselves count as a customer,
    #: and an internal agent driving this server cannot either.
    traffic_source: TrafficSource = TrafficSource.UNKNOWN
    #: Where telemetry and run directories go. A temporary directory when
    #: unset, which is the right default for a machine somebody is trying out.
    state_dir: Path | None = None
    #: Whether to record telemetry at all.
    telemetry: bool = True
    #: Scenario ids a visitor may select.
    allowed_scenarios: tuple[str, ...] = PUBLIC_SCENARIOS
    #: Concurrent lab runs. One, because a run boots a gateway and a sandbox
    #: and the honest answer to "can this serve a crowd" is "it is a
    #: diagnostic, not a service".
    max_concurrent_runs: int = 1

    def external_target_allowed(self, acknowledged: bool) -> bool:
        """Both authorizations, or no external request.

        The operator's flag says this deployment *may* be pointed outward. The
        request's acknowledgement says this particular call was meant to be.
        Requiring both means neither a forgotten flag nor a copied request body
        is sufficient on its own.
        """
        return bool(self.allow_external_targets and acknowledged)


@dataclass
class _Bucket:
    """One client's recent requests, for a fixed window."""

    hits: deque[float] = field(default_factory=deque)

    def allow(self, *, limit: int, window: float, now: float) -> bool:
        while self.hits and now - self.hits[0] > window:
            self.hits.popleft()
        if len(self.hits) >= limit:
            return False
        self.hits.append(now)
        return True


class _RateLimiter:
    """Fixed-window counters per client, bounded in size.

    The bound matters as much as the limit: a per-client dict that grows
    without one is itself the resource a visitor exhausts.
    """

    def __init__(self, *, max_clients: int = 4096) -> None:
        self._buckets: OrderedDict[str, _Bucket] = OrderedDict()
        self._max_clients = max_clients

    def allow(self, client: str, *, limit: int, window: float) -> bool:
        now = time.monotonic()
        bucket = self._buckets.get(client)
        if bucket is None:
            bucket = _Bucket()
            self._buckets[client] = bucket
            while len(self._buckets) > self._max_clients:
                self._buckets.popitem(last=False)
        self._buckets.move_to_end(client)
        return bucket.allow(limit=limit, window=window, now=now)


@dataclass
class _StoredResult:
    """One completed check, kept only long enough to be read back."""

    result_id: str
    created_at: float
    answer: DiagnosticAnswer
    environment: dict[str, Any]
    document: dict[str, Any]
    exit_status: int


def _client_key(request: Request) -> str:
    """A coarse client identity for rate limiting.

    The address is used for counting and is never written to telemetry, a log
    line or a result document. The PRD's privacy rule is that this surface does
    not collect who somebody is; a counter that forgets is not collection.
    """
    client = request.client
    return client.host if client and client.host else "unknown"


def _check_submission_text(raw: str) -> None:
    """Refuse anything credential-shaped before it is parsed."""
    if len(raw.encode("utf-8", "ignore")) > MAX_SUBMISSION_BYTES:
        raise SubmissionRefused(
            f"submission larger than {MAX_SUBMISSION_BYTES} bytes was refused "
            "without being read",
            status_code=413,
        )
    if _CREDENTIAL_SHAPED.search(raw):
        raise SubmissionRefused(
            "this submission looks like it contains a credential, so it was "
            "refused without being parsed. This check never needs an API key, "
            "a token or a private key. Send the receipt bundle only."
        )
    if REDACTED_KEY_PATTERN.search(raw):
        raise SubmissionRefused(
            "this submission contains a field whose name marks it as secret, "
            "so it was refused without being parsed. Remove it and resend; "
            "nothing here needs it."
        )


async def _read_json(request: Request) -> dict[str, Any]:
    body = await request.body()
    raw = body.decode("utf-8", "replace")
    if not raw.strip():
        return {}
    _check_submission_text(raw)
    try:
        parsed = json.loads(raw)
    except ValueError as exc:
        raise SubmissionRefused(f"body is not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise SubmissionRefused("body must be a JSON object")
    return parsed


class DiagnosticService:
    """The state one running diagnostic server owns."""

    def __init__(self, settings: DiagnosticSettings | None = None) -> None:
        self.settings = settings or DiagnosticSettings()
        self._results: OrderedDict[str, _StoredResult] = OrderedDict()
        self._limiter = _RateLimiter()
        self._runs = asyncio.Semaphore(max(1, self.settings.max_concurrent_runs))
        self._telemetry: TelemetryClient | None = None
        self._notes: list[str] = []

    # -- telemetry ---------------------------------------------------------

    def _telemetry_client(self) -> TelemetryClient | None:
        """Built lazily so a server that is never used writes nothing."""
        if not self.settings.telemetry:
            return None
        if self._telemetry is None:
            import tempfile

            directory = self.settings.state_dir or Path(
                tempfile.mkdtemp(prefix="failure-lab-diagnostic-")
            )
            directory.mkdir(parents=True, exist_ok=True)
            self._telemetry = TelemetryClient(directory, self.settings.traffic_source)
        return self._telemetry

    def record(self, name: EventName, **properties: Any) -> None:
        """Record an event, or record that the collector refused it.

        A telemetry write is never allowed to fail a visitor's request: the
        point of the surface is the measurement it returns, not the metric the
        vendor gets from it.
        """
        client = self._telemetry_client()
        if client is None:
            return
        try:
            client.record(name, **properties)
        except TelemetryRejected as exc:
            self._notes.append(f"telemetry event {name.value!r} refused: {exc}")

    # -- rate limiting -----------------------------------------------------

    def allow_read(self, request: Request) -> bool:
        return self._limiter.allow(
            _client_key(request), limit=READ_RATE_LIMIT, window=READ_RATE_WINDOW_SECONDS
        )

    def allow_run(self, request: Request) -> bool:
        return self._limiter.allow(
            _client_key(request), limit=RUN_RATE_LIMIT, window=RUN_RATE_WINDOW_SECONDS
        )

    # -- results -----------------------------------------------------------

    def store(self, stored: _StoredResult) -> None:
        self._results[stored.result_id] = stored
        while len(self._results) > MAX_RETAINED_RESULTS:
            self._results.popitem(last=False)

    def get(self, result_id: str) -> _StoredResult | None:
        return self._results.get(result_id)

    # -- the check itself --------------------------------------------------

    def select_scenarios(self, requested: Any) -> list[str]:
        """Validate a requested scenario list against the allowlist."""
        if requested is None:
            return list(DEFAULT_SCENARIOS)
        if isinstance(requested, str):
            requested = [requested]
        if not isinstance(requested, list) or not requested:
            raise SubmissionRefused("'scenarios' must be a non-empty list of test ids")
        allowed = set(self.settings.allowed_scenarios)
        chosen: list[str] = []
        for item in requested:
            if not isinstance(item, str):
                raise SubmissionRefused("'scenarios' must contain test ids as strings")
            test_id = item.strip().upper()
            if test_id not in allowed:
                raise SubmissionRefused(
                    f"{test_id} is not available on this surface. This server "
                    f"offers {', '.join(sorted(allowed))}; the full suite runs "
                    "from the command line."
                )
            if test_id not in chosen:
                chosen.append(test_id)
        return chosen

    def check_target(self, payload: dict[str, Any]) -> None:
        """Refuse an external target unless both authorizations are present."""
        target = payload.get("target") or payload.get("target_url")
        if target in (None, "", "sandbox"):
            return
        acknowledged = payload.get("external_target_acknowledged") is True
        if not self.settings.allow_external_targets:
            raise SubmissionRefused(
                "this server runs against its own sandbox only. It was not "
                "started with external targets enabled, so it will not send a "
                "request to a system you name here. Start it with "
                "allow_external_targets=True if you own the target and intend "
                "that.",
                status_code=403,
            )
        if not acknowledged:
            raise SubmissionRefused(
                "an external target also needs this request to carry "
                "'external_target_acknowledged': true, confirming you are "
                "authorized to send failure traffic at that system. The "
                "server-side flag alone is not treated as authorization for an "
                "individual request.",
                status_code=403,
            )
        raise SubmissionRefused(
            "external targets are authorized on this server but no external "
            "adapter is implemented, so nothing was sent. The check ran "
            "nothing rather than falling back to the sandbox and reporting a "
            "sandbox result under your target's name.",
            status_code=501,
        )

    async def run_check(self, scenarios: list[str]) -> _StoredResult:
        """Run the selected scenarios in the sandbox and build the answer."""
        from failure_lab.runner import run_lab

        async with self._runs:
            run = await asyncio.wait_for(
                run_lab(
                    test_ids=scenarios,
                    traffic_source=self.settings.traffic_source,
                    telemetry=False,
                    reproduction_command=(
                        "python -m failure_lab run --test " + " --test ".join(scenarios)
                    ),
                ),
                timeout=RUN_TIMEOUT_SECONDS,
            )

        answer = build_answer(run.comparisons)
        document = redact(
            {
                "result_id": run.run_id,
                "answer": answer.as_dict(),
                "environment": run.environment,
                "scenarios": run.verdict_rows(),
                "notes": run.notes,
                "errors": run.errors,
            }
        )
        stored = _StoredResult(
            result_id=run.run_id,
            created_at=time.time(),
            answer=answer,
            environment=dict(run.environment),
            document=document,
            exit_status=run.exit_status,
        )
        self.store(stored)
        return stored


# --------------------------------------------------------------------------- #
# Routes                                                                        #
# --------------------------------------------------------------------------- #


def _refusal(exc: SubmissionRefused) -> JSONResponse:
    return JSONResponse(
        {"error": "refused", "reason": exc.reason}, status_code=exc.status_code
    )


def _too_many(what: str) -> JSONResponse:
    return JSONResponse(
        {
            "error": "rate_limited",
            "reason": f"too many {what} from this client; try again shortly",
        },
        status_code=429,
    )


def create_app(settings: DiagnosticSettings | None = None) -> Starlette:
    """Build the diagnostic application."""
    service = DiagnosticService(settings)

    async def index(request: Request) -> Response:
        if not service.allow_read(request):
            return _too_many("requests")
        service.record(EventName.REPORT_VIEWED, surface="web", page="index")
        return HTMLResponse(
            pages.render_index(
                scenarios=list(service.settings.allowed_scenarios),
                defaults=list(DEFAULT_SCENARIOS),
                external_targets_enabled=service.settings.allow_external_targets,
            )
        )

    async def start_check(request: Request) -> Response:
        if not service.allow_run(request):
            return _too_many("checks")
        try:
            payload = await _read_json(request)
            service.check_target(payload)
            scenarios = service.select_scenarios(payload.get("scenarios"))
        except SubmissionRefused as exc:
            return _refusal(exc)

        started = time.monotonic()
        service.record(
            EventName.DIAGNOSTIC_STARTED,
            surface="web",
            scenario_count=len(scenarios),
            definition_version=TEST_DEFINITION_VERSION,
        )
        try:
            stored = await service.run_check(scenarios)
        except TimeoutError:
            service.record(
                EventName.DIAGNOSTIC_COMPLETED,
                surface="web",
                outcome="failure",
                error_kind="timeout",
            )
            return JSONResponse(
                {
                    "error": "timed_out",
                    "reason": (
                        "the check did not finish in time and was abandoned. "
                        "Nothing is reported, because a partial run is not a "
                        "result."
                    ),
                },
                status_code=504,
            )
        service.record(
            EventName.DIAGNOSTIC_COMPLETED,
            surface="web",
            outcome="success",
            scenario_count=len(scenarios),
            conclusion_kind=stored.answer.answer.value,
            duration_ms=round((time.monotonic() - started) * 1000),
        )

        wants_html = "text/html" in (request.headers.get("accept") or "")
        if wants_html:
            return HTMLResponse(
                pages.render_result(stored.answer, environment=stored.environment)
            )
        return JSONResponse(
            {"result_id": stored.result_id, "url": f"/check/{stored.result_id}"},
            status_code=201,
        )

    async def read_result(request: Request) -> Response:
        if not service.allow_read(request):
            return _too_many("requests")
        # Starlette matches routes in order and ``{result_id}`` happily
        # swallows a dotted suffix, so ``/check/<id>.json`` can arrive here
        # with the extension still attached to the id. Stripping it means the
        # two routes cannot shadow one another whatever order they are
        # declared in.
        result_id = request.path_params["result_id"]
        if result_id.endswith(".json"):
            result_id = result_id[: -len(".json")]
        stored = service.get(result_id)
        if stored is None:
            return JSONResponse(
                {
                    "error": "not_found",
                    "reason": (
                        "this result is not held any more. Results live in "
                        "memory only and are not a system of record; run the "
                        "check again."
                    ),
                },
                status_code=404,
            )
        service.record(
            EventName.REPORT_VIEWED,
            surface="web",
            page="result",
            report_format="json" if request.url.path.endswith(".json") else "html",
        )
        if request.url.path.endswith(".json"):
            return JSONResponse(stored.document)
        return HTMLResponse(
            pages.render_result(stored.answer, environment=stored.environment)
        )

    async def verify_page(request: Request) -> Response:
        if not service.allow_read(request):
            return _too_many("requests")
        service.record(EventName.REPORT_VIEWED, surface="web", page="verify")
        return HTMLResponse(pages.render_verify_form())

    async def verify_receipt(request: Request) -> Response:
        if not service.allow_read(request):
            return _too_many("requests")
        try:
            payload = await _read_json(request)
        except SubmissionRefused as exc:
            return _refusal(exc)

        bundle = payload.get("bundle") or payload.get("receipt")
        if not isinstance(bundle, dict):
            return _refusal(
                SubmissionRefused("send the portable receipt bundle as 'bundle'")
            )
        key_document = payload.get("keys")
        try:
            keys = parse_key_document(key_document) if key_document is not None else {}
        except ValueError as exc:
            return _refusal(SubmissionRefused(f"key document was not usable: {exc}"))

        pinned = payload.get("keys_are_pinned_out_of_band") is True
        observation = payload.get("downstream_observation")
        report = verify(
            bundle,
            keys,
            key_source=KeySource.OUT_OF_BAND_PIN if pinned else KeySource.ISSUER_ORIGIN,
            expected_issuer=payload.get("expected_issuer"),
            downstream_observation=observation if isinstance(observation, dict) else None,
        )
        document = redact(report.as_dict())
        if "text/html" in (request.headers.get("accept") or ""):
            return HTMLResponse(pages.render_verification(report))
        return JSONResponse(document)

    async def healthz(request: Request) -> Response:
        return JSONResponse(
            {
                "status": "ok",
                "lab_version": __version__,
                "test_definition_version": TEST_DEFINITION_VERSION,
                "external_targets_enabled": service.settings.allow_external_targets,
                "traffic_source": service.settings.traffic_source.value,
            }
        )

    app = Starlette(
        routes=[
            Route("/", index, methods=["GET"]),
            Route("/check", start_check, methods=["POST"]),
            # The .json route is declared first because Starlette matches in
            # order; the handler strips the suffix as well, so neither route
            # depends on the other's position.
            Route("/check/{result_id}.json", read_result, methods=["GET"]),
            Route("/check/{result_id}", read_result, methods=["GET"]),
            Route("/verify", verify_page, methods=["GET"]),
            Route("/verify", verify_receipt, methods=["POST"]),
            Route("/healthz", healthz, methods=["GET"]),
        ]
    )
    app.state.service = service
    return app


def serve(*, host: str = "127.0.0.1", port: int = 8080, **kwargs: Any) -> int:
    """Run the diagnostic server until interrupted."""
    import uvicorn

    settings = DiagnosticSettings(**kwargs) if kwargs else DiagnosticSettings()
    uvicorn.run(create_app(settings), host=host, port=port, log_level="info")
    return 0


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m failure_lab serve",
        description="Run the Agent Action Safety Check locally.",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument(
        "--allow-external-targets",
        action="store_true",
        help=(
            "Permit a request to name a target outside the sandbox. Each such "
            "request must ALSO carry external_target_acknowledged; this flag on "
            "its own authorizes nothing."
        ),
    )
    parser.add_argument(
        "--traffic-source",
        choices=[source.value for source in TrafficSource],
        default=TrafficSource.UNKNOWN.value,
        help=(
            "Recorded on every telemetry event. 'human_customer' is never "
            "inferred from a request and has to be typed here."
        ),
    )
    parser.add_argument("--state-dir", type=Path, default=None)
    parser.add_argument("--no-telemetry", action="store_true")
    args = parser.parse_args(argv)

    return serve(
        host=args.host,
        port=args.port,
        allow_external_targets=args.allow_external_targets,
        traffic_source=TrafficSource(args.traffic_source),
        state_dir=args.state_dir,
        telemetry=not args.no_telemetry,
    )


__all__ = [
    "DEFAULT_SCENARIOS",
    "DiagnosticService",
    "DiagnosticSettings",
    "MAX_SUBMISSION_BYTES",
    "PUBLIC_SCENARIOS",
    "SubmissionRefused",
    "create_app",
    "main",
    "serve",
]
