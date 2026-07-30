"""Normalize database URLs for SQLAlchemy vs raw asyncpg consumers.

Railway and many hosts provide ``postgresql://...``. SQLAlchemy async needs
``postgresql+asyncpg://...``. Raw ``asyncpg.create_pool`` rejects the
``+asyncpg`` driver suffix.
"""

from __future__ import annotations


def as_sqlalchemy_url(url: str) -> str:
    """Return a URL suitable for SQLAlchemy ``create_async_engine``."""
    trimmed = (url or "").strip()
    if not trimmed:
        return trimmed
    if trimmed.startswith("postgresql+asyncpg://"):
        return trimmed
    if trimmed.startswith("postgres://"):
        return "postgresql+asyncpg://" + trimmed[len("postgres://") :]
    if trimmed.startswith("postgresql://"):
        return "postgresql+asyncpg://" + trimmed[len("postgresql://") :]
    return trimmed


def as_asyncpg_url(url: str) -> str:
    """Return a URL suitable for ``asyncpg.create_pool``."""
    trimmed = (url or "").strip()
    if not trimmed:
        return trimmed
    if trimmed.startswith("postgresql+asyncpg://"):
        return "postgresql://" + trimmed[len("postgresql+asyncpg://") :]
    if trimmed.startswith("postgres://"):
        return "postgresql://" + trimmed[len("postgres://") :]
    return trimmed
