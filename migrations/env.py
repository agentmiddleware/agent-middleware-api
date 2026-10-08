"""
Alembic environment configuration for migrations.
"""

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

from app.db.models import SQLModel

# this is the Alembic Config object
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# Add your model's MetaData object here for 'autogenerate' support
target_metadata = SQLModel.metadata


def get_url():
    """Get database URL from config or environment (SQLAlchemy async form)."""
    import os

    from app.core.db_urls import as_sqlalchemy_url

    return as_sqlalchemy_url(os.getenv("DATABASE_URL", ""))


# Fallback used only for local development when DATABASE_URL is unset.
# Production-like deployments must set DATABASE_URL: see resolve_migration_url.
SQLITE_DEV_FALLBACK_URL = "sqlite+aiosqlite:///./agent_middleware.db"


def resolve_migration_url() -> str:
    """Return the database URL for a migration run, failing loudly when unsafe.

    A missing DATABASE_URL falls back to a local SQLite file for local
    development only. On a production-like ENVIRONMENT, or on a hosted
    runtime with no explicit ENVIRONMENT, a missing DATABASE_URL is a
    misconfiguration (the migration would run against a fresh local file
    while the real database sits unmigrated), so refuse instead.
    """
    import os

    from app.core.trust_mode import (
        PRODUCTION_LIKE_ENVIRONMENTS,
        normalize_environment,
        require_explicit_environment_on_hosted_runtime,
    )

    url = get_url()
    if url:
        return url
    environment = os.getenv("ENVIRONMENT")
    require_explicit_environment_on_hosted_runtime(environment)
    if normalize_environment(environment) in PRODUCTION_LIKE_ENVIRONMENTS:
        raise RuntimeError(
            "DATABASE_URL is not set and ENVIRONMENT=%r is production-like: "
            "refusing to migrate a throwaway SQLite file. Set DATABASE_URL "
            "to the durable database." % (environment,)
        )
    print(
        "Warning: DATABASE_URL not set, using local SQLite file for "
        "migrations (local development only): ./agent_middleware.db"
    )
    return SQLITE_DEV_FALLBACK_URL


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.
    """
    url = resolve_migration_url()

    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """In this scenario we need to create an Engine
    and associate a connection with the context.
    """
    url = resolve_migration_url()

    configuration = config.get_section(config.config_ini_section)
    configuration["sqlalchemy.url"] = url

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
