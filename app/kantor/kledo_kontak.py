"""Sinkronisasi kontak vendor Kledo → master `suppliers`.

Kledo adalah sumber kebenaran identitas mitra (lihat memori no-redundancy-kledo).
Modul ini menyalin kontak **vendor** ke `suppliers` supaya pos timbang dan
sistem penggilingan memakai daftar yang sama — bukan daftar tandingan yang
diketik ulang.

**Yang disebut "vendor" adalah `type_id = 1`.** Ini tidak bisa ditebak dari
isinya dan pernah nyaris salah: `type_id = 4` justru berisi PLN, Pertamina, dan
Petugas Kebersihan sehingga *terlihat* seperti vendor, padahal itu beban
operasional. Buktinya diperiksa pada data sungguhan 2026-08-30 — dari 63 pihak
yang benar-benar pernah menjual komoditas (gabah, beras, PK, broken, menir,
reject), **62 bertipe 1** dan hanya 6 bertipe 4. Menyalin tipe 4 akan
memasukkan PLN ke dropdown pos timbang sekaligus meninggalkan Catur, Umar
Arifuddin, dan Pak Suparno.

Aturan yang dijaga:

  · **Tidak pernah menghapus.** Supplier yang tidak lagi ada di Kledo dibiarkan
    apa adanya — riwayat timbangan dan pembelian masih menunjuk ke sana.
  · **Menaut lebih dulu, membuat kemudian.** Pencocokan lewat
    `kledo_contact_id`, lalu nama persis. Nama yang ambigu tidak ditebak.
  · **Idempoten.** Dijalankan berapa kali pun hasilnya sama.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Supplier

log = logging.getLogger(__name__)

#: Jenis kontak Kledo yang berarti vendor/pemasok. Lihat penjelasan di atas.
TIPE_VENDOR = 1

_BASE = os.getenv("KLEDO_BASE", "https://pthadimulyautama.api.kledo.com/api/v1")
_PER_HAL = 100
_MAKS_HAL = 40          # jaring pengaman; 599 kontak = 6 halaman


def terkonfigurasi() -> bool:
    return bool(os.getenv("KLEDO_API_KEY"))


def _get(path: str, params: dict) -> dict:
    url = f"{_BASE}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {os.getenv('KLEDO_API_KEY', '')}",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def _isi(d: dict) -> tuple[list[dict], int]:
    """Kledo membungkus daftar dua lapis; kembalikan (baris, total)."""
    data = d.get("data", d)
    if isinstance(data, dict):
        return list(data.get("data") or []), int(data.get("total") or 0)
    return list(data or []), 0


async def ambil_vendor() -> list[dict]:
    """Seluruh kontak bertipe vendor dari Kledo."""
    semua: list[dict] = []
    for hal in range(1, _MAKS_HAL + 1):
        d = await asyncio.to_thread(
            _get, "/finance/contacts", {"per_page": _PER_HAL, "page": hal}
        )
        baris, total = _isi(d)
        if not baris:
            break
        semua += baris
        if total and len(semua) >= total:
            break
    return [
        k for k in semua
        if TIPE_VENDOR in (k.get("type_ids") or [k.get("type_id")])
        and not k.get("is_archive")
    ]


def _nama(k: dict) -> str:
    return (k.get("name") or "").strip()


def _kunci(nama: str) -> str:
    return " ".join(nama.lower().split())


@dataclass
class HasilSinkron:
    dibuat: int = 0
    ditaut: int = 0
    diperbarui: int = 0
    dilewati: int = 0
    ambigu: list[str] = field(default_factory=list)

    @property
    def ringkas(self) -> str:
        bagian = [f"{self.dibuat} baru", f"{self.ditaut} ditaut",
                  f"{self.diperbarui} diperbarui"]
        if self.ambigu:
            bagian.append(f"{len(self.ambigu)} ambigu dilewati")
        return ", ".join(bagian)


async def sinkron(db: AsyncSession, *, terapkan: bool = True) -> HasilSinkron:
    """Salin kontak vendor Kledo ke `suppliers`.

    `terapkan=False` menghitung tanpa menyentuh database — dipakai untuk
    melihat dampaknya lebih dulu.
    """
    hasil = HasilSinkron()
    vendor = await ambil_vendor()
    if not vendor:
        log.warning("Kledo tidak mengembalikan kontak vendor — sinkron dibatalkan")
        return hasil

    lokal = list((await db.execute(select(Supplier))).scalars())
    per_kledo = {s.kledo_contact_id: s for s in lokal if s.kledo_contact_id}

    # Nama yang muncul lebih dari sekali di sisi lokal tidak boleh ditebak.
    hitung_nama: dict[str, int] = {}
    for s in lokal:
        hitung_nama[_kunci(s.nama_supplier)] = hitung_nama.get(
            _kunci(s.nama_supplier), 0
        ) + 1
    per_nama = {
        _kunci(s.nama_supplier): s for s in lokal
        if s.kledo_contact_id is None and hitung_nama[_kunci(s.nama_supplier)] == 1
    }

    for k in vendor:
        nama = _nama(k)
        if not nama:
            hasil.dilewati += 1
            continue
        kid = k.get("id")

        s = per_kledo.get(kid)
        if s is None:
            s = per_nama.get(_kunci(nama))
            if s is not None:
                if terapkan:
                    s.kledo_contact_id = kid
                per_kledo[kid] = s
                per_nama.pop(_kunci(nama), None)
                hasil.ditaut += 1
        if s is None:
            if terapkan:
                db.add(Supplier(
                    nama_supplier=nama, kledo_contact_id=kid,
                    no_telfon=(k.get("phone") or None),
                    alamat=(k.get("address") or None),
                ))
            hasil.dibuat += 1
            continue

        # Kledo memegang kebenaran identitas; salin bila memang berbeda.
        baru = {
            "nama_supplier": nama,
            "no_telfon": (k.get("phone") or None),
            "alamat": (k.get("address") or None),
        }
        berubah = False
        for kolom, nilai in baru.items():
            # Jangan mengosongkan data lokal hanya karena Kledo belum mengisinya.
            if nilai is None:
                continue
            if getattr(s, kolom) != nilai:
                if terapkan:
                    setattr(s, kolom, nilai)
                berubah = True
        if berubah:
            hasil.diperbarui += 1

    # Nama lokal yang kembar sengaja tidak ditebak — dilaporkan supaya
    # manusia yang memutuskan. "Agus" cocok dengan belasan kontak Kledo.
    hasil.ambigu = sorted(
        s.nama_supplier for s in lokal
        if s.kledo_contact_id is None and hitung_nama[_kunci(s.nama_supplier)] > 1
    )

    if terapkan:
        await db.commit()
    return hasil
