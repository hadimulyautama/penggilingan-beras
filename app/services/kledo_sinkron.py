"""Satu putaran sinkron kontak Kledo — dipicu dari tiga tempat, satu fungsi.

Tiga pemicu berbagi `mulai()`:
  · tombol "Perbarui Kontak" di Pengaturan (produksi sendiri);
  · `/internal/kledo-kontak/sinkron` — dipanggil Timbangan, yang tidak
    pernah memegang `KLEDO_API_KEY` sendiri (lihat `.env.example`);
  · scheduler tengah malam (`app/services/kledo_scheduler.py`).

Ketiganya memanggil `hmu_core.kledo_kontak.sinkron_semua(db)` yang SAMA — tak
satu pun menulis jalurnya sendiri. Menyalin logikanya akan membuat ketiganya
lambat laun berbeda, dan perbedaan diam-diam pada aturan penautan identitas
adalah jenis kesalahan yang paling sulit disadari (lihat docstring modul itu
sendiri untuk aturan sinkronnya).

**Kenapa ada status/lock di sini, bukan di `hmu_core`.** Modul `hmu_core`
sengaja netral — tak tahu apa-apa soal web, latar belakang, atau Railway.
Yang butuh tahu "sedang berjalan atau tidak" dan "apa hasil yang terakhir"
hanya produksi (pemilik satu-satunya proses yang menjalankannya — lihat
`railway.json`: `numReplicas: 1`). Jadi statusnya singleton tingkat modul di
sini, bukan di tabel basis data: tak ada proses lain yang perlu membacanya,
dan tabel baru untuk sesuatu yang hilang begitu proses restart cuma menambah
tempat lain yang bisa berbeda dari kenyataan.

**Kunci race-free TANPA `asyncio.Lock`.** `mulai()` memeriksa lalu menyetel
`_sedang_berjalan` TANPA satu pun `await` di antaranya — asyncio koperatif
satu-thread, jadi tak ada potongan kode lain yang bisa menyelip di antara
keduanya. Itu "satu kunci sederhana" yang dibutuhkan: dua orang menekan
tombol bersamaan (satu di Pengaturan produksi, satu lewat Timbangan) akan
membuat panggilan KEDUA melihat `_sedang_berjalan=True` dan pulang tanpa
memulai putaran kedua — bukan karena ditolak, cukup karena tak ada gunanya.

Bila `railway.json` suatu saat diubah ke lebih dari satu replika, singleton
ini TIDAK LAGI cukup: dua proses bisa sama-sama melihat `_sedang_berjalan =
False` miliknya sendiri dan menjalankan dua sinkron bersamaan. Tidak
merusak (`sinkron_semua` tetap idempoten) tapi memboroskan kuota API Kledo
dan menghasilkan dua laporan yang membingungkan — persis yang pemicu ini
dibuat untuk dicegah pada satu replika.
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
