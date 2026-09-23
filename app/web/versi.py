"""Versi kode yang SEDANG BERJALAN — supaya bisa dilihat dari ponsel.

21 September 2026, 20:50: pemilik melaporkan giling "masih tidak mau" —
HTTP 500, dan batch tertulis "0 kg". Perbaikannya (P6) sudah benar; QA
membuktikannya lewat HTTP pada skenario yang sama. Yang berjalan di ponsel
pemilik masih kode lama — tetapi tak ada satu layar pun yang menyebut kode
mana yang sedang berjalan, jadi butuh satu putaran QA penuh hanya untuk
mengetahui itu.

Tiga angka yang bersama-sama menjawab "apakah perbaikan itu sudah sampai?":

  · **VERSI** aset tampilan (`hmu_tampilan.VERSI`) — yang dilihat peramban;
  · **commit** pendek yang di-build ke image ini — yang dilihat server;
  · **revisi migrasi** yang tercatat di basis data — yang dilihat skema.

Yang ketiga yang paling sering menipu: kode baru di atas basis data yang
migrasinya belum jalan adalah keadaan yang galatnya tak menunjuk ke sebabnya.

Commit-nya dibaca oleh `hmu_tampilan.komit` — di paket, bukan di sini, sejak
penyatuan templat 23 September 2026: keempat app menampilkan angka yang sama
bentuknya dan cara membacanya persis sama, dan Meja & Gudang 2 belum punya
satu pun. Yang tinggal di modul ini adalah bagian yang memang milik repo ini:
perbandingan revisi alembic dengan rantai migrasinya sendiri.
"""
from __future__ import annotations

from app.web import skema
from hmu_tampilan.komit import komit  # noqa: F401 — dipakai `info()` & uji

#: Keadaan skema dibanding kode. Yang bukan `selaras` ditampilkan mencolok
#: kepada admin ke atas — operator tak bisa berbuat apa-apa dengannya.
SELARAS = "selaras"
TERTINGGAL = "tertinggal"     # basis data di belakang kode: migrasi belum jalan
KODE_LAMA = "kode_lama"       # basis data di DEPAN kode: yang berjalan kode lama
TAK_TERBACA = "tak_terbaca"   # tabel versi tak ada / basis data tak terjangkau


def banding(revisi: str | None, head: str | None) -> str:
    """Di mana basis data berada relatif terhadap kode ini."""
    if not revisi or not head:
        return TAK_TERBACA
    if revisi == head:
        return SELARAS
    # Revisi yang dikenal kode ini tetapi bukan head = basis data tertinggal.
    # Revisi yang TAK dikenal = dibuat kode yang lebih baru dari ini — persis
    # keadaan 21 September: yang berjalan bukan deploy terbaru.
    return TERTINGGAL if revisi in skema.revisi_berkas() else KODE_LAMA


async def info() -> dict:
    """Bahan baris versi di Pengaturan. Tak pernah melempar."""
    from app.web.tampilan import VERSI

    keadaan = await skema.keadaan()
    return {
        "versi": VERSI,
        "komit": komit(),
        "revisi": keadaan["revisi"],
        "head": keadaan["head"],
        "keadaan": banding(keadaan["revisi"], keadaan["head"]),
    }
