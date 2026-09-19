"""The HTTP surface: one page, one run at a time, on the loopback only.

Every refusal below is structural. A warning in the copy is a warning somebody
reads after the thing has already happened.

**Loopback only, and production refuses to boot at all.** :func:`serve` will
not bind anything but a loopback address, and :func:`create_app` calls
:func:`~failure_lab.diagnostic.runs.assert_not_production_like` against the
``ENVIRONMENT`` this process started with -- captured before
:func:`~failure_lab.gateway.boot_standalone_environment` can overwrite it with
``local``. A diagnostic that mints its own admin key, enables ``create_all``
and signs with an ephemeral seed has no business in a production process, and
the check that says so runs at construction, not at first request.

**The external-target code path is absent, not hidden.** With
``allow_external_targets`` false -- the default -- no handler object for it is
constructed and no route for it is registered, so the endpoint 404s because
there is nothing there. Turning the flag on does not enable an adapter either:
none is shipped, and the route that appears says so and sends nothing. The
choice to point failure traffic at somebody's system should cost more than a
boolean.

**One run at a time, and the second caller is told so.** The guard is a
synchronous check-and-set before the first ``await``, and a second run gets 429
rather than a queue slot. A diagnostic that queues is a diagnostic that can be
made to queue.

**No credential is accepted anywhere.** There is no field for one. A submission
whose bytes look like a credential is refused before it reaches ``json.loads``,
because a secret that reaches the parser has already been in memory, in a
buffer, and possibly in an error message.

**Nothing leaves without the redaction pass, and then a second look.** Every
run-derived body goes through :func:`failure_lab.evidence.redact`, and then
:meth:`DiagnosticService.guard` scans the finished bytes for the sandbox's own
secret values and refuses to serve the response if one survived. The bundle is
scanned a third time, by the evidence module, before it is written.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import tempfile
import time
from collections import OrderedDict, deque
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import (
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from starlette.routing import Route

from failure_lab import TEST_DEFINITION_VERSION, __version__
from failure_lab.configurations import Configuration
from failure_lab.diagnostic import pages, runs
from failure_lab.diagnostic.runs import RunRecord, RunRefused
from failure_lab.evidence import REDACTED_KEY_PATTERN, redact
from failure_lab.report import Comparison
from failure_lab.scenarios import SCENARIOS_BY_ID
from failure_lab.telemetry import (
    EventName,
    TelemetryClient,
    TelemetryRejected,
    TrafficSource,
    pseudonymous_subject,
)

logger = logging.getLogger("failure_lab.diagnostic")

#: Addresses this server will bind. Not a default -- a whitelist. The check is
#: in :func:`serve` so a wrapper cannot pass ``--host 0.0.0.0`` through.
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "[::1]"})

#: Run requests per client per window. Low, because one run occupies the whole
#: machine's sandbox for its duration.
RUN_RATE_LIMIT = 6
RUN_RATE_WINDOW_SECONDS = 300.0

#: Cheap endpoints: the page, the report, the stream.
READ_RATE_LIMIT = 240
READ_RATE_WINDOW_SECONDS = 60.0

#: Nothing posted here is bigger than a scenario list.
MAX_REQUEST_BYTES = 16 * 1024

#: How many finished runs stay addressable. Results live in memory and are not
#: a system of record; the evidence bundle is.
MAX_RETAINED_RUNS = 8

#: How long an event stream may stay open before the server closes it, even if
#: the run is somehow still going. Bounds a connection a client can hold.
STREAM_DEADLINE_SECONDS = runs.RUN_TIMEOUT_SECONDS + 60.0
#: How long the stream waits for a new step before writing a keep-alive.
STREAM_HEARTBEAT_SECONDS = 10.0

#: Refused before parsing, whatever it is labelled as. Deliberately stricter
#: than the redaction pass: redaction keeps a secret out of an artifact after
#: the fact, this keeps it from arriving.
_CREDENTIAL_SHAPED = re.compile(
    r"(?i)"
    r"(?:-----BEGIN [A-Z ]*PRIVATE KEY-----)"
    r"|(?:\bsk-[A-Za-z0-9]{16,})"
    r"|(?:\bBearer\s+[A-Za-z0-9._~+/-]{16,})"
    r"|(?:\b(?:api[_-]?key|apikey|secret|password|passwd|private[_-]?key|"
    r"client[_-]?secret|access[_-]?token|refresh[_-]?token)\b\s*[:=]\s*\S{8,})"
)


class SubmissionRefused(ValueError):
    """A request was refused before anything was parsed or executed."""

    def __init__(self, reason: str, *, status_code: int = 400) -> None:
        super().__init__(reason)
        self.reason = reason
        self.status_code = status_code


class ResponseWithheld(RuntimeError):
    """A finished response still contained a known secret, so it was not sent.

    The message never contains the value. This should be unreachable -- every
    document has already been through :func:`~failure_lab.evidence.redact` --
    and it exists because "should be unreachable" is not a guarantee.
    """


@dataclass
class DiagnosticSettings:
    """How this instance behaves. Every widening field defaults to narrow."""

    #: Whether an external-target route is constructed at all. See the module
    #: docstring: false means the handler does not exist, not that it is hidden.
    allow_external_targets: bool = False
    #: The traffic source for anything that is not a genuine browser session --
    #: the CLI, a test, a script. The PRD's rule is that synthetic traffic never
    #: reaches a conversion metric, so this is the default and it is not
    #: ``human_customer``.
    traffic_source: TrafficSource = TrafficSource.INTERNAL_TEST
    #: The source used when the request carries browser fetch metadata. Set to
    #: ``None`` to record every request under :attr:`traffic_source`.
    browser_traffic_source: TrafficSource | None = TrafficSource.HUMAN_CUSTOMER
    #: Where run directories, the telemetry log and the audit log go. A
    #: temporary directory when unset.
    state_dir: Path | None = None
    telemetry: bool = True
    allowed_scenarios: tuple[str, ...] = runs.PUBLIC_SCENARIOS
    max_retained_runs: int = MAX_RETAINED_RUNS


@dataclass
class _Bucket:
    hits: deque[float] = field(default_factory=deque)

    def allow(self, *, limit: int, window: float, now: float) -> bool:
        while self.hits and now - self.hits[0] > window:
            self.hits.popleft()
        if len(self.hits) >= limit:
            return False
        self.hits.append(now)
        return True


class _RateLimiter:
    """Fixed windows per client, bounded in size.

    One instance per endpoint class, never one shared by all of them: a
    visitor reading their own report must not be able to spend the budget that
    lets them start another run, and a budget shared between a cheap endpoint
    and an expensive one is the cheap endpoint's budget.

    The size bound matters as much as the rate: a per-client dict with no
    ceiling is itself the resource a visitor exhausts.
    """

    def __init__(self, *, max_clients: int = 2048) -> None:
        self._buckets: OrderedDict[str, _Bucket] = OrderedDict()
        self._max_clients = max_clients

    def allow(self, client: str, *, limit: int, window: float) -> bool:
        bucket = self._buckets.get(client)
        if bucket is None:
            bucket = _Bucket()
            self._buckets[client] = bucket
            while len(self._buckets) > self._max_clients:
                self._buckets.popitem(last=False)
        self._buckets.move_to_end(client)
        return bucket.allow(limit=limit, window=window, now=time.monotonic())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _client_key(request: Request) -> str:
    client = request.client
    return client.host if client and client.host else "unknown"


def _looks_like_browser(request: Request) -> bool:
    """Whether this request came from a browser actually rendering the page.

    Browsers send ``Sec-Fetch-*`` on every request and no HTTP client library
    does unless it is made to. That is the whole test, and it is deliberately
    the conservative direction: a browser misclassified as a script costs a
    funnel row, and a script misclassified as a human customer corrupts the one
    number the PRD says must never be corrupted.
    """
    headers = request.headers
    fetch_metadata = "sec-fetch-site" in headers or "sec-fetch-mode" in headers
    agent = headers.get("user-agent", "")
    return fetch_metadata and "mozilla" in agent.lower()


class DiagnosticService:
    """The state one running diagnostic server owns."""

    def __init__(self, settings: DiagnosticSettings | None = None) -> None:
        self.settings = settings or DiagnosticSettings()
        self.state_dir = Path(
            self.settings.state_dir
            or tempfile.mkdtemp(prefix="failure-lab-diagnostic-state-")
        )
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.audit_path = self.state_dir / "diagnostic-audit.jsonl"
        self._runs: OrderedDict[str, RunRecord] = OrderedDict()
        self._read_limiter = _RateLimiter()
        self._run_limiter = _RateLimiter()
        self._active_run_id: str | None = None
        self._task: asyncio.Task[Any] | None = None
        self._telemetry: dict[TrafficSource, TelemetryClient] = {}
        self.notes: list[str] = []

    # -- telemetry ---------------------------------------------------------

    def traffic_source_for(self, request: Request) -> TrafficSource:
        browser = self.settings.browser_traffic_source
        if browser is not None and _looks_like_browser(request):
            return browser
        return self.settings.traffic_source

    def record(self, source: TrafficSource, name: EventName, **properties: Any) -> None:
        """Record one event under the source the request established.

        A rejected event is noted and surfaced, never swallowed and never
        fatal: throwing away a completed diagnostic to protect the metric about
        the diagnostic is the wrong trade.
        """
        if not self.settings.telemetry:
            return
        client = self._telemetry.get(source)
        if client is None:
            client = TelemetryClient(self.state_dir, source)
            self._telemetry[source] = client
        try:
            client.record(name, **properties)
        except TelemetryRejected as exc:
            note = f"telemetry event {name.value!r} refused: {exc}"
            self.notes.append(note)
            logger.warning("%s", note)

    # -- audit -------------------------------------------------------------

    def audit(self, **entry: Any) -> None:
        """Append one line to the diagnostic's own execution log.

        "Who" is a pseudonym, not an address. This surface has no reason to
        learn who anybody is, and a trail that can only say "the same caller as
        the previous line" answers every operational question a loopback
        diagnostic actually has.
        """
        line = {"at": _now(), **entry}
        rendered = json.dumps(line, sort_keys=True, default=str)
        logger.info("diagnostic audit %s", rendered)
        try:
            with self.audit_path.open("a", encoding="utf-8") as handle:
                handle.write(rendered + "\n")
        except OSError as exc:  # pragma: no cover - the log is not the product
            self.notes.append(f"audit log could not be written: {exc}")

    def caller(self, request: Request) -> str:
        return pseudonymous_subject(
            _client_key(request), namespace="failure-lab-diagnostic"
        )

    # -- rate limiting -----------------------------------------------------

    def allow_read(self, request: Request) -> bool:
        return self._read_limiter.allow(
            _client_key(request), limit=READ_RATE_LIMIT, window=READ_RATE_WINDOW_SECONDS
        )

    def allow_run(self, request: Request) -> bool:
        return self._run_limiter.allow(
            _client_key(request), limit=RUN_RATE_LIMIT, window=RUN_RATE_WINDOW_SECONDS
        )

    # -- the response guard ------------------------------------------------

    def guard(self, body: str) -> str:
        """Refuse to serve a body that still contains a known secret."""
        for value in runs.known_secret_values():
            if len(value) >= 8 and value in body:
                raise ResponseWithheld(
                    "a response still contained a secret value of length "
                    f"{len(value)} after redaction and was not sent"
                )
        return body

    def html(self, body: str, *, status_code: int = 200) -> Response:
        return HTMLResponse(self.guard(body), status_code=status_code)

    def json(self, document: Any, *, status_code: int = 200) -> Response:
        text = json.dumps(redact(document), indent=2, sort_keys=True, default=str)
        return Response(
            self.guard(text), status_code=status_code, media_type="application/json"
        )

    # -- runs --------------------------------------------------------------

    @property
    def busy(self) -> bool:
        return self._active_run_id is not None

    def get(self, run_id: str) -> RunRecord | None:
        return self._runs.get(run_id)

    def begin(self, scenarios: list[str]) -> RunRecord:
        """Claim the single run slot. Synchronous, so there is no race to lose."""
        if self._active_run_id is not None:
            raise SubmissionRefused(
                "a check is already running on this machine. It boots a gateway, "
                "a downstream tool and a fault layer, and this surface runs one "
                "at a time on purpose. Wait for it to finish.",
                status_code=429,
            )
        record = RunRecord(
            run_id=runs.new_run_id(),
            scenarios=list(scenarios),
            seed=runs.new_seed(),
            created_at=time.monotonic(),
        )
        self._active_run_id = record.run_id
        self._runs[record.run_id] = record
        while len(self._runs) > self.settings.max_retained_runs:
            self._runs.popitem(last=False)
        return record

    def start(self, record: RunRecord, request: Request) -> None:
        caller = self.caller(request)
        source = self.traffic_source_for(request)
        self.audit(
            event="diagnostic_started",
            run_id=record.run_id,
            caller=caller,
            traffic_source=source.value,
            scenarios=list(record.scenarios),
            seed=record.seed,
        )
        self.record(
            source,
            EventName.DIAGNOSTIC_STARTED,
            surface="web",
            scenario_count=len(record.scenarios),
            definition_version=TEST_DEFINITION_VERSION,
            lab_version=__version__,
        )
        self._task = asyncio.create_task(self._drive(record, source, caller))

    async def _drive(
        self, record: RunRecord, source: TrafficSource, caller: str
    ) -> None:
        started = time.monotonic()
        try:
            await runs.execute(record, state_dir=self.state_dir)
        except asyncio.CancelledError:
            record.state = "failed"
            record.error = record.error or "the run was cancelled."
            raise
        except Exception as exc:  # noqa: BLE001 - reported, never raised at a visitor
            record.state = "failed"
            record.error = f"{type(exc).__name__}: {exc}"
            logger.exception("diagnostic run %s failed", record.run_id)
        finally:
            self._active_run_id = None
            record.wake()
            duration_ms = round((time.monotonic() - started) * 1000)
            self.audit(
                event="diagnostic_completed",
                run_id=record.run_id,
                caller=caller,
                scenarios=list(record.scenarios),
                state=record.state,
                exit_status=record.exit_status,
                answer=record.answer.answer.value if record.answer else None,
                duration_ms=duration_ms,
                error=record.error,
            )
            self._report_comparisons(source, record)
            self.record(
                source,
                EventName.DIAGNOSTIC_COMPLETED,
                surface="web",
                scenario_count=len(record.scenarios),
                outcome="success" if record.state == "complete" else "failure",
                duration_ms=duration_ms,
                **(
                    {"conclusion_kind": record.answer.answer.value}
                    if record.answer
                    else {}
                ),
            )

    def _report_comparisons(self, source: TrafficSource, record: RunRecord) -> None:
        """One comparison event per scenario, plus the baseline's own result.

        ``baseline_passed`` / ``baseline_failed`` are derived from the naive
        column's duplicate count -- the caller's kind of integration -- because
        that is the thing the PRD's funnel is actually asking about.
        """
        for comparison in record.comparisons:
            self.record(
                source,
                EventName.GATEWAY_COMPARISON_COMPLETED,
                test_id=comparison.test_id,
                verdict=comparison.verdict,
                conclusion_kind=comparison.conclusion.kind.value,
                matches_expectation=comparison.matches_expectation,
                surface="web",
            )
            baseline = _baseline_column(comparison)
            if baseline is None:
                continue
            self.record(
                source,
                EventName.BASELINE_FAILED
                if baseline.duplicate_effects > 0
                else EventName.BASELINE_PASSED,
                test_id=comparison.test_id,
                duplicate_effects=baseline.duplicate_effects,
                downstream_executions=baseline.downstream_effects,
                surface="web",
            )


def _baseline_column(comparison: Comparison) -> Any:
    for column in comparison.columns:
        if column.configuration == Configuration.DIRECT_NAIVE.value and column.ran:
            return column
    return None


# --------------------------------------------------------------------------- #
# Request helpers                                                               #
# --------------------------------------------------------------------------- #


async def _read_json(request: Request) -> dict[str, Any]:
    body = await request.body()
    if len(body) > MAX_REQUEST_BYTES:
        raise SubmissionRefused(
            f"a body larger than {MAX_REQUEST_BYTES} bytes was refused without "
            "being read. Nothing this surface accepts is that big.",
            status_code=413,
        )
    raw = body.decode("utf-8", "replace")
    if not raw.strip():
        return {}
    if _CREDENTIAL_SHAPED.search(raw) or REDACTED_KEY_PATTERN.search(raw):
        raise SubmissionRefused(
            "this submission looks like it carries a credential, so it was "
            "refused without being parsed. This check never needs an API key, a "
            "token or a private key; the sandbox mints its own."
        )
    try:
        parsed = json.loads(raw)
    except ValueError as exc:
        raise SubmissionRefused(f"body is not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise SubmissionRefused("body must be a JSON object")
    return parsed


def _refusal(exc: SubmissionRefused | RunRefused) -> JSONResponse:
    return JSONResponse(
        {"error": "refused", "reason": exc.reason}, status_code=exc.status_code
    )


def _rate_limited(what: str) -> JSONResponse:
    return JSONResponse(
        {
            "error": "rate_limited",
            "reason": f"too many {what} from this client; try again shortly",
        },
        status_code=429,
    )


def _not_found() -> JSONResponse:
    return JSONResponse(
        {
            "error": "not_found",
            "reason": (
                "no such run. Results are held in memory only, are not a system "
                "of record, and fall off the end as new ones arrive. Run the "
                "check again, or read the evidence bundle you downloaded."
            ),
        },
        status_code=404,
    )


def _sse(event: str, data: str) -> bytes:
    return f"event: {event}\ndata: {data}\n\n".encode()


def _refuse_target(payload: dict[str, Any]) -> None:
    """Refuse a target on the sandbox endpoint, whatever the server allows.

    This endpoint runs the sandbox. It does not grow an external mode because
    somebody put a URL in the body, even on an instance where external targets
    are permitted -- that is a different route, with a different authorization.
    """
    if payload.get("target") or payload.get("target_url"):
        raise SubmissionRefused(
            "this endpoint runs the built-in sandbox and has no target to "
            "choose. It will not send a request to a system you name here.",
            status_code=403,
        )


# --------------------------------------------------------------------------- #
# The application                                                               #
# --------------------------------------------------------------------------- #


def create_app(settings: DiagnosticSettings | None = None) -> Starlette:
    """Build the diagnostic application, refusing a production-like process."""
    runs.assert_not_production_like()
    service = DiagnosticService(settings)
    scenario_titles = {
        test_id: getattr(SCENARIOS_BY_ID[test_id], "title", "")
        for test_id in service.settings.allowed_scenarios
        if test_id in SCENARIOS_BY_ID
    }

    async def root(request: Request) -> Response:
        return RedirectResponse("/diagnostic", status_code=307)

    async def index(request: Request) -> Response:
        if not service.allow_read(request):
            return _rate_limited("requests")
        service.record(
            service.traffic_source_for(request),
            EventName.REPORT_VIEWED,
            surface="web",
            page="diagnostic",
        )
        return service.html(
            pages.render_index(
                scenarios=list(service.settings.allowed_scenarios),
                defaults=[
                    test_id
                    for test_id in runs.DEFAULT_SCENARIOS
                    if test_id in service.settings.allowed_scenarios
                ],
                scenario_titles=scenario_titles,
                external_targets_enabled=service.settings.allow_external_targets,
            )
        )

    async def start_run(request: Request) -> Response:
        if not service.allow_run(request):
            return _rate_limited("checks")
        try:
            payload = await _read_json(request)
            _refuse_target(payload)
            scenarios = runs.select_web_scenarios(
                payload.get("scenarios"), allowed=service.settings.allowed_scenarios
            )
            record = service.begin(scenarios)
        except (SubmissionRefused, RunRefused) as exc:
            return _refusal(exc)
        service.start(record, request)
        return JSONResponse(
            {
                "run_id": record.run_id,
                "scenarios": record.scenarios,
                "events_url": f"/diagnostic/run/{record.run_id}/events",
                "result_url": f"/diagnostic/run/{record.run_id}",
            },
            status_code=202,
        )

    async def stream_run(request: Request) -> Response:
        if not service.allow_read(request):
            return _rate_limited("requests")
        record = service.get(request.path_params["run_id"])
        if record is None:
            return _not_found()

        async def body() -> AsyncIterator[bytes]:
            deadline = time.monotonic() + STREAM_DEADLINE_SECONDS
            sent = 0
            yield b": open\n\n"
            while True:
                while sent < len(record.steps):
                    payload = pages.step_payload(record.steps[sent])
                    sent += 1
                    yield _sse("step", service.guard(payload))
                if record.finished:
                    event = "complete" if record.state == "complete" else "failed"
                    yield _sse(event, json.dumps(record.status_document()))
                    return
                if time.monotonic() > deadline:
                    yield _sse(
                        "failed",
                        json.dumps(
                            {
                                "run_id": record.run_id,
                                "state": "abandoned",
                                "error": (
                                    "the stream exceeded its deadline and was "
                                    "closed. The run has its own timeout."
                                ),
                            }
                        ),
                    )
                    return
                await record.wait_for_change(
                    after=sent, timeout=STREAM_HEARTBEAT_SECONDS
                )
                if sent >= len(record.steps) and not record.finished:
                    yield b": keep-alive\n\n"

        return StreamingResponse(
            body(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    async def read_run(request: Request) -> Response:
        if not service.allow_read(request):
            return _rate_limited("requests")
        raw_id = request.path_params["run_id"]
        wants_json = raw_id.endswith(".json")
        record = service.get(raw_id.removesuffix(".json"))
        if record is None:
            return _not_found()
        if not record.finished:
            if wants_json:
                return service.json(record.status_document(), status_code=409)
            return service.html(
                pages.render_error(
                    "Still running",
                    "This check has not finished. The page that started it is "
                    "streaming the run; reload when it says the run is complete.",
                    status=409,
                ),
                status_code=409,
            )
        service.record(
            service.traffic_source_for(request),
            EventName.REPORT_VIEWED,
            surface="web",
            page="result",
            report_format="json" if wants_json else "html",
        )
        if wants_json:
            return service.json(record.document or record.status_document())
        fragment = request.query_params.get("fragment") == "1"
        return service.html(pages.render_result(record, fragment=fragment))

    async def read_report(request: Request) -> Response:
        if not service.allow_read(request):
            return _rate_limited("requests")
        record = service.get(request.path_params["run_id"])
        if record is None or not record.report_html:
            return _not_found()
        service.record(
            service.traffic_source_for(request),
            EventName.REPORT_VIEWED,
            surface="web",
            page="comparison",
            report_format="html",
        )
        return service.html(pages.render_report(record))

    async def read_bundle(request: Request) -> Response:
        if not service.allow_read(request):
            return _rate_limited("requests")
        record = service.get(request.path_params["run_id"])
        if record is None:
            return _not_found()
        if record.archive is None:
            return service.json(
                {
                    "error": "no_bundle",
                    "reason": record.archive_note
                    or "this run produced no evidence bundle.",
                },
                status_code=404,
            )
        service.audit(
            event="evidence_downloaded",
            run_id=record.run_id,
            caller=service.caller(request),
            bytes=len(record.archive),
        )
        return Response(
            record.archive,
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{record.archive_name}"',
                "Cache-Control": "no-store",
            },
        )

    async def deployment(request: Request) -> Response:
        if not service.allow_read(request):
            return _rate_limited("requests")
        service.record(
            service.traffic_source_for(request),
            EventName.PRICING_VIEWED,
            surface="web",
            page="deployment",
        )
        service.audit(event="deployment_page_viewed", caller=service.caller(request))
        return service.html(pages.render_deployment())

    async def healthz(request: Request) -> Response:
        return JSONResponse(
            {
                "status": "ok",
                "lab_version": __version__,
                "test_definition_version": TEST_DEFINITION_VERSION,
                "startup_environment": runs.STARTUP_ENVIRONMENT,
                "external_targets_enabled": service.settings.allow_external_targets,
                "scenarios": list(service.settings.allowed_scenarios),
                "busy": service.busy,
                "notes": list(service.notes),
            }
        )

    @contextlib.asynccontextmanager
    async def lifespan(_: Starlette) -> AsyncIterator[None]:
        # Nothing to do on the way up: the sandbox boots on the first run, so
        # a server nobody uses never imports the application under test.
        yield
        await runs.shutdown_sandbox()

    routes = [
        Route("/", root, methods=["GET"]),
        Route("/diagnostic", index, methods=["GET"]),
        Route("/diagnostic/run", start_run, methods=["POST"]),
        Route("/diagnostic/run/{run_id}/events", stream_run, methods=["GET"]),
        Route("/diagnostic/run/{run_id}/report", read_report, methods=["GET"]),
        Route("/diagnostic/run/{run_id}/evidence.zip", read_bundle, methods=["GET"]),
        Route("/diagnostic/run/{run_id}", read_run, methods=["GET"]),
        Route("/diagnostic/deployment", deployment, methods=["GET"]),
        Route("/healthz", healthz, methods=["GET"]),
    ]

    if service.settings.allow_external_targets:
        # Constructed only on this branch. With the flag off there is no handler
        # object and no route, so the endpoint is absent rather than disabled --
        # which is the difference between a refusal and a feature flag.
        routes.append(
            Route("/diagnostic/external", _external_route(service), methods=["POST"])
        )

    app = Starlette(routes=routes, lifespan=lifespan)
    app.state.service = service
    return app


def _external_route(service: DiagnosticService) -> Any:
    """The external-target endpoint, which exists only when it was asked for.

    It still sends nothing. No external adapter is shipped in this build, and
    the honest answer to a request for one is an error naming what is missing --
    not a quiet fall back to the sandbox, which would report a sandbox result
    under somebody else's system's name.
    """

    async def external(request: Request) -> Response:
        if not service.allow_run(request):
            return _rate_limited("checks")
        try:
            payload = await _read_json(request)
        except SubmissionRefused as exc:
            return _refusal(exc)
        # The field is NOT called ``authorization_acknowledged``. This
        # surface refuses any submission whose text matches
        # ``REDACTED_KEY_PATTERN``, and that pattern matches "authorization" --
        # correctly, since an ``Authorization:`` header in a request body is
        # exactly what it exists to catch. Naming the field that way made this
        # endpoint unreachable: the only value that satisfied it was one the
        # guard refused first, so a caller following the error message below
        # got a contradiction. The guard is right; the name was wrong.
        if payload.get("external_target_acknowledged") is not True:
            return _refusal(
                SubmissionRefused(
                    "an external target needs this request to carry "
                    "'external_target_acknowledged': true, confirming you are "
                    "authorized to send failure traffic at that system. The "
                    "server-side flag is not treated as authorization for an "
                    "individual request.",
                    status_code=403,
                )
            )
        service.audit(
            event="external_target_refused",
            caller=service.caller(request),
            reason="no adapter in this build",
        )
        return _refusal(
            SubmissionRefused(
                "external targets are permitted on this server but no external "
                "adapter is compiled into this build, so nothing was sent. The "
                "check ran nothing rather than running the sandbox and reporting "
                "the result under your system's name.",
                status_code=501,
            )
        )

    return external


# --------------------------------------------------------------------------- #
# Entry points                                                                  #
# --------------------------------------------------------------------------- #


def serve(*, host: str = "127.0.0.1", port: int = 8080, **kwargs: Any) -> int:
    """Run the diagnostic until interrupted. Loopback addresses only."""
    if host not in LOOPBACK_HOSTS:
        raise ValueError(
            f"refusing to bind {host!r}: this diagnostic boots a gateway with an "
            "ephemeral signing key and an admin credential it mints itself, and "
            f"serves it unauthenticated. Bind one of {sorted(LOOPBACK_HOSTS)}."
        )
    import uvicorn

    settings = DiagnosticSettings(**kwargs) if kwargs else DiagnosticSettings()
    uvicorn.run(create_app(settings), host=host, port=port, log_level="info")
    return 0


def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        prog="python -m failure_lab serve",
        description="Run the Agent Action Safety Check on this machine.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="loopback addresses only")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument(
        "--allow-external-targets",
        action="store_true",
        help=(
            "Construct the external-target endpoint. Off by default, in which "
            "case no such handler exists. No external adapter is shipped, so "
            "turning this on still sends nothing."
        ),
    )
    parser.add_argument(
        "--traffic-source",
        choices=[source.value for source in TrafficSource],
        default=TrafficSource.INTERNAL_TEST.value,
        help=(
            "The source recorded for anything that is not a browser session. "
            "Defaults to internal_test so a script cannot count as a customer."
        ),
    )
    parser.add_argument(
        "--no-human-customer",
        action="store_true",
        help=(
            "Record browser sessions under --traffic-source too. Use it when "
            "the only browser pointed at this instance is yours."
        ),
    )
    parser.add_argument("--state-dir", type=Path, default=None)
    parser.add_argument("--no-telemetry", action="store_true")
    args = parser.parse_args(argv)

    try:
        return serve(
            host=args.host,
            port=args.port,
            allow_external_targets=args.allow_external_targets,
            traffic_source=TrafficSource(args.traffic_source),
            browser_traffic_source=(
                None if args.no_human_customer else TrafficSource.HUMAN_CUSTOMER
            ),
            state_dir=args.state_dir,
            telemetry=not args.no_telemetry,
        )
    except (ValueError, runs.ProductionRefused) as exc:
        sys.stderr.write(f"{exc}\n")
        return 2


__all__ = [
    "LOOPBACK_HOSTS",
    "MAX_RETAINED_RUNS",
    "DiagnosticService",
    "DiagnosticSettings",
    "ResponseWithheld",
    "SubmissionRefused",
    "create_app",
    "main",
    "serve",
]
