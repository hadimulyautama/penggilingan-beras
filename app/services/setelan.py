"""Setelan pabrik yang berubah di lapangan — dibaca dari basis data.

Yang boleh ada di sini hanya hal yang memang berubah tanpa perlu menyentuh
kode: target kadar air bawaan, dan daftar sebab berhenti. Bukan semua yang
kebetulan berupa angka — setelan yang tak pernah diubah cuma menambah tempat
untuk salah.

Nilai bawaannya tetap ditulis di kode, jadi pabrik yang basis datanya masih
kosong tetap jalan pada hari pertama.
"""
from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import SetelanPabrik
from app.penggilingan.gudang1.services.jeda import SEBAB as SEBAB_BAWAAN
from app.services.activity_log import log_activity

K_TARGET = "target_kadar_air"
K_SEBAB = "sebab_jeda"


async def _ambil(db: AsyncSession, kunci: str) -> str | None:
    return (await db.execute(
        select(SetelanPabrik.nilai).where(SetelanPabrik.kunci == kunci)
    )).scalars().first()


async def _simpan(db: AsyncSession, kunci: str, nilai: str, *, user) -> None:
    baris = await db.get(SetelanPabrik, kunci)
    lama = baris.nilai if baris else None
    if baris is None:
        db.add(SetelanPabrik(kunci=kunci, nilai=nilai, diubah_oleh=user.id))
    else:
        baris.nilai, baris.diubah_oleh = nilai, user.id
    await log_activity(
        db, table_name="setelan_pabrik", record_id=0, action="UPDATE",
        changed_by=user.id, field_name=kunci, old_value=lama, new_value=nilai,
    )
    await db.commit()


async def target_kadar_air(db: AsyncSession) -> float:
    """Nilai AWAL borang "mulai pengeringan", bukan aturan.

    Yang menentukan tetap operator saat menyalakan mesin — dan ia wajib
    mengisinya. Setelan ini cuma menghemat satu ketikan pada muatan yang
    memang biasa dituju ke angka yang sama.
    """
    n = await _ambil(db, K_TARGET)
    try:
        return float(n) if n is not None else float(settings.kadar_air_target_persen)
    except ValueError:
        return float(settings.kadar_air_target_persen)


async def set_target_kadar_air(db: AsyncSession, nilai: float, *, user) -> None:
    if not (5 <= nilai <= 30):
        raise ValueError("Target kadar air bawaan masuk akal antara 5% dan 30%.")
    await _simpan(db, K_TARGET, f"{nilai:g}", user=user)


async def sebab_jeda(db: AsyncSession) -> dict[str, list[str]]:
    """Sebab berhenti per jenis proses.

    Dryer tak pernah kepenuhan limbah dan mesin giling tak pernah kehabisan
    bahan bakar — daftar gabungan memaksa operator melewati sebab yang
    mustahil untuk mesinnya.
    """
    mentah = await _ambil(db, K_SEBAB)
    bawaan = {k: list(v) for k, v in SEBAB_BAWAAN.items()}
    if not mentah:
        return bawaan
    try:
        simpan = json.loads(mentah)
    except json.JSONDecodeError:
        return bawaan
    # Kunci yang hilang jatuh ke bawaannya — setelan yang rusak sebagian tak
    # boleh membuat borang jedanya kosong sama sekali.
    return {k: [str(x) for x in simpan.get(k) or v] for k, v in bawaan.items()}


async def set_sebab_jeda(db: AsyncSession, daftar: dict[str, list[str]], *,
                         user) -> None:
    for jenis, isi in daftar.items():
        if not isi:
            raise ValueError(
                f"Sebab berhenti {jenis} tak boleh kosong — berhenti tanpa sebab "
                "tak bisa dipakai memperbaiki apa pun.")
    await _simpan(db, K_SEBAB, json.dumps(daftar, ensure_ascii=False), user=user)
