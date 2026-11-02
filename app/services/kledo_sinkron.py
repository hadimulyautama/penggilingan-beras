"""Satu pemilik sinkron kontak Kledo untuk seluruh proses web.

Dalam deployment app.server, scheduler dan RPC privat berada pada satu
pekerja. Web memakai status_async/mulai_async; pemicu manual dari semua
web bertemu lock yang sama. Mode gabungan tetap mendukung pengembangan.

railway.json tetap satu replika. Menambah kontainer memerlukan koordinasi
pekerja lintas kontainer, bukan menggandakan supervisor ini begitu saja.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime

from app.database import SessionLocal, now_local
from hmu_core import kledo_kontak

log = logging.getLogger("kledo_sinkron")

_sedang_berjalan = False
_hasil_terakhir: str | None = None
_gagal_terakhir: str | None = None
_selesai_pada: datetime | None = None


@dataclass(frozen=True)
class StatusSinkron:
    terkonfigurasi: bool
    sedang_berjalan: bool
    hasil_terakhir: str | None
    gagal_terakhir: str | None
    selesai_pada: datetime | None


def status() -> StatusSinkron:
    """Potret keadaan sekarang — dibaca layar Pengaturan tiap kali dimuat."""
    return StatusSinkron(
        terkonfigurasi=kledo_kontak.terkonfigurasi(),
        sedang_berjalan=_sedang_berjalan,
        hasil_terakhir=_hasil_terakhir,
        gagal_terakhir=_gagal_terakhir,
        selesai_pada=_selesai_pada,
    )


async def _rpc(method,path):
    import os
    import httpx
    from fastapi import HTTPException
    token=os.environ.get('HMU_PEKERJA_TOKEN','')
    if not token:raise HTTPException(503,'Pekerja sinkronisasi belum tersedia.')
    port=int(os.environ.get('HMU_PEKERJA_PORT','8787'))
    try:
        async with httpx.AsyncClient(base_url=f'http://127.0.0.1:{port}',timeout=3,trust_env=False) as client:
            response=await client.request(method,path,headers={'X-Pekerja-Token':token})
            response.raise_for_status()
            return response.json()
    except (httpx.HTTPError,ValueError) as e:
        log.warning('Pekerja sinkronisasi tidak tersedia: %s',type(e).__name__)
        raise HTTPException(503,'Pekerja sinkronisasi belum tersedia.') from e


async def status_async():
    from app.config import settings
    if settings.peran_proses!='web':return status()
    d=await _rpc('GET','/kledo/status')
    if d.get('selesai_pada'):d['selesai_pada']=datetime.fromisoformat(d['selesai_pada'])
    return StatusSinkron(**d)


async def mulai_async():
    from app.config import settings
    if settings.peran_proses!='web':return mulai()
    return bool((await _rpc('POST','/kledo/mulai'))['dimulai'])


def mulai() -> bool:
    """Mulai satu putaran di latar. `False` bila sudah ada yang berjalan.

    SENGAJA fungsi biasa (bukan `async def`): bagian yang menentukan "aku
    yang dapat giliran" harus selesai dalam SATU langkah Python tanpa
    `await`, supaya pemanggil kedua yang datang sepersekian detik kemudian
    pasti melihat hasil dari pemanggil pertama, bukan keadaan di tengah.
    """
    global _sedang_berjalan
    if _sedang_berjalan:
        return False
    _sedang_berjalan = True
    asyncio.create_task(_jalankan())
    return True


async def _jalankan() -> None:
    global _sedang_berjalan, _hasil_terakhir, _gagal_terakhir, _selesai_pada
    try:
        async with SessionLocal() as db:
            hasil = await kledo_kontak.sinkron_semua(db)
        _hasil_terakhir = _ringkas_gabungan(hasil)
        _gagal_terakhir = None
    except Exception as e:  # noqa: BLE001 — satu malam gagal tak boleh mematikan pemicunya
        log.exception("Sinkron kontak Kledo gagal")
        _gagal_terakhir = f"{type(e).__name__}: {e}"
    finally:
        _selesai_pada = now_local()
        _sedang_berjalan = False


def _ringkas_gabungan(hasil: dict[str, kledo_kontak.HasilSinkron]) -> str:
    """Satu kalimat yang MENJAWAB kenapa orang menekan tombol ini.

    Orang menekan tombol ini karena ADA kontak baru di Kledo — "berhasil"
    saja tidak menjawab itu. Tiap bagian (baru/tertaut/tak berubah/ambigu)
    hanya disebut bila > 0, supaya kalimatnya tidak dipenuhi "0 tertaut"
    untuk jenis yang memang tak punya itu.
    """
    label = {"pelanggan": "pelanggan", "vendor": "supplier"}
    urutan = ("pelanggan", "vendor")   # yang ditunggu pelanggan Pos Produksi lebih dulu
    bagian = []
    for jenis in urutan:
        h = hasil.get(jenis)
        if h is None:
            continue
        rincian = []
        if h.dibuat:
            rincian.append(f"{h.dibuat} baru")
        if h.ditaut:
            rincian.append(f"{h.ditaut} tertaut")
        if h.diperbarui:
            rincian.append(f"{h.diperbarui} diperbarui")
        if h.tak_berubah:
            rincian.append(f"{h.tak_berubah} tak berubah")
        if h.ambigu:
            rincian.append(f"{len(h.ambigu)} ambigu dilewati")
        if not rincian:
            rincian = ["tidak ada data"]
        bagian.append(f"{label[jenis]}: {', '.join(rincian)}")
    return "Kontak diperbarui — " + "; ".join(bagian) + "."
