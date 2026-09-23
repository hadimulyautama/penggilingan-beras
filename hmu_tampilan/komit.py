"""Hash commit pendek kode yang SEDANG BERJALAN di repo app ini.

Di paket, bukan di tiap app, karena keempat app menampilkan angka yang sama
bentuknya di baris versi Pengaturan dan cara membacanya persis sama. Salinan
kedua dan ketiga dari fungsi ini adalah persis penyakit yang penyatuan 23
September 2026 obati — dan Meja & Gudang 2 belum punya satu pun, jadi ini
jalan supaya keduanya tak perlu menyalin.

Tiga sumber, berurutan:
  1. `RAILWAY_GIT_COMMIT_SHA` — disediakan Railway untuk deploy dari GitHub;
  2. berkas `KOMIT` di akar repo — ditulis Dockerfile saat build dari variabel
     yang sama (variabel build hanya terlihat bila dideklarasikan `ARG`);
  3. `git` langsung — laptop saja; image tak membawa `.git` (.dockerignore).

TIDAK ada variabel lain yang dibaca di sini. Nilainya ditampilkan di layar,
dan layar bukan tempat untuk nilai variabel apa pun selain hash commit.

Akar repo = induk folder paket ini. Paket di-vendor ke `<repo>/hmu_tampilan/`,
jadi induknya adalah `/app` di image — tempat Dockerfile menulis `KOMIT`.
"""
from __future__ import annotations

import functools
import os
import pathlib
import subprocess

PANJANG = 7
AKAR = pathlib.Path(__file__).resolve().parents[1]
BERKAS = AKAR / "KOMIT"


def _bersih(sha: str | None) -> str | None:
    sha = (sha or "").strip()
    return sha[:PANJANG] if sha else None


def _dari_lingkungan() -> str | None:
    return _bersih(os.environ.get("RAILWAY_GIT_COMMIT_SHA"))


def _dari_berkas() -> str | None:
    try:
        return _bersih(BERKAS.read_text())
    except OSError:
        return None


def _dari_git() -> str | None:
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
    """Hash pendek, atau None bila tak satu pun sumber menjawab.

    Di-cache: commit sebuah proses tak berubah selama proses itu hidup, dan
    membaca berkas atau menjalankan `git` tiap kali Pengaturan dibuka tak ada
    gunanya. Uji yang mengubah sumbernya wajib `komit.cache_clear()`.
    """
    return _dari_lingkungan() or _dari_berkas() or _dari_git()
