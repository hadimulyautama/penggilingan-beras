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


#: Awalan tabel yang BUKAN milik chain ini, walau modelnya ikut termuat.
#:
#: `kantor_*` milik repo Kantor, `timbangan_*` milik repo Timbangan, dan
#: `alembic_version*` milik alembic sendiri. Tanpa saringan ini `alembic check`
#: mengusulkan DROP 14 tabel timbangan dan 3 tabel versi — dan yang membaca
#: usulan itu sambil terburu-buru bisa saja menerapkannya. Temuan QA X-12.
#:
#: Migrasi 0022–0026 di chain ini memang MEMBUAT tabel timbangan_*, dan itu
#: sejarah yang tak bisa dicabut: mereka sudah berjalan di produksi. Yang
#: dilarang adalah autogenerate BERIKUTNYA ikut mengurusnya.
AWALAN_BUKAN_MILIK_KITA = ("kantor_", "timbangan_", "alembic_version")


def _bukan_milik_kita(nama: str | None) -> bool:
    return (nama or "").startswith(AWALAN_BUKAN_MILIK_KITA)


def include_object(object_, name, type_, reflected, compare_to) -> bool:
    """Saring benda milik chain lain dari autogenerate & `alembic check`."""
    if type_ == "table":
        return not _bukan_milik_kita(name)

    # ── FK yang MENUNJUK tabel milik repo lain ──
    #
    # `purchase_batches.timbangan_transaksi_id` menunjuk `timbangan_transaksi`,
    # dan tabel itu memang tidak ada di metadata repo ini — ia milik repo
    # timbangan. FK-nya nyata di basis data (dibuat migrasi 0027) tetapi tak
    # terwakili di model, jadi autogenerate melihatnya sebagai "ada di DB,
    # tak ada di model" lalu mengusulkan DROP. Menerapkan usulan itu akan
    # mencabut satu-satunya penjaga yang mencegah tiket terhapus sementara
    # batchnya masih menunjuk padanya. Temuan QA X-12.
    if type_ == "foreign_key_constraint":
        sasaran = {fk.column.table.name for fk in getattr(object_, "elements", [])
                   if fk.column is not None}
        if any(_bukan_milik_kita(t) for t in sasaran):
            return False
        if "timbangan" in (name or ""):
            return False

    parent = getattr(object_, "table", None)
    if parent is not None and parent.name:
        return not _bukan_milik_kita(parent.name)
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
