"""Pemotong dokumen — pecah teks (markdown) jadi bagian retrieval. MURNI.

Strategi: pecah per-heading (baris '#'), lalu gabung paragraf hingga ~target
karakter. Tiap potongan diberi awalan jalur heading (mis. "III. Struktur > 3.1")
agar konteksnya jelas saat ditemukan terpisah.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

_H = re.compile(r"^(#{1,6})\s+(.*)$")


@dataclass(frozen=True)
class Potongan:
    urutan: int
    judul_jalur: str   # breadcrumb heading, mis. "PEDOMAN > III. STRUKTUR"
    isi: str


def konten_hash(teks: str) -> str:
    """SHA-256 isi (dinormalkan) untuk deteksi perubahan / dedup."""
    norm = re.sub(r"\s+", " ", teks).strip()
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


def _bersih(baris: str) -> str:
    # buang penanda markdown ringan agar isi enak dicari/dibaca
    s = re.sub(r"[*_`]+", "", baris)
    return s.strip()


def potong(teks: str, *, target: int = 1100, minimum: int = 250) -> list[Potongan]:
    """Pecah `teks` markdown jadi daftar Potongan.

    - Batas potongan mengikuti heading; isi panjang dipecah lagi per paragraf
      hingga mendekati `target` karakter.
    - Potongan sangat pendek digabung dengan berikutnya (>= `minimum`).
    """
    jalur: list[str] = []          # tumpukan heading aktif per level
    buf: list[str] = []
    hasil: list[Potongan] = []

    def flush():
        isi = "\n".join(buf).strip()
        buf.clear()
        if not isi:
            return
        bread = " > ".join(j for j in jalur if j)
        hasil.append(Potongan(0, bread, isi))

    for raw in teks.splitlines():
        m = _H.match(raw.strip())
        if m:
            flush()
            level = len(m.group(1))
            judul = _bersih(m.group(2))
            del jalur[level - 1:]
            while len(jalur) < level - 1:
                jalur.append("")
            jalur.append(judul)
            continue
        buf.append(_bersih(raw))
        if sum(len(x) for x in buf) >= target:
            flush()
    flush()

    # gabung potongan mungil ke tetangga + isi ulang urutan
    padat: list[Potongan] = []
    for p in hasil:
        if padat and len(p.isi) < minimum and padat[-1].judul_jalur == p.judul_jalur:
            prev = padat[-1]
            padat[-1] = Potongan(0, prev.judul_jalur, prev.isi + "\n" + p.isi)
        else:
            padat.append(p)
    return [Potongan(i, p.judul_jalur, p.isi) for i, p in enumerate(padat)]
