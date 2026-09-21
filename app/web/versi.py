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

Commit-nya dibaca dari `RAILWAY_GIT_COMMIT_SHA` (disediakan Railway untuk
deploy yang dipicu GitHub), atau dari berkas `KOMIT` yang ditulis Dockerfile
saat build dari variabel yang sama, atau — di laptop — dari `git` langsung.
Tak ada variabel lain yang dibaca di sini: nilainya ditampilkan di layar, dan
layar bukan tempat untuk nilai variabel apa pun selain hash commit.
"""
from __future__ import annotations

import functools
import os
import pathlib
import subprocess

from app.web import skema

AKAR = pathlib.Path(__file__).resolve().parents[2]
BERKAS_KOMIT = AKAR / "KOMIT"
PANJANG = 7

#: Keadaan skema dibanding kode. Yang bukan `selaras` ditampilkan mencolok
#: kepada admin ke atas — operator tak bisa berbuat apa-apa dengannya.
SELARAS = "selaras"
TERTINGGAL = "tertinggal"     # basis data di belakang kode: migrasi belum jalan
KODE_LAMA = "kode_lama"       # basis data di DEPAN kode: yang berjalan kode lama
TAK_TERBACA = "tak_terbaca"   # tabel versi tak ada / basis data tak terjangkau


def _bersih(sha: str | None) -> str | None:
    sha = (sha or "").strip()
    return sha[:PANJANG] if sha else None


def _dari_lingkungan() -> str | None:
    return _bersih(os.environ.get("RAILWAY_GIT_COMMIT_SHA"))


def _dari_berkas() -> str | None:
    try:
        return _bersih(BERKAS_KOMIT.read_text())
    except OSError:
        return None


def _dari_git() -> str | None:
    """Laptop saja: image tak membawa `.git` (ada di .dockerignore)."""
    if not (AKAR / ".git").exists():
        return None
    try:
        hasil = subprocess.run(
            ["git", "rev-parse", f"--short={PANJANG}", "HEAD"],
            cwd=AKAR, capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return _bersih(hasil.stdout) if hasil.returncode == 0 else None


@functools.lru_cache(maxsize=1)
def komit() -> str | None:
    """Hash commit pendek kode ini, atau None bila tak ada satu pun sumber.

    Di-cache: commit sebuah proses tak berubah selama proses itu hidup, dan
    membaca berkas atau menjalankan `git` tiap kali Pengaturan dibuka tak
    ada gunanya.
    """
    return _dari_lingkungan() or _dari_berkas() or _dari_git()


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
