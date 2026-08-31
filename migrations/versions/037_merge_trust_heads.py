"""Merge the current main and transaction-integrity migration branches.

Revision ID: 037_merge_trust_heads
Revises: 034_permit_call_reservations, 036_permit_request_hash_anchor
Create Date: 2026-08-31
"""

from __future__ import annotations

from typing import Union


revision: str = "037_merge_trust_heads"
down_revision: Union[str, tuple[str, ...], None] = (
    "034_permit_call_reservations",
    "036_permit_request_hash_anchor",
)
branch_labels: Union[str, tuple[str, ...], None] = None
depends_on: Union[str, tuple[str, ...], None] = None


def upgrade() -> None:
    """Join the two schema branches without changing database objects."""


def downgrade() -> None:
    """Split the schema history back into its two parent branches."""
