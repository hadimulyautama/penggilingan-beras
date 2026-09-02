"""Alembic environment — async (asyncpg), URL & metadata dari aplikasi."""
from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy import pool

from app.config import settings
from app.models import Base  # noqa: F401  (mengimpor semua model)

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def include_object(object_, name, type_, reflected, compare_to) -> bool:
    """Tabel `kantor_*` milik chain KANTOR (repo & service sendiri, version_table
    `alembic_version_kantor`). Modelnya masih ikut termuat di metadata (dipakai
    server MCP), jadi tanpa saringan ini autogenerate produksi bisa mengusulkan
    DROP/ALTER tabel Kantor yang berisi data."""
    if type_ == "table":
        return not (name or "").startswith("kantor_")
    parent = getattr(object_, "table", None)
    if parent is not None and parent.name:
        return not parent.name.startswith("kantor_")
    return True


def do_run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=include_object,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        include_object=include_object,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_async_migrations())
