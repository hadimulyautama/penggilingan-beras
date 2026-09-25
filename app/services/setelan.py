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
K_MUTU = "fitur_mutu"
K_TOL_NOTA = "toleransi_nota_persen"

#: Bawaan toleransi kekurangan bobot terhadap nota, dalam PERSEN dari nota.
#: 0,2% = tepat 20 kg pada muatan 10 ton — angka yang pemilik sebut sendiri
#: (25 September 2026). Lihat catatan panjang di `timbang_link`.
TOL_NOTA_BAWAAN = 0.2


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


async def fitur_mutu(db: AsyncSession) -> bool:
    """Apakah pabrik ini mencatat mutu sama sekali. Bawaannya YA.

    Bawaan menyala, bukan padam: pabrik yang sudah memakai QC tak boleh
    kehilangan layarnya hanya karena setelan baru ditambahkan. Yang tidak
    memakainya cukup mematikannya sekali.

    Dimatikan berarti hilang SELURUHNYA — borang QC, kartu "mutu belum
    diperiksa", dan baris mutu di kartu Stok. Setengah mati adalah yang
    terburuk: layar yang masih menagih QC sementara borangnya tak ada
    mengajari orang mengabaikan tagihan.
    """
    n = await _ambil(db, K_MUTU)
    return n != "0"          # apa pun selain "0" berarti menyala


async def set_fitur_mutu(db: AsyncSession, aktif: bool, *, user) -> None:
    await _simpan(db, K_MUTU, "1" if aktif else "0", user=user)


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


async def toleransi_nota_persen(db: AsyncSession) -> float:
    """Berapa PERSEN dari nota yang masih dimaafkan saat barangnya kurang.

    Di setelan, bukan di kode, atas usul QA: pemilik menyebut "20 kg dari 10
    ton" dan penalaran bahwa susut perjalanan tumbuh bersama muatan adalah
    tafsir atas kalimat itu — bukan kalimatnya sendiri. Direksi yang kelak
    menemukan angkanya terlalu longgar atau terlalu ketat bisa menggesernya
    tanpa menunggu deploy.

    JENIS mana yang mendapatnya tetap di kode (`JENIS_BERTOLERANSI`): itu
    bukan angka melainkan keputusan tentang komoditas, dan memberi toleransi
    kepada komoditas yang pemilik tak sebut berarti memutuskan atas namanya.

    Nol pun sah: pabrik yang ingin nota selalu kalah begitu barangnya kurang
    cukup menyetelnya 0, dan seluruh jenis jadi seketat gabah kering.
    """
    n = await _ambil(db, K_TOL_NOTA)
    if n is None:
        return TOL_NOTA_BAWAAN
    try:
        v = float(n)
    except ValueError:
        return TOL_NOTA_BAWAAN
    # Negatif tak punya arti: ia berarti "hukum nota walau barangnya LEBIH".
    return v if v >= 0 else TOL_NOTA_BAWAAN


async def set_toleransi_nota_persen(db: AsyncSession, persen: float, *, user) -> None:
    await _simpan(db, K_TOL_NOTA, f"{float(persen):g}", user=user)
