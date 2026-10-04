"""Sinkronisasi kontak Kledo → master `suppliers` dan `pelanggan`.

Kledo adalah sumber kebenaran identitas mitra (lihat memori no-redundancy-kledo).
Modul ini menyalin kontak **vendor** ke `suppliers` dan kontak **pelanggan**
ke `pelanggan`, supaya pos timbang dan sistem penggilingan memakai daftar yang
sama — bukan daftar tandingan yang diketik ulang.

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

**Pelanggan adalah `type_id = 3`**, diperiksa pada data sungguhan 2026-09-01:
301 dari 601 kontak, dan salah satunya "Walk-in Customer" — kontak bawaan
Kledo yang hanya ada pada tipe pelanggan. Sisanya memang pembeli beras: Toko
beras handoko, Angkringan Depan, dr. H. Nurhadi.

24 kontak bertipe vendor SEKALIGUS pelanggan, dan itu memang wajar: orang yang
menjual gabah pagi bisa membeli beras sore. Keduanya disalin ke tabel
masing-masing, karena yang menentukan adalah perannya pada transaksi itu.

Satu jebakan API yang sudah dibuktikan: parameter `type_ids[]` pada
`/finance/contacts` **diabaikan** — permintaan bertipe apa pun tetap
mengembalikan seluruh 601 kontak. Penyaringan karena itu dikerjakan di sini,
bukan diserahkan ke server.

**Pindah ke `hmu_core` 4 Oktober 2026** (dari `kantor/app/kantor/kledo_kontak.py`).
Modul ini sudah portabel sejak awal — hanya mengimpor stdlib, SQLAlchemy, dan
`hmu_core.models` sendiri — jadi pindahnya murni memindah berkas: produksi dan
timbangan kini bisa memicunya langsung tanpa melalui Kantor sama sekali.
Penyegar mingguan Kantor (`app/kantor/proaktif/kledo_kontak.py`) tetap jalan,
hanya impornya yang berubah mengikuti kepindahan ini.
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

from hmu_core.models import Pelanggan, Supplier  # master bersama, bukan model domain apa pun

log = logging.getLogger(__name__)

#: Jenis kontak Kledo. Keduanya diperiksa pada data sungguhan; lihat di atas.
TIPE_VENDOR = 1
TIPE_PELANGGAN = 3

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


async def ambil_kontak(tipe: int) -> list[dict]:
    """Seluruh kontak Kledo bertipe ini.

    Seluruh halaman diambil lalu disaring di sini — `type_ids[]` di API-nya
    tidak berpengaruh sama sekali.
    """
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
        if tipe in (k.get("type_ids") or [k.get("type_id")])
        and not k.get("is_archive")
    ]


async def ambil_vendor() -> list[dict]:
    """Kontak vendor. Dipertahankan sebagai nama sendiri karena dipakai uji."""
    return await ambil_kontak(TIPE_VENDOR)


async def ambil_pelanggan() -> list[dict]:
    return await ambil_kontak(TIPE_PELANGGAN)


@dataclass(frozen=True)
class JenisKontak:
    """Satu macam kontak Kledo beserta tabel tujuannya.

    Sinkronisasi vendor dan pelanggan berbagi SATU fungsi. Menyalin fungsinya
    akan menghasilkan dua salinan yang lambat laun berbeda — dan perbedaan
    diam-diam pada penautan identitas adalah jenis kesalahan yang paling sulit
    disadari.
    """

    tipe: int
    model: type
    kolom_nama: str
    sebutan: str

    async def ambil(self) -> list[dict]:
        return await ambil_kontak(self.tipe)


VENDOR = JenisKontak(TIPE_VENDOR, Supplier, "nama_supplier", "vendor")
PELANGGAN = JenisKontak(TIPE_PELANGGAN, Pelanggan, "nama_pelanggan", "pelanggan")


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
    # Ditambahkan 4 Oktober 2026 bersama kepindahan ke `hmu_core`: tombol
    # pemicu di Produksi/Timbangan perlu melaporkan angka SUNGGUH-SUNGGUH,
    # bukan "berhasil" — dan "tak berubah" (kontak yang sudah tertaut/cocok
    # dan tak satu kolom pun berbeda) adalah bagian terbesar dari tiap
    # putaran (±600 kontak, hanya segelintir yang berubah tiap minggu).
    # Murni hitungan tambahan — tidak mengubah satu keputusan pencocokan
    # pun di bawah.
    tak_berubah: int = 0
    ambigu: list[str] = field(default_factory=list)

    @property
    def ringkas(self) -> str:
        bagian = [f"{self.dibuat} baru", f"{self.ditaut} ditaut",
                  f"{self.diperbarui} diperbarui"]
        if self.ambigu:
            bagian.append(f"{len(self.ambigu)} ambigu dilewati")
        return ", ".join(bagian)


async def sinkron(
    db: AsyncSession, jenis: JenisKontak = VENDOR, *, terapkan: bool = True
) -> HasilSinkron:
    """Salin kontak Kledo bertipe ini ke tabel masternya.

    `terapkan=False` menghitung tanpa menyentuh database — dipakai untuk
    melihat dampaknya lebih dulu.
    """
    hasil = HasilSinkron()
    kontak = await jenis.ambil()
    if not kontak:
        log.warning(
            "Kledo tidak mengembalikan kontak %s — sinkron dibatalkan",
            jenis.sebutan,
        )
        return hasil

    def _nama_baris(baris) -> str:
        return getattr(baris, jenis.kolom_nama)

    # ── Yang sudah DIHAPUS tidak ikut ──
    #
    # Pemasok yang dihapus tetap terbaca di sini, jadi kontak Kledo bisa
    # tertaut padanya — dan sejak itu pemasok aktif bernama sama muncul GANDA
    # di daftar pos timbang, satu hidup dan satu hantu. Temuan QA K-19.
    q = select(jenis.model)
    if hasattr(jenis.model, "deleted_at"):
        q = q.where(jenis.model.deleted_at.is_(None))
    lokal = list((await db.execute(q)).scalars())
    per_kledo = {s.kledo_contact_id: s for s in lokal if s.kledo_contact_id}

    # Nama yang muncul lebih dari sekali di sisi lokal tidak boleh ditebak.
    hitung_nama: dict[str, int] = {}
    for s in lokal:
        kunci = _kunci(_nama_baris(s))
        hitung_nama[kunci] = hitung_nama.get(kunci, 0) + 1
    per_nama = {
        _kunci(_nama_baris(s)): s for s in lokal
        if s.kledo_contact_id is None
        and hitung_nama[_kunci(_nama_baris(s))] == 1
    }

    for k in kontak:
        nama = _nama(k)
        if not nama:
            hasil.dilewati += 1
            continue
        kid = k.get("id")

        s = per_kledo.get(kid)
        # Baru ditaut PADA PUTARAN INI — supaya tidak ikut dihitung "tak
        # berubah" di bawah: sesuatu memang berubah (ID-nya), walau tak satu
        # kolom pun berubah.
        baru_ditaut = False
        if s is None:
            # Nama yang muncul lebih dari sekali di sisi lokal TIDAK ditebak —
            # `per_nama` sengaja hanya memuat nama yang unik. Yang ambigu
            # dilaporkan, bukan ditaut diam-diam ke salah satunya.
            if hitung_nama.get(_kunci(nama), 0) > 1:
                hasil.ambigu.append(nama)
                hasil.dilewati += 1
                continue
            s = per_nama.get(_kunci(nama))
            if s is not None:
                if terapkan:
                    s.kledo_contact_id = kid
                per_kledo[kid] = s
                per_nama.pop(_kunci(nama), None)
                hasil.ditaut += 1
                baru_ditaut = True
        if s is None:
            if terapkan:
                db.add(jenis.model(**{
                    jenis.kolom_nama: nama,
                    "kledo_contact_id": kid,
                    "no_telfon": (k.get("phone") or None),
                    "alamat": (k.get("address") or None),
                }))
            hasil.dibuat += 1
            continue

        # Kledo memegang kebenaran identitas; salin bila memang berbeda.
        baru = {
            jenis.kolom_nama: nama,
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
        elif not baru_ditaut:
            hasil.tak_berubah += 1

    # Nama lokal yang kembar sengaja tidak ditebak — dilaporkan supaya
    # manusia yang memutuskan. "Agus" cocok dengan belasan kontak Kledo.
    hasil.ambigu = sorted(
        _nama_baris(s) for s in lokal
        if s.kledo_contact_id is None
        and hitung_nama[_kunci(_nama_baris(s))] > 1
    )

    if terapkan:
        await db.commit()
    return hasil


async def sinkron_semua(
    db: AsyncSession, *, terapkan: bool = True
) -> dict[str, HasilSinkron]:
    """Vendor dan pelanggan sekaligus, dalam satu kali tarik per jenis."""
    return {
        j.sebutan: await sinkron(db, j, terapkan=terapkan)
        for j in (VENDOR, PELANGGAN)
    }
