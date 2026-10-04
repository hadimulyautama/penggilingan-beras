"""API internal — pemicu sinkron kontak Kledo untuk TIMBANGAN.

Berkas tersendiri, bukan ditambahkan ke `internal.py`: docstring berkas itu
menyatakan dirinya "satu-satunya pintu baca data pabrik untuk Kantor AI" dan
"READ-ONLY" — benar untuk isinya, dan tombol ini BUKAN untuk Kantor AI serta
BUKAN read-only (ia memulai penulisan ke `suppliers`/`pelanggan`). Mencampur
keduanya akan membuat salah satu klaim itu berhenti benar.

Tetap di bawah prefix `/internal`, jadi tetap mewarisi dua hal yang sama:
CSRF-exempt lewat `JALUR_BEBAS` di `app/web/csrf.py` (dicocokkan dari AWALAN
path, bukan dari berkas mana rute ini didaftarkan), dan token penjaga yang
SAMA (`INTERNAL_API_TOKEN`) — `_pastikan_token` diimpor dari `internal.py`
apa adanya, supaya hanya ada SATU tempat yang membandingkan token dengan
`hmac.compare_digest`.

Timbangan TIDAK PERNAH memegang `KLEDO_API_KEY` (lihat `.env.example` dan
alasan di `app/services/kledo_sinkron.py`) — ia hanya memanggil dua rute ini
lewat `app/timbangan/klien_produksi.py`. Produksi dan timbangan berbagi SATU
Postgres, jadi begitu sinkron ini menulis `suppliers`/`pelanggan`, timbangan
langsung melihatnya tanpa jalur tulis apa pun di sisinya sendiri.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Header

from app.services import kledo_sinkron
from app.web.internal import _pastikan_token

router = APIRouter(prefix="/internal", tags=["internal-kledo"])
log = logging.getLogger("web.internal_kledo")


@router.get("/kledo-kontak/status")
async def kledo_kontak_status(
    x_internal_token: str | None = Header(default=None),
) -> dict:
    """Keadaan sekarang — dipanggil Timbangan tiap kali layar Pengaturannya dimuat."""
    _pastikan_token(x_internal_token)
    s = kledo_sinkron.status()
    return {
        "terkonfigurasi": s.terkonfigurasi,
        "sedang_berjalan": s.sedang_berjalan,
        "hasil_terakhir": s.hasil_terakhir,
        "gagal_terakhir": s.gagal_terakhir,
        "selesai_pada": s.selesai_pada.isoformat() if s.selesai_pada else None,
    }


@router.post("/kledo-kontak/sinkron")
async def kledo_kontak_sinkron(
    x_internal_token: str | None = Header(default=None),
) -> dict:
    """Mulai satu putaran di latar — balas SEGERA, tak menunggu selesainya.

    ~600 kontak Kledo dipanggil berhalaman-halaman; menunggunya di sini akan
    menahan permintaan HTTP Timbangan cukup lama untuk kena gateway timeout
    Railway. Hasilnya dibaca lewat `/kledo-kontak/status` sesudahnya, bukan
    dari balasan panggilan ini.
    """
    _pastikan_token(x_internal_token)
    dimulai = kledo_sinkron.mulai()
    if not dimulai:
        log.info("Sinkron kontak Kledo: permintaan dari Timbangan, sudah berjalan")
    return {"dimulai": dimulai}
