"""Peringatan migrasi di Postgres sungguhan: `alembic_version` diturunkan
satu revisi, dan Pengaturan harus memperingatkan admin.

Tabel versinya DIKEMBALIKAN sesudahnya, apa pun yang terjadi: fixture `pg`
mempertahankan tabel itu antar-uji, dan `alembic upgrade head` berikutnya
akan mencoba menjalankan ulang migrasi terakhir di atas skema yang sudah
jadi bila barisnya tertinggal.
"""
from __future__ import annotations

import importlib.util
import pathlib

from sqlalchemy import text

AKAR = pathlib.Path(__file__).resolve().parents[2]


async def test_alembic_version_turun_satu_revisi_memicu_peringatan(pg):
    from app.web import skema, versi

    head = skema._head_dari_berkas()
    berkas = AKAR / "migrations" / "versions" / f"{head}.py"
    spec = importlib.util.spec_from_file_location(head, berkas)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    turun = m.down_revision

    async with pg() as db:
        tercatat = (await db.execute(text("SELECT version_num FROM alembic_version"))).scalar_one()
    assert tercatat == head, "fixture pg seharusnya di head"
    assert (await versi.info())["keadaan"] == versi.SELARAS

    async with pg() as db:
        await db.execute(text("UPDATE alembic_version SET version_num = :r"), {"r": turun})
        await db.commit()
    try:
        info = await versi.info()
        assert info["keadaan"] == versi.TERTINGGAL
        assert info["revisi"] == turun and info["head"] == head
    finally:
        async with pg() as db:
            await db.execute(text("UPDATE alembic_version SET version_num = :r"), {"r": head})
            await db.commit()

    assert (await versi.info())["keadaan"] == versi.SELARAS
