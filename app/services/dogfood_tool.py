"""Opt-in executable dogfood tool for live trust-loop demos.

When ``ENABLE_DOGFOOD_TOOL=true``, registers ``partner.notes.write`` as a
local MCP tool that appends a note to a JSONL file under permit control.

Default is off so production discovery stays empty of demo tools unless
ops explicitly enables the flag. This is independent of
``ENABLE_PROOF_SURFACES`` (which gates Phase9 / marketplace stubs).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from ..schemas.billing import ServiceCategory
from .service_registry import get_service_registry

logger = logging.getLogger(__name__)

DOGFOOD_TOOL_ID = "partner.notes.write"
DOGFOOD_TOOL_NAME = "Partner Notes Write"
DOGFOOD_NOTES_PATH = Path("data") / "dogfood_partner_notes.jsonl"
DOGFOOD_CREDITS_PER_UNIT = 2.0

_registered = False
_registration_lock = Lock()


def _write_note(text: str = "hello") -> dict[str, Any]:
    """Append one governed dogfood note (safe side effect: local JSONL)."""
    DOGFOOD_NOTES_PATH.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "text": text,
        "written_at": datetime.now(timezone.utc).isoformat(),
        "governed": True,
    }
    with DOGFOOD_NOTES_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")
    note_count = 0
    if DOGFOOD_NOTES_PATH.exists():
        note_count = sum(
            1
            for line in DOGFOOD_NOTES_PATH.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    return {
        "status": "ok",
        "tool": DOGFOOD_TOOL_ID,
        "note": entry,
        "notes_path": str(DOGFOOD_NOTES_PATH),
        "note_count": note_count,
    }


def register_dogfood_tool() -> None:
    """Register the executable dogfood tool in the local MCP registry."""
    global _registered
    if _registered:
        return

    with _registration_lock:
        if _registered:
            return
        registry = get_service_registry()
        registry.register_local(
            service_id=DOGFOOD_TOOL_ID,
            name=DOGFOOD_TOOL_NAME,
            description=(
                "Dogfood stand-in for one internal MCP tool. "
                "Appends a note to a local JSONL file under permit control. "
                "Opt-in via ENABLE_DOGFOOD_TOOL; not a production partner tool."
            ),
            category=ServiceCategory.AGENT_COMMS,
            func=_write_note,
            credits_per_unit=DOGFOOD_CREDITS_PER_UNIT,
            unit_name="call",
            require_permit=True,
        )
        _registered = True
        logger.info("Registered dogfood MCP tool: %s", DOGFOOD_TOOL_ID)


def unregister_dogfood_tool() -> None:
    """Remove the dogfood tool from the local registry."""
    global _registered
    registry = get_service_registry()
    with _registration_lock:
        registry.unregister_local(DOGFOOD_TOOL_ID)
        _registered = False


def sync_dogfood_tool_registration() -> None:
    """Register or unregister the dogfood tool to match ENABLE_DOGFOOD_TOOL.

    When the flag is off, only remove the tool if *this* module registered it.
    Scripts (``dogfood_trust_plane``) and tests may register the same id
    independently; discovery sync must not delete those registrations.
    """
    from ..core.config import get_settings

    if get_settings().ENABLE_DOGFOOD_TOOL:
        register_dogfood_tool()
    elif _registered:
        unregister_dogfood_tool()
