"""Bearer-only, wallet-scoped read surfaces for operator insight evidence."""

from __future__ import annotations

import asyncio
import io
import json
import tempfile
import time
import zipfile
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated, AsyncIterator, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.oidc_iga import EnterprisePrincipal
from app.db.database import get_session_factory
from app.services.operation_insights.auth import (
    authorize_scope,
    get_reporting_principal,
    reporting_read_transaction,
)
from app.services.operation_insights.contracts import (
    AccountMapping,
    Limits,
    TimeBasis,
    Window,
)
from app.services.operation_insights.export import (
    InsightExportTimeout,
    build_report,
    report_json_bytes,
    write_bundle,
)


router = APIRouter(prefix="/v1/operator/insights", tags=["Operator Insights"])


async def _report_session() -> AsyncIterator[AsyncSession]:
    try:
        factory = get_session_factory()
    except RuntimeError:
        raise HTTPException(
            status_code=503, detail="insight_storage_unavailable"
        ) from None
    async with factory() as session:
        yield session


def _window(as_of: datetime, days: Literal[7, 30], time_basis: TimeBasis) -> Window:
    try:
        return Window(as_of - timedelta(days=days), as_of, time_basis)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="invalid_insight_window") from None


def _unavailable() -> HTTPException:
    return HTTPException(status_code=503, detail="insight_report_unavailable")


def _request_deadline(limits: Limits) -> float:
    return asyncio.get_running_loop().time() + limits.seconds


@asynccontextmanager
async def _bounded_read(session: AsyncSession, deadline: float) -> AsyncIterator[None]:
    async with asyncio.timeout_at(deadline):
        async with reporting_read_transaction(session):
            yield


@router.get("/report")
async def get_insight_report(
    wallet_ids: Annotated[list[str], Query(alias="wallet_id")],
    as_of: datetime,
    days: Literal[7, 30],
    time_basis: TimeBasis,
    principal: Annotated[EnterprisePrincipal, Depends(get_reporting_principal)],
    session: Annotated[AsyncSession, Depends(_report_session)],
    include_unknown_wallet_counts: bool = False,
    format: Literal["json", "csv"] = "json",
) -> Response:
    """Return canonical JSON or a ZIP of linked CSV files and its manifest."""
    window = _window(as_of, days, time_basis)
    limits = Limits()
    deadline = _request_deadline(limits)
    try:
        async with _bounded_read(session, deadline):
            scope = await authorize_scope(
                principal, frozenset(wallet_ids), include_unknown_wallet_counts, session
            )
            # No verified account mapping is shipped with the reader. Unknown
            # attribution remains unknown until a governed mapping is supplied.
            mapping = AccountMapping(version="unverified", intervals=())
            report = await build_report(scope, window, limits, mapping, session)
            if format == "json":
                content = report_json_bytes(
                    report, scope=scope, session=session, deadline=deadline
                )
                return Response(
                    content,
                    media_type="application/json",
                    headers={"Cache-Control": "no-store"},
                )
            with tempfile.TemporaryDirectory(prefix="amw-insights-") as parent:
                directory = Path(parent) / "bundle"
                write_bundle(
                    report,
                    directory,
                    scope=scope,
                    session=session,
                    deadline=deadline,
                )
                buffer = io.BytesIO()
                with zipfile.ZipFile(
                    buffer, mode="w", compression=zipfile.ZIP_DEFLATED
                ) as archive:
                    for path in sorted(directory.iterdir()):
                        if time.monotonic() >= deadline:
                            raise InsightExportTimeout("insight_export_time_limit")
                        archive.write(path, arcname=path.name)
                if time.monotonic() >= deadline:
                    raise InsightExportTimeout("insight_export_time_limit")
                return Response(
                    buffer.getvalue(),
                    media_type="application/zip",
                    headers={
                        "Cache-Control": "no-store",
                        "Content-Disposition": f'attachment; filename="{report.report_id}.zip"',
                    },
                )
    except (InsightExportTimeout, TimeoutError):
        raise _unavailable() from None


@router.get("/operations/{operation_id}")
async def get_operation_insight(
    operation_id: str,
    wallet_id: str,
    as_of: datetime,
    days: Literal[7, 30],
    time_basis: TimeBasis,
    principal: Annotated[EnterprisePrincipal, Depends(get_reporting_principal)],
    session: Annotated[AsyncSession, Depends(_report_session)],
) -> Response:
    """Look up an ID only after the exact requested wallet is authorized."""
    window = _window(as_of, days, time_basis)
    limits = Limits()
    deadline = _request_deadline(limits)
    try:
        async with _bounded_read(session, deadline):
            scope = await authorize_scope(
                principal, frozenset({wallet_id}), False, session
            )
            mapping = AccountMapping(version="unverified", intervals=())
            report = await build_report(scope, window, limits, mapping, session)
            payload = json.loads(
                report_json_bytes(
                    report, scope=scope, session=session, deadline=deadline
                )
            )
            selected = next(
                (
                    item
                    for item in payload["operations"]
                    if item["operation_id"] == operation_id
                ),
                None,
            )
            if selected is None:
                if (
                    report.coverage.truncated
                    or not report.coverage.enumeration_complete
                ):
                    raise _unavailable()
                raise HTTPException(status_code=404, detail="operation_not_found")
            refs = {
                (
                    ref["source"],
                    ref["source_id"],
                    ref["wallet_id"],
                    ref["ownership_epoch_id"],
                    ref["original_operation_anchor_id"],
                )
                for ref in selected["evidence_refs"]
            }
            evidence = [
                row
                for row in payload["evidence"]
                if (
                    row["source"],
                    row["source_id"],
                    row["wallet_id"],
                    row["ownership_epoch_id"],
                    row["original_operation_anchor_id"],
                )
                in refs
            ]
            return Response(
                json.dumps(
                    {
                        "schema_version": payload["schema_version"],
                        "report_id": payload["report_id"],
                        "snapshot_cutoff": payload["snapshot_cutoff"],
                        "coverage": payload["coverage"],
                        "operation": selected,
                        "evidence": evidence,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                media_type="application/json",
                headers={"Cache-Control": "no-store"},
            )
    except (InsightExportTimeout, TimeoutError):
        raise _unavailable() from None
